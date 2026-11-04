"""End-to-end integration — 1 test (full pipeline via direct call)."""
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.pipeline_state import pipeline_phases
from api.routes.collection import _run_full_pipeline
from models.database import get_session
from models.schemas import Base, Vehicle


@pytest_asyncio.fixture
async def client_and_db():
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
        yield c, factory
    app.dependency_overrides.clear()
    pipeline_phases.clear()
    await engine.dispose()


async def test_full_e2e_pipeline(client_and_db):
    client, db = client_and_db

    # Step 1: Create vehicle via API
    resp = await client.post("/api/vehicles", json={"name": "海豹", "brand": "比亚迪", "search_keywords": ["海豹EV"]})
    assert resp.status_code == 200
    vid = resp.json()["id"]

    # Step 2: Run full pipeline directly (collect → analyze → heat → anomaly)
    # 相对日期：固定日期会滚出 90 天采集窗口（_store_posts floor）→ 0 帖连环挂
    _recent = (date.today() - timedelta(days=5)).isoformat()
    mock_posts = [
        {"title": f"海豹测评{i}", "content": f"续航很好，这是第{i}篇测评文章，内容各不相同" * 10,
         "url": f"https://ex.com/{i}",
         "source": "tikhub", "platform": "douyin", "author": "tester",
         "published_at": _recent}
        for i in range(5)
    ]
    mock_analysis = {"sentiment": "positive", "event_tags": ["新车上市"], "opinion_tags": ["续航好"], "confidence": 0.9}

    # 2026-10-15 R31：news 停采，注入通道换社媒（douyin）
    with patch("pipeline.scheduler.CollectionScheduler._collect_chezhiwang", new_callable=AsyncMock, return_value=[]), \
         patch("pipeline.scheduler.CollectionScheduler._collect_social_platform", new_callable=AsyncMock, return_value=(mock_posts, [])), \
         patch("pipeline.scheduler.CollectionScheduler._resolve_collector", new_callable=AsyncMock, return_value=(object(), "tikhub")), \
         patch("pipeline.scheduler.CollectionScheduler._crawl_full_texts", new_callable=AsyncMock, side_effect=lambda p: p), \
         patch("pipeline.scheduler.CollectionScheduler._resolve_urls", new_callable=AsyncMock, side_effect=lambda p: p), \
         patch("pipeline.scheduler.CollectionScheduler._run_dedup", side_effect=lambda p: p), \
         patch("pipeline.scheduler.CollectionScheduler._expand_keywords_if_needed", new_callable=AsyncMock, return_value=["海豹EV"]), \
         patch("pipeline.analysis.relevance_filter.RelevanceFilter.filter_vehicle",
              new_callable=AsyncMock, return_value={"total": 0, "passed": 0, "rejected_by_rules": 0, "limbo": 0, "rejected_by_llm": 0}), \
         patch("pipeline.analysis.analyzer.AnalysisPipeline.analyze_batch", new_callable=AsyncMock, return_value=[mock_analysis] * 5):
        await _run_full_pipeline(vid, _session_factory=db)

    assert pipeline_phases[vid]["phase"] == "completed"
    assert pipeline_phases[vid]["posts_collected"] == 5
    assert pipeline_phases[vid]["analyzed"] == 5

    # Step 3: Dashboard overview reflects pipeline results
    resp = await client.get(f"/api/dashboard/overview/{vid}")
    assert resp.status_code == 200
    overview = resp.json()
    assert overview["total_posts"] >= 5
    assert overview["positive"] >= 5

    # Step 4: Generate deep report
    with patch("api.routes.reports.generate_deep_report_content", new_callable=AsyncMock, return_value="# 深度报告"):
        resp = await client.post("/api/reports/deep-report", json={
            "vehicle_id": vid, "start_date": "2026-05-01", "end_date": "2026-05-18",
        })
    assert resp.status_code == 200
    assert resp.json()["type"] == "deep_report"

    # Step 5: Reports list
    resp = await client.get(f"/api/dashboard/reports/{vid}")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    # Step 6: Posts list
    resp = await client.get(f"/api/dashboard/posts/{vid}")
    assert resp.status_code == 200
    assert resp.json()["total"] >= 5

    # Step 7: Pipeline status endpoint
    resp = await client.get(f"/api/vehicles/{vid}/pipeline-status")
    assert resp.status_code == 200
    assert resp.json()["phase"] == "completed"
