"""Tests: GET /api/fleet/status 全局采集活动状态。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta


@pytest.mark.asyncio
async def test_fleet_status_无运行():
    """全 is_running=False → is_running=false。"""
    from api.routes.fleet import get_fleet_status

    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("api.routes.fleet.datetime") as mock_dt:
        mock_dt.now.return_value = datetime.now()
        result = await get_fleet_status(mock_session)

    assert result["is_running"] is False
    assert result["in_progress_count"] == 0


@pytest.mark.asyncio
async def test_fleet_status_有运行():
    """1 车 is_running=True lock_acquired_at=now → in_progress_count=1。"""
    from api.routes.fleet import get_fleet_status
    from models.schemas import Vehicle, CollectionStatus

    now = datetime.now()
    from models.schemas import Vehicle, CollectionStatus
    mock_vehicle = Vehicle(id="v1", name="车A", brand="测试", status="active")
    mock_cs = MagicMock()
    mock_cs.is_running = True
    mock_cs.lock_acquired_at = now
    mock_cs.last_collected_at = now

    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [(mock_vehicle, mock_cs)]
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("api.routes.fleet.pipeline_phases", {"v1": {"phase": "collecting"}}):
        with patch("api.routes.fleet.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.timedelta = timedelta
            result = await get_fleet_status(mock_session)

    assert result["is_running"] is True
    assert result["in_progress_count"] == 1
    assert result["vehicles"][0]["name"] == "车A"


@pytest.mark.asyncio
async def test_fleet_status_脏锁不计入():
    """P1-2：is_running=True 但 lock_acquired_at 超 30min → 不计入。"""
    from api.routes.fleet import get_fleet_status

    now = datetime.now()
    stale_lock = now - timedelta(minutes=31)
    mock_vehicle = MagicMock(id="v1", name="车A", status="active")
    mock_cs = MagicMock()
    mock_cs.is_running = True
    mock_cs.lock_acquired_at = stale_lock  # 超 30min
    mock_cs.last_collected_at = stale_lock

    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [(mock_vehicle, mock_cs)]
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("api.routes.fleet.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.timedelta = timedelta
        result = await get_fleet_status(mock_session)

    # 脏锁不计入
    assert result["is_running"] is False
    assert result["in_progress_count"] == 0


@pytest.mark.asyncio
async def test_fleet_status_无cs的active车跳过():
    """active 车无 CollectionStatus（outerjoin None）→ 跳过。"""
    from api.routes.fleet import get_fleet_status

    mock_vehicle = MagicMock(id="v1", name="车A", status="active")
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [(mock_vehicle, None)]  # cs=None
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("api.routes.fleet.datetime") as mock_dt:
        mock_dt.now.return_value = datetime.now()
        mock_dt.timedelta = timedelta
        result = await get_fleet_status(mock_session)

    assert result["in_progress_count"] == 0
