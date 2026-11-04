"""Tests: Event tracker keyword graph pipeline — reuses volume tracker test class names
for backward-compatible test discovery."""
import json
from datetime import date, datetime, timedelta

from pipeline.analysis.event_tracker import (
    annotate_topic,
    extract_keywords,
    build_keyword_graph,
    detect_communities,
    split_community_by_time,
    assemble_events,
    detect_events_from_posts,
)


def _make_post(post_id, tag_or_title, pub_date, sentiment="neutral"):
    """Helper to create a post dict for testing.

    Accepts both old-style (tag string) and new-style (title string) usage.
    """
    return {
        "id": post_id,
        "title": str(tag_or_title),
        "content": f"关于{tag_or_title}的讨论",
        "sentiment": sentiment,
        "published_at": pub_date,
    }


# ── Keyword extraction ──────────────────────────────────────────────────────

class TestExtractKeywords:
    def test_extracts_discriminative_keywords(self):
        kws = extract_keywords("海豚降价三万元促销活动优惠力度大")
        assert len(kws) > 0
        # Should have at least one price/promotion keyword
        assert any(kw in kws for kw in ["降价", "促销", "优惠", "三万元"])

    def test_empty_returns_empty(self):
        assert extract_keywords("") == []

    def test_filters_generic_brand(self):
        kws = extract_keywords("比亚迪海豚降价三万元")
        assert "比亚迪" not in kws
        assert "海豚" not in kws


# ── Co-occurrence graph ─────────────────────────────────────────────────────

class TestBuildKeywordGraph:
    def test_shared_keywords_create_edges(self):
        posts = [
            {"id": "p1", "topic_keywords": ["降价", "促销"]},
            {"id": "p2", "topic_keywords": ["降价", "优惠"]},
        ]
        G = build_keyword_graph(posts)
        assert G.has_edge("降价", "促销")
        assert G.has_edge("降价", "优惠")

    def test_edge_weight_increments(self):
        posts = [
            {"id": "p1", "topic_keywords": ["降价", "促销"]},
            {"id": "p2", "topic_keywords": ["降价", "促销"]},
        ]
        G = build_keyword_graph(posts)
        assert G["降价"]["促销"]["weight"] == 2

    def test_empty_returns_empty(self):
        G = build_keyword_graph([])
        assert G.number_of_nodes() == 0


# ── Community detection ─────────────────────────────────────────────────────

class TestDetectCommunities:
    def test_separates_unrelated_clusters(self):
        posts = [
            {"id": "p1", "topic_keywords": ["降价", "促销", "优惠"]},
            {"id": "p2", "topic_keywords": ["降价", "促销"]},
            {"id": "p3", "topic_keywords": ["续航", "衰减", "冬天"]},
            {"id": "p4", "topic_keywords": ["续航", "衰减"]},
        ]
        G = build_keyword_graph(posts)
        partition = detect_communities(G)
        # Two distinct clusters
        assert len(set(partition.values())) >= 2

    def test_empty_graph_returns_empty(self):
        import networkx as nx
        assert detect_communities(nx.Graph()) == {}


# ── Time split ──────────────────────────────────────────────────────────────

class TestSplitByTime:
    def test_close_posts_stay_together(self):
        posts = [
            {"id": "p1", "published_at": datetime(2026, 5, 10)},
            {"id": "p2", "published_at": datetime(2026, 5, 12)},
            {"id": "p3", "published_at": datetime(2026, 5, 14)},
        ]
        groups = split_community_by_time(posts, max_gap_days=7)
        assert len(groups) == 1

    def test_distant_posts_split(self):
        posts = [
            {"id": "p1", "published_at": datetime(2026, 5, 1)},
            {"id": "p2", "published_at": datetime(2026, 5, 3)},
            {"id": "p3", "published_at": datetime(2026, 5, 20)},
            {"id": "p4", "published_at": datetime(2026, 5, 22)},
        ]
        groups = split_community_by_time(posts, max_gap_days=7)
        assert len(groups) == 2


# ── Full pipeline ───────────────────────────────────────────────────────────

class TestDetectEventsFromPosts:
    def test_no_posts_returns_empty(self):
        assert detect_events_from_posts([]) == []

    def test_detects_events_from_posts(self):
        posts = [
            _make_post("p1", "海豚降价三万", date(2026, 5, 10)),
            _make_post("p2", "海豚大降价", date(2026, 5, 11)),
            _make_post("p3", "续航实测结果", date(2026, 5, 10)),
            _make_post("p4", "冬季续航衰减", date(2026, 5, 12)),
        ]
        events = detect_events_from_posts(posts)
        assert len(events) >= 1
        for e in events:
            assert e["event_tag"]
            assert e["post_count"] > 0

    def test_different_topics_form_separate_events(self):
        """Posts about price cuts vs. range issues should form separate events."""
        posts = []
        base = date(2026, 5, 1)
        for i in range(5):
            posts.append(_make_post(f"cut{i}", "海豚降价促销活动", base + timedelta(days=i)))
        for i in range(5):
            posts.append(_make_post(f"rng{i}", "续航衰减冬天掉电", base + timedelta(days=i)))
        events = detect_events_from_posts(posts)
        # Should have at least 2 distinct event tags
        tags = {e["event_tag"] for e in events}
        assert len(tags) >= 2
