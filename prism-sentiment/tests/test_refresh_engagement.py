"""Tests: 单车互动刷新端点（refresh-engagement）。"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta


@pytest.mark.asyncio
async def test_refresh_写_collection_status_is_running():
    """P1-2：refresh 触发时写 CollectionStatus.is_running=True。"""
    from api.routes.collection import trigger_refresh_engagement

    mock_session = MagicMock()
    mock_vehicle = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_vehicle)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    with patch("api.routes.collection._run_refresh_pipeline", new_callable=AsyncMock):
        with patch("api.routes.collection.pipeline_phases", {}):
            with patch("api.routes.collection.pipeline_progress", {}):
                with patch("api.routes.collection.PipelineProgress"):
                    result = await trigger_refresh_engagement("v1", mock_session)

    assert result["status"] == "started"
    assert result["phase"] == "refreshing"


@pytest.mark.asyncio
async def test_refresh_已运行返回_already_running():
    """P1-C：refresh 相位运行中时返回 already_running。"""
    from api.routes.collection import trigger_refresh_engagement

    mock_session = MagicMock()
    mock_vehicle = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_vehicle)

    phase_info = {"phase": "refreshing", "_updated_at": datetime.now()}
    with patch("api.routes.collection.pipeline_phases", {"v1": phase_info}):
        result = await trigger_refresh_engagement("v1", mock_session)

    assert result["status"] == "already_running"


@pytest.mark.asyncio
async def test_refresh_stale_可逃逸():
    """P1-3：refresh 相位 stale（30min+）可逃逸，允许新触发。"""
    from api.routes.collection import trigger_refresh_engagement

    mock_session = MagicMock()
    mock_vehicle = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_vehicle)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()

    stale_phase = {"phase": "refreshing", "_updated_at": datetime.now() - timedelta(minutes=31)}
    with patch("api.routes.collection.pipeline_phases", {"v1": stale_phase}):
        with patch("api.routes.collection._run_refresh_pipeline", new_callable=AsyncMock):
            with patch("api.routes.collection.pipeline_progress", {}):
                with patch("api.routes.collection.PipelineProgress"):
                    result = await trigger_refresh_engagement("v1", mock_session)

    assert result["status"] == "started"


@pytest.mark.asyncio
async def test_run_refresh_pipeline_成功写_cs_status_completed():
    """P1-2 v7：_run_refresh_pipeline 成功时写 CollectionStatus.status='completed'。"""
    from api.routes.collection import _run_refresh_pipeline

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    execute_calls = []
    async def _track_execute(stmt, *a, **kw):
        execute_calls.append(str(stmt))
        return MagicMock()
    mock_session.execute = AsyncMock(side_effect=_track_execute)
    mock_session.commit = AsyncMock()

    with patch("api.routes.collection.async_session", return_value=mock_session):
        with patch("scripts.refresh_engagement.refresh_vehicle_engagement", new_callable=AsyncMock, return_value=5):
            with patch("pipeline.analysis.heat_calculator.HeatMetricCalculator"):
                with patch("api.routes.collection.pipeline_phases", {}):
                    from api.pipeline_state import PipelineProgress
                    with patch("api.routes.collection.pipeline_progress", {"v1": PipelineProgress()}):
                        await _run_refresh_pipeline("v1")

    # 验证成功路径写了 CollectionStatus（execute 调用含 UPDATE collection_status SET status）
    found = any("UPDATE collection_status SET status" in c for c in execute_calls)
    assert found, f"成功应写 cs.status，execute calls: {execute_calls}"


@pytest.mark.asyncio
async def test_run_refresh_pipeline_失败写_cs_status_error():
    """P1-2 v7：_run_refresh_pipeline 失败时写 CollectionStatus.status='error'。"""
    from api.routes.collection import _run_refresh_pipeline

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    execute_calls = []
    async def _track_execute(stmt, *a, **kw):
        execute_calls.append(str(stmt))
        return MagicMock()
    mock_session.execute = AsyncMock(side_effect=_track_execute)
    mock_session.commit = AsyncMock()

    with patch("api.routes.collection.async_session", return_value=mock_session):
        with patch("scripts.refresh_engagement.refresh_vehicle_engagement", new_callable=AsyncMock, side_effect=Exception("TikHub 403")):
            with patch("pipeline.analysis.heat_calculator.HeatMetricCalculator"):
                with patch("api.routes.collection.pipeline_phases", {}):
                    from api.pipeline_state import PipelineProgress
                    with patch("api.routes.collection.pipeline_progress", {"v1": PipelineProgress()}):
                        await _run_refresh_pipeline("v1")

    # 验证失败路径写了 CollectionStatus status=error（UPDATE collection_status SET status）
    found = any("UPDATE collection_status SET status" in c for c in execute_calls)
    assert found, f"失败应写 cs.status=error，execute calls: {execute_calls}"
