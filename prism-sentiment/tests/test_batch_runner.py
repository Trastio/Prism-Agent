"""T2.1.3 Tests: Batch Analysis Runner — 6 tests."""
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.schemas import AnalyzedPost, Base, RawPost, Vehicle


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


async def _seed_posts(db, vehicle_id, count, status="pending"):
    for i in range(count):
        db.add(RawPost(
            id=str(uuid.uuid4()), vehicle_id=vehicle_id, source="test",
            platform="test", content=f"测试帖子{i}", analysis_status=status,
        ))
    await db.commit()


def _no_op_filter():
    """Mock relevance filter to be a no-op in tests."""
    return patch(
        "pipeline.analysis.relevance_filter.RelevanceFilter.filter_vehicle",
        new_callable=AsyncMock,
        return_value={"total": 0, "passed": 0, "rejected_by_rules": 0, "limbo": 0, "rejected_by_llm": 0},
    )


def _make_batch_mock(sentiment="positive", event_tags=None, confidence=0.9):
    """Return an async mock function for AnalysisPipeline.analyze_batch.

    The returned function generates one result dict per input post, matching
    the signature ``analyze_batch(posts, vehicle_name, vehicle_brand, confusables)``
    （v3：confusables 动态易混清单参数）.
    """
    async def mock(posts, vehicle_name="", vehicle_brand="", confusables=None):
        return [{
            "id": p["id"], "content": p["content"],
            "sentiment": sentiment,
            "event_tags": event_tags or ["日常讨论"],
            "opinion_tags": [], "dim_sentiment": {},
            "subject": "self", "subject_name": "",
            "confidence": confidence,
        } for p in posts]
    return mock


async def test_run_for_vehicle_analyzes_pending(db):
    from pipeline.analysis.batch_runner import BatchAnalysisRunner
    vid = "v001"
    db.add(Vehicle(id=vid, name="海豹", brand="比亚迪"))
    await _seed_posts(db, vid, 3)
    runner = BatchAnalysisRunner(db)
    mock_batch = _make_batch_mock(sentiment="positive")
    with _no_op_filter(), \
         patch.object(runner._pipeline, "analyze_batch", side_effect=mock_batch):
        result = await runner.run_for_vehicle(vid)
    assert result["analyzed"] == 3
    rows = (await db.execute(select(AnalyzedPost))).scalars().all()
    assert len(rows) == 3


async def test_run_for_vehicle_skips_already_analyzed(db):
    from pipeline.analysis.batch_runner import BatchAnalysisRunner
    vid = "v001"
    db.add(Vehicle(id=vid, name="海豹", brand="比亚迪"))
    await _seed_posts(db, vid, 2, status="analyzed")
    await _seed_posts(db, vid, 1, status="pending")
    runner = BatchAnalysisRunner(db)
    mock_batch = _make_batch_mock(sentiment="positive")
    with _no_op_filter(), \
         patch.object(runner._pipeline, "analyze_batch", side_effect=mock_batch):
        result = await runner.run_for_vehicle(vid)
    assert result["analyzed"] == 1


async def test_run_for_vehicle_updates_raw_post_status(db):
    from pipeline.analysis.batch_runner import BatchAnalysisRunner
    vid = "v001"
    db.add(Vehicle(id=vid, name="海豹", brand="比亚迪"))
    await _seed_posts(db, vid, 2)
    runner = BatchAnalysisRunner(db)
    mock_batch = _make_batch_mock(sentiment="negative", event_tags=["召回"], confidence=0.8)
    with _no_op_filter(), \
         patch.object(runner._pipeline, "analyze_batch", side_effect=mock_batch):
        await runner.run_for_vehicle(vid)
    pending = (await db.execute(
        select(RawPost).where(RawPost.vehicle_id == vid, RawPost.analysis_status == "pending")
    )).scalars().all()
    assert len(pending) == 0


async def test_run_for_vehicle_no_pending_posts(db):
    from pipeline.analysis.batch_runner import BatchAnalysisRunner
    vid = "v001"
    db.add(Vehicle(id=vid, name="海豹", brand="比亚迪"))
    await db.commit()
    runner = BatchAnalysisRunner(db)
    result = await runner.run_for_vehicle(vid)
    assert result["analyzed"] == 0


async def test_run_for_vehicle_batch_size(db):
    from pipeline.analysis.batch_runner import BatchAnalysisRunner
    vid = "v001"
    db.add(Vehicle(id=vid, name="海豹", brand="比亚迪"))
    await _seed_posts(db, vid, 7)
    runner = BatchAnalysisRunner(db, batch_size=3)
    mock_batch = _make_batch_mock(sentiment="neutral", confidence=0.5)
    with _no_op_filter(), \
         patch.object(runner._pipeline, "analyze_batch", side_effect=mock_batch):
        result = await runner.run_for_vehicle(vid)
    assert result["analyzed"] == 7


async def test_run_all_pending(db):
    from pipeline.analysis.batch_runner import BatchAnalysisRunner
    v1 = Vehicle(id="v001", name="海豹", brand="比亚迪")
    v2 = Vehicle(id="v002", name="秦PLUS", brand="比亚迪")
    db.add_all([v1, v2])
    await db.commit()
    await _seed_posts(db, "v001", 2)
    await _seed_posts(db, "v002", 3)
    runner = BatchAnalysisRunner(db)
    mock_batch = _make_batch_mock(sentiment="neutral", confidence=0.5)
    with _no_op_filter(), \
         patch.object(runner._pipeline, "analyze_batch", side_effect=mock_batch):
        results = await runner.run_all_pending()
    assert len(results) == 2
    assert results[0]["analyzed"] + results[1]["analyzed"] == 5


class TestCommentTopNKnob:
    """评论补抓选帖旋钮（2026-10-15 舆情降本 R41：默认 30→10、平台 4→2）：env COMMENT_TOP_N 可覆盖。"""

    def test_default_15_for_active_social_platforms(self, monkeypatch):
        monkeypatch.delenv("COMMENT_TOP_N", raising=False)
        from pipeline.analysis.batch_runner import comment_top_n
        assert {comment_top_n(p) for p in ("xiaohongshu", "douyin")} == {15}  # 2026-10-16 R46

    def test_env_override_applies_to_all_platforms(self, monkeypatch):
        monkeypatch.setenv("COMMENT_TOP_N", "8")
        from pipeline.analysis.batch_runner import comment_top_n
        assert comment_top_n("xiaohongshu") == 8
        assert comment_top_n("douyin") == 8

    def test_invalid_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("COMMENT_TOP_N", "abc")
        from pipeline.analysis.batch_runner import comment_top_n
        assert comment_top_n("douyin") == 15  # 2026-10-16 R46 top10→15

    def test_stopped_and_non_social_platforms_return_zero(self, monkeypatch):
        monkeypatch.setenv("COMMENT_TOP_N", "8")
        from pipeline.analysis.batch_runner import comment_top_n
        # 2026-10-15 R23 停采平台（weibo/kuaishou）与非社媒/news 一律 0
        assert comment_top_n("news") == 0
        assert comment_top_n("weibo") == 0
        assert comment_top_n("kuaishou") == 0
        assert comment_top_n("") == 0

    @pytest.mark.asyncio
    async def test_selection_limit_follows_env_top_n(self, db, monkeypatch):
        """端到端接线：选帖 SQL 的 LIMIT 随旋钮变（env 调大/调小/回默认）。

        所有帖互动量均 >= 5（likes=i+10）以通过 T1.3 最低互动门槛，使本测试
        聚焦 LIMIT 旋钮而非门槛过滤。帖子内容不含故障词，避免 T1.2 缺陷词帖
        定向全量干扰计数。
        """
        from pipeline.analysis.batch_runner import select_top_posts_for_comments
        v = Vehicle(id="v-knob", name="海豹", brand="比亚迪")
        db.add(v)
        await db.commit()
        for i in range(20):
            db.add(RawPost(
                id=str(uuid.uuid4()), vehicle_id=v.id, source="tikhub",
                platform="douyin", title="t", content=f"c{i}",
                url=f"https://m.weibo.cn/status/{i}", likes=i + 10,
            ))
        await db.commit()

        monkeypatch.setenv("COMMENT_TOP_N", "7")
        assert len(await select_top_posts_for_comments(db, v.id)) == 7
        monkeypatch.setenv("COMMENT_TOP_N", "20")
        assert len(await select_top_posts_for_comments(db, v.id)) == 20
        monkeypatch.delenv("COMMENT_TOP_N")
        assert len(await select_top_posts_for_comments(db, v.id)) == 15  # 2026-10-16 R46 默认 15（20 帖池 >15）


class TestSelectTopPostsBackfill:
    """T1.3：背调排除营销号后顺延补位 + 最低互动门槛。"""

    @pytest.mark.asyncio
    async def test_marketing_account_excluded_then_backfill(self, db, monkeypatch):
        """排除 marketing_account 后不足 N，顺延补位取后续帖。"""
        from pipeline.analysis.batch_runner import select_top_posts_for_comments
        monkeypatch.setenv("COMMENT_TOP_N", "3")
        v = Vehicle(id="v-bf", name="海豹", brand="比亚迪")
        db.add(v)
        await db.commit()
        # 5 帖：前 3 互动最高但都是 marketing_account，应被排除；
        # 后 2 互动较低但 authentic，应顺延补位进榜。
        db.add(RawPost(
            id="mk1", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="mk1", likes=100, comments=10, author_type="marketing_account",
        ))
        db.add(RawPost(
            id="mk2", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="mk2", likes=90, comments=9, author_type="marketing_account",
        ))
        db.add(RawPost(
            id="mk3", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="mk3", likes=80, comments=8, author_type="marketing_account",
        ))
        db.add(RawPost(
            id="real1", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="real1", likes=50, comments=5,
        ))
        db.add(RawPost(
            id="real2", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="real2", likes=40, comments=4,
        ))
        await db.commit()
        selected = await select_top_posts_for_comments(db, v.id)
        ids = {p.id for p in selected}
        assert "mk1" not in ids and "mk2" not in ids and "mk3" not in ids
        assert "real1" in ids and "real2" in ids
        assert len(selected) == 2  # 仅 2 个 authentic 帖，不足 3 但到此为止

    @pytest.mark.asyncio
    async def test_engagement_threshold_excludes_low_interaction(self, db, monkeypatch):
        """likes+comments < 5 的帖不进榜（不补评论为 0 的帖白烧 API）。"""
        from pipeline.analysis.batch_runner import select_top_posts_for_comments
        monkeypatch.setenv("COMMENT_TOP_N", "5")
        v = Vehicle(id="v-thr", name="海豹", brand="比亚迪")
        db.add(v)
        await db.commit()
        # 高互动但 likes+comments < 5（shares 不计入门槛）——应被排除
        db.add(RawPost(
            id="low1", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="low1", likes=2, comments=2, shares=999,
        ))
        db.add(RawPost(
            id="low2", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="low2", likes=0, comments=0, shares=500,
        ))
        # 达标帖
        db.add(RawPost(
            id="ok1", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="ok1", likes=3, comments=3,
        ))
        db.add(RawPost(
            id="ok2", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="ok2", likes=5, comments=0,
        ))
        await db.commit()
        selected = await select_top_posts_for_comments(db, v.id)
        ids = {p.id for p in selected}
        assert "low1" not in ids
        assert "low2" not in ids
        assert "ok1" in ids
        assert "ok2" in ids  # likes=5 单独达标（5 >= 5）

    @pytest.mark.asyncio
    async def test_brand_official_and_dealer_excluded(self, db, monkeypatch):
        """brand_official/dealer 同样在 INAUTHENTIC_AUTHOR_TYPES 内被排除。"""
        from pipeline.analysis.batch_runner import select_top_posts_for_comments
        monkeypatch.setenv("COMMENT_TOP_N", "2")
        v = Vehicle(id="v-bo", name="海豹", brand="比亚迪")
        db.add(v)
        await db.commit()
        db.add(RawPost(
            id="bo", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="bo", likes=200, comments=20, author_type="brand_official",
        ))
        db.add(RawPost(
            id="dl", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="dl", likes=150, comments=15, author_type="dealer",
        ))
        db.add(RawPost(
            id="or", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="or", likes=30, comments=3,
        ))
        await db.commit()
        selected = await select_top_posts_for_comments(db, v.id)
        ids = {p.id for p in selected}
        assert "bo" not in ids and "dl" not in ids
        assert "or" in ids


class TestSelectTopPostsDefectDirected:
    """T1.2：缺陷词帖定向全量补评论。

    top-N 可能不含低互动的缺陷帖（故障帖天然互动偏低）。标题/正文含故障词
    （DEFECT_SEED_KEYWORDS 全量 12 词）但不在 top-N 的帖，全量补评论——不受
    top-N 限制、不受最低互动门槛约束。
    """

    @pytest.mark.asyncio
    async def test_defect_post_below_engagement_floor_still_selected(self, db, monkeypatch):
        """含故障词但 likes+comments < 5（不达门槛）的帖也被定向选中。"""
        from pipeline.analysis.batch_runner import select_top_posts_for_comments
        monkeypatch.setenv("COMMENT_TOP_N", "2")
        v = Vehicle(id="v-def", name="海豹", brand="比亚迪")
        db.add(v)
        await db.commit()
        # 2 个高互动正常帖占满 top-2（不含故障词）
        db.add(RawPost(
            id="hot1", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="提车分享，很满意", likes=100, comments=10,
        ))
        db.add(RawPost(
            id="hot2", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="日常讨论", likes=80, comments=8,
        ))
        # 缺陷帖：0 互动但含故障词"黑屏"
        db.add(RawPost(
            id="def1", vehicle_id=v.id, source="tikhub", platform="douyin",
            title="黑屏故障", content="今天突然黑屏了", likes=0, comments=0,
        ))
        await db.commit()
        selected = await select_top_posts_for_comments(db, v.id)
        ids = {p.id for p in selected}
        assert "hot1" in ids and "hot2" in ids  # top-2 正常
        assert "def1" in ids  # 缺陷帖定向选中（即使 0 互动）

    @pytest.mark.asyncio
    async def test_non_defect_post_below_floor_not_selected(self, db, monkeypatch):
        """不含故障词且不达门槛的帖不进定向列表（不白烧 API）。"""
        from pipeline.analysis.batch_runner import select_top_posts_for_comments
        monkeypatch.setenv("COMMENT_TOP_N", "2")
        v = Vehicle(id="v-nodef", name="海豹", brand="比亚迪")
        db.add(v)
        await db.commit()
        db.add(RawPost(
            id="hot1", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="提车分享", likes=100, comments=10,
        ))
        db.add(RawPost(
            id="hot2", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="日常讨论", likes=80, comments=8,
        ))
        # 低互动且不含故障词——不应被选中
        db.add(RawPost(
            id="low1", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="随便说说", likes=0, comments=0,
        ))
        await db.commit()
        selected = await select_top_posts_for_comments(db, v.id)
        ids = {p.id for p in selected}
        assert "low1" not in ids

    @pytest.mark.asyncio
    async def test_defect_post_already_in_top_n_not_duplicated(self, db, monkeypatch):
        """缺陷帖若已在 top-N（互动达标），不重复进定向列表。"""
        from pipeline.analysis.batch_runner import select_top_posts_for_comments
        monkeypatch.setenv("COMMENT_TOP_N", "3")
        v = Vehicle(id="v-dup", name="海豹", brand="比亚迪")
        db.add(v)
        await db.commit()
        # 高互动缺陷帖——既在 top-N 又含故障词，不应重复
        db.add(RawPost(
            id="hotdef", vehicle_id=v.id, source="tikhub", platform="douyin",
            title="异响严重", content="刹车异响，投诉无门", likes=200, comments=20,
        ))
        db.add(RawPost(
            id="hot2", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="日常讨论", likes=80, comments=8,
        ))
        db.add(RawPost(
            id="hot3", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="提车分享", likes=60, comments=6,
        ))
        await db.commit()
        selected = await select_top_posts_for_comments(db, v.id)
        ids = [p.id for p in selected]
        assert ids.count("hotdef") == 1  # 不重复

    @pytest.mark.asyncio
    async def test_defect_keyword_in_title_only_matched(self, db, monkeypatch):
        """故障词仅出现在 title 也命中（title LIKE 或 content LIKE）。"""
        from pipeline.analysis.batch_runner import select_top_posts_for_comments
        monkeypatch.setenv("COMMENT_TOP_N", "1")
        v = Vehicle(id="v-title", name="海豹", brand="比亚迪")
        db.add(v)
        await db.commit()
        db.add(RawPost(
            id="hot1", vehicle_id=v.id, source="tikhub", platform="douyin",
            content="日常讨论", likes=100, comments=10,
        ))
        # 故障词只在 title
        db.add(RawPost(
            id="tdef", vehicle_id=v.id, source="tikhub", platform="douyin",
            title="召回", content="召回", likes=0, comments=0,
        ))
        await db.commit()
        selected = await select_top_posts_for_comments(db, v.id)
        ids = {p.id for p in selected}
        assert "tdef" in ids


async def test_run_comment_analysis_loops_until_empty(db, monkeypatch):
    """run_comment_analysis 应循环处理所有 NULL 评论直到清零（>1 批）。"""
    from pipeline.analysis.batch_runner import BatchAnalysisRunner
    from models.schemas import PostComment, RawPost, Vehicle
    import uuid

    vid = "v-comment-loop"
    monkeypatch.setenv("COMMENT_POLARITY_DIRECT", "0")  # T4：钉维度回退轨（结构行为与模式无关）
    db.add(Vehicle(id=vid, name="测试车", brand="测试品牌"))
    # 一个 RawPost 作为 PostComment 的父（外键约束）
    db.add(RawPost(id="p-loop", vehicle_id=vid, source="test", platform="douyin",
                   content="父帖", analysis_status="analyzed"))
    # 喂 1200 条 NULL 评论 → 验证 2 批 + 收尾（每批 500）
    for i in range(1200):
        db.add(PostComment(
            id=str(uuid.uuid4()), post_id="p-loop", vehicle_id=vid,
            content=f"评论{i} 续航不错", author="用户",
        ))
    await db.commit()

    runner = BatchAnalysisRunner(db)

    # mock LocalABSAModel.get() 返回已加载 + predict_batch 返回固定 dim_sentiment
    from pipeline.analysis.local_absa import LocalABSAModel
    class FakeModel:
        _loaded = True
        def predict_batch(self, texts, batch_size=16):
            return [{"dim_sentiment": {"续航": 1}} for _ in texts]
    monkeypatch.setattr(LocalABSAModel, "get", lambda cls=LocalABSAModel: FakeModel())

    result = await runner.run_comment_analysis(vid)

    # 全部 1200 条应被分析
    assert result == 1200
    # 验证 NULL 评论已清零
    from sqlalchemy import func
    null_count = (await db.execute(
        select(func.count()).select_from(PostComment).where(
            PostComment.vehicle_id == vid,
            (PostComment.dim_sentiment.is_(None)) | (PostComment.dim_sentiment == ""),
        )
    )).scalar()
    assert null_count == 0


async def test_run_comment_analysis_handles_empty_content(db, monkeypatch):
    """空内容评论应被标记为 '{}' 不留 NULL，否则死循环。"""
    from pipeline.analysis.batch_runner import BatchAnalysisRunner
    from models.schemas import PostComment, RawPost, Vehicle
    from sqlalchemy import func, select as sa_select
    import uuid

    vid = "v-comment-empty"
    monkeypatch.setenv("COMMENT_POLARITY_DIRECT", "0")  # T4：钉维度回退轨
    db.add(Vehicle(id=vid, name="测试车", brand="测试品牌"))
    db.add(RawPost(id="p-empty", vehicle_id=vid, source="test", platform="douyin",
                   content="父帖", analysis_status="analyzed"))
    # 混合：2 条空/空白内容 + 2 条正常内容（PostComment.content nullable=False，
    # 故不测 None 行）
    db.add(PostComment(id=str(uuid.uuid4()), post_id="p-empty", vehicle_id=vid,
                       content="", author="用户"))
    db.add(PostComment(id=str(uuid.uuid4()), post_id="p-empty", vehicle_id=vid,
                       content="   ", author="用户"))
    db.add(PostComment(id=str(uuid.uuid4()), post_id="p-empty", vehicle_id=vid,
                       content="续航不错", author="用户"))
    db.add(PostComment(id=str(uuid.uuid4()), post_id="p-empty", vehicle_id=vid,
                       content="空间很大", author="用户"))
    await db.commit()

    runner = BatchAnalysisRunner(db)

    from pipeline.analysis.local_absa import LocalABSAModel
    class FakeModel:
        _loaded = True
        def predict_batch(self, texts, batch_size=16):
            return [{"dim_sentiment": {"续航": 1}} for _ in texts]
    monkeypatch.setattr(LocalABSAModel, "get", lambda cls=LocalABSAModel: FakeModel())

    # 加超时保护——若死循环会超时抛错
    import asyncio
    result = await asyncio.wait_for(runner.run_comment_analysis(vid), timeout=5.0)

    # 2 条正常内容被分析
    assert result == 2
    # 所有评论 dim_sentiment 非 NULL（空内容的也被标记为 "{}"）
    null_count = (await db.execute(
        sa_select(func.count()).select_from(PostComment).where(
            PostComment.vehicle_id == vid,
            (PostComment.dim_sentiment.is_(None)) | (PostComment.dim_sentiment == ""),
        )
    )).scalar()
    assert null_count == 0


async def test_run_comment_analysis_stops_on_error(db, monkeypatch):
    """predict_batch 第 2 批抛错时，第 1 批已 commit 的保留，异常向上传播。"""
    from pipeline.analysis.batch_runner import BatchAnalysisRunner
    from models.schemas import PostComment, RawPost, Vehicle
    from sqlalchemy import func, select as sa_select
    import uuid

    vid = "v-comment-err"
    monkeypatch.setenv("COMMENT_POLARITY_DIRECT", "0")  # T4：钉维度回退轨
    db.add(Vehicle(id=vid, name="测试车", brand="测试品牌"))
    db.add(RawPost(id="p-err", vehicle_id=vid, source="test", platform="douyin",
                   content="父帖", analysis_status="analyzed"))
    # 1200 条评论 → 第 1 批 500 成功，第 2 批抛错
    for i in range(1200):
        db.add(PostComment(
            id=str(uuid.uuid4()), post_id="p-err", vehicle_id=vid,
            content=f"评论{i}", author="用户",
        ))
    await db.commit()

    runner = BatchAnalysisRunner(db)

    from pipeline.analysis.local_absa import LocalABSAModel
    call_count = {"n": 0}
    class FlakyModel:
        _loaded = True
        def predict_batch(self, texts, batch_size=16):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("模拟推理 OOM")
            return [{"dim_sentiment": {"续航": 1}} for _ in texts]
    monkeypatch.setattr(LocalABSAModel, "get", lambda cls=LocalABSAModel: FlakyModel())

    import pytest
    with pytest.raises(RuntimeError, match="模拟推理 OOM"):
        await runner.run_comment_analysis(vid)

    # 第 1 批 500 条应已 commit（dim_sentiment 非 NULL）
    analyzed_count = (await db.execute(
        sa_select(func.count()).select_from(PostComment).where(
            PostComment.vehicle_id == vid,
            PostComment.dim_sentiment.is_not(None),
            PostComment.dim_sentiment != "",
        )
    )).scalar()
    assert analyzed_count == 500
    # 第 2 批未 commit，剩余 700 条仍 NULL
    null_count = (await db.execute(
        sa_select(func.count()).select_from(PostComment).where(
            PostComment.vehicle_id == vid,
            (PostComment.dim_sentiment.is_(None)) | (PostComment.dim_sentiment == ""),
        )
    )).scalar()
    assert null_count == 700


async def test_run_comment_analysis_does_not_block_event_loop(db, monkeypatch):
    """predict_batch 同步推理必须在线程池跑，不能阻塞 asyncio 事件循环。

    用一个故意 sleep 的同步 predict_batch 模拟 torch 推理；若 run_comment_analysis
    直接同步调用，事件循环被阻塞，并发 task 的 tick 计数不会涨。
    """
    import asyncio as _asyncio
    from pipeline.analysis.batch_runner import BatchAnalysisRunner
    from models.schemas import PostComment, RawPost, Vehicle
    import uuid

    vid = "v-comment-noblock"
    monkeypatch.setenv("COMMENT_POLARITY_DIRECT", "0")  # T4：钉维度回退轨
    db.add(Vehicle(id=vid, name="测试车", brand="测试品牌"))
    db.add(RawPost(id="p-noblock", vehicle_id=vid, source="test", platform="douyin",
                   content="父帖", analysis_status="analyzed"))
    # 5 条评论（够触发一次 predict_batch 即可，重点测阻塞而非循环）
    for i in range(5):
        db.add(PostComment(id=str(uuid.uuid4()), post_id="p-noblock", vehicle_id=vid,
                           content=f"评论{i} 续航不错", author="用户"))
    await db.commit()

    runner = BatchAnalysisRunner(db)

    from pipeline.analysis.local_absa import LocalABSAModel
    class SlowModel:
        _loaded = True
        def predict_batch(self, texts, batch_size=16):
            # 同步 sleep 0.5s 模拟 torch 推理阻塞
            import time as _t
            _t.sleep(0.5)
            return [{"dim_sentiment": {"续航": 1}} for _ in texts]
    monkeypatch.setattr(LocalABSAModel, "get", lambda cls=LocalABSAModel: SlowModel())

    # 并发 task：每 50ms 自增 tick。若事件循环被阻塞，tick 不涨。
    tick = {"n": 0}
    async def ticker():
        while True:
            await _asyncio.sleep(0.05)
            tick["n"] += 1
    ticker_task = _asyncio.create_task(ticker())
    try:
        await runner.run_comment_analysis(vid)
    finally:
        ticker_task.cancel()
        try:
            await ticker_task
        except _asyncio.CancelledError:
            pass

    # 0.5s 同步 sleep 期间，事件循环应能调度 ticker 至少 5 次（宽松阈值防 flake）
    assert tick["n"] >= 5, f"事件循环被阻塞，ticker 只跑了 {tick['n']} 次（应 ≥5）"
