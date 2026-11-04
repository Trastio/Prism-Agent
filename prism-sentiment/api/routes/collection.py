import asyncio
import json
import logging
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.pipeline_state import PipelineProgress, pipeline_progress, pipeline_phases, _is_phase_stale
from models.database import get_session, async_session
from models.schemas import AnalyzedPost, CollectionStatus, DefectTheme, Vehicle
from pipeline.analysis.batch_runner import BatchAnalysisRunner
from pipeline.analysis.heat_calculator import HeatMetricCalculator
from pipeline.scheduler import CollectionScheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vehicles", tags=["collection"])

# 全局 task 注册表：持有运行中 task 引用防 GC（asyncio 文档要求保存引用）
_running_tasks: dict[str, asyncio.Task] = {}

# P0-B：跨车共享并发上限，覆盖 _run_full_pipeline 全程（避免 20 车 × 15 词 × 5 次重试风暴）
_PIPELINE_SEM = asyncio.Semaphore(3)

# P1-C：refresh 相位加入判定集（与 daily_update.py ACTIVE_PHASES 同语义，不硬编码多处）
ACTIVE_PHASES = {"collecting", "analyzing", "calculating"}
REFRESHING_PHASES = ACTIVE_PHASES | {"refreshing"}


def _collect_fetch_failures(vehicle_id: str) -> list[str]:
    """聚合 progress 各平台 fetch_failures（审计 P2-7）。

    原失败词聚合进 collecting dict 后被 completed/error 覆盖——采集完成后
    /pipeline-status 查不到失败关键词。终态 dict 挂上即不丢。
    """
    progs = getattr(pipeline_progress.get(vehicle_id), "platforms", {})
    failures: list[str] = []
    for pp in progs.values():
        failures.extend(pp.fetch_failures)
    return failures


async def _run_full_pipeline(vehicle_id: str, _session_factory=None):
    _sf = _session_factory or async_session
    pipeline_phases[vehicle_id] = {"phase": "collecting", "posts_collected": 0, "analyzed": 0, "error": None, "_updated_at": datetime.now()}

    # P2-4 + P1-3：SEM 包住整个 try/finally（含尾部释放段），CancelledError 也释放锁
    async with _PIPELINE_SEM:
        try:
            async with _sf() as session:
                try:
                    # Phase 1: Collection
                    scheduler = CollectionScheduler(session)
                    result = await scheduler.collect_vehicle(vehicle_id)

                    # P1-1（Step7 审查）：budget_capped 与 error 同为终态早退——
                    # 原实现只判 error，触顶后会继续跑 Phase 2-9 并在收尾把终态
                    # 覆盖成 completed，护栏事件对 daily_update 不可见（假"完成"）。
                    if result.get("status") in ("error", "budget_capped"):
                        pipeline_phases[vehicle_id] = {"phase": result.get("status"), "posts_collected": 0, "analyzed": 0, "error": result.get("error"), "_updated_at": datetime.now()}
                        return

                    posts_collected = result.get("posts_collected", 0)

                    # Phase 2: Analysis
                    pipeline_phases[vehicle_id] = {"phase": "analyzing", "posts_collected": posts_collected, "analyzed": 0, "error": None, "_updated_at": datetime.now()}

                    runner = BatchAnalysisRunner(session)
                    analysis_result = await runner.run_for_vehicle(vehicle_id)
                    analyzed = analysis_result.get("analyzed", 0)

                    # Phase 3: Heat calculation
                    pipeline_phases[vehicle_id] = {"phase": "calculating", "posts_collected": posts_collected, "analyzed": analyzed, "error": None, "_updated_at": datetime.now()}

                    calc = HeatMetricCalculator(session)
                    end = date.today()
                    start = end - timedelta(days=90)
                    await calc.calculate_range(vehicle_id, start, end)

                    # Phase 4: On-demand comment fetching for top posts
                    # （审计 P1-2：补抓必须先于摘要——两者选同一批帖
                    # select_top_posts_for_comments，先补抓则摘要/ABSA 当轮就
                    # 覆盖完整评论；与 _run_analysis_pipeline 契约一致）
                    try:
                        await scheduler.fetch_top_comments(vehicle_id)
                    except Exception as e:
                        logger.warning("On-demand comments failed: %s", e)

                    # Phase 5: Comment summaries for top posts
                    try:
                        await runner.run_comment_summaries(vehicle_id)
                    except Exception as e:
                        logger.warning("Comment summaries failed: %s", e)

                    # Phase 6: Comment dimension analysis via local ABSA
                    try:
                        cmt_analyzed = await runner.run_comment_analysis(vehicle_id)
                        pipeline_phases[vehicle_id]["comments_analyzed"] = cmt_analyzed
                    except Exception as e:
                        logger.warning("Comment ABSA failed: %s", e)

                    # Phase 7: Event detection (keyword graph + Louvain) — separate social and news
                    try:
                        from pipeline.analysis.event_tracker import detect_events_for_vehicle  # noqa: inline-import
                        await detect_events_for_vehicle(vehicle_id, session, source="social")
                        await detect_events_for_vehicle(vehicle_id, session, source="news")
                    except Exception as e:
                        logging.getLogger(__name__).warning("Event detection failed: %s", e)

                    # Phase 8: 缺陷话题挖掘（发酵层；失败不断管线）+ 结果落库
                    # 2026-10-20 闭环改造：①固定 30 天权威窗（不吃上方采集窗——
                    # 原 90 天窗与浏览侧 30 天窗互踩，每次切换全量重算烧 LLM）；
                    # ②LLM 判定失败（degraded）保旧载荷，不再空覆盖
                    logger.info("Phase 8 defect mining started: vehicle=%s", vehicle_id)
                    try:
                        from pipeline.analysis.defect_miner import mine_defect_themes  # noqa: inline-import
                        d_end = date.today()
                        d_start = d_end - timedelta(days=29)
                        themes, degraded = await mine_defect_themes(
                            vehicle_id, session,
                            start=d_start.isoformat(), end=d_end.isoformat())
                        if degraded:
                            logger.warning(
                                "Phase 8 defect mining degraded (LLM judge failed): "
                                "keep old payload for %s", vehicle_id)
                        else:
                            await session.execute(
                                delete(DefectTheme).where(DefectTheme.vehicle_id == vehicle_id)
                            )
                            session.add(DefectTheme(
                                id=str(uuid.uuid4()), vehicle_id=vehicle_id,
                                payload=json.dumps(themes),
                                window_start=d_start.isoformat(),
                                window_end=d_end.isoformat(),
                            ))
                            await session.commit()
                            pipeline_phases[vehicle_id]["defect_themes"] = len(themes)
                            logger.info("Phase 8 defect mining completed: %d themes for %s",
                                        len(themes), vehicle_id)
                    except Exception as e:
                        logger.warning("Defect mining failed: %s", e)

                    # Phase 9: 互动刷新（/collect 触发也刷新，不只 daily_update 收尾——
                    # 手动补采的热帖互动数快照冻结问题同样要治）。失败只 warning 不断管线。
                    try:
                        from scripts.refresh_engagement import refresh_vehicle_engagement  # noqa: inline-import
                        n = await refresh_vehicle_engagement(session, vehicle_id)
                        logger.info("Engagement refreshed: %d posts for %s", n, vehicle_id)
                        # 审计 P1-3：刷新后重算热度——原顺序热度先算、刷新在后且不重算，
                        # 热度永远用上一轮互动数（榜单滞后一轮）
                        await calc.calculate_range(vehicle_id, start, end)
                    except Exception as e:
                        logger.warning("Engagement refresh failed: %s", e)

                    # P2-7：终态带上 fetch_failures（原聚合进 collecting dict 后被覆盖）
                    final = {"phase": "completed", "posts_collected": posts_collected, "analyzed": analyzed, "error": None, "_updated_at": datetime.now()}
                    failures = _collect_fetch_failures(vehicle_id)
                    if failures:
                        final["fetch_failures"] = failures
                    pipeline_phases[vehicle_id] = final
                    logger.info("Pipeline completed: vehicle=%s, collected=%d, analyzed=%d", vehicle_id, posts_collected, analyzed)

                except Exception as e:
                    logger.error("Pipeline failed for %s: %s", vehicle_id, e)
                    final = {"phase": "error", "posts_collected": 0, "analyzed": 0, "error": str(e), "_updated_at": datetime.now()}
                    failures = _collect_fetch_failures(vehicle_id)
                    if failures:
                        final["fetch_failures"] = failures
                    pipeline_phases[vehicle_id] = final
        finally:
            # audit Phase 1 T1.4：释放 DB 锁移到 finally，确保 CancelledError/崩溃也释放
            # P1-3：finally 保留（CancelledError 是 BaseException 不被 except Exception 捕获）
            try:
                async with _sf() as rel:
                    await rel.execute(
                        update(CollectionStatus).where(
                            CollectionStatus.vehicle_id == vehicle_id,
                            CollectionStatus.source == "all",
                        ).values(is_running=False)
                    )
                    await rel.commit()
            except Exception:
                pass


@router.post("/{vehicle_id}/collect")
async def trigger_collection(vehicle_id: str, session: AsyncSession = Depends(get_session)):
    vehicle = await session.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(404, detail="Vehicle not found")

    phase_info = pipeline_phases.get(vehicle_id, {})
    # P1-3：相位命中且非 stale 才拒绝（refresh task 挂起 30min 后可逃逸）
    if phase_info.get("phase") in REFRESHING_PHASES and not _is_phase_stale(phase_info):
        return {"vehicle_id": vehicle_id, "status": "already_running", "phase": phase_info["phase"]}

    # F-1：DB 级并发锁——内存 dict 重启后清空，DB is_running 持久化防重启后并发同车
    # 脏锁容错（code-review #1）：is_running=True 但超过 30 分钟视为崩溃残留，重置
    cs = (await session.execute(
        select(CollectionStatus).where(
            CollectionStatus.vehicle_id == vehicle_id,
            CollectionStatus.source == "all",
        )
    )).scalar_one_or_none()
    if cs and cs.is_running:
        # §3.8 L5：脏锁判据用 lock_acquired_at（加锁时刻），而非 last_collected_at
        # （last_collected_at 只在采集完成时更新，无法区分"本次运行已 30min"与"上次完成已 30min 前"）
        lock_time = cs.lock_acquired_at or cs.last_collected_at  # 兼容旧数据
        stale = (not lock_time or datetime.now() - lock_time > timedelta(minutes=30))
        if not stale:
            return {"vehicle_id": vehicle_id, "status": "already_running", "phase": "collecting(db_lock)"}
        logger.warning("检测到脏 DB 锁（is_running 超 30min），重置: vehicle=%s", vehicle_id)
    if cs:
        cs.is_running = True
        cs.lock_acquired_at = datetime.now()  # §3.8 L5：记录加锁时刻
        await session.commit()
    else:
        cs = CollectionStatus(vehicle_id=vehicle_id, source="all", mode="initial",
                              is_running=True, lock_acquired_at=datetime.now())
        session.add(cs)
        await session.commit()

    # 持有 task 引用防 GC + 取消同车 zombie
    old = _running_tasks.get(vehicle_id)
    if old and not old.done():
        old.cancel()
        logger.info("取消同车旧 task: vehicle=%s", vehicle_id)
    task = asyncio.create_task(_run_full_pipeline(vehicle_id))
    _running_tasks[vehicle_id] = task
    task.add_done_callback(lambda t: _running_tasks.pop(vehicle_id, None))
    return {"vehicle_id": vehicle_id, "status": "started", "phase": "collecting"}


@router.post("/{vehicle_id}/refresh-engagement")
async def trigger_refresh_engagement(vehicle_id: str, session: AsyncSession = Depends(get_session)):
    """单车互动刷新 + 热度重算。异步 task。

    P0-3：不在请求内 await，避免 HTTP 长阻塞。
    P1-2：写 CollectionStatus.is_running=True + lock_acquired_at（与采集同构），
          避免 /pipeline-status DB-first 短路返回 completed。
    P1-C：复用 _running_tasks 单字典 + "refreshing" 在判定集内。
    P1-3：判定加 _is_phase_stale 逃逸。
    P2-1：refresh 不进 _PIPELINE_SEM（轻量，不搜新帖）。
    """
    vehicle = await session.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(404, detail="Vehicle not found")

    phase_info = pipeline_phases.get(vehicle_id, {})
    if phase_info.get("phase") in REFRESHING_PHASES and not _is_phase_stale(phase_info):
        return {"vehicle_id": vehicle_id, "status": "already_running", "phase": phase_info["phase"]}

    # P1-2：写 CollectionStatus（与采集同构），避免 DB-first 短路
    cs = (await session.execute(
        select(CollectionStatus).where(
            CollectionStatus.vehicle_id == vehicle_id,
            CollectionStatus.source == "all",
        )
    )).scalar_one_or_none()
    if cs:
        cs.is_running = True
        cs.lock_acquired_at = datetime.now()
    else:
        cs = CollectionStatus(vehicle_id=vehicle_id, source="all", mode="initial",
                              is_running=True, lock_acquired_at=datetime.now())
        session.add(cs)
    await session.commit()

    pipeline_phases[vehicle_id] = {"phase": "refreshing", "posts_refreshed": 0, "error": None, "_updated_at": datetime.now()}
    # P1-3：重置 pipeline_progress
    pipeline_progress[vehicle_id] = PipelineProgress()
    pipeline_progress[vehicle_id].overall_phase = "refreshing"
    pipeline_progress[vehicle_id].current_step = "刷新互动数"

    # P1-C：复用 _running_tasks 单字典
    old = _running_tasks.get(vehicle_id)
    if old and not old.done():
        old.cancel()
    task = asyncio.create_task(_run_refresh_pipeline(vehicle_id))
    _running_tasks[vehicle_id] = task
    task.add_done_callback(lambda t: _running_tasks.pop(vehicle_id, None))
    return {"vehicle_id": vehicle_id, "status": "started", "phase": "refreshing"}


async def _run_refresh_pipeline(vehicle_id: str):
    """异步：互动刷新 + 热度重算。不调 LLM。

    P1-2：成功写 cs.status='completed'，失败写 cs.status='error'+error_message（避免 DB-first 短路掩盖错误）。
    P1-2：finally 复位 is_running=False（与 _run_full_pipeline 同款）。
    P2-1：不进 _PIPELINE_SEM（轻量，不搜新帖）。
    """
    from scripts.refresh_engagement import refresh_vehicle_engagement  # noqa: inline-import
    _sf = async_session
    try:
        async with _sf() as session:
            n = await refresh_vehicle_engagement(session, vehicle_id)
            pipeline_phases[vehicle_id] = {"phase": "calculating", "posts_refreshed": n, "_updated_at": datetime.now()}
            pipeline_progress[vehicle_id].overall_phase = "calculating"
            pipeline_progress[vehicle_id].current_step = "重算热度"
            calc = HeatMetricCalculator(session)
            end = date.today()
            start = end - timedelta(days=90)
            await calc.calculate_range(vehicle_id, start, end)
            pipeline_phases[vehicle_id] = {"phase": "completed", "posts_refreshed": n, "_updated_at": datetime.now()}
            pipeline_progress[vehicle_id].overall_phase = "completed"
            # P1-2 v7：成功时同步写 CollectionStatus.status，避免 DB-first 短路掩盖
            # 方案 C：写 last_refreshed_at（展示字段），不写 last_collected_at（水位线，防 P0-1 漏采）
            await session.execute(
                update(CollectionStatus).where(
                    CollectionStatus.vehicle_id == vehicle_id,
                    CollectionStatus.source == "all",
                ).values(status="completed", error_message=None, last_refreshed_at=datetime.now())
            )
            await session.commit()
    except Exception as e:
        pipeline_phases[vehicle_id] = {"phase": "error", "error": str(e), "_updated_at": datetime.now()}
        pipeline_progress[vehicle_id].overall_phase = "error"
        # P1-2 v7：失败时同步写 CollectionStatus.status='error'（独立 session）
        try:
            async with _sf() as err_s:
                await err_s.execute(
                    update(CollectionStatus).where(
                        CollectionStatus.vehicle_id == vehicle_id,
                        CollectionStatus.source == "all",
                    ).values(status="error", error_message=str(e)[:200])
                )
                await err_s.commit()
        except Exception:
            pass
    finally:
        # P1-2：finally 复位 is_running=False（与 _run_full_pipeline 同款，CancelledError 也释放）
        try:
            async with _sf() as rel:
                await rel.execute(
                    update(CollectionStatus).where(
                        CollectionStatus.vehicle_id == vehicle_id,
                        CollectionStatus.source == "all",
                    ).values(is_running=False)
                )
                await rel.commit()
        except Exception:
            pass


@router.get("/{vehicle_id}/progress")
async def get_collection_progress(vehicle_id: str):
    """Per-platform collection progress (new API)."""
    progress = pipeline_progress.get(vehicle_id)
    if not progress:
        return {"vehicle_id": vehicle_id, "overall_phase": "idle", "current_step": "", "platforms": {}}
    return {"vehicle_id": vehicle_id, **progress.to_dict()}


@router.get("/{vehicle_id}/pipeline-status")
async def get_pipeline_status(vehicle_id: str, session: AsyncSession = Depends(get_session)):
    """DB 优先（真相源）→ 内存 dict 热缓存（带 TTL）→ fallback idle。

    DB collection_status.status='completed' 且 is_running=False 直接返回，
    不查内存（防 zombie 内存 dict 掩盖 DB 真相）。
    """
    # 1. 查 DB（真相源）
    status = (await session.execute(
        select(CollectionStatus).where(
            CollectionStatus.vehicle_id == vehicle_id,
            CollectionStatus.source == "all",
        )
    )).scalar_one_or_none()

    analyzed = (await session.execute(
        select(func.count(AnalyzedPost.id)).where(AnalyzedPost.vehicle_id == vehicle_id)
    )).scalar() or 0

    # 2. DB completed + 不在运行 → 直接返回（即使内存有 zombie calculating）
    if status and status.status == "completed" and not status.is_running:
        return {
            "vehicle_id": vehicle_id,
            "phase": "completed",
            "posts_collected": status.posts_collected or 0,
            "analyzed": analyzed,
            "error": status.error_message,
        }

    # 3. DB 非 completed → 看内存 dict（热缓存，带 TTL）
    phase_info = pipeline_phases.get(vehicle_id)
    if phase_info and not _is_phase_stale(phase_info):
        return {"vehicle_id": vehicle_id, **phase_info}

    # 4. 内存无或 stale → fallback DB status
    if status:
        return {
            "vehicle_id": vehicle_id,
            "phase": status.status or "idle",
            "posts_collected": status.posts_collected or 0,
            "analyzed": analyzed,
            "error": status.error_message,
        }
    return {"vehicle_id": vehicle_id, "phase": "idle", "posts_collected": 0, "analyzed": 0, "error": None}


@router.get("/{vehicle_id}/collection-status")
async def get_collection_status(vehicle_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(CollectionStatus).where(CollectionStatus.vehicle_id == vehicle_id)
    )
    statuses = result.scalars().all()
    return [
        {
            "id": s.id, "source": s.source, "mode": s.mode,
            "last_collected_at": s.last_collected_at.isoformat() if s.last_collected_at else None,
            "last_refreshed_at": s.last_refreshed_at.isoformat() if s.last_refreshed_at else None,
            "posts_collected": s.posts_collected, "status": s.status,
            "error_message": s.error_message,
        }
        for s in statuses
    ]
