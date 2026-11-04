"""口碑洞察引擎核心（specs/koubei-insights v5）。

独立模块：读 owner_reviews/review_tags/series_summaries/exinfo，
被看板路由调用渲染。不修改 loop.py/chat_routes.py（架构红线）。
"""
from __future__ import annotations

import re
import statistics
from collections import defaultdict
from sqlalchemy import bindparam, text

from src.storage.db import session_scope
from src.models.orm import InsightCache, OwnerReview, ReviewTag, SeriesSummary
from src.insights.normalize_filter import filter_hash
from src.tools.reviews import _map_to_business_dim
from src.api.dashboard_data import parse_km


def _series_baseline(model_id: str) -> tuple[int, int]:
    """该系当前 owner_reviews / review_tags 行数（缓存基线比对用）。"""
    with session_scope() as s:
        rv = s.execute(text("SELECT COUNT(*) FROM owner_reviews WHERE model_id=:m"),
                       {"m": model_id}).scalar()
        rt = s.execute(text("SELECT COUNT(*) FROM review_tags WHERE model_id=:m"),
                       {"m": model_id}).scalar()
    return int(rv), int(rt)


def cache_save(model_id: str, filter_hash: str, filter_json: dict,
               summary: str, refs: list, n: int,
               llm_model: str = "deepseek-chat") -> None:
    """落库/更新一条 AI 总结缓存（upsert）。

    baseline 以 DB 当前实际行数为准（_series_baseline），不信任调用方传参——
    否则调用方传陈旧数值会使缓存永不被失效，破坏数据真实性硬底线。
    """
    rv, rt = _series_baseline(model_id)
    with session_scope() as s:
        existing = s.get(InsightCache, filter_hash)
        if existing:
            existing.model_id = model_id
            existing.filter_json = filter_json
            existing.summary_markdown = summary
            existing.review_refs = refs
            existing.n = n
            existing.llm_model = llm_model
            existing.baseline_reviews = rv
            existing.baseline_tags = rt
        else:
            s.add(InsightCache(filter_hash=filter_hash, model_id=model_id,
                               filter_json=filter_json, summary_markdown=summary,
                               review_refs=refs, n=n, llm_model=llm_model,
                               baseline_reviews=rv, baseline_tags=rt))


def cache_load(model_id: str, filter_hash: str) -> dict | None:
    """读缓存；基线行数与当前不一致返回 None（失效）。命中返回 dict，否则 None。

    先查缓存行，miss 直接返回 None（避免无效基线 COUNT 查询）；命中才比对基线。
    """
    with session_scope() as s:
        row = s.get(InsightCache, filter_hash)
        if row is None:
            return None
    rv, rt = _series_baseline(model_id)
    if row.baseline_reviews != rv or row.baseline_tags != rt:
        return None  # 业务数据变化 → 缓存失效
    return {
        "summary_markdown": row.summary_markdown,
        "review_refs": row.review_refs or [],
        "n": row.n,
        "llm_model": row.llm_model,
        "created_at": str(row.created_at) if row.created_at else "-",
    }


_INSIGHT_PROMPT = """你是一名汽车口碑分析师。仅基于下方给定的真实车主原话生成总结。

硬性规则：
1. 只能基于给定原话，不得使用任何训练知识或外部信息编造。
2. 每条结论必须附引文，格式"（引文：原话片段）"，片段须能在给定原话中找到。
3. 用 Markdown 输出，严格按以下三段结构：
## 整体印象
（1-2 句总体评价）
## 亮点
- 优点结论（引文：原话片段）
- ...
## 短板
- 缺点结论（引文：原话片段）
- ...
4. 若原话不足以支撑结论，输出"原话样本不足以总结"。

车主原话（共 {n} 条）：
{reviews}
"""


def _format_reviews_for_llm(reviews: list) -> str:
    parts = []
    for i, r in enumerate(reviews):
        best = (r.get("best") or "").strip()
        worst = (r.get("worst") or "").strip()
        parts.append(f"[{i+1}] review_id={r.get('review_id')}\n  最满意：{best}\n  最不满意：{worst}")
    return "\n\n".join(parts)


def _extract_refs(summary: str, reviews: list) -> list:
    """从总结里提取引文片段对应的 review_id + 来源 meta。

    扫总结里出现的原话片段：既匹配 best（最满意）也匹配 worst（最不满意），
    任一字段命中即记一条引文。设最小长度门槛（>=4）避免短词误命中。
    dashboard-v12 Task 1.2：refs 增强 field（pro=最满意/con=最不满意）+ 来源 meta
    （spec/city/post_date），供前端引文分组卡片渲染（pro/con 分组 + 来源标注）。
    """
    refs = []
    seen_rids = set()
    for r in reviews:
        rid = r.get("review_id")
        if rid in seen_rids:
            continue
        for field in ("best", "worst"):
            text = (r.get(field) or "").strip()
            if len(text) >= 4 and text[:8] in summary:
                refs.append({
                    "rid": rid,
                    "quote": text[:60],
                    "field": "pro" if field == "best" else "con",
                    "spec": r.get("spec_name") or "-",
                    "city": r.get("city") or "-",
                    "post_date": r.get("post_date") or "-",
                })
                seen_rids.add(rid)
                break
    return refs[:10]


_LLM_CLIENT = None

# 缓存键版本后缀：v9 起 AI 总结改三段式结构化输出（整体印象/亮点/短板）+ refs 增强
# field/spec/city/post_date（dashboard-v12 Task 1.2）。旧 v8 缓存（自由式总结 + 无 meta
# refs）结构不兼容，bump 后缀使旧缓存天然 miss。升级口径时 bump 此后缀即可整体失效旧缓存。
_CACHE_VERSION = "v9"


def _cache_key(fh: str) -> str:
    """给 filter_hash 加版本后缀，用于 InsightCache PK。"""
    return f"{fh}#{_CACHE_VERSION}"


def _get_llm_client():
    """模块级单例 LLM client（app 生命周期常驻，不每次新建/关闭，避免 httpx 泄漏）。"""
    global _LLM_CLIENT
    if _LLM_CLIENT is None:
        from src.nlp.llm_client import BaseLLMClient
        _LLM_CLIENT = BaseLLMClient()
    return _LLM_CLIENT


async def ai_summarize(model_id: str, filt: dict, reviews: list) -> dict:
    """AI 总结（specs/koubei-insights v5）。

    - n<5 只列原话不总结（status=only_reviews）
    - 按筛选指纹查缓存，命中且基线一致直接返回（不调 LLM）
    - 仅喂筛出原话、强制引文、prompt 约束
    - 完成后落缓存
    """
    n = len(reviews)
    fh = filter_hash(model_id, filt)
    if n < 5:
        return {"status": "only_reviews", "n": n, "refs": [], "summary": None}

    cached = cache_load(model_id, _cache_key(fh))
    if cached is not None:
        return {"status": "summary", "n": cached["n"], "summary": cached["summary_markdown"],
                "refs": cached["review_refs"], "cached": True,
                "created_at": cached["created_at"]}

    client = _get_llm_client()
    messages = [{"role": "user", "content": _INSIGHT_PROMPT.format(
        n=n, reviews=_format_reviews_for_llm(reviews))}]
    try:
        resp = await client.chat_nonstream(messages, max_tokens=1024, temperature=0)
        summary = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        return {"status": "error", "n": n, "error": str(e), "refs": [], "summary": None}

    # 空总结不缓存（数据真实性：避免空壳缓存诱导后续命中返回空结论）
    if not summary.strip():
        return {"status": "error", "n": n, "error": "LLM 返回空总结",
                "refs": [], "summary": None}

    refs = _extract_refs(summary, reviews)
    # 有总结但无可验证引文 → 不缓存，标记 insufficient_citations
    # （数据真实性硬底线：禁止"有总结、空引文"被缓存并诱导后续 LLM 编造）
    if not refs:
        return {"status": "insufficient_citations", "n": n, "summary": summary,
                "refs": [], "error": "总结无可验证引文"}

    # baseline 由 cache_save 内部 _series_baseline 取当前 DB 实际行数
    cache_save(model_id, _cache_key(fh), filt, summary, refs, n)
    return {"status": "summary", "n": n, "summary": summary, "refs": refs, "cached": False}


# ---------------------------------------------------------------------------
# A 层单车型诊断（specs/dashboards v5）：画像 / 趋势 / 交叉验证 / 竞品考虑集
# ---------------------------------------------------------------------------

_RANGE_FIELD = "春秋满电续航"
_COMPETITOR_RE = re.compile(r"(?:对比了|之前开|纠结过?|看过|之前的车)([一-龥A-Za-z0-9]{2,12})")
_RANGE_TOPIC_KW = ("续航", "虚标", "掉电")


def _peer_pool(level_name: str) -> list[tuple]:
    """同级池（同 level_name）所有车系行：(series_id, average_score, level_rank,
    level_series_count, cmp_scores)。

    画像卡 z-score（_peer_scores）与同级分位（peer_percentile）共用同一同级池口径
    与同一条查询（specs/dashboards v5），避免重复查询 SeriesSummary。
    """
    with session_scope() as s:
        return s.query(SeriesSummary.series_id, SeriesSummary.average_score,
                       SeriesSummary.level_rank, SeriesSummary.level_series_count,
                       SeriesSummary.cmp_scores).filter(
            SeriesSummary.level_name == level_name).all()


def _peer_scores(level_name: str) -> list[float]:
    """同级池（同 level_name）所有车系的 average_score（仅非空）。

    画像卡 z-score 与 peer_percentile 分位共用同一同级池口径（specs/dashboards v5）。
    """
    return [r[1] for r in _peer_pool(level_name) if r[1] is not None]


def diagnose(model_id: str, reviews: list | None = None) -> dict:
    """A 层单车型诊断（specs/dashboards v5）：画像/趋势/交叉验证/竞品考虑集。

    全部基于真实库内数据，不足返回 insufficient_data / not_collected。
    不调用 LLM、不返回写死的示例值。

    reviews：交叉透视筛选后的原话子集（cross_pivot["reviews"]）。传入时仅基于
    该子集计算 profile/trend/cross_validation/competitor_set，保证页面各处 n 一致
    （specs：三维交叉筛选联动）。None → 查全量（向后兼容旧调用）。
    """
    with session_scope() as s:
        # Gap 3：筛选联动——reviews 子集在 SQL 层过滤（避免取全量后 Python 过滤）
        if reviews is not None:
            allowed = {r.get("review_id") for r in reviews if r.get("review_id")}
        q = s.query(OwnerReview.review_id, OwnerReview.spec_name, OwnerReview.city,
                    OwnerReview.post_date, OwnerReview.best_review_text,
                    OwnerReview.worst_review_text, OwnerReview.exinfo,
                    OwnerReview.buy_price).filter(OwnerReview.model_id == model_id)
        if reviews is not None:
            # 空子集 → 1=0 不命中任何行（保持原行为：空子集落到下方 not_collected）
            q = q.filter(OwnerReview.review_id.in_(allowed)) if allowed else q.filter(text("1=0"))
        rows = q.all()
        if not rows:
            return {"not_collected": True, "model_id": model_id}
        rids = [r[0] for r in rows]
        tags = (s.query(ReviewTag.review_id, ReviewTag.sentiment, ReviewTag.tag_name,
                        ReviewTag.tag_category)
                .filter(ReviewTag.model_id == model_id,
                        ReviewTag.review_id.in_(rids)).all()
                if rids else [])
        summ = s.get(SeriesSummary, model_id)

    # 画像卡：情绪分布 + 标签结构 top 维度 + 同级均分 + z-score（同级池均值偏离）
    senti = {"pro": 0, "con": 0}
    dim_pro: dict[str, set] = defaultdict(set)
    dim_con: dict[str, set] = defaultdict(set)
    # 同时复用同一批 tag 行构建月度趋势：review_id → post_date[:7] 月份映射
    rid_to_month = {r[0]: (r[3] or "")[:7] for r in rows}
    months_list: dict[str, dict] = defaultdict(lambda: {"pro": 0, "con": 0})
    for rid, senti_val, tname, tcat in tags:
        biz_dim = _map_to_business_dim(tcat or "", tname or "")
        if senti_val == "pro":
            senti["pro"] += 1
            dim_pro[biz_dim].add(tname)
        elif senti_val == "con":
            senti["con"] += 1
            dim_con[biz_dim].add(tname)
        m = rid_to_month.get(rid)
        # P1#11：非 pro/con 情感（脏数据/未来新增中性档）不入月度趋势——
        # 原实现静默计入 con（虚增槽点）。senti 画像同理只认 pro/con。
        if m and senti_val in ("pro", "con") and re.fullmatch(r"\d{4}-\d{2}", m):
            months_list[m][senti_val] += 1
    top_dims = sorted(set(dim_pro) | set(dim_con),
                      key=lambda k: -(len(dim_pro.get(k, ())) + len(dim_con.get(k, ()))) )[:6]

    # z-score：target.average_score 相对同级池（同 level_name）均值的偏离
    z_score = peer_mean = peer_std = None
    peer_n = 0
    note = None
    if summ and summ.level_name:
        scores = _peer_scores(summ.level_name)
        peer_n = len(scores)
        if peer_n >= 2:
            peer_mean = statistics.mean(scores)
            peer_std = statistics.pstdev(scores)  # 总体标准差
            if summ.average_score is not None and peer_std > 0:
                z_score = (summ.average_score - peer_mean) / peer_std
            elif summ.average_score is None:
                note = "target 无均分"
            else:  # std == 0 → 全同级同分，z 无意义
                note = "insufficient peers"
        else:
            note = "insufficient peers"
    profile = {"sentiment": senti, "top_dims": top_dims,
               "avg_score": summ.average_score if summ else None,
               "z_score": round(z_score, 2) if z_score is not None else None,
               "peer_mean": round(peer_mean, 2) if peer_mean is not None else None,
               "peer_std": round(peer_std, 2) if peer_std is not None else None,
               "peer_n": peer_n}
    if note:
        profile["note"] = note

    months = [{"month": k, "pro": v["pro"], "con": v["con"]}
              for k, v in sorted(months_list.items())]
    # Gap 2：月度 con 比率 + 恶化/好转段标注
    for m in months:
        tot = m["pro"] + m["con"]
        m["con_ratio"] = round(m["con"] / tot, 3) if tot > 0 else None
    segments = _trend_segments(months)
    trend = {"months": months, "segments": segments}

    # 文本×数值交叉验证：扫 best/worst 两段原文定位续航话题 → exinfo 实测中位数
    range_vals = []
    for r in rows:
        exinfo = r[6] if isinstance(r[6], dict) else {}
        matched = any(
            any(kw in txt for kw in _RANGE_TOPIC_KW)
            for txt in (r[4] or "", r[5] or "")
        )
        if matched:
            v = parse_km(exinfo.get(_RANGE_FIELD))
            if v:
                range_vals.append(v)
    # Gap 4：官方标称续航未落库（R1，config-workshop-v5 范围）→ 降级标注，不编造
    official_comparison = {
        "status": "insufficient_data",
        "reason": "官方标称续航未落库（依赖 config-workshop-v5 快照表）"}
    if len(range_vals) >= 5:
        cross_validation = {"topic": "续航",
                            "median": round(statistics.median(range_vals), 1),
                            "n": len(range_vals), "unit": "km",
                            "official_comparison": official_comparison}
    else:
        cross_validation = {"topic": "续航",
                            "status": "insufficient_data", "n": len(range_vals),
                            "official_comparison": official_comparison}

    # 竞品考虑集：原文正则提取
    comp_counts: dict[str, int] = defaultdict(int)
    for r in rows:
        for txt in (r[4] or "", r[5] or ""):
            for m in _COMPETITOR_RE.finditer(txt):
                name = m.group(1).strip()
                if name and len(name) >= 2:
                    comp_counts[name] += 1
    competitor_set = {"items": [{"name": k, "cnt": v} for k, v in
                                sorted(comp_counts.items(), key=lambda x: -x[1])[:15]]}

    return {"model_id": model_id, "profile": profile, "trend": trend,
            "cross_validation": cross_validation, "competitor_set": competitor_set}


def _trend_segments(months: list[dict]) -> list[dict]:
    """月度趋势恶化/好转段标注（specs/dashboards v5）。

    在连续（con_ratio 非空）月份段内，若段首→段末 con_ratio 变化 >= +0.15 标"恶化"，
    <= -0.15 标"好转"；段长需 >= 2 个月。不足 3 个月或无符合段 → []。
    取极大连续段（避免碎片化重叠）。
    """
    segments: list[dict] = []
    ratios = [m.get("con_ratio") for m in months]
    i = 0
    while i < len(months):
        if ratios[i] is None:
            i += 1
            continue
        j = i
        while j + 1 < len(months) and ratios[j + 1] is not None:
            j += 1
        if j - i + 1 >= 2:
            delta = ratios[j] - ratios[i]
            if delta >= 0.15:
                segments.append({"type": "恶化", "start_month": months[i]["month"],
                                 "end_month": months[j]["month"], "delta": round(delta, 3)})
            elif delta <= -0.15:
                segments.append({"type": "好转", "start_month": months[i]["month"],
                                 "end_month": months[j]["month"], "delta": round(delta, 3)})
        i = j + 1
    return segments


# ---------------------------------------------------------------------------
# B 层同级分位（specs/dashboards v5）：同级池排位 + 官方字段直展
# ---------------------------------------------------------------------------

def _rank_in_pool(value: float, pool: list[float]) -> int:
    """value 在 pool 中的排名（1=最高，降序）。空池返回 0。"""
    if not pool:
        return 0
    sorted_pool = sorted(pool, reverse=True)
    rank = 0
    for i, v in enumerate(sorted_pool):
        if abs(v - value) < 1e-9:
            rank = i + 1
            break
    return rank or len(sorted_pool)


def peer_percentile(model_id: str) -> dict:
    """B 层同级分位（specs/dashboards v5）：所有比率带同级 N 系排第 N/总数。
    同级池按 level_name 圈定；白捡 level_rank/level_series_count/cmp_scores。"""
    with session_scope() as s:
        target = s.get(SeriesSummary, model_id)
        if target is None:
            return {"not_collected": True, "model_id": model_id}
        level = target.level_name
        if level is None:
            return {"insufficient_data": True, "reason": "no level_name",
                    "model_id": model_id}
        peers = _peer_pool(level)
        # 找出 target 的 top pro 标签（提及口碑数最多的正评标签），
        # 用于计算该具体标签的同级提及率分位（spec：标签提及率带同级分位）。
        top_tag_row = s.execute(text(
            "SELECT tag_name FROM review_tags "
            "WHERE model_id=:m AND sentiment='pro' "
            "GROUP BY tag_name ORDER BY COUNT(DISTINCT review_id) DESC LIMIT 1"),
            {"m": model_id}).first()
        top_tag = top_tag_row[0] if top_tag_row else None
        # 每系：口碑总数 + taggable（有正文可打标条数）+ top_tag 提及口碑数
        # P0-5：提及率分母改 taggable（有正文条数），不再用口碑总数——
        # 17% 无正文口碑不参与文本分析，旧分母会让提及率被稀释（虚低）。
        tag_counts: dict[str, tuple[int, int]] = {}
        peer_ids = [p[0] for p in peers]
        in_stmt = text(
            "SELECT model_id, COUNT(*) FROM owner_reviews WHERE model_id IN :ids "
            "GROUP BY model_id").bindparams(bindparam("ids", expanding=True))
        rv_rows = s.execute(in_stmt, {"ids": peer_ids}).fetchall()
        rv_map = {r[0]: int(r[1]) for r in rv_rows}
        # taggable（有正文）：与 _batch_tag_coverage / _tag_coverage_for_series 同口径
        # （2026-10-18 P1-4：补入 best/worst_full_text——老数据只有全文，此前提及率分母
        # 漏计它们，与打标分子口径错位可致提及率 >100%）
        tg_stmt = text(
            "SELECT model_id, COUNT(*) FROM owner_reviews WHERE model_id IN :ids "
            "AND ((best_review_text IS NOT NULL AND best_review_text != '') "
            "OR (worst_review_text IS NOT NULL AND worst_review_text != '') "
            "OR (best_full_text IS NOT NULL AND best_full_text != '') "
            "OR (worst_full_text IS NOT NULL AND worst_full_text != '')) "
            "GROUP BY model_id").bindparams(bindparam("ids", expanding=True))
        tg_rows = s.execute(tg_stmt, {"ids": peer_ids}).fetchall()
        tg_map = {r[0]: int(r[1]) for r in tg_rows}
        if top_tag:
            rt_stmt = text(
                "SELECT model_id, COUNT(DISTINCT review_id) FROM review_tags "
                "WHERE model_id IN :ids AND sentiment='pro' AND tag_name=:t "
                "GROUP BY model_id").bindparams(bindparam("ids", expanding=True))
            rt_rows = s.execute(rt_stmt, {"ids": peer_ids, "t": top_tag}).fetchall()
            rt_map = {r[0]: int(r[1]) for r in rt_rows}
        else:
            rt_map = {}
        for sid in peer_ids:
            # (提及数, taggable 分母)；taggable 缺失→0（该系全无正文，不入排名池）
            tag_counts[sid] = (rt_map.get(sid, 0), tg_map.get(sid, 0))

    peer_n = len(peers)
    metrics: dict = {}

    # 均分分位：排名池仅含有均分的同级系
    scores = [p[1] for p in peers if p[1] is not None]
    if target.average_score is not None and scores:
        rank = _rank_in_pool(target.average_score, scores)
        # P0#4 口径标注：pool_label 让消费方（看板/API）知道排名池是库内自算而非之家全量
        metrics["avg_score"] = {"value": target.average_score, "rank": rank,
                                "peer_n": len(scores),
                                "pool_label": f"库内 {len(scores)} 系"}

    # top 标签提及率分位：按 target 的 top pro 标签逐系计算提及率，
    # P0-5：分母=taggable（有正文可打标条数），与标签覆盖率同口径；
    # 排名池仅含有可分析口碑（taggable > 0）的同级系。无 top pro 标签则跳过。
    if top_tag is not None:
        rates = [tag_counts[p[0]][0] / tag_counts[p[0]][1]
                 for p in peers if tag_counts[p[0]][1] > 0]
        target_rate = (tag_counts[model_id][0] / tag_counts[model_id][1]
                       if tag_counts[model_id][1] > 0 else 0)
        if rates:
            rank = _rank_in_pool(target_rate, rates)
            metrics["top_tag_mention"] = {
                "tag": top_tag, "value": round(target_rate, 3),
                "rank": rank, "peer_n": len(rates),
                "denominator": "taggable"}

    official = {"level_rank": target.level_rank,
                "level_series_count": target.level_series_count,
                "cmp_scores": target.cmp_scores}
    return {"model_id": model_id, "peer_n": peer_n, "peer_level": level,
            "metrics": metrics, "official": official}
