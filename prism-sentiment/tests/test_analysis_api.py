"""Analysis API + async trigger tests — 8 tests."""
import json
import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.pipeline_state import pipeline_phases
from api.routes.analysis import _run_analysis_pipeline
from models.database import get_session
from models.schemas import Base, HeatMetric, RawPost, Vehicle


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


async def _create_vehicle(client):
    resp = await client.post("/api/vehicles", json={"name": "海豹", "brand": "比亚迪"})
    return resp.json()["id"]


# --- API layer tests ---

async def test_trigger_analysis_returns_started(client):
    vid = await _create_vehicle(client)
    with patch("api.routes.analysis._run_analysis_pipeline", new_callable=AsyncMock):
        resp = await client.post(f"/api/analysis/trigger/{vid}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"
    assert resp.json()["phase"] == "analyzing"


async def test_trigger_analysis_vehicle_not_found(client):
    resp = await client.post("/api/analysis/trigger/nonexistent")
    assert resp.status_code == 404


async def test_trigger_analysis_already_running(client):
    vid = await _create_vehicle(client)
    pipeline_phases[vid] = {"phase": "analyzing", "posts_collected": 5, "analyzed": 0, "error": None}
    resp = await client.post(f"/api/analysis/trigger/{vid}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "already_running"


async def test_get_heat_metrics_empty(client):
    vid = await _create_vehicle(client)
    resp = await client.get(f"/api/analysis/heat-metrics/{vid}?start=2026-05-01&end=2026-05-20")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_sentiment_summary(client):
    vid = await _create_vehicle(client)
    resp = await client.get(f"/api/analysis/sentiment-summary/{vid}")
    assert resp.status_code == 200
    data = resp.json()
    assert "positive" in data
    assert "negative" in data
    assert "neutral" in data


async def test_get_top_events_empty(client):
    vid = await _create_vehicle(client)
    resp = await client.get(f"/api/analysis/top-events/{vid}")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_get_top_opinions_empty(client):
    vid = await _create_vehicle(client)
    resp = await client.get(f"/api/analysis/top-opinions/{vid}")
    assert resp.status_code == 200
    data = resp.json()
    # Phase 5 T5.1：返回 dict {items, degraded} 而非裸 list
    assert isinstance(data, dict)
    assert "items" in data and "degraded" in data
    assert data["items"] == []


@pytest.mark.asyncio
async def test_opinion_merge_groups_synonyms(monkeypatch):
    """方案3：_merge_opinion_tags 归并同义标签——'价格便宜/价格合理/价格实惠'合并。"""
    from api.routes import analysis
    tags = [("价格便宜", 51), ("价格合理", 23), ("价格实惠", 19),
            ("续航长", 26), ("续航里程长", 17), ("空间大", 25)]
    merge_result = json.dumps([
        {"name": "价格便宜", "members": ["价格便宜", "价格合理", "价格实惠"]},
        {"name": "续航长", "members": ["续航长", "续航里程长"]},
        {"name": "空间大", "members": ["空间大"]},
    ])
    async def fake_llm(prompt, timeout=30):
        return merge_result
    monkeypatch.setattr(analysis, "call_llm", fake_llm)
    result = await analysis._merge_opinion_tags(tags)
    result_dict = dict(result)
    assert result_dict["价格便宜"] == 93  # 51+23+19
    assert result_dict["续航长"] == 43    # 26+17
    assert "价格合理" not in result_dict


@pytest.mark.asyncio
async def test_opinion_merge_fallback_on_llm_failure(monkeypatch):
    """方案3降级：LLM 失败 raise LLMError，端点 catch 返回未归并。"""
    from api.routes import analysis
    from utils.llm_client import LLMError
    async def failing_llm(prompt, timeout=30):
        raise LLMError("timeout", "超时")
    monkeypatch.setattr(analysis, "call_llm", failing_llm)
    with pytest.raises(LLMError):
        await analysis._merge_opinion_tags([("标签1", 10), ("标签2", 5)])


# --- Pipeline logic test ---

async def test_analysis_pipeline_completes(db):
    async with db() as session:
        session.add(Vehicle(id="v1", name="海豹", brand="比亚迪"))
        session.add(RawPost(
            id="p1", vehicle_id="v1", source="mediacrawler", platform="xhs",
            content="海豹非常好开", analysis_status="pending",
        ))
        await session.commit()

    with patch("pipeline.analysis.relevance_filter.RelevanceFilter.filter_vehicle",
               new_callable=AsyncMock, return_value={"total": 0, "passed": 0, "rejected_by_rules": 0, "limbo": 0, "rejected_by_llm": 0}), \
         patch("pipeline.analysis.analyzer.AnalysisPipeline.analyze_batch",
               new_callable=AsyncMock, return_value=[{
                   "id": "p1", "content": "海豹非常好开",
                   "sentiment": "positive", "event_tags": ["用车感受"],
                   "opinion_tags": ["舒适"], "dim_sentiment": {},
                   "subject": "self", "subject_name": "", "confidence": 0.9}]):
        await _run_analysis_pipeline("v1", _session_factory=db)

    assert pipeline_phases["v1"]["phase"] == "completed"
    assert pipeline_phases["v1"]["analyzed"] >= 1
    assert pipeline_phases["v1"].get("_updated_at") is not None  # 审计 P1-1


async def test_pipeline_calls_fetch_top_comments_before_summaries(db):
    """_run_analysis_pipeline 应在 run_comment_summaries 前调 fetch_top_comments。"""
    async with db() as session:
        session.add(Vehicle(id="v2", name="海豹", brand="比亚迪"))
        session.add(RawPost(
            id="p2", vehicle_id="v2", source="mediacrawler", platform="xhs",
            content="测试内容", analysis_status="pending",
        ))
        await session.commit()

    call_order = []

    async def fake_fetch(self, vid):
        call_order.append("fetch_top_comments")
        return 0

    async def fake_summaries(self, vid):
        call_order.append("run_comment_summaries")
        return 0

    with patch("pipeline.analysis.relevance_filter.RelevanceFilter.filter_vehicle",
               new_callable=AsyncMock,
               return_value={"total": 0, "passed": 0, "rejected_by_rules": 0, "limbo": 0, "rejected_by_llm": 0}), \
         patch("pipeline.analysis.analyzer.AnalysisPipeline.analyze_batch",
               new_callable=AsyncMock,
               return_value=[{"id": "p2", "content": "测试内容",
                              "sentiment": "neutral", "event_tags": [], "opinion_tags": [],
                              "dim_sentiment": {}, "subject": "self", "subject_name": "",
                              "confidence": 0.5}]), \
         patch("pipeline.scheduler.CollectionScheduler.fetch_top_comments", fake_fetch), \
         patch("pipeline.analysis.batch_runner.BatchAnalysisRunner.run_comment_summaries", fake_summaries):
        await _run_analysis_pipeline("v2", _session_factory=db)

    assert "fetch_top_comments" in call_order
    assert call_order.index("fetch_top_comments") < call_order.index("run_comment_summaries")


# --- BatchRunner new fields + full_content tests ---

async def test_batch_runner_stores_new_fields(db):
    """BatchAnalysisRunner should store dim_sentiment and event_tags."""
    import json as _json
    from models.schemas import AnalyzedPost
    from pipeline.analysis.batch_runner import BatchAnalysisRunner

    async with db() as session:
        vehicle_id = str(uuid.uuid4())
        session.add(Vehicle(id=vehicle_id, name="测试", brand="测试"))
        session.add(RawPost(
            id="post_new1", vehicle_id=vehicle_id, content="刹车异响",
            source="test", analysis_status="pending",
        ))
        await session.commit()

        runner = BatchAnalysisRunner(session)
        with patch("pipeline.analysis.relevance_filter.RelevanceFilter.filter_vehicle",
                   new_callable=AsyncMock, return_value={"total": 0, "passed": 0, "rejected_by_rules": 0, "limbo": 0, "rejected_by_llm": 0}), \
             patch.object(runner._pipeline, "analyze_batch", new_callable=AsyncMock) as mock_analyze:
            mock_analyze.return_value = [{
                "id": "post_new1", "content": "刹车异响",
                "sentiment": "negative",
                "event_tags": ["异响/故障"],
                "opinion_tags": ["刹车问题"], "dim_sentiment": {"安全性": -1},
                "confidence": 0.9,
            }]
            result = await runner.run_for_vehicle(vehicle_id)
            assert result["analyzed"] == 1

        from sqlalchemy import select
        ap = (await session.execute(
            select(AnalyzedPost).where(AnalyzedPost.post_id == "post_new1")
        )).scalars().first()
        assert ap is not None
        dim = _json.loads(ap.dim_sentiment)
        assert "安全性" in dim
        tags = _json.loads(ap.event_tags)
        assert "异响/故障" in tags


async def test_batch_runner_uses_full_content(db):
    """Should prefer full_content over content when available."""
    from pipeline.analysis.batch_runner import BatchAnalysisRunner

    async with db() as session:
        vehicle_id = str(uuid.uuid4())
        session.add(Vehicle(id=vehicle_id, name="测试", brand="测试"))
        session.add(RawPost(
            id="post_fc1", vehicle_id=vehicle_id, content="short snippet",
            full_content="Full article with lots of detail " * 20,
            source="bocha", analysis_status="pending",
        ))
        await session.commit()

        runner = BatchAnalysisRunner(session)
        with patch("pipeline.analysis.relevance_filter.RelevanceFilter.filter_vehicle",
                   new_callable=AsyncMock, return_value={"total": 0, "passed": 0, "rejected_by_rules": 0, "limbo": 0, "rejected_by_llm": 0}), \
             patch.object(runner._pipeline, "analyze_batch", new_callable=AsyncMock) as mock_analyze:
            mock_analyze.return_value = [{
                "id": "post_fc1", "content": "Full article with lots of detail " * 20,
                "sentiment": "positive",
                "event_tags": [],
                "opinion_tags": [], "dim_sentiment": {},
                "confidence": 0.8,
            }]
            result = await runner.run_for_vehicle(vehicle_id)
            assert result["analyzed"] == 1
            # Verify analyze_batch was called with full_content, not snippet
            call_args = mock_analyze.call_args[0][0]
            assert len(call_args) == 1
            assert "Full article" in call_args[0]["content"]
