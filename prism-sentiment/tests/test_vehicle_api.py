"""T1.3 Tests: Vehicle CRUD API — 9 endpoints."""
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture
async def client():
    from api.main import app
    from models.database import get_session
    from models.schemas import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()
    await engine.dispose()


async def test_create_vehicle(client):
    resp = await client.post("/api/vehicles", json={
        "name": "海豹", "brand": "比亚迪", "search_keywords": ["海豹EV"],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "海豹"
    assert data["status"] == "active"


async def test_list_vehicles(client):
    await client.post("/api/vehicles", json={"name": "海豹", "brand": "比亚迪"})
    await client.post("/api/vehicles", json={"name": "秦PLUS", "brand": "比亚迪"})
    resp = await client.get("/api/vehicles")
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


async def test_search_vehicles(client):
    await client.post("/api/vehicles", json={"name": "海豹", "brand": "比亚迪"})
    resp = await client.get("/api/vehicles/search?q=海豹")
    assert resp.status_code == 200
    names = [v["name"] for v in resp.json()]
    assert "海豹" in names


async def test_get_vehicle(client):
    r = await client.post("/api/vehicles", json={"name": "海豹", "brand": "比亚迪"})
    vid = r.json()["id"]
    resp = await client.get(f"/api/vehicles/{vid}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "海豹"


async def test_get_vehicle_not_found(client):
    resp = await client.get("/api/vehicles/nonexistent")
    assert resp.status_code == 404


async def test_update_vehicle(client):
    r = await client.post("/api/vehicles", json={"name": "海豹", "brand": "比亚迪"})
    vid = r.json()["id"]
    resp = await client.put(f"/api/vehicles/{vid}", json={"name": "海豹06"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "海豹06"


async def test_delete_vehicle(client):
    r = await client.post("/api/vehicles", json={"name": "海豹", "brand": "比亚迪"})
    vid = r.json()["id"]
    resp = await client.delete(f"/api/vehicles/{vid}")
    assert resp.status_code == 200
    list_resp = await client.get("/api/vehicles")
    assert vid not in [v["id"] for v in list_resp.json()]


async def test_update_lifecycle(client):
    r = await client.post("/api/vehicles", json={"name": "海豹", "brand": "比亚迪"})
    vid = r.json()["id"]
    resp = await client.put(f"/api/vehicles/{vid}/lifecycle",
                            json={"launch": "2024-06-01", "facelift": "2025-03-01"})
    assert resp.status_code == 200


async def test_update_competitors(client):
    v1 = await client.post("/api/vehicles", json={"name": "海豹", "brand": "比亚迪"})
    v2 = await client.post("/api/vehicles", json={"name": "Model 3", "brand": "Tesla"})
    resp = await client.put(f"/api/vehicles/{v1.json()['id']}/competitors",
                            json=[v2.json()["id"]])
    assert resp.status_code == 200
