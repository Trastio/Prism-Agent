"""T1.5 互动数刷新（A3）——每日批量刷新近30天帖互动数，治快照冻结。

策略（2026-09-27 OneAPI 退役后全走 TikHub）：
- 抖音：批量统计端点 fetch_douyin_play_stats（便宜，全刷近30天帖）
- 快手：批量详情端点 fetch_videos_batch（≤40/批，全刷近30天帖）
- 微博：无批量端点，只刷 top30 帖（按 likes+comments 降序，web_v2 详情
  端点逐帖刷新——控成本，避免逐帖计费刷全量）
- 小红书：无批量端点，只刷 top30 帖（app_v2 get_image_note_detail 逐帖）
- 刷新失败不阻断（记 warning 跳过该批/该帖）
"""
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from unittest.mock import AsyncMock, patch

from models.schemas import Base, RawPost, Vehicle
from pipeline.collectors.tikhub_collector import TikHubClient
from scripts.refresh_engagement import refresh_vehicle_engagement, run_all


@pytest_asyncio.fixture
async def env():
    """共享一个内存库 session（无 HTTP client，刷新脚本只操作 DB）。"""
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


async def _seed_vehicle(s, vid="v1", name="M03"):
    s.add(Vehicle(id=vid, name=name, brand="小鹏"))
    await s.commit()


async def _seed_post(s, vid, pid, platform, url, likes=10, comments=1, shares=0,
                     published_at=None):
    s.add(RawPost(
        id=pid, vehicle_id=vid, source="tikhub", platform=platform,
        title=f"帖{pid}", content=f"内容{pid}", author="作者",
        url=url, published_at=published_at or datetime.now(),
        collected_at=datetime.now(), likes=likes, comments=comments,
        shares=shares, analysis_status="analyzed",
    ))
    await s.commit()


@pytest.mark.asyncio
async def test_douyin_batch_refresh(env):
    """抖音帖用批量统计端点刷新互动数：likes 10→500 回写 DB。"""
    s = env
    await _seed_vehicle(s)
    await _seed_post(s, "v1", "p1", "douyin",
                     "https://www.douyin.com/video/aweme123", likes=10)
    client = TikHubClient()
    with patch.object(TikHubClient, "fetch_douyin_play_stats",
                      new=AsyncMock(return_value={
                          "aweme123": {"digg_count": 500, "comment_count": 50,
                                       "share_count": 5}
                      })):
        n = await refresh_vehicle_engagement(s, "v1", client=client)
    assert n == 1
    post = (await s.execute(select(RawPost).where(RawPost.id == "p1"))).scalar_one()
    assert post.likes == 500
    assert post.comments == 50
    assert post.shares == 5


@pytest.mark.asyncio
async def test_stopped_platforms_not_refreshed(env):
    """停采平台（weibo/kuaishou，R23）存量帖不再刷互动（2026-10-16 T7 实测补刀）。

    停采渠道数字定格在最后一次刷新值，随 30 天保留线自然出库——
    T7 首跑曾实证停采平台逐帖刷新占 225 次/天无效消耗面。
    """
    s = env
    await _seed_vehicle(s)
    for i in range(20):
        await _seed_post(s, "v1", f"w{i}", "weibo",
                         f"https://m.weibo.cn/status/wb{i}", likes=i)
    await _seed_post(s, "v1", "k1", "kuaishou",
                     "https://www.kuaishou.com/short-video/photoAAA", likes=7)
    client = TikHubClient()
    mock_get = AsyncMock()
    with patch.object(TikHubClient, "get", new=mock_get):
        n = await refresh_vehicle_engagement(s, "v1", client=client)
    assert n == 0                      # 零帖刷新
    assert mock_get.call_count == 0    # 零 API 调用（含批量端点）
    post = (await s.execute(select(RawPost).where(RawPost.id == "w19"))).scalar_one()
    assert post.likes == 19            # 数字定格不被改写


@pytest.mark.asyncio
async def test_xhs_topn_refresh(env):
    """小红书帖用 app_v2 详情端点刷 top30：likes 8→478 回写 DB。"""
    s = env
    await _seed_vehicle(s)
    await _seed_post(s, "v1", "x1", "xiaohongshu",
                     "https://www.xiaohongshu.com/explore/note1", likes=8)
    client = TikHubClient()
    # 实采确认响应：双层信封 data[0].note_list[0].liked_count
    mock_get = AsyncMock(return_value={
        "code": 200, "success": True,
        "data": [{"note_list": [{"liked_count": 478, "comments_count": 96,
                                  "shared_count": 44}]}],
    })
    with patch.object(TikHubClient, "get", new=mock_get):
        n = await refresh_vehicle_engagement(s, "v1", client=client)
    assert n == 1
    post = (await s.execute(select(RawPost).where(RawPost.id == "x1"))).scalar_one()
    assert post.likes == 478
    assert post.comments == 96
    assert post.shares == 44


@pytest.mark.asyncio
async def test_refresh_failure_doesnt_block(env):
    """刷新失败不阻断（记 warning 跳过该批），原值不变。"""
    s = env
    await _seed_vehicle(s)
    await _seed_post(s, "v1", "p1", "douyin",
                     "https://www.douyin.com/video/a1", likes=10)
    client = TikHubClient()
    with patch.object(TikHubClient, "fetch_douyin_play_stats",
                      new=AsyncMock(side_effect=RuntimeError("boom"))):
        n = await refresh_vehicle_engagement(s, "v1", client=client)
    assert n == 0  # 失败跳过，不 raise
    post = (await s.execute(select(RawPost).where(RawPost.id == "p1"))).scalar_one()
    assert post.likes == 10  # 原值不变


@pytest.mark.asyncio
async def test_no_posts_returns_zero(env):
    """无近30天帖时返回 0，不调任何端点。"""
    s = env
    await _seed_vehicle(s)
    client = TikHubClient()
    mock_dy = AsyncMock(return_value={})
    with patch.object(TikHubClient, "fetch_douyin_play_stats", new=mock_dy):
        n = await refresh_vehicle_engagement(s, "v1", client=client)
    assert n == 0
    assert mock_dy.call_count == 0


@pytest.mark.asyncio
async def test_run_all_recalcs_heat_after_refresh():
    """审计 P1-3：daily_update 收尾 run_all 每车刷新后重算热度（原只刷新不重算）。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        await _seed_vehicle(s, "v1")
        await _seed_post(s, "v1", "p1", "douyin",
                         "https://www.douyin.com/video/a1", likes=10)

    with patch("scripts.refresh_engagement.async_session", factory), \
         patch("models.database.engine", engine), \
         patch.object(TikHubClient, "fetch_douyin_play_stats",
                      new=AsyncMock(return_value={})), \
         patch("scripts.refresh_engagement.HeatMetricCalculator") as MockCalc:
        instance = MockCalc.return_value
        instance.calculate_range = AsyncMock()
        await run_all()

    instance.calculate_range.assert_awaited_once()
    await engine.dispose()
