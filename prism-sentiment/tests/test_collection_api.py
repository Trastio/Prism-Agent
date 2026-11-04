"""Collection API + pipeline tests — 8 tests."""
import asyncio
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.pipeline_state import pipeline_phases
from api.routes.collection import _run_full_pipeline
from models.database import get_session
from models.schemas import Base, CollectionStatus, Vehicle


@pytest_asyncio.fixture
async def client():
    from api.main import app

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()
    pipeline_phases.clear()


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    pipeline_phases.clear()
    await engine.dispose()


async def _create_vehicle(client: AsyncClient, name: str = "海豹", brand: str = "比亚迪") -> str:
    resp = await client.post("/api/vehicles", json={"name": name, "brand": brand})
    return resp.json()["id"]


# --- API layer tests ---

async def test_trigger_collection_returns_started(client):
    vid = await _create_vehicle(client)
    with patch("api.routes.collection._run_full_pipeline", new_callable=AsyncMock):
        resp = await client.post(f"/api/vehicles/{vid}/collect")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "started"
    assert data["phase"] == "collecting"


async def test_trigger_collection_vehicle_not_found(client):
    resp = await client.post("/api/vehicles/nonexistent/collect")
    assert resp.status_code == 404


async def test_trigger_collection_already_running(client):
    vid = await _create_vehicle(client)
    pipeline_phases[vid] = {"phase": "analyzing", "posts_collected": 5, "analyzed": 0, "error": None}
    resp = await client.post(f"/api/vehicles/{vid}/collect")
    assert resp.status_code == 200
    assert resp.json()["status"] == "already_running"


async def test_pipeline_status_idle(client):
    vid = await _create_vehicle(client)
    resp = await client.get(f"/api/vehicles/{vid}/pipeline-status")
    assert resp.status_code == 200
    assert resp.json()["phase"] == "idle"


async def test_pipeline_status_active(client):
    vid = await _create_vehicle(client)
    pipeline_phases[vid] = {"phase": "collecting", "posts_collected": 0, "analyzed": 0, "error": None}
    resp = await client.get(f"/api/vehicles/{vid}/pipeline-status")
    assert resp.status_code == 200
    assert resp.json()["phase"] == "collecting"


# --- Pipeline logic tests (direct call with test session factory) ---

async def test_pipeline_collects_and_completes(db):
    async with db() as session:
        session.add(Vehicle(id="v1", name="海豹", brand="比亚迪", search_keywords='["海豹"]'))
        await session.commit()

    # 2026-10-15 R31：news 停采，注入通道换社媒（douyin），类级放行 resolve_collector
    with patch("pipeline.scheduler.CollectionScheduler._collect_social_platform",
              new_callable=AsyncMock, return_value=([
        # 标题带品牌 token（过品牌过滤）+ 相对日期（过采集窗口 floor，固定日期会滚出窗口）
        {"title": "海豹测试", "content": "内容", "url": "https://ex.com/1",
         "source": "tikhub", "platform": "douyin",
         "published_at": (date.today() - timedelta(days=5)).isoformat()},
    ], [])), patch("pipeline.scheduler.CollectionScheduler._resolve_collector",
              new_callable=AsyncMock, return_value=(object(), "tikhub")), \
         patch("pipeline.analysis.relevance_filter.RelevanceFilter.filter_vehicle",
              new_callable=AsyncMock, return_value={"total": 0, "passed": 0, "rejected_by_rules": 0, "limbo": 0, "rejected_by_llm": 0}), \
         patch("pipeline.analysis.analyzer.AnalysisPipeline.analyze_batch",
              new_callable=AsyncMock, return_value=[{
                  "sentiment": "positive", "event_tags": ["日常讨论"],
                  "opinion_tags": [], "subject": "self", "subject_name": "",
                  "dim_sentiment": {}, "confidence": 0.9}]):
        await _run_full_pipeline("v1", _session_factory=db)

    assert pipeline_phases["v1"]["phase"] == "completed"
    assert pipeline_phases["v1"]["posts_collected"] >= 1
    assert pipeline_phases["v1"]["analyzed"] >= 1


async def test_pipeline_handles_collection_error(db):
    async with db() as session:
        session.add(Vehicle(id="v2", name="秦PLUS", brand="比亚迪", search_keywords='["秦PLUS"]'))
        await session.commit()

    # 2026-10-15 R31：news 停采，错误注入换车质网阶段（无条件执行）
    with patch("pipeline.scheduler.CollectionScheduler._collect_chezhiwang", new_callable=AsyncMock, side_effect=Exception("timeout")):
        await _run_full_pipeline("v2", _session_factory=db)

    assert pipeline_phases["v2"]["phase"] == "error"


async def test_pipeline_budget_capped_not_completed(db):
    """P1-1（Step7 审查回归钉）：触顶必须以 budget_capped 终态早退——
    原实现只判 error，触顶后继续跑完 Phase 2-9 并把终态覆盖成 completed，
    daily_update 侧打出假"完成"且退出码 0，护栏事件不可见。"""
    async with db() as session:
        session.add(Vehicle(id="v9", name="测试车", brand="测试", search_keywords='["测试车"]'))
        await session.commit()

    capped_result = {"vehicle_id": "v9", "status": "budget_capped",
                     "posts_collected": 0, "error": "当日 TikHub 调用数 2200 已超预算"}
    with patch("pipeline.scheduler.CollectionScheduler.collect_vehicle",
               new_callable=AsyncMock, return_value=capped_result):
        await _run_full_pipeline("v9", _session_factory=db)

    assert pipeline_phases["v9"]["phase"] == "budget_capped"  # 不得是 completed


async def test_pipeline_deduplicates_posts(db):
    async with db() as session:
        session.add(Vehicle(id="v3", name="汉", brand="比亚迪", search_keywords='["汉"]'))
        await session.commit()

    # 2026-10-15 R31：news 停采，注入通道换社媒（douyin）
    posts = [
        # 标题带品牌 token：品牌过滤（采集层竞品根治）会丢掉不含 token 的帖
        {"title": "比亚迪汉A", "content": "c1", "url": "https://ex.com/1",
         "source": "tikhub", "platform": "douyin",
         "published_at": (date.today() - timedelta(days=5)).isoformat()},
        {"title": "比亚迪汉dup", "content": "c2", "url": "https://ex.com/1",
         "source": "tikhub", "platform": "douyin",
         "published_at": (date.today() - timedelta(days=5)).isoformat()},
    ]
    with patch("pipeline.scheduler.CollectionScheduler._collect_social_platform", new_callable=AsyncMock, return_value=(posts, [])), \
         patch("pipeline.scheduler.CollectionScheduler._resolve_collector", new_callable=AsyncMock, return_value=(object(), "tikhub")):
        await _run_full_pipeline("v3", _session_factory=db)

    assert pipeline_phases["v3"]["posts_collected"] == 1


async def test_pipeline_phase9_engagement_refresh_invoked_and_failure_tolerated(db):
    """Phase 9：/collect 触发也刷新互动数；刷新失败不断管线。"""
    async with db() as session:
        session.add(Vehicle(id="ver", name="海豹", brand="比亚迪", search_keywords='["海豹"]'))
        await session.commit()

    with patch("pipeline.scheduler.CollectionScheduler._collect_news", new_callable=AsyncMock, return_value=[
        {"title": "海豹测试", "content": "内容", "url": "https://ex.com/1",
         "source": "news", "platform": "news",
         "published_at": (date.today() - timedelta(days=5)).isoformat()},
    ]), patch("pipeline.scheduler.CollectionScheduler._collect_social_platform",
              new_callable=AsyncMock, return_value=([], [])), \
         patch("pipeline.analysis.relevance_filter.RelevanceFilter.filter_vehicle",
               new_callable=AsyncMock, return_value={"total": 0, "passed": 0, "rejected_by_rules": 0, "limbo": 0, "rejected_by_llm": 0}), \
         patch("pipeline.analysis.analyzer.AnalysisPipeline.analyze_batch",
               new_callable=AsyncMock, return_value=[{
                   "sentiment": "positive", "event_tags": ["日常讨论"],
                   "opinion_tags": [], "subject": "self", "subject_name": "",
                   "dim_sentiment": {}, "confidence": 0.9}]), \
         patch("scripts.refresh_engagement.refresh_vehicle_engagement",
               new_callable=AsyncMock, side_effect=RuntimeError("tikhub down")) as mock_refresh:
        await _run_full_pipeline("ver", _session_factory=db)

    assert mock_refresh.await_count == 1  # /collect 触发也刷新互动数
    assert pipeline_phases["ver"]["phase"] == "completed"


async def test_pipeline_phase8_persists_defect_themes(db):
    """Phase 8：mine_defect_themes 结果落库 defect_themes 表（全量覆盖）。"""
    import json
    from sqlalchemy import select
    from models.schemas import DefectTheme

    async with db() as session:
        session.add(Vehicle(id="vp", name="海豹", brand="比亚迪", search_keywords='["海豹"]'))
        await session.commit()

    fixed_clusters = [{"name": "刹车异响", "severity": "high", "suggestion": "排查",
                       "comments": 10, "posts": ["p1", "p2"], "neg_ratio": 0.9,
                       "rep_comments": [], "keywords": ["刹车", "异响"]}]

    with patch("pipeline.scheduler.CollectionScheduler._collect_news", new_callable=AsyncMock, return_value=[
        {"title": "海豹测试", "content": "内容", "url": "https://ex.com/1",
         "source": "news", "platform": "news",
         "published_at": (date.today() - timedelta(days=5)).isoformat()},
    ]), patch("pipeline.scheduler.CollectionScheduler._collect_social_platform",
              new_callable=AsyncMock, return_value=([], [])), \
         patch("pipeline.analysis.relevance_filter.RelevanceFilter.filter_vehicle",
               new_callable=AsyncMock, return_value={"total": 0, "passed": 0, "rejected_by_rules": 0, "limbo": 0, "rejected_by_llm": 0}), \
         patch("pipeline.analysis.analyzer.AnalysisPipeline.analyze_batch",
               new_callable=AsyncMock, return_value=[{
                   "sentiment": "positive", "event_tags": ["日常讨论"],
                   "opinion_tags": [], "subject": "self", "subject_name": "",
                   "dim_sentiment": {}, "confidence": 0.9}]), \
         patch("pipeline.analysis.defect_miner.mine_defect_themes",
               new_callable=AsyncMock, return_value=(fixed_clusters, False)):
        await _run_full_pipeline("vp", _session_factory=db)

    assert pipeline_phases["vp"]["phase"] == "completed"
    # 落库验证：一行，payload=完整簇列表 JSON
    # （注：Phase 8 设置的 defect_themes 计数会被 completed dict 覆盖，
    # 与 comments_analyzed 同模式——以 DB 落库为落库证据，不查 phase dict）
    async with db() as session:
        rows = (await session.execute(
            select(DefectTheme).where(DefectTheme.vehicle_id == "vp")
        )).scalars().all()
        assert len(rows) == 1
        assert json.loads(rows[0].payload) == fixed_clusters
        # 2026-10-20 权威窗：window = 今天−29 ~ 今天（不再吃采集管线的 90 天窗）
        from datetime import date as _date, timedelta as _td
        assert rows[0].window_end == _date.today().isoformat()
        assert rows[0].window_start == (_date.today() - _td(days=29)).isoformat()


async def test_pipeline_phase8_degraded_keeps_old_payload(db):
    """Phase 8 degraded（LLM 判定失败）→ 保旧载荷不覆盖（2026-10-20，T11 实证路径）。"""
    import json
    from sqlalchemy import select
    from models.schemas import DefectTheme

    async with db() as session:
        session.add(Vehicle(id="vd", name="海豹2", brand="比亚迪", search_keywords='["海豹2"]'))
        # 预置旧载荷（好数据）
        session.add(DefectTheme(id="dt-old", vehicle_id="vd",
                                payload=json.dumps([{"name": "旧簇"}]),
                                window_start="2026-10-01", window_end="2026-10-30"))
        await session.commit()

    with patch("pipeline.scheduler.CollectionScheduler._collect_news", new_callable=AsyncMock, return_value=[
        {"title": "海豹测试", "content": "内容", "url": "https://ex.com/1",
         "source": "news", "platform": "news",
         "published_at": (date.today() - timedelta(days=5)).isoformat()},
    ]), patch("pipeline.scheduler.CollectionScheduler._collect_social_platform",
              new_callable=AsyncMock, return_value=([], [])), \
         patch("pipeline.analysis.relevance_filter.RelevanceFilter.filter_vehicle",
               new_callable=AsyncMock, return_value={"total": 0, "passed": 0, "rejected_by_rules": 0, "limbo": 0, "rejected_by_llm": 0}), \
         patch("pipeline.analysis.analyzer.AnalysisPipeline.analyze_batch",
               new_callable=AsyncMock, return_value=[{
                   "sentiment": "positive", "event_tags": ["日常讨论"],
                   "opinion_tags": [], "subject": "self", "subject_name": "",
                   "dim_sentiment": {}, "confidence": 0.9}]), \
         patch("pipeline.analysis.defect_miner.mine_defect_themes",
               new_callable=AsyncMock, return_value=([], True)):  # LLM 失败信号
        await _run_full_pipeline("vd", _session_factory=db)

    assert pipeline_phases["vd"]["phase"] == "completed"
    async with db() as session:
        rows = (await session.execute(
            select(DefectTheme).where(DefectTheme.vehicle_id == "vd")
        )).scalars().all()
        assert len(rows) == 1  # 旧行未被删除覆盖
        assert json.loads(rows[0].payload) == [{"name": "旧簇"}]


async def test_trigger_collection_idle_cs_returns_started(db):
    """P0 回归：已有 cs 行且 is_running=False → started（非 UnboundLocalError）。

    复现风云T9L 故障路径：collection_status 存在 source='all' 行、is_running=False、
    pipeline_phases 无活跃 phase（非 already_running）。
    修复前 trigger_collection 在此路径抛 UnboundLocalError(datetime)。
    """
    from api.routes.collection import trigger_collection
    async with db() as session:
        session.add(Vehicle(id="vidle", name="风云T9L", brand="奇瑞",
                            search_keywords='["风云T9L"]'))
        session.add(CollectionStatus(vehicle_id="vidle", source="all", mode="initial",
                                     is_running=False, status="completed"))
        await session.commit()
        pipeline_phases.pop("vidle", None)  # 确保不进 already_running 分支
        with patch("api.routes.collection._run_full_pipeline", new_callable=AsyncMock):
            result = await trigger_collection("vidle", session)
    assert result["status"] == "started"


# --- 审计 P1 回归（2026-10-07 audit-p1-followups）---

async def test_full_pipeline_fetches_comments_before_summaries(db):
    """审计 P1-2：_run_full_pipeline 应在 run_comment_summaries 前调 fetch_top_comments。

    与 test_analysis_api::test_pipeline_calls_fetch_top_comments_before_summaries
    （分析管线）同契约：两者选同一批帖，补抓先行则摘要/ABSA 当轮覆盖完整评论。
    """
    async with db() as session:
        session.add(Vehicle(id="vord", name="海豹", brand="比亚迪", search_keywords='["海豹"]'))
        await session.commit()

    call_order = []

    async def fake_fetch(self, vid):
        call_order.append("fetch_top_comments")
        return 0

    async def fake_summaries(self, vid):
        call_order.append("run_comment_summaries")
        return 0

    with patch("pipeline.scheduler.CollectionScheduler._collect_news", new_callable=AsyncMock, return_value=[]), \
         patch("pipeline.scheduler.CollectionScheduler._collect_social_platform",
               new_callable=AsyncMock, return_value=([], [])), \
         patch("pipeline.scheduler.CollectionScheduler.fetch_top_comments", fake_fetch), \
         patch("pipeline.analysis.batch_runner.BatchAnalysisRunner.run_comment_summaries", fake_summaries):
        await _run_full_pipeline("vord", _session_factory=db)

    assert call_order.index("fetch_top_comments") < call_order.index("run_comment_summaries")


async def test_collecting_phase_carries_updated_at(db):
    """审计 P1-1：采集阶段 pipeline_phases 带 _updated_at（30min stale 逃逸的前提）。

    回归背景：scheduler.py 原写 phase dict 不带时间戳，_is_phase_stale 恒 False，
    采集阶段（最长阶段）zombie 无逃逸，叠加 DB status=error 会永久 already_running。
    """
    async with db() as session:
        session.add(Vehicle(id="vts", name="海豹", brand="比亚迪", search_keywords='["海豹"]'))
        await session.commit()

    snapshots = []

    # 2026-10-15 R31：news 停采，快照钩子换车质网阶段（无条件执行）
    async def fake_cz(self, vid, vehicle_name, start, end, progress):
        # 采集进行中快照：此时代码位于 scheduler.collect_vehicle 内部
        snapshots.append(dict(pipeline_phases[vid]))
        return []

    with patch("pipeline.scheduler.CollectionScheduler._collect_chezhiwang", new=fake_cz), \
         patch("pipeline.scheduler.CollectionScheduler._collect_social_platform",
               new_callable=AsyncMock, return_value=([], [])):
        await _run_full_pipeline("vts", _session_factory=db)

    assert pipeline_phases["vts"]["phase"] == "completed"
    assert snapshots, "fake_cz 未被执行"
    assert snapshots[0].get("_updated_at") is not None, \
        "collecting 阶段缺 _updated_at → stale 逃逸失效"
    assert pipeline_phases["vts"].get("_updated_at") is not None


async def test_pipeline_recalcs_heat_after_engagement_refresh(db):
    """审计 P1-3：互动刷新后必须重算热度（Phase 3 初算 + Phase 9 刷新后重算 ≥2 次）。"""
    async with db() as session:
        session.add(Vehicle(id="vhr", name="海豹", brand="比亚迪", search_keywords='["海豹"]'))
        await session.commit()

    with patch("pipeline.scheduler.CollectionScheduler._collect_news", new_callable=AsyncMock, return_value=[]), \
         patch("pipeline.scheduler.CollectionScheduler._collect_social_platform",
               new_callable=AsyncMock, return_value=([], [])), \
         patch("scripts.refresh_engagement.refresh_vehicle_engagement",
               new_callable=AsyncMock, return_value=3) as mock_refresh, \
         patch("pipeline.analysis.heat_calculator.HeatMetricCalculator.calculate_range",
               new_callable=AsyncMock) as mock_calc:
        await _run_full_pipeline("vhr", _session_factory=db)

    assert mock_refresh.await_count == 1
    assert mock_calc.await_count >= 2  # Phase 3 初算 + Phase 9 刷新后重算
    assert pipeline_phases["vhr"]["phase"] == "completed"
