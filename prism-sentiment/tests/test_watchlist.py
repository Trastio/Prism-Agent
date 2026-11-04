"""WatchItem 手动关注清单 CRUD 测试（openspec: watch-list）。

纯人工标记，无状态机——验证标记后列表可见、无 status 字段、删除生效。
"""
import pytest
import pytest_asyncio
from datetime import date
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from api.main import app
from models.database import get_session
from models.schemas import Base, Vehicle


@pytest_asyncio.fixture
async def env():
    """(client, session) 共享同一内存库。"""
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
        async with factory() as s:
            yield c, s
    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_watchitem_crud(env):
    """标记关注 → 列表可见 → 移除生效。"""
    client, s = env
    s.add(Vehicle(id="v1", name="风云T7", brand="奇瑞"))
    await s.commit()

    # 标记一个缺陷簇
    r = await client.post("/api/watchlist/v1", json={
        "title": "仪表盘车道线消失",
        "source_type": "defect_cluster",
        "source_ref": "cluster_xxx",
        "post_count": 12,
        "first_seen": "2026-09-20",
    })
    assert r.status_code == 200
    item_id = r.json()["id"]

    # 列表可见
    r = await client.get("/api/watchlist/v1")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["id"] == item_id
    assert items[0]["title"] == "仪表盘车道线消失"
    assert items[0]["source_type"] == "defect_cluster"
    assert items[0]["post_count"] == 12
    assert items[0]["first_seen"] == "2026-09-20"
    # 无 status 字段（纯人工标记，无状态机）
    assert "status" not in items[0]

    # 移除
    r = await client.delete(f"/api/watchlist/v1/{item_id}")
    assert r.status_code == 200
    r = await client.get("/api/watchlist/v1")
    assert r.json() == []


@pytest.mark.asyncio
async def test_watchitem_ordering_by_first_seen_desc(env):
    """列表按 first_seen 降序（新鲜度优先）。"""
    client, s = env
    s.add(Vehicle(id="v1", name="风云T7", brand="奇瑞"))
    await s.commit()

    for i, (title, seen) in enumerate([
        ("旧关注", "2026-09-10"),
        ("新关注", "2026-09-25"),
        ("中关注", "2026-09-18"),
    ]):
        r = await client.post("/api/watchlist/v1", json={
            "title": title, "source_type": "hot_post",
            "source_ref": f"p{i}", "post_count": 1, "first_seen": seen,
        })
        assert r.status_code == 200

    items = (await client.get("/api/watchlist/v1")).json()
    titles = [it["title"] for it in items]
    assert titles == ["新关注", "中关注", "旧关注"]


@pytest.mark.asyncio
async def test_watchitem_scoped_to_vehicle(env):
    """A 车的关注项不泄漏给 B 车。"""
    client, s = env
    s.add(Vehicle(id="v1", name="风云T7", brand="奇瑞"))
    s.add(Vehicle(id="v2", name="星愿", brand="吉利"))
    await s.commit()

    await client.post("/api/watchlist/v1", json={
        "title": "风云关注", "source_type": "event",
        "source_ref": "e1", "post_count": 3, "first_seen": "2026-09-20",
    })
    await client.post("/api/watchlist/v2", json={
        "title": "星愿关注", "source_type": "complaint",
        "source_ref": "c1", "post_count": 2, "first_seen": "2026-09-20",
    })

    v1 = (await client.get("/api/watchlist/v1")).json()
    v2 = (await client.get("/api/watchlist/v2")).json()
    assert len(v1) == 1 and v1[0]["title"] == "风云关注"
    assert len(v2) == 1 and v2[0]["title"] == "星愿关注"
