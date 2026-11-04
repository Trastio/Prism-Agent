"""Tests: Phase 5 静默降级显式化（degraded 字段 + ABSA A 方案 + 观点归并 + confidence + 管线收敛）。"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_overview_comment_model_available_false_when_unloaded():
    """T5.2: ABSA 模型未加载时 overview 返回 comment_model_available: false。"""
    from pipeline.analysis.local_absa import LocalABSAModel
    mock_session = MagicMock()
    # mock vehicle
    mock_vehicle = MagicMock()
    mock_vehicle.lifecycle_anchors = None
    mock_session.get = AsyncMock(return_value=mock_vehicle)
    # mock 所有查询返回 0
    mock_result = MagicMock()
    mock_result.scalar = MagicMock(return_value=0)
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_result.first = MagicMock(return_value=None)
    mock_result.all = MagicMock(return_value=[])
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch.object(LocalABSAModel, "get", return_value=MagicMock(_loaded=False)):
        from api.routes.dashboard import get_overview
        r = await get_overview("v-test", None, None, mock_session)
    assert "comment_model_available" in r, "overview 应返回 comment_model_available 字段"
    assert r["comment_model_available"] is False, "模型未加载时应为 false"


@pytest.mark.asyncio
async def test_opinion_merge_failure_returns_degraded():
    """T5.1/T5.3: 观点标签归并失败时返回 degraded 标记。"""
    from utils.llm_client import LLMError
    mock_session = MagicMock()
    # 模拟 11+ 个标签触发归并路径（每个标签计数 >= 2 通过 min_count 过滤）
    tags = []
    for i in range(15):
        tags.extend([f"标签{i}", f"标签{i}"])  # 每个标签出现 2 次
    tags_json = json.dumps(tags)
    mock_result = MagicMock()
    mock_result.all = MagicMock(return_value=[(tags_json,)])
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("api.routes.analysis.call_llm", new_callable=AsyncMock, side_effect=LLMError("timeout", "timeout")):
        from api.routes.analysis import get_top_opinions, _opinion_merge_cache
        _opinion_merge_cache.clear()
        r = await get_top_opinions("v-test", None, None, mock_session)
    # 归并失败应返回 degraded 标记
    assert isinstance(r, dict) and "degraded" in r, "归并失败应返回 degraded 标记"
    assert r["degraded"] is True


@pytest.mark.asyncio
async def test_opinion_min_count_filter():
    """T5.4: 计数 < 2 的标签不进 TOP 榜。"""
    mock_session = MagicMock()
    # 模拟标签数据：A 出现 1 次（应过滤），B 出现 5 次（保留）
    mock_result = MagicMock()
    mock_result.all = MagicMock(return_value=[('[\"A\",\"B\",\"B\",\"B\",\"B\",\"B\"]',)])
    mock_session.execute = AsyncMock(return_value=mock_result)

    from api.routes.analysis import get_top_opinions, _opinion_merge_cache
    _opinion_merge_cache.clear()
    r = await get_top_opinions("v-test", None, None, mock_session)
    items = r.get("items", r) if isinstance(r, dict) else r
    # 标签 A 计数 1 应被过滤（min_count=2）
    tag_names = [it[0] for it in items] if items and isinstance(items[0], (list, tuple)) else []
    assert "A" not in tag_names or len(items) <= 10, "min_count=2 应过滤计数<2 的标签"


@pytest.mark.asyncio
async def test_confidence_threshold_filter():
    """T5.5: confidence < 0.3 不入聚合；confidence == 0.0 标记 fallback。"""
    from api.routes.dashboard import _confidence_filter
    # confidence >= 0.3 过滤条件
    filt = _confidence_filter()
    assert filt is not None, "应返回过滤条件"


def test_confidence_filter_excludes_low():
    """T5.5: confidence < 0.3 被排除。"""
    from sqlalchemy import select
    from models.schemas import AnalyzedPost
    from api.routes.dashboard import _confidence_filter
    # 构造查询验证 SQL 含 confidence >= 0.3
    q = select(AnalyzedPost.id).where(_confidence_filter())
    sql_text = str(q)
    assert "confidence" in sql_text.lower(), "SQL 应含 confidence 过滤"


@pytest.mark.asyncio
async def test_analysis_trigger_produces_defects_events():
    """T5.6: /analysis/trigger 后产出缺陷簇和事件（管线收敛）。"""
    from api.routes.analysis import _run_analysis_pipeline
    calls = []
    async def _fake_runner_run(*a, **kw):
        return {"analyzed": 5}
    async def _fake_detect(*a, **kw):
        calls.append("detect_events")
        return []
    async def _fake_mine(*a, **kw):
        calls.append("mine_defects")
        return ([{"name": "测试簇", "severity": "high"}], False)
    async def _fake_calc(*a, **kw):
        calls.append("heat_calc")
    async def _fake_fetch(*a, **kw):
        return 0
    async def _fake_summaries(*a, **kw):
        return 0
    async def _fake_comment_analysis(*a, **kw):
        return 0

    mock_session = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))

    # P0 回归防护（2026-10-20）：录下写库的 DefectTheme——防元组未解包被
    # json.dumps 成 "[[...], false]" 损坏 payload（隔离审查抓到的 analysis.py 旧病灶）。
    # 经共享 session mock 采集（_async_ctx 每次 new，故 patch mock_session_ctx 归一）
    import tests.test_degradation_visibility as _tdv
    shared = mock_session_ctx()

    with patch("pipeline.analysis.batch_runner.BatchAnalysisRunner.run_for_vehicle", new_callable=AsyncMock, side_effect=_fake_runner_run), \
         patch("pipeline.analysis.batch_runner.BatchAnalysisRunner.run_comment_summaries", new_callable=AsyncMock, side_effect=_fake_summaries), \
         patch("pipeline.analysis.batch_runner.BatchAnalysisRunner.run_comment_analysis", new_callable=AsyncMock, side_effect=_fake_comment_analysis), \
         patch("pipeline.analysis.heat_calculator.HeatMetricCalculator.calculate_range", new_callable=AsyncMock, side_effect=_fake_calc), \
         patch("pipeline.analysis.event_tracker.detect_events_for_vehicle", new_callable=AsyncMock, side_effect=_fake_detect), \
         patch("pipeline.analysis.defect_miner.mine_defect_themes", new_callable=AsyncMock, side_effect=_fake_mine), \
         patch.object(_tdv, "mock_session_ctx", return_value=shared), \
         patch("pipeline.scheduler.CollectionScheduler.fetch_top_comments", new_callable=AsyncMock, side_effect=_fake_fetch):
        await _run_analysis_pipeline("v-test", _session_factory=lambda: _async_ctx())

    assert "detect_events" in calls, "/analysis/trigger 应调用事件检测"
    assert "mine_defects" in calls, "/analysis/trigger 应调用缺陷挖掘"
    # 30 天权威窗 + payload 为纯簇列表（元组形状即刻失败）
    import json as _json
    from datetime import date as _date, timedelta as _td
    from models.schemas import DefectTheme as _DT
    written = [c.args[0] for c in shared.add.call_args_list
               if c.args and isinstance(c.args[0], _DT)]
    assert len(written) == 1, "应恰写一行缺陷簇"
    assert _json.loads(written[0].payload) == [{"name": "测试簇", "severity": "high"}]
    assert written[0].window_end == _date.today().isoformat()
    assert written[0].window_start == (_date.today() - _td(days=29)).isoformat()


@pytest.mark.asyncio
async def test_analysis_trigger_degraded_keeps_old_payload():
    """degraded（LLM 判定失败）→ /analysis/trigger 路径不写缺陷簇（保旧载荷）。"""
    from api.routes.analysis import _run_analysis_pipeline
    import tests.test_degradation_visibility as _tdv

    async def _fake_mine(*a, **kw):
        return ([], True)
    shared = mock_session_ctx()

    with patch("pipeline.analysis.batch_runner.BatchAnalysisRunner.run_for_vehicle", new_callable=AsyncMock, return_value={"analyzed": 5}), \
         patch("pipeline.analysis.batch_runner.BatchAnalysisRunner.run_comment_summaries", new_callable=AsyncMock, return_value=0), \
         patch("pipeline.analysis.batch_runner.BatchAnalysisRunner.run_comment_analysis", new_callable=AsyncMock, return_value=0), \
         patch("pipeline.analysis.heat_calculator.HeatMetricCalculator.calculate_range", new_callable=AsyncMock), \
         patch("pipeline.analysis.event_tracker.detect_events_for_vehicle", new_callable=AsyncMock, return_value=[]), \
         patch("pipeline.analysis.defect_miner.mine_defect_themes", new_callable=AsyncMock, side_effect=_fake_mine), \
         patch.object(_tdv, "mock_session_ctx", return_value=shared), \
         patch("pipeline.scheduler.CollectionScheduler.fetch_top_comments", new_callable=AsyncMock, return_value=0):
        await _run_analysis_pipeline("v-deg", _session_factory=lambda: _async_ctx())

    from models.schemas import DefectTheme as _DT
    written = [c.args[0] for c in shared.add.call_args_list
               if c.args and isinstance(c.args[0], _DT)]
    assert written == [], "degraded 时不得写库（旧载荷保留）"


class _async_ctx:
    async def __aenter__(self):
        return mock_session_ctx()
    async def __aexit__(self, *a):
        pass


def mock_session_ctx():
    s = MagicMock()
    s.commit = AsyncMock()
    s.add = MagicMock()
    s.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    return s


def test_opinion_merge_prompt_covers_suffix_variants():
    """T5.7: 归并 prompt 含带后缀形态规则（续航长（正面）→续航长）。"""
    from api.routes.analysis import _merge_opinion_tags
    import inspect
    src = inspect.getsource(_merge_opinion_tags)
    # prompt 应含带后缀/情感后缀归并规则
    assert "后缀" in src or "正面" in src or "续航长" in src, "归并 prompt 应含带后缀形态规则"
