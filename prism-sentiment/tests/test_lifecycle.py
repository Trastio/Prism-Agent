"""T4.2 Tests: Lifecycle phase annotations — 3 tests."""
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


async def test_overview_includes_lifecycle(client):
    resp = await client.post("/api/vehicles", json={
        "name": "海豹", "brand": "比亚迪",
        "lifecycle_anchors": {"launch": "2024-06-01", "facelift": "2025-03-01"},
    })
    vid = resp.json()["id"]
    resp = await client.get(f"/api/dashboard/overview/{vid}")
    assert resp.status_code == 200
    data = resp.json()
    assert "lifecycle_anchors" in data
    assert data["lifecycle_anchors"]["launch"] == "2024-06-01"


async def test_trend_includes_lifecycle_phases(client):
    resp = await client.post("/api/vehicles", json={
        "name": "海豹", "brand": "比亚迪",
        "lifecycle_anchors": {"launch": "2024-06-01", "facelift": "2025-03-01"},
    })
    vid = resp.json()["id"]
    resp = await client.get(f"/api/dashboard/trend/{vid}?start=2024-05-01&end=2025-06-01")
    assert resp.status_code == 200
    data = resp.json()
    assert "lifecycle_phases" in data
    phases = data["lifecycle_phases"]
    assert len(phases) >= 1
    assert any(p["type"] == "launch" for p in phases)


async def test_trend_no_lifecycle(client):
    resp = await client.post("/api/vehicles", json={"name": "秦PLUS", "brand": "比亚迪"})
    vid = resp.json()["id"]
    resp = await client.get(f"/api/dashboard/trend/{vid}?start=2026-05-01&end=2026-05-22")
    assert resp.status_code == 200
    data = resp.json()
    assert "lifecycle_phases" in data
    assert data["lifecycle_phases"] == []
