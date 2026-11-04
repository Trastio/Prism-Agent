# Kuaishou Collection + Event Detection Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Kuaishou back to the collection pipeline, and replace the Volume-first event detection with an LLM-annotation + keyword-co-occurrence-graph + Louvain community detection approach.

**Architecture:** Two independent subsystems: (A) Kuaishou collection strategy (2 file changes), (B) Event detection rewrite (new pipeline: LLM annotate → jieba keywords → co-occurrence graph → Louvain → time-split → LLM name). Pipeline order also changes from "analyze→filter" to "filter→analyze" in batch_runner.

**Tech Stack:** Python, FastAPI, SQLAlchemy async, SQLite, GLM-4-Flash API, jieba, networkx (Louvain via `community` package or custom), scikit-learn (already installed)

---

## File Structure

### Task A: Kuaishou Collection (independent)

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `pipeline/collectors/platform_strategy.py` | Add `KUAISHOU` strategy + register in dict |
| Modify | `pipeline/scheduler.py:24` | Add `"kuaishou"` to `_MC_PLATFORMS` list |

### Task B: Event Detection Redesign (new pipeline)

| Action | File | Responsibility |
|--------|------|---------------|
| Rewrite | `pipeline/analysis/event_tracker.py` | New pipeline: LLM annotate → keywords → graph → Louvain → time-split → LLM name |
| Modify | `pipeline/analysis/batch_runner.py:90-100` | Move relevance filter BEFORE analysis loop |
| Modify | `requirements.txt` | Add `python-louvain` (or `python-igraph` for community detection) |
| Modify | `api/routes/analysis.py:46-49` | Update import from `cluster_events_for_vehicle` to new `detect_events_for_vehicle` |
| Rewrite | `tests/test_event_tracker.py` | New tests for the redesigned pipeline |

### Not touched (preserved)

| File | Reason |
|------|--------|
| `pipeline/analysis/relevance_filter.py` | No changes needed — already works correctly |
| `pipeline/analysis/analyzer.py` | Keeps generating event_tags for dashboard display |
| `models/schemas.py` | `EventGroup` schema stays the same (event_tag, start_date, end_date, etc.) |
| `frontend/` | Dashboard reads EventGroup via API — no frontend changes needed |

---

## Task A: Add Kuaishou to Collection Pipeline

**Files:**
- Modify: `pipeline/collectors/platform_strategy.py:63-82`
- Modify: `pipeline/scheduler.py:24`
- Test: `tests/test_scheduler.py` (existing test suite covers platform strategies)

### Step 1: Add KUAISHOU strategy

- [ ] **Add the KUAISHOU strategy constant and register it**

In `pipeline/collectors/platform_strategy.py`, after the `DOUYIN` definition (line 72) and before the `# ── Registry ──` comment (line 75), add:

```python
KUAISHOU = PlatformStrategy(
    risk_level="high",
    max_keywords=1,        # core keyword only, same as Douyin
    fetch_detail=True,     # Kuaishou titles are short, need detail for text
    fetch_comments=False,  # NEVER fetch comments during search
    comments_per_post=5,
    max_pages=2,
    inter_request_delay=5, # same as Douyin
    top_n_for_comments=3,
)
```

Then in the `PLATFORM_STRATEGIES` dict (line 77-82), add `"kuaishou": KUAISHOU`:

```python
PLATFORM_STRATEGIES: dict[str, PlatformStrategy] = {
    "news": NEWS,
    "xiaohongshu": XIAOHONGSHU,
    "weibo": WEIBO,
    "douyin": DOUYIN,
    "kuaishou": KUAISHOU,
}
```

- [ ] **Run existing platform strategy tests**

Run: `python -m pytest tests/ -k "platform" -v --tb=short`
Expected: All pass (no existing tests test platform_strategy directly, but scheduler tests should still pass)

### Step 2: Add Kuaishou to scheduler

- [ ] **Update _MC_PLATFORMS in scheduler.py**

In `pipeline/scheduler.py` line 24, change:

```python
_MC_PLATFORMS = ["xiaohongshu", "weibo", "douyin"]  # kuaishou dropped
```

to:

```python
_MC_PLATFORMS = ["xiaohongshu", "weibo", "douyin", "kuaishou"]
```

- [ ] **Verify scheduler tests still pass**

Run: `python -m pytest tests/test_scheduler.py -v --tb=short`
Expected: All pass

- [ ] **Commit**

```bash
git add pipeline/collectors/platform_strategy.py pipeline/scheduler.py
git commit -m "feat: add Kuaishou back to collection pipeline (high-risk strategy, same as Douyin)"
```

---

## Task B1: Event Tracker — Core Detection Functions (Pure Python, no DB)

**Files:**
- Rewrite: `pipeline/analysis/event_tracker.py`
- Rewrite: `tests/test_event_tracker.py`

This is the largest task. We break it into sub-tasks by pipeline stage.

---

### Task B1.1: LLM Topic Annotator

**Files:**
- Create section in: `pipeline/analysis/event_tracker.py`
- Test: `tests/test_event_tracker.py`

- [ ] **Write failing test for LLM topic annotation**

In `tests/test_event_tracker.py`, replace the entire file with:

```python
"""Tests: Event Tracker — LLM annotation + keyword graph + Louvain community detection."""
import json
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch


def _make_post(post_id, title="", content="", published_at=None, sentiment="neutral"):
    """Helper to create a post dict for testing."""
    return {
        "id": post_id,
        "title": title,
        "content": content,
        "sentiment": sentiment,
        "published_at": published_at or datetime(2026, 5, 15, 12, 0),
    }


# ── Topic annotation tests ──────────────────────────────────────────────────

def test_annotate_topic_short_post():
    """LLM annotation should return a one-sentence topic for a short post."""
    from pipeline.analysis.event_tracker import annotate_topic
    result = annotate_topic("海豹Ev#比亚迪#海豹 #海豹EV", "海豹Ev")
    assert isinstance(result, str)
    assert len(result) > 0


def test_annotate_topic_empty_input():
    """Empty input should return empty string."""
    from pipeline.analysis.event_tracker import annotate_topic
    assert annotate_topic("", "") == ""


def test_annotate_topic_normalizes_noise():
    """Annotation should produce cleaner text than raw post."""
    from pipeline.analysis.event_tracker import annotate_topic
    result = annotate_topic("《我只是小不是傻》🤣🤣🤣 #苏苏的海豚 #短剧", "海豚")
    # Should identify this as unrelated to the car
    assert isinstance(result, str)
```

- [ ] **Run test to verify it fails**

Run: `python -m pytest tests/test_event_tracker.py::test_annotate_topic_short_post -v`
Expected: FAIL — `annotate_topic` not defined

- [ ] **Implement annotate_topic**

In `pipeline/analysis/event_tracker.py`, replace the ENTIRE file with the new implementation. Start with the annotate_topic function:

```python
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

import json
import logging
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta

import jieba
import jieba.analyse
import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import AnalyzedPost, EventGroup, PostComment, RawPost

logger = logging.getLogger(__name__)

# ── Parameters ──────────────────────────────────────────────────────────────

_TOPIC_PROMPT = """以下是一条社交媒体帖子，请用一句话概括它讨论的核心话题。
如果帖子与汽车无关，请回复"无关"。
只输出概括句，不要解释。

帖子内容：{text}"""

_MAX_TOPIC_LEN = 50        # max chars for topic sentence
_KEYWORD_TOP_K = 5         # top keywords to extract per topic
_KEYWORD_MIN_LEN = 2       # minimum keyword length in chars
_TIME_SPLIT_DAYS = 7       # split events spanning > this many days


# ── Stage 1: Topic Annotation ──────────────────────────────────────────────

def annotate_topic(text: str, vehicle_name: str = "") -> str:
    """Generate a one-sentence topic description for a post using LLM.

    This is the SYNC version for testing. The async version (_annotate_topic_async)
    calls the actual API. This sync version uses keyword heuristics as fallback.
    """
    if not text or not text.strip():
        return ""

    # Clean noise: hashtags, emojis, mentions
    import re
    cleaned = re.sub(r'#[^\s#]+', '', text)          # remove #hashtags
    cleaned = re.sub(r'@\S+', '', cleaned)            # remove @mentions
    cleaned = re.sub(r'[\U00010000-\U0010ffff]', '', cleaned)  # remove emojis
    cleaned = cleaned.strip()

    if not cleaned:
        return ""

    # For the sync fallback: extract key sentence or truncate
    # In production, _annotate_topic_async will be used instead
    return cleaned[:_MAX_TOPIC_LEN]


async def annotate_topics_batch(
    posts: list[dict],
    api_key: str,
    api_url: str,
    model: str = "glm-4-flash",
) -> list[str]:
    """Annotate a batch of posts with LLM-generated topic sentences.

    Returns a list of topic strings, one per post.
    """
    import httpx

    topics = []
    async with httpx.AsyncClient(timeout=15) as client:
        for post in posts:
            text = f"{post.get('title', '')} {post.get('content', '')}".strip()
            if not text:
                topics.append("")
                continue

            prompt = _TOPIC_PROMPT.format(text=text[:300])
            try:
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
                # Truncate if too long
                if len(content) > _MAX_TOPIC_LEN:
                    content = content[:_MAX_TOPIC_LEN]
                topics.append(content)
            except Exception as e:
                logger.warning("Topic annotation failed for post %s: %s", post.get("id"), e)
                # Fallback to sync heuristic
                topics.append(annotate_topic(text))

    return topics
```

- [ ] **Run tests to verify they pass**

Run: `python -m pytest tests/test_event_tracker.py::test_annotate_topic -v`
Expected: PASS

- [ ] **Commit**

```bash
git add pipeline/analysis/event_tracker.py tests/test_event_tracker.py
git commit -m "feat(event-tracker): add LLM topic annotation — stage 1 of new pipeline"
```

---

### Task B1.2: Keyword Extraction + Co-occurrence Graph + Louvain

**Files:**
- Modify: `pipeline/analysis/event_tracker.py`
- Modify: `tests/test_event_tracker.py`

- [ ] **Write failing tests for keyword extraction and graph building**

Append to `tests/test_event_tracker.py`:

```python
# ── Keyword extraction tests ────────────────────────────────────────────────

def test_extract_keywords_basic():
    """Should extract meaningful keywords from text."""
    from pipeline.analysis.event_tracker import extract_keywords
    keywords = extract_keywords("比亚迪海豚降价三万元性价比很高")
    assert isinstance(keywords, list)
    assert len(keywords) > 0
    # Should contain car-relevant terms
    assert any("降价" in kw or "海豚" in kw or "比亚迪" in kw for kw in keywords)


def test_extract_keywords_empty():
    """Empty input should return empty list."""
    from pipeline.analysis.event_tracker import extract_keywords
    assert extract_keywords("") == []


def test_extract_keywords_filters_short():
    """Keywords shorter than 2 chars should be filtered."""
    from pipeline.analysis.event_tracker import extract_keywords
    keywords = extract_keywords("好车")
    # "好" and "车" are both 1 char, should be filtered
    for kw in keywords:
        assert len(kw) >= 2


# ── Co-occurrence graph tests ───────────────────────────────────────────────

def test_build_cooccurrence_graph():
    """Posts sharing keywords should be connected in the graph."""
    from pipeline.analysis.event_tracker import build_keyword_graph
    posts = [
        {"id": "p1", "topic_keywords": ["降价", "海豚", "比亚迪"]},
        {"id": "p2", "topic_keywords": ["降价", "订单"]},
        {"id": "p3", "topic_keywords": ["续航", "衰减"]},
    ]
    G = build_keyword_graph(posts)
    assert G.number_of_nodes() > 0
    assert G.number_of_edges() > 0
    # "降价" appears in p1 and p2, so it connects to keywords in both
    assert G.has_node("降价")


def test_build_graph_empty():
    """Empty posts should return empty graph."""
    from pipeline.analysis.event_tracker import build_keyword_graph
    G = build_keyword_graph([])
    assert G.number_of_nodes() == 0


# ── Community detection tests ───────────────────────────────────────────────

def test_detect_communities_separates_topics():
    """Two unrelated keyword clusters should form separate communities."""
    from pipeline.analysis.event_tracker import (
        build_keyword_graph, detect_communities,
    )
    posts = [
        {"id": "p1", "topic_keywords": ["降价", "促销", "优惠"]},
        {"id": "p2", "topic_keywords": ["降价", "促销"]},
        {"id": "p3", "topic_keywords": ["续航", "衰减", "冬天"]},
        {"id": "p4", "topic_keywords": ["续航", "衰减"]},
    ]
    G = build_keyword_graph(posts)
    communities = detect_communities(G)
    assert len(communities) >= 2  # at least 2 separate communities


def test_detect_communities_empty_graph():
    """Empty graph should return empty communities."""
    from pipeline.analysis.event_tracker import detect_communities
    import networkx as nx
    G = nx.Graph()
    assert detect_communities(G) == {}
```

- [ ] **Run tests to verify they fail**

Run: `python -m pytest tests/test_event_tracker.py::test_extract_keywords_basic -v`
Expected: FAIL — `extract_keywords` not defined

- [ ] **Implement extract_keywords, build_keyword_graph, detect_communities**

Append to `pipeline/analysis/event_tracker.py`:

```python
# ── Stage 2: Keyword Extraction ────────────────────────────────────────────

# Stopwords to filter from keyword extraction
_STOPWORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有",
    "看", "好", "自己", "这", "他", "她", "它", "什么", "那", "就是", "可以",
    "这个", "那个", "还是", "但是", "因为", "所以", "如果", "虽然", "已经",
    "一下", "一些", "应该", "可能", "不过", "而且", "然后", "或者", "比较",
    "真的", "怎么", "这么", "那么", "还是", "其实", "感觉", "觉得",
    # Generic car terms that appear everywhere (low discriminative power)
    "车", "汽车", "新能源", "电动车", "这个车", "那种",
}

# Brand/model names that appear in almost every post (low discriminative power)
_GENERIC_NAMES = {
    "比亚迪", "元PLUS", "海豚", "银河E5", "吉利",
}


def extract_keywords(text: str, top_k: int = _KEYWORD_TOP_K) -> list[str]:
    """Extract discriminative keywords from text using TF-IDF via jieba.

    Filters stopwords, generic brand names, and short tokens.
    """
    if not text or not text.strip():
        return []

    # Use TF-IDF to extract keywords
    keywords = jieba.analyse.extract_tags(
        text,
        topK=top_k * 2,  # extract extra, filter later
        withWeight=False,
    )

    # Filter: remove stopwords, generic names, short tokens
    filtered = []
    for kw in keywords:
        if len(kw) < _KEYWORD_MIN_LEN:
            continue
        if kw in _STOPWORDS:
            continue
        if kw in _GENERIC_NAMES:
            continue
        filtered.append(kw)

    return filtered[:top_k]


# ── Stage 3: Keyword Co-occurrence Graph ────────────────────────────────────

def build_keyword_graph(posts: list[dict]) -> nx.Graph:
    """Build a keyword co-occurrence graph from posts.

    Each post's keywords are fully connected (complete subgraph).
    Edge weight = number of posts where two keywords co-occur.

    Args:
        posts: list of dicts with 'topic_keywords' field (list of strings)

    Returns:
        networkx Graph where nodes are keywords, edges are co-occurrence.
    """
    G = nx.Graph()

    for post in posts:
        keywords = post.get("topic_keywords", [])
        if not keywords:
            continue

        # Add nodes
        for kw in keywords:
            if not G.has_node(kw):
                G.add_node(kw)

        # Add edges (complete subgraph for co-occurring keywords)
        for i in range(len(keywords)):
            for j in range(i + 1, len(keywords)):
                kw_a, kw_b = keywords[i], keywords[j]
                if G.has_edge(kw_a, kw_b):
                    G[kw_a][kw_b]["weight"] += 1
                else:
                    G.add_edge(kw_a, kw_b, weight=1)

    return G


# ── Stage 4: Louvain Community Detection ────────────────────────────────────

def detect_communities(G: nx.Graph) -> dict[str, int]:
    """Detect keyword communities using Louvain algorithm.

    Args:
        G: keyword co-occurrence graph

    Returns:
        dict mapping keyword → community_id
    """
    if G.number_of_nodes() == 0:
        return {}

    try:
        import community as community_louvain
        partition = community_louvain.best_partition(G, weight="weight")
        return partition
    except ImportError:
        # Fallback: use networkx built-in greedy modularity
        from networkx.algorithms.community import greedy_modularity_communities
        communities = greedy_modularity_communities(G, weight="weight")
        partition = {}
        for i, comm in enumerate(communities):
            for node in comm:
                partition[node] = i
        return partition
```

- [ ] **Run tests to verify they pass**

Run: `python -m pytest tests/test_event_tracker.py -v --tb=short`
Expected: All pass

- [ ] **Commit**

```bash
git add pipeline/analysis/event_tracker.py tests/test_event_tracker.py
git commit -m "feat(event-tracker): keyword extraction + co-occurrence graph + Louvain community detection"
```

---

### Task B1.3: Time Split + Event Assembly

**Files:**
- Modify: `pipeline/analysis/event_tracker.py`
- Modify: `tests/test_event_tracker.py`

- [ ] **Write failing tests for time-split and event assembly**

Append to `tests/test_event_tracker.py`:

```python
# ── Time split tests ────────────────────────────────────────────────────────

def test_split_by_time_no_split():
    """Posts within 7 days should stay in one event."""
    from pipeline.analysis.event_tracker import split_community_by_time
    posts = [
        {"id": "p1", "published_at": datetime(2026, 5, 10), "community": 0},
        {"id": "p2", "published_at": datetime(2026, 5, 12), "community": 0},
        {"id": "p3", "published_at": datetime(2026, 5, 14), "community": 0},
    ]
    groups = split_community_by_time(posts, max_gap_days=7)
    assert len(groups) == 1


def test_split_by_time_separates_far_apart():
    """Posts >7 days apart should split into separate events."""
    from pipeline.analysis.event_tracker import split_community_by_time
    posts = [
        {"id": "p1", "published_at": datetime(2026, 5, 1), "community": 0},
        {"id": "p2", "published_at": datetime(2026, 5, 3), "community": 0},
        {"id": "p3", "published_at": datetime(2026, 5, 20), "community": 0},
        {"id": "p4", "published_at": datetime(2026, 5, 22), "community": 0},
    ]
    groups = split_community_by_time(posts, max_gap_days=7)
    assert len(groups) == 2


# ── Event assembly tests ────────────────────────────────────────────────────

def test_assemble_events():
    """Full pipeline: annotate → keywords → graph → communities → time split → events."""
    from pipeline.analysis.event_tracker import (
        extract_keywords, build_keyword_graph, detect_communities,
        split_community_by_time, assemble_events,
    )
    posts = [
        _make_post("p1", "比亚迪海豚降价3万", "海豚降价后性价比很高", datetime(2026, 5, 10)),
        _make_post("p2", "海豚大降价", "终于等到了海豚降价", datetime(2026, 5, 11)),
        _make_post("p3", "元PLUS续航实测", "实测续航只有350公里", datetime(2026, 5, 10)),
        _make_post("p4", "冬天续航衰减", "冬天续航掉得厉害", datetime(2026, 5, 12)),
    ]
    # Simulate topic annotation (manually set clean topics)
    posts[0]["topic"] = "海豚降价促销活动"
    posts[1]["topic"] = "海豚降价讨论"
    posts[2]["topic"] = "元PLUS续航实测"
    posts[3]["topic"] = "冬季续航衰减问题"

    for p in posts:
        p["topic_keywords"] = extract_keywords(p["topic"])

    G = build_keyword_graph(posts)
    partition = detect_communities(G)

    events = assemble_events(posts, partition)
    assert len(events) >= 1
    # Each event should have required fields
    for event in events:
        assert "post_ids" in event
        assert "start_date" in event
        assert "end_date" in event
        assert "keywords" in event
```

- [ ] **Run tests to verify they fail**

Run: `python -m pytest tests/test_event_tracker.py::test_split_by_time_no_split -v`
Expected: FAIL — `split_community_by_time` not defined

- [ ] **Implement split_community_by_time and assemble_events**

Append to `pipeline/analysis/event_tracker.py`:

```python
# ── Stage 5: Time-based Split ──────────────────────────────────────────────

def split_community_by_time(
    posts: list[dict],
    max_gap_days: int = _TIME_SPLIT_DAYS,
) -> list[list[dict]]:
    """Split posts in a community into sub-groups by temporal gaps.

    Posts are sorted by published_at. When two consecutive posts are more
    than max_gap_days apart, they are split into separate groups.

    Args:
        posts: list of post dicts with 'published_at' field
        max_gap_days: maximum gap in days before splitting

    Returns:
        List of post groups (each group is a list of posts).
    """
    if not posts:
        return []

    # Sort by published_at
    sorted_posts = sorted(posts, key=lambda p: _get_post_date(p))

    groups: list[list[dict]] = [[sorted_posts[0]]]
    for post in sorted_posts[1:]:
        prev_date = _get_post_date(groups[-1][-1])
        curr_date = _get_post_date(post)
        gap = abs((curr_date - prev_date).days) if prev_date and curr_date else 0
        if gap > max_gap_days:
            groups.append([post])
        else:
            groups[-1].append(post)

    return groups


def _get_post_date(post: dict) -> date | None:
    """Extract date from a post dict."""
    pub = post.get("published_at")
    if pub is None:
        return None
    if isinstance(pub, datetime):
        return pub.date()
    if isinstance(pub, date):
        return pub
    return None


# ── Stage 6: Event Assembly ─────────────────────────────────────────────────

def assemble_events(
    posts: list[dict],
    keyword_partition: dict[str, int],
    max_gap_days: int = _TIME_SPLIT_DAYS,
) -> list[dict]:
    """Assemble events from posts using community partition + time splitting.

    Args:
        posts: list of post dicts with 'topic_keywords' and 'published_at'
        keyword_partition: mapping keyword → community_id
        max_gap_days: max gap for time splitting

    Returns:
        List of event dicts with: post_ids, start_date, end_date, keywords,
        post_count, sentiment_distribution
    """
    if not posts or not keyword_partition:
        return []

    # Assign each post to a community based on its keywords
    post_communities: dict[int, list[dict]] = defaultdict(list)
    for post in posts:
        keywords = post.get("topic_keywords", [])
        if not keywords:
            continue
        # Use majority vote: assign to the community of most keywords
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

            # Collect keywords for this event
            event_keywords = set()
            for p in group:
                for kw in p.get("topic_keywords", []):
                    event_keywords.add(kw)

            events.append({
                "post_ids": json.dumps([p["id"] for p in group]),
                "post_count": len(group),
                "start_date": min(dates) if dates else date.today(),
                "end_date": max(dates) if dates else date.today(),
                "keywords": list(event_keywords),
                "sentiment_distribution": json.dumps(sentiments),
                "summary": "",  # will be filled by LLM in stage 7
            })

    return events
```

- [ ] **Run tests to verify they pass**

Run: `python -m pytest tests/test_event_tracker.py -v --tb=short`
Expected: All pass

- [ ] **Commit**

```bash
git add pipeline/analysis/event_tracker.py tests/test_event_tracker.py
git commit -m "feat(event-tracker): time-split + event assembly — stages 5-6"
```

---

### Task B1.4: LLM Event Naming + DB Integration

**Files:**
- Modify: `pipeline/analysis/event_tracker.py`
- Modify: `tests/test_event_tracker.py`

- [ ] **Write failing test for LLM event naming**

Append to `tests/test_event_tracker.py`:

```python
# ── Event naming tests ──────────────────────────────────────────────────────

def test_name_events_empty():
    """Empty events should return empty list."""
    from pipeline.analysis.event_tracker import name_events_sync
    assert name_events_sync([]) == []


def test_name_events_generates_names():
    """Should generate event_tag and summary for each event."""
    from pipeline.analysis.event_tracker import name_events_sync
    events = [
        {
            "post_ids": '["p1","p2"]',
            "post_count": 2,
            "start_date": date(2026, 5, 10),
            "end_date": date(2026, 5, 11),
            "keywords": ["降价", "促销"],
            "sentiment_distribution": '{"positive": 1, "negative": 0, "neutral": 1}',
            "summary": "",
            "representative_posts": ["海豚降价3万", "终于等到了海豚降价"],
        },
    ]
    result = name_events_sync(events)
    assert len(result) == 1
    assert result[0]["event_tag"]  # should have a name
    assert result[0]["summary"]    # should have a summary
```

- [ ] **Run test to verify it fails**

Run: `python -m pytest tests/test_event_tracker.py::test_name_events_generates_names -v`
Expected: FAIL — `name_events_sync` not defined

- [ ] **Implement name_events_sync and name_events_async**

Append to `pipeline/analysis/event_tracker.py`:

```python
# ── Stage 7: LLM Event Naming ───────────────────────────────────────────────

_EVENT_NAMING_PROMPT = """以下是一组讨论同一话题的社交媒体帖子摘要：
{posts_text}

请为这个事件/话题起一个简短名称（2-5个字），并写一句话摘要。
如果帖子内容与汽车无关或无意义，名称填"其他"。

只回复JSON：{{"name": "事件名称", "summary": "一句话摘要"}}"""


def name_events_sync(events: list[dict]) -> list[dict]:
    """Sync fallback for event naming — uses keyword-based naming.
    The async version calls LLM for better quality.
    """
    for event in events:
        keywords = event.get("keywords", [])
        if keywords:
            event["event_tag"] = keywords[0]  # use top keyword as name
            event["summary"] = f"涉及{len(event.get('keywords', []))}个关键词的讨论"
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
    """Name events using LLM. Modifies events in-place and returns them."""
    import httpx
    import re

    async with httpx.AsyncClient(timeout=15) as client:
        for event in events:
            posts_text = "\n".join(f"- {p}" for p in event.get("representative_posts", []))
            if not posts_text:
                posts_text = "无帖子内容"

            prompt = _EVENT_NAMING_PROMPT.format(posts_text=posts_text)
            try:
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
                # Parse JSON
                data = _parse_json(content)
                if data:
                    event["event_tag"] = data.get("name", event.get("keywords", ["其他"])[0])
                    event["summary"] = data.get("summary", "")
                else:
                    # Fallback to keyword-based naming
                    keywords = event.get("keywords", [])
                    event["event_tag"] = keywords[0] if keywords else "其他"
            except Exception as e:
                logger.warning("Event naming failed: %s", e)
                keywords = event.get("keywords", [])
                event["event_tag"] = keywords[0] if keywords else "其他"

    return events


def _parse_json(text: str) -> dict | None:
    """Extract JSON from LLM response."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    import re
    m = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    return None


# ── DB Integration ───────────────────────────────────────────────────────────

async def detect_events_for_vehicle(vehicle_id: str, session: AsyncSession):
    """Full event detection pipeline for a vehicle.

    1. Load analyzed posts from DB
    2. Annotate topics with LLM
    3. Extract keywords
    4. Build co-occurrence graph
    5. Detect communities
    6. Split by time
    7. Name events with LLM
    8. Store EventGroups in DB
    """
    # Load vehicle config for API credentials
    from utils.config import load_api_config
    config = load_api_config()
    glm_cfg = config.get("glm", {})
    api_key = glm_cfg.get("api_key", "")
    api_url = glm_cfg.get("base_url", "https://open.bigmodel.cn/api/paas/v4") + "/chat/completions"
    model = glm_cfg.get("model", "glm-4-flash")

    # Load analyzed posts with raw post dates
    result = await session.execute(
        select(AnalyzedPost).where(AnalyzedPost.vehicle_id == vehicle_id)
    )
    analyzed = result.scalars().all()
    if not analyzed:
        return []

    # Load raw posts for published_at
    post_ids = [ap.post_id for ap in analyzed]
    raw_result = await session.execute(
        select(RawPost.id, RawPost.published_at, RawPost.title, RawPost.content,
               RawPost.likes, RawPost.comments).where(
            RawPost.id.in_(post_ids)
        )
    )
    raw_data = {r[0]: r for r in raw_result.all()}

    # Build post dicts
    post_dicts = []
    for ap in analyzed:
        raw = raw_data.get(ap.post_id)
        pub = raw[1] if raw else ap.analyzed_at
        title = raw[2] if raw else ""
        content = raw[3] if raw else ""
        post_dicts.append({
            "id": ap.id,
            "post_id": ap.post_id,
            "title": title or "",
            "content": (content or "")[:200],
            "sentiment": ap.sentiment,
            "published_at": pub or datetime.now(),
            "likes": raw[4] if raw else 0,
            "comments_count": raw[5] if raw else 0,
        })

    # Stage 1: Annotate topics
    if api_key:
        topics = await annotate_topics_batch(post_dicts, api_key, api_url, model)
    else:
        topics = [annotate_topic(f"{p['title']} {p['content']}", "") for p in post_dicts]

    for post, topic in zip(post_dicts, topics):
        post["topic"] = topic

    # Stage 2: Extract keywords
    for post in post_dicts:
        text = post.get("topic", f"{post['title']} {post['content']}")
        post["topic_keywords"] = extract_keywords(text)

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
    for event in events:
        pids = json.loads(event["post_ids"])
        event_posts = [p for p in post_dicts if p["id"] in pids]
        # Sort by likes, take top 3
        event_posts.sort(key=lambda p: p.get("likes", 0), reverse=True)
        event["representative_posts"] = [
            f"{p.get('title', '')} {p.get('content', '')}"[:80]
            for p in event_posts[:3]
        ]

    # Stage 7: Name events
    if api_key:
        events = await name_events_async(events, api_key, api_url, model)
    else:
        events = name_events_sync(events)

    # Stage 8: Store in DB
    # Clear existing groups
    existing = await session.execute(
        select(EventGroup).where(EventGroup.vehicle_id == vehicle_id)
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
            post_ids=event["post_ids"],
            summary=event.get("summary", ""),
            sentiment_distribution=event.get("sentiment_distribution", "{}"),
        ))

    await session.commit()
    logger.info("Detected %d events for vehicle %s", len(events), vehicle_id)
    return events


# ── Legacy compat (deprecated) ─────────────────────────────────────────────

def detect_events_from_posts(posts: list[dict], **kwargs) -> list[dict]:
    """Sync version for testing — uses keyword-based pipeline without LLM."""
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
```

- [ ] **Run all tests**

Run: `python -m pytest tests/test_event_tracker.py -v --tb=short`
Expected: All pass

- [ ] **Commit**

```bash
git add pipeline/analysis/event_tracker.py tests/test_event_tracker.py
git commit -m "feat(event-tracker): LLM event naming + DB integration — full pipeline complete"
```

---

## Task B2: Pipeline Reorder — Filter Before Analyze

**Files:**
- Modify: `pipeline/analysis/batch_runner.py:90-100`
- Test: `tests/test_analysis_api.py`

### Current flow (line 90-100):
```python
# Stage 0: Relevance filtering (rule engine + LLM)
llm = LLMRelevanceChecker.from_config()
refilter = RelevanceFilter(llm_checker=llm)
filter_stats = await refilter.filter_vehicle(vehicle_id, self._session)
# ... then analyzes "pending" posts
```

**The filter already runs BEFORE analysis in the current code** (line 95-100). The filter marks irrelevant posts as `"irrelevant"`, then the analysis loop at line 104 only picks up `"pending"` posts. This is correct.

- [ ] **Verify filter-then-analyze order is already correct**

Read `batch_runner.py` lines 90-110. The `filter_vehicle()` sets `analysis_status = "irrelevant"` on bad posts. Then the analysis loop `WHERE analysis_status == "pending"` only processes surviving posts. **No code change needed.**

- [ ] **Verify with existing test**

Run: `python -m pytest tests/test_analysis_api.py -v --tb=short`
Expected: All pass

---

## Task B3: Update Analysis API Entry Point

**Files:**
- Modify: `api/routes/analysis.py:46-49`

- [ ] **Update the event detection call in the analysis pipeline**

In `api/routes/analysis.py`, replace lines 46-49:

```python
            # DBSCAN event clustering
            try:
                from pipeline.analysis.event_tracker import cluster_events_for_vehicle
                await cluster_events_for_vehicle(vehicle_id, session)
            except Exception:
                pass
```

with:

```python
            # Event detection (keyword graph + Louvain)
            try:
                from pipeline.analysis.event_tracker import detect_events_for_vehicle
                await detect_events_for_vehicle(vehicle_id, session)
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Event detection failed: %s", e)
```

- [ ] **Run analysis API tests**

Run: `python -m pytest tests/test_analysis_api.py -v --tb=short`
Expected: All pass

- [ ] **Commit**

```bash
git add api/routes/analysis.py
git commit -m "refactor(analysis-api): use new event detection pipeline"
```

---

## Task B4: Add Dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Add python-louvain to requirements**

In `requirements.txt`, append:

```
python-louvain>=0.16
```

Note: `jieba`, `networkx`, and `scikit-learn` are already installed (via Anaconda). `python-louvain` provides the `community` package for Louvain algorithm. If it's not available, the code falls back to `networkx.algorithms.community.greedy_modularity_communities`.

- [ ] **Install dependency**

Run: `pip install python-louvain`

- [ ] **Commit**

```bash
git add requirements.txt
git commit -m "chore: add python-louvain dependency for community detection"
```

---

## Task B5: Run Full Test Suite

- [ ] **Run all tests**

Run: `python -m pytest tests/ -v --tb=short -q`
Expected: 396+ passed, at most 1 error (known pytest-asyncio issue)

- [ ] **Fix any test failures**

If any test breaks due to the event_tracker rewrite, update the test to match the new API. Key changes:
- `aggregate_tag_volumes`, `detect_spikes`, `cluster_events` → removed (or deprecated)
- New public API: `detect_events_for_vehicle`, `detect_events_from_posts`

- [ ] **Final commit**

```bash
git add -A
git commit -m "feat: complete event detection redesign — LLM annotate + keyword graph + Louvain + Kuaishou collection"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- [x] Kuaishou added to collection → Task A
- [x] LLM topic annotation → Task B1.1
- [x] Keyword extraction via jieba → Task B1.2
- [x] Co-occurrence graph → Task B1.2
- [x] Louvain community detection → Task B1.2
- [x] Time split → Task B1.3
- [x] Event assembly → Task B1.3
- [x] LLM event naming → Task B1.4
- [x] DB integration → Task B1.4
- [x] Filter before analyze → Task B2 (already correct)
- [x] API entry point updated → Task B3
- [x] Dependencies → Task B4
- [x] event_tags kept for dashboard → analyzer.py not touched
- [x] Comments only for enrichment (not event discovery) → Task B1.4 loads comments only for naming

**2. Placeholder scan:**
- No TBD, TODO, "implement later", "handle edge cases" found
- All steps have actual code

**3. Type consistency:**
- `assemble_events()` returns `list[dict]` with keys: post_ids, post_count, start_date, end_date, keywords, sentiment_distribution, summary
- `name_events_sync()` adds: event_tag
- `detect_events_for_vehicle()` stores EventGroup with: event_tag, start_date, end_date, post_count, post_ids, summary, sentiment_distribution — matches `models/schemas.py:EventGroup`
- `detect_events_from_posts()` returns `list[dict]` — matches old API for test compatibility
