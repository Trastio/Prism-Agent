import json
import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from api.query_scopes import time_window_filter
from models.database import get_session
from models.schemas import (
    AnalyzedPost, DefectTheme, EventGroup, HeatMetric, PostComment, RawPost,
    Report, SearchIndexMetric, Vehicle, AUTHENTIC_AUTHOR, RELEVANT_ONLY,
    SELF_ONLY, LISTING_CALIBER, INAUTHENTIC_AUTHOR_TYPES,
)
from utils.metrics import compute_health_score
from pipeline.platforms import normalize_platform, platform_query_values

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _relevant_posts_filter(query):
    """Add filter to exclude irrelevant posts from dashboard queries."""
    return query.where(RELEVANT_ONLY)


async def _get_vehicle_or_404(vehicle_id: str, session: AsyncSession) -> Vehicle:
    vehicle = await session.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(404, detail="Vehicle not found")
    return vehicle


def _safe_json_loads(text: str | None) -> dict | list:
    if not text:
        return {}
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}


# T5.5（confidence 阈值过滤，既定设计债 [[review-rounds-complete-2026-10-01]]）：
# 聚合层引入 confidence >= 阈值 过滤，低置信 fallback (0.0) 不等权入指标。
_CONFIDENCE_THRESHOLD = 0.3


def _confidence_filter():
    """返回 confidence 过滤条件：confidence >= 阈值 或 NULL（兼容旧数据）。"""
    return or_(AnalyzedPost.confidence >= _CONFIDENCE_THRESHOLD,
               AnalyzedPost.confidence.is_(None))  # NULL 视为旧数据保留


@router.get("/overview/{vehicle_id}")
async def get_overview(
    vehicle_id: str,
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
):
    vehicle = await _get_vehicle_or_404(vehicle_id, session)

    # 时间窗条件（coalesce 兜底 NULL published_at——微博/抖音详情采集器常不返回
    # 时间戳，直比 published_at 会静默丢帖）。前端默认传 30 天窗。
    tw = []
    if start:
        tw.append(func.coalesce(RawPost.published_at, RawPost.collected_at) >= datetime.fromisoformat(start))
    if end:
        tw.append(func.coalesce(RawPost.published_at, RawPost.collected_at) < datetime.fromisoformat(end) + timedelta(days=1))

    # 1. total（T3.3：改为与情感分母同源口径——排除竞品+官方+经销商+营销号+导流+irrelevant；
    #    v3 §13.2 实测星愿差 23%——原仅 REL 含竞品/官方帖导致总量与环图对不上）
    #    SELF_ONLY 引用 AnalyzedPost.subject，RawPost 查询需反排除 competitor
    #    （与 Phase 2 T2.1 heat_calculator 同模式：~RawPost.id.in_(competitor_post_ids)）
    competitor_ids_sub = (
        select(AnalyzedPost.post_id)
        .where(AnalyzedPost.vehicle_id == vehicle_id, AnalyzedPost.subject == "competitor")
    ).subquery()
    total_result = await session.execute(
        select(func.count(RawPost.id))
        .where(
            RawPost.vehicle_id == vehicle_id,
            AUTHENTIC_AUTHOR, RELEVANT_ONLY, *tw,
            ~RawPost.id.in_(select(competitor_ids_sub.c.post_id)),
        )
    )
    total = total_result.scalar() or 0

    # 2. sentiment 计数 pos/neg/neu（口径：SELF_ONLY + AUTHENTIC_AUTHOR + tw）
    #    T5.5：加 confidence >= 阈值 过滤，低置信 fallback 不等权入健康分
    sentiment_result = await session.execute(
        select(AnalyzedPost.sentiment, func.count(AnalyzedPost.id))
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == vehicle_id)
        .where(SELF_ONLY, AUTHENTIC_AUTHOR, _confidence_filter(), *tw)
        .group_by(AnalyzedPost.sentiment)
    )
    counts = {row[0]: row[1] for row in sentiment_result.all()}
    pos = counts.get("positive", 0)
    neg = counts.get("negative", 0)
    neu = counts.get("neutral", 0)

    # 3. analyzed_total（挂 tw；T5.5：加 confidence 过滤）
    analyzed_total_result = await session.execute(
        select(func.count(AnalyzedPost.id))
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == vehicle_id)
        .where(SELF_ONLY, AUTHENTIC_AUTHOR, _confidence_filter(), *tw)
    )
    analyzed_total = analyzed_total_result.scalar() or 0

    # 4. health_score（#1：统一调 compute_health_score 单一真相源）
    # T4.1（audit Phase 4）：0 帖时返 None（与 /fleet-overview 统一，当前返 50）
    if analyzed_total > 0:
        health_score = compute_health_score(pos, neg, analyzed_total)
    else:
        health_score = None

    # 5. week_change_rate（保持固定近7天vs上7天——不挂 tw，它是独立周趋势信号，
    # 语义与用户选择的任意窗不同。封顶 999 防数据积累期爆炸数）
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    week_result = await session.execute(
        _relevant_posts_filter(
            select(func.count(RawPost.id)).where(
                RawPost.vehicle_id == vehicle_id,
                # U-17：补 coalesce（published_at NULL 的帖用 collected_at 兜底，与车队视图一致）
                func.coalesce(RawPost.published_at, RawPost.collected_at) >= week_ago,
            )
        )
    )
    week_total = week_result.scalar() or 0

    two_weeks_ago = (date.today() - timedelta(days=14)).isoformat()
    prev_week_result = await session.execute(
        _relevant_posts_filter(
            select(func.count(RawPost.id)).where(
                RawPost.vehicle_id == vehicle_id,
                func.coalesce(RawPost.published_at, RawPost.collected_at) >= two_weeks_ago,
                func.coalesce(RawPost.published_at, RawPost.collected_at) < week_ago,
            )
        )
    )
    prev_week_total = prev_week_result.scalar() or 0

    if prev_week_total > 0:
        week_change_rate = round((week_total - prev_week_total) / prev_week_total * 100, 1)
        # 数据积累期保护：上周个位数帖 → 本周数百帖会出 +4737% 这类无信息量
        # 的爆炸数（M03 实测），封顶 999 让前端不至于渲染成长串
        if week_change_rate > 999:
            week_change_rate = 999.0
    elif week_total > 0:
        week_change_rate = 100.0
    else:
        week_change_rate = None

    # 6. comments_per_post（挂 tw：评论数 + 社媒帖数都按窗。分母=社媒帖：评论
    # 只挂社媒帖，新闻帖进分母只会稀释指标——"每帖评论数"语义应为社媒互动强度）
    comments_tw = []
    if start:
        comments_tw.append(func.coalesce(PostComment.published_at, PostComment.collected_at) >= datetime.fromisoformat(start))
    if end:
        comments_tw.append(func.coalesce(PostComment.published_at, PostComment.collected_at) < datetime.fromisoformat(end) + timedelta(days=1))
    comments_result = await session.execute(
        select(func.count(PostComment.id)).where(PostComment.vehicle_id == vehicle_id, *comments_tw)
    )
    total_comments = comments_result.scalar() or 0
    social_total_result = await session.execute(
        _relevant_posts_filter(
            select(func.count(RawPost.id)).where(
                RawPost.vehicle_id == vehicle_id,
                RawPost.platform != "news",
                *tw,
            )
        )
    )
    social_total = social_total_result.scalar() or 0
    comments_per_post = round(total_comments / max(social_total, 1), 1)

    lifecycle_anchors = _safe_json_loads(vehicle.lifecycle_anchors)

    # 7. peak_date（T3.3：加 SELF_ONLY，避免竞品帖峰值成为本品峰值日）
    # FIX 2026-10-11：SELF_ONLY 引用 AnalyzedPost.subject，RawPost 查询必须
    # outerjoin（未分析帖 subject 为 NULL 走 self 兜底）；缺 join 时 SQLAlchemy
    # 将 analyzed_posts 无条件交叉进 FROM——笛卡尔积既慢（万级帖×万级分析 ≈ 30s）
    # 又错（计数被放大数千倍）。同 LISTING_CALIBER 既有 outerjoin 惯例。
    if start or end:
        peak_result = await session.execute(
            _relevant_posts_filter(
                select(func.date(func.coalesce(RawPost.published_at, RawPost.collected_at)).label("d"),
                       func.count(RawPost.id))
                .outerjoin(AnalyzedPost, AnalyzedPost.post_id == RawPost.id)
                .where(RawPost.vehicle_id == vehicle_id, SELF_ONLY, *tw)
                .group_by("d").order_by(func.count(RawPost.id).desc()).limit(1)
            )
        )
    else:
        thirty_ago = (date.today() - timedelta(days=30)).isoformat()
        peak_result = await session.execute(
            select(func.date(func.coalesce(RawPost.published_at, RawPost.collected_at)).label("d"),
                   func.count(RawPost.id))
            .outerjoin(AnalyzedPost, AnalyzedPost.post_id == RawPost.id)
            .where(RawPost.vehicle_id == vehicle_id, SELF_ONLY,
                   func.coalesce(RawPost.published_at, RawPost.collected_at) >= thirty_ago)
            .group_by("d").order_by(func.count(RawPost.id).desc()).limit(1)
        )
    peak_row = peak_result.first()
    peak_date = peak_row[0] if peak_row else None
    peak_count = peak_row[1] if peak_row else 0

    # 8. best_dim/worst_dim（挂 tw；口径：排除官方/经销商）
    dim_result = await session.execute(
        select(AnalyzedPost.dim_sentiment)
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == vehicle_id)
        .where(SELF_ONLY, AUTHENTIC_AUTHOR, *tw)
    )
    dim_agg: dict[str, list[float]] = {}
    for (dim_json,) in dim_result.all():
        dims = _safe_json_loads(dim_json)
        if isinstance(dims, dict):
            for k, v in dims.items():
                dim_agg.setdefault(k, []).append(v)
    dim_avg = {k: round(sum(v) / len(v), 2) for k, v in dim_agg.items()}
    best_dim = max(dim_avg, key=dim_avg.get) if dim_avg else None
    worst_dim = min(dim_avg, key=dim_avg.get) if dim_avg else None

    return {
        "total_posts": total,
        "analyzed_posts": analyzed_total,
        "positive": pos, "negative": neg, "neutral": neu,
        "week_total": week_total,
        "week_change_rate": week_change_rate,
        "comments_per_post": comments_per_post,
        "health_score": health_score,
        "lifecycle_anchors": lifecycle_anchors,
        "peak_date": str(peak_date) if peak_date else None,
        "peak_count": peak_count,
        "best_dim": best_dim,
        "best_dim_score": dim_avg.get(best_dim) if best_dim else None,
        "worst_dim": worst_dim,
        "worst_dim_score": dim_avg.get(worst_dim) if worst_dim else None,
        # 样本不足护栏：窗内已分析帖 <20 时前端高亮提示，避免小基数误读健康分
        "sample_insufficient": analyzed_total < 20,
        # T5.2（ABSA A 方案）：评论维度模型可用性。模型未加载时前端显示"评论维度数据缺失"占位
        "comment_model_available": _check_comment_model_available(),
        # T5.1（M4 降级显式化）：降级状态字段，前端加角标
        "degraded": _overview_degraded_flags(),
    }


def _check_comment_model_available() -> bool:
    """T5.2：评论打标引擎可用性（2026-10-20 引擎切换后语义扩展）。

    deepseek（默认）= key 可解析（env/.secrets/pi-auth）；local = 模型已加载。
    """
    engine = os.environ.get("POLARITY_ENGINE", "deepseek").strip().lower()
    if engine != "local":
        from pipeline.analysis.deepseek_polarity import resolve_api_key  # noqa: inline-import
        return bool(resolve_api_key()[0])
    try:
        from pipeline.analysis.local_absa import LocalABSAModel  # noqa: inline-import
        return LocalABSAModel.get()._loaded
    except Exception:
        return False


def _overview_degraded_flags() -> list[str]:
    """T5.1：overview 降级标记列表。"""
    flags = []
    if not _check_comment_model_available():
        flags.append("comment_model_unavailable")
    return flags


@router.get("/fleet-overview")
async def get_fleet_overview(session: AsyncSession = Depends(get_session)):
    """一屏扫完所有车的健康度+异动+风险（D14 车队总览）。

    高效简化版：批量查询按 vehicle_id 分组，避免 N 车 × 8 查询。
    - health_score：近 30 天 SELF_ONLY+AUTHENTIC_AUTHOR 的 pos/neg/total
      （与 /overview 同口径，固定 30 天窗而非用户窗——车队视图要可比基准）
    - week_change_rate：近 7 天 vs 上 7 天 RELEVANT_ONLY 帖数（同 /overview）
    - risk_level：简化版——单因子负面率（≥25% high / ≥15% medium / else low），
      样本 <20 降级 insufficient（与 negative-radar 防抖一致，但舍去周环比/TOP
      互动两因子，车队视图求快扫不求全量风险画像）
    按健康分升序排（差的在前，便于巡检）。
    """
    vehicles = (await session.execute(
        select(Vehicle).where(Vehicle.status == "active")
    )).scalars().all()
    if not vehicles:
        return []

    vehicle_ids = [v.id for v in vehicles]

    # 固定时间锚点
    today = date.today()
    thirty_ago = today - timedelta(days=30)
    thirty_ago_dt = datetime.combine(thirty_ago, datetime.min.time())
    fleet_end_dt = datetime.combine(today + timedelta(days=1), datetime.min.time())  # T4.2：上界 < end+1天，排除未来帖
    week_ago = today - timedelta(days=7)
    two_weeks_ago = today - timedelta(days=14)

    # 1. 近 30 天情感计数（按 vehicle_id 分组）——口径同 /overview health_score
    # T4.2（audit Phase 4）：补上界 < end+1天，与 /overview 一致（当前仅 >= thirty_ago_dt）
    sent_q = (
        select(AnalyzedPost.vehicle_id, AnalyzedPost.sentiment, func.count(AnalyzedPost.id))
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id.in_(vehicle_ids))
        .where(SELF_ONLY, AUTHENTIC_AUTHOR)
        .where(func.coalesce(RawPost.published_at, RawPost.collected_at) >= thirty_ago_dt)
        .where(func.coalesce(RawPost.published_at, RawPost.collected_at) < fleet_end_dt)
        .group_by(AnalyzedPost.vehicle_id, AnalyzedPost.sentiment)
    )
    sent_rows = (await session.execute(sent_q)).all()
    # {vid: {sentiment: count, "_total": n}}
    sent_map: dict[str, dict[str, int]] = {}
    for vid, sentiment, cnt in sent_rows:
        sent_map.setdefault(vid, {})[sentiment or "neutral"] = cnt
    # 算每车 total
    for vid, counts in sent_map.items():
        counts["_total"] = sum(v for k, v in counts.items() if k != "_total")

    # 2. 本周帖数（按 vehicle_id 分组，RELEVANT_ONLY 口径同 /overview week_change）
    #    用 coalesce 兜底 NULL published_at，与 /overview 的固定周趋势信号一致——
    #    但 /overview 此处未挂 coalesce（历史遗留）；车队视图统一更稳。
    week_q = (
        select(RawPost.vehicle_id, func.count(RawPost.id))
        .where(RawPost.vehicle_id.in_(vehicle_ids), RELEVANT_ONLY)
        .where(func.coalesce(RawPost.published_at, RawPost.collected_at) >= week_ago)
        .group_by(RawPost.vehicle_id)
    )
    week_map = {vid: cnt for vid, cnt in (await session.execute(week_q)).all()}

    # 3. 上周帖数
    prev_q = (
        select(RawPost.vehicle_id, func.count(RawPost.id))
        .where(RawPost.vehicle_id.in_(vehicle_ids), RELEVANT_ONLY)
        .where(func.coalesce(RawPost.published_at, RawPost.collected_at) >= two_weeks_ago)
        .where(func.coalesce(RawPost.published_at, RawPost.collected_at) < week_ago)
        .group_by(RawPost.vehicle_id)
    )
    prev_map = {vid: cnt for vid, cnt in (await session.execute(prev_q)).all()}

    result = []
    for v in vehicles:
        counts = sent_map.get(v.id, {})
        pos = counts.get("positive", 0)
        neg = counts.get("negative", 0)
        analyzed_total = counts.get("_total", 0)

        # health_score（#1：统一调 compute_health_score）
        if analyzed_total > 0:
            health_score = compute_health_score(pos, neg, analyzed_total)
        else:
            health_score = None

        # week_change_rate（同 /overview：封顶 999，上周 0 本周>0 → 100）
        wt = week_map.get(v.id, 0)
        pt = prev_map.get(v.id, 0)
        if pt > 0:
            week_change_rate = round((wt - pt) / pt * 100, 1)
            if week_change_rate > 999:
                week_change_rate = 999.0
        elif wt > 0:
            week_change_rate = 100.0
        else:
            week_change_rate = None

        # risk_level（车队简化单因子：负面率；样本不足防抖）
        # T4.4（audit Phase 4）：与单车页 /negative-radar 的多因子风险算法不同——
        # 车队视图求快扫不求全量风险画像，只用负面率单因子。详见 docs/舆情看板-前端设计.md
        negative_rate = (neg / analyzed_total) if analyzed_total else 0.0
        if analyzed_total < 20:
            risk_level = "insufficient"
        elif negative_rate >= 0.25:
            risk_level = "high"
        elif negative_rate >= 0.15:
            risk_level = "medium"
        else:
            risk_level = "low"

        result.append({
            "id": v.id, "name": v.name, "brand": v.brand,
            "health_score": health_score,
            "week_change_rate": week_change_rate,
            "risk_level": risk_level,
            "analyzed_total": analyzed_total,
            "week_total": wt,
        })

    # 健康分升序（差的在前便于巡检）；无数据车 health_score=None 排末尾
    # （原视作 50 居中，但实际车分数均 >50 → 17 台无数据车被排到最前，违背巡检初衷）
    # sort key: (is None, score) — None 时第一个元素 True=1 排后有数据车后；
    # 有数据车按 score 升序（差的在前）。同 None 内 stable。
    result.sort(key=lambda x: (x["health_score"] is None, x["health_score"] if x["health_score"] is not None else 999))
    return result


@router.get("/increment-overview/{vehicle_id}")
async def get_increment_overview(
    vehicle_id: str,
    start: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
):
    """7天增量视图（D13）：本周新增负面/新事件/新缺陷簇/发酵中帖。

    用户拍板"7天需重构"——从过滤器改为增量模式：不再缩窗复看常规组件，而是
    回答"这周冒出了什么新东西"。口径与情感环一致：LISTING_CALIBER（主车型帖 +
    排除官方/经销商 + 排除无关帖），outerjoin AnalyzedPost 让 SELF_ONLY 在未分析
    帖上也生效（同 T1.4 comment-sentiment-overview 模式）。时间窗跟随
    coalesce(published_at, collected_at) 兜底 NULL（微博/抖音常不返回时间戳）。
    """
    await _get_vehicle_or_404(vehicle_id, session)
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end) + timedelta(days=1)

    # 1. 新增负面帖数（窗内 published_at 的负面帖）
    new_negative = await session.execute(
        select(func.count(AnalyzedPost.id))
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(
            AnalyzedPost.vehicle_id == vehicle_id,
            AnalyzedPost.sentiment == "negative",
            *LISTING_CALIBER,
            func.coalesce(RawPost.published_at, RawPost.collected_at) >= start_dt,
            func.coalesce(RawPost.published_at, RawPost.collected_at) < end_dt,
        )
    )
    new_negative_count = new_negative.scalar() or 0

    # 2. 新事件（EventGroup start_date 落在窗内）
    new_events = (await session.execute(
        select(EventGroup).where(
            EventGroup.vehicle_id == vehicle_id,
            EventGroup.start_date >= start_dt.date(),
            EventGroup.start_date < end_dt.date(),
        )
    )).scalars().all()

    # 3. 新缺陷簇（DefectTheme computed_at 在窗内——TTL 24h 表只存最新一行，
    #    computed_at 落在窗内即视为本周新算出的簇集）
    new_defects = (await session.execute(
        select(DefectTheme).where(
            DefectTheme.vehicle_id == vehicle_id,
            DefectTheme.computed_at >= start_dt,
        )
    )).scalars().all()
    new_defect_themes_count = 0
    for d in new_defects:
        try:
            payload = json.loads(d.payload) if d.payload else []
        except (json.JSONDecodeError, TypeError):
            payload = []
        if isinstance(payload, list):
            new_defect_themes_count += len(payload)

    # 4. 发酵中帖（窗内互动 top5——简化版，不对比历史互动）
    trending = (await session.execute(
        select(RawPost)
        .outerjoin(AnalyzedPost, AnalyzedPost.post_id == RawPost.id)
        .where(
            RawPost.vehicle_id == vehicle_id,
            *LISTING_CALIBER,
            func.coalesce(RawPost.published_at, RawPost.collected_at) >= start_dt,
        )
        .order_by((RawPost.likes + RawPost.comments + RawPost.shares).desc())
        .limit(5)
    )).scalars().all()

    return {
        "new_negative_count": new_negative_count,
        "new_events": [
            {
                "tag": e.event_tag,
                "start": str(e.start_date),
                "posts": e.post_count,
                "source": e.source or "social",
            }
            for e in new_events
        ],
        "new_defect_themes": new_defect_themes_count,
        "trending_posts": [
            {
                "id": p.id,
                "title": p.title or (p.content or "")[:40],
                "platform": p.platform,
                "likes": p.likes or 0,
                "comments": p.comments or 0,
            }
            for p in trending
        ],
    }


@router.get("/comment-sentiment-overview/{vehicle_id}")
async def get_comment_sentiment_overview(
    vehicle_id: str,
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
):
    """评论级口碑分布——从 PostComment.dim_sentiment 派生情感。

    与帖级 sentiment-donut **分开呈现不混算**：帖级走 AnalyzedPost.sentiment
    （GLM 主力标定），评论级走本地 ABSA dim_sentiment 均值映射
    （derive_comment_sentiment，阈值 ±0.3）。两套模型标定口径不同，混算会让
    量纲错位。口径同 LISTING_CALIBER——主车型帖 + 排除官方/经销商 + 排除无关
    帖；outerjoin AnalyzedPost 保留未分析帖（subject NULL 视为 self）。
    时间窗跟随 RawPost.coalesce(published_at, collected_at) 兜底 NULL。
    """
    await _get_vehicle_or_404(vehicle_id, session)
    from pipeline.collectors.post_utils import derive_comment_sentiment  # noqa: inline-import

    q = (
        select(PostComment.dim_sentiment, PostComment.comment_polarity)
        .join(RawPost, PostComment.post_id == RawPost.id)
        .outerjoin(AnalyzedPost, AnalyzedPost.post_id == RawPost.id)
        .where(RawPost.vehicle_id == vehicle_id, *LISTING_CALIBER)
    )
    if start:
        q = q.where(func.coalesce(RawPost.published_at, RawPost.collected_at) >= datetime.fromisoformat(start))
    if end:
        q = q.where(func.coalesce(RawPost.published_at, RawPost.collected_at) < datetime.fromisoformat(end) + timedelta(days=1))
    result = await session.execute(q)
    counts = {"positive": 0, "negative": 0, "neutral": 0}
    unanalyzed = 0  # §9.3: NULL/空 dim_sentiment 不计入 neutral，单独计数
    for dim_json, polarity in result.all():
        # 双轨（2026-10-16 T4）：极性直出列优先；两列皆空（含哨兵）= 未打标
        if polarity in ("1", "0", "-1"):
            counts[derive_comment_sentiment(dim_json, polarity)] += 1
            continue
        if not dim_json or dim_json in ("{}", "", "null"):
            unanalyzed += 1
            continue
        s = derive_comment_sentiment(dim_json)
        counts[s] += 1
    total = sum(counts.values())
    return {**counts, "total": total, "unanalyzed": unanalyzed}


@router.get("/comment-sentiment-trend/{vehicle_id}")
async def get_comment_sentiment_trend(
    vehicle_id: str,
    start: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
):
    """日级评论情感趋势——按日聚合评论级 positive/negative/neutral。

    与帖级 /sentiment-trend **分开不混算**：帖级走 AnalyzedPost.sentiment
    （GLM 标定，17 帖量级曲线扁平），评论级走 PostComment.dim_sentiment 均值
    映射（derive_comment_sentiment，阈值 ±0.3，~2400 评论敏感度天差地别）。
    口径同 LISTING_CALIBER——主车型帖 + 排除官方/经销商 + 排除无关帖；
    outerjoin AnalyzedPost 保留未分析帖（subject NULL 视为 self，同 T1.4 模式）。
    时间窗跟随 RawPost.coalesce(published_at, collected_at) 兜底 NULL。
    """
    await _get_vehicle_or_404(vehicle_id, session)
    from pipeline.collectors.post_utils import derive_comment_sentiment  # noqa: inline-import

    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end) + timedelta(days=1)

    q = (
        select(
            func.date(func.coalesce(RawPost.published_at, RawPost.collected_at)).label("d"),
            PostComment.dim_sentiment,
            PostComment.comment_polarity,
        )
        .join(RawPost, PostComment.post_id == RawPost.id)
        .outerjoin(AnalyzedPost, AnalyzedPost.post_id == RawPost.id)
        .where(RawPost.vehicle_id == vehicle_id, *LISTING_CALIBER)
        .where(func.coalesce(RawPost.published_at, RawPost.collected_at) >= start_dt)
        .where(func.coalesce(RawPost.published_at, RawPost.collected_at) < end_dt)
    )
    result = await session.execute(q)
    daily: dict[str, dict[str, int]] = {}
    for d, dim_json, polarity in result.all():
        if d is None:
            continue
        key = d.isoformat() if hasattr(d, "isoformat") else str(d)
        daily.setdefault(key, {"positive": 0, "negative": 0, "neutral": 0})
        # 双轨（2026-10-16 T4）：极性直出列优先
        if polarity in ("1", "0", "-1"):
            daily[key][derive_comment_sentiment(dim_json, polarity)] += 1
            continue
        # §9.3: NULL/空 dim_sentiment 不计入 neutral（避免 neutral 虚高）
        if not dim_json or dim_json in ("{}", "", "null"):
            continue
        s = derive_comment_sentiment(dim_json)
        daily[key][s] += 1

    # 填充缺失日期
    current = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    dates = []
    while current <= end_d:
        key = current.isoformat()
        dates.append(key)
        daily.setdefault(key, {"positive": 0, "negative": 0, "neutral": 0})
        current += timedelta(days=1)

    return [{"date": d, **daily[d]} for d in sorted(dates)]


@router.get("/trend/{vehicle_id}")
async def get_trend(
    vehicle_id: str,
    start: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
):
    vehicle = await _get_vehicle_or_404(vehicle_id, session)

    result = await session.execute(
        select(HeatMetric).where(
            HeatMetric.vehicle_id == vehicle_id,
            HeatMetric.date >= date.fromisoformat(start),
            HeatMetric.date <= date.fromisoformat(end),
        ).order_by(HeatMetric.date)
    )
    metrics = result.scalars().all()

    # 多平台搜索指数（抖音+小红书）：量纲不同（dy ~千、xhs ~百）→ 各源按
    # 窗口内自身 max 归一到 0-100，再对当日有值的源取平均 = 合成 search_index。
    # 前端优先用它，无指数数据的日子回退 attention_index（互动合成）。
    si_result = await session.execute(
        select(SearchIndexMetric).where(
            SearchIndexMetric.vehicle_id == vehicle_id,
            SearchIndexMetric.date >= date.fromisoformat(start),
            SearchIndexMetric.date <= date.fromisoformat(end),
        )
    )
    si_by_date: dict[str, dict[str, float]] = {}
    source_max: dict[str, float] = {}
    for m in si_result.scalars().all():
        iso = m.date.isoformat()
        si_by_date.setdefault(iso, {})[m.source] = m.index_value
        source_max[m.source] = max(source_max.get(m.source, 0.0), m.index_value)

    def _composite(iso: str) -> tuple[float | None, dict]:
        per_source = si_by_date.get(iso) or {}
        scaled = []
        for source, value in per_source.items():
            mx = source_max.get(source, 0.0)
            # value<=0 视为该源当日无数据（指数滞后：dy 当天常 0、PGY 滞后
            # 1-2 天），不计入合成——计入会把合成拖成 0 误报"热度归零"
            if mx > 0 and value > 0:
                scaled.append(min(value / mx, 1.0) * 100)
        if not scaled:
            return None, {}
        return round(sum(scaled) / len(scaled), 1), per_source

    points = []
    for m in metrics:
        iso = m.date.isoformat()
        composite, detail = _composite(iso)
        points.append({
            "date": iso,
            "attention_index": m.attention_index,
            "discussion_volume": m.discussion_volume,
            "media_volume": m.media_volume,
            "interaction_intensity": m.interaction_intensity,
            "search_index": composite,
            "search_detail": detail or None,
        })

    lifecycle_phases = []
    anchors = _safe_json_loads(vehicle.lifecycle_anchors)
    if anchors:
        start_d = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
        for phase_name, phase_date_str in anchors.items():
            try:
                pd = date.fromisoformat(phase_date_str)
                if start_d <= pd <= end_d:
                    lifecycle_phases.append({"type": phase_name, "date": phase_date_str})
            except (ValueError, TypeError):
                pass

    # 话题标注：时间窗内 EventGroup 按周分组，前端趋势图 markPoint 标在峰值周
    # 周起点对齐前端 renderAttentionChart 的分桶（JS getDay()→周日为 0，即周日起）。
    # 用 (weekday()+1)%7 把 Python weekday（周一=0）折算成 JS getDay（周日=0），
    # 保证 annotation key 与前端 x 轴 weekKey 严格一致，markPoint coord 才能命中。
    events_q = select(EventGroup).where(
        EventGroup.vehicle_id == vehicle_id,
        EventGroup.end_date >= date.fromisoformat(start),
        EventGroup.start_date <= date.fromisoformat(end),
    )
    event_annotations: dict[str, list[str]] = {}
    for e in (await session.execute(events_q)).scalars().all():
        js_dow = (e.start_date.weekday() + 1) % 7
        week_start = e.start_date - timedelta(days=js_dow)
        event_annotations.setdefault(week_start.isoformat(), []).append(e.event_tag)

    return {"data": points, "lifecycle_phases": lifecycle_phases, "event_annotations": event_annotations}


@router.get("/sentiment-trend/{vehicle_id}")
async def get_sentiment_trend(
    vehicle_id: str,
    start: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
):
    """Daily sentiment counts for stacked area chart."""
    await _get_vehicle_or_404(vehicle_id, session)
    start_d = date.fromisoformat(start)
    end_d = date.fromisoformat(end)

    start_dt = datetime.combine(start_d, datetime.min.time())
    end_dt = datetime.combine(end_d + timedelta(days=1), datetime.min.time())

    result = await session.execute(
        select(
            func.date(RawPost.published_at).label("d"),
            AnalyzedPost.sentiment,
            func.count(AnalyzedPost.id),
        )
        .join(AnalyzedPost, AnalyzedPost.post_id == RawPost.id)
        .where(
            RawPost.vehicle_id == vehicle_id,
            RawPost.published_at >= start_dt,
            RawPost.published_at < end_dt,
            SELF_ONLY,
            AUTHENTIC_AUTHOR,  # 口碑口径：排除官方/经销商（2026-09-15 Q5）
        )
        .group_by("d", AnalyzedPost.sentiment)
        .order_by("d")
    )

    daily: dict[str, dict[str, int]] = {}
    for d, sentiment, cnt in result.all():
        if d is None:
            continue
        key = d.isoformat() if hasattr(d, "isoformat") else str(d)
        daily.setdefault(key, {"positive": 0, "negative": 0, "neutral": 0})
        if sentiment in daily[key]:
            daily[key][sentiment] = cnt

    # Fill missing dates
    dates = []
    current = start_d
    while current <= end_d:
        key = current.isoformat()
        dates.append(key)
        daily.setdefault(key, {"positive": 0, "negative": 0, "neutral": 0})
        current += timedelta(days=1)

    return [
        {"date": d, **daily[d]}
        for d in sorted(dates)
    ]


@router.get("/platform-distribution/{vehicle_id}")
async def get_platform_distribution(
    vehicle_id: str,
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
):
    await _get_vehicle_or_404(vehicle_id, session)
    # T3.3：用 scoped_posts 统一 LISTING_CALIBER 口径 + coalesce 时间窗
    # FIX 2026-10-11：SELF_ONLY 引用 AnalyzedPost.subject，须 outerjoin（未分析帖
    # 走 self 兜底）；原缺 join 触发笛卡尔积——实测平台计数被放大约 7500 倍
    # （xiaohongshu 810→8176074）且查询耗时 15~30s。同 LISTING_CALIBER 惯例。
    query = (
        select(RawPost.platform, AnalyzedPost.sentiment, func.count(RawPost.id))
        .outerjoin(AnalyzedPost, AnalyzedPost.post_id == RawPost.id)
        .where(RawPost.vehicle_id == vehicle_id, SELF_ONLY, AUTHENTIC_AUTHOR, RELEVANT_ONLY, *time_window_filter(start, end))
    )
    query = query.group_by(RawPost.platform, AnalyzedPost.sentiment)
    result = await session.execute(query)
    # 聚合到规范名：迁移前 dy/douyin 分组经 normalize 合并，迁移后自然单一
    # 2026-10-20：同时给出该平台的情感细分（未分析帖计入 unknown，总数口径不变）
    dist: dict[str, dict] = {}
    for platform_name, sentiment, count in result.all():
        key = normalize_platform(platform_name) or "unknown"
        row = dist.get(key)
        if row is None:
            row = {"platform": key, "count": 0, "positive": 0, "neutral": 0, "negative": 0, "unknown": 0}
            dist[key] = row
        c = count or 0
        row["count"] += c
        se = sentiment if sentiment in ("positive", "neutral", "negative") else "unknown"
        row[se] += c
    return list(dist.values())


@router.get("/event-distribution/{vehicle_id}")
async def get_event_distribution(
    vehicle_id: str,
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
):
    await _get_vehicle_or_404(vehicle_id, session)
    # T3.3：补 AUTHENTIC_AUTHOR + RELEVANT_ONLY（原仅 SELF_ONLY），时间窗用 coalesce
    ap_query = (
        select(AnalyzedPost.event_tags)
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == vehicle_id, SELF_ONLY, AUTHENTIC_AUTHOR, RELEVANT_ONLY, *time_window_filter(start, end))
    )
    result = await session.execute(ap_query)
    tag_counts: dict[str, int] = {}
    for (tags_json,) in result.all():
        tags = _safe_json_loads(tags_json)
        if isinstance(tags, list):
            for tag in tags:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
    return sorted(tag_counts.items(), key=lambda x: -x[1])[:15]


@router.get("/top-posts/{vehicle_id}")
async def get_top_posts(
    vehicle_id: str,
    platform: str | None = Query(None),
    sentiment: str | None = Query(None, pattern="^(positive|negative|neutral)$"),
    limit: int = Query(10, ge=1, le=50),
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
):
    """Top posts by engagement (likes+comments+shares).

    排除 irrelevant 帖（2026-09-15 修：星愿实采发现 LLM 判无关的 K-pop
    "星愿降临"帖 1.4 万赞登上热帖榜——过滤层工作了，展示层漏挂）。
    sentiment 过滤支撑"吐槽榜"（负面×互动 = 舆情风险的优先视野）。
    口径（C1）：LISTING_CALIBER——主车型帖 + 排除官方/经销商 + 排除无关帖。
    outerjoin AnalyzedPost 保留未分析帖（subject NULL 视为 self）。
    """
    await _get_vehicle_or_404(vehicle_id, session)
    query = (
        select(RawPost)
        .outerjoin(AnalyzedPost, AnalyzedPost.post_id == RawPost.id)
        .where(RawPost.vehicle_id == vehicle_id, *LISTING_CALIBER)
    )
    if platform:
        query = query.where(RawPost.platform.in_(platform_query_values(platform)))
    if sentiment:
        analyzed = await session.execute(
            select(AnalyzedPost.post_id).where(
                AnalyzedPost.vehicle_id == vehicle_id,
                AnalyzedPost.sentiment == sentiment,
                SELF_ONLY,
            )
        )
        query = query.where(RawPost.id.in_([row[0] for row in analyzed.all()]))
    if start:
        query = query.where(func.coalesce(RawPost.published_at, RawPost.collected_at) >= datetime.fromisoformat(start))
    if end:
        query = query.where(func.coalesce(RawPost.published_at, RawPost.collected_at) < datetime.fromisoformat(end) + timedelta(days=1))

    query = query.order_by(
        (RawPost.likes + RawPost.comments + RawPost.shares).desc(),
        RawPost.published_at.desc(),
    ).limit(limit)

    result = await session.execute(query)
    posts = result.scalars().all()

    # Get full analysis for each post
    post_ids = [p.id for p in posts]
    analysis_map: dict[str, AnalyzedPost] = {}
    if post_ids:
        ap_result = await session.execute(
            select(AnalyzedPost).where(AnalyzedPost.post_id.in_(post_ids))
        )
        for ap in ap_result.scalars().all():
            analysis_map[ap.post_id] = ap

    def _ap_fields(ap):
        if not ap:
            return {}
        return {
            "sentiment": ap.sentiment or "",
            "subject_name": ap.subject_name or "",
            "dim_sentiment": ap.dim_sentiment or "",
            "event_tags": ap.event_tags or "",
            "opinion_tags": ap.opinion_tags or "",
            "comment_summary": ap.comment_summary or "",
        }

    return [
        {
            "id": p.id, "title": p.title, "content": p.content,
            "platform": p.platform, "source": p.source,
            "author": p.author, "url": p.url,
            "author_type": p.author_type or "organic",
            "likes": p.likes or 0, "comments": p.comments or 0, "shares": p.shares or 0,
            "engagement": (p.likes or 0) + (p.comments or 0) + (p.shares or 0),
            "published_at": p.published_at.isoformat() if p.published_at else None,
            **_ap_fields(analysis_map.get(p.id)),
        }
        for p in posts
    ]


@router.get("/posts/{vehicle_id}")
async def get_posts(
    vehicle_id: str,
    page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
    sentiment: str | None = Query(None), platform: str | None = Query(None),
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
):
    await _get_vehicle_or_404(vehicle_id, session)
    # 同 top-posts：irrelevant 帖不进内容列表（analysis_status 字段仍返回）
    query = _relevant_posts_filter(
        select(RawPost).where(RawPost.vehicle_id == vehicle_id)
    )
    if platform:
        query = query.where(RawPost.platform.in_(platform_query_values(platform)))
    if sentiment:
        analyzed = await session.execute(
            select(AnalyzedPost.post_id).where(
                AnalyzedPost.vehicle_id == vehicle_id,
                AnalyzedPost.sentiment == sentiment,
                SELF_ONLY,
            )
        )
        post_ids = [row[0] for row in analyzed.all()]
        query = query.where(RawPost.id.in_(post_ids))
    if start:
        start_dt = datetime.fromisoformat(start)
        query = query.where(RawPost.published_at >= start_dt)
    if end:
        end_dt = datetime.fromisoformat(end) + timedelta(days=1)
        query = query.where(RawPost.published_at < end_dt)

    total_result = await session.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = total_result.scalar() or 0

    offset = (page - 1) * size
    result = await session.execute(query.order_by(RawPost.published_at.desc()).offset(offset).limit(size))
    posts = result.scalars().all()

    # Batch-load analysis fields for these posts
    post_ids = [p.id for p in posts]
    analysis_map: dict[str, AnalyzedPost] = {}
    if post_ids:
        ap_res = await session.execute(
            select(AnalyzedPost).where(AnalyzedPost.post_id.in_(post_ids))
        )
        for ap in ap_res.scalars().all():
            analysis_map[ap.post_id] = ap

    def _ap_fields(ap):
        if not ap:
            return {}
        return {
            "sentiment": ap.sentiment or "",
            "subject_name": ap.subject_name or "",
            "dim_sentiment": ap.dim_sentiment or "",
            "event_tags": ap.event_tags or "",
            "opinion_tags": ap.opinion_tags or "",
            "comment_summary": ap.comment_summary or "",
        }

    return {
        "items": [
            {
                "id": p.id, "title": p.title, "content": p.content,
                "platform": p.platform, "source": p.source,
                "author": p.author, "url": p.url,
                "author_type": p.author_type or "organic",
                "likes": p.likes, "comments": p.comments, "shares": p.shares,
                "published_at": p.published_at.isoformat() if p.published_at else None,
                "analysis_status": p.analysis_status,
                **_ap_fields(analysis_map.get(p.id)),
            }
            for p in posts
        ],
        "total": total, "page": page, "size": size,
    }


@router.get("/reports/{vehicle_id}")
async def get_reports(vehicle_id: str, session: AsyncSession = Depends(get_session)):
    await _get_vehicle_or_404(vehicle_id, session)
    result = await session.execute(
        select(Report).where(Report.vehicle_id == vehicle_id)
        .order_by(Report.created_at.desc())
    )
    reports = result.scalars().all()
    return [
        {
            "id": r.id, "type": r.type, "title": r.title,
            "content": r.content,
            "time_range_start": r.time_range_start.isoformat() if r.time_range_start else None,
            "time_range_end": r.time_range_end.isoformat() if r.time_range_end else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in reports
    ]


@router.get("/competitor-comparison/{vehicle_id}")
async def get_competitor_comparison(
    vehicle_id: str,
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
):
    vehicle = await _get_vehicle_or_404(vehicle_id, session)
    competitor_ids = _safe_json_loads(vehicle.competitor_ids)
    if not isinstance(competitor_ids, list) or not competitor_ids:
        return []

    all_ids = [vehicle_id] + competitor_ids
    vehicles_result = await session.execute(
        select(Vehicle).where(Vehicle.id.in_(all_ids))
    )
    vehicles_map = {v.id: v.name for v in vehicles_result.scalars().all()}

    # #14：批量查询（原 for 循环逐车 N+1，改一次查所有车按 vehicle_id+sentiment 分组）
    batch_q = (select(AnalyzedPost.vehicle_id, AnalyzedPost.sentiment, func.count(AnalyzedPost.id))
               .join(RawPost, AnalyzedPost.post_id == RawPost.id)
               .where(AnalyzedPost.vehicle_id.in_(all_ids), SELF_ONLY, AUTHENTIC_AUTHOR))
    if start:
        batch_q = batch_q.where(func.coalesce(RawPost.published_at, RawPost.collected_at) >= datetime.fromisoformat(start))
    if end:
        batch_q = batch_q.where(func.coalesce(RawPost.published_at, RawPost.collected_at) < datetime.fromisoformat(end) + timedelta(days=1))
    batch_q = batch_q.group_by(AnalyzedPost.vehicle_id, AnalyzedPost.sentiment)
    batch_result = await session.execute(batch_q)
    # 聚合：vid → {sentiment: count}
    counts_by_vid: dict[str, dict[str, int]] = {}
    for vid, sent, cnt in batch_result.all():
        counts_by_vid.setdefault(vid, {})[sent] = cnt

    result = []
    for vid in all_ids:
        name = vehicles_map.get(vid, "未知")
        counts = counts_by_vid.get(vid, {})
        result.append({
            "name": name,
            "vehicle_id": vid,
            "positive": counts.get("positive", 0),
            "negative": counts.get("negative", 0),
            "neutral": counts.get("neutral", 0),
        })
    return result


@router.get("/comment-sentiment-diff/{vehicle_id}")
async def get_comment_sentiment_diff(
    vehicle_id: str,
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
):
    """Show posts where comment_summary.genuine_sentiment differs from post sentiment.

    direction: pos2neg/neg2pos；帖中性时 other（无评论行的帖 top_comment 为 None）。
    """
    ap_q = select(AnalyzedPost).where(
        AnalyzedPost.vehicle_id == vehicle_id,
        AnalyzedPost.comment_summary.isnot(None),
        SELF_ONLY,
    )
    # No published_at window: same reason as select_top_posts_for_comments —
    # weibo/douyin posts have NULL published_at and would be silently dropped,
    # leaving the controversial-post card empty even when summaries exist.
    result = await session.execute(ap_q)
    analyzed = result.scalars().all()

    # Batch load RawPosts to avoid N+1
    post_ids = [ap.post_id for ap in analyzed if ap.post_id]
    posts_map = {}
    if post_ids:
        pr = await session.execute(select(RawPost).where(RawPost.id.in_(post_ids)))
        posts_map = {p.id: p for p in pr.scalars().all()}

    # 口径（T3.3：用 INAUTHENTIC_AUTHOR_TYPES 替换硬编码，补 marketing_account；
    #    v3 §6.4 实证此处漏 marketing_account 与 AUTHENTIC_AUTHOR 漂移）
    analyzed = [
        ap for ap in analyzed
        if (p := posts_map.get(ap.post_id)) is None
        or not p.author_type or p.author_type not in INAUTHENTIC_AUTHOR_TYPES
    ]

    diff_items = []
    for ap in analyzed:
        try:
            cs = json.loads(ap.comment_summary) if ap.comment_summary else {}
        except (json.JSONDecodeError, TypeError):
            continue
        gs = cs.get("genuine_sentiment", "")
        if gs and gs != ap.sentiment:
            post = posts_map.get(ap.post_id)
            diff_items.append({
                "post_id": ap.post_id,
                "title": (post.title or post.content[:40]) if post else "",
                "platform": post.platform if post else None,
                "url": post.url if post else None,  # R2：查看原文链接
                "likes": post.likes if post else 0,  # R2：互动数
                "post_sentiment": ap.sentiment,
                "comment_sentiment": gs,
                "is_argumentative": cs.get("is_argumentative", False),
                "genuine_themes": cs.get("genuine_themes", []),
                "summary": cs.get("summary", ""),
            })

    # 口碑反转卡增强（2026-09-20 openspec monitor-slimdown）：
    # direction + 评论总数 + 热门评论摘录（按 likes top1）
    diff_ids = [d["post_id"] for d in diff_items]
    top_by_post: dict[str, dict] = {}
    if diff_ids:
        crows = await session.execute(
            select(PostComment).where(PostComment.post_id.in_(diff_ids))
            .order_by(PostComment.likes.desc())
        )
        for c in crows.scalars():
            top_by_post.setdefault(c.post_id, {
                "content": (c.content or "")[:120], "likes": c.likes or 0, "author": c.author,
            })
    for d in diff_items:
        d["direction"] = ("pos2neg" if d["post_sentiment"] == "positive"
                          else "neg2pos" if d["post_sentiment"] == "negative" else "other")
        d["comment_count"] = 0
        if (p := posts_map.get(d["post_id"])) is not None:
            d["comment_count"] = p.comments or 0
        d["top_comment"] = top_by_post.get(d["post_id"])
    return diff_items


@router.get("/word-cloud/{vehicle_id}")
async def get_word_cloud(
    vehicle_id: str,
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(80, ge=10, le=200),
    platform: str | None = Query(None, description="按平台出词云（douyin / xiaohongshu / chezhiwang）"),
    session: AsyncSession = Depends(get_session),
):
    """Keyword frequency from post titles + content for word cloud.

    口径（C1）：LISTING_CALIBER——主车型帖 + 排除官方/经销商 + 排除无关帖。
    outerjoin AnalyzedPost 保留未分析帖（subject NULL 视为 self），仅排除
    subject='competitor' 的竞品帖。
    2026-10-20：新增 platform 过滤，支持分平台词云（同一口径，不另起统计）。
    """
    import jieba  # noqa: inline-import
    vehicle = await _get_vehicle_or_404(vehicle_id, session)
    query = (
        select(RawPost.title, RawPost.content)
        .outerjoin(AnalyzedPost, AnalyzedPost.post_id == RawPost.id)
        .where(RawPost.vehicle_id == vehicle_id, *LISTING_CALIBER)
    )
    if platform:
        query = query.where(RawPost.platform.in_(platform_query_values(platform)))
    if start:
        query = query.where(func.coalesce(RawPost.published_at, RawPost.collected_at) >= datetime.fromisoformat(start))
    if end:
        query = query.where(func.coalesce(RawPost.published_at, RawPost.collected_at) < datetime.fromisoformat(end) + timedelta(days=1))
    result = await session.execute(query)
    text_pool = []
    for title, content in result.all():
        if title:
            text_pool.append(title)
        if content:
            text_pool.append(content)
    combined = " ".join(text_pool)
    # Use jieba for Chinese segmentation + regex for English
    cn_words = [w for w in jieba.cut(combined) if len(w) >= 2 and re.fullmatch(r'[一-鿿]+', w)]
    en_words = re.findall(r'[a-zA-Z]{3,}', combined)
    stopwords = {
        "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
        "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
        "自己", "这", "他", "她", "它", "们", "那", "被", "把", "让", "给", "从", "对",
        "但", "而", "又", "与", "及", "等", "可", "以", "所以", "因为", "如果", "但是",
        "不过", "还是", "已经", "可以", "这个", "那个", "什么", "怎么", "为什么",
        "com", "www", "http", "https", "the", "and", "for", "not", "are", "but",
        "这个", "那个", "什么", "怎么", "这样", "那样", "那么", "这么", "其实",
        "已经", "应该", "可能", "还是", "而且", "虽然", "然后", "如果", "因为",
        "之后", "之前", "现在", "以后", "比较", "非常", "真的", "感觉", "觉得",
        "时候", "地方", "东西", "问题", "知道", "需要", "通过", "以及", "关于",
    }
    # 注入停用词（B4/D9）：当前车型名/品牌 + 全库车型名（防对比帖他车名霸屏）
    # + 通稿套话高频无信息量词，治词云霸屏。
    generic_names: set[str] = set()
    if vehicle.name:
        generic_names.add(vehicle.name)
    if vehicle.brand:
        generic_names.add(vehicle.brand)
    all_vehicles = (await session.execute(select(Vehicle.name, Vehicle.brand))).all()
    for name, brand in all_vehicles:
        if name:
            generic_names.add(name)
        if brand:
            generic_names.add(brand)
    # 车名常含品牌前缀（如"奇瑞风云"/"吉利银河"），jieba 切出的子串也要屏蔽。
    # 用 jieba 切分车名，与词云分词器同源，确保子串口径一致。
    extra_substrings: set[str] = set()
    for token in list(generic_names):
        for sub in jieba.cut(token):
            if len(sub) >= 2 and re.fullmatch(r"[一-鿿]+", sub):
                extra_substrings.add(sub)
    generic_names |= extra_substrings
    # 通稿套话词表（营销/参数/品类泛词，无情感信息量）
    BOILERPLATE_WORDS = {
        "纯电", "suv", "全球", "全系", "万元", "上市", "实测", "汽车", "品质",
        "高速", "电池", "续航", "新能源", "电动", "车型", "级别", "全新",
        "轿车", "越野", "混动", "插混", "增程", "发动机", "变速箱", "底盘",
        "内饰", "外观", "空间", "配置", "动力", "试驾", "评测", "优惠",
        "经销商", "报价", "落地", "提车", "交付", "订单", "销量",
    }
    stopwords = stopwords | {w.lower() for w in generic_names} | {w.lower() for w in BOILERPLATE_WORDS}
    word_freq: dict[str, int] = {}
    for w in cn_words + en_words:
        w = w.lower()
        if w not in stopwords and len(w) >= 2:
            word_freq[w] = word_freq.get(w, 0) + 1
    top = sorted(word_freq.items(), key=lambda x: -x[1])[:limit]
    return [{"name": w, "value": c} for w, c in top]


@router.get("/negative-radar/{vehicle_id}")
async def get_negative_radar(
    vehicle_id: str,
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
):
    """负面雷达：高影响吐槽帖 + 风险信号聚合（2026-09-16）。

    业界共识的本地化：异动（周环比）优先于绝对量；负面×影响力交叉成榜；
    风险档位=可解释的三因子规则（负面率/环比/TOP吐槽互动），样本不足降级
    提示而非虚报。口径与情感环一致：主车型帖（SELF_ONLY）+ 排除官方/经销商
    （AUTHENTIC_AUTHOR）；irrelevant 帖无 AnalyzedPost 行，结构性排除。
    周环比沿用 overview 口径：本周 vs 上周、封顶 999、上周 0 本周>0 → 100。
    """
    await _get_vehicle_or_404(vehicle_id, session)

    start_dt = datetime.fromisoformat(start) if start else None
    end_dt = datetime.fromisoformat(end) + timedelta(days=1) if end else None

    def _window(q):
        if start_dt:
            q = q.where(RawPost.published_at >= start_dt)
        if end_dt:
            q = q.where(RawPost.published_at < end_dt)
        return q

    # 1. 情感计数（口碑口径 + 时间窗）
    base = (
        select(AnalyzedPost.sentiment, func.count(AnalyzedPost.id))
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == vehicle_id)
        .where(SELF_ONLY, AUTHENTIC_AUTHOR)
    )
    sent_result = await session.execute(_window(base).group_by(AnalyzedPost.sentiment))
    counts = {row[0]: row[1] for row in sent_result.all()}
    neg = counts.get("negative", 0)
    pos = counts.get("positive", 0)
    neu = counts.get("neutral", 0)
    analyzed_total = pos + neg + neu
    negative_rate = round(neg / analyzed_total, 4) if analyzed_total else 0.0

    # 2. 负面声量周环比（固定本周 vs 上周，与 KPI「声量节奏」同语义）
    now = datetime.now()
    week_ago = now - timedelta(days=7)
    two_weeks_ago = now - timedelta(days=14)

    async def _neg_between(a, b):
        r = await session.execute(
            select(func.count(AnalyzedPost.id))
            .join(RawPost, AnalyzedPost.post_id == RawPost.id)
            .where(
                AnalyzedPost.vehicle_id == vehicle_id,
                AnalyzedPost.sentiment == "negative",
                SELF_ONLY, AUTHENTIC_AUTHOR,
                RawPost.published_at >= a, RawPost.published_at < b,
            )
        )
        return r.scalar() or 0

    neg_week = await _neg_between(week_ago, now)
    neg_prev_week = await _neg_between(two_weeks_ago, week_ago)
    if neg_prev_week > 0:
        neg_wow = round((neg_week - neg_prev_week) / neg_prev_week * 100, 1)
        if neg_wow > 999:
            neg_wow = 999.0
    elif neg_week > 0:
        neg_wow = 100.0
    else:
        neg_wow = None

    # 3. 高影响吐槽榜 TOP10（影响力分与 dashboard-summary 同权重）
    # 动态门槛（D7）：先算该车近30天负面帖的互动中位数，低于中位数的帖不进榜，
    # 不凑数——避免 infl=8 的低质帖只因凑满 10 条而混入榜内。
    median_q = _window(
        select((RawPost.likes + RawPost.comments + RawPost.shares).label("eng"))
        .join(AnalyzedPost, AnalyzedPost.post_id == RawPost.id)
        .where(
            AnalyzedPost.vehicle_id == vehicle_id,
            AnalyzedPost.sentiment == "negative",
            SELF_ONLY, AUTHENTIC_AUTHOR,
        )
    )
    eng_rows = (await session.execute(median_q)).all()
    eng_values = sorted((r[0] or 0) for r in eng_rows)
    median_engagement = eng_values[len(eng_values) // 2] if eng_values else 0

    complaints_q = _window(
        select(AnalyzedPost, RawPost)
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(
            AnalyzedPost.vehicle_id == vehicle_id,
            AnalyzedPost.sentiment == "negative",
            SELF_ONLY, AUTHENTIC_AUTHOR,
            (RawPost.likes + RawPost.comments + RawPost.shares) >= median_engagement,
        )
    ).order_by(
        (RawPost.likes + RawPost.comments + RawPost.shares).desc()
    ).limit(10)
    complaints_result = await session.execute(complaints_q)
    top_complaints = []
    for ap, rp in complaints_result.all():
        dims = _safe_json_loads(ap.dim_sentiment)
        top_neg_dims = []
        if isinstance(dims, dict):
            scored = sorted(
                ((k, float(v)) for k, v in dims.items() if isinstance(v, (int, float))),
                key=lambda kv: kv[1],
            )
            top_neg_dims = [k for k, _ in scored[:2]]
        top_complaints.append({
            "id": rp.id, "title": rp.title or (rp.content or "")[:60],
            "platform": rp.platform, "author_type": rp.author_type,
            "sentiment": "negative",
            "likes": rp.likes or 0, "comments": rp.comments or 0, "shares": rp.shares or 0,
            "influence_score": (rp.likes or 0) + (rp.comments or 0) + (rp.shares or 0),
            "top_neg_dims": top_neg_dims, "published_at": str(rp.published_at or ""),
            "url": rp.url,
        })

    # 4. 负面维度 TOP5（负面帖里该维出现次数 / 全部口碑帖该维出现次数）
    neg_dims_q = _window(
        select(AnalyzedPost.dim_sentiment)
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(
            AnalyzedPost.vehicle_id == vehicle_id,
            AnalyzedPost.sentiment == "negative",
            SELF_ONLY, AUTHENTIC_AUTHOR,
        )
    )
    neg_dim_counter: dict[str, int] = {}
    for (dim_json,) in (await session.execute(neg_dims_q)).all():
        dims = _safe_json_loads(dim_json)
        if isinstance(dims, dict):
            for k in dims:
                neg_dim_counter[k] = neg_dim_counter.get(k, 0) + 1
    all_dim_counter: dict[str, int] = {}
    if neg_dim_counter:
        all_dims_q = _window(
            select(AnalyzedPost.dim_sentiment)
            .join(RawPost, AnalyzedPost.post_id == RawPost.id)
            .where(AnalyzedPost.vehicle_id == vehicle_id)
            .where(SELF_ONLY, AUTHENTIC_AUTHOR)
        )
        for (dim_json,) in (await session.execute(all_dims_q)).all():
            dims = _safe_json_loads(dim_json)
            if isinstance(dims, dict):
                for k in dims:
                    all_dim_counter[k] = all_dim_counter.get(k, 0) + 1
    negative_dims = [
        {
            "dim": k,
            "negative_count": c,
            "total_count": all_dim_counter.get(k, c),
            "negative_rate": round(c / all_dim_counter[k], 4) if all_dim_counter.get(k) else 1.0,
        }
        for k, c in sorted(neg_dim_counter.items(), key=lambda kv: -kv[1])[:5]
    ]

    # 5. 负面事件 TOP3（负面帖数优先，post_count 破平）
    events_q = select(EventGroup).where(EventGroup.vehicle_id == vehicle_id)
    if start:
        events_q = events_q.where(EventGroup.end_date >= date.fromisoformat(start))
    if end:
        events_q = events_q.where(EventGroup.start_date <= date.fromisoformat(end))
    events = (await session.execute(events_q)).scalars().all()
    neg_events = []
    for e in events:
        dist = _safe_json_loads(e.sentiment_distribution)
        n = dist.get("negative", 0) if isinstance(dist, dict) else 0
        if n > 0:
            neg_events.append((n, e))
    neg_events.sort(key=lambda t: (t[0], t[1].post_count or 0), reverse=True)
    negative_events = [
        {
            "id": e.id, "event_tag": e.event_tag, "source": e.source or "social",
            "start_date": str(e.start_date), "end_date": str(e.end_date),
            "post_count": e.post_count, "negative_posts": n,
            "summary": e.summary,
            "sentiment_distribution": _safe_json_loads(e.sentiment_distribution),
        }
        for n, e in neg_events[:3]
    ]

    # 6. 风险档位：三因子可解释规则（样本不足防抖优先）
    if analyzed_total < 20:
        risk_level, risk_reasons = "insufficient", [
            f"样本不足（分析帖 {analyzed_total} < 20），档位仅供参考"
        ]
    else:
        score = 0
        reasons = []
        if negative_rate >= 0.25:
            score += 2; reasons.append(f"负面率 {negative_rate:.0%}（≥25%）")
        elif negative_rate >= 0.15:
            score += 1; reasons.append(f"负面率 {negative_rate:.0%}（≥15%）")
        if neg_wow is not None and neg_wow >= 50:
            score += 2; reasons.append(f"负面声量周环比 +{neg_wow:.0f}%（≥50%）")
        elif neg_wow is not None and neg_wow >= 20:
            score += 1; reasons.append(f"负面声量周环比 +{neg_wow:.0f}%（≥20%）")
        top_influence = top_complaints[0]["influence_score"] if top_complaints else 0
        if top_influence >= 100_000:
            score += 2; reasons.append(f"TOP 吐槽影响力分 {top_influence:,}（≥10万）")
        elif top_influence >= 20_000:
            score += 1; reasons.append(f"TOP 吐槽影响力分 {top_influence:,}（≥2万）")
        risk_level = "high" if score >= 4 else "medium" if score >= 2 else "low"
        if not reasons:
            reasons.append("三因子均未触发风险阈值")
        risk_reasons = reasons

    return {
        "negative_total": neg,
        "negative_rate": negative_rate,
        "negative_week": neg_week,
        "negative_prev_week": neg_prev_week,
        "negative_wow": neg_wow,
        "risk_level": risk_level,
        "risk_reasons": risk_reasons,
        "top_complaints": top_complaints,
        "negative_dims": negative_dims,
        "negative_events": negative_events,
    }


@router.get("/vehicles/{vehicle_id}/events")
async def get_event_timeline(
    vehicle_id: str,
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    source: str | None = Query(None),  # "social" or "news", None = both
    session: AsyncSession = Depends(get_session),
):
    q = select(EventGroup).where(EventGroup.vehicle_id == vehicle_id)
    if source:
        q = q.where(EventGroup.source == source)
    if start:
        q = q.where(EventGroup.end_date >= date.fromisoformat(start))
    if end:
        q = q.where(EventGroup.start_date <= date.fromisoformat(end))
    q = q.order_by(EventGroup.start_date.desc())
    result = await session.execute(q)
    events = result.scalars().all()
    return [
        {
            "id": e.id,
            "event_tag": e.event_tag,
            "source": e.source or "social",
            "start_date": str(e.start_date),
            "end_date": str(e.end_date),
            "post_count": e.post_count,
            "summary": e.summary,
            "sentiment_distribution": _safe_json_loads(e.sentiment_distribution),
        }
        for e in events
    ]


@router.get("/dim-sentiment/{vehicle_id}")
async def get_dim_sentiment(
    vehicle_id: str,
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
):
    """Aggregate dim_sentiment scores across all analyzed posts (SELF_ONLY).
    Returns [{dim, score, count}] sorted by score desc.
    """
    await _get_vehicle_or_404(vehicle_id, session)

    q = (
        select(AnalyzedPost.dim_sentiment)
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == vehicle_id, SELF_ONLY, AUTHENTIC_AUTHOR)
    )
    if start:
        q = q.where(RawPost.published_at >= datetime.fromisoformat(start))
    if end:
        q = q.where(RawPost.published_at < datetime.fromisoformat(end) + timedelta(days=1))
    result = await session.execute(q)

    dim_agg: dict[str, list[float]] = {}
    for (dim_json,) in result.all():
        dims = _safe_json_loads(dim_json)
        if not isinstance(dims, dict):
            continue
        for k, v in dims.items():
            if isinstance(v, (int, float)):
                dim_agg.setdefault(k, []).append(float(v))

    # 均分只算有倾向的提及（非零）：本地 ABSA 对隐含讽刺/假设句判保守，
    # 0 分=中性提及占 ~46%，计入只会把口碑分稀释向 0（2026-09-13 口径
    # 修正：模型保守是能力边界，改 prompt 治不了还引误判）；count 仍报
    # 全部提及数
    rows = [
        {
            "dim": k,
            "score": round(sum(nz) / len(nz), 3) if (nz := [v for v in vals if v != 0]) else 0.0,
            "count": len(vals),
        }
        for k, vals in dim_agg.items()
    ]
    rows.sort(key=lambda r: -r["score"])
    return rows


@router.get("/dim-examples/{vehicle_id}")
async def get_dim_examples(
    vehicle_id: str,
    dim: str = Query(..., min_length=1),
    sentiment: str | None = Query(None, pattern="^(positive|negative|neutral)$"),
    limit: int = Query(10, ge=1, le=50),
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"), end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
):
    """维度提及实例（帖+评论）——维度口碑图的证据链下钻，BI/Agent 共用。

    dim 为包含匹配（"续航" 命中 "续航里程"——15 维全集是全名，自然语言
    查询很少说全名）；实例带 matched_dim 标明实际命中的维度键。
    帖：按互动加权排序，可选按帖情感过滤；评论：本地 ABSA 分值方向匹配
    sentiment（negative→score<0 / positive→score>0 / 不传或 neutral→全部提及）。
    口径同 dim-sentiment：SELF_ONLY + 排除官方/经销商。
    """
    await _get_vehicle_or_404(vehicle_id, session)

    q = (
        select(
            AnalyzedPost.dim_sentiment, AnalyzedPost.sentiment,
            RawPost.title, RawPost.content, RawPost.platform, RawPost.url,
            RawPost.published_at, RawPost.likes, RawPost.comments, RawPost.shares,
            RawPost.author_type,
        )
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == vehicle_id, SELF_ONLY, AUTHENTIC_AUTHOR)
    )
    if sentiment:
        q = q.where(AnalyzedPost.sentiment == sentiment)
    if start:
        q = q.where(RawPost.published_at >= datetime.fromisoformat(start))
    if end:
        q = q.where(RawPost.published_at < datetime.fromisoformat(end) + timedelta(days=1))
    rows = (await session.execute(q)).all()

    def _hit(dims: dict) -> str | None:
        """第一个含 dim 子串且分值为数字的维度键（全名如 续航里程）。"""
        if not isinstance(dims, dict):
            return None
        return next((k for k in dims if dim in k and isinstance(dims[k], (int, float))), None)

    available: dict[str, int] = {}
    posts_out = []
    for (dim_json, ap_sent, title, content, platform, url, pub,
         likes, comments, shares, atype) in rows:
        dims = _safe_json_loads(dim_json)
        for k in dims if isinstance(dims, dict) else []:
            available[k] = available.get(k, 0) + 1
        key = _hit(dims)
        if key is not None:
            posts_out.append({
                "title": title or (content or "")[:40],
                "content": (content or "")[:120],
                "platform": platform, "url": url,
                "published_at": pub.isoformat() if pub else None,
                "sentiment": ap_sent,
                "matched_dim": key, "dim_score": dims[key],
                "likes": likes or 0, "comments": comments or 0, "shares": shares or 0,
                "author_type": atype or "organic",
            })
    posts_out.sort(key=lambda p: -(p["likes"] + p["comments"] * 5 + p["shares"] * 10))
    posts_out = posts_out[:limit]

    # 评论实例：全量取回 Python 过滤——dim JSON 存库为 \\uXXXX 转义形态，
    # SQL LIKE 中文匹配不可靠（实证 0 命中），且单车评论量级仅几千
    # §9.4: 评论查询挂口径（join RawPost + SELF_ONLY+AUTHENTIC_AUTHOR+RELEVANT_ONLY）
    comments = (await session.execute(
        select(PostComment)
        .join(RawPost, PostComment.post_id == RawPost.id)
        .outerjoin(AnalyzedPost, AnalyzedPost.post_id == RawPost.id)
        .where(RawPost.vehicle_id == vehicle_id, *LISTING_CALIBER)
    )).scalars().all()
    comments_out = []
    for c in comments:
        cd = _safe_json_loads(c.dim_sentiment) if c.dim_sentiment else {}
        key = _hit(cd)
        if key is None:
            continue
        score = cd[key]
        if sentiment == "negative" and score >= 0:
            continue
        if sentiment == "positive" and score <= 0:
            continue
        comments_out.append({
            "content": c.content, "author": c.author, "likes": c.likes or 0,
            "platform": c.platform,
            "published_at": c.published_at.isoformat() if c.published_at else None,
            "matched_dim": key, "dim_score": score,
        })
    comments_out.sort(key=lambda c: -c["likes"])

    return {"dim": dim, "sentiment": sentiment, "available_dims": available,
            "posts": posts_out, "comments": comments_out[:limit]}


@router.get("/post-comments/{vehicle_id}/{post_id}")
async def get_post_comments(
    vehicle_id: str,
    post_id: str,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """单帖评论列表（按点赞排序）——帖详情/Agent 引用原话的证据链。"""
    await _get_vehicle_or_404(vehicle_id, session)
    post = (await session.execute(
        select(RawPost).where(RawPost.id == post_id, RawPost.vehicle_id == vehicle_id)
    )).scalar_one_or_none()
    if not post:
        raise HTTPException(404, "Post not found")

    rows = (await session.execute(
        select(PostComment).where(PostComment.post_id == post_id)
        .order_by(func.coalesce(PostComment.likes, 0).desc())
        .limit(limit)
    )).scalars().all()

    return {
        "post": {
            "id": post.id, "title": post.title, "platform": post.platform,
            "url": post.url, "author": post.author,
            "author_type": post.author_type or "organic",
        },
        "comments": [{
            "author": c.author, "content": c.content, "likes": c.likes or 0,
            "platform": c.platform,
            "published_at": c.published_at.isoformat() if c.published_at else None,
            "dim_sentiment": _safe_json_loads(c.dim_sentiment) if c.dim_sentiment else {},
        } for c in rows],
    }


@router.get("/defect-themes/{vehicle_id}")
async def get_defect_themes(
    vehicle_id: str,
    start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    end: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    session: AsyncSession = Depends(get_session),
):
    """发酵层：缺陷话题簇（中低互动帖聚类，非热度榜）。

    全量评论共现聚类 + LLM 簇判定，捞吐槽榜漏掉的早期缺陷讨论。口径与
    negative-radar 一致（SELF_ONLY + AUTHENTIC_AUTHOR + RELEVANT_ONLY）。

    权威口径（2026-10-20 闭环改造）：统一 30 天窗（今天−29 ~ 今天），由
    夜间 Phase 8 批产；本端点 24h TTL 读库，过期/无行时按同一 30 天窗自愈
    重算落库。start/end 参数**保留签名但已退役**（原按用户窗重算，与管线
    90 天窗互踩导致每次切窗全量重算 + LLM 失败清空覆盖）。
    LLM 判定失败（degraded）：保留并返回旧载荷，不覆盖（无行才返回空）。
    """
    await _get_vehicle_or_404(vehicle_id, session)

    # 读最新 defect_themes 行（computed_at 降序取第一条）
    row = (await session.execute(
        select(DefectTheme)
        .where(DefectTheme.vehicle_id == vehicle_id)
        .order_by(DefectTheme.computed_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    # TTL 24h（单一窗口后无需比对 window_start/end）
    if row is not None and row.computed_at is not None:
        age = (datetime.utcnow() - row.computed_at).total_seconds()
        if age < 86400:
            return json.loads(row.payload)

    # 过期/无行：按 30 天权威窗自愈重算 + 落库
    from pipeline.analysis.defect_miner import mine_defect_themes  # noqa: inline-import
    d_end = date.today()
    d_start = d_end - timedelta(days=29)
    result, degraded = await mine_defect_themes(
        vehicle_id, session, start=d_start.isoformat(), end=d_end.isoformat())
    if degraded:
        # LLM 失败：保旧载荷（有行返回旧行，无行只能空——与旧行为区别是不写库）
        logger.warning("defect-themes recompute degraded for %s: serve stale payload", vehicle_id)
        if row is not None:
            return json.loads(row.payload)
        return []
    await session.execute(
        delete(DefectTheme).where(DefectTheme.vehicle_id == vehicle_id)
    )
    session.add(DefectTheme(
        id=str(uuid.uuid4()), vehicle_id=vehicle_id,
        window_start=d_start.isoformat(), window_end=d_end.isoformat(),
        payload=json.dumps(result),
    ))
    await session.commit()
    return result
