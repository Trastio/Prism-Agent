"""Fleet 端点：全车增量采集（频率分层）。

P0-A：每车独立 session（不共用 request session，避免 AsyncSession 并发错误）。
P0-B：管线级并发上限在 _run_full_pipeline 入口（_PIPELINE_SEM），非此处。
P1-1：counts 由 to_thread 传入 select_by_frequency，不阻塞事件循环。
P2-5：无 concurrency 死参数（_PIPELINE_SEM 硬编码 3）。
"""
import asyncio
import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_session, async_session
from models.schemas import Vehicle, CollectionStatus
from pipeline.frequency import select_by_frequency, recent_post_counts, db_path
from api.pipeline_state import pipeline_phases

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fleet", tags=["fleet"])


@router.post("/collect")
async def trigger_fleet_collect(
    session: AsyncSession = Depends(get_session),
):
    """全车增量采集（频率分层）。

    P0-A：每车独立 session。
    P1-1：counts 由 to_thread 传入 select_by_frequency。
    """
    vehicles = (await session.execute(
        select(Vehicle).where(Vehicle.status == "active")
    )).scalars().all()
    veh_dicts = [{"id": v.id, "name": v.name, "status": v.status} for v in vehicles]

    # P1-1：同步查库用 to_thread 包裹避免阻塞事件循环
    counts = await asyncio.to_thread(
        recent_post_counts, [v["id"] for v in veh_dicts], db_path()
    )
    targets, skipped = select_by_frequency(veh_dicts, counts, date.today())

    # P0-A：每车独立 session（不共用 request session）
    # F-2：import 提到循环外（import 有缓存无害，纯风格；G-1 全口径禁函数体 import）
    from api.routes.collection import trigger_collection as _tc  # noqa: inline-import
    started = []
    for v in targets:
        try:
            async with async_session() as s:
                await _tc(v["id"], s)
            started.append(v["id"])
        except Exception as e:
            logger.warning("fleet collect %s failed: %s", v["name"], e)

    return {"started": started, "skipped": [{"name": n, "tier": t} for n, t in skipped]}


# D2：脏锁容错阈值，与 collection.py:169-173 对齐
_LOCK_STALE_MINUTES = 30


@router.get("/status")
async def get_fleet_status(session: AsyncSession = Depends(get_session)):
    """全局采集活动状态：进行中车数 + 各车 phase。

    D2：前端 mounted 调此端点恢复 fleetCollecting（跨会话）。
    P1-2 脏锁容错：is_running=True 但 lock_acquired_at 超 30min 视为崩溃残留，
    不计入运行中（对齐 collection.py:169-173），避免进程被 kill 后
    DB 锁残留导致前端永久禁用刷新按钮。
    """
    rows = (await session.execute(
        select(Vehicle, CollectionStatus).outerjoin(
            CollectionStatus, and_(
                CollectionStatus.vehicle_id == Vehicle.id,
                CollectionStatus.source == "all",
            )
        ).where(Vehicle.status == "active")
    )).all()

    now = datetime.now()
    in_progress = []
    for v, cs in rows:
        if not cs or not cs.is_running:
            continue
        lock_time = cs.lock_acquired_at or cs.last_collected_at
        if not lock_time or now - lock_time > timedelta(minutes=_LOCK_STALE_MINUTES):
            continue  # 脏锁，不计入
        phase = pipeline_phases.get(v.id, {}).get("phase", "unknown")
        in_progress.append({"id": v.id, "name": v.name, "phase": phase})

    return {
        "is_running": len(in_progress) > 0,
        "in_progress_count": len(in_progress),
        "vehicles": in_progress,
    }
