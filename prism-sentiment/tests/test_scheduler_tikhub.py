"""Tests: scheduler 采集 provider 路由（2026-09-27 OneAPI 退役，单 provider）。

四平台搜索/评论/批量统计全走 TikHub（providers.py 单 provider 路由表）。
关键行为：
- 搜索路由打点（collector × platform × mode/window_days 透传）
- TikHub 未配置 key：平台 skip + env_warning 可见化（防伪 completed）
- fetch_top_comments 评论路由（douyin_comments 独立 key）
- douyin 批量统计经 douyin_stats 路由
注意：conftest 已隔离真实 key（collector 未配置态），本文件全部 patch
is_available / search / fetch_comments_for_post，无真网络路径；
日期动态（date.today()），防 90 天窗口定时炸弹。
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.schemas import Base, Vehicle
from pipeline.collectors.providers import DEFAULT_PROVIDERS, collect_providers
from pipeline.collectors.tikhub_collector import TikHubAuthError


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
    v = Vehicle(id="v-tikhub", name="海豹", brand="比亚迪", search_keywords='["海豹EV"]')
    db.add(v)
    await db.commit()
    return v


def _base_mocks(s):
    """collect_vehicle 的通用外围 mock 列表：news/全文/指数/节奏，隔离真实网络。"""
    return [
        patch.object(s, "_expand_keywords_if_needed",
                     new_callable=AsyncMock, return_value=["海豹EV"]),
        patch.object(s, "_collect_news",
                     new_callable=AsyncMock, return_value=[]),
        patch.object(s, "_crawl_full_texts",
                     new_callable=AsyncMock, side_effect=lambda p: p),
        patch("pipeline.scheduler.IndexCollector"),
        patch("pipeline.scheduler.asyncio.sleep", new_callable=AsyncMock),
    ]


def _wire_collectors(s, *, tikhub_available=True):
    """把真实 collector 的网络面全部换成 mock（availability + search）。"""
    return [
        patch.object(s._tikhub, "is_available",
                     AsyncMock(return_value=tikhub_available)),
    ]


class TestSearchRouting:
    @pytest.mark.asyncio
    async def test_default_routing_two_social_on_tikhub(self, db, vehicle):
        """默认路由：两社媒平台（含 douyin 搜索）全打 TikHub；mode/window 透传。

        2026-10-15 R23：微博/快手停采，调度面只剩 小红书/抖音。
        """
        import contextlib
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        with contextlib.ExitStack() as stack:
            for m in _base_mocks(s):
                stack.enter_context(m)
            for m in _wire_collectors(s):
                stack.enter_context(m)
            tik_search = stack.enter_context(
                patch.object(s._tikhub, "search", AsyncMock(return_value=([], []))))
            result = await s.collect_vehicle(vehicle.id)

        assert result["status"] == "completed"
        # 缺陷扩词（T1.1）后每平台多词搜索，按平台集合断言路由（非逐次计数）
        tik_platforms = [c.args[1] for c in tik_search.call_args_list]
        assert sorted(set(tik_platforms)) == ["douyin", "xiaohongshu"]
        # 参数透传：initial（无历史）+ 30 天窗（R40：start_date = today-30 → 31 天）
        for call in tik_search.call_args_list:
            assert call.kwargs["mode"] == "initial"
            assert call.kwargs["window_days"] == 31

    @pytest.mark.asyncio
    async def test_tikhub_unavailable_skips_all_social_with_env_warning(self, db, vehicle):
        """TikHub 无 key（未配置）：社媒全 skip + env_warning，news 链路不炸。"""
        import contextlib
        from api.pipeline_state import pipeline_progress
        from pipeline.scheduler import CollectionScheduler
        pipeline_progress.clear()
        s = CollectionScheduler(db)  # conftest 隔离 → collector 未配置
        with contextlib.ExitStack() as stack:
            for m in _base_mocks(s):
                stack.enter_context(m)
            tik_search = stack.enter_context(
                patch.object(s._tikhub, "search", AsyncMock(return_value=([], []))))
            result = await s.collect_vehicle(vehicle.id)

        assert result["status"] == "completed"
        tik_search.assert_not_called()
        progress = pipeline_progress.get(vehicle.id)
        assert progress is not None
        assert progress.env_warning and "TIKHUB_KEY" in progress.env_warning
        # 2026-10-15 R23：调度面只剩两社媒（progress 平台表同步收敛）
        for p in ("xiaohongshu", "douyin"):
            assert progress.platforms[p].phase == "skipped", p


class TestDouyinSearchNoFallback:
    """OneAPI 退役后抖音搜索直接 TikHub，无双 provider 回退路径。

    0 帖就是 0 帖（真无新帖或上游空窗），不存在"再试另一家"的语义。
    """

    def _progress(self):
        from api.pipeline_state import PlatformProgress
        return PlatformProgress()

    @pytest.mark.asyncio
    async def test_tikhub_zero_posts_returns_zero(self, db, vehicle):
        """TikHub 搜索 0 帖：如实返回 0，不重试不回退。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        with patch.object(s._tikhub, "is_available", AsyncMock(return_value=True)), \
             patch.object(s._tikhub, "search", AsyncMock(return_value=([], []))) as tik_search, \
             patch("pipeline.scheduler.asyncio.sleep", new_callable=AsyncMock):
            posts, comments = await s._collect_social_platform(
                vehicle.id, "douyin", ["小鹏M03"], self._progress(),
                collector=s._tikhub, provider="tikhub")
        tik_search.assert_called_once()  # 单 provider：只搜一轮
        assert posts == []
        assert comments == []


class TestResolveCollector:
    @pytest.mark.asyncio
    async def test_unknown_key_returns_none(self, db):
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        assert await s._resolve_collector("nonexistent") == (None, "")

    @pytest.mark.asyncio
    async def test_known_key_unconfigured_returns_none(self, db):
        """TikHub 未配置（conftest 隔离）：返回 (None, "tikhub")。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        assert await s._resolve_collector("weibo") == (None, "tikhub")


class TestFetchTopCommentsRouting:
    @pytest.mark.asyncio
    async def test_default_all_active_on_tikhub(self, db, vehicle):
        """默认评论路由：两社媒平台（含 douyin）全打 TikHub；停采平台 0 配额跳过。

        2026-10-15 R23/R41：weibo/kuaishou comment_top_n=0 → 即使选帖返回也不抓。
        """
        from pipeline.scheduler import CollectionScheduler
        fake_posts = [
            SimpleNamespace(url="https://m.weibo.cn/status/111", platform="weibo"),
            SimpleNamespace(url="https://www.xiaohongshu.com/explore/222", platform="xiaohongshu"),
            SimpleNamespace(url="https://www.kuaishou.com/short-video/3xabc", platform="kuaishou"),
            SimpleNamespace(url="https://www.douyin.com/video/333", platform="douyin"),
        ]
        async def _fake_fetch(url, platform):
            return [{"post_url": url, "post_note_id": url.rsplit("/", 1)[-1],
                     "content": "好评", "author": "u", "likes": 1,
                     "platform": platform, "published_at": ""}]
        with patch("pipeline.analysis.batch_runner.select_top_posts_for_comments",
                   new_callable=AsyncMock, return_value=fake_posts):
            s = CollectionScheduler(db)
            with patch.object(s._tikhub, "is_available", AsyncMock(return_value=True)), \
                 patch.object(s._tikhub, "fetch_comments_for_post",
                              AsyncMock(side_effect=_fake_fetch)) as tik_fetch:
                total = await s.fetch_top_comments(vehicle.id)

        assert total == 2  # 仅 xhs/douyin（weibo/kuaishou 停采配额 0 跳过）
        assert tik_fetch.call_count == 2
        assert sorted(c.args[1] for c in tik_fetch.call_args_list) == \
            ["douyin", "xiaohongshu"]

    @pytest.mark.asyncio
    async def test_tikhub_auth_error_breaks_loop(self, db, vehicle):
        """TikHubAuthError 账户级错误：评论补抓 break（后续帖不再尝试）。"""
        from pipeline.scheduler import CollectionScheduler
        fake_posts = [
            SimpleNamespace(url="https://www.douyin.com/video/1", platform="douyin"),
            SimpleNamespace(url="https://www.douyin.com/video/2", platform="douyin"),
        ]
        with patch("pipeline.analysis.batch_runner.select_top_posts_for_comments",
                   new_callable=AsyncMock, return_value=fake_posts):
            s = CollectionScheduler(db)
            with patch.object(s._tikhub, "is_available", AsyncMock(return_value=True)), \
                 patch.object(s._tikhub, "fetch_comments_for_post",
                              AsyncMock(side_effect=TikHubAuthError("TikHub HTTP 401"))) as tik_fetch:
                total = await s.fetch_top_comments(vehicle.id)

        assert total == 0
        tik_fetch.assert_called_once()  # 第一帖抛 AuthError → break


class TestDouyinStatsRouting:
    @pytest.mark.asyncio
    async def test_default_stats_on_tikhub(self, db):
        """douyin_stats 路由 TikHub（fetch_multi_video_statistics，$0.025/批）。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        with patch.object(s._tikhub, "is_available", AsyncMock(return_value=True)), \
             patch.object(s._tikhub._client, "fetch_douyin_play_stats",
                          AsyncMock(return_value={"111": {"play_count": 10}})) as tik_stats:
            stats = await s._fetch_douyin_play_stats(["111"])

        assert stats == {"111": {"play_count": 10}}
        tik_stats.assert_called_once_with(["111"])

    @pytest.mark.asyncio
    async def test_stats_unconfigured_returns_empty(self, db):
        """TikHub 未配置：log warning + 返回 {}（调用方按空结果容错）。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)  # conftest 隔离 → 未配置
        assert await s._fetch_douyin_play_stats(["111"]) == {}
        assert await s._fetch_douyin_play_stats([]) == {}


class TestProviders:
    def test_defaults_all_tikhub(self):
        """单 provider 路由表：六 key 全 tikhub（OneAPI 已退役）。"""
        assert set(DEFAULT_PROVIDERS.values()) == {"tikhub"}
        assert set(DEFAULT_PROVIDERS) == {
            "weibo", "xiaohongshu", "kuaishou",
            "douyin_search", "douyin_comments", "douyin_stats"}

    def test_returns_copy(self):
        """返回副本：调用方改写不污染默认表。"""
        providers = collect_providers()
        providers["weibo"] = "something-else"
        assert collect_providers()["weibo"] == "tikhub"
