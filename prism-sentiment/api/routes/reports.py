import json
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_session
from models.schemas import (AnalyzedPost, EventGroup, HeatMetric, PostComment,
                            RawPost, Report, Vehicle, AUTHENTIC_AUTHOR,
                            RELEVANT_ONLY, SELF_ONLY, LISTING_CALIBER)
from utils.llm_client import call_llm, LLMError
from utils.metrics import compute_health_score


class DeepReportRequest(BaseModel):
    vehicle_id: str
    start_date: str | None = None
    end_date: str | None = None


class WeeklyDigestRequest(BaseModel):
    vehicle_id: str
    start_date: str | None = None
    end_date: str | None = None


class DashboardSummaryRequest(BaseModel):
    vehicle_id: str
    start_date: str | None = None
    end_date: str | None = None


router = APIRouter(prefix="/api/reports", tags=["reports"])


async def _call_llm(prompt: str, timeout: int = 60) -> str:
    """薄包装：委托共享 utils.llm_client.call_llm（保留名以兼容 test patch 路径）。"""
    return await call_llm(prompt, timeout=timeout)


async def generate_deep_report_content(vehicle_name: str, start_date: str, end_date: str,
                                       sentiment_data: dict, event_data: list,
                                       dim_data: list) -> str:
    dim_text = json.dumps([{d["dim"]: d["score"]} for d in dim_data[:10]], ensure_ascii=False) if dim_data else "(无)"
    prompt = f"""你是汽车舆情分析师。请为以下车型生成一份深度舆情分析报告：

车型：{vehicle_name}
分析周期：{start_date} 至 {end_date}
情感分布：正面{sentiment_data.get('positive', 0)}，负面{sentiment_data.get('negative', 0)}，中性{sentiment_data.get('neutral', 0)}
主要事件：{json.dumps(event_data[:10], ensure_ascii=False)}
维度评分：{dim_text}

请按以下结构生成报告（800-1500字）：
一、车型概况
二、舆情总体分析
三、情感趋势分析
四、核心事件解读
五、用户观点洞察
六、策略建议"""

    # F-10：LLM 失败 raise LLMError，不再返回错误串当正文
    return await _call_llm(prompt, timeout=60)


async def generate_weekly_digest(
    session: AsyncSession,
    vehicle_id: str,
    start_date: str,
    end_date: str,
) -> str:
    vehicle = await session.get(Vehicle, vehicle_id)
    vehicle_name = vehicle.name if vehicle else "未知"

    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date) + timedelta(days=1)

    # Sentiment counts（口径 C3：published_at + LISTING_CALIBER，与看板/dim 口径一致）
    sent_result = await session.execute(
        select(AnalyzedPost.sentiment, func.count(AnalyzedPost.id))
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(
            AnalyzedPost.vehicle_id == vehicle_id,
            RawPost.published_at >= start_dt,
            RawPost.published_at < end_dt,
            *LISTING_CALIBER,
        )
        .group_by(AnalyzedPost.sentiment)
    )
    sent = {row[0]: row[1] for row in sent_result.all()}

    # Total posts（口径：排除无关帖）
    total_result = await session.execute(
        select(func.count(RawPost.id)).where(
            RawPost.vehicle_id == vehicle_id,
            RawPost.published_at >= start_dt,
            RawPost.published_at < end_dt,
            RELEVANT_ONLY,
        )
    )
    total = total_result.scalar() or 0

    # Top events（口径 C3：JOIN RawPost + published_at + LISTING_CALIBER，
    # 与 _compute_dim_sentiment 同口径，避免官方/竞品/无关帖污染事件标签）
    event_result = await session.execute(
        select(AnalyzedPost.event_tags)
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(
            AnalyzedPost.vehicle_id == vehicle_id,
            RawPost.published_at >= start_dt,
            RawPost.published_at < end_dt,
            *LISTING_CALIBER,
        )
    )
    tag_counter: dict[str, int] = {}
    for (tags_json,) in event_result.all():
        if tags_json:
            try:  # F-8：防坏 JSON
                for tag in json.loads(tags_json):
                    tag_counter[tag] = tag_counter.get(tag, 0) + 1
            except json.JSONDecodeError:
                continue
    top_events = sorted(tag_counter.items(), key=lambda x: -x[1])[:5]

    # Top posts（口径：排除无关帖——无关高热帖不得进周报内容）
    top_posts_result = await session.execute(
        select(RawPost.title).where(
            RawPost.vehicle_id == vehicle_id,
            RawPost.published_at >= start_dt,
            RawPost.published_at < end_dt,
            RawPost.platform != "news",
            RELEVANT_ONLY,
        ).order_by((RawPost.likes + RawPost.comments + RawPost.shares).desc()).limit(5)
    )
    top_titles = [row[0] for row in top_posts_result.all() if row[0]]

    prompt = f"""你是汽车舆情分析师。请为以下车型生成一份周报摘要（200-300字）：

车型：{vehicle_name}
周期：{start_date} 至 {end_date}
总帖子数：{total}
情感分布：正面{sent.get('positive', 0)}，负面{sent.get('negative', 0)}，中性{sent.get('neutral', 0)}
TOP事件：{json.dumps(dict(top_events), ensure_ascii=False)}

热门帖子：{json.dumps(top_titles, ensure_ascii=False)}

请简洁总结：本周舆情概况、情感变化、关键事件、下周关注点。用 Markdown 格式。"""

    return await _call_llm(prompt)


async def _compute_dim_sentiment(session: AsyncSession, vehicle_id: str,
                                start_dt: datetime | None = None,
                                end_dt: datetime | None = None):
    """Aggregate dim_sentiment scores across analyzed posts (SELF_ONLY).
    Optionally filtered by time range (joins RawPost.published_at).
    Returns [{dim, score, count}] sorted by score desc.
    """
    # 口径（2026-09-15 Q5）：排除官方/经销商作者帖，与看板 dim-sentiment 一致
    query = (
        select(AnalyzedPost.dim_sentiment)
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == vehicle_id, SELF_ONLY, AUTHENTIC_AUTHOR)
    )
    if start_dt is not None and end_dt is not None:
        query = query.where(
            RawPost.published_at >= start_dt,
            RawPost.published_at < end_dt,
        )

    result = await session.execute(query)
    dim_agg: dict[str, list[float]] = {}
    for (dim_json,) in result.all():
        try:
            dims = json.loads(dim_json) if dim_json else {}
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(dims, dict):
            continue
        for k, v in dims.items():
            if isinstance(v, (int, float)):
                dim_agg.setdefault(k, []).append(float(v))

    rows = [
        {"dim": k, "score": round(sum(v) / len(v), 3), "count": len(v)}
        for k, v in dim_agg.items()
    ]
    rows.sort(key=lambda r: -r["score"])
    return rows


@router.post("/deep-report")
async def create_deep_report(req: DeepReportRequest, session: AsyncSession = Depends(get_session)):
    vehicle = await session.get(Vehicle, req.vehicle_id)
    if not vehicle:
        raise HTTPException(404, detail="Vehicle not found")

    # 报告期独立（D15）：月报固定 30 天，不跟看板窗走——忽略前端传入的 start/end
    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=30)).isoformat()
    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date) + timedelta(days=1)

    # Sentiment distribution (SELF_ONLY, 时间窗按 published_at —— 与下方 dim 对齐口径)
    sent_result = await session.execute(
        select(AnalyzedPost.sentiment, func.count(AnalyzedPost.id))
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == req.vehicle_id, SELF_ONLY,
               RawPost.published_at >= start_dt, RawPost.published_at < end_dt)
        .group_by(AnalyzedPost.sentiment)
    )
    sentiment_data = {r[0]: r[1] for r in sent_result.all()}

    # Top events
    event_result = await session.execute(
        select(EventGroup).where(EventGroup.vehicle_id == req.vehicle_id)
        .order_by(EventGroup.post_count.desc()).limit(10)
    )
    event_data = [
        {"tag": e.event_tag, "count": e.post_count, "span": f"{e.start_date}~{e.end_date}"}
        for e in event_result.scalars().all()
    ]

    # Dimension scores (复用 _compute_dim_sentiment)
    dim_data = await _compute_dim_sentiment(session, req.vehicle_id, start_dt, end_dt)

    try:
        content = await generate_deep_report_content(
            vehicle_name=vehicle.name, start_date=start_date, end_date=end_date,
            sentiment_data=sentiment_data, event_data=event_data, dim_data=dim_data,
        )
    except LLMError as e:
        raise HTTPException(503, detail=f"报告生成失败（{e.kind}），请稍后重试")

    report = Report(
        id=str(uuid.uuid4()),
        vehicle_id=req.vehicle_id,
        type="deep_report",
        title=f"{vehicle.name} 深度报告 {start_date}~{end_date}",
        content=content,
        time_range_start=date.fromisoformat(start_date),
        time_range_end=date.fromisoformat(end_date),
    )
    session.add(report)
    await session.commit()

    return {
        "id": report.id, "vehicle_id": req.vehicle_id, "type": "deep_report",
        "title": report.title, "content": content,
        "time_range_start": start_date, "time_range_end": end_date,
    }


@router.post("/weekly-digest")
async def create_weekly_digest(req: WeeklyDigestRequest, session: AsyncSession = Depends(get_session)):
    vehicle = await session.get(Vehicle, req.vehicle_id)
    if not vehicle:
        raise HTTPException(404, detail="Vehicle not found")

    # 报告期独立（D15）：周报固定 7 天，不跟看板窗走——忽略前端传入的 start/end
    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=7)).isoformat()

    try:
        content = await generate_weekly_digest(session, req.vehicle_id, start_date, end_date)
    except LLMError as e:
        raise HTTPException(503, detail=f"周报生成失败（{e.kind}），请稍后重试")

    report = Report(
        id=str(uuid.uuid4()),
        vehicle_id=req.vehicle_id,
        type="weekly_digest",
        title=f"{vehicle.name} 周报 {start_date}~{end_date}",
        content=content,
        time_range_start=date.fromisoformat(start_date),
        time_range_end=date.fromisoformat(end_date),
    )
    session.add(report)
    await session.commit()

    return {
        "id": report.id, "vehicle_id": req.vehicle_id, "type": "weekly_digest",
        "title": report.title, "content": content,
        "time_range_start": start_date, "time_range_end": end_date,
    }


@router.post("/dashboard-summary")
async def create_dashboard_summary(
    req: DashboardSummaryRequest,
    session: AsyncSession = Depends(get_session),
):
    vehicle = await session.get(Vehicle, req.vehicle_id)
    if not vehicle:
        raise HTTPException(404, "Vehicle not found")

    today = date.today()
    start_date = req.start_date or (today - timedelta(days=30)).isoformat()
    end_date = req.end_date or today.isoformat()
    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date) + timedelta(days=1)

    # 1. Overall sentiment（口径：SELF_ONLY + AUTHENTIC_AUTHOR + 时间窗，与 /overview 一致）
    # #1 修复：原漏挂时间窗，用全量数据算健康分与看板不一致
    sent_result = await session.execute(
        select(AnalyzedPost.sentiment, func.count(AnalyzedPost.id))
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == req.vehicle_id, SELF_ONLY, AUTHENTIC_AUTHOR,
               func.coalesce(RawPost.published_at, RawPost.collected_at) >= start_dt,
               func.coalesce(RawPost.published_at, RawPost.collected_at) < end_dt)
        .group_by(AnalyzedPost.sentiment)
    )
    sent_counts = {r[0]: r[1] for r in sent_result.all()}
    total_analyzed = sum(sent_counts.values()) or 1
    pos_pct = round(sent_counts.get("positive", 0) / total_analyzed * 100, 1)
    neg_pct = round(sent_counts.get("negative", 0) / total_analyzed * 100, 1)
    total_posts = total_analyzed  # 保留变量名供 prompt 引用

    # 2. Health score（#1：统一调 compute_health_score 单一函数）
    health = compute_health_score(sent_counts.get("positive", 0), sent_counts.get("negative", 0), total_analyzed)

    # 3. Top dimensions
    dims = await _compute_dim_sentiment(session, req.vehicle_id, start_dt, end_dt)
    best_dim = dims[0] if dims else None
    worst_dim = dims[-1] if dims else None

    # 4. Top events
    events_result = await session.execute(
        select(EventGroup).where(EventGroup.vehicle_id == req.vehicle_id)
        .order_by(EventGroup.post_count.desc()).limit(5)
    )
    top_events = events_result.scalars().all()

    # 5. Recent top posts
    posts_result = await session.execute(
        select(RawPost.title, RawPost.platform, RawPost.likes, RawPost.comments, AnalyzedPost.sentiment)
        .join(AnalyzedPost, RawPost.id == AnalyzedPost.post_id)
        .where(RawPost.vehicle_id == req.vehicle_id, SELF_ONLY)
        .order_by((RawPost.likes + RawPost.comments + RawPost.shares).desc()).limit(5)
    )
    top_posts = posts_result.all()

    # 6. Comments per post（分母口径：排除无关帖）
    total_raw = (await session.execute(
        select(func.count(RawPost.id)).where(
            RawPost.vehicle_id == req.vehicle_id, RELEVANT_ONLY)
    )).scalar() or 1
    total_cmt = (await session.execute(
        select(func.count(PostComment.id)).where(PostComment.vehicle_id == req.vehicle_id)
    )).scalar() or 0

    # Build prompt
    events_text = "\n".join(
        f"- {e.event_tag}: {e.post_count}帖, {e.start_date}~{e.end_date}"
        for e in top_events
    )
    posts_text = "\n".join(
        f"- 「{p[0][:50] if p[0] else '(无标题)'}」{p[1]} {p[2] or 0}赞 {p[3] or 0}评 {p[4]}"
        for p in top_posts
    )
    dims_text = f"最强维度: {best_dim['dim']}({best_dim['score']})，最弱维度: {worst_dim['dim']}({worst_dim['score']})" if best_dim and worst_dim else ""

    prompt = f"""你是汽车行业舆情分析师。基于以下数据生成一份结构化舆情简报。

## 数据
- 车型: {vehicle.name}
- 周期: {start_date} 至 {end_date}
- 健康分: {health}/100 （50 + (正面数-负面数)/总量×50，60以上良好）
- 分析帖数: {total_posts}，正面{pos_pct}% 负面{neg_pct}% 中性{round(100-pos_pct-neg_pct,1)}%
- 帖均评论: {round(total_cmt/max(total_raw,1),1)}
- {dims_text}
- TOP事件: {events_text if events_text else '(无)'}

## 输出要求
按以下结构输出 Markdown，每段不超过150字：

### 1. 总体研判
一句话概括当前舆情态势（健康/警惕/风险），说明核心原因。

### 2. 维度亮点与短板
- 亮点：选1-2个最强维度，结合数据说明用户为什么满意
- 短板：选1-2个最弱维度，分析可能原因和影响

### 3. 事件信号
从TOP事件中识别1-2个值得关注的信号（正面或负面），说明为什么重要。

### 4. 行动建议
给品牌方2条具体可执行的建议，基于以上数据发现。

要求：用数据说话、避免套话、每条建议有依据。"""

    try:
        result = await _call_llm(prompt)
    except LLMError as e:
        raise HTTPException(503, detail=f"简报生成失败（{e.kind}），请稍后重试")

    report = Report(
        id=str(uuid.uuid4()),
        vehicle_id=req.vehicle_id,
        type="dashboard_summary",
        title=f"{vehicle.name} 舆情简报 {end_date}",
        content=result,
        time_range_start=date.fromisoformat(start_date),
        time_range_end=date.fromisoformat(end_date),
    )
    session.add(report)
    await session.commit()

    return {"id": report.id, "content": result}
