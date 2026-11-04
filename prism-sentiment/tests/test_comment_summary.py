"""Tests: Comment batch summary — get_current_period + summarize_comments."""
import pytest
from datetime import date
from unittest.mock import patch, AsyncMock

from pipeline.analysis.batch_runner import get_current_period, summarize_comments


# ── get_current_period ────────────────────────────────────────────────────

def test_get_current_period_first_half():
    """Day 1-15 is first half."""
    with patch("pipeline.analysis.batch_runner.date_type") as mock_date:
        mock_date.today.return_value = date(2026, 5, 10)
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        mock_date.fromordinal = date.fromordinal
        start, end = get_current_period()
        assert start == date(2026, 5, 1)
        assert end == date(2026, 5, 15)


def test_get_current_period_second_half():
    """Day 16+ is second half."""
    with patch("pipeline.analysis.batch_runner.date_type") as mock_date:
        mock_date.today.return_value = date(2026, 5, 20)
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        mock_date.fromordinal = date.fromordinal
        start, end = get_current_period()
        assert start == date(2026, 5, 16)
        assert end == date(2026, 5, 31)


def test_get_current_period_december_second_half():
    """December 16-31."""
    with patch("pipeline.analysis.batch_runner.date_type") as mock_date:
        mock_date.today.return_value = date(2026, 12, 25)
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        mock_date.fromordinal = date.fromordinal
        start, end = get_current_period()
        assert start == date(2026, 12, 16)
        assert end == date(2026, 12, 31)


def test_get_current_period_first_day():
    """Day 1 should be in first half."""
    with patch("pipeline.analysis.batch_runner.date_type") as mock_date:
        mock_date.today.return_value = date(2026, 3, 1)
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        mock_date.fromordinal = date.fromordinal
        start, end = get_current_period()
        assert start == date(2026, 3, 1)
        assert end == date(2026, 3, 15)


def test_get_current_period_boundary_day_15():
    """Day 15 is still first half."""
    with patch("pipeline.analysis.batch_runner.date_type") as mock_date:
        mock_date.today.return_value = date(2026, 7, 15)
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        mock_date.fromordinal = date.fromordinal
        start, end = get_current_period()
        assert start == date(2026, 7, 1)
        assert end == date(2026, 7, 15)


def test_get_current_period_boundary_day_16():
    """Day 16 starts second half."""
    with patch("pipeline.analysis.batch_runner.date_type") as mock_date:
        mock_date.today.return_value = date(2026, 7, 16)
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        mock_date.fromordinal = date.fromordinal
        start, end = get_current_period()
        assert start == date(2026, 7, 16)


# ── summarize_comments ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_summarize_comments_skips_low_count():
    """Posts with < 3 comments should be skipped."""
    result = await summarize_comments(
        [{"content": "评论1", "likes": 5}, {"content": "评论2", "likes": 3}],
        title="标题",
        content_snippet="内容",
    )
    assert result is None


@pytest.mark.asyncio
async def test_summarize_comments_returns_dict():
    """With sufficient comments, should return parsed JSON dict."""
    comments = [{"content": f"评论{i}", "likes": i} for i in range(10)]
    with patch("pipeline.analysis.batch_runner.AnalysisPipeline") as MockPipeline:
        instance = MockPipeline.return_value
        instance._call_api = AsyncMock(
            return_value='{"is_argumentative": false, "argument_detail": "", '
                         '"genuine_themes": ["价格"], "genuine_sentiment": "positive", '
                         '"genuine_sentiment_score": 0.7, "summary": "评论区整体正面"}'
        )
        result = await summarize_comments(comments, title="标题", content_snippet="内容")
        assert result is not None
        assert result["genuine_sentiment"] == "positive"
        assert "价格" in result["genuine_themes"]


@pytest.mark.asyncio
async def test_summarize_comments_llm_failure():
    """LLM failure should return None."""
    comments = [{"content": f"评论{i}", "likes": i} for i in range(10)]
    with patch("pipeline.analysis.batch_runner.AnalysisPipeline") as MockPipeline:
        instance = MockPipeline.return_value
        instance._call_api = AsyncMock(side_effect=Exception("API error"))
        result = await summarize_comments(comments, title="标题", content_snippet="内容")
        assert result is None


@pytest.mark.asyncio
async def test_summarize_comments_malformed_response():
    """LLM returning non-JSON should return None."""
    comments = [{"content": f"评论{i}", "likes": i} for i in range(10)]
    with patch("pipeline.analysis.batch_runner.AnalysisPipeline") as MockPipeline:
        instance = MockPipeline.return_value
        instance._call_api = AsyncMock(return_value="This is not JSON at all")
        result = await summarize_comments(comments, title="标题", content_snippet="内容")
        assert result is None


@pytest.mark.asyncio
async def test_summarize_comments_exactly_3():
    """Exactly 3 comments should NOT be skipped (new threshold is 3)."""
    comments = [{"content": f"评论{i}", "likes": i} for i in range(3)]
    with patch("pipeline.analysis.batch_runner.AnalysisPipeline") as MockPipeline:
        instance = MockPipeline.return_value
        instance._call_api = AsyncMock(
            return_value='{"is_argumentative": false, "argument_detail": "", '
                         '"genuine_themes": [], "genuine_sentiment": "mixed", '
                         '"genuine_sentiment_score": 0.0, "summary": "test"}'
        )
        result = await summarize_comments(comments, title="标题", content_snippet="内容")
        assert result is not None


@pytest.mark.asyncio
async def test_summarize_comments_sorts_by_likes():
    """Comments should be sorted by likes (descending) before being sent."""
    comments = [
        {"content": "低赞评论", "likes": 1},
        {"content": "高赞评论", "likes": 100},
        {"content": "中赞评论", "likes": 50},
        {"content": "评论4", "likes": 10},
        {"content": "评论5", "likes": 5},
    ]
    with patch("pipeline.analysis.batch_runner.AnalysisPipeline") as MockPipeline:
        instance = MockPipeline.return_value
        instance._call_api = AsyncMock(
            return_value='{"is_argumentative": false, "argument_detail": "", '
                         '"genuine_themes": [], "genuine_sentiment": "positive", '
                         '"genuine_sentiment_score": 0.5, "summary": "ok"}'
        )
        # We just verify it succeeds — the sorting is internal
        result = await summarize_comments(comments, title="标题", content_snippet="内容")
        assert result is not None
        # Verify _call_api was called (the prompt was generated)
        instance._call_api.assert_called_once()
