"""T3.2 Tests: Dashboard API — 10 tests."""
import json
import uuid
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.database import get_session
from models.schemas import (
    AnalyzedPost, Base, EventGroup, HeatMetric, PostComment, RawPost, Report, Vehicle,
)


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


async def _setup_vehicle_with_data(client):
    resp = await client.post("/api/vehicles", json={"name": "海豹", "brand": "比亚迪"})
    vid = resp.json()["id"]
    return vid


async def _seed_data(db, vid):
    for i in range(5):
        db.add(RawPost(
            id=str(uuid.uuid4()), vehicle_id=vid, source="tavily", platform="news",
            content=f"帖子{i}", analysis_status="analyzed",
            published_at=datetime(2026, 5, 20),
        ))
    db.add(AnalyzedPost(
        id=str(uuid.uuid4()), post_id="p1", vehicle_id=vid,
        sentiment="positive", event_tags='["新车上市"]',
        opinion_tags='["颜值高"]', confidence=0.9, model_used="test",
    ))
    db.add(AnalyzedPost(
        id=str(uuid.uuid4()), post_id="p2", vehicle_id=vid,
        sentiment="negative", event_tags='["召回"]',
        opinion_tags='["自燃"]', confidence=0.8, model_used="test",
    ))
    db.add(AnalyzedPost(
        id=str(uuid.uuid4()), post_id="p3", vehicle_id=vid,
        sentiment="neutral", event_tags='["日常讨论"]',
        opinion_tags='[]', confidence=0.5, model_used="test",
    ))
    db.add(HeatMetric(
        id=str(uuid.uuid4()), vehicle_id=vid, date=date(2026, 5, 20),
        attention_index=10.0, discussion_volume=5, media_volume=3, interaction_intensity=2.5,
    ))
    await db.commit()


async def test_overview(client):
    vid = await _setup_vehicle_with_data(client)
    resp = await client.get(f"/api/dashboard/overview/{vid}")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_posts" in data
    assert "positive" in data
    assert "negative" in data
    assert "neutral" in data
    assert "health_score" in data
    assert "comments_per_post" in data
    assert "week_change_rate" in data
    assert isinstance(data["week_change_rate"], (int, float, type(None)))
    # T1.7 样本不足护栏：空库 analyzed_total=0 < 20 → True
    assert "sample_insufficient" in data
    assert data["sample_insufficient"] is True


@pytest_asyncio.fixture
async def client_with_session():
    """返回 (client, session_factory) 共享同一内存库，便于直接灌匹配帖。"""
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


async def test_overview_sample_insufficient_threshold(client_with_session):
    """T1.7：≥20 帖时 sample_insufficient=False。"""
    client, session = client_with_session
    resp = await client.post("/api/vehicles", json={"name": "海豹", "brand": "比亚迪"})
    vid = resp.json()["id"]
    # 灌 25 个 organic + self 帖（过 SELF_ONLY + AUTHENTIC_AUTHOR 口径）
    for i in range(25):
        pid = f"p{i}"
        session.add(RawPost(
            id=pid, vehicle_id=vid, source="tikhub", platform="weibo",
            title=f"帖{i}", content=f"帖{i}" * 2, author=f"作者{i}", url=f"https://x/{pid}",
            published_at=datetime(2026, 5, 20), likes=10, comments=5, shares=0,
            analysis_status="analyzed", relevance_score=1.0, author_type="organic",
        ))
        session.add(AnalyzedPost(
            id=f"ap-{pid}", post_id=pid, vehicle_id=vid,
            sentiment="positive", model_used="test", subject="self",
        ))
    await session.commit()
    resp = await client.get(
        f"/api/dashboard/overview/{vid}?start=2026-05-01&end=2026-05-31"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["analyzed_posts"] >= 20
    assert data["sample_insufficient"] is False


async def test_overview_vehicle_not_found(client):
    resp = await client.get("/api/dashboard/overview/nonexistent")
    assert resp.status_code == 404


async def test_trend(client):
    vid = await _setup_vehicle_with_data(client)
    resp = await client.get(f"/api/dashboard/trend/{vid}?start=2026-05-18&end=2026-05-22")
    assert resp.status_code == 200
    data = resp.json()
    assert "data" in data
    assert isinstance(data["data"], list)
    # event_annotations 默认空 dict（无 EventGroup 时也要有键，前端 .filter 才不炸）
    assert data["event_annotations"] == {}


async def test_trend_event_annotations_sunday_key():
    """/trend event_annotations：EventGroup.start_date 落在的周按「周日起」取 key，
    与前端 renderAttentionChart 的 getDay() 分桶一致——markPoint coord 才能命中 x 轴。"""
    from api.main import app
    import uuid as _uuid

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    vid = str(_uuid.uuid4())
    async with factory() as session:
        session.add(Vehicle(id=vid, name="海豹", brand="比亚迪"))
        # HeatMetric 给一周的点位，确保该周出现在 weekKeys
        for d in ("2026-08-23", "2026-08-24", "2026-08-25", "2026-08-26",
                  "2026-08-27", "2026-08-28", "2026-08-29"):
            session.add(HeatMetric(vehicle_id=vid, date=date.fromisoformat(d),
                                   attention_index=500.0))
        # EventGroup：start_date=2026-08-26（周三）→ 周日起点 = 2026-08-23
        session.add(EventGroup(vehicle_id=vid, event_tag="续航争议",
                               start_date=date.fromisoformat("2026-08-26"),
                               end_date=date.fromisoformat("2026-08-29"),
                               post_count=5, source="social"))
        await session.commit()

    async def override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(
                f"/api/dashboard/trend/{vid}?start=2026-08-23&end=2026-08-30")
        assert resp.status_code == 200
        ann = resp.json()["event_annotations"]
        # 周三 08-26 → 周日起 08-23（JS getDay 周三=3，08-26-3=08-23）
        assert "2026-08-23" in ann
        assert ann["2026-08-23"] == ["续航争议"]
    finally:
        app.dependency_overrides.clear()


async def test_platform_distribution(client):
    vid = await _setup_vehicle_with_data(client)
    resp = await client.get(f"/api/dashboard/platform-distribution/{vid}")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_event_distribution(client):
    vid = await _setup_vehicle_with_data(client)
    resp = await client.get(f"/api/dashboard/event-distribution/{vid}")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_posts_list(client):
    vid = await _setup_vehicle_with_data(client)
    resp = await client.get(f"/api/dashboard/posts/{vid}")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data


async def test_posts_with_filters(client):
    vid = await _setup_vehicle_with_data(client)
    resp = await client.get(f"/api/dashboard/posts/{vid}?sentiment=positive&page=1&size=10")
    assert resp.status_code == 200


async def test_posts_with_time_range(client):
    vid = await _setup_vehicle_with_data(client)
    resp = await client.get(f"/api/dashboard/posts/{vid}?start=2026-05-19&end=2026-05-21")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "items" in data


async def test_posts_with_time_range_excludes(client):
    vid = await _setup_vehicle_with_data(client)
    resp = await client.get(f"/api/dashboard/posts/{vid}?start=2026-06-01&end=2026-06-30")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0


async def test_word_cloud(client):
    vid = await _setup_vehicle_with_data(client)
    resp = await client.get(f"/api/dashboard/word-cloud/{vid}")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    if data:
        assert "name" in data[0]
        assert "value" in data[0]


async def test_word_cloud_with_time_range(client):
    vid = await _setup_vehicle_with_data(client)
    resp = await client.get(f"/api/dashboard/word-cloud/{vid}?start=2026-05-01&end=2026-05-31")
    assert resp.status_code == 200


async def test_reports_list(client):
    vid = await _setup_vehicle_with_data(client)
    resp = await client.get(f"/api/dashboard/reports/{vid}")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_competitor_comparison(client):
    resp = await client.post("/api/vehicles", json={"name": "海豹", "brand": "比亚迪"})
    vid = resp.json()["id"]
    resp2 = await client.post("/api/vehicles", json={"name": "Model 3", "brand": "特斯拉"})
    comp_id = resp2.json()["id"]
    await client.put(f"/api/vehicles/{vid}/competitors", json=[comp_id])

    resp = await client.get(f"/api/dashboard/competitor-comparison/{vid}")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 2
    names = [d["name"] for d in data]
    assert "海豹" in names
    assert "Model 3" in names
    for item in data:
        assert "positive" in item
        assert "negative" in item
        assert "neutral" in item


async def test_competitor_comparison_no_competitors(client):
    resp = await client.post("/api/vehicles", json={"name": "海豹", "brand": "比亚迪"})
    vid = resp.json()["id"]
    resp = await client.get(f"/api/dashboard/competitor-comparison/{vid}")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_event_timeline_returns_list(client):
    response = await client.get("/api/dashboard/vehicles/nonexistent/events")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


async def test_top_posts_includes_subject_name(client):
    """Top posts response schema should include subject_name field."""
    vid = await _setup_vehicle_with_data(client)
    resp = await client.get(f"/api/dashboard/top-posts/{vid}")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # Any returned post must include the subject_name key
    for post in data:
        assert "subject_name" in post


@pytest.mark.asyncio
async def test_trend_composite_search_index():
    """/trend 合成搜索指数：两源量纲不同（dy~千 vs xhs~百）→ 各源按窗口内
    自身 max 归一 0-100 再平均；无指数数据的日期 search_index=None。"""
    from api.main import app
    import uuid as _uuid
    from models.schemas import SearchIndexMetric

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    vid = str(_uuid.uuid4())
    async with factory() as session:
        session.add(Vehicle(id=vid, name="海豹", brand="比亚迪"))
        # 两天 HeatMetric 行（日期驱动 points），attention 给旧字段留值
        for d, attention in (("2026-05-19", 500.0), ("2026-05-20", 600.0),
                             ("2026-05-21", 700.0)):
            session.add(HeatMetric(vehicle_id=vid, date=date.fromisoformat(d),
                                   attention_index=attention))
        # 指数：05-19 两源齐（dy max=3000 / xhs max=600 都出现在这天 → 双 100），
        # 05-20 只有 dy 半值（1500/3000=50，无 xhs → composite=50），
        # 05-21 dy=0（指数滞后形态）→ 0 值视为无数据 → composite=None
        rows = [
            (SearchIndexMetric(vehicle_id=vid, date=date.fromisoformat("2026-05-19"),
                               source="douyin", keyword="海豹", index_value=3000.0),
             SearchIndexMetric(vehicle_id=vid, date=date.fromisoformat("2026-05-19"),
                               source="xiaohongshu", keyword="海豹", index_value=600.0)),
            (SearchIndexMetric(vehicle_id=vid, date=date.fromisoformat("2026-05-20"),
                               source="douyin", keyword="海豹", index_value=1500.0), None),
            (SearchIndexMetric(vehicle_id=vid, date=date.fromisoformat("2026-05-21"),
                               source="douyin", keyword="海豹", index_value=0.0), None),
        ]
        for a, b in rows:
            session.add(a)
            if b:
                session.add(b)
        await session.commit()

    async def override():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            resp = await c.get(
                f"/api/dashboard/trend/{vid}?start=2026-05-19&end=2026-05-21")
        assert resp.status_code == 200
        points = resp.json()["data"]
        assert [p["date"] for p in points] == ["2026-05-19", "2026-05-20", "2026-05-21"]
        assert points[0]["search_index"] == 100.0      # (3000/3000 + 600/600)/2
        assert points[0]["search_detail"] == {"douyin": 3000.0, "xiaohongshu": 600.0}
        assert points[1]["search_index"] == 50.0       # 1500/3000，单源
        assert points[1]["search_detail"] == {"douyin": 1500.0}
        assert points[2]["search_index"] is None       # dy 0 值=无数据 → 不合成
        assert points[2]["search_detail"] is None      # 合成不存在时 detail 也不给
        # 旧字段原样保留（前端回退路径）
        assert points[0]["attention_index"] == 500.0
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


# ── T1.4 评论级口碑分布端点 ──────────────────────────────────────────────
async def _comment_overview_factory(vid):
    """建独立 in-memory engine + factory，种数据后返回 (factory, engine)。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory, engine


async def test_comment_sentiment_overview_empty(client):
    """空库返回全 0 + total 0。"""
    vid = await _setup_vehicle_with_data(client)
    resp = await client.get(f"/api/dashboard/comment-sentiment-overview/{vid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"positive": 0, "negative": 0, "neutral": 0, "total": 0, "unanalyzed": 0}


async def test_comment_sentiment_overview_mapping(client):
    """dim_sentiment 均值正确映射到 positive/negative/neutral。"""
    vid = await _setup_vehicle_with_data(client)
    factory, engine = await _comment_overview_factory(vid)
    pid = "p_t1_4"
    async with factory() as s:
        s.add(Vehicle(id=vid, name="海豹", brand="比亚迪"))
        s.add(RawPost(id=pid, vehicle_id=vid, source="tavily", platform="weibo",
                      content="测帖", analysis_status="analyzed",
                      author_type="organic", published_at=datetime(2026, 5, 20)))
        s.add(AnalyzedPost(id="a1", post_id=pid, vehicle_id=vid,
                           sentiment="positive", subject="self",
                           confidence=0.9, model_used="test"))
        # positive: 均值 (0.8+0.6)/2=0.7 >0.3
        s.add(PostComment(id="c1", post_id=pid, vehicle_id=vid, cid="c1",
                         content="好", author="A", likes=1, platform="weibo",
                         dim_sentiment='{"续航": 0.8, "动力": 0.6}'))
        # negative: 均值 -0.7 <-0.3
        s.add(PostComment(id="c2", post_id=pid, vehicle_id=vid, cid="c2",
                         content="差", author="B", likes=2, platform="weibo",
                         dim_sentiment='{"刹车": -0.8, "异响": -0.6}'))
        # neutral: 均值 0.1 在 [-0.3,0.3]
        s.add(PostComment(id="c3", post_id=pid, vehicle_id=vid, cid="c3",
                         content="一般", author="C", likes=0, platform="weibo",
                         dim_sentiment='{"价格": 0.2, "外观": 0.0}'))
        await s.commit()

    from api.main import app
    async def _override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session] = _override
    try:
        resp = await client.get(f"/api/dashboard/comment-sentiment-overview/{vid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["positive"] == 1
        assert data["negative"] == 1
        assert data["neutral"] == 1
        assert data["total"] == 3
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def test_comment_sentiment_overview_excludes_dealer(client):
    """官方/经销商帖的评论不进评论级口碑（口径同 LISTING_CALIBER）。"""
    vid = await _setup_vehicle_with_data(client)
    factory, engine = await _comment_overview_factory(vid)
    async with factory() as s:
        s.add(Vehicle(id=vid, name="海豹", brand="比亚迪"))
        s.add(RawPost(id="p_org", vehicle_id=vid, source="tavily", platform="weibo",
                      content="用户帖", analysis_status="analyzed",
                      author_type="organic", published_at=datetime(2026, 5, 20)))
        s.add(AnalyzedPost(id="a_org", post_id="p_org", vehicle_id=vid,
                           sentiment="positive", subject="self",
                           confidence=0.9, model_used="test"))
        s.add(PostComment(id="c_org", post_id="p_org", vehicle_id=vid, cid="c_org",
                         content="赞", author="A", likes=1, platform="weibo",
                         dim_sentiment='{"续航": 0.8}'))
        s.add(RawPost(id="p_dl", vehicle_id=vid, source="tavily", platform="weibo",
                      content="4S 优惠", analysis_status="analyzed",
                      author_type="dealer", published_at=datetime(2026, 5, 20)))
        s.add(AnalyzedPost(id="a_dl", post_id="p_dl", vehicle_id=vid,
                           sentiment="positive", subject="self",
                           confidence=0.9, model_used="test"))
        s.add(PostComment(id="c_dl", post_id="p_dl", vehicle_id=vid, cid="c_dl",
                         content="快买", author="D", likes=5, platform="weibo",
                         dim_sentiment='{"续航": 0.9}'))
        await s.commit()

    from api.main import app
    async def _override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session] = _override
    try:
        resp = await client.get(f"/api/dashboard/comment-sentiment-overview/{vid}")
        data = resp.json()
        assert data["positive"] == 1   # 仅 organic 帖评论
        assert data["total"] == 1
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def test_comment_sentiment_overview_time_window(client):
    """时间窗跟随：窗内只命中 1 条评论。"""
    vid = await _setup_vehicle_with_data(client)
    factory, engine = await _comment_overview_factory(vid)
    async with factory() as s:
        s.add(Vehicle(id=vid, name="海豹", brand="比亚迪"))
        s.add(RawPost(id="p_in", vehicle_id=vid, source="tavily", platform="weibo",
                      content="窗内", analysis_status="analyzed",
                      author_type="organic", published_at=datetime(2026, 5, 20)))
        s.add(AnalyzedPost(id="a_in", post_id="p_in", vehicle_id=vid,
                           sentiment="positive", subject="self",
                           confidence=0.9, model_used="test"))
        s.add(PostComment(id="c_in", post_id="p_in", vehicle_id=vid, cid="c_in",
                         content="好", author="A", likes=1, platform="weibo",
                         dim_sentiment='{"续航": 0.8}'))
        s.add(RawPost(id="p_out", vehicle_id=vid, source="tavily", platform="weibo",
                      content="窗外", analysis_status="analyzed",
                      author_type="organic", published_at=datetime(2026, 3, 1)))
        s.add(AnalyzedPost(id="a_out", post_id="p_out", vehicle_id=vid,
                           sentiment="positive", subject="self",
                           confidence=0.9, model_used="test"))
        s.add(PostComment(id="c_out", post_id="p_out", vehicle_id=vid, cid="c_out",
                         content="好", author="B", likes=1, platform="weibo",
                         dim_sentiment='{"续航": 0.8}'))
        await s.commit()

    from api.main import app
    async def _override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session] = _override
    try:
        resp = await client.get(
            f"/api/dashboard/comment-sentiment-overview/{vid}"
            f"?start=2026-05-19&end=2026-05-21")
        data = resp.json()
        assert data["positive"] == 1
        assert data["total"] == 1
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


# ── T1.5 评论级负面声量趋势端点 ──────────────────────────────────────────
async def _seed_comment_trend_data(factory, vid):
    """种 2 天评论：2026-05-20 一正一负，2026-05-21 两负；窗外 1 评论不计。"""
    async with factory() as s:
        s.add(Vehicle(id=vid, name="海豹", brand="比亚迪"))
        s.add(RawPost(id="p20", vehicle_id=vid, source="tavily", platform="weibo",
                      content="帖20", analysis_status="analyzed",
                      author_type="organic", published_at=datetime(2026, 5, 20)))
        s.add(AnalyzedPost(id="a20", post_id="p20", vehicle_id=vid,
                           sentiment="positive", subject="self",
                           confidence=0.9, model_used="test"))
        s.add(PostComment(id="c20p", post_id="p20", vehicle_id=vid, cid="c20p",
                         content="好", author="A", likes=1, platform="weibo",
                         dim_sentiment='{"续航": 0.8}'))  # positive
        s.add(PostComment(id="c20n", post_id="p20", vehicle_id=vid, cid="c20n",
                         content="差", author="B", likes=2, platform="weibo",
                         dim_sentiment='{"刹车": -0.7}'))  # negative
        s.add(RawPost(id="p21", vehicle_id=vid, source="tavily", platform="weibo",
                      content="帖21", analysis_status="analyzed",
                      author_type="organic", published_at=datetime(2026, 5, 21)))
        s.add(AnalyzedPost(id="a21", post_id="p21", vehicle_id=vid,
                           sentiment="positive", subject="self",
                           confidence=0.9, model_used="test"))
        s.add(PostComment(id="c21n1", post_id="p21", vehicle_id=vid, cid="c21n1",
                         content="糟", author="C", likes=0, platform="weibo",
                         dim_sentiment='{"异响": -0.6}'))  # negative
        s.add(PostComment(id="c21n2", post_id="p21", vehicle_id=vid, cid="c21n2",
                         content="烂", author="D", likes=1, platform="weibo",
                         dim_sentiment='{"质量": -0.5}'))  # negative
        # 窗外帖（2026-03-01）评论不应计入
        s.add(RawPost(id="pout", vehicle_id=vid, source="tavily", platform="weibo",
                      content="窗外", analysis_status="analyzed",
                      author_type="organic", published_at=datetime(2026, 3, 1)))
        s.add(AnalyzedPost(id="aout", post_id="pout", vehicle_id=vid,
                           sentiment="positive", subject="self",
                           confidence=0.9, model_used="test"))
        s.add(PostComment(id="cout", post_id="pout", vehicle_id=vid, cid="cout",
                         content="差", author="E", likes=0, platform="weibo",
                         dim_sentiment='{"刹车": -0.8}'))  # negative but out of window
        await s.commit()


async def test_comment_sentiment_trend_daily_aggregation(client):
    """日级评论情感趋势：5/20 = 1正1负，5/21 = 2负；窗外评论不计。"""
    vid = await _setup_vehicle_with_data(client)
    factory, engine = await _comment_overview_factory(vid)
    await _seed_comment_trend_data(factory, vid)
    from api.main import app
    async def _override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session] = _override
    try:
        resp = await client.get(
            f"/api/dashboard/comment-sentiment-trend/{vid}"
            f"?start=2026-05-20&end=2026-05-21")
        assert resp.status_code == 200
        data = resp.json()
        by_date = {d["date"]: d for d in data}
        assert by_date["2026-05-20"]["positive"] == 1
        assert by_date["2026-05-20"]["negative"] == 1
        assert by_date["2026-05-21"]["negative"] == 2
        assert by_date["2026-05-21"]["positive"] == 0
        # 窗外 2026-03-01 不在结果里
        assert "2026-03-01" not in by_date
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def test_comment_sentiment_trend_counts_comments_not_posts(client):
    """关键断言：数的是评论而非帖——同帖多评论分别计数（5/20 同帖 2 评论各计）。"""
    vid = await _setup_vehicle_with_data(client)
    factory, engine = await _comment_overview_factory(vid)
    await _seed_comment_trend_data(factory, vid)
    from api.main import app
    async def _override():
        async with factory() as session:
            yield session
    app.dependency_overrides[get_session] = _override
    try:
        resp = await client.get(
            f"/api/dashboard/comment-sentiment-trend/{vid}"
            f"?start=2026-05-20&end=2026-05-20")
        data = resp.json()
        d = next(x for x in data if x["date"] == "2026-05-20")
        # 1 帖带 2 评论（1正1负）——若数帖则 positive=1/negative=0；数评论则 1/1
        assert d["positive"] == 1
        assert d["negative"] == 1
        assert d["positive"] + d["negative"] + d["neutral"] == 2
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def test_comment_sentiment_trend_fills_missing_dates(client):
    """缺失日期填充为 0；空库返回窗口内每日全 0 行。"""
    vid = await _setup_vehicle_with_data(client)
    resp = await client.get(
        f"/api/dashboard/comment-sentiment-trend/{vid}"
        f"?start=2026-05-20&end=2026-05-22")
    assert resp.status_code == 200
    data = resp.json()
    dates = [d["date"] for d in data]
    assert dates == ["2026-05-20", "2026-05-21", "2026-05-22"]
    for d in data:
        assert d["positive"] == 0 and d["negative"] == 0 and d["neutral"] == 0


# ── D14 车队总览 ──
async def test_fleet_overview_empty(client):
    """空库返回 []。"""
    resp = await client.get("/api/dashboard/fleet-overview")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_fleet_overview_lists_and_sorts(client_with_session):
    """两车按健康分升序排（差的在前），含 name/health_score/week_change_rate/risk_level。"""
    client, session = client_with_session
    from datetime import date as _date, datetime as _datetime, timedelta as _td
    today = _date.today()
    pub = _datetime.combine(today - _td(days=2), _datetime.min.time())

    # v1：80% 正面 → 健康分高
    session.add(Vehicle(id="v1", name="星愿", brand="吉利银河"))
    for i in range(20):
        pid = f"v1-p{i}"
        session.add(RawPost(id=pid, vehicle_id="v1", source="tikhub", platform="weibo",
                            title=f"t{i}", content=f"c{i}", published_at=pub,
                            analysis_status="analyzed", author_type="organic"))
        session.add(AnalyzedPost(id=f"ap-{pid}", post_id=pid, vehicle_id="v1",
                                 sentiment="positive", model_used="t", subject="self"))
    # v2：80% 负面 → 健康分低（排在前）
    session.add(Vehicle(id="v2", name="海豹", brand="比亚迪"))
    for i in range(20):
        pid = f"v2-p{i}"
        session.add(RawPost(id=pid, vehicle_id="v2", source="tikhub", platform="weibo",
                            title=f"t{i}", content=f"c{i}", published_at=pub,
                            analysis_status="analyzed", author_type="organic"))
        session.add(AnalyzedPost(id=f"ap-{pid}", post_id=pid, vehicle_id="v2",
                                 sentiment="negative", model_used="t", subject="self"))
    await session.commit()

    resp = await client.get("/api/dashboard/fleet-overview")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    # 健康分升序：v2（负面多）在前
    assert data[0]["name"] == "海豹"
    assert data[1]["name"] == "星愿"
    assert data[0]["health_score"] < data[1]["health_score"]
    for item in data:
        assert {"id", "name", "brand", "health_score", "week_change_rate", "risk_level"} <= set(item.keys())
    # v2 负面率 100% → high；v1 正面 → low
    assert data[0]["risk_level"] == "high"
    assert data[1]["risk_level"] == "low"


async def test_fleet_overview_excludes_inactive(client_with_session):
    """status != active 的车不出现在车队总览。"""
    client, session = client_with_session
    session.add(Vehicle(id="v1", name="星愿", brand="吉利银河", status="active"))
    session.add(Vehicle(id="v2", name="海豹", brand="比亚迪", status="archived"))
    await session.commit()
    resp = await client.get("/api/dashboard/fleet-overview")
    assert resp.status_code == 200
    names = [v["name"] for v in resp.json()]
    assert "星愿" in names and "海豹" not in names


async def test_fleet_overview_insufficient_sample(client_with_session):
    """分析帖 <20 → risk_level=insufficient，health_score 仍计算（None when 0 帖）。"""
    client, session = client_with_session
    session.add(Vehicle(id="v1", name="星愿", brand="吉利银河"))
    # 仅 3 帖（<20）
    from datetime import date as _date, datetime as _datetime, timedelta as _td
    pub = _datetime.combine(_date.today() - _td(days=2), _datetime.min.time())
    for i in range(3):
        pid = f"v1-p{i}"
        session.add(RawPost(id=pid, vehicle_id="v1", source="tikhub", platform="weibo",
                            title=f"t{i}", content=f"c{i}", published_at=pub,
                            analysis_status="analyzed", author_type="organic"))
        session.add(AnalyzedPost(id=f"ap-{pid}", post_id=pid, vehicle_id="v1",
                                 sentiment="positive", model_used="t", subject="self"))
    await session.commit()
    resp = await client.get("/api/dashboard/fleet-overview")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["risk_level"] == "insufficient"
    assert data[0]["health_score"] is not None  # 3 正面 → 健康分 100


async def test_fleet_overview_empty_vehicle_health_none(client_with_session):
    """无分析帖的车：health_score=None，risk_level=insufficient。"""
    client, session = client_with_session
    session.add(Vehicle(id="v1", name="星愿", brand="吉利银河"))
    await session.commit()
    resp = await client.get("/api/dashboard/fleet-overview")
    data = resp.json()
    assert len(data) == 1
    assert data[0]["health_score"] is None
    assert data[0]["risk_level"] == "insufficient"
    assert data[0]["week_change_rate"] is None


@pytest.mark.asyncio
async def test_overview_no_data_health_score_none(client_with_session):
    """T4.1：analyzed_total<=0 时 /overview health_score=None（与车队统一，当前返 50）。"""
    client, session = client_with_session
    resp = await client.post("/api/vehicles", json={"name": "空车T41", "brand": "测试"})
    vid = resp.json()["id"]
    # 不灌任何帖
    resp = await client.get(f"/api/dashboard/overview/{vid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["health_score"] is None, f"0 帖时 health_score 应为 None，实际 {data['health_score']}"
    assert data["sample_insufficient"] is True


@pytest.mark.asyncio
async def test_fleet_overview_upper_bound_excludes_future_posts(client_with_session):
    """T4.2：车队 30 天窗有上界，未来 published_at 帖不计入（当前无上界）。"""
    client, session = client_with_session
    resp = await client.post("/api/vehicles", json={"name": "车队上界T42", "brand": "测试"})
    vid = resp.json()["id"]
    # 灌一个未来日期的 self organic 帖
    future = date.today() + timedelta(days=10)
    session.add(RawPost(
        id="p-future", vehicle_id=vid, source="tikhub", platform="weibo",
        title="未来帖", content="未来帖" * 2, author="作者", url="https://x/p-future",
        published_at=datetime.combine(future, datetime.min.time()), likes=10, comments=5, shares=0,
        analysis_status="analyzed", relevance_score=1.0, author_type="organic",
    ))
    session.add(AnalyzedPost(
        id="ap-p-future", post_id="p-future", vehicle_id=vid,
        sentiment="positive", model_used="test", subject="self",
    ))
    await session.commit()
    resp = await client.get("/api/dashboard/fleet-overview")
    assert resp.status_code == 200
    data = resp.json()
    fleet_item = next((v for v in data if v.get("id") == vid), None)
    assert fleet_item is not None
    # 未来帖不应计入车队 30 天窗
    assert fleet_item["analyzed_total"] == 0, f"未来帖不应计入，实际 {fleet_item['analyzed_total']}"
