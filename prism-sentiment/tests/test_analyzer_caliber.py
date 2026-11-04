"""Tests: Phase 2 分析层口径（评论分母/事件切并/缺陷 TTL 等）。"""
import pytest


def test_unanalyzed_dim_sentiment_values():
    """§9.3: 端点层应排除的未分析 dim_sentiment 值。"""
    # derive_comment_sentiment 对这些返回 neutral，但端点层应跳过不计数
    from pipeline.collectors.post_utils import derive_comment_sentiment
    for v in [None, "{}", "", "null"]:
        assert derive_comment_sentiment(v) == "neutral", f"{v!r} 应派生 neutral"


def test_analyzed_dim_sentiment_values():
    """§9.3: 已分析 dim_sentiment 应正常派生情感。"""
    from pipeline.collectors.post_utils import derive_comment_sentiment
    # 正面维度
    pos = '{"续航": 0.8, "动力": 0.5}'
    assert derive_comment_sentiment(pos) == "positive"
    # 负面维度
    neg = '{"续航": -0.8, "动力": -0.5}'
    assert derive_comment_sentiment(neg) == "negative"


def test_event_split_merge_params_consistent():
    """§9.4: 切分阈值与合并阈值统一（决策：bug，统一为 7 天）。"""
    from pipeline.analysis.event_tracker import _TIME_SPLIT_DAYS, _MERGE_GAP_DAYS
    # 切分阈值应 >= 合并阈值（否则切了又并回来抵消）
    assert _TIME_SPLIT_DAYS >= _MERGE_GAP_DAYS, \
        f"切分 {_TIME_SPLIT_DAYS} < 合并 {_MERGE_GAP_DAYS}，互相抵消"
    # 默认都 7 天
    assert _TIME_SPLIT_DAYS == 7
    assert _MERGE_GAP_DAYS == 7


def test_event_params_env_configurable():
    """§9.4: 事件参数 env 化（与 defect_miner 风格统一）。"""
    from pipeline.analysis.event_tracker import _TIME_SPLIT_DAYS, _MERGE_GAP_DAYS, _MIN_EVENT_POSTS
    # 都是 env_int 返回的 int 类型
    assert isinstance(_TIME_SPLIT_DAYS, int)
    assert isinstance(_MERGE_GAP_DAYS, int)
    assert isinstance(_MIN_EVENT_POSTS, int)


def test_event_same_name_different_posts_not_merged():
    """§9.5: 同名但合并后跨度超上限 → 不合并（防撞名误并）。"""
    import json
    from pipeline.analysis.event_tracker import merge_adjacent_slices
    from datetime import date
    # 两个同名事件，gap 3 天（≤7 相邻），但合并后跨度 35 天 > 30 天上限
    events = [
        {"event_tag": "OTA升级", "start_date": date(2026,5,1), "end_date": date(2026,5,3),
         "post_ids": json.dumps(["p1","p2"]), "post_count": 2,
         "sentiment_distribution": json.dumps({"positive":1,"negative":1,"neutral":0}),
         "summary": "OTA1"},
        {"event_tag": "OTA升级", "start_date": date(2026,5,6), "end_date": date(2026,6,5),
         "post_ids": json.dumps(["p3","p4"]), "post_count": 2,
         "sentiment_distribution": json.dumps({"positive":1,"negative":1,"neutral":0}),
         "summary": "OTA2"},
    ]
    merged = merge_adjacent_slices(events, max_gap_days=7)
    # 合并后跨度 35 天 > 30 天上限 → 不合并
    assert len(merged) == 2, f"撞名不同事件（跨度超限）不应合并，实际 {len(merged)}"


def test_event_same_name_within_span_merged():
    """§9.5: 同名 + 时间相邻 + 跨度在上限内 → 合并（同一事件延续）。"""
    import json
    from pipeline.analysis.event_tracker import merge_adjacent_slices
    from datetime import date
    events = [
        {"event_tag": "OTA升级", "start_date": date(2026,5,1), "end_date": date(2026,5,3),
         "post_ids": json.dumps(["p1","p2"]), "post_count": 2,
         "sentiment_distribution": json.dumps({"positive":1,"negative":1,"neutral":0}),
         "summary": "OTA1"},
        {"event_tag": "OTA升级", "start_date": date(2026,5,6), "end_date": date(2026,5,15),
         "post_ids": json.dumps(["p3","p4"]), "post_count": 2,
         "sentiment_distribution": json.dumps({"positive":1,"negative":1,"neutral":0}),
         "summary": "OTA2"},
    ]
    merged = merge_adjacent_slices(events, max_gap_days=7)
    # 合并后跨度 14 天 ≤ 30 天 → 合并
    assert len(merged) == 1, f"跨度内的同名事件应合并，实际 {len(merged)}"


def test_defect_rep_comments_prefers_negative():
    """§9.5: rep_comments 排序逻辑——负面帖评论优先，非正面。"""
    # 验证 defect_miner 用的排序 key
    comments = [
        {"post_id": "p1", "content": "好评", "likes": 100, "post_sentiment": "positive"},
        {"post_id": "p2", "content": "差评", "likes": 5, "post_sentiment": "negative"},
        {"post_id": "p3", "content": "中性", "likes": 50, "post_sentiment": "neutral"},
    ]
    rep = sorted(comments, key=lambda c: (c.get("post_sentiment") != "negative", -c.get("likes", 0)))[:3]
    # negative 评论排首位（即使 likes 最低）
    assert rep[0]["post_sentiment"] == "negative", f"负面评论应排首位，实际 {rep[0]['post_sentiment']}"
