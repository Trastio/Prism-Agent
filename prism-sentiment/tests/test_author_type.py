"""Q5 作者分层（2026-09-15）：classify_author_type 分类 + 口径端点 + Agent 新端点。"""

import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.database import get_session
from models.schemas import AnalyzedPost, Base, PostComment, RawPost, Vehicle
from pipeline.collectors.post_utils import classify_author_type


# ── 分类函数 ─────────────────────────────────────────────────────────────────

class TestClassify:
    def test_official_exact_brand(self):
        assert classify_author_type(
            "特斯拉", brand="特斯拉", vehicle_name="Model Y") == "brand_official"

    def test_official_brand_plus_series(self):
        # 实测官号 "小鹏MONA"（brand=小鹏, 车型=小鹏MONA M03）
        assert classify_author_type(
            "小鹏MONA", brand="小鹏", vehicle_name="小鹏MONA M03") == "brand_official"

    def test_official_brand_is_full_name(self):
        assert classify_author_type(
            "小米汽车", brand="小米汽车", vehicle_name="小米SU7") == "brand_official"

    def test_official_with_separators(self):
        assert classify_author_type(
            "小 鹏｜MONA", brand="小鹏", vehicle_name="小鹏MONA M03") == "brand_official"

    def test_official_beats_media_token(self):
        # "小鹏汽车" 含"汽车"媒体 token，但官号优先
        assert classify_author_type(
            "小鹏汽车", brand="小鹏", vehicle_name="小鹏MONA M03") == "brand_official"

    def test_fan_account_is_organic(self):
        assert classify_author_type(
            "小鹏车主老王", brand="小鹏", vehicle_name="小鹏MONA M03") == "organic"

    def test_dealer_author(self):
        assert classify_author_type(
            "海南小鹏贩卖机", brand="小鹏", vehicle_name="小鹏MONA M03") == "dealer"

    def test_dealer_4s_title(self):
        assert classify_author_type(
            "张三", title="4S店大促优惠", brand="小鹏", vehicle_name="小鹏MONA M03") == "dealer"

    def test_media_tokens(self):
        for a in ["车圈朵教主Dora", "橘子选车指南", "正经车评人", "易车榜", "汽车洋葱圈"]:
            assert classify_author_type(a) == "auto_media"

    def test_media_traditional_char(self):
        assert classify_author_type("車界说") == "auto_media"

    def test_organic(self):
        for a in ["阿至开su7", "momo", "鱼儿先生", "杨琴Johnny", "苏黎世贝勒爷"]:
            assert classify_author_type(a) == "organic"

    def test_empty_author(self):
        assert classify_author_type("") == "organic"


# ── 端点（口径 + Agent 新端点）───────────────────────────────────────────────

@pytest_asyncio.fixture
async def env():
    """(client, session) 共享同一内存库。"""
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


async def _seed(s, vid, pid, sentiment, author, author_type,
                likes=10, dim=None, platform="weibo"):
    s.add(RawPost(
        id=pid, vehicle_id=vid, source="tikhub", platform=platform,
        title=f"帖{pid}", content=f"内容{pid}", author=author,
        url=f"https://x.com/{pid}", published_at=datetime(2026, 9, 10),
        likes=likes, comments=1, shares=0, analysis_status="analyzed",
        author_type=author_type,
    ))
    s.add(AnalyzedPost(
        id=f"ap-{pid}", post_id=pid, vehicle_id=vid, sentiment=sentiment,
        model_used="test", dim_sentiment=dim,
    ))


class TestSentimentCaliber:
    @pytest.mark.asyncio
    async def test_overview_excludes_official_and_dealer(self, env):
        client, s = env
        s.add(Vehicle(id="v1", name="小鹏MONA M03", brand="小鹏"))
        await s.commit()
        # 1 官方正面 + 1 经销商正面 + 1 用户正面 + 1 用户负面
        await _seed(s, "v1", "p1", "positive", "小鹏汽车", "brand_official", likes=99)
        await _seed(s, "v1", "p2", "positive", "海南小鹏贩卖机", "dealer")
        await _seed(s, "v1", "p3", "positive", "老王", "organic")
        await _seed(s, "v1", "p4", "negative", "小李", "organic")
        await s.commit()

        r = (await client.get("/api/dashboard/overview/v1")).json()
        # 官方/经销商正面被排除：positive=1（若未排除=3）
        assert r["positive"] == 1
        assert r["negative"] == 1
        assert r["analyzed_posts"] == 2
        # 50 + (1-1)/2*50 = 50（未排除会是 50+(3-1)/4*50=75）
        assert r["health_score"] == 50.0

    @pytest.mark.asyncio
    async def test_sentiment_trend_excludes(self, env):
        client, s = env
        s.add(Vehicle(id="v1", name="海豹", brand="比亚迪"))
        await s.commit()
        await _seed(s, "v1", "p1", "positive", "比亚迪汽车", "brand_official")
        await _seed(s, "v1", "p2", "negative", "老王", "organic")
        await s.commit()

        r = await client.get("/api/dashboard/sentiment-trend/v1"
                             "?start=2026-09-01&end=2026-09-30")
        days = {d["date"]: d for d in r.json()}
        assert days["2026-09-10"]["positive"] == 0   # 官方帖被排除
        assert days["2026-09-10"]["negative"] == 1

    @pytest.mark.asyncio
    async def test_top_posts_excludes_official_and_dealer(self, env):
        """热帖榜排除官方/经销商帖（2026-09-25 口径对齐 negative-radar）。

        旧口径保留官方帖带徽标，现改为排除——dealer/official 不应上热帖榜。
        """
        client, s = env
        s.add(Vehicle(id="v1", name="特斯拉Model Y", brand="特斯拉"))
        await s.commit()
        await _seed(s, "v1", "p1", "positive", "特斯拉", "brand_official", likes=999)
        await _seed(s, "v1", "p2", "neutral", "老王", "organic", likes=5)
        await s.commit()

        r = await client.get("/api/dashboard/top-posts/v1")
        items = r.json()
        # brand_official 帖被排除，只剩 organic
        assert len(items) == 1
        assert items[0]["author_type"] == "organic"
        assert items[0]["likes"] == 5

    @pytest.mark.asyncio
    async def test_posts_list_carries_author_type(self, env):
        client, s = env
        s.add(Vehicle(id="v1", name="海豹", brand="比亚迪"))
        await s.commit()
        await _seed(s, "v1", "p1", "positive", "海南小鹏贩卖机", "dealer")
        await s.commit()

        r = await client.get("/api/dashboard/posts/v1")
        assert r.json()["items"][0]["author_type"] == "dealer"


class TestTopPostsRelevance:
    @pytest.mark.asyncio
    async def test_top_posts_excludes_irrelevant(self, env):
        """星愿实采暴露的展示层 bug：LLM 判无关的高互动帖（K-pop"星愿降临"）
        不应登上热帖榜——过滤层工作(rel=0.0)，热帖端点此前漏挂 relevant 过滤。"""
        client, s = env
        s.add(Vehicle(id="v1", name="星愿", brand="吉利银河"))
        await s.commit()
        s.add(RawPost(
            id="p1", vehicle_id="v1", source="tikhub", platform="xiaohongshu",
            title="星愿降临 我在微店等你", content="x", author="曺薇娟", url="u1",
            likes=14639, comments=1437, analysis_status="irrelevant", relevance_score=0.0,
        ))
        await _seed(s, "v1", "p2", "positive", "老王", "organic", likes=100)
        await s.commit()

        r = await client.get("/api/dashboard/top-posts/v1")
        assert [i["id"] for i in r.json()] == ["p2"]

    @pytest.mark.asyncio
    async def test_top_posts_sentiment_filter(self, env):
        """吐槽榜地基：sentiment=negative 只返回负面帖（按互动降序）。"""
        client, s = env
        s.add(Vehicle(id="v1", name="海豹", brand="比亚迪"))
        await s.commit()
        await _seed(s, "v1", "p1", "positive", "A", "organic", likes=999)
        await _seed(s, "v1", "p2", "negative", "B", "organic", likes=500)
        await _seed(s, "v1", "p3", "negative", "C", "organic", likes=50)
        await s.commit()

        r = await client.get("/api/dashboard/top-posts/v1?sentiment=negative")
        assert [i["id"] for i in r.json()] == ["p2", "p3"]

    @pytest.mark.asyncio
    async def test_posts_list_excludes_irrelevant(self, env):
        client, s = env
        s.add(Vehicle(id="v1", name="海豹", brand="比亚迪"))
        await s.commit()
        s.add(RawPost(
            id="p1", vehicle_id="v1", source="tikhub", platform="weibo",
            title="无关帖", content="x", author="路人", url="u1",
            likes=10, analysis_status="irrelevant", relevance_score=0.0,
        ))
        await _seed(s, "v1", "p2", "positive", "老王", "organic")
        await s.commit()

        r = await client.get("/api/dashboard/posts/v1")
        assert [i["id"] for i in r.json()["items"]] == ["p2"]
        assert r.json()["total"] == 1


class TestAgentEndpoints:
    @pytest.mark.asyncio
    async def test_dim_examples_posts_and_comments(self, env):
        client, s = env
        s.add(Vehicle(id="v1", name="海豹", brand="比亚迪"))
        await s.commit()
        # 维度键是 15 维全名（如 续航里程）；评论按本地 ABSA 实际形态存
        # ascii 转义 JSON——端点须对两种形态都能命中
        await _seed(s, "v1", "p1", "negative", "老王", "organic",
                    dim='{"续航里程": -2, "空间": 1}')
        await _seed(s, "v1", "p2", "positive", "小李", "organic",
                    dim='{"续航里程": 1}')
        await s.commit()
        s.add(PostComment(
            id="c1", post_id="p1", vehicle_id="v1", cid="c1",
            content="续航虚得离谱", author="网友A", likes=50, platform="weibo",
            dim_sentiment='{"\\u7eed\\u822a\\u91cc\\u7a0b": -1}',  # 转义形态（生产实测）
        ))
        s.add(PostComment(
            id="c2", post_id="p1", vehicle_id="v1", cid="c2",
            content="续航还行", author="网友B", likes=5, platform="weibo",
            dim_sentiment='{"续航里程": 1}',
        ))
        await s.commit()

        # dim=续航 包含匹配 续航里程
        r = await client.get("/api/dashboard/dim-examples/v1?dim=续航")
        data = r.json()
        assert data["dim"] == "续航"
        assert len(data["posts"]) == 2          # 两帖都提及续航
        assert all(p["matched_dim"] == "续航里程" for p in data["posts"])
        assert len(data["comments"]) == 2       # 转义+原文两种形态都命中
        assert set(data["available_dims"]) >= {"续航里程", "空间"}

        r = await client.get("/api/dashboard/dim-examples/v1?dim=续航&sentiment=negative")
        data = r.json()
        assert [p["dim_score"] for p in data["posts"]] == [-2]   # 只剩负面帖
        assert [c["dim_score"] for c in data["comments"]] == [-1]  # 只剩负面评论
        assert data["comments"][0]["content"] == "续航虚得离谱"

    @pytest.mark.asyncio
    async def test_dim_examples_excludes_dealer(self, env):
        client, s = env
        s.add(Vehicle(id="v1", name="海豹", brand="比亚迪"))
        await s.commit()
        await _seed(s, "v1", "p1", "positive", "海南小鹏贩卖机", "dealer",
                    dim='{"续航里程": 2}')
        await s.commit()

        r = await client.get("/api/dashboard/dim-examples/v1?dim=续航")
        assert r.json()["posts"] == []

    @pytest.mark.asyncio
    async def test_post_comments(self, env):
        client, s = env
        s.add(Vehicle(id="v1", name="海豹", brand="比亚迪"))
        await s.commit()
        await _seed(s, "v1", "p1", "positive", "老王", "organic")
        await s.commit()
        s.add(PostComment(id="c1", post_id="p1", vehicle_id="v1", cid="c1",
                          content="顶", author="A", likes=1, platform="weibo"))
        s.add(PostComment(id="c2", post_id="p1", vehicle_id="v1", cid="c2",
                          content="热评", author="B", likes=10, platform="weibo",
                          dim_sentiment='{"续航": -1}'))
        await s.commit()

        r = await client.get("/api/dashboard/post-comments/v1/p1")
        data = r.json()
        assert data["post"]["id"] == "p1"
        assert [c["content"] for c in data["comments"]] == ["热评", "顶"]  # 按赞排序
        assert data["comments"][0]["dim_sentiment"] == {"续航": -1}

        # 他车 post_id → 404（越权防护）
        r = await client.get("/api/dashboard/post-comments/v2/p1")
        assert r.status_code == 404
