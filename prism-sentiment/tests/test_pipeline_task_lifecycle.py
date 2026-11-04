"""Tests: 采集 task 生命周期管理。"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from api.routes.collection import _running_tasks


@pytest.mark.asyncio
async def test_task_held_reference(monkeypatch):
    """触发 collect 后 _running_tasks 持有 task 引用，done 后清理。"""
    # mock _run_full_pipeline 立刻完成
    async def _fake_pipeline(vid):
        await asyncio.sleep(0.05)

    monkeypatch.setattr("api.routes.collection._run_full_pipeline", _fake_pipeline)
    # mock DB 查询返回无锁
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    from api.routes.collection import trigger_collection
    # 取一个不存在的 vid（mock 会返回 Vehicle）
    mock_vehicle = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_vehicle)

    await trigger_collection("v-test-hold", mock_session)
    # task 持有
    assert "v-test-hold" in _running_tasks, "task 引用应持有"
    # 等 done（yield 让 task 调度完成）
    await asyncio.sleep(0.2)
    assert "v-test-hold" not in _running_tasks, "done 后应清理"


@pytest.mark.asyncio
async def test_zombie_task_cancelled_on_retrigger(monkeypatch):
    """重新触发同车 collect 时取消旧 zombie task。"""
    cancelled = []
    async def _slow_pipeline(vid):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.append(vid)
            raise

    monkeypatch.setattr("api.routes.collection._run_full_pipeline", _slow_pipeline)
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_vehicle = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_vehicle)

    from api.routes.collection import trigger_collection
    await trigger_collection("v-zombie", mock_session)  # 启动旧 task
    assert "v-zombie" in _running_tasks
    await asyncio.sleep(0)  # yield 让 task1 调度
    await trigger_collection("v-zombie", mock_session)  # 重新触发应取消旧
    await asyncio.sleep(0.3)  # 等 task1 处理 CancelledError
    assert "v-zombie" in cancelled, "旧 task 应被取消"
    # 清理 task2（仍在 sleep 10s）
    t2 = _running_tasks.pop("v-zombie", None)
    if t2 and not t2.done():
        t2.cancel()
        try:
            await t2
        except asyncio.CancelledError:
            pass


def test_phase_stale_ttl():
    """30min 旧 phase 视为 stale；无时间戳向后兼容不 stale。"""
    from datetime import datetime, timedelta
    from api.pipeline_state import _is_phase_stale
    fresh = {"phase": "collecting", "_updated_at": datetime.now()}
    stale = {"phase": "collecting", "_updated_at": datetime.now() - timedelta(minutes=31)}
    no_ts = {"phase": "collecting"}  # 旧数据无时间戳
    assert not _is_phase_stale(fresh), "fresh 不应 stale"
    assert _is_phase_stale(stale), "31min 旧应 stale"
    assert not _is_phase_stale(no_ts), "无时间戳向后兼容不 stale（_run_full_pipeline 现在都设 _updated_at，zombie 30min 后 stale）"


@pytest.mark.asyncio
async def test_get_status_db_priority(monkeypatch):
    """DB completed 时返回 completed，即使内存 dict 是 calculating（zombie）。"""
    from datetime import datetime
    from api.pipeline_state import pipeline_phases
    # 内存残留 calculating（zombie）
    pipeline_phases["v-db-test"] = {"phase": "calculating", "_updated_at": datetime.now()}

    # mock DB 返回 completed + is_running=False
    mock_session = MagicMock()
    mock_status = MagicMock()
    mock_status.status = "completed"
    mock_status.is_running = False
    mock_status.posts_collected = 100
    mock_status.error_message = None
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=mock_status)
    mock_result.scalars = MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_status)))
    mock_analyzed_result = MagicMock()
    mock_analyzed_result.scalar = MagicMock(return_value=95)
    async def _execute(stmt, *a, **kw):
        # CollectionStatus 查询返回 mock_status，AnalyzedPost 计数返回 95
        if "collection_status" in str(stmt).lower() or "CollectionStatus" in str(stmt):
            return mock_result
        return mock_analyzed_result
    mock_session.execute = AsyncMock(side_effect=_execute)

    from api.routes.collection import get_pipeline_status
    r = await get_pipeline_status("v-db-test", mock_session)
    assert r["phase"] == "completed", f"DB completed 应优先，实际 {r['phase']}"
    assert r["posts_collected"] == 100
    # 清理
    pipeline_phases.pop("v-db-test", None)
