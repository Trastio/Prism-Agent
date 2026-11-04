"""T4.4 Tests: Error handling and empty states — 5 tests."""
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.database import get_session
from models.schemas import Base


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


async def _create_vehicle(client):
    resp = await client.post("/api/vehicles", json={"name": "海豹", "brand": "比亚迪"})
    return resp.json()["id"]


async def test_overview_empty_data(client):
    vid = await _create_vehicle(client)
    resp = await client.get(f"/api/dashboard/overview/{vid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_posts"] == 0
    assert data["positive"] == 0
    assert data["negative"] == 0
    assert data["neutral"] == 0
    assert data["health_score"] is None  # T4.1（audit Phase 4）：0 帖返 None，与车队统一


async def test_trend_empty_data(client):
    vid = await _create_vehicle(client)
    resp = await client.get(f"/api/dashboard/trend/{vid}?start=2026-05-01&end=2026-05-22")
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"] == []


async def test_posts_empty_data(client):
    vid = await _create_vehicle(client)
    resp = await client.get(f"/api/dashboard/posts/{vid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0


async def test_platform_dist_empty(client):
    vid = await _create_vehicle(client)
    resp = await client.get(f"/api/dashboard/platform-distribution/{vid}")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_sentiment_summary_empty(client):
    vid = await _create_vehicle(client)
    resp = await client.get(f"/api/analysis/sentiment-summary/{vid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["positive"] == 0
    assert data["negative"] == 0
    assert data["neutral"] == 0
