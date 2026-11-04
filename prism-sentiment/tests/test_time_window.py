"""T1.4 时间窗跟随：overview/word-cloud/top-posts 3 端点挂 start/end
（defect-themes 2026-10-20 起退出用户窗跟随，统一 30 天权威窗——见其用例）
+ coalesce(published_at, collected_at) 兜底 NULL。

背景：微博/抖音 published_at 大量 NULL（详情采集器不返回时间戳），此前 overview
total 不挂窗、word-cloud/top-posts 前端故意不传 start/end（注释明说 NULL 丢帖）。
coalesce 兜底解决了丢帖问题，4 端点开始统一跟随用户窗。
"""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.database import get_session
from models.schemas import AnalyzedPost, Base, PostComment, RawPost, Vehicle


@pytest_asyncio.fixture
async def env():
    """(client, session) 共享同一内存库（复用 test_author_type.py 模式）。"""
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
        async with factory() as s:
            yield c, s
    app.dependency_overrides.clear()
    await engine.dispose()


async def _seed_post(s, vid, pid, published_at, collected_at=None,
                     sentiment="positive", platform="weibo", likes=10,
                     content=None, author="老王", author_type="organic"):
    """seed 一帖，可独立指定 published_at / collected_at（None 测兜底）。"""
    s.add(RawPost(
        id=pid, vehicle_id=vid, source="tikhub", platform=platform,
        title=f"帖{pid}", content=content or f"内容{pid}", author=author,
        url=f"https://x.com/{pid}", published_at=published_at,
        collected_at=collected_at, likes=likes, comments=1, shares=0,
        analysis_status="analyzed", author_type=author_type,
    ))
    s.add(AnalyzedPost(
        id=f"ap-{pid}", post_id=pid, vehicle_id=vid, sentiment=sentiment,
        model_used="test", dim_sentiment='{"续航里程": 1}',
    ))


@pytest.mark.asyncio
async def test_overview_follows_time_window(env):
    """overview 传 start/end 时只统计窗内帖：9月窗→total=1，不传→total=2。"""
    client, s = env
    s.add(Vehicle(id="v1", name="海豹", brand="比亚迪"))
    await s.commit()
    # p1 在 9 月窗内，p2 在 8 月窗外
    await _seed_post(s, "v1", "p1", datetime(2026, 9, 1), datetime(2026, 9, 1))
    await _seed_post(s, "v1", "p2", datetime(2026, 8, 1), datetime(2026, 8, 1))
    await s.commit()

    # 不传窗 → 全量 total=2
    r = (await client.get("/api/dashboard/overview/v1")).json()
    assert r["total_posts"] == 2

    # 传 9 月窗 → total=1（仅 p1）
    r = (await client.get("/api/dashboard/overview/v1"
                          "?start=2026-09-01&end=2026-09-30")).json()
    assert r["total_posts"] == 1
    # 窗内情感计数也跟随：positive=1（p1），不传窗 positive=2
    assert r["positive"] == 1
    assert r["analyzed_posts"] == 1
    # 健康分跟随用户窗（窗内 pos=1 neg=0 analyzed=1 → 50+(1-0)/1*50=100）
    assert r["health_score"] == 100.0


@pytest.mark.asyncio
async def test_null_published_at_uses_collected_at(env):
    """published_at=NULL 时用 collected_at 兜底进窗（微博/抖音常见 NULL）。

    p1: published_at=None, collected_at=9月15（窗内）→ coalesce 兜底进窗
    p2: published_at=8月1（窗外）→ 不进窗
    传 9 月窗 → total=1（仅 p1）。若直比 published_at 会丢 p1 → total=0。
    """
    client, s = env
    s.add(Vehicle(id="v1", name="海豹", brand="比亚迪"))
    await s.commit()
    await _seed_post(s, "v1", "p1", None, datetime(2026, 9, 15))
    await _seed_post(s, "v1", "p2", datetime(2026, 8, 1), datetime(2026, 8, 1))
    await s.commit()

    # 不传窗 → total=2
    r = (await client.get("/api/dashboard/overview/v1")).json()
    assert r["total_posts"] == 2

    # 传 9 月窗 → coalesce 兜底 p1 进窗，p2 在窗外 → total=1
    r = (await client.get("/api/dashboard/overview/v1"
                          "?start=2026-09-01&end=2026-09-30")).json()
    assert r["total_posts"] == 1
    assert r["positive"] == 1


@pytest.mark.asyncio
async def test_word_cloud_follows_time_window(env):
    """word-cloud 传 start/end 时只取窗内帖文本（coalesce 兜底 NULL）。

    p1: published_at=None, collected_at=9月（窗内）→ coalesce 兜底进窗
    p2: published_at=8月（窗外）→ 不进窗
    窗内只应有 p1 的特征词"刹车异响"，不应有 p2 的"续航虚标"。
    """
    client, s = env
    s.add(Vehicle(id="v1", name="海豹", brand="比亚迪"))
    await s.commit()
    await _seed_post(s, "v1", "p1", None, datetime(2026, 9, 1),
                     content="刹车异响严重", likes=10)
    await _seed_post(s, "v1", "p2", datetime(2026, 8, 1), datetime(2026, 8, 1),
                     content="续航虚标", likes=20)
    await s.commit()

    r = (await client.get("/api/dashboard/word-cloud/v1"
                          "?start=2026-09-01&end=2026-09-30&limit=10")).json()
    names = {w["name"] for w in r}
    # p1 特征词进窗，p2 特征词不进窗
    assert "刹车" in names or "异响" in names
    assert "续航" not in names and "虚标" not in names


@pytest.mark.asyncio
async def test_top_posts_follows_time_window(env):
    """top-posts 传 start/end 时只返回窗内帖（coalesce 兜底 NULL）。

    p1: published_at=None, collected_at=9月（窗内），likes=10
    p2: published_at=8月（窗外），likes=999
    传 9 月窗 → 只返回 p1（p2 互动更高但在窗外）。
    若直比 published_at，p1 的 NULL 会被排除 → 返回空列表。
    """
    client, s = env
    s.add(Vehicle(id="v1", name="海豹", brand="比亚迪"))
    await s.commit()
    await _seed_post(s, "v1", "p1", None, datetime(2026, 9, 1), likes=10)
    await _seed_post(s, "v1", "p2", datetime(2026, 8, 1), datetime(2026, 8, 1),
                     likes=999)
    await s.commit()

    r = (await client.get("/api/dashboard/top-posts/v1"
                          "?start=2026-09-01&end=2026-09-30")).json()
    assert [p["id"] for p in r] == ["p1"]


@pytest.mark.asyncio
async def test_defect_themes_uses_30d_authoritative_window(env):
    """缺陷簇 30 天权威窗（2026-10-20 闭环改造，替代原"跟随用户窗"行为）。

    端点不再跟随用户 start/end（原管线 90 天窗/浏览 30 天窗互踩，每次切换
    全量重算烧 LLM + LLM 失败清空覆盖），统一按"今天−29 ~ 今天"取池。
    本用例两层验证：①极端用户窗参数（2020 年）被无视；②评论池按固定 30 天
    窗取帖（coalesce 兜底 NULL published_at 的旧行为仍覆盖）。
    """
    client, s = env
    s.add(Vehicle(id="v1", name="海豹", brand="比亚迪"))
    await s.commit()
    now = datetime.now()
    # 窗内：published_at=None + collected_at=5 天前（coalesce 兜底路径）
    await _seed_post(s, "v1", "p1", None, now - timedelta(days=5),
                     sentiment="negative")
    # 窗外：40 天前（在 30 天权威窗外，即便 likes 更高也不进池）
    await _seed_post(s, "v1", "p2", now - timedelta(days=40),
                     now - timedelta(days=40), sentiment="negative")
    await s.commit()
    for i in range(8):
        s.add(PostComment(
            id=f"c1-{i}", post_id="p1", vehicle_id="v1", cid=f"c1-{i}",
            content=f"刹车异响问题{i}", author=f"A{i}", likes=10, platform="weibo",
        ))
    for i in range(8):
        s.add(PostComment(
            id=f"c2-{i}", post_id="p2", vehicle_id="v1", cid=f"c2-{i}",
            content=f"窗外评论{i}", author=f"B{i}", likes=999, platform="weibo",
        ))
    await s.commit()

    from pipeline.analysis import defect_miner

    captured = {}

    def fake_cluster(pool, generic_names=None):
        captured["pool_post_ids"] = {c["post_id"] for c in pool}
        return []

    async def fake_judge(clusters, vehicle_name=""):
        return []

    mp = pytest.MonkeyPatch()
    mp.setattr(defect_miner, "_cluster_complaints", fake_cluster)
    mp.setattr(defect_miner, "_judge_defect_clusters", fake_judge)
    try:
        r = (await client.get("/api/dashboard/defect-themes/v1"
                              "?start=2020-01-01&end=2020-12-31")).json()
    finally:
        mp.undo()

    # 窗内帖 p1 评论进池（coalesce 兜底 NULL published_at），
    # 窗外帖 p2 不进池（用户窗 2020 年被无视，按今天−29 天取池）
    assert captured.get("pool_post_ids") == {"p1"}
    assert r == []
