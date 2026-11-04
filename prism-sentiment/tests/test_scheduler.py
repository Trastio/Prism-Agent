"""T1.7 Tests: Collection Scheduler — 16 tests."""
import json
import uuid
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.schemas import Base, CollectionStatus, PostComment, RawPost, Vehicle


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def vehicle(db):
    v = Vehicle(id="v001", name="海豹", brand="比亚迪", search_keywords='["海豹EV"]')
    db.add(v)
    await db.commit()
    return v


class TestDateRanges:
    def test_initial_single_range(self):
        # 2026-10-15 R40：initial 窗 90→30（env INITIAL_WINDOW_DAYS，默认 30）
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler.__new__(CollectionScheduler)
        ranges = s._get_date_ranges("initial", None)
        today = date.today()
        assert len(ranges) == 1
        assert ranges[0][0] == (today - timedelta(days=30)).strftime("%Y-%m-%d")
        assert ranges[0][1] == today.strftime("%Y-%m-%d")

    def test_incremental_single_range(self):
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler.__new__(CollectionScheduler)
        last = datetime(2026, 5, 15)
        ranges = s._get_date_ranges("incremental", last)
        assert len(ranges) == 1
        assert ranges[0][0] == "2026-05-13"
        assert ranges[0][1] == date.today().strftime("%Y-%m-%d")


class TestModeDetection:
    @pytest.mark.asyncio
    async def test_no_history_is_initial(self, db, vehicle):
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        mode, last = await s._determine_mode(vehicle.id)
        assert mode == "initial"
        assert last is None

    @pytest.mark.asyncio
    async def test_existing_history_is_incremental(self, db, vehicle):
        from pipeline.scheduler import CollectionScheduler
        db.add(CollectionStatus(
            vehicle_id=vehicle.id, source="news", mode="initial",
            last_collected_at=datetime(2026, 5, 15), status="completed",
        ))
        await db.commit()
        s = CollectionScheduler(db)
        mode, last = await s._determine_mode(vehicle.id)
        assert mode == "incremental"
        assert last is not None


class TestCollectVehicle:
    @pytest.mark.asyncio
    async def test_stores_posts(self, db, vehicle):
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        # 2026-10-15 R31 news 停采：注入通道换社媒（douyin），需放行 _resolve_collector
        mock_posts = [
            {"title": "海豹测评", "content": "很好开" * 50, "url": "https://ex.com/1",
             "source": "tikhub", "platform": "douyin", "author": "tester",
             # 相对日期：固定日期会滚出采集窗口（_store_posts floor），此前 6 测试连环挂
             "published_at": (date.today() - timedelta(days=5)).isoformat()},
        ]
        with patch.object(s, "_collect_social_platform", new_callable=AsyncMock, return_value=(mock_posts, [])), \
             patch.object(s, "_resolve_collector", AsyncMock(return_value=(object(), "tikhub"))), \
             patch.object(s, "_crawl_full_texts", new_callable=AsyncMock, side_effect=lambda p: p), \
             patch.object(s, "_resolve_urls", new_callable=AsyncMock, side_effect=lambda p: p), \
             patch.object(s, "_run_dedup", side_effect=lambda p: p), \
             patch.object(s, "_expand_keywords_if_needed", new_callable=AsyncMock, return_value=["海豹EV"]), \
             patch("pipeline.scheduler.asyncio.sleep", AsyncMock()):
            result = await s.collect_vehicle(vehicle.id)
        assert result["posts_collected"] >= 1
        rows = (await db.execute(select(RawPost))).scalars().all()
        assert len(rows) >= 1
        assert rows[0].title == "海豹测评"

    @pytest.mark.asyncio
    async def test_creates_status_records(self, db, vehicle):
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        with patch.object(s, "_collect_news", new_callable=AsyncMock, return_value=[]), \
             patch.object(s, "_collect_social_platform", new_callable=AsyncMock, return_value=([], [])), \
             patch.object(s, "_crawl_full_texts", new_callable=AsyncMock, side_effect=lambda p: p), \
             patch.object(s, "_resolve_urls", new_callable=AsyncMock, side_effect=lambda p: p), \
             patch.object(s, "_run_dedup", side_effect=lambda p: p), \
             patch.object(s, "_expand_keywords_if_needed", new_callable=AsyncMock, return_value=["海豹EV"]):
            await s.collect_vehicle(vehicle.id)
        statuses = (await db.execute(
            select(CollectionStatus).where(CollectionStatus.vehicle_id == vehicle.id)
        )).scalars().all()
        assert len(statuses) >= 1

    @pytest.mark.asyncio
    async def test_error_does_not_crash(self, db, vehicle):
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        with patch.object(s, "_expand_keywords_if_needed", new_callable=AsyncMock, side_effect=Exception("API down")):
            result = await s.collect_vehicle(vehicle.id)
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_dedup_by_url(self, db, vehicle):
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        # 2026-10-15 R31：注入通道换社媒（douyin）
        posts = [
            {"title": "A 海豹", "content": "c1" * 50, "url": "https://ex.com/1",
             "source": "tikhub", "platform": "douyin",
             "published_at": (date.today() - timedelta(days=5)).isoformat()},
            {"title": "dup 海豹", "content": "c2" * 50, "url": "https://ex.com/1",
             "source": "tikhub", "platform": "douyin",
             "published_at": (date.today() - timedelta(days=5)).isoformat()},
            {"title": "B 海豹", "content": "c3" * 50, "url": "https://ex.com/2",
             "source": "tikhub", "platform": "douyin",
             "published_at": (date.today() - timedelta(days=5)).isoformat()},
        ]
        with patch.object(s, "_collect_social_platform", new_callable=AsyncMock, return_value=(posts, [])), \
             patch.object(s, "_resolve_collector", AsyncMock(return_value=(object(), "tikhub"))), \
             patch.object(s, "_crawl_full_texts", new_callable=AsyncMock, side_effect=lambda p: p), \
             patch.object(s, "_resolve_urls", new_callable=AsyncMock, side_effect=lambda p: p), \
             patch.object(s, "_run_dedup", side_effect=lambda p: p), \
             patch.object(s, "_expand_keywords_if_needed", new_callable=AsyncMock, return_value=["海豹EV"]), \
             patch("pipeline.scheduler.asyncio.sleep", AsyncMock()):
            result = await s.collect_vehicle(vehicle.id)
        assert result["posts_collected"] == 2

    @pytest.mark.asyncio
    async def test_search_index_collected_and_stored(self, db, vehicle):
        """collect_vehicle 应采集多平台搜索指数（抖音+小红书）写 SearchIndexMetric。"""
        from pipeline.scheduler import CollectionScheduler
        from models.schemas import SearchIndexMetric
        s = CollectionScheduler(db)
        dy = [{"date": "2026-05-19", "keyword": "海豹", "source": "douyin", "index": 2440.0}]
        xhs = [{"date": "2026-05-20", "keyword": "海豹", "source": "xiaohongshu", "index": 190.0}]
        with patch.object(s, "_collect_news", new_callable=AsyncMock, return_value=[]), \
             patch.object(s, "_collect_social_platform", new_callable=AsyncMock, return_value=([], [])), \
             patch.object(s, "_crawl_full_texts", new_callable=AsyncMock, side_effect=lambda p: p), \
             patch.object(s, "_resolve_urls", new_callable=AsyncMock, side_effect=lambda p: p), \
             patch.object(s, "_run_dedup", side_effect=lambda p: p), \
             patch.object(s, "_expand_keywords_if_needed", new_callable=AsyncMock, return_value=["海豹EV"]), \
             patch.object(s._index, "is_available", AsyncMock(return_value=True)), \
             patch.object(s._index, "collect_douyin", new_callable=AsyncMock, return_value=dy) as mock_dy, \
             patch.object(s._index, "collect_xiaohongshu", new_callable=AsyncMock, return_value=xhs):
            await s.collect_vehicle(vehicle.id)
        rows = (await db.execute(
            select(SearchIndexMetric).where(SearchIndexMetric.vehicle_id == vehicle.id)
        )).scalars().all()
        assert {(r.source, r.index_value) for r in rows} ==             {("douyin", 2440.0), ("xiaohongshu", 190.0)}

        # dy 指数固定 30 天滚动窗（与采集窗解耦——initial 窗 90 天/增量窗更窄，
        # 指数窗不随它们缩放，否则曲线被截成零星几个点）
        args = mock_dy.call_args
        assert args.args[0] == "海豹EV"
        assert args.args[1] == (date.today() - timedelta(days=29)).isoformat()
        assert args.args[2] == date.today().isoformat()

    @pytest.mark.asyncio
    async def test_search_index_store_is_idempotent_per_source(self, db, vehicle):
        """重跑覆盖同 source 的日期段（delete+insert），不跨 source 误删、
        不触碰本次未包含的日期。"""
        from pipeline.scheduler import CollectionScheduler
        from models.schemas import SearchIndexMetric
        s = CollectionScheduler(db)
        first = [{"date": "2026-05-19", "keyword": "k", "source": "douyin", "index": 100.0},
                 {"date": "2026-05-20", "keyword": "k", "source": "douyin", "index": 200.0},
                 {"date": "2026-05-20", "keyword": "k", "source": "xiaohongshu", "index": 50.0}]
        await s._store_search_index(vehicle.id, first)
        # 重跑：douyin 只有 05-20 且值变了；05-19 douyin 与 05-20 xhs 不在本次范围
        second = [{"date": "2026-05-20", "keyword": "k", "source": "douyin", "index": 999.0}]
        await s._store_search_index(vehicle.id, second)
        rows = (await db.execute(
            select(SearchIndexMetric).where(SearchIndexMetric.vehicle_id == vehicle.id)
        )).scalars().all()
        got = {(r.source, str(r.date), r.index_value) for r in rows}
        assert got == {("douyin", "2026-05-20", 999.0),       # 被覆盖
                       ("douyin", "2026-05-19", 100.0),       # 日期未涉及 → 保留
                       ("xiaohongshu", "2026-05-20", 50.0)}   # 跨 source → 不误删

    @pytest.mark.asyncio
    async def test_filters_posts_outside_collection_range(self, db, vehicle):
        """采集范围外的老帖（如 2018 年历史污染）不应入库。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        # 2026-10-15 R31：注入通道换社媒（douyin）
        mock_posts = [
            {"title": "近期帖 海豹", "content": "c" * 50, "url": "https://ex.com/1",
             "source": "tikhub", "platform": "douyin",
             "published_at": (date.today() - timedelta(days=5)).isoformat()},
            {"title": "2018老帖 海豹", "content": "old" * 50, "url": "https://ex.com/2",
             "source": "tikhub", "platform": "douyin", "published_at": "2018-07-24"},
        ]
        with patch.object(s, "_collect_social_platform", new_callable=AsyncMock, return_value=(mock_posts, [])), \
             patch.object(s, "_resolve_collector", AsyncMock(return_value=(object(), "tikhub"))), \
             patch.object(s, "_crawl_full_texts", new_callable=AsyncMock, side_effect=lambda p: p), \
             patch.object(s, "_resolve_urls", new_callable=AsyncMock, side_effect=lambda p: p), \
             patch.object(s, "_run_dedup", side_effect=lambda p: p), \
             patch.object(s, "_expand_keywords_if_needed", new_callable=AsyncMock, return_value=["海豹EV"]), \
             patch("pipeline.scheduler.asyncio.sleep", AsyncMock()):
            await s.collect_vehicle(vehicle.id)
        rows = (await db.execute(select(RawPost))).scalars().all()
        titles = [r.title for r in rows]
        assert any("近期帖" in t for t in titles)
        assert not any("2018老帖" in t for t in titles)



class TestCrawlFullTexts:
    @pytest.mark.asyncio
    async def test_crawl_full_text_gates_on_news_source(self, db):
        """_crawl_full_texts 只对 news 源帖抓外部全文（社媒全文走 TikHub 富化）。

        2026-10-15 R31 news 停采后此门在生产中不再命中（归档路径保留），
        测试改为单元级直测门控行为，不经 collect_vehicle。
        """
        from pipeline.scheduler import CollectionScheduler
        with patch("pipeline.scheduler.crawl_full_text", new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = {
                "url": "https://example.com/n1",
                "full_text": "Full article " * 50,
                "status": "success",
            }
            s = CollectionScheduler(db)
            out = await s._crawl_full_texts([
                {"title": "t", "content": "c", "url": "https://example.com/n1",
                 "source": "bocha", "platform": "news"},
                {"title": "t2", "content": "c", "url": "https://example.com/s1",
                 "source": "tikhub", "platform": "douyin"},
            ])
            mock_crawl.assert_called_once()  # 社媒帖不走外部全文抓取
            assert out[0]["full_content"] == "Full article " * 50
            assert "full_content" not in out[1]


class TestExpandKeywords:
    """2026-10-15 R31：LLM 扩词链下线——_expand_keywords_if_needed 直接返回
    search_keywords（不再读 expanded_keywords 缓存、不再调 keyword_expander）。"""

    @pytest.mark.asyncio
    async def test_returns_search_keywords_directly(self, db):
        from pipeline.scheduler import CollectionScheduler
        v = Vehicle(id="v002", name="海豚", brand="比亚迪",
                     search_keywords='["海豚","比亚迪海豚"]',
                     expanded_keywords='["海豚","老缓存词"]')
        db.add(v)
        await db.commit()
        s = CollectionScheduler(db)
        result = await s._expand_keywords_if_needed(v)
        assert result == ["海豚", "比亚迪海豚"]  # 老缓存不再参与

    @pytest.mark.asyncio
    async def test_fallback_to_name_when_no_keywords(self, db):
        from pipeline.scheduler import CollectionScheduler
        v = Vehicle(id="v003", name="秦PLUS", brand="比亚迪", search_keywords=None)
        db.add(v)
        await db.commit()
        s = CollectionScheduler(db)
        assert await s._expand_keywords_if_needed(v) == ["秦PLUS"]


class TestResolveUrls:
    @pytest.mark.asyncio
    async def test_resolves_xhslink(self, db):
        """URLs with xhslink.com get resolved_note_id."""
        from pipeline.scheduler import CollectionScheduler

        async def _fake_resolve(url: str) -> str:
            if "xhslink.com" in url:
                return "resolved_note_abc"
            return url.rsplit("/", 1)[-1].split("?")[0]

        s = CollectionScheduler(db)
        posts = [
            {"url": "https://xhslink.com/abc123", "title": "test"},
            {"url": "https://example.com/article", "title": "no-resolve"},
        ]
        with patch("pipeline.scheduler.resolve_note_id", new_callable=AsyncMock,
                    side_effect=_fake_resolve):
            result = await s._resolve_urls(posts)
        assert result[0].get("resolved_note_id") == "resolved_note_abc"
        assert "resolved_note_id" not in result[1]

    @pytest.mark.asyncio
    async def test_non_xhslink_unchanged(self, db):
        """Non-xhslink URLs pass through unchanged."""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        posts = [{"url": "https://example.com/article", "title": "test"}]
        result = await s._resolve_urls(posts)
        assert "resolved_note_id" not in result[0]


class TestRunDedup:
    @pytest.mark.asyncio
    async def test_removes_near_duplicates(self, db):
        """SimHash dedup removes near-duplicate posts."""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        dup_text = "比亚迪海豹2026款纯电轿车续航里程可达700公里加速性能优异底盘调校偏向运动风格外观设计采用了海洋美学理念内饰用料考究做工精细智能驾驶辅助系统功能齐全整体性价比非常高值得推荐购买"
        unique_text = "特斯拉Model Y最新OTA升级增加了全新自动驾驶功能界面设计更加简洁直观语音助手响应速度大幅提升导航系统优化了路线规划算法充电网络覆盖范围进一步扩大超级充电站建设加速推进"
        posts = [
            {"title": "比亚迪海豹详细评测", "content": dup_text * 3,
             "url": "https://a.com", "published_at": "2026-05-20"},
            {"title": "比亚迪海豹详细评测（转载）", "content": dup_text * 3,
             "url": "https://b.com", "published_at": "2026-05-21"},
            {"title": "特斯拉Model Y OTA升级体验", "content": unique_text * 3,
             "url": "https://c.com", "published_at": "2026-05-22"},
        ]
        result = s._run_dedup(posts)
        # The exact-duplicate should be removed; only 2 kept
        assert len(result) == 2


class TestDedupInPipeline:
    @pytest.mark.asyncio
    async def test_dedup_called_in_pipeline(self, db):
        """Dedup should remove near-duplicate posts in full pipeline."""
        from pipeline.scheduler import CollectionScheduler
        vehicle_id = str(uuid.uuid4())
        db.add(Vehicle(id=vehicle_id, name="测试车", brand="测试",
                       search_keywords='["测试车"]', expanded_keywords='["测试车"]'))
        await db.commit()

        # 2026-10-15 R31：注入通道换社媒（douyin）
        with patch("pipeline.scheduler.IndexCollector") as MockIndex, \
             patch("pipeline.scheduler.crawl_full_text", new_callable=AsyncMock) as mock_crawl:
            MockIndex.return_value.is_available = AsyncMock(return_value=False)
            mock_crawl.return_value = {"url": "", "full_text": "", "status": "fallback"}

            scheduler = CollectionScheduler(db)
            with patch.object(scheduler, "_collect_social_platform", AsyncMock(return_value=([
                # 车名词元须出现在帖文（社媒 AND 门）
                {"title": "测试车新闻A", "content": "内容A" * 50, "url": "https://a.com",
                 "source": "tikhub", "platform": "douyin",
                 "published_at": f"{(date.today() - timedelta(days=5)).isoformat()}T10:00:00"},
                {"title": "测试车新闻B", "content": "完全不同的内容B" * 50, "url": "https://b.com",
                 "source": "tikhub", "platform": "douyin",
                 "published_at": f"{(date.today() - timedelta(days=4)).isoformat()}T10:00:00"},
            ], []))), \
                 patch.object(scheduler, "_resolve_collector",
                              AsyncMock(return_value=(object(), "tikhub"))), \
                 patch("pipeline.scheduler.asyncio.sleep", AsyncMock()):
                result = await scheduler.collect_vehicle(vehicle_id)
            assert result["status"] == "completed"
            assert result["posts_collected"] >= 1


class TestBrandKeywords:
    def test_extract_chinese_and_alphanumeric(self):
        """中英文混合车型名应正确拆分为独立关键词。"""
        from pipeline.scheduler import _extract_brand_keywords
        kw = _extract_brand_keywords("启源Q05", "长安")
        assert "启源" in kw
        assert "Q05" in kw
        assert "长安" in kw
        # 不应包含太短的 token
        assert all(len(k) >= 2 for k in kw)

    def test_pure_chinese_name(self):
        """纯中文车型名 + 同品牌不应重复。"""
        from pipeline.scheduler import _extract_brand_keywords
        kw = _extract_brand_keywords("比亚迪海豚", "比亚迪")
        assert "比亚迪海豚" in kw or "比亚迪" in kw
        # 去重
        assert kw.count("比亚迪") <= 1

    def test_english_name(self):
        """英文车型名应正确提取。"""
        from pipeline.scheduler import _extract_brand_keywords
        kw = _extract_brand_keywords("Model 3", "Tesla")
        assert "Model" in kw
        assert "Tesla" in kw
        # "3" 长度 < 2 不应出现
        assert "3" not in kw

    def test_single_char_not_included(self):
        """单字关键词不应出现（如'元'从'元PLUS'提取）。"""
        from pipeline.scheduler import _extract_brand_keywords
        kw = _extract_brand_keywords("元PLUS", "比亚迪")
        assert "元" not in kw
        assert "PLUS" in kw


class TestBrandFilter:
    @pytest.mark.asyncio
    async def test_store_posts_filters_non_brand_posts(self, db, vehicle):
        """不含品牌关键词的帖子不应入库。vehicle=海豹/比亚迪, 竞品帖不含海豹或比亚迪→过滤。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        # vehicle fixture: name="海豹", brand="比亚迪" → keywords=["海豹","比亚迪"]
        # 竞品帖: 特斯拉Model 3, 不含"海豹"也不含"比亚迪" → 应被过滤
        posts = [
            {"title": "特斯拉Model 3评测", "content": "Model 3驾驶体验非常出色",
             "url": "http://a.com/1", "platform": "dy", "source": "mediacrawler",
             "likes": 10, "comments": 2, "shares": 1, "author": "u1",
             "published_at": "2026-06-01T10:00:00"},
        ]
        count = sum((await s._store_posts(
            vehicle.id, posts,
            vehicle_name=vehicle.name, vehicle_brand=vehicle.brand,
        )).values())
        assert count == 0

    @pytest.mark.asyncio
    async def test_store_posts_keeps_brand_matching_posts(self, db, vehicle):
        """含品牌关键词的帖子应正常入库。包含"比亚迪"即匹配。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        posts = [
            {"title": "海豹降价了", "content": "比亚迪海豹最新优惠",
             "url": "http://a.com/3", "platform": "wb", "source": "mediacrawler",
             "likes": 30, "comments": 8, "shares": 2, "author": "u3",
             "published_at": "2026-06-01T10:00:00"},
        ]
        count = sum((await s._store_posts(
            vehicle.id, posts,
            vehicle_name=vehicle.name, vehicle_brand=vehicle.brand,
        )).values())
        assert count == 1
        from sqlalchemy import select
        from models.schemas import RawPost
        result = await db.execute(select(RawPost).where(RawPost.vehicle_id == vehicle.id))
        stored = result.scalars().all()
        assert len(stored) == 1
        assert "海豹" in stored[0].title

    @pytest.mark.asyncio
    async def test_store_posts_chezhiwang_exempt_from_floor(self, db, vehicle):
        """车质网帖跳过社媒 min_date floor——incremental 模式下社媒 start_date≈3 天前，
        车质网 30 天窗的 4~30 天前投诉帖不应被 floor 误杀（code-review 修复）。"""
        from pipeline.scheduler import CollectionScheduler
        from datetime import date, timedelta
        s = CollectionScheduler(db)
        # 模拟 incremental 窄窗：min_date = 3 天前
        narrow_start = (date.today() - timedelta(days=3)).isoformat()
        # 车质网帖：20 天前发布（晚于 30 天窗内，但早于 3 天 floor）
        old_cz_date = (date.today() - timedelta(days=20)).strftime("%Y-%m-%dT10:00:00")
        posts = [
            {"title": "海豹投诉", "content": "比亚迪海豹质量问题",
             "url": "http://bbs.12365auto.com/thread/1.shtml",
             "platform": "chezhiwang", "source": "chezhiwang",
             "likes": 0, "comments": 0, "shares": 0, "author": "车主",
             "published_at": old_cz_date},
            # 对照组：社媒帖同样 20 天前 → 应被 floor 丢
            {"title": "海豹旧帖", "content": "比亚迪海豹讨论",
             "url": "http://weibo.com/old",
             "platform": "weibo", "source": "tikhub",
             "likes": 5, "comments": 1, "shares": 0, "author": "u",
             "published_at": old_cz_date},
        ]
        count = sum((await s._store_posts(
            vehicle.id, posts, min_date=narrow_start,
            vehicle_name=vehicle.name, vehicle_brand=vehicle.brand,
        )).values())
        # 车质网帖入库，社媒旧帖被 floor 丢
        assert count == 1
        from sqlalchemy import select
        from models.schemas import RawPost
        stored = (await db.execute(
            select(RawPost).where(RawPost.vehicle_id == vehicle.id)
        )).scalars().all()
        assert len(stored) == 1
        assert stored[0].platform == "chezhiwang"

    @pytest.mark.asyncio
    async def test_store_posts_logs_filtered_count(self, db, vehicle, caplog):
        """过滤时应输出 info 日志记录过滤数量。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        posts = [
            {"title": "竞品车评测", "content": "其他品牌",
             "url": "http://a.com/4", "platform": "dy", "source": "mediacrawler",
             "likes": 1, "comments": 0, "shares": 0, "author": "u4",
             "published_at": "2026-06-01T10:00:00"},
        ]
        import logging
        with caplog.at_level(logging.INFO, logger="pipeline.scheduler"):
            await s._store_posts(
                vehicle.id, posts,
                vehicle_name=vehicle.name, vehicle_brand=vehicle.brand,
            )
        assert "brand filter" in caplog.text.lower() or "filtered" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_collect_vehicle_filters_competitor_posts(self, db, vehicle):
        """集成测试：collect_vehicle 全链路应过滤竞品帖。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        # 模拟采集返回竞品帖（不含 vehicle 品牌关键词）
        competitor_posts = [
            {"title": "特斯拉Model 3评测", "content": "Model 3驾驶体验",
             "url": "http://b.com/1", "platform": "dy", "source": "mediacrawler",
             "likes": 10, "comments": 2, "shares": 1, "author": "u5",
             "published_at": "2026-06-01T10:00:00"},
        ]
        with patch.object(s, "_collect_news", new_callable=AsyncMock, return_value=[]), \
             patch.object(s, "_collect_social_platform", new_callable=AsyncMock, return_value=(competitor_posts, [])), \
             patch.object(s, "_crawl_full_texts", new_callable=AsyncMock, side_effect=lambda p: p), \
             patch.object(s, "_resolve_urls", new_callable=AsyncMock, side_effect=lambda p: p), \
             patch.object(s, "_run_dedup", side_effect=lambda p: p), \
             patch.object(s, "_expand_keywords_if_needed", new_callable=AsyncMock, return_value=["海豹EV"]):
            result = await s.collect_vehicle(vehicle.id)
        # 竞品帖不含品牌关键词，应全部被过滤
        assert result["posts_collected"] == 0

    @pytest.mark.asyncio
    async def test_store_posts_matches_on_full_content(self, db, vehicle):
        """品牌关键词仅出现在 full_content 中时也应匹配。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        # title 和 content 不含关键词，只有 full_content 包含
        posts = [
            {"title": "不明帖子", "content": "不明内容",
             "full_content": "比亚迪最新技术突破，海豹性能解析",
             "url": "http://a.com/5", "platform": "news", "source": "bocha",
             "likes": 1, "comments": 0, "shares": 0, "author": "u6",
             "published_at": "2026-06-01T10:00:00"},
        ]
        count = sum((await s._store_posts(
            vehicle.id, posts,
            vehicle_name=vehicle.name, vehicle_brand=vehicle.brand,
        )).values())
        assert count == 1


class TestStoreComments:
    """评论入库咽喉：空内容守卫对所有 provider 生效（看板评估 P1-6）。"""

    @pytest.mark.asyncio
    async def test_empty_content_comments_dropped_normal_kept(self, db, vehicle):
        from pipeline.scheduler import CollectionScheduler
        url = "https://m.weibo.cn/status/5341322191834751"
        db.add(RawPost(id="p1", vehicle_id=vehicle.id, source="tikhub",
                       platform="weibo", title="t", content="c", url=url))
        await db.commit()
        s = CollectionScheduler(db)
        n = await s._store_comments(vehicle.id, [
            {"post_url": url, "content": "正常评论", "author": "a", "likes": 1,
             "platform": "weibo", "published_at": ""},
            {"post_url": url, "content": "", "author": "a", "likes": 1,
             "platform": "weibo", "published_at": ""},          # 空串
            {"post_url": url, "content": "  \n\t ", "author": "a", "likes": 1,
             "platform": "weibo", "published_at": ""},          # 纯空白
            {"post_url": url, "content": None, "author": "a", "likes": 1,
             "platform": "weibo", "published_at": ""},          # None 兜底
        ])
        assert n == 1
        rows = (await db.execute(select(PostComment))).scalars().all()
        assert len(rows) == 1 and rows[0].content == "正常评论"

    @pytest.mark.asyncio
    async def test_unmatched_post_url_still_skipped(self, db, vehicle, caplog):
        """守卫不放松匹配语义：post_url/note_id 对不上帖的评论照旧不入库。"""
        import logging as _logging
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        with caplog.at_level(_logging.WARNING, logger="pipeline.scheduler"):
            n = await s._store_comments(vehicle.id, [
                {"post_url": "https://m.weibo.cn/status/none", "content": "有内容但无主",
                 "author": "a", "likes": 0, "platform": "weibo", "published_at": ""},
            ])
        assert n == 0
        # T2.4 归因：警告带"帖被过滤/去重丢弃"说明 + 样本 URL（非 id 错配）
        assert "Comment matching: 1/1 unmatched" in caplog.text
        assert "品牌过滤" in caplog.text
        assert "https://m.weibo.cn/status/none" in caplog.text

    @pytest.mark.asyncio
    async def test_same_comment_twice_not_duplicated(self, db, vehicle):
        """评论去重（2026-09-12 修）：同一条评论二次入库只留一份。

        真实场景：每日增量重抓同一批热帖，top 评论每次都出现在响应里。
        此前无去重键导致 M03 4476 条里 1216 组重复（最狠 ×13）。
        """
        from pipeline.scheduler import CollectionScheduler
        url = "https://www.douyin.com/video/7684062274742778793"
        db.add(RawPost(id="p1", vehicle_id=vehicle.id, source="tikhub",
                       platform="douyin", title="t", content="c", url=url))
        await db.commit()
        s = CollectionScheduler(db)
        comment = {"post_url": url, "content": "这车真的不错", "author": "a",
                   "likes": 3, "platform": "douyin", "published_at": "",
                   "comment_cid": "7684068765316055857"}
        assert await s._store_comments(vehicle.id, [comment]) == 1
        # 同 cid 再来一次 → 跳过；无 cid 的同内容（指纹）也跳过
        assert await s._store_comments(vehicle.id, [comment]) == 0
        no_cid = {k: v for k, v in comment.items() if k != "comment_cid"}
        assert await s._store_comments(vehicle.id, [no_cid]) == 0
        rows = (await db.execute(select(PostComment))).scalars().all()
        assert len(rows) == 1
        assert rows[0].cid == "7684068765316055857"

    @pytest.mark.asyncio
    async def test_same_content_different_post_both_kept(self, db, vehicle):
        """指纹含 post_id：不同帖下的同文评论（如"哈哈哈"）都保留。"""
        from pipeline.scheduler import CollectionScheduler
        for i, url in enumerate(("https://www.douyin.com/video/1",
                                 "https://www.douyin.com/video/2")):
            db.add(RawPost(id=f"p{i}", vehicle_id=vehicle.id, source="tikhub",
                           platform="douyin", title="t", content="c", url=url))
        await db.commit()
        s = CollectionScheduler(db)
        n = await s._store_comments(vehicle.id, [
            {"post_url": "https://www.douyin.com/video/1", "content": "哈哈哈",
             "author": "a", "likes": 0, "platform": "douyin", "published_at": ""},
            {"post_url": "https://www.douyin.com/video/2", "content": "哈哈哈",
             "author": "a", "likes": 0, "platform": "douyin", "published_at": ""},
        ])
        assert n == 2

    @pytest.mark.asyncio
    async def test_ks_legacy_comment_id_key_still_dedups(self, db, vehicle):
        """快手 collector 历史遗留 comment_id 键（非 comment_cid）也能去重。"""
        from pipeline.scheduler import CollectionScheduler
        url = "https://www.kuaishou.com/short-video/3xabc"
        db.add(RawPost(id="p1", vehicle_id=vehicle.id, source="tikhub",
                       platform="kuaishou", title="t", content="c", url=url))
        await db.commit()
        s = CollectionScheduler(db)
        comment = {"post_url": url, "content": "快手热评", "author": "k",
                   "likes": 1, "platform": "kuaishou", "published_at": "",
                   "comment_id": "889001835226"}
        assert await s._store_comments(vehicle.id, [comment]) == 1
        assert await s._store_comments(vehicle.id, [comment]) == 0


class TestPostPathDedup:
    """帖 URL 去重键 = 路径（2026-09-12 修）：xhs xsec_token 是抓取凭证
    不是身份，同 nid 不同 token 曾致一条笔记入库 4 份。"""

    @pytest.mark.asyncio
    async def test_same_path_different_query_deduped(self, db, vehicle):
        """同路径不同 query（token 变体）：只入库一份，互动数刷新到旧行。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        base = {"platform": "xiaohongshu", "source": "tikhub", "title": "海豹提车",
                "content": "海豹内容", "author": "a", "likes": 10, "comments": 2,
                "shares": 1, "published_at": "2026-09-10T10:00:00"}
        n1 = await s._store_posts(vehicle.id, [
            {**base, "url": "https://www.xiaohongshu.com/explore/abc?xsec_token=T1"},
        ], vehicle_name=vehicle.name, vehicle_brand=vehicle.brand)
        n2 = await s._store_posts(vehicle.id, [
            # 同 nid 不同 token + 更新后的互动数 → 刷新而非新行
            {**base, "url": "https://www.xiaohongshu.com/explore/abc?xsec_token=T2",
             "likes": 99, "comments": 5, "shares": 3},
        ], vehicle_name=vehicle.name, vehicle_brand=vehicle.brand)
        assert sum(n1.values()) == 1 and sum(n2.values()) == 0
        rows = (await db.execute(select(RawPost))).scalars().all()
        assert len(rows) == 1
        assert rows[0].likes == 99 and rows[0].comments == 5  # 刷新生效

    @pytest.mark.asyncio
    async def test_different_path_both_stored(self, db, vehicle):
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        base = {"platform": "weibo", "source": "tikhub", "title": "海豹t",
                "content": "海豹c", "author": "a", "likes": 0, "comments": 0,
                "shares": 0, "published_at": "2026-09-10T10:00:00"}
        n = await s._store_posts(vehicle.id, [
            {**base, "url": "https://m.weibo.cn/status/111"},
            {**base, "url": "https://m.weibo.cn/status/222"},
        ], vehicle_name=vehicle.name, vehicle_brand=vehicle.brand)
        assert sum(n.values()) == 2


class TestNewsTitleDedup:
    """（2026-10-15 R31：news 跨源标题去重逻辑随停采摘除，news 侧用例删除；
    保留社媒侧用例守护"同标题不同 URL 不误伤"。）"""

    @pytest.mark.asyncio
    async def test_social_same_title_not_affected(self, db, vehicle):
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        base = {"platform": "weibo", "source": "tikhub", "author": "同一人",
                "content": "内容 海豹", "likes": 0, "comments": 0, "shares": 0,
                "published_at": (date.today() - timedelta(days=1)).isoformat()}
        n = await s._store_posts(vehicle.id, [
            {**base, "title": "海豹提车", "url": "https://m.weibo.cn/status/1"},
            {**base, "title": "海豹提车", "url": "https://m.weibo.cn/status/2"},
        ], vehicle_name=vehicle.name, vehicle_brand=vehicle.brand)
        assert sum(n.values()) == 2  # 社媒同标题不同帖是不同内容，不去重


class TestCrossBatchDedup:
    """跨批次近似去重（B2）：新帖与近30天库内同前缀帖 simhash 比对。

    场景：跨天多账号转发稿——同标题（或仅标点/空白差异）、不同 URL，当批次
    去重挡不住（deduplicate 只看本次采集内）。simhash 阈值≤3 对中文短标题
    实际只挡近全同（转发稿场景），真实微改稿（换词）simhash 距离远超 3 不
    在本层覆盖范围——那靠事件层 Louvain 聚簇收口。
    """

    @pytest.mark.asyncio
    async def test_near_dup_same_prefix_blocked(self, db, vehicle):
        """新帖标题与库内近30天帖前12字相同 + simhash 距离≤3 → 拦截。

        转发稿场景：同标题、不同 URL、不同账号。
        """
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        existing_title = "吉利星愿上市21个月累计销量突破十万辆大关成为市场爆款"
        db.add(RawPost(id="p-existing", vehicle_id=vehicle.id, source="tikhub",
                       platform="weibo", title=existing_title, content="c",
                       url="https://m.weibo.cn/status/old",
                       collected_at=datetime.now() - timedelta(days=5)))
        await db.commit()
        # 新帖：标题仅末尾加标点（simhash 距离 0）、不同 URL
        new_title = existing_title + "！"
        posts = [{"title": new_title, "content": "c", "url": "https://m.weibo.cn/status/new",
                  "platform": "weibo", "source": "tikhub", "author": "a",
                  "likes": 0, "comments": 0, "shares": 0,
                  "published_at": (date.today() - timedelta(days=1)).isoformat()}]
        result = await s._cross_batch_dedup(posts, vehicle.id)
        assert len(result) == 0  # 拦截

    @pytest.mark.asyncio
    async def test_same_prefix_diff_content_passes(self, db, vehicle):
        """新帖与库内帖前缀同但内容差异大（simhash>3）→ 通过。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        existing_title = "比亚迪海豹最新动态：降价促销活动开始了欢迎大家来看"
        db.add(RawPost(id="p-existing", vehicle_id=vehicle.id, source="tikhub",
                       platform="weibo", title=existing_title, content="c",
                       url="https://m.weibo.cn/status/old",
                       collected_at=datetime.now() - timedelta(days=3)))
        await db.commit()
        # 新帖：同前12字但后半完全不同 → simhash 距离远超 3
        new_title = "比亚迪海豹最新动态：底盘调校偏向运动风格续航里程表现出色"
        posts = [{"title": new_title, "content": "c", "url": "https://m.weibo.cn/status/new",
                  "platform": "weibo", "source": "tikhub", "author": "a",
                  "likes": 0, "comments": 0, "shares": 0,
                  "published_at": (date.today() - timedelta(days=1)).isoformat()}]
        result = await s._cross_batch_dedup(posts, vehicle.id)
        assert len(result) == 1  # 通过

    @pytest.mark.asyncio
    async def test_no_matching_prefix_passes(self, db, vehicle):
        """新帖无同前缀库内帖 → 通过。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        db.add(RawPost(id="p-existing", vehicle_id=vehicle.id, source="tikhub",
                       platform="weibo", title="完全不同的标题关于特斯拉Model Y",
                       content="c", url="https://m.weibo.cn/status/old",
                       collected_at=datetime.now() - timedelta(days=2)))
        await db.commit()
        posts = [{"title": "海豹提车作业分享很长时间的等待终于提车了非常开心",
                  "content": "c", "url": "https://m.weibo.cn/status/new",
                  "platform": "weibo", "source": "tikhub", "author": "a",
                  "likes": 0, "comments": 0, "shares": 0,
                  "published_at": (date.today() - timedelta(days=1)).isoformat()}]
        result = await s._cross_batch_dedup(posts, vehicle.id)
        assert len(result) == 1  # 无同前缀桶 → 通过

    @pytest.mark.asyncio
    async def test_old_post_outside_30day_window_not_matched(self, db, vehicle):
        """库内帖超过30天的不参与比对（窗口外老帖不挡新帖）。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        existing_title = "吉利星愿上市21个月累计销量突破十万辆大关成为市场爆款"
        db.add(RawPost(id="p-old", vehicle_id=vehicle.id, source="tikhub",
                       platform="weibo", title=existing_title, content="c",
                       url="https://m.weibo.cn/status/old",
                       collected_at=datetime.now() - timedelta(days=60)))
        await db.commit()
        # 新帖标题与 60 天前库内帖近全同 → 窗口外不应挡
        new_title = existing_title + "！"
        posts = [{"title": new_title, "content": "c", "url": "https://m.weibo.cn/status/new",
                  "platform": "weibo", "source": "tikhub", "author": "a",
                  "likes": 0, "comments": 0, "shares": 0,
                  "published_at": (date.today() - timedelta(days=1)).isoformat()}]
        result = await s._cross_batch_dedup(posts, vehicle.id)
        assert len(result) == 1  # 窗口外 → 不挡

    @pytest.mark.asyncio
    async def test_empty_title_post_passes(self, db, vehicle):
        """空标题新帖无前缀 → 直接放行（后续品牌过滤/入库守卫处理）。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        db.add(RawPost(id="p-existing", vehicle_id=vehicle.id, source="tikhub",
                       platform="weibo", title="海豹相关内容标题", content="c",
                       url="https://m.weibo.cn/status/old",
                       collected_at=datetime.now() - timedelta(days=1)))
        await db.commit()
        posts = [{"title": "", "content": "c", "url": "https://m.weibo.cn/status/new",
                  "platform": "weibo", "source": "tikhub", "author": "a",
                  "likes": 0, "comments": 0, "shares": 0,
                  "published_at": (date.today() - timedelta(days=1)).isoformat()}]
        result = await s._cross_batch_dedup(posts, vehicle.id)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_interception_count_logged_always(self, db, vehicle, caplog):
        """T2.6：拦截计数无条件输出——0 拦截也打一行，日志存在即证明方法生效。"""
        import logging as _logging
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        with caplog.at_level(_logging.INFO, logger="pipeline.scheduler"):
            # 无库内帖、无同前缀 → 0 拦截，但日志必须出现
            result = await s._cross_batch_dedup(
                [{"title": "全新标题与库内无任何前缀重叠", "content": "c",
                  "url": "https://m.weibo.cn/status/new", "platform": "weibo",
                  "source": "tikhub", "author": "a", "likes": 0, "comments": 0,
                  "shares": 0, "published_at": date.today().isoformat()}],
                vehicle.id)
        assert len(result) == 1
        assert "跨批次去重" in caplog.text
        assert "0/1" in caplog.text


class TestCommentRemapOnDedup:
    """T2.4 评论 unmatched 修复：被当批次去重丢弃的帖，其评论搬迁到保留孪生帖。

    根因（实采 55/365 unmatched 排查）：评论在 collector 搜索内先抓，帖随后
    才被 deduplicate 丢弃——近重复转发稿内容近同但 URL 不同，其评论
    post_url 查无此帖全进 unmatched。deduplicate 在丢弃帖上标记
    duplicate_of_url，scheduler 据此改写评论 post_url。
    """

    def test_comments_of_dropped_post_remap_to_kept_twin(self):
        from pipeline.scheduler import CollectionScheduler
        pre = [
            {"url": "https://m.weibo.cn/status/kept", "title": "转发稿原文标题",
             "content": "c", "published_at": "2026-09-01"},
            {"url": "https://m.weibo.cn/status/dropped", "title": "转发稿原文标题！",
             "content": "c", "duplicate_of_url": "https://m.weibo.cn/status/kept",
             "published_at": "2026-09-02"},
        ]
        kept = [pre[0]]
        comments = [
            {"post_url": "https://m.weibo.cn/status/dropped", "content": "评论A"},
            {"post_url": "https://m.weibo.cn/status/kept", "content": "评论B"},
            {"post_url": "https://m.weibo.cn/status/unrelated", "content": "评论C"},
        ]
        out = CollectionScheduler._remap_comments_to_kept_posts(pre, kept, comments)
        # 丢弃帖的评论改挂保留帖
        assert out[0]["post_url"] == "https://m.weibo.cn/status/kept"
        # 其余评论原样
        assert out[1]["post_url"] == "https://m.weibo.cn/status/kept"
        assert out[2]["post_url"] == "https://m.weibo.cn/status/unrelated"

    def test_no_dropped_posts_returns_comments_unchanged(self):
        from pipeline.scheduler import CollectionScheduler
        pre = [{"url": "https://m.weibo.cn/status/a", "title": "t", "content": "c"}]
        comments = [{"post_url": "https://m.weibo.cn/status/a", "content": "x"}]
        out = CollectionScheduler._remap_comments_to_kept_posts(pre, list(pre), comments)
        assert out is comments

    def test_dropped_without_twin_marker_not_remapped(self):
        """无 duplicate_of_url 标记的丢弃帖（如空文本帖）评论不动。"""
        from pipeline.scheduler import CollectionScheduler
        pre = [
            {"url": "https://m.weibo.cn/status/kept", "title": "t1", "content": "c"},
            {"url": "https://m.weibo.cn/status/dropped", "title": "t2", "content": "c"},
        ]
        comments = [{"post_url": "https://m.weibo.cn/status/dropped", "content": "x"}]
        out = CollectionScheduler._remap_comments_to_kept_posts(pre, pre[:1], comments)
        assert out[0]["post_url"] == "https://m.weibo.cn/status/dropped"


# ── T1.2: 平台级限速 token bucket ────────────────────────────────────────
def test_platform_sem_singleton_and_default():
    """同平台返回同一信号量（缓存），未知平台默认 2。"""
    from pipeline.scheduler import _get_platform_sem, _platform_sems
    _platform_sems.clear()
    s1 = _get_platform_sem("douyin")
    s2 = _get_platform_sem("douyin")
    assert s1 is s2
    assert s1._value == 2
    s3 = _get_platform_sem("unknownplat")
    assert s3._value == 2


# ── T2: 车质网 30 天窗口（2026-09-28 修订：统一 30 天，不再首次/增量分支）──


class TestChezhiwangWindow:
    """_collect_chezhiwang 统一 30 天窗口 + max_pages=3，不区分首次/增量。"""

    @pytest.mark.asyncio
    async def test_first_time_uses_30_day_window(self, db, vehicle):
        """库内 0 车质网帖 → 仍 30 天窗 + max_pages=3（不再 180 天宽窗）。"""
        from pipeline.scheduler import CollectionScheduler
        from api.pipeline_state import PlatformProgress
        s = CollectionScheduler(db)
        captured: dict = {}

        async def _fake_search(vehicle_name, start_date, end_date, max_pages=None):
            captured["start_date"] = start_date
            captured["end_date"] = end_date
            captured["max_pages"] = max_pages
            return []

        with patch.object(s._chezhiwang, "search", AsyncMock(side_effect=_fake_search)):
            pp = PlatformProgress()
            await s._collect_chezhiwang(vehicle.id, vehicle.name, "2026-09-27", "2026-09-28", pp)
        expected_start = (date.today() - timedelta(days=30)).isoformat()
        assert captured["start_date"] == expected_start
        assert captured["max_pages"] == 3

    @pytest.mark.asyncio
    async def test_incremental_uses_30_day_window(self, db, vehicle):
        """库内已有车质网帖 → 30 天窗 + max_pages=3（与首次一致）。"""
        from pipeline.scheduler import CollectionScheduler
        from api.pipeline_state import PlatformProgress
        # 预置一条车质网帖
        db.add(RawPost(
            id="cz1", vehicle_id=vehicle.id, source="chezhiwang",
            platform="chezhiwang", title="已有投诉", content="c", url="https://bbs.12365auto.com/threadforum/20260901/1.shtml",
        ))
        await db.commit()
        s = CollectionScheduler(db)
        captured: dict = {}

        async def _fake_search(vehicle_name, start_date, end_date, max_pages=None):
            captured["start_date"] = start_date
            captured["max_pages"] = max_pages
            return []

        with patch.object(s._chezhiwang, "search", AsyncMock(side_effect=_fake_search)):
            pp = PlatformProgress()
            await s._collect_chezhiwang(vehicle.id, vehicle.name, "2026-09-27", "2026-09-28", pp)
        expected_start = (date.today() - timedelta(days=30)).isoformat()
        assert captured["start_date"] == expected_start
        assert captured["max_pages"] == 3

    @pytest.mark.asyncio
    async def test_window_ignores_social_start_date(self, db, vehicle):
        """社媒 start_date 不影响车质网窗口——始终 30 天。"""
        from pipeline.scheduler import CollectionScheduler
        from api.pipeline_state import PlatformProgress
        s = CollectionScheduler(db)
        captured: dict = {}

        async def _fake_search(vehicle_name, start_date, end_date, max_pages=None):
            captured["start_date"] = start_date
            return []

        # 传入极窄的社媒 start_date（模拟增量模式 1 天窗）
        with patch.object(s._chezhiwang, "search", AsyncMock(side_effect=_fake_search)):
            pp = PlatformProgress()
            await s._collect_chezhiwang(vehicle.id, vehicle.name, "2026-09-27", "2026-09-28", pp)
        expected_start = (date.today() - timedelta(days=30)).isoformat()
        assert captured["start_date"] == expected_start  # 不跟随社媒 2026-09-27
