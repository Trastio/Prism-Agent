"""负面雷达端点测试（2026-09-16）。

口径：SELF_ONLY + AUTHENTIC_AUTHOR + irrelevant 结构性排除（无 AnalyzedPost 行）。
风险档位三因子：负面率 / 周环比 / TOP 吐槽影响力分。
"""

import json
from datetime import date, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.database import get_session
from models.schemas import AnalyzedPost, Base, EventGroup, RawPost, Vehicle

NOW = datetime.now()
PREV = NOW - timedelta(days=10)  # 上周


def _post(pid, vid, *, sentiment="positive", subject="self", author_type=None,
          likes=10, comments=5, shares=0, platform="weibo", published=None, dims=None):
    p = RawPost(
        id=pid, vehicle_id=vid, source="tikhub", platform=platform,
        title=f"帖{pid}", content=f"内容{pid}", author="作者" + pid,
        url=f"https://x/{pid}", published_at=published or NOW,
        likes=likes, comments=comments, shares=shares,
        analysis_status="analyzed", relevance_score=1.0, author_type=author_type,
    )
    ap = AnalyzedPost(
        id=f"ap-{pid}", post_id=pid, vehicle_id=vid, sentiment=sentiment,
        model_used="test", subject=subject,
        dim_sentiment=json.dumps(dims, ensure_ascii=False) if dims else None,
    )
    return p, ap


def _add(s, p, ap):
    s.add(p)
    if ap is not None:
        s.add(ap)


@pytest_asyncio.fixture
async def env():
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
            # ── v1 富场景：7 负 + 20 正 = 27 帖 → 负面率 25.9%、TOP 影响 12 万 → high ──
            s.add(Vehicle(id="v1", name="星愿", brand="吉利银河"))
            _add(s, *_post("v1-n1", "v1", sentiment="negative", likes=120_000, comments=100,
                           dims={"续航里程": 0.1, "空间": 0.9}))
            _add(s, *_post("v1-n2", "v1", sentiment="negative", likes=1000,
                           dims={"续航里程": 0.2}))
            for i in range(3, 7):  # 本周负面 n3..n6
                _add(s, *_post(f"v1-n{i}", "v1", sentiment="negative",
                               likes=500 * i, dims={"空间": 0.3}))
            _add(s, *_post("v1-n7", "v1", sentiment="negative", likes=800, published=PREV))
            for i in range(20):  # 口碑正面帖
                dims = {"续航里程": 0.8} if i == 0 else None
                _add(s, *_post(f"v1-p{i}", "v1", sentiment="positive", dims=dims))
            # 必须被口径排除的三类
            _add(s, *_post("v1-x-official", "v1", sentiment="negative",
                           author_type="brand_official", likes=999_999))
            _add(s, *_post("v1-x-comp", "v1", sentiment="negative",
                           subject="competitor", likes=888_888))
            irr, _ = _post("v1-x-irr", "v1", sentiment="negative", likes=777_777)
            irr.analysis_status = "irrelevant"
            s.add(irr)  # 无 AnalyzedPost 行 → 结构性排除
            # 负面事件：e1 负面最多（5），e3 无负面应被排除
            s.add(EventGroup(id="e1", vehicle_id="v1", event_tag="续航争议",
                             start_date=date(2026, 9, 1), end_date=date(2026, 9, 10),
                             post_count=10, source="social",
                             sentiment_distribution=json.dumps({"negative": 5, "positive": 1})))
            s.add(EventGroup(id="e2", vehicle_id="v1", event_tag="提车热潮",
                             start_date=date(2026, 9, 2), end_date=date(2026, 9, 8),
                             post_count=30, source="social",
                             sentiment_distribution=json.dumps({"negative": 2, "positive": 20})))
            s.add(EventGroup(id="e3", vehicle_id="v1", event_tag="发布会",
                             start_date=date(2026, 9, 3), end_date=date(2026, 9, 5),
                             post_count=8, source="news",
                             sentiment_distribution=json.dumps({"positive": 9})))

            # ── v2 样本不足：3 帖 ──
            s.add(Vehicle(id="v2", name="铂智", brand="丰田"))
            _add(s, *_post("v2-n1", "v2", sentiment="negative"))
            _add(s, *_post("v2-p1", "v2"))
            _add(s, *_post("v2-p2", "v2"))

            # ── v3 低风险：2 负（都在上周）+ 20 正 ──
            s.add(Vehicle(id="v3", name="M03", brand="小鹏"))
            for i in range(2):
                _add(s, *_post(f"v3-n{i}", "v3", sentiment="negative",
                               likes=100, published=PREV))
            for i in range(20):
                _add(s, *_post(f"v3-p{i}", "v3"))

            # ── v4 中位数边界：5 负互动 [8,50,100,200,500]，中位数=100 ──
            s.add(Vehicle(id="v4", name="风云T7", brand="奇瑞"))
            for eng in (8, 50, 100, 200, 500):
                _add(s, *_post(f"v4-e{eng}", "v4", sentiment="negative",
                               likes=eng, comments=0, shares=0))
            await s.commit()
            yield c, s
    app.dependency_overrides.clear()
    await engine.dispose()


class TestNegativeRadar:
    @pytest.mark.asyncio
    async def test_caliber_exclusions_and_ranking(self, env):
        """官号/竞品/irrelevant 负面帖不进榜；影响力分降序。

        v1 七条负面帖互动降序：[120100, 3005, 2505, 2005, 1505, 1005, 805]，
        中位数（index 3）= 2005，故仅 4 条（n1/n4/n5/n6）进榜——D7 动态门槛。
        """
        client, _ = env
        r = (await client.get("/api/dashboard/negative-radar/v1")).json()
        assert r["negative_total"] == 7  # 中位数门槛只过滤榜单，不过滤计数
        ids = [c["id"] for c in r["top_complaints"]]
        assert ids[0] == "v1-n1"  # 120000+100+0 = 120100 最高
        assert set(ids) == {"v1-n1", "v1-n4", "v1-n5", "v1-n6"}  # 仅互动≥中位数 2005
        assert "v1-x-official" not in ids and "v1-x-comp" not in ids and "v1-x-irr" not in ids
        scores = [c["influence_score"] for c in r["top_complaints"]]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_top_neg_dims_lowest_scores(self, env):
        client, _ = env
        r = (await client.get("/api/dashboard/negative-radar/v1")).json()
        assert r["top_complaints"][0]["top_neg_dims"] == ["续航里程", "空间"]  # 0.1 < 0.9

    @pytest.mark.asyncio
    async def test_negative_dims_rate(self, env):
        client, _ = env
        r = (await client.get("/api/dashboard/negative-radar/v1")).json()
        dims = {d["dim"]: d for d in r["negative_dims"]}
        # 续航里程：负面帖 n1+n2 = 2，全量分母 + p0 = 3
        assert dims["续航里程"]["negative_count"] == 2
        assert dims["续航里程"]["total_count"] == 3
        assert abs(dims["续航里程"]["negative_rate"] - 2 / 3) < 1e-4  # 端点 round 4 位
        assert dims["空间"]["negative_rate"] == 1.0  # 5/5
        assert r["negative_dims"][0]["dim"] == "空间"  # 负面次数最多

    @pytest.mark.asyncio
    async def test_negative_events_ranking(self, env):
        client, _ = env
        r = (await client.get("/api/dashboard/negative-radar/v1")).json()
        evs = r["negative_events"]
        assert len(evs) == 2  # e3 无负面被排除
        assert evs[0]["event_tag"] == "续航争议" and evs[0]["negative_posts"] == 5
        assert evs[1]["negative_posts"] == 2

    @pytest.mark.asyncio
    async def test_risk_levels(self, env):
        client, _ = env
        v1 = (await client.get("/api/dashboard/negative-radar/v1")).json()
        assert v1["risk_level"] == "high"  # 率 25.9%(+2) + 影响力 12 万(+2) [+ 环比+500%(+2)]
        assert len(v1["risk_reasons"]) >= 2
        v2 = (await client.get("/api/dashboard/negative-radar/v2")).json()
        assert v2["risk_level"] == "insufficient"  # 3 帖 < 20
        v3 = (await client.get("/api/dashboard/negative-radar/v3")).json()
        assert v3["risk_level"] == "low"
        assert v3["risk_reasons"] == ["三因子均未触发风险阈值"]

    @pytest.mark.asyncio
    async def test_wow_weekly_change(self, env):
        client, _ = env
        v1 = (await client.get("/api/dashboard/negative-radar/v1")).json()
        assert v1["negative_week"] == 6      # n1..n6 本周
        assert v1["negative_prev_week"] == 1  # n7 上周
        assert v1["negative_wow"] == 500.0
        v3 = (await client.get("/api/dashboard/negative-radar/v3")).json()
        assert v3["negative_wow"] == -100.0   # 上周 2 → 本周 0

    @pytest.mark.asyncio
    async def test_median_threshold_boundary(self, env):
        """D7：互动中位数门槛——低于中位数的帖不进榜。

        v4 五条负面帖互动 [8,50,100,200,500]，中位数（index 2）= 100，
        仅 100/200/500 三条达标，8/50 被滤除。
        """
        client, _ = env
        r = (await client.get("/api/dashboard/negative-radar/v4")).json()
        ids = [c["id"] for c in r["top_complaints"]]
        assert ids == ["v4-e500", "v4-e200", "v4-e100"]  # 降序
        assert "v4-e8" not in ids and "v4-e50" not in ids

    @pytest.mark.asyncio
    async def test_no_padding_when_few_qualify(self, env):
        """D7：达标帖不足 10 条时不凑数——v1 仅 4 条达标，返回 4 条而非凑满 10。"""
        client, _ = env
        r = (await client.get("/api/dashboard/negative-radar/v1")).json()
        assert len(r["top_complaints"]) == 4  # 7 条负面中仅 4 条互动≥中位数
