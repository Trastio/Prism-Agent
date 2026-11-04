import asyncio
import json
import logging
import uuid
from datetime import date, datetime, timedelta

from cachetools import TTLCache
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.pipeline_state import pipeline_phases, _is_phase_stale
from api.query_scopes import time_window_filter
from models.database import get_session, async_session
from models.schemas import AnalyzedPost, DefectTheme, HeatMetric, RawPost, Vehicle, LISTING_CALIBER
from pipeline.analysis.batch_runner import BatchAnalysisRunner
from pipeline.analysis.heat_calculator import HeatMetricCalculator
from pipeline.scheduler import CollectionScheduler
from utils.llm_client import LLMError, call_llm
from utils.llm_helpers import extract_json_array

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

log = logging.getLogger(__name__)


async def _run_analysis_pipeline(vehicle_id: str, _session_factory=None):
    _sf = _session_factory or async_session
    # _updated_at 必带（审计 P1-1，与 collection.py 同契约）：无时间戳则 30min stale 逃逸失效
    pipeline_phases[vehicle_id] = {"phase": "analyzing", "posts_collected": pipeline_phases.get(vehicle_id, {}).get("posts_collected", 0), "analyzed": 0, "error": None, "_updated_at": datetime.now()}

    async with _sf() as session:
        try:
            runner = BatchAnalysisRunner(session)
            result = await runner.run_for_vehicle(vehicle_id)
            analyzed = result.get("analyzed", 0)

            # 按需抓 Top N 评论 + 生成摘要（激活评论情感差异组件）
            # fetch_top_comments 必须先于 summaries，否则 comment_summary 全空
            comment_count = 0
            try:
                sched = CollectionScheduler(session)
                await sched.fetch_top_comments(vehicle_id)
                comment_count = await runner.run_comment_summaries(vehicle_id)
            except Exception as e:
                log.warning("Comment summary phase failed: %s", e)

            # Comment dimension analysis via local ABSA model
            try:
                cmt_analyzed = await runner.run_comment_analysis(vehicle_id)
                pipeline_phases[vehicle_id]["comments_analyzed"] = cmt_analyzed
            except Exception as e:
                log.warning("Comment ABSA phase failed: %s", e)

            pipeline_phases[vehicle_id] = {"phase": "calculating", "posts_collected": pipeline_phases[vehicle_id]["posts_collected"], "analyzed": analyzed, "error": None, "_updated_at": datetime.now()}

            calc = HeatMetricCalculator(session)
            end = date.today()
            start = end - timedelta(days=90)
            await calc.calculate_range(vehicle_id, start, end)

            # Event detection (keyword graph + Louvain) — separate social and news
            try:
                from pipeline.analysis.event_tracker import detect_events_for_vehicle  # noqa: inline-import
                ev_social = await detect_events_for_vehicle(vehicle_id, session, source="social")
                ev_news = await detect_events_for_vehicle(vehicle_id, session, source="news")
                pipeline_phases[vehicle_id]["events_social"] = len(ev_social) if ev_social else 0
                pipeline_phases[vehicle_id]["events_news"] = len(ev_news) if ev_news else 0
            except Exception as e:
                log.warning("Event detection failed: %s", e)

            # T5.6 管线收敛：/analysis/trigger 也产出缺陷簇（与 /collect 对齐）
            # 2026-10-20 闭环对齐（P0 修复）：30 天权威窗 + degraded 保旧——
            # 原此调用点未适配 (themes, degraded) 元组，把元组直接 json.dumps
            # 损坏 payload、LLM 失败照样空覆盖、窗口列写 date 对象且实际走
            # mine 默认 7 天窗（与权威口径三重漂移）
            try:
                from pipeline.analysis.defect_miner import mine_defect_themes  # noqa: inline-import
                d_end = date.today()
                d_start = d_end - timedelta(days=29)
                themes, degraded = await mine_defect_themes(
                    vehicle_id, session,
                    start=d_start.isoformat(), end=d_end.isoformat())
                if degraded:
                    log.warning("Defect mining degraded (LLM judge failed): "
                                "keep old payload for %s", vehicle_id)
                else:
                    await session.execute(
                        __import__("sqlalchemy").delete(DefectTheme).where(DefectTheme.vehicle_id == vehicle_id)
                    )
                    session.add(DefectTheme(
                        id=str(uuid.uuid4()), vehicle_id=vehicle_id,
                        window_start=d_start.isoformat(), window_end=d_end.isoformat(),
                        payload=json.dumps(themes),
                    ))
                    await session.commit()
                    pipeline_phases[vehicle_id]["defect_themes"] = len(themes)
            except Exception as e:
                log.warning("Defect mining failed: %s", e)

            pipeline_phases[vehicle_id] = {"phase": "completed", "posts_collected": pipeline_phases[vehicle_id]["posts_collected"], "analyzed": analyzed, "error": None, "_updated_at": datetime.now()}
        except Exception as e:
            pipeline_phases[vehicle_id] = {"phase": "error", "posts_collected": 0, "analyzed": 0, "error": str(e), "_updated_at": datetime.now()}


@router.post("/trigger/{vehicle_id}")
async def trigger_analysis(vehicle_id: str, session: AsyncSession = Depends(get_session)):
    vehicle = await session.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(404, detail="Vehicle not found")

    phase_info = pipeline_phases.get(vehicle_id, {})
    # 审计 P1-1：判定加 stale 逃逸（对齐 collection.py P1-3 模式）——zombie phase
    # 残留 30min 后不再永久 already_running
    if phase_info.get("phase") in ("collecting", "analyzing", "calculating") and not _is_phase_stale(phase_info):
        return {"vehicle_id": vehicle_id, "status": "already_running", "phase": phase_info["phase"]}

    asyncio.create_task(_run_analysis_pipeline(vehicle_id))
    return {"vehicle_id": vehicle_id, "status": "started", "phase": "analyzing"}


@router.get("/heat-metrics/{vehicle_id}")
async def get_heat_metrics(
    vehicle_id: str,
    start: str = Query(...), end: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    calc = HeatMetricCalculator(session)
    metrics = await calc.get_metrics(vehicle_id, date.fromisoformat(start), date.fromisoformat(end))
    return [
        {
            "id": m.id, "date": m.date.isoformat() if m.date else None,
            "attention_index": m.attention_index, "discussion_volume": m.discussion_volume,
            "media_volume": m.media_volume, "interaction_intensity": m.interaction_intensity,
        }
        for m in metrics
    ]


@router.get("/sentiment-summary/{vehicle_id}")
async def get_sentiment_summary(
    vehicle_id: str,
    start: str | None = Query(None), end: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    # T3.3：补 LISTING_CALIBER 口径 + coalesce 时间窗（原裸挂无口径）
    ap_q = (
        select(AnalyzedPost.sentiment, func.count(AnalyzedPost.id))
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == vehicle_id, *LISTING_CALIBER, *time_window_filter(start, end))
    )
    result = await session.execute(ap_q.group_by(AnalyzedPost.sentiment))
    counts = {row[0]: row[1] for row in result.all()}
    return {
        "positive": counts.get("positive", 0),
        "negative": counts.get("negative", 0),
        "neutral": counts.get("neutral", 0),
    }


@router.get("/top-events/{vehicle_id}")
async def get_top_events(
    vehicle_id: str,
    start: str | None = Query(None), end: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    # T3.3：补 LISTING_CALIBER 口径 + coalesce 时间窗（原裸挂无口径）
    ap_query = (
        select(AnalyzedPost.event_tags)
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == vehicle_id, *LISTING_CALIBER, *time_window_filter(start, end))
    )
    result = await session.execute(ap_query)
    tag_counts: dict[str, int] = {}
    for (tags_json,) in result.all():
        if tags_json:
            try:  # F-8：防坏 JSON
                for tag in json.loads(tags_json):
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
            except json.JSONDecodeError:
                continue
    return sorted(tag_counts.items(), key=lambda x: -x[1])


# 观点标签归并缓存（方案3）：{(vehicle_id, start, end): merged_top10}
_opinion_merge_cache: TTLCache = TTLCache(maxsize=128, ttl=3600)  # 1h TTL，自动驱逐


async def _merge_opinion_tags(tags_with_counts: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """LLM 归并同义标签。失败 raise LLMError/ValueError（调用方降级返回未归并）。"""
    tags_str = "\n".join(f"{tag}: {count}" for tag, count in tags_with_counts[:20])
    prompt = f"""你是舆情分析师。以下是某车型的用户观点标签及出现次数，请把同义标签归并：

{tags_str}

规则：
1. 同义标签归一组（如"价格便宜/价格合理/价格实惠/价格优惠"→"价格便宜"）
2. 每组取最简短常见的作为标准名
3. 保留所有标签（不丢弃）
4. 归并要彻底——价格相关（便宜/合理/实惠/优惠/划算）归一组；外观相关（颜值高/外观好看/造型好看）归一组；续航相关（续航长/续航里程长/续航远）归一组
5. 带情感后缀的变体归并到基础形态（如"续航长（正面）"→"续航长"；"价格便宜（正面）"→"价格便宜"；"续航短（负面）"→"续航短"）。后缀如（正面）/（负面）/（中性）一律剥离，归并到对应基础标签
6. 只输出 JSON 数组：[{{"name":"标准名","members":["原标签1","原标签2"]}}]"""
    raw = await call_llm(prompt, timeout=30)
    groups = extract_json_array(raw)
    if not groups or not isinstance(groups, list):
        raise ValueError("LLM 归并返回非 JSON 数组")
    # 合并计数
    count_map = dict(tags_with_counts)
    merged: dict[str, int] = {}
    for g in groups:
        name = g.get("name", "")
        members = g.get("members", [])
        total = sum(count_map.get(m, 0) for m in members)
        if name and total > 0:
            merged[name] = merged.get(name, 0) + total
    return sorted(merged.items(), key=lambda x: -x[1])


@router.get("/top-opinions/{vehicle_id}")
async def get_top_opinions(
    vehicle_id: str,
    start: str | None = Query(None), end: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    # 缓存检查（方案3）
    cache_key = (vehicle_id, start, end)
    cached = _opinion_merge_cache.get(cache_key)
    if cached is not None:
        return cached

    # 口径（C1）：LISTING_CALIBER——主车型帖 + 排除官方/经销商 + 排除无关帖
    ap_query = (
        select(AnalyzedPost.opinion_tags)
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == vehicle_id, *LISTING_CALIBER)
    )
    if start or end:
        sub = select(RawPost.id).where(RawPost.vehicle_id == vehicle_id)
        if start:
            sub = sub.where(RawPost.published_at >= datetime.fromisoformat(start))
        if end:
            sub = sub.where(RawPost.published_at < datetime.fromisoformat(end) + timedelta(days=1))
        post_ids_sub = sub.subquery()
        ap_query = ap_query.where(AnalyzedPost.post_id.in_(post_ids_sub))
    result = await session.execute(ap_query)
    tag_counts: dict[str, int] = {}
    for (tags_json,) in result.all():
        if tags_json:
            try:  # F-8：防坏 JSON
                for tag in json.loads(tags_json):
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
            except json.JSONDecodeError:
                continue
    # T5.4：最小计数门槛——计数 < 2 不进 TOP 榜（避免 1 次即进的噪音）
    _MIN_OPINION_COUNT = 2
    sorted_tags = sorted(
        ((t, c) for t, c in tag_counts.items() if c >= _MIN_OPINION_COUNT),
        key=lambda x: -x[1],
    )

    # 方案3：TOP20 → LLM 归并同义 → TOP10
    degraded = False
    if len(sorted_tags) <= 10:
        result_list = sorted_tags[:10]
    else:
        try:
            result_list = (await _merge_opinion_tags(sorted_tags[:20]))[:10]
        except (LLMError, ValueError):
            result_list = sorted_tags[:10]  # 降级：返回未归并 TOP10
            degraded = True  # T5.3：标记降级，前端可区分"未归并"与"已归并"

    # 写缓存（含 degraded 标记）
    cache_value = {"items": result_list, "degraded": degraded}
    _opinion_merge_cache[cache_key] = cache_value
    return cache_value
