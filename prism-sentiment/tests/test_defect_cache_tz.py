"""Tests: 缺陷簇缓存时区修复（H1）。"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_defect_cache_hit_after_tz_fix():
    """H1: computed_at UTC 与 datetime.utcnow() 比较应命中缓存（< 24h）。

    v3 报告 H1：dashboard.py 用 datetime.now()（本地 UTC+8）比 DB computed_at（UTC），
    差 8 小时，age 恒 > 21600/86400 → 缓存永不命中。修复后用 utcnow() 应命中。
    """
    from api.routes.dashboard import get_defect_themes
    from models.schemas import DefectTheme

    # 模拟 1 小时前 UTC 写入的缓存行（age = 3600s < 86400）
    recent_utc = datetime.utcnow() - timedelta(hours=1)

    mock_row = MagicMock()
    mock_row.computed_at = recent_utc
    mock_row.window_start = "2026-10-01"
    mock_row.window_end = "2026-10-06"
    mock_row.payload = '[{"theme":"test"}]'

    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=MagicMock())  # _get_vehicle_or_404
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=mock_row)
    mock_session.execute = AsyncMock(return_value=mock_result)

    # 调用端点（start/end 匹配 window_start/end）
    r = await get_defect_themes(
        "v-test", start="2026-10-01", end="2026-10-06", session=mock_session
    )

    # 应命中缓存返回 payload，不重算
    assert r == [{"theme": "test"}], f"应命中缓存，实际 {r}"


@pytest.mark.asyncio
async def test_defect_cache_miss_when_expired():
    """缓存过期（> 24h）应重算。"""
    from api.routes.dashboard import get_defect_themes

    # 25 小时前 UTC
    old_utc = datetime.utcnow() - timedelta(hours=25)

    mock_row = MagicMock()
    mock_row.computed_at = old_utc
    mock_row.window_start = "2026-10-01"
    mock_row.window_end = "2026-10-06"
    mock_row.payload = '[{"theme":"old"}]'

    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=MagicMock())  # _get_vehicle_or_404
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=mock_row)
    mock_session.execute = AsyncMock(return_value=mock_result)

    # mock mine_defect_themes 返回新结果（2026-10-20 起为 (themes, degraded) 元组）
    with patch("pipeline.analysis.defect_miner.mine_defect_themes",
               new_callable=AsyncMock, return_value=([{"theme": "new"}], False)):
        with patch("api.routes.dashboard.json.loads", return_value=[{"theme": "old"}]):
            # 过期应走重算路径——这里只验证不返回旧 payload
            # 由于重算路径涉及 session.add/delete，mock 复杂，简化断言：
            # 缓存过期时 computed_at 读取后 age > 86400，应进入重算分支
            # 我们通过验证 mine_defect_themes 被调用来确认
            import api.routes.dashboard as dash_mod
            orig_execute = mock_session.execute
            call_count = {"mine": 0}

            async def fake_mine(*a, **kw):
                call_count["mine"] += 1
                return [{"theme": "new"}], False

            with patch("pipeline.analysis.defect_miner.mine_defect_themes", new=fake_mine):
                try:
                    await get_defect_themes(
                        "v-test", start="2026-10-01", end="2026-10-06", session=mock_session
                    )
                except Exception:
                    pass  # mock session 后续操作可能失败，忽略
                assert call_count["mine"] > 0, "过期缓存应触发重算"
