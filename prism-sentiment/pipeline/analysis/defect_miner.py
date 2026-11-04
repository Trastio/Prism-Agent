"""缺陷话题挖掘（发酵层数据源）——三分法看板第三层"话题发酵"组件。

与吐槽榜（高互动负面）互补：本模块捞中低互动帖的早期缺陷讨论。

四步管线（详见 openspec/changes/defect-theme-monitoring/design.md 第 3 节）：
1. ``_complaint_pool`` — 近 7 天素材口径全部帖的全部评论（口径三挂 +
   coalesce 时间窗），likes 降序上限 5000。
2. ``_cluster_complaints`` — jieba 切词 + 同评论内关键词共现边 + 连通分量
   成簇（不用 Louvain——缺陷关键词特异，连通分量足够且免调参）。簇准入
   comments ≥ 8 且 posts ≥ 2；score=评论数×(0.5+负面占比) top5。
3. ``_judge_defect_clusters`` — 一次 LLM 调用判定 is_defect/name/severity/
   suggestion（带车型锚）；失败或坏 JSON **raise DefectJudgeError**——上游
   据此保旧载荷，不再静默空覆盖（2026-10-20 闭环改造）。
4. ``mine_defect_themes`` — 编排 1-3，返回 ``(themes, degraded)``，供
   ``/defect-themes/{vehicle_id}`` 端点、collection.py Phase 8 与
   analysis.py /analysis/trigger 管线调用（三处同 30 天权威窗）。

方法论复用 ``event_tracker``（jieba/停用词/共现边/LLM 调用范式），但聚类
改用 ``networkx.connected_components``（缺陷关键词特异如「车道线/仪表盘」，
连通分量足够，免 Louvain 调参摆动）。
"""
import logging
from collections import defaultdict
from datetime import datetime, timedelta

import networkx as nx
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import (
    AnalyzedPost, PostComment, RawPost, Vehicle,
    AUTHENTIC_AUTHOR, RELEVANT_ONLY, SELF_ONLY,
)
from pipeline.analysis.event_tracker import extract_keywords
from utils.config import env_int
from utils.llm_client import call_llm
from utils.llm_helpers import extract_json_object

logger = logging.getLogger(__name__)


class DefectJudgeError(Exception):
    """LLM 簇判定失败（网络异常/坏 JSON）——调用方须保留旧载荷，不得空覆盖。

    2026-10-20 前此路径静默返回 []，"判定失败"与"合法空簇"不可区分，
    上游无条件覆盖把好载荷清空（T11 2026-10-19 15:48 三簇 → 19:47 零簇实证）。
    """

# ── Parameters ──────────────────────────────────────────────────────────────
# 均可用同名 env 覆盖（见 docs/配置参数.md）。模块级读取——import 时定型，
# 如需运行时调整请重启进程或在测试里 monkeypatch 模块属性。

_WINDOW_DAYS = env_int("DEFECT_WINDOW_DAYS", 7)          # 评论池时间窗（与素材层一致）
_MAX_COMMENTS = env_int("DEFECT_MAX_COMMENTS", 5000)      # 单车评论池上限（likes 降序截断保序）
_KEYWORD_TOP_K = 5        # 每评论/每簇关键词上限
_MIN_CLUSTER_COMMENTS = env_int("DEFECT_MIN_CLUSTER_COMMENTS", 8)  # 簇准入：评论数门槛（<8=噪音非话题）
_MIN_CLUSTER_POSTS = env_int("DEFECT_MIN_CLUSTER_POSTS", 2)        # 簇准入：跨帖门槛（单帖=孤帖非话题）
_TOP_K = 5                # 取 top K 簇送 LLM 判定

_JUDGE_PROMPT = """以下是 {n} 个社交媒体评论聚类（按共现关键词分组），请判断每个是否为"车辆缺陷话题"。本看板车型为 {vehicle_name}。

判断标准：簇内评论是否围绕 {vehicle_name} 某个具体的缺陷/故障/质量问题（如"刹车异响""续航虚标""车机死机"），而非泛泛吐槽或价格讨论。

{clusters_text}

只回复JSON，格式：
{{"clusters": [{{"idx": 0, "is_defect": true, "name": "缺陷名称(2-8字)", "severity": "high|mid|low", "suggestion": "一句话处置建议"}}]}}

要求：
- idx 与上方簇编号对应
- is_defect=false 的簇也输出（调用方会丢弃）
- severity: high=安全相关/大面积 / mid=常见抱怨 / low=个别案例
- name 用实义组合，禁止只用品牌名或车名
- ⚠ 簇内代表评论若主要讨论其他车型（对比推荐他车/吐槽他车的内容），is_defect=false——本看板只收 {vehicle_name} 的缺陷（车型锚，防跨车簇混入）"""


# ── 3.1 Complaint Pool ──────────────────────────────────────────────────────

async def _complaint_pool(session: AsyncSession, vehicle_id: str,
                          start: str | None = None, end: str | None = None) -> list[dict]:
    """近 7 天素材口径全部帖的全部评论（时间窗可由调用方覆盖）。

    口径三挂：RELEVANT_ONLY（analysis_status != irrelevant）+ SELF_ONLY
    （subject='self' 或 NULL）+ AUTHENTIC_AUTHOR（author_type 非
    brand_official/dealer）；时间窗用 coalesce(published_at, collected_at)
    兜 NULL（weibo/douyin published_at 常 NULL，直比会静默丢帖）。传 start/end
    时按用户窗（end 当天含），否则回退默认近 7 天。

    每条评论返回 {post_id, content, likes, post_sentiment}；post_sentiment
    来自 AnalyzedPost.sentiment 挂帖。批查防 N+1（先查口径内 post_id 集，
    再查 PostComment where post_id IN (...)）。likes 降序，上限 5000 截断保序。
    """
    if start and end:
        since = datetime.fromisoformat(start)
        until = datetime.fromisoformat(end) + timedelta(days=1)
    else:
        since = datetime.now() - timedelta(days=_WINDOW_DAYS)
        until = None  # 默认窗无上界（保持原行为——collected_at=now 的帖不应被 now<now 误排除）

    # 1. 口径内 post_id + 挂帖情感（批查，防 N+1）
    tw_conds = [func.coalesce(RawPost.published_at, RawPost.collected_at) >= since]
    if until is not None:
        tw_conds.append(func.coalesce(RawPost.published_at, RawPost.collected_at) < until)
    base = (
        select(AnalyzedPost.post_id, AnalyzedPost.sentiment)
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(
            AnalyzedPost.vehicle_id == vehicle_id,
            SELF_ONLY,
            AUTHENTIC_AUTHOR,
            RELEVANT_ONLY,
            *tw_conds,
        )
    )
    rows = (await session.execute(base)).all()
    post_sentiment = {pid: sent for pid, sent in rows}
    if not post_sentiment:
        return []

    # 2. 批量取这些帖的全部评论（likes 降序，上限 5000 截断保序）
    post_ids = list(post_sentiment.keys())
    cq = (
        select(PostComment.post_id, PostComment.content, PostComment.likes, RawPost.url, RawPost.title)
        .join(RawPost, PostComment.post_id == RawPost.id)
        .where(PostComment.post_id.in_(post_ids))
        .order_by(func.coalesce(PostComment.likes, 0).desc(), PostComment.id)
        .limit(_MAX_COMMENTS)
    )
    crows = (await session.execute(cq)).all()

    return [
        {
            "post_id": pid,
            "content": content or "",
            "likes": likes or 0,
            "post_sentiment": post_sentiment.get(pid, "neutral"),
            "post_url": url or "",
            "post_title": title or "",
        }
        for pid, content, likes, url, title in crows
    ]


# ── 3.2 Cluster Complaints ─────────────────────────────────────────────────

def _cluster_complaints(
    pool: list[dict],
    generic_names: set[str] | None = None,
) -> list[dict]:
    """评论关键词共现图 + 连通分量成簇。

    复用 event_tracker 方法论：jieba 切词（``extract_keywords``，含停用词 +
    车型名过滤）→ 同评论内关键词两两共现边 → ``networkx.connected_components``
    切簇（不用 Louvain）。

    每簇聚合：keywords（度数 top5）、comments（簇内评论数）、posts（去重帖
    id 集合）、neg_ratio（簇内评论来自 negative 帖的占比）。簇准入
    comments ≥ 8 且 posts ≥ 2；排序 score = comments × (0.5 + neg_ratio)，
    取 top K=5。
    """
    # 1. 每评论切词
    enriched: list[dict] = []
    for c in pool:
        kws = extract_keywords(
            c.get("content", ""), top_k=_KEYWORD_TOP_K, generic_names=generic_names,
        )
        if kws:  # 无关键词的评论不参与聚类
            enriched.append({**c, "keywords": kws})
    if not enriched:
        return []

    # 2. 共现图（复用 event_tracker.build_keyword_graph——塑形 topic_keywords 键）
    from pipeline.analysis.event_tracker import build_keyword_graph, detect_communities
    G = build_keyword_graph([{"topic_keywords": c["keywords"]} for c in enriched])

    # 3. Louvain 社区检测切簇（2026-09-29 U-2 治本：连通分量在泛词车退化
    # 成巨簇——"捂脸/官方/更新"等高频通用词当枢纽把不相关评论黏成一团。
    # Louvain 按模块度切社区，巨簇被拆成更聚焦的话题。复用 event_tracker
    # 的 detect_communities（带 greedy_modularity fallback + random_state 固定）。
    partition = detect_communities(G)
    if not partition:
        # 无社区（空图）→ 退连通分量兜底
        partition = {
            node: cid
            for cid, comp in enumerate(nx.connected_components(G))
            for node in comp
        }
    comp_of = partition

    # 4. 评论归簇——Louvain 可能拆开同评论的关键词团（code-review #2：
    #    连通分量的"同评论必同簇"不变量在 Louvain 下不成立）。改多数投票：
    #    统计评论所有关键词的社区，取出现最多的社区归簇。
    from collections import Counter
    buckets: dict[int, dict] = {}
    for c in enriched:
        cids = [comp_of.get(kw) for kw in c["keywords"] if comp_of.get(kw) is not None]
        if not cids:
            continue
        cid = Counter(cids).most_common(1)[0][0]  # 多数投票
        b = buckets.setdefault(cid, {
            "deg": defaultdict(int), "comments": [], "posts": set(),
            "neg": 0, "total": 0,
        })
        b["comments"].append(c)
        b["posts"].add(c["post_id"])
        b["total"] += 1
        if c.get("post_sentiment") == "negative":
            b["neg"] += 1
        for kw in c["keywords"]:
            b["deg"][kw] += 1

    # 5. 聚合 + 簇准入 + 排序
    # 门槛（code-review #6 修正：原 max(8,pool//30) 对大池升高反而抑制真簇。
    # Louvain+停用词已解决巨簇退化，门槛保持固定 8 不自适应）
    result: list[dict] = []
    for b in buckets.values():
        n_comments = b["total"]
        n_posts = len(b["posts"])
        if n_comments < _MIN_CLUSTER_COMMENTS or n_posts < _MIN_CLUSTER_POSTS:
            continue
        neg_ratio = b["neg"] / n_comments if n_comments else 0.0
        top_kw = sorted(b["deg"].items(), key=lambda kv: kv[1], reverse=True)[:_KEYWORD_TOP_K]
        keywords = [k for k, _ in top_kw]
        posts = sorted(b["posts"])
        # §9.5: rep_comments 优先取负面帖评论（缺陷代表评论应反映问题，非正面）
        # 排序：post_sentiment=negative 优先，其次 likes 高
        rep = sorted(b["comments"],
                     key=lambda c: (c.get("post_sentiment") != "negative", -c.get("likes", 0)))[:3]
        result.append({
            "keywords": keywords,
            "comments": n_comments,
            "posts": posts,
            "neg_ratio": round(neg_ratio, 4),
            "score": round(n_comments * (0.5 + neg_ratio), 4),
            "rep_comments": [
                {"content": r.get("content", ""), "likes": r.get("likes", 0),
                 "post_id": r["post_id"],
                 "post_url": r.get("post_url", ""),  # R3：查看原文链接
                 "post_title": r.get("post_title", "")}  # R3：原帖标题
                for r in rep
            ],
        })

    result.sort(key=lambda c: c["score"], reverse=True)
    return result[:_TOP_K]


# ── 3.3 LLM Judge ───────────────────────────────────────────────────────────

async def _judge_defect_clusters(clusters: list[dict], vehicle_name: str = "") -> list[dict]:
    """一次 LLM 调用判定 top-K 簇是否为缺陷话题（带车型锚，见 _JUDGE_PROMPT）。

    prompt 带 ≤5 簇的 keywords + 每簇 3 条代表评论（按 likes）。输出 JSON
    {"clusters": [{"idx", "is_defect", "name", "severity", "suggestion"}]}。
    is_defect=false 的簇丢弃。通过簇 → {name, severity, suggestion, comments,
    posts, neg_ratio, rep_comments, post_ids}。

    降级语义（2026-10-20 改）：LLM 失败或坏 JSON → raise DefectJudgeError
    （原静默返回空会把"失败"伪装成"无缺陷"，上游空覆盖好载荷）。
    合法空（聚类无合格簇）不经本函数，见 mine_defect_themes。
    """
    if not clusters:
        return []

    blocks = []
    for i, cl in enumerate(clusters):
        kws = "、".join(cl["keywords"][:_KEYWORD_TOP_K])
        reps = "\n".join(f"  - {c['content'][:80]}" for c in cl["rep_comments"][:3])
        blocks.append(f"【簇{i}】关键词：{kws}\n代表评论：\n{reps}")
    prompt = _JUDGE_PROMPT.format(
        n=len(clusters), vehicle_name=vehicle_name or "本车型",
        clusters_text="\n\n".join(blocks),
    )

    try:
        raw = await call_llm(prompt, timeout=30)
    except Exception as e:
        logger.warning("Defect judge LLM call raised: %s", e)
        raise DefectJudgeError(str(e)) from e

    data = extract_json_object(raw)
    if not data or not isinstance(data.get("clusters"), list):
        logger.warning("Defect judge returned bad JSON (raw head: %s)", raw[:120])
        raise DefectJudgeError(f"bad judge JSON: {raw[:120]!r}")

    judged = data["clusters"]
    result: list[dict] = []
    seen_idx: set[int] = set()
    _SEVERITY_MAP = {"high": "high", "mid": "mid", "low": "low",
                     "高": "high", "中": "mid", "低": "low"}
    for j in judged:
        if not isinstance(j, dict):
            continue
        idx = j.get("idx")
        if not isinstance(idx, int) or idx < 0 or idx >= len(clusters):
            continue  # 伪造/越界 idx 丢弃
        if idx in seen_idx:
            continue  # 重复 idx 去重（LLM 可能返回重复条目）
        # is_defect 严格布尔判定：LLM 可能返回字符串 "false"（bool("false")==True 会误留）
        v = j.get("is_defect")
        is_defect = v is True or (isinstance(v, str) and v.lower() == "true")
        if not is_defect:
            continue  # 非缺陷簇丢弃
        seen_idx.add(idx)
        base = clusters[idx]
        # severity 归一化：LLM 可能返回中文"高/中/低"，CSS 只认 high/mid/low
        sev = _SEVERITY_MAP.get(j.get("severity") or "", "mid")
        result.append({
            "name": j.get("name") or "、".join(base["keywords"][:3]) or "未命名缺陷",
            "severity": sev,
            "suggestion": j.get("suggestion") or "",
            "comments": base["comments"],
            "posts": base["posts"],
            "neg_ratio": base["neg_ratio"],
            "rep_comments": base["rep_comments"],
            "keywords": base["keywords"],
        })
    return result


# ── 3.4 Orchestration ──────────────────────────────────────────────────────

async def mine_defect_themes(vehicle_id: str, session: AsyncSession,
                             start: str | None = None, end: str | None = None
                             ) -> tuple[list[dict], bool]:
    """编排 3.1-3.3，返回 ``(缺陷簇列表, degraded)``。

    供 ``GET /defect-themes/{vehicle_id}`` 端点与 collection.py Phase 8 调用。
    start/end 透传 _complaint_pool（权威口径：调用方统一传 30 天窗）。

    返回语义（2026-10-20 闭环改造）：
    - ``([], False)``  = 合法空（池空/无合格簇/全被判定非缺陷）——正常落库；
    - ``([], True)``   = LLM 簇判定失败（DefectJudgeError）——**调用方须保留
      defect_themes 旧载荷，不得覆盖**（防清空覆盖，T11 实证路径）。
    """
    pool = await _complaint_pool(session, vehicle_id, start=start, end=end)
    logger.info("Defect mining pool: %d comments for %s", len(pool), vehicle_id)
    if not pool:
        return [], False

    # 当前车型名/品牌名加入停用词过滤（防车型名本身聚簇成"伪话题"）
    # 只查当前车型——本车名必滤；池内仍可能混入对比帖评论的他车名
    # （评论层无车型校验，2026-10-20 已知边界，judge 车型锚兜底）
    veh_row = (await session.execute(
        select(Vehicle.name, Vehicle.brand).where(Vehicle.id == vehicle_id)
    )).first()
    generic_names: set[str] = set()
    vehicle_name = ""
    if veh_row:
        name, brand = veh_row
        vehicle_name = name or ""
        if name:
            generic_names.add(name)
        if brand:
            generic_names.add(brand)

    clusters = _cluster_complaints(pool, generic_names=generic_names)
    logger.info("Defect mining clusters: %d qualified clusters from %d comments "
                "(threshold: comments>=%d, posts>=%d)",
                len(clusters), len(pool), _MIN_CLUSTER_COMMENTS, _MIN_CLUSTER_POSTS)
    if not clusters:
        return [], False

    try:
        judged = await _judge_defect_clusters(clusters, vehicle_name=vehicle_name)
    except DefectJudgeError:
        logger.warning("Defect mining degraded for %s: keep old payload", vehicle_id)
        return [], True
    logger.info("Defect mining judged: %d/%d clusters confirmed as defect themes",
                len(judged), len(clusters))
    return judged, False
