"""口碑工具：封装已有采集、分析、搜索能力"""
import asyncio
import json
import logging
import time

from sqlalchemy import or_, and_

logger = logging.getLogger(__name__)

_background_tasks: dict[str, asyncio.Task] = {}
_task_status: dict[str, dict] = {}
_MAX_COMPLETED_STATUS = 50

COLLECT_TIMEOUT = 600
TAG_EXTRACT_TIMEOUT = 900
MAX_RESTART_ATTEMPTS = 2  # 心跳超时后的最大自动重启次数

# 标签覆盖率阈值（工具守卫与看板披露共用口径，单一来源，勿在别处另抄数值）：
COVERAGE_OK = 0.8    # ≥ 此值：结论可信
COVERAGE_MIN = 0.05  # < 此值：视为"标签未提取"，不产出标签聚合

_series_name_cache: dict[str, str] = {}
_MAX_CACHE_SIZE = 500

_TASK_STATUS_FILE = "data/task_status.json"
_task_status_loaded = False


def _ensure_task_status_loaded():
    """延迟加载：首次访问任务状态时才读磁盘"""
    global _task_status_loaded
    if _task_status_loaded:
        return
    _task_status_loaded = True
    _load_task_status_from_disk()


def _load_task_status_from_disk():
    """从磁盘加载已完成的任务状态"""
    global _task_status
    try:
        from pathlib import Path
        p = Path(_TASK_STATUS_FILE)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            for k, v in data.items():
                if v.get("status") in ("completed", "failed"):
                    _task_status[k] = v
    except Exception as e:
        logger.warning(f"加载任务状态失败: {e}")


def _save_task_status_to_disk():
    """将任务状态持久化到磁盘"""
    try:
        from pathlib import Path
        p = Path(_TASK_STATUS_FILE)
        p.parent.mkdir(parents=True, exist_ok=True)
        finished = {k: v for k, v in _task_status.items()
                    if v.get("status") in ("completed", "failed")}
        p.write_text(json.dumps(finished, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"保存任务状态失败: {e}")


def _update_tag_progress(series_id: str, processed: int, total: int, skipped: int) -> None:
    """写 tag_progress + last_heartbeat（M1 核心：让 progress endpoint 能检测 task 活/死）

    Args:
        series_id: 任务标识（model_id）
        processed: 已处理的 review 数
        total: 总数
        skipped: 跳过的数（best/worst text 缺失等）
    """
    if series_id in _task_status:
        _task_status[series_id]["last_heartbeat"] = time.time()
        _task_status[series_id]["tag_progress"] = {
            "processed": processed,
            "total": total,
            "skipped": skipped,
        }


def _maybe_restart_stale_task(model_id: str, cov: dict | None = None) -> dict | None:
    """M2 stale 自愈统一逻辑：若 task 心跳超时且未达 MAX_RESTART_ATTEMPTS 上限，自动重启。

    Args:
        cov: 调用方已算好的 _tag_coverage_for_series 结果（复用省重复查询），None 则现算。

    Returns:
        None — 已自动重启或不需要重启（调用方继续走正常分支）
        dict — {status: "tagging_failed", ...} 已失败（调用方直接 return 这个信封）
        dict — {status: "tagging_in_progress", ...} 重启中（调用方直接 return 这个信封）
    """
    from src.tools.review_status import derive_status
    _ensure_task_status_loaded()
    bg_now = _task_status.get(model_id)
    if cov is None:
        cov = _tag_coverage_for_series(model_id)
    derived = derive_status(bg_now, cov["taggable"], cov["tagged"])
    current_stage = derived["stage"]

    # 已确认失败 → 返回失败信封
    if current_stage == "tagging_failed":
        return {
            "model_id": model_id,
            "status": "tagging_failed",
            "stop_answering": True,
            "note": (bg_now or {}).get("error", "标签提取失败，请稍后重试"),
            "last_error": (bg_now or {}).get("error"),
        }

    # 心跳超时但还在重试预算内 → 重启
    attempts = (bg_now or {}).get("restart_attempts", 0)
    if current_stage == "tagging" and not derived["task_alive"] and attempts < MAX_RESTART_ATTEMPTS:
        _task_status[model_id] = {
            "status": "extracting_tags",
            "started_at": time.time(),
            "last_heartbeat": time.time(),
            "restart_attempts": attempts + 1,
        }
        task = asyncio.create_task(_background_tag_only(model_id))
        _background_tasks[model_id] = task
        logger.warning(f"检测到 stale task，自动重启 ({attempts + 1}/{MAX_RESTART_ATTEMPTS}): {model_id}")
        return {
            "model_id": model_id,
            "status": "tagging_in_progress",
            "stop_answering": True,
            "note": f"后台任务心跳超时，已自动重启 ({attempts + 1}/{MAX_RESTART_ATTEMPTS})，请稍候。",
            "coverage": derived["coverage"],
            "stage": "tagging",
        }

    # 心跳超时且重试预算耗尽
    if current_stage == "tagging" and not derived["task_alive"] and attempts >= MAX_RESTART_ATTEMPTS:
        return {
            "model_id": model_id,
            "status": "tagging_failed",
            "stop_answering": True,
            "note": f"后台任务重启 {attempts} 次后仍失败。请稍后重试。",
            "last_error": "max restart attempts hit",
        }

    return None  # 正常情况，调用方继续


def _tag_coverage_for_series(series_id: str) -> dict:
    """统一标签覆盖率口径：tagged / taggable（有文本可提取的口碑为分母）。

    所有需要覆盖率/进度的地方必须用本函数，不得各自内联实现。

    Returns:
        {total: 口碑总数（含无文本）, taggable: 有文本可提取数,
         tagged: 有至少一个标签的口碑数（distinct review_id）,
         coverage: tagged/taggable 保留 4 位小数，taggable=0 时为 0.0}
    """
    from src.storage.db import session_scope
    from src.models.orm import OwnerReview, ReviewTag
    with session_scope() as s:
        total = s.query(OwnerReview).filter(OwnerReview.model_id == series_id).count()
        if total == 0:
            # 空车型短路：total=0 ⇒ taggable/tagged 必为 0，省两次 COUNT（fetch_reviews 新车型首查热路径）
            taggable = tagged = 0
        else:
            taggable = s.query(OwnerReview).filter(
                OwnerReview.model_id == series_id, _has_text_filter(OwnerReview)
            ).count()
            # 2026-10-18 口径修正：分子取"有标签且有文本"交集（join 限定），
            # 防止老数据"只有全文无短文本但已被打标"的口碑把分子撑过分母（覆盖率>100%）
            tagged = s.query(ReviewTag.review_id).join(
                OwnerReview, OwnerReview.review_id == ReviewTag.review_id
            ).filter(
                OwnerReview.model_id == series_id, _has_text_filter(OwnerReview)
            ).distinct().count()
    coverage = (tagged / taggable) if taggable > 0 else 0.0
    return {"total": total, "taggable": taggable, "tagged": tagged,
            "coverage": round(coverage, 4)}


def _has_text_filter(model_cls):
    """构建"有文本口碑"的SQLAlchemy过滤条件，使用 or_() 避免位运算bug

    2026-10-18 口径修正：补入 best/worst_full_text——老数据口碑常只有详情页全文
    而无短文本，此前分母漏计它们导致 标签数(分子) > 有文本数(分母) → 覆盖率 >100%。
    """
    return or_(
        and_(model_cls.best_review_text != None, model_cls.best_review_text != ""),
        and_(model_cls.worst_review_text != None, model_cls.worst_review_text != ""),
        and_(model_cls.best_full_text != None, model_cls.best_full_text != ""),
        and_(model_cls.worst_full_text != None, model_cls.worst_full_text != ""),
    )


# 在售版本spec_id缓存（避免每次分析都重新拉取汽车之家API）
_onsell_spec_cache: dict[str, tuple[float, set]] = {}
_ONSELL_CACHE_TTL = 600  # 10分钟缓存


async def _get_onsell_spec_ids(model_id: str) -> set[str]:
    """获取车系下所有在售版本的spec_id集合（带缓存）

    用于 onsell_only 筛选：只统计在售车口碑，排除已停售的老款。
    """
    cached = _onsell_spec_cache.get(model_id)
    if cached and (time.time() - cached[0]) < _ONSELL_CACHE_TTL:
        return cached[1]

    try:
        from src.api.autohome_api import get_autohome_api
        api = await get_autohome_api()
        specs = await api.get_series_specs(model_id)
        spec_ids = {str(s.get("spec_id", "")) for s in specs if s.get("spec_id")}
        _onsell_spec_cache[model_id] = (time.time(), spec_ids)
        return spec_ids
    except Exception as e:
        logger.warning(f"获取在售版本失败({model_id}): {e}")
        return set()


async def _get_series_display_name(series_id: str) -> str:
    """从车系索引获取车系名称（如'银河E5'），带缓存"""
    if series_id in _series_name_cache:
        return _series_name_cache[series_id]
    try:
        from src.api.autohome_api import get_autohome_api
        api = await get_autohome_api()
        index = await api.build_series_index()
        info = index.get(series_id)
        name = info.get("name", "") if info else ""
        _series_name_cache[series_id] = name
        if len(_series_name_cache) > _MAX_CACHE_SIZE:
            # 移除最早的一半缓存
            keys_to_remove = list(_series_name_cache.keys())[:_MAX_CACHE_SIZE // 2]
            for k in keys_to_remove:
                del _series_name_cache[k]
        return name
    except Exception as e:
        logger.warning(f"获取车系名称失败: {e}")
        return ""


def _fix_model_full_name(series_id: str, correct_name: str):
    """修复数据库中 model_full_name 缺少车系名的口碑和标签"""
    if not correct_name:
        return
    from src.storage.db import session_scope
    from src.models.orm import OwnerReview, ReviewTag

    with session_scope() as session:
        bad_reviews = session.query(OwnerReview).filter(
            OwnerReview.model_id == series_id,
            ~OwnerReview.model_full_name.startswith(correct_name),
        ).all()
        if bad_reviews:
            for r in bad_reviews:
                old_name = r.model_full_name
                if correct_name not in old_name:
                    r.model_full_name = f"{correct_name} {old_name}".strip()
            session.flush()
            logger.info(f"修复 {len(bad_reviews)} 条口碑的 model_full_name")

        bad_tags = session.query(ReviewTag).filter(
            ReviewTag.model_id == series_id,
            ~ReviewTag.model_full_name.startswith(correct_name),
        ).all()
        if bad_tags:
            for t in bad_tags:
                old_name = t.model_full_name
                if correct_name not in old_name:
                    t.model_full_name = f"{correct_name} {old_name}".strip()
            session.flush()
            logger.info(f"修复 {len(bad_tags)} 条标签的 model_full_name")


def _is_task_stale(status_dict: dict | None) -> bool:
    """检查任务是否超时（采集超过10分钟或标签提取超过15分钟）"""
    if not status_dict:
        return False
    started = status_dict.get("started_at", 0)
    if not started:
        return False
    elapsed = time.time() - started
    current_status = status_dict.get("status", "")
    if current_status == "collecting" and elapsed > COLLECT_TIMEOUT:
        return True
    if current_status == "extracting_tags" and elapsed > TAG_EXTRACT_TIMEOUT:
        return True
    return False


async def _check_total_reviews(series_id: str) -> int | None:
    """通过口碑 API 查询该车型的总口碑数，返回 rowcount 或 None"""
    try:
        from src.api.autohome_api import get_autohome_api

        api = await get_autohome_api()
        result = await api.fetch_koubei_page(series_id, page_index=1, page_size=1)
        if not result:
            return None
        rowcount = result.get("rowcount", 0)
        return rowcount if rowcount > 0 else None
    except Exception as e:
        logger.warning(f"查询总口碑数失败: {e}")
        return None


async def _background_collect(series_id: str, max_pages: int | None = None):
    """后台采集口碑并提取标签，分两阶段更新任务状态

    阶段1: 采集口碑数据（不调用LLM），完成后状态变为 extracting_tags
    阶段2: LLM 增量提取标签，完成后状态变为 completed
    """
    _ensure_task_status_loaded()

    # 注意：调用方模式是 create_task() 后立即 _background_tasks[sid]=task，
    # 因此本协程真正执行时 _background_tasks[sid] 已指向自己。
    # 必须用 current_task() 排除自身，否则防重复检查永远命中自己 → 函数体从不执行。
    _current = asyncio.current_task()
    existing_task = _background_tasks.get(series_id)
    if existing_task is not None and existing_task is not _current and not existing_task.done():
        logger.warning(f"后台任务已在运行: {series_id}, 跳过重复启动")
        return

    _task_status[series_id] = {
        "status": "collecting",
        "started_at": time.time(),
        "last_heartbeat": time.time(),
    }
    try:
        from src.scraper.collector import ReviewCollector

        collector = ReviewCollector()
        saved = await collector.collect(series_id, max_pages, use_llm=False)

        _task_status[series_id] = {
            "status": "extracting_tags",
            "saved": saved,
            "started_at": time.time(),
            "collect_completed_at": time.time(),
        }
        logger.info(f"后台采集完成: {series_id}, 保存 {saved} 条，开始 LLM 标签提取")

        def on_tag_progress(processed, total, skipped):
            _update_tag_progress(series_id, processed, total, skipped)

        llm_saved = await collector._llm_extract_all_tags(
            _get_all_reviews_for_model(series_id), series_id,
            progress_callback=on_tag_progress,
        )

        _task_status[series_id] = {
            "status": "completed",
            "saved": saved,
            "llm_saved": llm_saved,
            "completed_at": time.time(),
        }
        logger.info(f"后台任务全部完成: {series_id}, 采集 {saved} 条, LLM 标签 {llm_saved} 条")
    except Exception as e:
        _task_status[series_id] = {"status": "failed", "error": str(e)}
        logger.error(f"后台采集失败: {series_id}, {e}")
    finally:
        _background_tasks.pop(series_id, None)
        _cleanup_old_status()


def _get_all_reviews_for_model(model_id: str) -> list[dict]:
    """从数据库获取某车型所有口碑，供 LLM 提取使用。
    仅查询必要字段，避免全量加载大文本字段到内存。
    """
    from src.storage.db import session_scope
    from src.models.orm import OwnerReview

    with session_scope() as session:
        rows = session.query(
            OwnerReview.review_id,
            OwnerReview.best_review_text,
            OwnerReview.worst_review_text,
            OwnerReview.owner_id,
            OwnerReview.model_full_name,
        ).filter(
            OwnerReview.model_id == model_id, _has_text_filter(OwnerReview)
        ).all()
        result = []
        for r in rows:
            best = r.best_review_text or ""
            worst = r.worst_review_text or ""
            has_text = bool(best.strip() or worst.strip())
            result.append({
                "review_id": r.review_id,
                "best_review_text": best,
                "worst_review_text": worst,
                "owner_id": r.owner_id or "",
                "model_full_name": r.model_full_name or "",
                "_has_text": has_text,
            })
    return result


async def _background_tag_only(series_id: str):
    """仅对已有口碑执行 LLM 标签提取（不重新采集）"""
    _ensure_task_status_loaded()

    _current = asyncio.current_task()
    existing_task = _background_tasks.get(series_id)
    if existing_task is not None and existing_task is not _current and not existing_task.done():
        logger.warning(f"后台标签提取已在运行: {series_id}, 跳过重复启动")
        return

    _task_status[series_id] = {
        "status": "extracting_tags",
        "saved": 0,
        "started_at": time.time(),
        "last_heartbeat": time.time(),
    }
    try:
        from src.scraper.collector import ReviewCollector

        reviews = _get_all_reviews_for_model(series_id)
        _task_status[series_id]["saved"] = len(reviews)

        collector = ReviewCollector()

        def on_tag_progress(processed, total, skipped):
            _update_tag_progress(series_id, processed, total, skipped)

        llm_saved = await asyncio.wait_for(
            collector._llm_extract_all_tags(
                reviews, series_id, progress_callback=on_tag_progress
            ),
            timeout=300
        )

        _task_status[series_id] = {
            "status": "completed",
            "saved": len(reviews),
            "llm_saved": llm_saved,
            "completed_at": time.time(),
        }
        logger.info(f"标签提取完成: {series_id}, 口碑 {len(reviews)} 条, LLM 标签 {llm_saved} 条")
    except asyncio.TimeoutError:
        logger.warning(f"标签提取超时: {series_id}")
        _task_status[series_id]["status"] = "partial"
        _task_status[series_id]["timed_out"] = True
    except Exception as e:
        _task_status[series_id] = {"status": "failed", "error": str(e)}
        logger.error(f"标签提取失败: {series_id}, {e}")
    finally:
        _background_tasks.pop(series_id, None)
        _cleanup_old_status()


def _cleanup_old_status():
    """Evict oldest completed/failed entries to prevent unbounded growth."""
    _ensure_task_status_loaded()
    finished_keys = [k for k, v in _task_status.items()
                     if v.get("status") in ("completed", "failed")]
    while len(finished_keys) > _MAX_COMPLETED_STATUS:
        old_key = finished_keys.pop(0)
        _task_status.pop(old_key, None)
    _save_task_status_to_disk()


async def _ensure_tags_ready(model_id: str, min_coverage: float = 0.5,
                             cov: dict | None = None) -> dict | None:
    """标签就绪守卫：供 regional/spec/year 等依赖 ReviewTag 的口碑工具入口调用。

    cov: 调用方已算好的 _tag_coverage_for_series 结果（复用省重复查询），None 则现算。

    标签覆盖率不足时触发后台采集/标签提取，并返回标准 stop_answering 信封
    （调用方必须直接 return，不得基于空标签继续分析）。
    标签就绪（或无口碑/无文本）时返回 None，调用方继续原分析逻辑。

    对齐 get_review_analysis 的真实性协议：杜绝"有口碑数、空分析 → LLM 编造"。
    """
    _ensure_task_status_loaded()
    from src.tools.review_status import derive_status

    if cov is None:
        cov = _tag_coverage_for_series(model_id)
    cnt, has_text_cnt, tagged_cnt = cov["total"], cov["taggable"], cov["tagged"]
    if cnt == 0:
        return None  # 无口碑，交由上层 cnt<5 / no_data 逻辑处理

    # 无可标签文本，或覆盖率达标 → 守卫放行
    if has_text_cnt == 0 or (tagged_cnt > 0 and cov["coverage"] >= min_coverage):
        return None

    # 覆盖率不足 → 触发后台 + 返回 stop_answering
    _ensure_task_status_loaded()
    bg_now = _task_status.get(model_id)
    derived = derive_status(bg_now, cov["taggable"], cov["tagged"])
    current_stage = derived["stage"]
    is_alive = derived["task_alive"]

    # M2 stale 自愈：统一走 _maybe_restart_stale_task（自动重启 / 失败信封）
    gate_result = _maybe_restart_stale_task(model_id, cov=cov)
    if gate_result is not None:
        return gate_result

    is_running = bool(current_stage in ("collecting", "tagging") and is_alive)
    if not is_running:
        total = await _check_total_reviews(model_id)
        if total and cnt < total:
            logger.info(f"[守卫] {model_id} 标签不足({tagged_cnt}/{has_text_cnt})，触发后台采集+标签")
            _task_status[model_id] = {"status": "started", "started_at": time.time()}
            task = asyncio.create_task(_background_collect(model_id))
            _background_tasks[model_id] = task
        else:
            logger.info(f"[守卫] {model_id} 标签覆盖率低({tagged_cnt}/{has_text_cnt})，触发后台标签补充")
            _task_status[model_id] = {"status": "extracting_tags", "saved": cnt, "started_at": time.time()}
            task = asyncio.create_task(_background_tag_only(model_id))
            _background_tasks[model_id] = task

    model_name = await _get_series_display_name(model_id) or model_id
    coverage_pct = f"{tagged_cnt / has_text_cnt:.0%}" if has_text_cnt else "0%"
    return {
        "model_id": model_id,
        "model_name": model_name,
        "review_count": cnt,
        "tagged_count": tagged_cnt,
        "insufficient_data": True,
        "status": "tagging_in_progress",
        "data_source": f"已采集{cnt}条，标签提取中（{tagged_cnt}/{has_text_cnt}，{coverage_pct}）",
        "top_pros": [],
        "top_cons": [],
        "spec_distribution": [],
        "interactive": {"type": "dimension_table", "dimensions": [], "pros": [], "cons": [], "wordcloud": []},
        "note": (
            f"已采集 {cnt} 条口碑，标签提取进行中（已完成 {tagged_cnt}/{has_text_cnt}）。"
            f"请告知用户：口碑正在后台分析中，预计1-3分钟后完成，请稍候再问。"
            f"不要基于空标签编造地域/版型/年款分析结论。"
        ),
        "stop_answering": True,
    }


async def fetch_reviews(series_id: str, max_pages: int | None = None) -> dict:
    """按需采集某车型口碑数据。数据充足时直接返回；否则启动后台采集+标签提取，
    立即返回，不阻塞等待。请稍后调用 get_review_analysis 获取分析结果。

    Args:
        series_id: 汽车之家车系 ID
        max_pages: 采集页数上限（None=全量）
    """
    _ensure_task_status_loaded()

    try:
        display_name = await _get_series_display_name(series_id)

        cov = _tag_coverage_for_series(series_id)
        if cov["total"] >= 5 and cov["coverage"] >= COVERAGE_OK:
            _fix_model_full_name(series_id, display_name)
            _task_status[series_id] = {
                "status": "completed",
                "saved": cov["total"],
                "llm_saved": cov["tagged"],
                "completed_at": time.time(),
            }
            return {
                "series_id": series_id,
                "status": "completed",
                "review_count": cov["total"],
                "message": "口碑数据充足，请调用 get_review_analysis 获取分析结果。",
            }

        # 检查是否已有后台任务在运行
        running_statuses = {"collecting", "extracting_tags", "started"}
        current_status = _task_status.get(series_id, {})
        if current_status.get("status") in running_statuses:
            return {
                "series_id": series_id,
                "status": current_status.get("status", "collecting"),
                "message": f"口碑采集已在后台进行中（{current_status.get('phase', '采集+标签提取')}），请稍后调用 get_review_analysis 获取分析结果。",
            }

        # 先标记状态，再启动后台采集（防止竞态）
        _fix_model_full_name(series_id, display_name)
        _task_status[series_id] = {"status": "started", "started_at": time.time()}
        task = asyncio.create_task(_background_collect(series_id, max_pages))
        _background_tasks[series_id] = task

        return {
            "series_id": series_id,
            "status": "started",
            "message": (
                "口碑采集任务已启动（后台执行），预计1-3分钟完成。"
                "请稍后调用 get_review_analysis 获取分析结果。"
            ),
        }
    except Exception as e:
        logger.error(f"fetch_reviews error: {e}")
        _task_status[series_id] = {"status": "failed", "error": str(e)}
        return {"error": str(e), "series_id": series_id}


def get_collection_progress(series_id: str) -> dict:
    """Return derived progress state for frontend polling.

    返回的字典同时包含：
    - 新字段（state machine）：stage / task_alive / coverage / eta_seconds / rate_per_sec / last_error
    - 向后兼容字段：status / phase / progress (0-100) / collected_count / total。
      已知消费者（chat.html 轮询）只读新字段；兼容字段保留供未知外部消费者。

    注：coverage/progress/total 分母为 taggable（有文本可提取口碑数，2026-09-15 行为变化）；reviews_total 为原始口碑总数。
    """
    from src.tools.review_status import derive_status
    _ensure_task_status_loaded()
    raw = _task_status.get(series_id)
    cov = _tag_coverage_for_series(series_id)
    derived = derive_status(raw, cov["taggable"], cov["tagged"])

    # 向后兼容字段（已知消费者 chat.html 只读新字段，保留供未知外部消费者）
    raw_status = (raw or {}).get("status", "unknown")
    phase_map = {
        "collecting": "采集口碑数据",
        "tagging": "提取标签中",
        "analysis_ready": "分析完成",
        "tagging_failed": "采集失败",
        "unknown": "排队中",
    }
    return {
        "series_id": series_id,
        # 新字段（state machine）
        "stage": derived["stage"],
        "task_alive": derived["task_alive"],
        "coverage": derived["coverage"],
        "eta_seconds": derived["eta_seconds"],
        "rate_per_sec": derived["rate_per_sec"],
        "last_error": derived["last_error"],
        "raw_status": derived["raw_status"],
        # 向后兼容字段（已知消费者 chat.html 只读新字段，保留供未知外部消费者）
        "status": raw_status,
        "phase": phase_map.get(derived["stage"], "处理中"),
        "progress": int(derived["coverage"] * 100),
        "collected_count": cov["tagged"],
        "total": cov["taggable"],
        # 新增字段（本变更新增）：原始口碑总数（含无文本，区别于 total=taggable）
        "reviews_total": cov["total"],
    }


# 业务维度固定顺序（按业务重要性排序：第一眼 → 长期持有）
_BUSINESS_DIM_ORDER = [
    "外观", "配置", "性价比", "操控", "空间",
    "续航", "动力", "舒适性", "内饰", "充电",
]

# L1 tag_category → 业务维度覆盖（仅列出非恒等映射）。
# 恒等映射（空间/外观/内饰/性价比/充电 == 业务维度）由 _map_to_business_dim 兜底自动处理。
_L1_OVERRIDES = {
    "舒适": "舒适性",
    "舒适性": "舒适性",
}

# L1 标签命中关键词 → 业务维度。未命中关键词时走 _L2_FALLBACK 兜底。
_L2_SPLIT_KEYWORDS = {
    "智能化": [
        ("配置", {"配置", "辅助驾驶", "L2", "屏幕", "中控"}),
    ],
    "驾驶感受": [
        ("动力", {"动力", "加速", "提速", "起步", "推背", "电机"}),
    ],
    "续航": [
        ("充电", {"充电", "快充", "慢充", "充电桩", "充电站"}),
    ],
}

# L2 未命中拆分关键词时的兜底（仅列出非恒等映射）。
_L2_FALLBACK = {
    "智能化": "配置",
    "驾驶感受": "操控",
}


def _map_to_business_dim(tag_category: str, tag_name: str) -> str:
    """L1 + L2 → 业务维度（10 选 1）。

    覆盖链：L1_OVERRIDES → L2_SPLIT_KEYWORDS → L2_FALLBACK → tag_category 自身。
    """
    if tag_category in _L1_OVERRIDES:
        return _L1_OVERRIDES[tag_category]
    if tag_category in _L2_SPLIT_KEYWORDS:
        for biz_dim, keywords in _L2_SPLIT_KEYWORDS[tag_category]:
            if any(kw in tag_name for kw in keywords):
                return biz_dim
        return _L2_FALLBACK.get(tag_category, tag_category)
    return tag_category or "其他"


def _build_dimension_table_v3(pros: list, cons: list,
                                model_name: str, review_count: int) -> list[dict]:
    """业务维度归一化版：L1→业务维度映射 + L2 二次拆分 + 唯一口碑计数

    Args:
        pros: list of (tag_category, tag_name, cnt, uniq_reviews)
        cons: 同 pros，con sentiment
        model_name: 车型名称（仅日志用）
        review_count: 总口碑数（仅日志用）

    Returns:
        业务维度评价表，按 _BUSINESS_DIM_ORDER 排序，仅返回有数据的维度
    """
    logger.debug("_build_dimension_table_v3: model=%s, reviews=%d", model_name, review_count)
    dim_pro: dict[str, list[dict]] = {}
    dim_con: dict[str, list[dict]] = {}

    for row in pros:
        cat, tag, cnt, uniq = row[0], row[1], row[2], row[3]
        biz_dim = _map_to_business_dim(cat or "", tag)
        dim_pro.setdefault(biz_dim, []).append({
            "tag": tag, "count": cnt, "uniq": uniq if uniq is not None else cnt
        })

    for row in cons:
        cat, tag, cnt, uniq = row[0], row[1], row[2], row[3]
        biz_dim = _map_to_business_dim(cat or "", tag)
        dim_con.setdefault(biz_dim, []).append({
            "tag": tag, "count": cnt, "uniq": uniq if uniq is not None else cnt
        })

    dimensions = []
    for dim_name in _BUSINESS_DIM_ORDER:
        pro_items = dim_pro.get(dim_name, [])
        con_items = dim_con.get(dim_name, [])
        if not pro_items and not con_items:
            continue

        pro_total = sum(p["uniq"] for p in pro_items)
        con_total = sum(c["uniq"] for c in con_items)
        net = pro_total - con_total

        top_pro_tags = [p["tag"] for p in sorted(
            pro_items, key=lambda x: x["uniq"], reverse=True
        )[:3]]
        top_con_tags = [c["tag"] for c in sorted(
            con_items, key=lambda x: x["uniq"], reverse=True
        )[:3]]

        if net > 5:
            verdict = "优势突出"
        elif net > 0:
            verdict = "整体偏好"
        elif net == 0:
            verdict = "褒贬不一"
        elif net > -5:
            verdict = "略有不足"
        else:
            verdict = "明显短板"

        dimensions.append({
            "dimension": dim_name,
            "pro_count": pro_total,
            "con_count": con_total,
            "net_score": net,
            "top_pro_tags": top_pro_tags,
            "top_con_tags": top_con_tags,
            "verdict": verdict,
        })

    return dimensions


def _build_tag_hierarchy(tags: list) -> list[dict]:
    """Build L1→L2 hierarchy from grouped tag data.
    tags: [(category, tag_name, count, uniq, avg_conf), ...]
    """
    cat_map: dict[str, list] = {}
    for row in tags:
        cat = row[0] or "其他"
        tag = row[1]
        count = row[2]
        conf = row[4] if len(row) > 4 else 0.8
        cat_map.setdefault(cat, []).append({"tag": tag, "count": count, "confidence": round(conf or 0, 3)})

    result = []
    for cat, items in cat_map.items():
        items.sort(key=lambda x: x["count"], reverse=True)
        result.append({"category": cat, "tags": items})
    result.sort(key=lambda x: sum(t["count"] for t in x["tags"]), reverse=True)
    return result


async def get_review_analysis(model_id: str, top_n: int = 10,
                              spec_name: str = "",
                              onsell_only: bool = False,
                              skip_background: bool = False) -> dict:
    """获取车型口碑分析结果：买点/槽点标签排行、各维度评价、版本分布。

    如果口碑数据不足会返回 insufficient_data=true，建议先调用 fetch_reviews 采集。
    支持按具体版本筛选口碑，支持只看在售车口碑。

    Args:
        model_id: 车系 ID（series_id）
        top_n: 返回的标签数量
        spec_name: 按版本名称筛选（如 "510KM 旗舰型"），为空则返回全部
        onsell_only: True时只统计在售车口碑（排除已停售的老款），默认False返回全部
        skip_background: 为True时不触发后台采集/标签提取（用于score_models等批量调用场景）

    Returns:
        top_pros: 买点标签列表 [{tag, count, avg_confidence}]
        top_cons: 槽点标签列表
        review_count: 口碑总数
        spec_distribution: 按版本的口碑分布
        interactive: 维度评价表、词云数据
    """
    _ensure_task_status_loaded()

    try:
        # M2 + M3: stale 自愈重启 + 部分结果返回
        # 与 _ensure_tags_ready 的 M2 守卫对齐：stale task 不应该让 get_review_analysis 沉默返回空分析，
        # 部分覆盖（>=5%）也不应该被拒答（已能产出可信的维度表）。
        cov = _tag_coverage_for_series(model_id)
        reviews_total = cov["total"]
        reviews_tagged = cov["tagged"]
        taggable_total = cov["taggable"]
        coverage = cov["coverage"]

        # M2 stale 自愈：统一走 _maybe_restart_stale_task（自动重启 / 失败信封）
        gate_result = _maybe_restart_stale_task(model_id, cov=cov)
        if gate_result is not None:
            return gate_result

        # 数据门守卫：有可分析口碑但标签覆盖率 < 5% → 复用 _ensure_tags_ready
        # 触发标签提取 + 返回 stop_answering 信封，杜绝"有口碑数、空分析 → LLM 编造"。
        # min_coverage=0.05 与下方 M3 partial 下界对齐：< 5% 由本守卫拦截，[5%,100%) 放行给 partial。
        # 键控 DB 实际标签覆盖率（跨进程共享），不依赖不可靠的 _task_status。
        gate = await _ensure_tags_ready(model_id, min_coverage=COVERAGE_MIN, cov=cov)
        if gate is not None:
            return gate

        # M3: 部分结果（coverage >= 5% 且 < 100%）—— 不要因未满覆盖率就拒答
        # 复用 _get_partial_analysis 构造维度表，再覆盖 is_partial + coverage 字段
        # 注意：coverage 分母用 taggable_total（可被 LLM 标签提取的口碑数），
        # 而不是 reviews_total（含无 text 的不可提取口碑），避免覆盖率永远到不了 100% 误导 LLM。
        if COVERAGE_MIN <= coverage < 1.0:
            partial = await _get_partial_analysis(model_id, top_n)
            partial["model_id"] = model_id
            partial["is_partial"] = True
            partial["coverage"] = round(coverage, 4)
            partial["reviews_total"] = reviews_total
            partial["reviews_tagged"] = reviews_tagged
            partial["taggable_total"] = taggable_total
            partial["note"] = (
                f"当前分析基于 {reviews_tagged}/{taggable_total} 条可分析口碑 "
                f"({coverage * 100:.1f}%)，后台继续提取剩余标签，"
                f"后续可再次调用以获得更完整结果。"
            )
            return partial

        from src.storage.db import session_scope
        from src.models.orm import OwnerReview, ReviewTag
        from sqlalchemy import func, distinct

        bg = _task_status.get(model_id)
        if _is_task_stale(bg):
            logger.warning(f"get_review_analysis: 任务超时，清除状态: {model_id}")
            _task_status.pop(model_id, None)
            _background_tasks.pop(model_id, None)
            bg = None

        if bg and bg.get("status") in ("collecting", "extracting_tags"):
            partial = await _get_partial_analysis(model_id, top_n)
            partial["model_id"] = model_id
            has_data = partial.get("review_count", 0) > 0
            if has_data:
                partial["data_source"] = (
                    f"口碑正在采集中（已完成{partial['review_count']}条）"
                    if bg.get("status") == "collecting"
                    else f"口碑已采集{bg.get('saved', 0)}条，标签提取中"
                )
                partial["message"] = (
                    "后台采集仍在进行中，以上为已采集数据的初步分析，"
                    "采集完成后可再次调用 get_review_analysis 获取完整结果。"
                    "建议先基于已有数据回复用户。"
                )
            else:
                partial["data_source"] = "口碑正在采集中"
                partial["message"] = (
                    "该车型口碑正在后台采集中，预计3-10分钟完成。"
                    "建议先回复用户告知预计等待时间。"
                )
            return partial

        with session_scope() as session:
            cnt = session.query(OwnerReview).filter(OwnerReview.model_id == model_id).count()

        if cnt < 5:
            bg_now = _task_status.get(model_id)
            if bg_now and bg_now.get("status") in ("collecting", "extracting_tags", "started"):
                partial = await _get_partial_analysis(model_id, top_n)
                partial["model_id"] = model_id
                has_data = partial.get("review_count", 0) > 0
                if has_data:
                    partial["data_source"] = (
                        f"口碑正在采集中（已完成{partial['review_count']}条）"
                        if bg_now.get("status") == "collecting"
                        else f"口碑已采集{bg_now.get('saved', 0)}条，标签提取中"
                    )
                    partial["message"] = (
                        "后台采集仍在进行中，以上为已采集数据的初步分析，"
                        "采集完成后可再次调用 get_review_analysis 获取完整结果。"
                        "建议先基于已有数据回复用户。"
                    )
                else:
                    partial["data_source"] = "口碑正在采集中"
                    partial["message"] = (
                        "该车型口碑正在后台采集中，预计3-10分钟完成。"
                        "建议先回复用户告知预计等待时间。"
                    )
                return partial

            total = await _check_total_reviews(model_id)
            total_info = f"（API显示共约{total}条）" if total else ""
            model_name = await _get_series_display_name(model_id) or model_id

            # 兑现工具描述“数据不足会自动触发后台采集”。
            # 此前这里只返回提示让 LLM 去调 fetch_reviews，但 LLM 常不调、反而死循环重试
            # get_review_analysis（被 stop hint 截断），导致新车型口碑永远采不到。
            # 改为：除非确实无口碑，否则主动启动后台采集+标签提取。

            # 真正无口碑：库里 0 条 且 API 也确认无总量
            if cnt == 0 and not total:
                return {
                    "model_id": model_id,
                    "model_name": model_name,
                    "review_count": 0,
                    "insufficient_data": True,
                    "status": "no_data",
                    "data_source": "暂无口碑数据",
                    "top_pros": [],
                    "top_cons": [],
                    "spec_distribution": [],
                    "interactive": {"type": "dimension_table", "dimensions": [], "pros": [], "cons": [], "wordcloud": []},
                    "note": "该车型暂无口碑数据，汽车之家口碑库中尚未收录。",
                }

            # 否则自动启动后台采集+标签提取（_background_collect 内部 on_conflict 去重 + LLM 标签）
            logger.info(f"车型 {model_id} 口碑不足({cnt}条/预期{total})，自动触发后台采集+标签提取")
            _task_status[model_id] = {"status": "started", "started_at": time.time()}
            task = asyncio.create_task(_background_collect(model_id))
            _background_tasks[model_id] = task

            phase = "采集口碑数据" if (total and cnt < total) else "提取标签"
            return {
                "model_id": model_id,
                "model_name": model_name,
                "review_count": cnt,
                "total_expected": total,
                "insufficient_data": True,
                "status": "tagging_in_progress",
                "data_source": f"已采集{cnt}条，{phase}中" if cnt > 0 else "口碑采集中",
                "top_pros": [],
                "top_cons": [],
                "spec_distribution": [],
                "interactive": {"type": "dimension_table", "dimensions": [], "pros": [], "cons": [], "wordcloud": []},
                "note": (
                    f"该车型口碑数据不足，已自动启动后台{phase}（预计1-3分钟完成）。"
                    f"请告知用户：口碑正在分析中，预计1-3分钟后完成，请稍候再问。"
                    f"不要基于空数据编造分析结论。"
                ),
                "stop_answering": True,
            }

        with session_scope() as session:
            base_filter = OwnerReview.model_id == model_id
            is_filtered = False
            if spec_name:
                base_filter = base_filter & (OwnerReview.spec_name.contains(spec_name))
                is_filtered = True

            # 在售车筛选：只统计在售版本的口碑（排除已停售的老款）
            onsell_spec_ids = None
            if onsell_only:
                onsell_spec_ids = await _get_onsell_spec_ids(model_id)
                if onsell_spec_ids:
                    base_filter = base_filter & (OwnerReview.spec_id.in_(onsell_spec_ids))
                    is_filtered = True

            # 覆盖率口径统一：未筛选时三计数直接复用 cov（函数开头 _tag_coverage_for_series）；
            # 筛选域计数统一函数不覆盖，保留筛选查询。is_filtered 随 base_filter 构成维护
            # （新增筛选维度时在此置位），避免在消费点手写谓词镜像漂移。
            if is_filtered:
                cnt = session.query(OwnerReview).filter(base_filter).count()
                has_text_cnt = session.query(OwnerReview).filter(
                    base_filter, _has_text_filter(OwnerReview)
                ).count()
            else:
                cnt = cov["total"]
                has_text_cnt = cov["taggable"]

            tag_filter = ReviewTag.model_id == model_id
            if spec_name:
                matching_ids = {r[0] for r in session.query(OwnerReview.review_id).filter(
                    OwnerReview.model_id == model_id,
                    OwnerReview.spec_name.contains(spec_name)
                ).all()}
                tag_filter = ReviewTag.review_id.in_(matching_ids) if matching_ids else False

            pros = (
                session.query(
                    ReviewTag.tag_category, ReviewTag.tag_name,
                    func.count().label("cnt"),
                    func.count(distinct(ReviewTag.review_id)).label("uniq"),
                    func.avg(ReviewTag.confidence).label("avg_conf"))
                .filter(tag_filter, ReviewTag.sentiment == "pro")
                .group_by(ReviewTag.tag_category, ReviewTag.tag_name)
                .order_by(func.count().desc()).limit(top_n * 2).all()
            )
            cons = (
                session.query(
                    ReviewTag.tag_category, ReviewTag.tag_name,
                    func.count().label("cnt"),
                    func.count(distinct(ReviewTag.review_id)).label("uniq"),
                    func.avg(ReviewTag.confidence).label("avg_conf"))
                .filter(tag_filter, ReviewTag.sentiment == "con")
                .group_by(ReviewTag.tag_category, ReviewTag.tag_name)
                .order_by(func.count().desc()).limit(top_n * 2).all()
            )
            name_row = session.query(OwnerReview.model_full_name).filter(
                OwnerReview.model_id == model_id).first()

            if spec_name:
                tagged_cnt = session.query(ReviewTag.review_id).filter(
                    tag_filter
                ).distinct().count()
            else:
                # 与 _tag_coverage_for_series 的 tagged 同源（model_id 全域 distinct），复用 cov
                # 既有口径：onsell 筛选时 tagged 仍取全域（coverage 可能>1），修复属行为变化需另行声明。
                tagged_cnt = cov["tagged"]

        model_name = await _get_series_display_name(model_id)
        if not model_name:
            model_name = name_row[0] if name_row else model_id

        if cnt > 0 and not skip_background:
            coverage = tagged_cnt / has_text_cnt if has_text_cnt > 0 else 0
            need_llm = (not pros and not cons) or coverage < COVERAGE_OK

            if need_llm:
                bg_now = _task_status.get(model_id)
                is_running = bg_now and bg_now.get("status") in ("collecting", "extracting_tags", "started")
                if not is_running:
                    total = await _check_total_reviews(model_id)
                    if total and cnt < total:
                        logger.info(f"车型 {model_id} 口碑不完整({cnt}/{total})，触发增量采集+标签提取")
                        task = asyncio.create_task(_background_collect(model_id))
                        _background_tasks[model_id] = task
                        is_running = True  # 刚启动，标记为运行中
                    else:
                        untagged_cnt = has_text_cnt - tagged_cnt
                        if untagged_cnt > 10:
                            logger.info(f"车型 {model_id} 标签覆盖率低({coverage:.1%})，启动后台LLM标签补充")
                            task = asyncio.create_task(_background_tag_only(model_id))
                            _background_tasks[model_id] = task
                            is_running = True  # 刚启动，标记为运行中

                # 关键修复：标签还在提取中时，返回明确的"请等待"状态
                # 而不是用空标签继续生成回答（避免"还没分析就回答"的问题）
                if is_running and not pros and not cons:
                    bg_status = bg_now.get("status", "processing") if bg_now else "started"
                    phase_text = "采集口碑数据" if bg_status == "collecting" else "提取标签中"
                    return {
                        "model_id": model_id,
                        "model_name": model_name,
                        "review_count": cnt,
                        "total_expected": total if 'total' in locals() and total else None,
                        "insufficient_data": True,
                        "status": "tagging_in_progress",
                        "data_source": f"已采集{cnt}条，{phase_text}",
                        "top_pros": [],
                        "top_cons": [],
                        "spec_distribution": [],
                        "interactive": {"type": "dimension_table", "dimensions": [], "pros": [], "cons": [], "wordcloud": []},
                        "note": (
                            f"已采集 {cnt} 条口碑，{phase_text}（后台进行中）。"
                            f"标签提取完成后才能给出准确的买点/槽点分析。"
                            f"请告知用户：口碑正在分析中，预计1-3分钟后完成，请稍候再问。"
                            f"不要基于空数据编造分析结论。"
                        ),
                        "stop_answering": True,  # 明确告诉Agent：不要基于此回答
                    }

        # 构建维度口碑表数据（V3 业务维度版）
        dimension_table_data = _build_dimension_table_v3(pros, cons, model_name, cnt)

        # 按版本聚合口碑分布
        spec_distribution = _build_spec_distribution(model_id, cnt)

        # Build L1→L2 hierarchy for top pros/cons
        pro_hierarchy = _build_tag_hierarchy(pros[:top_n])
        con_hierarchy = _build_tag_hierarchy(cons[:top_n])

        # 计算在售/全部口碑数量（用于前端显示筛选信息）
        total_all_cnt = session.query(OwnerReview).filter(
            OwnerReview.model_id == model_id
        ).count()
        onsell_cnt = cnt if onsell_only else (
            len(onsell_spec_ids) if onsell_spec_ids is not None
            else None
        )
        # 如果当前是"全部"模式，额外算一下在售数量供前端显示
        if not onsell_only and onsell_spec_ids is None:
            try:
                onsell_ids = await _get_onsell_spec_ids(model_id)
                if onsell_ids:
                    onsell_cnt = session.query(OwnerReview).filter(
                        OwnerReview.model_id == model_id,
                        OwnerReview.spec_id.in_(onsell_ids)
                    ).count()
                else:
                    onsell_cnt = total_all_cnt  # 无法区分时，在售=全部
            except Exception:
                onsell_cnt = None

        data_source = f"汽车之家车主口碑（{cnt}条）" if cnt > 0 else "暂无口碑数据"
        if onsell_only and onsell_cnt is not None and total_all_cnt > cnt:
            data_source = f"汽车之家车主口碑（在售{cnt}条/全部{total_all_cnt}条）"

        return {
            "model_id": model_id,
            "model_name": model_name,
            "review_count": cnt,
            "total_review_count": total_all_cnt,  # 全部口碑（含停售）
            "onsell_review_count": onsell_cnt,    # 在售口碑
            "onsell_only": onsell_only,            # 当前筛选模式
            "insufficient_data": False,
            "data_source": data_source,
            "top_pros": [{"category": p[0], "tag": p[1], "count": p[2], "avg_confidence": round(p[4] or 0, 3)} for p in pros[:top_n]],
            "top_cons": [{"category": c[0], "tag": c[1], "count": c[2], "avg_confidence": round(c[4] or 0, 3)} for c in cons[:top_n]],
            "pro_hierarchy": pro_hierarchy,
            "con_hierarchy": con_hierarchy,
            "spec_distribution": spec_distribution,
            "interactive": {
                "type": "dimension_table",
                "model_name": model_name,
                "model_id": model_id,
                "review_count": cnt,
                "total_review_count": total_all_cnt,
                "onsell_review_count": onsell_cnt,
                "onsell_only": onsell_only,
                "dimensions": dimension_table_data,
                "pros": [{"category": p[0], "tag": p[1], "count": p[2]} for p in pros[:top_n]],
                "cons": [{"category": c[0], "tag": c[1], "count": c[2]} for c in cons[:top_n]],
                "wordcloud": (
                    [{"text": p[1], "weight": p[2], "sentiment": "pro", "category": p[0]} for p in pros[:top_n]] +
                    [{"text": c[1], "weight": c[2], "sentiment": "con", "category": c[0]} for c in cons[:top_n]]
                ),
                "data_source": data_source,
            },
        }
    except Exception as e:
        logger.error(f"get_review_analysis error: {e}")
        return {"error": str(e), "model_id": model_id}


async def search_reviews(model_id: str, keyword: str) -> dict:
    """在已采集口碑中搜索关键词，返回相关车主原文片段。

    Args:
        model_id: 车系 ID
        keyword: 搜索关键词
    """
    try:
        from src.storage.db import session_scope
        from src.models.orm import OwnerReview

        try:
            import jieba
            tokens = list(jieba.cut(keyword))
        except ImportError:
            tokens = [keyword]

        with session_scope() as session:
            reviews = session.query(OwnerReview).filter(
                OwnerReview.model_id == model_id,
                (OwnerReview.best_review_text.contains(keyword)) |
                (OwnerReview.worst_review_text.contains(keyword))
            ).limit(20).all()

            existing_ids = {r.review_id for r in reviews}

            if len(tokens) > 1:
                for token in tokens:
                    if len(token) < 2:
                        continue
                    extra = session.query(OwnerReview).filter(
                        OwnerReview.model_id == model_id,
                        ~OwnerReview.review_id.in_(existing_ids),
                        (OwnerReview.best_review_text.contains(token)) |
                        (OwnerReview.worst_review_text.contains(token))
                    ).limit(10).all()
                    for r in extra:
                        if r.review_id not in existing_ids:
                            existing_ids.add(r.review_id)
                            reviews.append(r)

            results = []
            seen = set()
            for r in reviews:
                if r.review_id in seen:
                    continue
                seen.add(r.review_id)
                snippet = ""
                for field in [r.best_review_text, r.worst_review_text]:
                    text = field or ""
                    for kw in [keyword] + [t for t in tokens if len(t) >= 2]:
                        if kw in text:
                            idx = text.index(kw)
                            start = max(0, idx - 20)
                            end = min(len(text), idx + len(kw) + 30)
                            snippet = "..." + text[start:end] + "..."
                            break
                    if snippet:
                        break

                results.append({
                    "owner_id": r.owner_id or "匿名车主",
                    "model_full_name": r.model_full_name,
                    "snippet": snippet or (r.best_review_text or r.worst_review_text)[:80] + "...",
                })

        return {"results": results[:30], "keyword": keyword, "model_id": model_id, "count": len(results[:30])}
    except Exception as e:
        logger.error(f"search_reviews error: {e}")
        return {"error": str(e), "keyword": keyword}


async def _get_partial_analysis(model_id: str, top_n: int = 10) -> dict:
    """Return whatever analysis is available from DB, even if incomplete."""
    try:
        from src.storage.db import session_scope
        from src.models.orm import OwnerReview, ReviewTag
        from sqlalchemy import func, distinct

        with session_scope() as session:
            cnt = session.query(OwnerReview).filter(
                OwnerReview.model_id == model_id).count()

            if cnt == 0:
                return {
                    "review_count": 0,
                    "insufficient_data": True,
                    "top_pros": [],
                    "top_cons": [],
                    "interactive": {"type": "dimension_table", "dimensions": [],
                                    "pros": [], "cons": [], "wordcloud": []},
                }

            pros = (
                session.query(
                    ReviewTag.tag_category, ReviewTag.tag_name,
                    func.count().label("cnt"),
                    func.count(distinct(ReviewTag.review_id)).label("uniq"),
                    func.avg(ReviewTag.confidence).label("avg_conf"))
                .filter(ReviewTag.model_id == model_id, ReviewTag.sentiment == "pro")
                .group_by(ReviewTag.tag_category, ReviewTag.tag_name)
                .order_by(func.count().desc()).limit(top_n * 2).all()
            )
            cons = (
                session.query(
                    ReviewTag.tag_category, ReviewTag.tag_name,
                    func.count().label("cnt"),
                    func.count(distinct(ReviewTag.review_id)).label("uniq"),
                    func.avg(ReviewTag.confidence).label("avg_conf"))
                .filter(ReviewTag.model_id == model_id, ReviewTag.sentiment == "con")
                .group_by(ReviewTag.tag_category, ReviewTag.tag_name)
                .order_by(func.count().desc()).limit(top_n * 2).all()
            )

        model_name = await _get_series_display_name(model_id) or model_id
        dimension_table_data = _build_dimension_table_v3(pros, cons, model_name, cnt)
        spec_distribution = _build_spec_distribution(model_id, cnt)

        return {
            "model_name": model_name,
            "review_count": cnt,
            "insufficient_data": False,
            "top_pros": [{"category": p[0], "tag": p[1], "count": p[2], "avg_confidence": round(p[4] or 0, 3)} for p in pros[:top_n]],
            "top_cons": [{"category": c[0], "tag": c[1], "count": c[2], "avg_confidence": round(c[4] or 0, 3)} for c in cons[:top_n]],
            "spec_distribution": spec_distribution,
            "interactive": {
                "type": "dimension_table",
                "model_name": model_name,
                "review_count": cnt,
                "dimensions": dimension_table_data,
                "pros": [{"category": p[0], "tag": p[1], "count": p[2]} for p in pros[:top_n]],
                "cons": [{"category": c[0], "tag": c[1], "count": c[2]} for c in cons[:top_n]],
                "wordcloud": (
                    [{"text": p[1], "weight": p[2], "sentiment": "pro", "category": p[0]} for p in pros[:top_n]] +
                    [{"text": c[1], "weight": c[2], "sentiment": "con", "category": c[0]} for c in cons[:top_n]]
                ),
            },
        }
    except Exception as e:
        logger.warning(f"获取部分分析数据失败: {e}")
        return {
            "review_count": 0,
            "insufficient_data": True,
            "top_pros": [],
            "top_cons": [],
            "interactive": {"type": "dimension_table", "dimensions": [],
                            "pros": [], "cons": [], "wordcloud": []},
        }


def _build_spec_distribution(model_id: str, total_count: int) -> list[dict]:
    """按版本聚合口碑数量分布"""
    try:
        from src.storage.db import session_scope
        from src.models.orm import OwnerReview
        from sqlalchemy import func

        with session_scope() as session:
            rows = (
                session.query(
                    OwnerReview.spec_name,
                    func.count().label("cnt"),
                )
                .filter(OwnerReview.model_id == model_id, _has_text_filter(OwnerReview))
                .group_by(OwnerReview.spec_name)
                .order_by(func.count().desc())
                .all()
            )

        result = []
        for spec_name, cnt in rows:
            name = spec_name or "未指定版本"
            result.append({
                "spec_name": name,
                "count": cnt,
                "percentage": round(cnt / total_count * 100, 1) if total_count > 0 else 0,
            })
        return result
    except Exception as e:
        logger.warning(f"构建版本分布失败: {e}")
        return []


async def get_dimension_reviews(model_id: str, dimension: str = "",
                                 sample_count: int = 10) -> dict:
    """获取某车型各维度的口碑详情原文。聚合 dimension_reviews 字段，按维度分组返回代表性评价。

    Args:
        model_id: 车系 ID
        dimension: 按维度筛选（如"空间"、"外观"、"舒适"），为空返回所有维度
        sample_count: 每个维度返回的样本数
    """
    try:
        from src.storage.db import session_scope
        from src.models.orm import OwnerReview
        import json

        with session_scope() as session:
            rows = session.query(OwnerReview.dimension_reviews, OwnerReview.review_id).filter(
                OwnerReview.model_id == model_id,
                OwnerReview.dimension_reviews != None,
            ).all()

        dim_texts: dict[str, list[str]] = {}
        for row in rows:
            dr = row[0]
            if not dr:
                continue
            if isinstance(dr, str):
                try:
                    dr = json.loads(dr)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not isinstance(dr, dict):
                continue
            for dim_name, text in dr.items():
                if not text or not text.strip():
                    continue
                if dimension and dimension not in dim_name:
                    continue
                dim_texts.setdefault(dim_name, []).append(text.strip())

        result = []
        for dim_name, texts in dim_texts.items():
            samples = texts[:sample_count]
            avg_len = sum(len(t) for t in texts) / len(texts) if texts else 0
            result.append({
                "dimension": dim_name,
                "count": len(texts),
                "avg_length": round(avg_len, 0),
                "samples": samples,
            })
        result.sort(key=lambda x: x["count"], reverse=True)

        return {
            "model_id": model_id,
            "dimensions": result,
            "total_dimensions": len(result),
        }
    except Exception as e:
        logger.error(f"get_dimension_reviews error: {e}")
        return {"error": str(e), "model_id": model_id}


async def get_energy_analysis(model_id: str) -> dict:
    """获取车型能耗分析：从口碑 exinfo 提取季节能耗、实测续航数据。

    仅对包含 exinfo 数据的口碑有效（需要重新采集才能获取）。
    返回季节电耗分布、续航统计等。

    Args:
        model_id: 车系 ID
    """
    try:
        from src.storage.db import session_scope
        from src.models.orm import OwnerReview
        import json
        import re

        with session_scope() as session:
            rows = session.query(OwnerReview.exinfo).filter(
                OwnerReview.model_id == model_id,
                OwnerReview.exinfo != None,
            ).all()

        if not rows:
            return {
                "model_id": model_id,
                "status": "no_data",
                "note": "暂无能耗数据（exinfo）。需要重新采集口碑数据以获取季节能耗信息。",
                "consumption_samples": [],
                "range_samples": [],
            }

        consumption_data = []
        range_data = []
        for row in rows:
            ex = row[0]
            if not ex:
                continue
            if isinstance(ex, str):
                try:
                    ex = json.loads(ex)
                except (json.JSONDecodeError, TypeError):
                    continue
            for key, value in ex.items():
                val_str = str(value)
                nums = re.findall(r'[\d.]+', val_str)
                if not nums:
                    continue
                if any(kw in key for kw in ['电耗', '能耗', '油耗', '百公里']):
                    consumption_data.append({
                        "label": key,
                        "value": val_str,
                        "number": float(nums[0]) if nums else None,
                    })
                elif any(kw in key for kw in ['续航', '里程']):
                    range_data.append({
                        "label": key,
                        "value": val_str,
                        "number": float(nums[0]) if nums else None,
                    })

        consumption_summary = {}
        if consumption_data:
            nums = [c["number"] for c in consumption_data if c["number"] is not None]
            if nums:
                consumption_summary = {
                    "avg": round(sum(nums) / len(nums), 1),
                    "min": min(nums),
                    "max": max(nums),
                    "sample_count": len(nums),
                }

        range_summary = {}
        if range_data:
            nums = [r["number"] for r in range_data if r["number"] is not None]
            if nums:
                range_summary = {
                    "avg": round(sum(nums) / len(nums), 0),
                    "min": min(nums),
                    "max": max(nums),
                    "sample_count": len(nums),
                }

        return {
            "model_id": model_id,
            "status": "available",
            "consumption_summary": consumption_summary,
            "consumption_samples": consumption_data[:20],
            "range_summary": range_summary,
            "range_samples": range_data[:20],
        }
    except Exception as e:
        logger.error(f"get_energy_analysis error: {e}")
        return {"error": str(e), "model_id": model_id}
