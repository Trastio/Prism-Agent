"""Tests: 采集容错（A7）——429/超时指数退避重试 2 次 + 失败计数前端可见。

分层容错行为：
- 网络/超时类异常（httpx.TimeoutException/ConnectError/ConnectionError）→
  scheduler 层指数退避重试 2 次（1s, 2s）；首次失败二次成功 → 拿到结果；
  三次都失败 → 返回空 + 记 fetch_failures。
- collector 内部重试耗尽（TikHubError 非 auth）→ 记 fetch_failures
  跳过该词，不拖垮整平台。
- 账户级错误（TikHubAuthError）→ 立即 raise 不断管线不重试。
- 代码 bug（KeyError/AttributeError）→ 不重试不吞，直接抛出。
"""

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from unittest.mock import AsyncMock, patch

from api.pipeline_state import PlatformProgress
from models.schemas import Base, Vehicle
from pipeline.collectors.tikhub_collector import TikHubAuthError, TikHubError


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
    v = Vehicle(id="v-resilience", name="星愿", brand="吉利", search_keywords='["星愿"]')
    db.add(v)
    await db.commit()
    return v


class TestCollectionResilience:
    """A7 采集容错：重试语义 + 失败计数可见。"""

    @pytest.mark.asyncio
    async def test_network_timeout_then_success_retries_and_returns_result(self, db, vehicle):
        """首次超时、二次成功 → 重试拿到结果，不记失败。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        post = {"url": "https://weibo.com/123", "platform": "weibo", "title": "t"}
        # side_effect: 第一次超时，第二次成功
        side_effects = [
            httpx.TimeoutException("connect timed out"),
            ([post], []),
        ]
        with patch.object(s._tikhub, "is_available", AsyncMock(return_value=True)), \
             patch.object(s._tikhub, "search", AsyncMock(side_effect=side_effects)), \
             patch("pipeline.scheduler.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            progress = PlatformProgress()
            posts, comments = await s._collect_social_platform(
                vehicle.id, "weibo", ["星愿"], progress,
                collector=s._tikhub, provider="tikhub",
            )
        assert len(posts) == 1
        assert posts[0]["url"] == "https://weibo.com/123"
        assert progress.fetch_failures == []  # 重试成功不算失败
        # 指数退避：失败后 sleep(2**0)=1s 一次
        assert sleep_mock.await_count >= 1

    @pytest.mark.asyncio
    async def test_network_timeout_all_attempts_records_failure(self, db, vehicle):
        """三次都超时 → 返回空 + fetch_failures 记录该关键词。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        with patch.object(s._tikhub, "is_available", AsyncMock(return_value=True)), \
             patch.object(s._tikhub, "search",
                          AsyncMock(side_effect=httpx.ConnectError("refused"))), \
             patch("pipeline.scheduler.asyncio.sleep", new_callable=AsyncMock):
            progress = PlatformProgress()
            posts, comments = await s._collect_social_platform(
                vehicle.id, "weibo", ["星愿"], progress,
                collector=s._tikhub, provider="tikhub",
            )
        assert posts == []
        assert comments == []
        assert progress.fetch_failures == ["星愿"]
        # 前端可见：to_dict 暴露 fetch_failures
        d = progress.to_dict()
        assert d["fetch_failures"] == ["星愿"]

    @pytest.mark.asyncio
    async def test_connection_error_retries(self, db, vehicle):
        """ConnectionError（非 httpx）也走重试路径。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        post = {"url": "https://weibo.com/c", "platform": "weibo"}
        side_effects = [
            ConnectionError("reset"),
            ([post], []),
        ]
        with patch.object(s._tikhub, "is_available", AsyncMock(return_value=True)), \
             patch.object(s._tikhub, "search", AsyncMock(side_effect=side_effects)), \
             patch("pipeline.scheduler.asyncio.sleep", new_callable=AsyncMock):
            progress = PlatformProgress()
            posts, _ = await s._collect_social_platform(
                vehicle.id, "weibo", ["星愿"], progress,
                collector=s._tikhub, provider="tikhub",
            )
        assert len(posts) == 1
        assert progress.fetch_failures == []

    @pytest.mark.asyncio
    async def test_collector_exhausted_error_records_failure_no_crash(self, db, vehicle):
        """collector 内部重试耗尽（TikHubError 非 auth）→ 记失败跳过，不拖垮整平台。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        with patch.object(s._tikhub, "is_available", AsyncMock(return_value=True)), \
             patch.object(s._tikhub, "search",
                          AsyncMock(side_effect=TikHubError("重试耗尽"))), \
             patch("pipeline.scheduler.asyncio.sleep", new_callable=AsyncMock):
            progress = PlatformProgress()
            # 不应抛出（collector 级错误记失败继续）
            posts, comments = await s._collect_social_platform(
                vehicle.id, "weibo", ["星愿"], progress,
                collector=s._tikhub, provider="tikhub",
            )
        assert posts == []
        assert progress.fetch_failures == ["星愿"]

    @pytest.mark.asyncio
    async def test_auth_error_raises_no_retry(self, db, vehicle):
        """账户级错误（TikHubAuthError）→ 立即 raise，不重试不记失败。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        search_mock = AsyncMock(side_effect=TikHubAuthError("HTTP 402: 余额耗尽"))
        with patch.object(s._tikhub, "is_available", AsyncMock(return_value=True)), \
             patch.object(s._tikhub, "search", search_mock), \
             patch("pipeline.scheduler.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            progress = PlatformProgress()
            with pytest.raises(TikHubAuthError):
                await s._collect_social_platform(
                    vehicle.id, "weibo", ["星愿"], progress,
                    collector=s._tikhub, provider="tikhub",
                )
        # 账户级错误不重试（search 只调一次）
        assert search_mock.await_count == 1
        # 不记 fetch_failures（账户级错误走 env_warning 通道，不是丢词）
        assert progress.fetch_failures == []

    @pytest.mark.asyncio
    async def test_code_bug_propagates_not_swallowed(self, db, vehicle):
        """代码 bug（KeyError）→ 不重试不吞，直接抛出暴露问题。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        with patch.object(s._tikhub, "is_available", AsyncMock(return_value=True)), \
             patch.object(s._tikhub, "search",
                          AsyncMock(side_effect=KeyError("missing_field"))), \
             patch("pipeline.scheduler.asyncio.sleep", new_callable=AsyncMock):
            progress = PlatformProgress()
            with pytest.raises(KeyError):
                await s._collect_social_platform(
                    vehicle.id, "weibo", ["星愿"], progress,
                    collector=s._tikhub, provider="tikhub",
                )
        # 代码 bug 不记 fetch_failures（它该被修，而非伪装成丢词）
        assert progress.fetch_failures == []

    @pytest.mark.asyncio
    async def test_partial_keyword_failures_collected(self, db, vehicle):
        """多关键词：一个超时耗尽 + 一个成功 → 成功的拿到 + 失败的记入。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        # 2026-10-15 R23：weibo 停采后 get_strategy 回落 _DEFAULT（max_kw=1），直接调用换 douyin
        post = {"url": "https://www.douyin.com/video/ok1", "platform": "douyin"}

        def side(kw, platform, **kw_):
            if kw == "星愿":
                raise httpx.TimeoutException("timeout")
            return ([post], [])

        with patch.object(s._tikhub, "is_available", AsyncMock(return_value=True)), \
             patch.object(s._tikhub, "search", AsyncMock(side_effect=side)), \
             patch("pipeline.scheduler.asyncio.sleep", new_callable=AsyncMock):
            progress = PlatformProgress()
            posts, _ = await s._collect_social_platform(
                vehicle.id, "douyin", ["星愿", "吉利星愿"], progress,
                collector=s._tikhub, provider="tikhub",
            )
        assert len(posts) == 1  # 第二个词成功
        assert progress.fetch_failures == ["星愿"]  # 第一个词失败记入
