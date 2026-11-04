"""Report API tests — deep report + dashboard summary (主题C 删 brief)。"""
import uuid
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.database import get_session
from models.schemas import Base, Report, Vehicle


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
    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest_asyncio.fixture
async def vehicle(client):
    resp = await client.post("/api/vehicles", json={"name": "海豹", "brand": "比亚迪"})
    return resp.json()["id"]


async def test_generate_deep_report(client, vehicle):
    mock_report = "# 海豹深度报告\n## 一、车型概况\n...\n## 六、建议\n..."
    with patch("api.routes.reports.generate_deep_report_content", new_callable=AsyncMock, return_value=mock_report):
        resp = await client.post("/api/reports/deep-report", json={
            "vehicle_id": vehicle,
            "start_date": "2026-05-01",
            "end_date": "2026-05-20",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "deep_report"


async def test_deep_report_saves_to_db(client, vehicle):
    mock_report = "深度报告内容"
    with patch("api.routes.reports.generate_deep_report_content", new_callable=AsyncMock, return_value=mock_report):
        await client.post("/api/reports/deep-report", json={
            "vehicle_id": vehicle, "start_date": "2026-05-01", "end_date": "2026-05-20",
        })
    resp = await client.get(f"/api/dashboard/reports/{vehicle}")
    reports = resp.json()
    assert any(r["type"] == "deep_report" for r in reports)


async def test_deep_report_vehicle_not_found(client):
    resp = await client.post("/api/reports/deep-report", json={
        "vehicle_id": "nonexistent", "start_date": "2026-05-01", "end_date": "2026-05-20",
    })
    assert resp.status_code == 404


async def test_dashboard_summary(client, vehicle):
    mock_content = "## 舆情简报\n总体评价：良好。关键发现：本周声量平稳。"
    with patch("api.routes.reports._call_llm", new_callable=AsyncMock, return_value=mock_content):
        resp = await client.post("/api/reports/dashboard-summary", json={
            "vehicle_id": vehicle,
            "start_date": "2026-05-01",
            "end_date": "2026-06-17",
        })
    assert resp.status_code == 200
    data = resp.json()
    assert "content" in data
    assert "id" in data
    assert data["content"] == mock_content


async def test_deep_report_prompt_contains_real_data():
    """deep-report 接 DB 后，传给 LLM 的 prompt 应含真实 sentiment/事件/维度（主题C 核心）。"""
    from api.routes.reports import generate_deep_report_content

    captured = {}

    async def fake_llm(prompt, timeout=60):
        captured["prompt"] = prompt
        return "深度报告"

    with patch("api.routes.reports._call_llm", new=fake_llm):
        await generate_deep_report_content(
            vehicle_name="海豹", start_date="2026-05-01", end_date="2026-05-20",
            sentiment_data={"positive": 10, "negative": 3, "neutral": 5},
            event_data=[{"tag": "降价促销", "count": 8, "span": "2026-05-01~2026-05-10"}],
            dim_data=[{"dim": "续航", "score": 0.85, "count": 5}],
        )
    assert "10" in captured["prompt"]         # sentiment 计数
    assert "降价促销" in captured["prompt"]     # 事件名
    assert "续航" in captured["prompt"]         # 维度
