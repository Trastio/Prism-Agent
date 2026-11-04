"""Tests: Event Tracker — LLM annotation + keyword graph + Louvain community detection."""
import json
from datetime import date, datetime, timedelta


def _make_post(post_id, title="", content="", published_at=None, sentiment="neutral", raw_id=None):
    """Helper to create a post dict for testing.

    raw_id: RawPost.id（= AnalyzedPost.post_id），默认与 post_id 相同。
    测试 EventGroup.post_ids 语义时传不同值，以区分 AnalyzedPost.id 与 RawPost.id。
    """
    return {
        "id": post_id,
        "post_id": raw_id or post_id,
        "title": title,
        "content": content,
        "sentiment": sentiment,
        "published_at": published_at or datetime(2026, 5, 15, 12, 0),
    }


# ── Topic annotation tests ──────────────────────────────────────────────────

def test_annotate_topic_short_post():
    """LLM annotation should return a one-sentence topic for a short post."""
    from pipeline.analysis.event_tracker import annotate_topic
    result = annotate_topic("海豹Ev#比亚迪#海豹 #海豹EV")
    assert isinstance(result, str)
    assert len(result) > 0


def test_annotate_topic_empty_input():
    """Empty input should return empty string."""
    from pipeline.analysis.event_tracker import annotate_topic
    assert annotate_topic("") == ""


def test_annotate_topic_strips_noise():
    """Annotation should produce cleaner text than raw post."""
    from pipeline.analysis.event_tracker import annotate_topic
    result = annotate_topic("《我只是小不是傻》🤣🤣🤣 #苏苏的海豚 #短剧")
    assert isinstance(result, str)


def test_annotate_topic_truncates_long():
    """Long text should be truncated to _MAX_TOPIC_LEN."""
    from pipeline.analysis.event_tracker import annotate_topic, _MAX_TOPIC_LEN
    long_text = "这是一段非常长的帖子内容" * 20
    result = annotate_topic(long_text)
    assert len(result) <= _MAX_TOPIC_LEN


# ── Keyword extraction tests ────────────────────────────────────────────────

def test_extract_keywords_basic():
    """Should extract meaningful keywords from text."""
    from pipeline.analysis.event_tracker import extract_keywords
    keywords = extract_keywords("比亚迪海豚降价三万元性价比很高")
    assert isinstance(keywords, list)
    assert len(keywords) > 0
    assert any("降价" in kw or "性价比" in kw for kw in keywords)


def test_extract_keywords_empty():
    """Empty input should return empty list."""
    from pipeline.analysis.event_tracker import extract_keywords
    assert extract_keywords("") == []


def test_extract_keywords_filters_short():
    """Keywords shorter than 2 chars should be filtered."""
    from pipeline.analysis.event_tracker import extract_keywords
    keywords = extract_keywords("好车")
    for kw in keywords:
        assert len(kw) >= 2


def test_extract_keywords_filters_brand():
    """Generic brand names should be filtered out."""
    from pipeline.analysis.event_tracker import extract_keywords
    keywords = extract_keywords("比亚迪海豚降价三万元")
    # "比亚迪" and "海豚" are in _GENERIC_NAMES, should be filtered
    assert "比亚迪" not in keywords
    assert "海豚" not in keywords


# ── Co-occurrence graph tests ───────────────────────────────────────────────

def test_build_cooccurrence_graph():
    """Posts sharing keywords should be connected in the graph."""
    from pipeline.analysis.event_tracker import build_keyword_graph
    posts = [
        {"id": "p1", "topic_keywords": ["降价", "促销", "优惠"]},
        {"id": "p2", "topic_keywords": ["降价", "订单"]},
        {"id": "p3", "topic_keywords": ["续航", "衰减"]},
    ]
    G = build_keyword_graph(posts)
    assert G.number_of_nodes() > 0
    assert G.number_of_edges() > 0
    assert G.has_node("降价")
    # "降价" co-occurs with "促销" in p1, and with "订单" in p2
    assert G.has_edge("降价", "促销")
    assert G.has_edge("降价", "订单")


def test_build_graph_empty():
    """Empty posts should return empty graph."""
    from pipeline.analysis.event_tracker import build_keyword_graph
    G = build_keyword_graph([])
    assert G.number_of_nodes() == 0


def test_build_graph_no_keywords():
    """Posts without topic_keywords should be skipped."""
    from pipeline.analysis.event_tracker import build_keyword_graph
    posts = [{"id": "p1"}, {"id": "p2", "topic_keywords": []}]
    G = build_keyword_graph(posts)
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
    partition = detect_communities(G)
    assert len(set(partition.values())) >= 2


def test_detect_communities_empty_graph():
    """Empty graph should return empty communities."""
    from pipeline.analysis.event_tracker import detect_communities
    import networkx as nx
    G = nx.Graph()
    assert detect_communities(G) == {}


# ── Time split tests ────────────────────────────────────────────────────────

def test_split_by_time_no_split():
    """Posts within 7 days should stay in one event."""
    from pipeline.analysis.event_tracker import split_community_by_time
    posts = [
        {"id": "p1", "published_at": datetime(2026, 5, 10)},
        {"id": "p2", "published_at": datetime(2026, 5, 12)},
        {"id": "p3", "published_at": datetime(2026, 5, 14)},
    ]
    groups = split_community_by_time(posts, max_gap_days=7)
    assert len(groups) == 1


def test_split_by_time_separates_far_apart():
    """Posts >7 days apart should split into separate events."""
    from pipeline.analysis.event_tracker import split_community_by_time
    posts = [
        {"id": "p1", "published_at": datetime(2026, 5, 1)},
        {"id": "p2", "published_at": datetime(2026, 5, 3)},
        {"id": "p3", "published_at": datetime(2026, 5, 20)},
        {"id": "p4", "published_at": datetime(2026, 5, 22)},
    ]
    groups = split_community_by_time(posts, max_gap_days=7)
    assert len(groups) == 2


def test_split_by_time_empty():
    """Empty posts should return empty list."""
    from pipeline.analysis.event_tracker import split_community_by_time
    assert split_community_by_time([]) == []


def test_split_by_time_handles_none_published_at():
    """Posts with None published_at must NOT be treated as 'today'.

    Phase 2 §9.4: NULL 日期帖子不参与事件检测（无时间无法分组成时间事件），
    避免塞入任意簇污染时间线。
    """
    from pipeline.analysis.event_tracker import split_community_by_time
    posts = [
        {"id": "p1", "published_at": datetime(2026, 5, 10)},
        {"id": "p2", "published_at": None},  # NULL 帖 → 跳过
        {"id": "p3", "published_at": datetime(2026, 5, 12)},
    ]
    groups = split_community_by_time(posts, max_gap_days=7)
    # NULL 帖跳过，只分组有日期的 2 帖
    total = sum(len(g) for g in groups)
    assert total == 2, f"NULL 帖应跳过，实际 {total}"
    # p1 和 p3 都有日期，gap 2 天 ≤ 7 → 同一组
    assert len(groups) == 1
    ids = [p["id"] for p in groups[0]]
    assert "p1" in ids and "p3" in ids and "p2" not in ids


# ── Event assembly tests ────────────────────────────────────────────────────

def test_assemble_events():
    """Full pipeline: keywords → graph → communities → time split → events."""
    from pipeline.analysis.event_tracker import (
        extract_keywords, build_keyword_graph, detect_communities,
        assemble_events, name_events_sync,
    )
    posts = [
        _make_post("p1", "海豚降价", "海豚降价后性价比很高", datetime(2026, 5, 10)),
        _make_post("p2", "海豚大降价", "终于等到了海豚降价", datetime(2026, 5, 11)),
        _make_post("p3", "续航实测", "实测续航只有350公里", datetime(2026, 5, 10)),
        _make_post("p4", "冬天续航", "冬天续航掉得厉害", datetime(2026, 5, 12)),
    ]
    # Simulate topic annotation (manually set clean topics)
    posts[0]["topic"] = "海豚降价促销活动"
    posts[1]["topic"] = "海豚降价讨论"
    posts[2]["topic"] = "续航实测结果"
    posts[3]["topic"] = "冬季续航衰减问题"

    for p in posts:
        p["topic_keywords"] = extract_keywords(p["topic"])

    G = build_keyword_graph(posts)
    partition = detect_communities(G)
    events = assemble_events(posts, partition)

    assert len(events) >= 1
    for event in events:
        assert "post_ids" in event
        pids = json.loads(event["post_ids"])
        assert isinstance(pids, list)              # post_ids 是合法 JSON 数组
        assert len(pids) == event["post_count"]    # 数量与 post_count 一致
        assert "start_date" in event
        assert "end_date" in event
        assert "keywords" in event
        assert event["post_count"] > 0


def test_assemble_events_stores_raw_post_id():
    """EventGroup.post_ids 必须存 RawPost.id（post_id），不是 AnalyzedPost.id（id）。

    回归守护：全项目 post_ids 语义统一为 RawPost.id。id 与 post_id 取不同值，
    才能抓住"存错 id"的回归。用 4 posts + 手动干净 topic 让 Louvain 能聚类成 event
    （2 posts 不足：会被分到不同 community、1-post 组被 _MIN_EVENT_POSTS 过滤）。
    """
    from pipeline.analysis.event_tracker import (
        extract_keywords, build_keyword_graph, detect_communities,
        assemble_events,
    )
    posts = [
        _make_post("ap-1", raw_id="raw-1", title="海豚降价",
                   content="海豚降价后性价比很高", published_at=datetime(2026, 5, 10)),
        _make_post("ap-2", raw_id="raw-2", title="海豚大降价",
                   content="终于等到了海豚降价", published_at=datetime(2026, 5, 11)),
        _make_post("ap-3", raw_id="raw-3", title="续航实测",
                   content="实测续航只有350公里", published_at=datetime(2026, 5, 10)),
        _make_post("ap-4", raw_id="raw-4", title="冬天续航",
                   content="冬天续航掉得厉害", published_at=datetime(2026, 5, 12)),
    ]
    posts[0]["topic"] = "海豚降价促销活动"
    posts[1]["topic"] = "海豚降价讨论"
    posts[2]["topic"] = "续航实测结果"
    posts[3]["topic"] = "冬季续航衰减问题"
    for p in posts:
        p["topic_keywords"] = extract_keywords(p["topic"])

    G = build_keyword_graph(posts)
    partition = detect_communities(G)
    events = assemble_events(posts, partition)

    assert len(events) >= 1
    all_post_ids = []
    for event in events:
        all_post_ids.extend(json.loads(event["post_ids"]))
    # 所有 post_ids 必须是 RawPost.id（raw-*），不能有 AnalyzedPost.id（ap-*）
    assert len(all_post_ids) > 0
    for pid in all_post_ids:
        assert pid.startswith("raw-"), f"post_ids 应存 RawPost.id，但含 AnalyzedPost.id: {pid}"


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
        },
    ]
    result = name_events_sync(events)
    assert len(result) == 1
    assert result[0]["event_tag"]
    assert result[0]["summary"]


# ── Full sync pipeline test ─────────────────────────────────────────────────

def test_detect_events_from_posts():
    """Full sync pipeline should detect events from posts."""
    from pipeline.analysis.event_tracker import detect_events_from_posts
    posts = [
        _make_post("p1", "海豚降价三万", "海豚降价后性价比很高", datetime(2026, 5, 10)),
        _make_post("p2", "海豚大降价", "终于等到了海豚降价", datetime(2026, 5, 11)),
        _make_post("p3", "续航实测", "实测续航只有350公里", datetime(2026, 5, 10)),
        _make_post("p4", "冬天续航", "冬天续航掉得厉害", datetime(2026, 5, 12)),
    ]
    events = detect_events_from_posts(posts)
    assert isinstance(events, list)
    # Should have at least one event
    assert len(events) >= 1
    for event in events:
        assert "event_tag" in event
        assert "post_count" in event
        assert event["post_count"] > 0


def test_detect_events_empty_posts():
    """Empty input should return empty list."""
    from pipeline.analysis.event_tracker import detect_events_from_posts
    assert detect_events_from_posts([]) == []


class TestMergeAdjacentSlices:
    """同名相邻切片合并（2026-09-13）：同 tag 间隔 ≤14 天合并成一行。"""

    @staticmethod
    def _ev(tag, s, e, n=2):
        from datetime import date
        return {
            "event_tag": tag, "start_date": date.fromisoformat(s),
            "end_date": date.fromisoformat(e), "post_count": n,
            "post_ids": json.dumps([f"{tag}-{s}-{i}" for i in range(n)]),
            "sentiment_distribution": json.dumps({"positive": n, "negative": 0, "neutral": 0}),
            "summary": f"{tag}摘要",
        }

    def test_adjacent_same_tag_merged(self):
        from pipeline.analysis.event_tracker import merge_adjacent_slices
        events = [
            self._ev("小鹏M03", "2026-04-01", "2026-04-05"),
            self._ev("小鹏M03", "2026-04-10", "2026-04-15"),  # gap 5 天 → 并
            self._ev("小鹏M03", "2026-05-20", "2026-05-25"),  # gap 35 天 → 不并
            self._ev("交付", "2026-04-02", "2026-04-03"),      # 不同 tag 不并
        ]
        out = merge_adjacent_slices(events)
        tags = [(e["event_tag"], e["post_count"]) for e in out]
        assert ("小鹏M03", 4) in tags          # 前两片合并
        assert ("小鹏M03", 2) in tags          # 第三片独立
        assert ("交付", 2) in tags
        merged = next(e for e in out if e["event_tag"] == "小鹏M03" and e["post_count"] == 4)
        assert str(merged["start_date"]) == "2026-04-01"
        assert str(merged["end_date"]) == "2026-04-15"
        assert json.loads(merged["sentiment_distribution"])["positive"] == 4

    def test_qita_bucket_never_merged(self):
        from pipeline.analysis.event_tracker import merge_adjacent_slices
        events = [
            self._ev("其他", "2026-04-01", "2026-04-02"),
            self._ev("其他", "2026-04-03", "2026-04-04"),
        ]
        out = merge_adjacent_slices(events)
        assert len(out) == 2  # "其他"语义混杂，永不合并
