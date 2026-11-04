"""LLM-annotation + keyword co-occurrence graph + Louvain event detection.

Replaces the old Volume-first (event_tags + spike detection + DBSCAN) approach.
Pipeline:
1. LLM generates one-sentence topic per post (solves short/noisy text)
2. jieba extracts keywords from topic sentences
3. Build keyword co-occurrence graph
4. Louvain community detection → each community = a topic cluster
5. Time constraint: split clusters spanning >7 days into separate events
6. LLM generates event name + summary for each final event
"""

import asyncio
import httpx
import json
import logging
import re
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta

import jieba
import jieba.analyse
import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import (
    AnalyzedPost, EventGroup, RawPost, SELF_ONLY,
    INAUTHENTIC_AUTHOR_TYPES,
)
from utils.config import env_int
from utils.llm_helpers import extract_json_object

logger = logging.getLogger(__name__)

# ── Parameters ──────────────────────────────────────────────────────────────

_TOPIC_PROMPT = """以下是一条社交媒体帖子，请用一句话概括它讨论的核心话题。
如果帖子与汽车无关，请回复"无关"。
只输出概括句，不要解释。

帖子内容：{text}"""

_MAX_TOPIC_LEN = env_int("MAX_TOPIC_LEN", 50)        # max chars for topic sentence
_KEYWORD_TOP_K = 5         # top keywords to extract per topic
_KEYWORD_MIN_LEN = 2       # minimum keyword length in chars
_TIME_SPLIT_DAYS = env_int("TIME_SPLIT_DAYS", 7)     # split events spanning > this many days
_LLM_CONCURRENCY = 5       # max concurrent LLM requests
_MIN_EVENT_POSTS = env_int("MIN_EVENT_POSTS", 2)     # 丢弃 post_count < 此值的事件组（单帖组=噪音非事件）

# ── Stage 1: Topic Annotation ──────────────────────────────────────────────

def annotate_topic(text: str) -> str:
    """Generate a one-sentence topic description for a post.

    Sync heuristic version. The async version (annotate_topics_batch)
    calls the actual LLM API for better quality.
    """
    if not text or not text.strip():
        return ""

    # Clean noise: hashtags, emojis, mentions
    cleaned = re.sub(r'#[^\s#]+', '', text)            # remove #hashtags
    cleaned = re.sub(r'@\S+', '', cleaned)              # remove @mentions
    cleaned = re.sub(r'[\U00010000-\U0010ffff]', '', cleaned)  # remove emojis
    cleaned = cleaned.strip()

    if not cleaned:
        return ""

    return cleaned[:_MAX_TOPIC_LEN]


async def annotate_topics_batch(
    posts: list[dict],
    api_key: str,
    api_url: str,
    model: str = "glm-4-flash",
) -> list[str]:
    """Annotate a batch of posts with LLM-generated topic sentences.

    Uses concurrent requests (semaphore-limited) for throughput.
    Returns a list of topic strings, one per post.
    """
    sem = asyncio.Semaphore(_LLM_CONCURRENCY)
    results: list[str | None] = [None] * len(posts)

    async def _annotate_one(idx: int, post: dict) -> None:
        text = f"{post.get('title', '')} {post.get('content', '')}".strip()
        if not text:
            results[idx] = ""
            return
        async with sem:
            prompt = _TOPIC_PROMPT.format(text=text[:300])
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        api_url,
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.1,
                            "max_tokens": 60,
                        },
                    )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()
                if len(content) > _MAX_TOPIC_LEN:
                    content = content[:_MAX_TOPIC_LEN]
                results[idx] = content
            except Exception as e:
                logger.warning("Topic annotation failed for post %s: %s", post.get("id"), e)
                results[idx] = annotate_topic(text)

    await asyncio.gather(*[_annotate_one(i, p) for i, p in enumerate(posts)])

    # Replace any remaining None with fallback (shouldn't happen, but defensive)
    return [r if r is not None else "" for r in results]


# ── Stage 2: Keyword Extraction ────────────────────────────────────────────

# Stopwords to filter from keyword extraction
_STOPWORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有",
    "看", "好", "自己", "这", "他", "她", "它", "什么", "那", "就是", "可以",
    "这个", "那个", "还是", "但是", "因为", "所以", "如果", "虽然", "已经",
    "一下", "一些", "应该", "可能", "不过", "而且", "然后", "或者", "比较",
    "真的", "怎么", "这么", "那么", "其实", "感觉", "觉得",
    # Generic car terms that appear everywhere (low discriminative power)
    "车", "汽车", "新能源", "电动车", "这个车", "那种",
    # Emoji 文字 + 平台词 + 高频通用词（2026-09-29 U-2 治本：审查实证这些
    # 词当共现图枢纽节点，把不相关评论黏成巨簇——捂脸/官方/更新/分钟/高亮）
    "捂脸", "偷笑", "点赞", "关注", "转发", "收藏", "评论", "视频", "直播",
    "官方", "更新", "分钟", "高亮", "首页", "推荐", "热门", "话题",
    "知道", "问题", "时候", "现在", "今天", "昨天", "终于", "时间",
}

# Brand/model names that appear in almost every post (low discriminative power).
# Defaults are extended at runtime with vehicle names from DB (see _build_generic_names).
_DEFAULT_GENERIC_NAMES = {
    "比亚迪", "元PLUS", "海豚", "银河E5", "吉利",
}


def _build_generic_names(extra_names: set[str] | None = None) -> set[str]:
    """Merge static defaults with runtime vehicle names from DB."""
    names = set(_DEFAULT_GENERIC_NAMES)
    if extra_names:
        names.update(extra_names)
    return names


def extract_keywords(text: str, top_k: int = _KEYWORD_TOP_K,
                     generic_names: set[str] | None = None) -> list[str]:
    """Extract discriminative keywords from text using TF-IDF via jieba.

    Filters stopwords, generic brand names, and short tokens.
    """
    if not text or not text.strip():
        return []

    generic = _build_generic_names(generic_names)

    keywords = jieba.analyse.extract_tags(
        text,
        topK=top_k * 2,  # extract extra, filter later
        withWeight=False,
    )

    filtered = []
    for kw in keywords:
        if len(kw) < _KEYWORD_MIN_LEN:
            continue
        if kw in _STOPWORDS:
            continue
        if kw in generic:
            continue
        filtered.append(kw)

    return filtered[:top_k]


# ── Stage 3: Keyword Co-occurrence Graph ────────────────────────────────────

def build_keyword_graph(posts: list[dict]) -> nx.Graph:
    """Build a keyword co-occurrence graph from posts.

    Each post's keywords are fully connected (complete subgraph).
    Edge weight = sum over posts of post_weight, where news posts contribute
    _NEWS_EDGE_WEIGHT (soft anchor) and others 1.
    """
    G = nx.Graph()

    for post in posts:
        keywords = post.get("topic_keywords", [])
        if not keywords:
            continue
        w = 1  # all posts equal weight — social and news events are separate pipelines

        for kw in keywords:
            if not G.has_node(kw):
                G.add_node(kw)

        for i in range(len(keywords)):
            for j in range(i + 1, len(keywords)):
                kw_a, kw_b = keywords[i], keywords[j]
                if G.has_edge(kw_a, kw_b):
                    G[kw_a][kw_b]["weight"] += w
                else:
                    G.add_edge(kw_a, kw_b, weight=w)

    return G


# ── Stage 4: Louvain Community Detection ────────────────────────────────────

def detect_communities(G: nx.Graph) -> dict[str, int]:
    """Detect keyword communities using Louvain algorithm.

    random_state 固定（2026-09-13 实测：不固定时同图 5 次分区结果有摆动，
    事件每轮全量重建会随机抖动；固定后 3 次完全一致）。

    Returns:
        dict mapping keyword → community_id
    """
    if G.number_of_nodes() == 0:
        return {}

    try:
        import community as community_louvain
        partition = community_louvain.best_partition(
            G, weight="weight", random_state=42)
        return partition
    except ImportError:
        from networkx.algorithms.community import greedy_modularity_communities
        communities = greedy_modularity_communities(G, weight="weight")
        partition = {}
        for i, comm in enumerate(communities):
            for node in comm:
                partition[node] = i
        return partition


# ── Stage 5: Time-based Split ──────────────────────────────────────────────

def _get_post_date(post: dict) -> date | None:
    """Extract date from a post dict."""
    pub = post.get("published_at")
    if pub is None:
        return None
    if isinstance(pub, datetime):
        return pub.date()
    if isinstance(pub, date):
        return pub
    if isinstance(pub, str):
        # ISO 字符串（同步入口/测试传字符串时曾静默回退 today——2026-09-13 修）
        try:
            return datetime.fromisoformat(pub).date()
        except ValueError:
            return None
    return None


def split_community_by_time(
    posts: list[dict],
    max_gap_days: int = _TIME_SPLIT_DAYS,
) -> list[list[dict]]:
    """Split posts in a community into sub-groups by temporal gaps.

    Posts are sorted by published_at. When two consecutive posts are more
    than max_gap_days apart, they are split into separate groups.
    """
    if not posts:
        return []

    # §9.4: NULL 日期帖子不参与事件检测（事件基于时间序列，无时间无法分组成事件）
    posts_with_date = [p for p in posts if _get_post_date(p) is not None]
    if not posts_with_date:
        return []
    sorted_posts = sorted(posts_with_date, key=lambda p: _get_post_date(p))

    groups: list[list[dict]] = [[sorted_posts[0]]]
    for post in sorted_posts[1:]:
        prev_date = _get_post_date(groups[-1][-1])
        curr_date = _get_post_date(post)
        gap = abs((curr_date - prev_date).days)
        if gap > max_gap_days:
            groups.append([post])
        else:
            groups[-1].append(post)

    return groups


# ── Stage 6: Event Assembly ─────────────────────────────────────────────────

def assemble_events(
    posts: list[dict],
    keyword_partition: dict[str, int],
    max_gap_days: int = _TIME_SPLIT_DAYS,
) -> list[dict]:
    """Assemble events from posts using community partition + time splitting.

    Returns list of event dicts with: post_ids (RawPost.id 的 JSON 数组,
    优先 p["post_id"]，缺失时退回 p["id"]), start_date, end_date,
    keywords, post_count, sentiment_distribution.
    """
    if not posts or not keyword_partition:
        return []

    # Assign each post to a community based on its keywords (majority vote)
    post_communities: dict[int, list[dict]] = defaultdict(list)
    for post in posts:
        keywords = post.get("topic_keywords", [])
        if not keywords:
            continue
        comm_counts: dict[int, int] = defaultdict(int)
        for kw in keywords:
            if kw in keyword_partition:
                comm_counts[keyword_partition[kw]] += 1
        if comm_counts:
            best_comm = max(comm_counts, key=comm_counts.get)
            post_communities[best_comm].append(post)

    # Split each community by time
    events = []
    for comm_id, comm_posts in post_communities.items():
        time_groups = split_community_by_time(comm_posts, max_gap_days)
        for group in time_groups:
            if not group:
                continue
            dates = [_get_post_date(p) for p in group if _get_post_date(p)]
            sentiments = {"positive": 0, "negative": 0, "neutral": 0}
            for p in group:
                s = p.get("sentiment", "neutral")
                if s in sentiments:
                    sentiments[s] += 1

            event_keywords = set()
            for p in group:
                for kw in p.get("topic_keywords", []):
                    event_keywords.add(kw)

            events.append({
                "post_ids": json.dumps([p.get("post_id") or p.get("id") for p in group]),
                "post_count": len(group),
                "start_date": min(dates) if dates else date.today(),
                "end_date": max(dates) if dates else date.today(),
                "keywords": sorted(event_keywords),
                "sentiment_distribution": json.dumps(sentiments),
                "summary": "",
            })

    # 丢弃单帖组（噪音非事件，碎片化主因之一）
    events = [e for e in events if e.get("post_count", 0) >= _MIN_EVENT_POSTS]
    return events


# 同名切片合并间隔：LLM 命名后同话题被时间切片（_TIME_SPLIT_DAYS）拆成
# 多行，间隔 ≤ _MERGE_GAP_DAYS 的相邻切片合并成一行，防事件时间线碎片化。
# Phase 2 §9.4：原切分 7 天 + 合并 14 天互相抵消（净 14 天，切分形同虚设），
# 决策统一为 7 天（切=并），合并间隔 ≤ 切分阈值。
_MERGE_GAP_DAYS = env_int("MERGE_GAP_DAYS", 7)
# §9.5：合并后总跨度上限——同名切片合并后若超过此值视为撞名不同事件，不合并。
_MAX_MERGED_SPAN_DAYS = env_int("MAX_MERGED_SPAN_DAYS", 30)


def _absorb_slice(target: dict, other: dict) -> None:
    """把 other 切片并入 target（post_ids 并集、区间扩展、情感累加）。"""
    ids = json.loads(target["post_ids"]) + json.loads(other["post_ids"])
    target["post_ids"] = json.dumps(ids)
    target["post_count"] = len(ids)
    target["start_date"] = min(target["start_date"], other["start_date"])
    target["end_date"] = max(target["end_date"], other["end_date"])
    t = json.loads(target["sentiment_distribution"])
    o = json.loads(other["sentiment_distribution"])
    for k in t:
        t[k] = t.get(k, 0) + o.get(k, 0)
    target["sentiment_distribution"] = json.dumps(t)
    # summary 保留 target（首个切片）的命名摘要


def merge_adjacent_slices(events: list[dict],
                          max_gap_days: int = _MERGE_GAP_DAYS) -> list[dict]:
    """同名（event_tag）相邻时间切片合并。"其他"桶不参与（语义混杂）。

    Phase 2 §9.5：合并判据加"合并后跨度上限"——同名切片合并后若总跨度超过
    _MAX_MERGED_SPAN_DAYS（默认 30 天），视为撞名不同事件，不合并。防两次
    召回/同词簇等撞名事件被回并导致时间线被拉长。
    """
    by_tag: dict[str, list[dict]] = defaultdict(list)
    others: list[dict] = []
    for e in events:
        tag = str(e.get("event_tag") or "").strip()
        if tag and tag != "其他":
            by_tag[tag].append(e)
        else:
            others.append(e)
    merged: list[dict] = []
    for group in by_tag.values():
        group.sort(key=lambda e: e["start_date"])
        current: dict | None = None
        for e in group:
            if current is not None and \
                    (e["start_date"] - current["end_date"]).days <= max_gap_days and \
                    (e["end_date"] - current["start_date"]).days <= _MAX_MERGED_SPAN_DAYS:
                _absorb_slice(current, e)
                continue
            if current is not None:
                merged.append(current)
            current = e
        if current is not None:
            merged.append(current)
    merged.extend(others)
    merged.sort(key=lambda e: e["start_date"])
    return merged


# ── Stage 7: LLM Event Naming ───────────────────────────────────────────────

_EVENT_NAMING_PROMPT = """以下是一组讨论同一话题的社交媒体帖子摘要：
{posts_text}

请为这个事件/话题起一个简短名称（2-8个字），并写一句话摘要。
命名要求：用"主题+事件/现象"的实义组合（如"续航虚标争议""提车等待周期长"）；
禁止颜色/光影/氛围等风格词（如"紫""日落光影"）；禁止只用品牌名或车名单独作名。
如果帖子内容与汽车无关或无意义，名称填"其他"。

只回复JSON：{{"name": "事件名称", "summary": "一句话摘要"}}"""


def name_events_sync(events: list[dict]) -> list[dict]:
    """Sync fallback for event naming — uses keyword-based naming."""
    for event in events:
        keywords = event.get("keywords", [])
        if keywords:
            event["event_tag"] = keywords[0]
            event["summary"] = f"涉及{len(keywords)}个关键词的讨论"
        else:
            event["event_tag"] = "其他"
            event["summary"] = ""
    return events


async def name_events_async(
    events: list[dict],
    api_key: str,
    api_url: str,
    model: str = "glm-4-flash",
) -> list[dict]:
    """Name events using LLM concurrently. Modifies events in-place and returns them."""
    sem = asyncio.Semaphore(_LLM_CONCURRENCY)

    async def _name_one(event: dict) -> None:
        posts_text = "\n".join(f"- {p}" for p in event.get("representative_posts", []))
        if not posts_text:
            posts_text = "无帖子内容"
        async with sem:
            prompt = _EVENT_NAMING_PROMPT.format(posts_text=posts_text)
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.post(
                        api_url,
                        headers={"Authorization": f"Bearer {api_key}"},
                        json={
                            "model": model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.1,
                            "max_tokens": 80,
                        },
                    )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()
                data = extract_json_object(content)
                if data:
                    event["event_tag"] = data.get("name", event.get("keywords", ["其他"])[0])
                    event["summary"] = data.get("summary", "")
                else:
                    keywords = event.get("keywords", [])
                    event["event_tag"] = keywords[0] if keywords else "其他"
            except Exception as e:
                logger.warning("Event naming failed: %s", e)
                keywords = event.get("keywords", [])
                event["event_tag"] = keywords[0] if keywords else "其他"

    await asyncio.gather(*[_name_one(ev) for ev in events])
    return events


# ── DB Integration ───────────────────────────────────────────────────────────

async def detect_events_for_vehicle(vehicle_id: str, session: AsyncSession, source: str = "social"):
    """Full event detection pipeline for a vehicle.

    1. Load analyzed posts from DB (filtered by source: social/news)
    2. Annotate topics with LLM
    3. Extract keywords (with dynamic vehicle-name filtering)
    4. Build co-occurrence graph
    5. Detect communities
    6. Split by time
    7. Name events with LLM
    8. Store EventGroups in DB
    """
    from utils.config import load_api_config
    config = load_api_config()
    glm_cfg = config.get("glm", {})
    api_key = glm_cfg.get("api_key", "")
    api_url = glm_cfg.get("base_url", "https://open.bigmodel.cn/api/paas/v4") + "/chat/completions"
    model = glm_cfg.get("model", "glm-4-flash")

    # Load all vehicle names for dynamic generic-name filtering
    from models.schemas import Vehicle
    veh_rows = (await session.execute(select(Vehicle.name, Vehicle.brand))).all()
    generic_names: set[str] = set()
    for name, brand in veh_rows:
        if name:
            generic_names.add(name)
        if brand:
            generic_names.add(brand)

    # Load analyzed posts with raw post dates
    # 只用主车型帖（subject='self'）；NULL 视为 self 兼容老数据/未回填
    result = await session.execute(
        select(AnalyzedPost).where(
            AnalyzedPost.vehicle_id == vehicle_id,
            SELF_ONLY,
        )
    )
    analyzed = result.scalars().all()
    if not analyzed:
        return []

    # Load raw posts for published_at, title, content, engagement + 口径字段
    post_ids = [ap.post_id for ap in analyzed]
    raw_result = await session.execute(
        select(RawPost.id, RawPost.published_at, RawPost.title, RawPost.content,
               RawPost.likes, RawPost.comments, RawPost.platform,
               RawPost.author_type, RawPost.analysis_status).where(
            RawPost.id.in_(post_ids)
        )
    )
    raw_data = {
        r[0]: {"published_at": r[1], "title": r[2], "content": r[3],
               "likes": r[4], "comments": r[5], "platform": r[6],
               "author_type": r[7], "analysis_status": r[8]}
        for r in raw_result.all()
    }

    # Build post dicts — filter by source + 口径（C1：排除官方/经销商/无关帖）
    # irrelevant 帖无 AnalyzedPost 行（结构性排除），此处对 author_type 防御性
    # 双保险——官方/经销商帖不进事件聚类与 sentiment_distribution。
    post_dicts = []
    for ap in analyzed:
        raw = raw_data.get(ap.post_id)
        atype = raw["author_type"] if raw else None
        astatus = raw["analysis_status"] if raw else None
        if atype in INAUTHENTIC_AUTHOR_TYPES:
            continue
        if astatus == "irrelevant":
            continue
        platform = raw["platform"] if raw else ""
        # Filter: social excludes news, news includes only news
        if source == "social" and platform == "news":
            continue
        if source == "news" and platform != "news":
            continue
        post_dicts.append({
            "id": ap.id,
            "post_id": ap.post_id,
            "title": (raw["title"] if raw else "") or "",
            "content": ((raw["content"] if raw else "") or "")[:200],
            "sentiment": ap.sentiment,
            "published_at": raw["published_at"] if raw else None,
            "likes": raw["likes"] if raw else 0,
            "comments_count": raw["comments"] if raw else 0,
            "platform": raw["platform"] if raw else "",
        })

    # Stage 1: Annotate topics
    if api_key:
        topics = await annotate_topics_batch(post_dicts, api_key, api_url, model)
    else:
        topics = [annotate_topic(f"{p['title']} {p['content']}") for p in post_dicts]

    for post, topic in zip(post_dicts, topics):
        post["topic"] = topic

    # Stage 2: Extract keywords (with dynamic vehicle-name filtering)
    for post in post_dicts:
        text = post.get("topic", f"{post['title']} {post['content']}")
        post["topic_keywords"] = extract_keywords(text, generic_names=generic_names)

    # Filter out posts with no keywords
    posts_with_kw = [p for p in post_dicts if p.get("topic_keywords")]

    if not posts_with_kw:
        logger.info("No posts with keywords for vehicle %s", vehicle_id)
        return []

    # Stage 3-4: Build graph + detect communities
    G = build_keyword_graph(posts_with_kw)
    partition = detect_communities(G)

    # Stage 5-6: Assemble events
    events = assemble_events(posts_with_kw, partition)

    if not events:
        return []

    # Enrich with representative posts for naming
    post_by_id = {p["post_id"]: p for p in post_dicts}
    for event in events:
        pids = json.loads(event["post_ids"])
        event_posts = sorted(
            [post_by_id[pid] for pid in pids if pid in post_by_id],
            key=lambda p: p.get("likes", 0), reverse=True,
        )
        event["representative_posts"] = [
            f"{p.get('title', '')} {p.get('content', '')}"[:80]
            for p in event_posts[:3]
        ]

    # Stage 7: Name events
    if api_key:
        events = await name_events_async(events, api_key, api_url, model)
    else:
        events = name_events_sync(events)

    # Stage 7.5: 同名相邻切片合并（命名后才知道哪些切片是同一话题）
    events = merge_adjacent_slices(events)

    # Stage 8: Store in DB
    existing = await session.execute(
        select(EventGroup).where(
            EventGroup.vehicle_id == vehicle_id,
            EventGroup.source == source,
        )
    )
    for eg in existing.scalars().all():
        await session.delete(eg)

    for event in events:
        session.add(EventGroup(
            id=str(uuid.uuid4()),
            vehicle_id=vehicle_id,
            event_tag=event.get("event_tag", "其他"),
            start_date=event["start_date"],
            end_date=event["end_date"],
            post_count=event["post_count"],
            source=source,
            post_ids=event["post_ids"],
            summary=event.get("summary", ""),
            sentiment_distribution=event.get("sentiment_distribution", "{}"),
        ))

    await session.commit()
    logger.info("Detected %d events for vehicle %s", len(events), vehicle_id)
    return events


# ── Sync entry point for testing ────────────────────────────────────────────

def detect_events_from_posts(posts: list[dict]) -> list[dict]:
    """Sync version for testing — keyword-based pipeline without LLM."""
    for post in posts:
        text = f"{post.get('title', '')} {post.get('content', '')}"
        post["topic"] = annotate_topic(text)
        post["topic_keywords"] = extract_keywords(post["topic"])

    posts_with_kw = [p for p in posts if p.get("topic_keywords")]
    if not posts_with_kw:
        return []

    G = build_keyword_graph(posts_with_kw)
    partition = detect_communities(G)
    events = assemble_events(posts_with_kw, partition)
    return name_events_sync(events)
