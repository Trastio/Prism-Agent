"""口径一致性横扫（2026-09-15 举一反三收口）。

星愿实采暴露的 bug 类：LLM 判无关的帖（analysis_status='irrelevant'）从展示层
泄漏（热帖榜/词云/平台分布/周报/锚点对话/热度引擎共 8+ 处）。本文件种一条带
独特标记词的高互动无关帖，横扫所有出口——**以后新增任何出数端点，都应在这里
补一行**。
"""

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
from models.schemas import AnalyzedPost, Base, RawPost, Vehicle

IRR_TITLE = "星愿降临薯条胡辣汤"   # 独特标记词：薯条/胡辣汤 只出现在无关帖


def _post(pid, vid, title, status="analyzed", platform="weibo",
          likes=10, comments=5, published=None, sentiment=None,
          author_type="organic", subject=None, opinion_tags=None, content=None):
    p = RawPost(
        id=pid, vehicle_id=vid, source="tikhub", platform=platform,
        title=title, content=content or title * 2, author="作者" + pid, url=f"https://x/{pid}",
        published_at=published or datetime(2026, 9, 10),
        likes=likes, comments=comments, shares=0,
        analysis_status=status, relevance_score=0.0 if status == "irrelevant" else 1.0,
        author_type=author_type,
    )
    if status != "irrelevant":
        import json as _json
        ap = AnalyzedPost(
            id=f"ap-{pid}", post_id=pid, vehicle_id=vid,
            sentiment=sentiment or "neutral", model_used="test",
            subject=subject,
            opinion_tags=_json.dumps(opinion_tags) if opinion_tags else None,
        )
    else:
        ap = None
    return p, ap


@pytest_asyncio.fixture
async def env():
    """(client, session) 同一内存库，预置 1 车 + 1 无关帖 + 1 正常帖。"""
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
            s.add(Vehicle(id="v1", name="星愿", brand="吉利银河"))
            await s.commit()
            p_irr, _ = _post("p-irr", "v1", IRR_TITLE, status="irrelevant",
                             likes=14639, comments=1437)
            p_ok, ap_ok = _post("p-ok", "v1", "吉利星愿提车分享", likes=100, comments=50,
                                sentiment="positive")
            s.add(p_irr); s.add(p_ok); s.add(ap_ok)
            await s.commit()
            yield c, s
    app.dependency_overrides.clear()
    await engine.dispose()


class TestRelevanceCaliberSweep:
    @pytest.mark.asyncio
    async def test_top_posts(self, env):
        client, _ = env
        items = (await client.get("/api/dashboard/top-posts/v1")).json()
        assert [i["id"] for i in items] == ["p-ok"]

    @pytest.mark.asyncio
    async def test_posts_list(self, env):
        client, _ = env
        data = (await client.get("/api/dashboard/posts/v1")).json()
        assert data["total"] == 1 and data["items"][0]["id"] == "p-ok"

    @pytest.mark.asyncio
    async def test_word_cloud(self, env):
        client, _ = env
        words = (await client.get("/api/dashboard/word-cloud/v1?limit=50")).json()
        names = {w["name"] for w in words}
        assert not ({"薯条", "胡辣汤"} & names), "无关帖文本不得进词云"

    @pytest.mark.asyncio
    async def test_platform_distribution(self, env):
        client, _ = env
        dist = (await client.get("/api/dashboard/platform-distribution/v1")).json()
        weibo = next(d for d in dist if d["platform"] == "weibo")
        assert weibo["count"] == 1  # 无关帖不计声量

    @pytest.mark.asyncio
    async def test_overview_total(self, env):
        client, _ = env
        ov = (await client.get("/api/dashboard/overview/v1")).json()
        assert ov["total_posts"] == 1

    @pytest.mark.asyncio
    async def test_weekly_digest_prompt(self, env):
        """周报喂给 LLM 的内容（总帖数/热门帖子）不得含无关帖。"""
        client, s = env
        # 让两帖都落进默认周窗（本周）
        for pid in ("p-irr", "p-ok"):
            await s.execute(
                RawPost.__table__.update().where(RawPost.id == pid)
                .values(published_at=datetime.now() - timedelta(days=1))
            )
        await s.commit()
        prompts: list[str] = []

        async def fake_llm(prompt, timeout=60):
            prompts.append(prompt)
            return "摘要"

        with patch("api.routes.reports.call_llm", new=fake_llm):
            r = await client.post("/api/reports/weekly-digest", json={"vehicle_id": "v1"})
        assert r.status_code == 200
        assert prompts, "LLM 应被调用"
        assert "薯条" not in prompts[0] and "胡辣汤" not in prompts[0]
        assert "提车分享" in prompts[0]


class TestHeatCaliber:
    @pytest.mark.asyncio
    async def test_heat_excludes_irrelevant(self):
        """热度四指标（discussion/media/interaction）不累计无关帖的互动。"""
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:", echo=False,
            connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as s:
            s.add(Vehicle(id="v1", name="星愿", brand="吉利银河"))
            day = datetime(2026, 9, 10)
            p_irr, _ = _post("h-irr", "v1", "无关", status="irrelevant",
                             likes=5000, comments=900, published=day)
            p_ok, ap_ok = _post("h-ok", "v1", "正常", likes=10, comments=5, published=day)
            n_ok, n_ap = _post("h-news", "v1", "新闻", platform="news", published=day)
            s.add_all([p_irr, p_ok, ap_ok, n_ok, n_ap])
            await s.commit()

            calc = HeatMetricCalculator(s)
            m = await calc.calculate_daily("v1", date(2026, 9, 10))
            assert m is not None
            assert m.discussion_volume == 5      # 只算正常社媒帖评论
            assert m.media_volume == 1
            assert m.interaction_intensity == 10 * 1 + 5 * 5  # 赞×1+评×5，无关帖 5000/900 不进
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_heat_zeroes_stale_days(self):
        """范围内已无 relevant 帖的日子：旧 heat 行清零（attention 保留）——
        2026-09-16 实测 7 行僵尸（irrelevant-only 日 heat>0）。"""
        from models.schemas import HeatMetric
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:", echo=False,
            connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as s:
            s.add(Vehicle(id="v1", name="星愿", brand="吉利银河"))
            day = datetime(2026, 6, 7)
            p_irr, _ = _post("z-irr", "v1", "无关", status="irrelevant",
                             likes=400, comments=64, published=day)
            s.add(p_irr)
            # 模拟旧口径时代写入的污染行（该日当时帖子还算 relevant）
            s.add(HeatMetric(id="hm-stale", vehicle_id="v1", date=date(2026, 6, 7),
                             attention_index=88.8, discussion_volume=64,
                             media_volume=0, interaction_intensity=332.0))
            await s.commit()

            calc = HeatMetricCalculator(s)
            await calc.calculate_range("v1", date(2026, 6, 1), date(2026, 6, 30))
            stale = await s.get(HeatMetric, "hm-stale")
            assert stale.interaction_intensity == 0
            assert stale.discussion_volume == 0
            assert stale.attention_index == 88.8  # 搜索指数独立于帖子，保留
        await engine.dispose()


# ── LISTING_CALIBER 横扫（C1：brand_official/dealer/competitor/irrelevant） ──

OFFICIAL_TITLE = "官方发布会声明数据"   # 独特标记词：官方/发布会/声明/数据
COMP_TITLE = "竞品车型对比测试"          # 独特标记词：竞品/车型/对比/测试
OK_TITLE = "星愿性价比分享"              # 正常帖标记词


@pytest_asyncio.fixture
async def env_caliber():
    """(client, session) 预置 1 车 + 4 帖：正常/官方/竞品/无关。

    brand_official 帖高互动（验证不因互动高而泄漏）；竞品帖 subject='competitor'。
    """
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
            s.add(Vehicle(id="v1", name="星愿", brand="吉利银河"))
            # 正常帖（organic, self）
            p_ok, ap_ok = _post("p-ok", "v1", OK_TITLE, likes=100, comments=50,
                                sentiment="positive", subject="self",
                                opinion_tags=["性价比", "性价比"])  # 2 次过 min_count=2 门槛（Phase 5 T5.4）
            # 官方帖（brand_official, self, 高互动）
            p_off, ap_off = _post("p-off", "v1", OFFICIAL_TITLE, likes=9999,
                                  comments=500, sentiment="positive",
                                  author_type="brand_official", subject="self",
                                  opinion_tags=["官方宣传"])
            # 竞品帖（organic, competitor）
            p_comp, ap_comp = _post("p-comp", "v1", COMP_TITLE, likes=888,
                                    comments=99, sentiment="neutral",
                                    subject="competitor",
                                    opinion_tags=["竞品对比"])
            # 无关帖（irrelevant, 无 AnalyzedPost）
            p_irr, _ = _post("p-irr", "v1", "薯条胡辣汤", status="irrelevant",
                             likes=14639, comments=1437)
            s.add_all([p_ok, ap_ok, p_off, ap_off, p_comp, ap_comp, p_irr])
            await s.commit()
            yield c, s
    app.dependency_overrides.clear()
    await engine.dispose()


class TestListingCaliberSweep:
    """C1: LISTING_CALIBER 横扫——brand_official/dealer/competitor/irrelevant 帖
    不得进入任何展示端点。"""

    @pytest.mark.asyncio
    async def test_top_posts_excludes_official_competitor(self, env_caliber):
        client, _ = env_caliber
        items = (await client.get("/api/dashboard/top-posts/v1")).json()
        ids = [i["id"] for i in items]
        assert ids == ["p-ok"], f"只应含正常帖，实际: {ids}"

    @pytest.mark.asyncio
    async def test_word_cloud_excludes_official_competitor(self, env_caliber):
        client, _ = env_caliber
        words = (await client.get("/api/dashboard/word-cloud/v1?limit=50")).json()
        names = {w["name"] for w in words}
        # 官方帖/竞品帖的标记词不得进词云
        assert not ({"官方", "发布会", "声明", "竞品", "车型", "对比"} & names), \
            f"官方/竞品帖文本泄漏进词云: {names}"
        # 正常帖标记词应在
        assert "性价比" in names or "分享" in names, \
            f"正常帖文本缺失: {names}"

    @pytest.mark.asyncio
    async def test_top_opinions_excludes_official_competitor(self, env_caliber):
        client, _ = env_caliber
        opinions = (await client.get("/api/analysis/top-opinions/v1")).json()
        items = opinions["items"] if isinstance(opinions, dict) else opinions
        tags = {tag for tag, _ in items}
        assert tags == {"性价比"}, f"只应含正常帖观点标签，实际: {tags}"

    @pytest.mark.asyncio
    async def test_sentiment_trend_excludes_official_competitor(self, env_caliber):
        """sentiment-trend 口径：官方/竞品帖不进每日情感计数。"""
        client, s = env_caliber
        # 把帖发布日设到窗口内
        for pid in ("p-ok", "p-off", "p-comp"):
            await s.execute(
                RawPost.__table__.update().where(RawPost.id == pid)
                .values(published_at=datetime(2026, 9, 10))
            )
        await s.commit()
        r = await client.get(
            "/api/dashboard/sentiment-trend/v1?start=2026-09-09&end=2026-09-11")
        data = r.json()
        # 9/10 只应计 1 个 positive（p-ok），官方 positive 不计
        day = next(d for d in data if d["date"] == "2026-09-10")
        assert day["positive"] == 1, f"官方/竞品帖泄漏: {day}"

    @pytest.mark.asyncio
    async def test_dim_sentiment_excludes_official_competitor(self, env_caliber):
        """dim-sentiment 口径：官方/竞品帖的维度不进聚合。"""
        client, s = env_caliber
        from models.schemas import AnalyzedPost as AP
        import json as _json
        # 给 p-ok 和 p-off 都加 dim_sentiment
        await s.execute(
            AP.__table__.update().where(AP.post_id == "p-ok")
            .values(dim_sentiment=_json.dumps({"续航": 0.8})))
        await s.execute(
            AP.__table__.update().where(AP.post_id == "p-off")
            .values(dim_sentiment=_json.dumps({"续航": -0.9})))
        await s.commit()
        rows = (await client.get("/api/dashboard/dim-sentiment/v1")).json()
        row = next(r for r in rows if r["dim"] == "续航")
        # 只计 p-ok 的 0.8，p-off 的 -0.9 不进
        assert row["count"] == 1, f"官方帖泄漏进维度聚合: {row}"
        assert row["score"] == 0.8


class TestWeeklyDigestCaliber:
    """C3: weekly-digest 口径——published_at（非 analyzed_at）+ LISTING_CALIBER。
    情感计数与事件标签均不得用 analyzed_at 做时间过滤，且排除官方/竞品/无关帖。"""

    @pytest_asyncio.fixture
    async def env_weekly(self):
        """预置 1 车 + 4 帖，published_at 均落本周窗，analyzed_at 故意错配。"""
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
                s.add(Vehicle(id="v1", name="星愿", brand="吉利银河"))
                # 窗口：本周（today-7 ~ today）。published_at 设为昨天（窗内）。
                pub_in = datetime.now() - timedelta(days=1)
                # analyzed_at 故意设到 30 天前（窗外）——旧口径会漏算此帖。
                analyzed_out = datetime.now() - timedelta(days=30)

                # 正常帖（organic, self, positive）——应进周报
                p_ok, ap_ok = _post("w-ok", "v1", "星愿性价比分享", likes=100,
                                    comments=50, published=pub_in,
                                    sentiment="positive", subject="self")
                ap_ok.event_tags = json.dumps(["续航讨论"])
                ap_ok.analyzed_at = analyzed_out
                # 官方帖（brand_official, self, positive）——不进情感/事件
                p_off, ap_off = _post("w-off", "v1", OFFICIAL_TITLE, likes=9999,
                                      comments=500, published=pub_in,
                                      sentiment="positive",
                                      author_type="brand_official", subject="self")
                ap_off.event_tags = json.dumps(["官方宣传"])
                ap_off.analyzed_at = analyzed_out
                # 竞品帖（organic, competitor, neutral）——不进情感/事件
                p_comp, ap_comp = _post("w-comp", "v1", COMP_TITLE, likes=888,
                                        comments=99, published=pub_in,
                                        sentiment="neutral", subject="competitor")
                ap_comp.event_tags = json.dumps(["竞品对比"])
                ap_comp.analyzed_at = analyzed_out
                # 无关帖（irrelevant）——无 AnalyzedPost
                p_irr, _ = _post("w-irr", "v1", "薯条胡辣汤", status="irrelevant",
                                 likes=14639, comments=1437, published=pub_in)
                s.add_all([p_ok, ap_ok, p_off, ap_off, p_comp, ap_comp, p_irr])
                await s.commit()
                yield c, s
        app.dependency_overrides.clear()
        await engine.dispose()

    @staticmethod
    def _parse_sent(prompt: str) -> dict:
        """从周报 prompt 抽取 正面/负面/中性 计数。"""
        import re
        m = re.search(r"正面(\d+).*负面(\d+).*中性(\d+)", prompt)
        assert m, f"prompt 缺情感计数行: {prompt}"
        return {"positive": int(m.group(1)),
                "negative": int(m.group(2)),
                "neutral": int(m.group(3))}

    @pytest.mark.asyncio
    async def test_weekly_uses_published_at_not_analyzed_at(self, env_weekly):
        """周报情感计数按 published_at 过滤——analyzed_at 在窗外但 published_at
        在窗内的帖仍应被计入（旧 analyzed_at 口径会漏算）。"""
        client, _ = env_weekly
        prompts: list[str] = []

        async def fake_llm(prompt, timeout=60):
            prompts.append(prompt)
            return "摘要"

        with patch("api.routes.reports.call_llm", new=fake_llm):
            r = await client.post("/api/reports/weekly-digest", json={"vehicle_id": "v1"})
        assert r.status_code == 200
        sent = self._parse_sent(prompts[0])
        # p-ok positive 必须计入（analyzed_at 在窗外但 published_at 在窗内）
        assert sent["positive"] == 1, \
            f"published_at 窗内帖被漏算（analyzed_at 口径残留）: {sent}"

    @pytest.mark.asyncio
    async def test_weekly_excludes_competitor(self, env_weekly):
        """周报情感计数排除竞品帖（SELF_ONLY）——p-comp neutral 不得计入。"""
        client, _ = env_weekly
        prompts: list[str] = []

        async def fake_llm(prompt, timeout=60):
            prompts.append(prompt)
            return "摘要"

        with patch("api.routes.reports.call_llm", new=fake_llm):
            await client.post("/api/reports/weekly-digest", json={"vehicle_id": "v1"})
        sent = self._parse_sent(prompts[0])
        # 只 p-ok positive=1；竞品 neutral 不计
        assert sent["neutral"] == 0, f"竞品帖泄漏进周报情感计数: {sent}"
        assert sent["positive"] == 1

    @pytest.mark.asyncio
    async def test_weekly_excludes_official(self, env_weekly):
        """周报情感计数排除官方帖（AUTHENTIC_AUTHOR）——p-off positive 不得计入。"""
        client, _ = env_weekly
        prompts: list[str] = []

        async def fake_llm(prompt, timeout=60):
            prompts.append(prompt)
            return "摘要"

        with patch("api.routes.reports.call_llm", new=fake_llm):
            await client.post("/api/reports/weekly-digest", json={"vehicle_id": "v1"})
        sent = self._parse_sent(prompts[0])
        # 只 p-ok positive=1；官方 positive 不计
        assert sent["positive"] == 1, f"官方帖泄漏进周报情感计数: {sent}"

    @pytest.mark.asyncio
    async def test_weekly_event_tags_use_caliber(self, env_weekly):
        """周报 TOP 事件标签排除官方/竞品帖——只应含 p-ok 的"续航讨论"。"""
        client, _ = env_weekly
        prompts: list[str] = []

        async def fake_llm(prompt, timeout=60):
            prompts.append(prompt)
            return "摘要"

        with patch("api.routes.reports.call_llm", new=fake_llm):
            await client.post("/api/reports/weekly-digest", json={"vehicle_id": "v1"})
        # TOP事件行格式：TOP事件：{"tag": count, ...}
        import re
        m = re.search(r"TOP事件：(\{.*?\})", prompts[0])
        assert m, f"prompt 缺 TOP事件行: {prompts[0]}"
        events = json.loads(m.group(1))
        assert "续航讨论" in events, f"正常帖事件标签缺失: {events}"
        assert "官方宣传" not in events, f"官方帖事件标签泄漏: {events}"
        assert "竞品对比" not in events, f"竞品帖事件标签泄漏: {events}"


class TestEventTrackerCaliber:
    """C1: event_tracker 聚类层口径——官方/经销商帖不进事件聚类与
    sentiment_distribution。"""

    @pytest.mark.asyncio
    async def test_official_excluded_from_events(self):
        from pipeline.analysis.event_tracker import detect_events_for_vehicle
        from unittest.mock import patch as _patch
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:", echo=False,
            connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as s:
            s.add(Vehicle(id="v1", name="星愿", brand="吉利银河"))
            # 2 organic 帖共享"续航""衰减"双关键词 → 聚成一个事件
            p1, ap1 = _post("e-ok1", "v1", "续航衰减",
                            content="续航衰减问题续航衰减分享", likes=10,
                            sentiment="positive", subject="self")
            p2, ap2 = _post("e-ok2", "v1", "续航衰减",
                            content="续航衰减测试续航衰减结果", likes=5,
                            sentiment="negative", subject="self")
            # 官方帖同样含"续航衰减"——若未过滤会混入事件、污染 sentiment_distribution
            p3, ap3 = _post("e-off", "v1", "续航衰减",
                            content="续航衰减公告续航衰减数据", likes=9999,
                            sentiment="positive", author_type="brand_official",
                            subject="self")
            s.add_all([p1, ap1, p2, ap2, p3, ap3])
            await s.commit()

            # 走 sync 路径（无 api_key），避免 LLM 调用
            with _patch("utils.config.load_api_config",
                        return_value={"glm": {"api_key": ""}}):
                events = await detect_events_for_vehicle("v1", s, source="social")

            assert len(events) >= 1, "至少一个事件（2 organic 帖共享关键词）"
            all_pids = []
            for ev in events:
                pids = json.loads(ev["post_ids"])
                all_pids.extend(pids)
                dist = json.loads(ev["sentiment_distribution"])
                # 官方帖 positive 不进 sentiment_distribution
                assert dist.get("positive", 0) <= 1, \
                    f"官方帖泄漏进 sentiment_distribution: {dist}"
            # 官方帖不在任何事件的 post_ids 中
            assert "e-off" not in all_pids, \
                f"官方帖泄漏进事件 post_ids: {all_pids}"
        await engine.dispose()


# ── D8: 互动量公式统一（1:1:1） ──

class TestEngagementFormulaUniformity:
    """D8: 热帖榜（top-posts）与吐槽榜（negative-radar complaints）必须用
    同一套 1:1:1 公式（likes+comments+shares）排序，且 influence_score
    不带旧的 1:5:10 加权。"""

    @pytest_asyncio.fixture
    async def env_eng(self):
        """预置 1 车 + 2 负面帖（有机/self）+ 1 高赞非负面帖。

        两个负面帖用同一发布日，便于 negative-radar 取到；互动设计使
        1:1:1 与 1:5:10 给出不同排序，从而能区分两套公式。
        """
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
        pub = datetime.now() - timedelta(days=1)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            async with factory() as s:
                s.add(Vehicle(id="v1", name="星愿", brand="吉利银河"))
                # 负面帖 A：likes=20, comments=10, shares=5
                #   1:1:1 = 35 ; 1:5:10 = 20+50+50 = 120
                pA, apA = _post("eng-A", "v1", "续航虚标投诉", likes=20, comments=10,
                                published=pub, sentiment="negative", subject="self")
                pA.shares = 5
                # 负面帖 B：likes=30, comments=2, shares=0
                #   1:1:1 = 32 ; 1:5:10 = 30+10+0 = 40
                #   1:1:1 → A(35) > B(32) ；1:5:10 → A(120) > B(40)
                #   两帖 1:1:1 排序 A>B，但仍验证 influence_score 数值不带加权
                pB, apB = _post("eng-B", "v1", "刹车异响吐槽", likes=30, comments=2,
                                published=pub, sentiment="negative", subject="self")
                pB.shares = 0
                # 非负面高赞帖：确保 top-posts 不受 sentiment 过滤影响、
                # 且 negative-radar 不取它
                pC, apC = _post("eng-C", "v1", "提车分享开心", likes=999, comments=10,
                                published=pub, sentiment="positive", subject="self")
                # 低互动负面帖：把负面互动中位数压到 32 以下，使 eng-A/eng-B
                # 均通过 D7 动态门槛进榜（公式测试聚焦公式，非中位数过滤）
                pD, apD = _post("eng-D", "v1", "微小吐槽", likes=0, comments=0,
                                published=pub, sentiment="negative", subject="self")
                s.add_all([pA, apA, pB, apB, pC, apC, pD, apD])
                await s.commit()
                yield c, s
        app.dependency_overrides.clear()
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_complaints_influence_score_is_111(self, env_eng):
        """吐槽榜 influence_score 必须 = likes+comments+shares（非旧加权）。"""
        client, _ = env_eng
        r = await client.get("/api/dashboard/negative-radar/v1")
        assert r.status_code == 200
        data = r.json()
        complaints = data["top_complaints"]
        assert len(complaints) == 2, f"应取到 2 条吐槽帖: {complaints}"
        by_id = {c["id"]: c for c in complaints}
        # eng-A: 20+10+5 = 35（旧 1:5:10 会得 120）
        assert by_id["eng-A"]["influence_score"] == 35, \
            f"eng-A influence_score 非纯求和: {by_id['eng-A']}"
        # eng-B: 30+2+0 = 32（旧 1:5:10 会得 40）
        assert by_id["eng-B"]["influence_score"] == 32, \
            f"eng-B influence_score 非纯求和: {by_id['eng-B']}"

    @pytest.mark.asyncio
    async def test_complaints_and_top_posts_same_formula(self, env_eng):
        """热帖榜与吐槽榜用同一公式排序：两者对同一组帖子按
        likes+comments+shares desc。"""
        client, _ = env_eng
        top = (await client.get("/api/dashboard/top-posts/v1")).json()
        radar = (await client.get("/api/dashboard/negative-radar/v1")).json()
        complaints = radar["top_complaints"]
        # top-posts 取全 sentiment，应含 eng-C(1009) > eng-A(35) > eng-B(32) > eng-D(0)
        top_ids = [i["id"] for i in top]
        assert top_ids == ["eng-C", "eng-A", "eng-B", "eng-D"], \
            f"top-posts 排序非 1:1:1: {top_ids}"
        # 吐槽榜只取 negative，A(35) > B(32)
        comp_ids = [c["id"] for c in complaints]
        assert comp_ids == ["eng-A", "eng-B"], \
            f"吐槽榜排序非 1:1:1: {comp_ids}"
        # 同一帖子在两榜的排序键一致（influence_score 与 top-posts 等价）
        for c in complaints:
            assert c["influence_score"] == c["likes"] + c["comments"] + c["shares"]
