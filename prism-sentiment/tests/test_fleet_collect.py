"""Tests: 全车增量采集端点（fleet.py）。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date


@pytest.mark.asyncio
async def test_fleet_collect_频率分层():
    """全车采集按频率分层返回 started/skipped。"""
    from api.routes.fleet import trigger_fleet_collect

    # 用真实 Vehicle 对象避免 MagicMock .id 属性问题
    from models.schemas import Vehicle
    mock_vehicles = [Vehicle(id="v1", name="车A", brand="测试", status="active"),
                     Vehicle(id="v2", name="车B", brand="测试", status="active")]

    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_vehicles
    mock_session.execute = AsyncMock(return_value=mock_result)

    # v1=200 hot（每天都跑），v2=0 cold（非周一跳过）
    # patch fleet 模块里的 recent_post_counts 引用（from import 后的绑定）
    with patch("api.routes.fleet.recent_post_counts", return_value={"v1": 200, "v2": 0}):
        with patch("api.routes.collection.trigger_collection", new_callable=AsyncMock, return_value={"status": "started"}):
            class _S:
                async def __aenter__(self): return MagicMock()
                async def __aexit__(self, *a): return None
            with patch("api.routes.fleet.async_session", return_value=_S()):
                result = await trigger_fleet_collect(mock_session)

    assert "started" in result
    assert "skipped" in result
    # v1=200 hot 应进 started
    assert "v1" in result["started"], f"v1 hot 应进 started，实际 {result['started']}"
    # v2=0 cold 非周一应进 skipped（除非今天是周一）
    if date.today().weekday() != 0:
        assert any(s["name"] == "车B" for s in result["skipped"])


@pytest.mark.asyncio
async def test_fleet_collect_无active车():
    """无 active 车时 started/skipped 都空。"""
    from api.routes.fleet import trigger_fleet_collect

    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("pipeline.frequency.recent_post_counts", return_value={}):
        result = await trigger_fleet_collect(mock_session)

    assert result["started"] == []
    assert result["skipped"] == []
