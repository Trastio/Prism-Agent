"""T2（2026-10-15 舆情降本）负面帖评论追加测试：选帖逻辑 + 旋钮。

覆盖：batch_runner.comment_negative_extra_n / select_top_posts_for_comments
的负面追加段（词表命中、排除已选、独立 N 上限、零互动入选、LISTING_CALIBER
口径、_negative_directed 标记）。
"""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.schemas import Base, RawPost, Vehicle


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


def _post(db, vid, pid, content="", likes=0, comments=0, platform="douyin",
          author_type=None):
    db.add(RawPost(
        id=pid, vehicle_id=vid, source="tikhub", platform=platform,
        title="", content=content, likes=likes, comments=comments,
        author_type=author_type,
    ))


class TestNegativeExtraKnob:
    def test_default_env_zero_semantics(self, monkeypatch):
        from pipeline.analysis.batch_runner import comment_negative_extra_n
        monkeypatch.delenv("COMMENT_NEGATIVE_EXTRA_N", raising=False)
        assert comment_negative_extra_n("douyin") == 10
        monkeypatch.setenv("COMMENT_NEGATIVE_EXTRA_N", "5")
        assert comment_negative_extra_n("xiaohongshu") == 5
        assert comment_negative_extra_n("weibo") == 0   # 停采/非社媒平台 0
        assert comment_negative_extra_n("news") == 0


class TestNegativeExtraSelection:
    @pytest.mark.asyncio
    async def test_zero_interaction_negative_post_selected(self, db, monkeypatch):
        """核心语义：负面帖即使 0 互动也入选（topN 按互动排序会漏它们）。"""
        from pipeline.analysis.batch_runner import select_top_posts_for_comments
        monkeypatch.setenv("COMMENT_TOP_N", "2")
        v = Vehicle(id="v-neg1", name="海豹", brand="比亚迪")
        db.add(v)
        await db.commit()
        _post(db, v.id, "hot1", content="提车一个月，真香", likes=100, comments=20)
        _post(db, v.id, "hot2", content="续航扎实", likes=80, comments=15)
        _post(db, v.id, "neg1", content="维权两个月没人理，专员扯皮", likes=0)
        await db.commit()

        selected = await select_top_posts_for_comments(db, v.id)
        ids = {p.id for p in selected}
        assert "hot1" in ids and "hot2" in ids          # top-N 照常
        assert "neg1" in ids                            # 负面追加捞回 0 互动帖
        neg = next(p for p in selected if p.id == "neg1")
        assert getattr(neg, "_negative_directed", False)
        hots = [p for p in selected if p.id in ("hot1", "hot2")]
        assert all(not getattr(p, "_negative_directed", False) for p in hots)

    @pytest.mark.asyncio
    async def test_cap_and_interaction_order(self, db, monkeypatch):
        """独立 N 上限 + 追加池内部按互动降序（R41：追加 10/平台可 env 收）。"""
        from pipeline.analysis.batch_runner import select_top_posts_for_comments
        monkeypatch.setenv("COMMENT_TOP_N", "1")
        monkeypatch.setenv("COMMENT_NEGATIVE_EXTRA_N", "3")
        v = Vehicle(id="v-neg2", name="海豹", brand="比亚迪")
        db.add(v)
        await db.commit()
        _post(db, v.id, "top", content="真香", likes=500, comments=50)
        # 5 条自燃类负面帖（非缺陷词——缺陷词段不涉及），互动各异
        for i, likes in enumerate((40, 90, 10, 70, 5)):
            _post(db, v.id, f"neg{i}", content=f"隔壁车自燃了第{i}起",
                  likes=likes)
        await db.commit()

        selected = await select_top_posts_for_comments(db, v.id)
        neg_ids = [p.id for p in selected
                   if getattr(p, "_negative_directed", False)]
        assert len(neg_ids) == 3                          # cap 3
        assert set(neg_ids) == {"neg1", "neg3", "neg0"}   # 90 > 70 > 40 降序取头

    @pytest.mark.asyncio
    async def test_excludes_already_selected_and_defect_covered(self, db, monkeypatch):
        """高互动负面帖已进 top-N 不重复；缺陷词帖归缺陷段（全量语义）不占追加 cap。"""
        from pipeline.analysis.batch_runner import select_top_posts_for_comments
        monkeypatch.setenv("COMMENT_TOP_N", "2")
        monkeypatch.setenv("COMMENT_NEGATIVE_EXTRA_N", "5")
        v = Vehicle(id="v-neg3", name="海豹", brand="比亚迪")
        db.add(v)
        await db.commit()
        _post(db, v.id, "neg_hot", content="断裂门维权中，顶我", likes=300, comments=30)
        _post(db, v.id, "plain", content="外观好看", likes=200, comments=20)
        _post(db, v.id, "defect1", content="召回通知出了", likes=0)
        _post(db, v.id, "defect2", content="异响严重", likes=0)
        _post(db, v.id, "neg_cold", content="自燃舆情发酵", likes=1)
        await db.commit()

        selected = await select_top_posts_for_comments(db, v.id)
        by_id = {p.id: p for p in selected}
        assert "neg_hot" in by_id                        # 高互动负面先进 top-N
        assert not getattr(by_id["neg_hot"], "_negative_directed", False)
        assert not getattr(by_id["neg_hot"], "_defect_directed", False)
        for pid in ("defect1", "defect2"):               # 缺陷词段全量（不占追加 cap）
            assert getattr(by_id[pid], "_defect_directed", False)
            assert not getattr(by_id[pid], "_negative_directed", False)
        assert getattr(by_id["neg_cold"], "_negative_directed", False)

    @pytest.mark.asyncio
    async def test_listing_caliber_applies_to_negative_extra(self, db, monkeypatch):
        """LISTING_CALIBER 口径照挂：营销号负面帖不追加。"""
        from pipeline.analysis.batch_runner import select_top_posts_for_comments
        monkeypatch.setenv("COMMENT_TOP_N", "1")
        v = Vehicle(id="v-neg4", name="海豹", brand="比亚迪")
        db.add(v)
        await db.commit()
        _post(db, v.id, "top", content="真香", likes=100, comments=10)
        _post(db, v.id, "neg_mk", content="维权群曝光", likes=50,
              author_type="marketing_account")
        _post(db, v.id, "neg_real", content="起火了现场视频", likes=2)
        await db.commit()

        selected = await select_top_posts_for_comments(db, v.id)
        ids = {p.id for p in selected}
        assert "neg_mk" not in ids                       # 营销号被口径挡掉
        assert "neg_real" in ids

    @pytest.mark.asyncio
    async def test_stopped_platform_not_scanned(self, db, monkeypatch):
        """停采平台（weibo 存量帖）不进负面追加（白名单外 N=0）。"""
        from pipeline.analysis.batch_runner import select_top_posts_for_comments
        monkeypatch.setenv("COMMENT_TOP_N", "2")
        v = Vehicle(id="v-neg5", name="海豹", brand="比亚迪")
        db.add(v)
        await db.commit()
        _post(db, v.id, "dy_top", content="真香", likes=100, comments=10)
        _post(db, v.id, "dy_neg", content="断裂维权", likes=0)
        _post(db, v.id, "wb_neg", content="断裂维权", likes=0, platform="weibo")
        await db.commit()

        selected = await select_top_posts_for_comments(db, v.id)
        ids = {p.id for p in selected}
        assert "dy_neg" in ids
        assert "wb_neg" not in ids
