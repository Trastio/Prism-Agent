"""T2.3 Tests: Half-month Top 5 comment batch summary — 7 tests."""
import json
import uuid
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.schemas import AnalyzedPost, Base, PostComment, RawPost, Vehicle
from pipeline.analysis.batch_runner import get_current_period, summarize_comments


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


# ── get_current_period tests ──────────────────────────────────────────────

def test_get_current_period_first_half():
    """First half of month: day 1-15."""
    with patch("pipeline.analysis.batch_runner.date_type") as mock_date:
        mock_date.today.return_value = date(2026, 5, 10)
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        start, end = get_current_period()
        assert start.day == 1
        assert end.day == 15


def test_get_current_period_second_half():
    """Second half of month: day 16+."""
    with patch("pipeline.analysis.batch_runner.date_type") as mock_date:
        mock_date.today.return_value = date(2026, 5, 20)
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        start, end = get_current_period()
        assert start.day == 16


def test_get_current_period_second_half_december():
    """December second half: end should be Dec 31."""
    with patch("pipeline.analysis.batch_runner.date_type") as mock_date:
        mock_date.today.return_value = date(2026, 12, 25)
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        mock_date.fromordinal = date.fromordinal
        start, end = get_current_period()
        assert start.day == 16
        assert end.day == 31


# ── summarize_comments tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_summarize_comments_skips_low_count():
    """Comments below minimum threshold should be skipped."""
    result = await summarize_comments(
        [{"content": "评论1", "likes": 5}],
        title="标题", content_snippet="摘要",
    )
    assert result is None


@pytest.mark.asyncio
async def test_summarize_comments_calls_llm():
    """With sufficient comments, should call LLM and return parsed result."""
    comments = [
        {"content": f"评论{i}", "likes": 10 - i}
        for i in range(6)
    ]
    mock_result = json.dumps({
        "is_argumentative": False,
        "argument_detail": "",
        "genuine_themes": ["续航"],
        "genuine_sentiment": "positive",
        "genuine_sentiment_score": 0.7,
        "summary": "评论区整体正面",
    })

    with patch("pipeline.analysis.analyzer.AnalysisPipeline._call_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = mock_result
        result = await summarize_comments(comments, "标题", "摘要")

    assert result is not None
    assert result["genuine_sentiment"] == "positive"
    assert "续航" in result["genuine_themes"]


@pytest.mark.asyncio
async def test_summarize_comments_handles_api_failure():
    """API failure should return None gracefully."""
    comments = [
        {"content": f"评论{i}", "likes": 10 - i}
        for i in range(5)
    ]

    with patch("pipeline.analysis.analyzer.AnalysisPipeline._call_api", new_callable=AsyncMock) as mock_api:
        mock_api.side_effect = Exception("API error")
        result = await summarize_comments(comments, "标题", "摘要")

    assert result is None


# ── run_comment_summaries integration tests ───────────────────────────────

@pytest.mark.asyncio
async def test_run_comment_summaries_top5(db):
    """Top posts with sufficient comments get summaries stored in AnalyzedPost."""
    from pipeline.analysis.batch_runner import BatchAnalysisRunner

    vid = "v001"
    db.add(Vehicle(id=vid, name="海豹", brand="比亚迪"))
    now = datetime.now()

    # Create 3 posts with different interaction intensities
    # （2026-10-15 R23：weibo 停采后选帖跳过，fixture 平台换 douyin）
    post_ids = []
    for i, (likes, comments_count, shares) in enumerate([(100, 20, 50), (50, 10, 20), (10, 5, 2)]):
        pid = str(uuid.uuid4())
        post_ids.append(pid)
        db.add(RawPost(
            id=pid, vehicle_id=vid, source="test", platform="douyin",
            title=f"帖子{i}", content=f"内容{i}",
            published_at=now - timedelta(hours=i),
            likes=likes, comments=comments_count, shares=shares,
            analysis_status="analyzed",
        ))
        # Create AnalyzedPost for each
        db.add(AnalyzedPost(
            id=str(uuid.uuid4()), post_id=pid, vehicle_id=vid,
            sentiment="positive", confidence=0.8,
        ))
        # Create comments for each post
        for j in range(comments_count):
            db.add(PostComment(
                id=str(uuid.uuid4()), post_id=pid, vehicle_id=vid,
                content=f"评论{j}帖{i}", likes=max(0, comments_count - j),
            ))

    await db.commit()

    mock_summary = {
        "is_argumentative": False,
        "argument_detail": "",
        "genuine_themes": ["续航"],
        "genuine_sentiment": "positive",
        "genuine_sentiment_score": 0.7,
        "summary": "正面讨论",
    }

    runner = BatchAnalysisRunner(db)
    with patch("pipeline.analysis.batch_runner.summarize_comments", new_callable=AsyncMock) as mock_sc:
        mock_sc.return_value = mock_summary
        count = await runner.run_comment_summaries(vid)

    # All 3 posts have sufficient comments, so all should get summaries
    assert count == 3

    # Verify comment_summary stored in AnalyzedPost
    for pid in post_ids:
        ap = (await db.execute(
            select(AnalyzedPost).where(AnalyzedPost.post_id == pid)
        )).scalars().first()
        assert ap.comment_summary is not None
        stored = json.loads(ap.comment_summary)
        assert stored["genuine_sentiment"] == "positive"


@pytest.mark.asyncio
async def test_run_comment_summaries_skips_few_comments(db):
    """Posts with too few comments should be skipped."""
    from pipeline.analysis.batch_runner import BatchAnalysisRunner

    vid = "v002"
    db.add(Vehicle(id=vid, name="秦PLUS", brand="比亚迪"))
    now = datetime.now()

    pid = str(uuid.uuid4())
    db.add(RawPost(
        id=pid, vehicle_id=vid, source="test", platform="weibo",
        title="少评论帖子", content="内容",
        published_at=now, likes=50, comments=2, shares=10,
        analysis_status="analyzed",
    ))
    db.add(AnalyzedPost(
        id=str(uuid.uuid4()), post_id=pid, vehicle_id=vid,
        sentiment="neutral", confidence=0.5,
    ))
    for j in range(2):
        db.add(PostComment(
            id=str(uuid.uuid4()), post_id=pid, vehicle_id=vid,
            content=f"评论{j}", likes=j,
        ))

    await db.commit()

    runner = BatchAnalysisRunner(db)
    with patch("pipeline.analysis.batch_runner.summarize_comments", new_callable=AsyncMock) as mock_sc:
        count = await runner.run_comment_summaries(vid)

    assert count == 0
    mock_sc.assert_not_called()
