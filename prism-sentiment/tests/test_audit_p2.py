"""审计 P2 回归：fetch_failures 终态可见（P2-7）+ 互动数零值覆盖守卫（P2-8）。"""
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from api.pipeline_state import pipeline_phases
from api.routes.collection import _run_full_pipeline
from models.schemas import Base, RawPost, Vehicle


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    pipeline_phases.clear()
    await engine.dispose()


async def test_pipeline_completed_carries_fetch_failures(db):
    """P2-7：采集关键词失败要进终态 dict（原聚合进 collecting 后被 completed 覆盖）。"""
    async with db() as session:
        session.add(Vehicle(id="vff", name="海豹", brand="比亚迪", search_keywords='["海豹"]'))
        await session.commit()

    # 2026-10-15 R31 news 停采后，失败注入点换到车质网阶段（无条件执行；
    # 社媒阶段在无 TIKHUB_KEY 的测试环境里会被 _resolve_collector 先 skip）
    async def fake_cz(self, vid, vehicle_name, start_date, end_date, progress):
        progress.fetch_failures.append("海豹 故障")
        return []

    with patch("pipeline.scheduler.CollectionScheduler._collect_chezhiwang", new=fake_cz):
        await _run_full_pipeline("vff", _session_factory=db)

    assert pipeline_phases["vff"]["phase"] == "completed"
    assert "海豹 故障" in pipeline_phases["vff"].get("fetch_failures", [])


async def test_store_posts_zero_stats_does_not_clobber(db):
    """P2-8：重遇已入库帖且新快照统计为 0 → 不把库内真值清零；非零新值照常覆盖。"""
    async with db() as session:
        session.add(Vehicle(id="vz", name="海豹", brand="比亚迪"))
        post = RawPost(
            id="pz1", vehicle_id="vz", source="tikhub", platform="douyin",
            title="海豹真值帖", content="内容", url="https://v.douyin.com/abc123",
            likes=500, comments=60, shares=7, analysis_status="analyzed",
        )
        session.add(post)
        await session.commit()

        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(session)

        def _post_dict(likes, comments, shares):
            return {"title": "海豹真值帖", "content": "内容",
                    "url": "https://v.douyin.com/abc123",
                    "source": "tikhub", "platform": "douyin",
                    "likes": likes, "comments": comments, "shares": shares,
                    "published_at": (date.today() - timedelta(days=2)).isoformat()}

        # 全 0 快照（抖音上游选择性回填形态）：三个真值都不被清零
        await s._store_posts("vz", [_post_dict(0, 0, 0)],
                             min_date=None, vehicle_name="海豹", vehicle_brand="比亚迪")
        await session.refresh(post)
        assert (post.likes, post.comments, post.shares) == (500, 60, 7)

        # 非零快照：likes 覆盖为 600，0 值的 comments/shares 保持真值
        await s._store_posts("vz", [_post_dict(600, 0, 0)],
                             min_date=None, vehicle_name="海豹", vehicle_brand="比亚迪")
        await session.refresh(post)
        assert post.likes == 600
        assert (post.comments, post.shares) == (60, 7)

        # 重遇不重复入库（URL path 去重）
        cnt = (await session.execute(
            select(func.count()).select_from(RawPost).where(RawPost.vehicle_id == "vz")
        )).scalar()
        assert cnt == 1
