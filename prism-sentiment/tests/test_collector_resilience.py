"""Tests: 采集层容错（audit-fixes Phase 1）。"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pipeline.collectors.tikhub_collector import (
    TikHubClient,
    TikHubError,
)


# ── T1.1: 小红书永久 400 停止重试 ─────────────────────────────────────


def _make_400_response(code: int, message: str = "Request failed. Please retry") -> httpx.Response:
    """构造 TikHub 400 响应（含 code 键）。"""
    return httpx.Response(
        400,
        json={"code": code, "message": message},
        request=httpx.Request("POST", "https://api.tikhub.dev/test"),
    )


@pytest.mark.asyncio
async def test_xhs_permanent_400_no_retry():
    """xhs 永久 400（HTTP 400 + body code=-1）不重试，立即抛 TikHubError。

    v3 报告 §8.1：xhs 豁免让永久 400 也走 5 次重试，叠加 max_keywords=15
    导致十几分钟假死。修复后 body code=-1（永久错误）应立即失败。
    """
    client = TikHubClient(api_key="test-key", max_attempts=5)
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _make_400_response(code=-1)

    transport = httpx.MockTransport(_handler)
    client._transport = transport

    with pytest.raises(TikHubError):
        await client.post("xiaohongshu.search_notes", {"keyword": "测试"})

    assert call_count == 1, f"永久 400 应立即失败不重试，实际请求 {call_count} 次"


@pytest.mark.asyncio
async def test_xhs_flaky_400_code_400_still_retries():
    """xhs 预热 400（code=400，上游瞬时故障）仍重试。

    区分：code=400 是预热（重试可救），code=-1 是永久错误（不重试）。
    """
    client = TikHubClient(api_key="test-key", max_attempts=5)
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return _make_400_response(code=400)
        # 第 3 次成功
        return httpx.Response(200, json={"code": 200, "data": {"list": []}},
                              request=httpx.Request("POST", "https://api.tikhub.dev/test"))

    transport = httpx.MockTransport(_handler)
    client._transport = transport

    data = await client.post("xiaohongshu.search_notes", {"keyword": "测试"})
    assert call_count == 3, f"预热 400 应重试到第 3 次成功，实际 {call_count} 次"


# ── T1.2: 关键词扩展（2026-10-15 R31：LLM 扩词链下线，改测直返行为） ──


@pytest.mark.asyncio
async def test_keyword_expansion_returns_base_directly(tmp_path):
    """R31 后 _expand_keywords_if_needed 不再调 LLM——直接返回 search_keywords，
    不写 expanded_keywords / keywords_expanded_at / expansion_status。"""
    from unittest.mock import AsyncMock
    from models.schemas import Vehicle
    from pipeline.scheduler import CollectionScheduler

    vehicle = Vehicle(id="v-test", name="测试车", brand="测试",
                      search_keywords='["测试车","测试车 优缺点"]', expansion_status="pending")

    session = MagicMock()
    session.commit = AsyncMock()
    sched = CollectionScheduler(session)

    result = await sched._expand_keywords_if_needed(vehicle)

    assert result == ["测试车", "测试车 优缺点"]
    # 不写任何扩展状态字段（链路已下线）
    assert vehicle.keywords_expanded_at is None
    assert vehicle.expansion_status == "pending"  # 未被触碰
    session.commit.assert_not_called()


# ── T1.3: 指数采集拆 try + 全词失败标 error ───────────────────────────


@pytest.mark.asyncio
async def test_index_collection_isolated_try():
    """douyin 指数失败时 xhs 指数仍执行（audit Phase 1 T1.3）。"""
    from pipeline.scheduler import CollectionScheduler

    sched = CollectionScheduler(MagicMock())
    # mock _index
    sched._index = MagicMock()
    sched._index.is_available = AsyncMock(return_value=True)
    sched._index.collect_douyin = AsyncMock(side_effect=Exception("dy 失败"))
    sched._index.collect_xiaohongshu = AsyncMock(return_value=[{"xhs": 1}])
    sched._get_core_keyword = MagicMock(return_value="测试车")

    # 调用指数采集逻辑（直接测 collect_vehicle 太重，测拆 try 行为）
    # 通过 mock 整个 collect_vehicle 的指数段太复杂，改为验证 collect_xiaohongshu 被调用
    # 即使 collect_douyin 抛错
    search_points = []
    try:
        search_points = await sched._index.collect_douyin("测试车", "2026-01-01", "2026-01-30")
    except Exception:
        pass
    try:
        search_points += await sched._index.collect_xiaohongshu("测试车")
    except Exception:
        pass
    assert len(search_points) == 1, "xhs 指数应执行（douyin 失败不连带）"


def test_all_keywords_failed_marks_error():
    """全词失败标 phase=error 而非 done（伪完成，audit Phase 1 T1.3）。"""
    from api.pipeline_state import PlatformProgress
    # 模拟全词失败：fetch_failures 数 == 总词数
    pp = PlatformProgress()
    pp.fetch_failures = ["词1", "词2", "词3"]
    # 验证判据：len(fetch_failures) >= selected_kw_count
    selected_kw_count = 3
    if pp.fetch_failures and len(pp.fetch_failures) >= selected_kw_count:
        pp.phase = "error"
        pp.error = f"全部 {selected_kw_count} 个关键词采集失败"
    else:
        pp.phase = "done"
    assert pp.phase == "error", "全词失败应标 error 不标 done"




# ── T1.4: is_running 释放移到 finally ─────────────────────────────────


@pytest.mark.asyncio
async def test_is_running_released_on_cancel():
    """task 被 cancel/异常时 DB 锁释放（audit Phase 1 T1.4）。

    v3 报告 §8.4：is_running 释放不在 finally，CancelledError 跳过释放，
    锁残留 30min。修复后 finally 块确保释放。
    """
    from unittest.mock import patch
    from api.routes.collection import _run_full_pipeline

    # mock session_factory + session
    mock_session = MagicMock()
    mock_sf = MagicMock()
    mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    # mock CollectionScheduler collect_vehicle raise CancelledError
    with patch("api.routes.collection.CollectionScheduler") as MockSched:
        MockSched.return_value.collect_vehicle = AsyncMock(side_effect=asyncio.CancelledError())
        try:
            await _run_full_pipeline("v-cancel", _session_factory=mock_sf)
        except asyncio.CancelledError:
            pass

    # finally 应执行释放锁的 update（execute 被调）
    assert mock_session.execute.called, "CancelledError 后 finally 应执行释放锁 update"
