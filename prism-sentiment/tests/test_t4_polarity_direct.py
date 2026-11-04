"""T4（舆情降本 change · 评论极性直出双轨）测试。

覆盖：parse_polarity_output / derive 双轨 / run_comment_analysis 极性模式
（队列筛选·哨兵·不写 dim）/ 迁移 v19 幂等 / 端点双轨计数。全 mock 模型，
零真实 GPU、零付费 API。
"""
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.schemas import Base, PostComment, RawPost, Vehicle
from pipeline.analysis.local_absa import parse_polarity_output
from pipeline.collectors.post_utils import derive_comment_sentiment


# ── 1. parse_polarity_output ─────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("1", "1"), ("0", "0"), ("-1", "-1"),
    ("  -1\n", "-1"),
    ("情感倾向：-1", "-1"),                      # 模型输出整句
    ("<think>让我想想</think>1", "1"),            # think 块剥离
    ("很好开，推荐", None),                        # 无合法词元
    ("", None), ("   ", None), (None, None),
    ("2", None), ("+1", None),
])
def test_parse_polarity_output(text, expected):
    assert parse_polarity_output(text) == expected


# ── 2. derive_comment_sentiment 双轨 ─────────────────────────────────

def test_derive_polarity_track_takes_precedence():
    # 极性列有效时覆盖 dim（含 dim 与极性"矛盾"的情况——新轨是权威）
    assert derive_comment_sentiment({"动力": 1.0}, "-1") == "negative"
    assert derive_comment_sentiment(None, "1") == "positive"
    assert derive_comment_sentiment("{}", "0") == "neutral"


def test_derive_falls_back_to_dim_when_polarity_invalid():
    assert derive_comment_sentiment({"续航": 0.5, "动力": 0.8}, None) == "positive"
    assert derive_comment_sentiment({"刹车": -0.5, "异响": -0.8}, "none") == "negative"
    assert derive_comment_sentiment({"价格": 0.2, "外观": -0.1}, "") == "neutral"


def test_derive_both_empty_returns_neutral():
    # 偏差记录：设计文本写"两皆空返回 None"，但 NULL→neutral 是 2026-10-03
    # spec 钉过的既有口径——"跳过未打标"由端点层 unanalyzed 检查承担。
    assert derive_comment_sentiment(None, None) == "neutral"
    assert derive_comment_sentiment("", "none") == "neutral"


# ── 3. run_comment_analysis 极性模式（mock 模型）──────────────────────

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


async def _seed(db, vehicle_id: str) -> None:
    db.add(Vehicle(id=vehicle_id, name="T4测试车", brand="T4", status="active"))
    now = datetime.utcnow()
    # 新评论（两列皆空，应被选中）
    for i, content in enumerate(["续航不错", "", "刹车异响"]):
        db.add(PostComment(
            id=f"c-new-{i}", post_id="p1", vehicle_id=vehicle_id,
            content=content, platform="xiaohongshu", collected_at=now,
        ))
    # 老评论（有 dim、无 polarity——不应被重标）
    db.add(PostComment(
        id="c-old", post_id="p1", vehicle_id=vehicle_id,
        content="老评论", platform="xiaohongshu", collected_at=now,
        dim_sentiment='{"动力": 1}',
    ))
    # 极性哨兵已处理的（不应被选中）
    db.add(PostComment(
        id="c-done", post_id="p1", vehicle_id=vehicle_id,
        content="哨兵评论", platform="xiaohongshu", collected_at=now,
        comment_polarity="none",
    ))
    db.add(RawPost(
        id="p1", vehicle_id=vehicle_id, platform="xiaohongshu", source="tikhub",
        content="帖子", collected_at=now, analysis_status="analyzed",
    ))
    await db.commit()


class _FakeModel:
    """绕过加载门槛：_loaded=True + 固定输出。"""

    _loaded = True

    def predict_batch(self, texts, batch_size=16, polarity=False):
        assert polarity is True
        # 按"续航=正 / 刹车=负 / 其余不可解析"造输出
        out = []
        for t in texts:
            if "续航" in t:
                out.append("1")
            elif "刹车" in t:
                out.append("-1")
            else:
                out.append("垃圾输出")
        return out


async def test_run_comment_analysis_polarity_mode(db, monkeypatch):
    from pipeline.analysis import batch_runner as br
    from pipeline.analysis.local_absa import LocalABSAModel

    monkeypatch.setenv("COMMENT_POLARITY_DIRECT", "1")
    await _seed(db, "v1")
    monkeypatch.setattr(LocalABSAModel, "get", classmethod(lambda cls: _FakeModel()))

    runner = br.BatchAnalysisRunner(db)
    n = await runner.run_comment_analysis("v1")

    rows = {c.id: c for c in (await db.execute(
        select(PostComment).where(PostComment.vehicle_id == "v1"))).scalars()}
    # 新评论：极性直出，dim 不写
    assert rows["c-new-0"].comment_polarity == "1"
    assert rows["c-new-0"].dim_sentiment is None
    assert rows["c-new-2"].comment_polarity == "-1"
    # 空内容 + 解析失败 → 哨兵 none（已处理，防死循环）
    assert rows["c-new-1"].comment_polarity == "none"
    # 老评论不重标、哨兵不重选
    assert rows["c-old"].dim_sentiment == '{"动力": 1}'
    assert rows["c-old"].comment_polarity is None
    assert n == 2  # 只算有效内容（空内容不计 analyze 数，与维度模式口径一致）


async def test_run_comment_analysis_env_off_keeps_dim_mode(db, monkeypatch):
    from pipeline.analysis import batch_runner as br
    from pipeline.analysis.local_absa import LocalABSAModel

    monkeypatch.setenv("COMMENT_POLARITY_DIRECT", "0")
    await _seed(db, "v2")
    monkeypatch.setattr(LocalABSAModel, "get", classmethod(lambda cls: _FakeModel()))

    class _FakeDimModel(_FakeModel):
        def predict_batch(self, texts, batch_size=16, polarity=False):
            assert polarity is False  # env 关=回退维度模式
            return [{"dim_sentiment": {"动力": 1}, "sentiment": "positive"}] * len(texts)

    monkeypatch.setattr(LocalABSAModel, "get", classmethod(lambda cls: _FakeDimModel()))
    runner = br.BatchAnalysisRunner(db)
    await runner.run_comment_analysis("v2")

    rows = {c.id: c for c in (await db.execute(
        select(PostComment).where(PostComment.vehicle_id == "v2"))).scalars()}
    assert rows["c-new-0"].dim_sentiment == '{"动力": 1}'
    assert rows["c-new-0"].comment_polarity is None


# ── 4. 迁移 v19 幂等 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_migration_v19_idempotent(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine
    from models import database as dbmod
    from models.schemas import Base

    db_file = tmp_path / "mig.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await dbmod._run_migrations(conn)
        await dbmod._run_migrations(conn)  # 幂等：第二遍不炸
    async with engine.connect() as conn:
        from sqlalchemy import text
        cols = [r[1] for r in (await conn.execute(
            text("PRAGMA table_info(post_comments)"))).fetchall()]
        await conn.close()
    assert "comment_polarity" in cols
    await engine.dispose()


# ── 5. 端点双轨计数 ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_overview_dual_track(db, monkeypatch):
    from api.routes import dashboard as dash
    from sqlalchemy.ext.asyncio import AsyncSession

    await _seed(db, "v3")
    # 直接调函数（session 注入），数据：2 新极性(1/-1) + 1 空内容哨兵
    # + 1 老维度(正) + 1 哨兵——LISTING_CALIBER 需要 AnalyzedPost 行
    from models.schemas import AnalyzedPost
    db.add(AnalyzedPost(
        post_id="p1", vehicle_id="v3", sentiment="positive",
        subject="self", analyzed_at=datetime.utcnow(),
    ))
    rows = {c.id: c for c in (await db.execute(
        select(PostComment).where(PostComment.vehicle_id == "v3"))).scalars()}
    rows["c-new-0"].comment_polarity = "1"
    rows["c-new-2"].comment_polarity = "-1"
    rows["c-new-1"].comment_polarity = "none"
    await db.commit()

    class _FakeSession:  # 端点里 session.execute(q) → 结果元组流
        async def execute(self, q):
            class R:
                def all(_s):
                    return [
                        ('{"动力": 1}', None),   # 老评论：dim 轨
                        (None, "1"),             # 新评论：极性轨
                        (None, "-1"),            # 新评论：极性轨
                        (None, None),            # 未打标 → unanalyzed
                        ("{}", None),            # 维度哨兵 → unanalyzed
                    ]
            return R()

    async def _fake_404(vehicle_id, session):
        return None

    monkeypatch.setattr(dash, "_get_vehicle_or_404", _fake_404)
    out = await dash.get_comment_sentiment_overview("v3", None, None, _FakeSession())
    assert out == {"positive": 2, "negative": 1, "neutral": 0,
                   "total": 3, "unanalyzed": 2}
