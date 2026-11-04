"""Tests: 4-layer Heat Metric Calculator."""
import uuid
from datetime import date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.schemas import Base, HeatMetric, RawPost, Vehicle


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


@pytest_asyncio.fixture
async def vehicle(db):
    v = Vehicle(id="v001", name="海豹", brand="比亚迪")
    db.add(v)
    await db.commit()
    return v


def _make_post(vid, day, source="cdp", platform="xhs", likes=10, comments=5, shares=2,
               author_type="organic", is_promo=False, analysis_status="analyzed"):
    return RawPost(
        id=str(uuid.uuid4()), vehicle_id=vid, source=source, platform=platform,
        title="test", content="content", published_at=datetime.combine(day, datetime.min.time()),
        likes=likes, comments=comments, shares=shares,
        author_type=author_type, is_promo=is_promo,
        analysis_status=analysis_status,
    )


async def _seed(db, *posts):
    for p in posts:
        db.add(p)
    await db.commit()


async def _seed(db, *posts):
    for p in posts:
        db.add(p)
    await db.commit()


class TestAttentionIndex:
    """Layer 1: attention_index from 百度指数, set by scheduler into HeatMetric directly."""

    @pytest.mark.asyncio
    async def test_preserves_scheduler_attention_index(self, db, vehicle):
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        db.add(HeatMetric(id=str(uuid.uuid4()), vehicle_id=vehicle.id, date=day, attention_index=2500.0))
        await db.commit()
        await _seed(db, _make_post(vehicle.id, day))

        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        assert metric.attention_index == 2500.0

    @pytest.mark.asyncio
    async def test_default_attention_falls_back_to_interaction(self, db, vehicle):
        """无 scheduler 数据时 attention 回退为 interaction_intensity（不再死 0）。"""
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        await _seed(db, _make_post(vehicle.id, day))
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        # 默认 post: likes=10,comments=5,shares=2 → interaction=55
        # log1p(55)*1000 ≈ 4.0254*1000 = 4025.4
        assert metric.attention_index == 4025.4

    @pytest.mark.asyncio
    async def test_returns_metric_when_only_attention_index_exists(self, db, vehicle):
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        db.add(HeatMetric(id=str(uuid.uuid4()), vehicle_id=vehicle.id, date=day, attention_index=2500.0))
        await db.commit()

        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        assert metric is not None
        assert metric.attention_index == 2500.0
        assert metric.discussion_volume == 0
        assert metric.media_volume == 0
        assert metric.interaction_intensity == 0.0

    @pytest.mark.asyncio
    async def test_fallback_to_interaction_when_no_baidu_index(self, db, vehicle):
        """无百度指数数据时，attention_index 应回退为 interaction_intensity（让热度图有值）。"""
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        await _seed(db, _make_post(vehicle.id, day, source="cdp", likes=10, comments=5, shares=2))
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        # interaction = 10×1 + 5×5 + 2×10 = 55
        # 无百度指数时 attention 对数压缩: log1p(55)*1000 ≈ 4025.4
        assert metric.attention_index == 4025.4

    @pytest.mark.asyncio
    async def test_fallback_updates_existing_metric(self, db, vehicle):
        """已存在 HeatMetric（attention=0）在 fallback 时也应被更新，不只新建时。"""
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        # 预建 existing HeatMetric（attention=0，模拟 scheduler 没填百度指数）
        db.add(HeatMetric(id=str(uuid.uuid4()), vehicle_id=vehicle.id, date=day, attention_index=0.0))
        await db.commit()
        await _seed(db, _make_post(vehicle.id, day, source="cdp", likes=10, comments=5, shares=2))
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        # existing attention=0 + interaction=55 → fallback
        # 对数压缩: log1p(55)*1000 ≈ 4025.4
        assert metric.attention_index == 4025.4


class TestDiscussionVolume:
    """Layer 2: social comment count — sum of RawPost.comments for platform != news posts."""

    @pytest.mark.asyncio
    async def test_counts_social_posts_across_sources(self, db, vehicle):
        """P0-1 回归：判定按 platform 而非 source 白名单——oneapi/tikhub 帖
        （曾因白名单只有 "cdp" 全被排除，discussion_volume 连日全 0）照常计入。"""
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        await _seed(db,
            _make_post(vehicle.id, day, source="cdp", platform="xhs"),
            _make_post(vehicle.id, day, source="oneapi", platform="wb"),
            _make_post(vehicle.id, day, source="tikhub", platform="dy"),
        )
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        # 默认 fixture comments=5，3 帖合计 15
        assert metric.discussion_volume == 15

    @pytest.mark.asyncio
    async def test_excludes_news_posts(self, db, vehicle):
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        await _seed(db,
            _make_post(vehicle.id, day, source="cdp", platform="xhs"),
            _make_post(vehicle.id, day, source="bocha", platform="news"),
        )
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        # news 帖不计入 discussion（platform 语义反例：source 无关）
        assert metric.discussion_volume == 5


class TestMediaVolume:
    """Layer 3: article count from news sources (platform == 'news')."""

    @pytest.mark.asyncio
    async def test_counts_bocha_and_anspire(self, db, vehicle):
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        await _seed(db,
            _make_post(vehicle.id, day, source="bocha", platform="news"),
            _make_post(vehicle.id, day, source="anspire", platform="news"),
            _make_post(vehicle.id, day, source="cdp", platform="xhs"),
        )
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        assert metric.media_volume == 2

    @pytest.mark.asyncio
    async def test_zero_when_no_news(self, db, vehicle):
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        await _seed(db, _make_post(vehicle.id, day, source="cdp", platform="xhs"))
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        assert metric.media_volume == 0


class TestInteractionIntensity:
    """Layer 4: weighted engagement (likes×1 + comments×5 + shares×10) from social posts."""

    @pytest.mark.asyncio
    async def test_weighted_interaction_formula(self, db, vehicle):
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        await _seed(db,
            _make_post(vehicle.id, day, source="cdp", likes=10, comments=5, shares=2),
        )
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        # 10×1 + 5×5 + 2×10 = 10 + 25 + 20 = 55
        assert metric.interaction_intensity == 55.0

    @pytest.mark.asyncio
    async def test_sums_weighted_social_engagement(self, db, vehicle):
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        await _seed(db,
            _make_post(vehicle.id, day, source="cdp", likes=100, comments=50, shares=30),
            _make_post(vehicle.id, day, source="cdp", likes=200, comments=100, shares=70),
        )
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        # (100+200)×1 + (50+100)×5 + (30+70)×10 = 300 + 750 + 1000 = 2050
        assert metric.interaction_intensity == 2050.0

    @pytest.mark.asyncio
    async def test_excludes_news_engagement(self, db, vehicle):
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        await _seed(db,
            _make_post(vehicle.id, day, source="cdp", likes=100, comments=50, shares=30),
            _make_post(vehicle.id, day, source="bocha", platform="news", likes=999, comments=999, shares=999),
        )
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        # 100×1 + 50×5 + 30×10 = 100 + 250 + 300 = 650
        assert metric.interaction_intensity == 650.0

    @pytest.mark.asyncio
    async def test_zero_when_no_social_posts(self, db, vehicle):
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        await _seed(db, _make_post(vehicle.id, day, source="bocha", platform="news"))
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        assert metric.interaction_intensity == 0.0


class TestIntegration:
    @pytest.mark.asyncio
    async def test_full_four_layer_scenario(self, db, vehicle):
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)

        db.add(HeatMetric(id=str(uuid.uuid4()), vehicle_id=vehicle.id, date=day, attention_index=1927.0))
        await db.commit()

        await _seed(db,
            _make_post(vehicle.id, day, source="cdp", platform="xhs", likes=500, comments=200, shares=100),
            _make_post(vehicle.id, day, source="tikhub", platform="wb", likes=300, comments=150, shares=50),
            _make_post(vehicle.id, day, source="oneapi", platform="dy", likes=1000, comments=500, shares=200),
            _make_post(vehicle.id, day, source="bocha", platform="news"),
            _make_post(vehicle.id, day, source="anspire", platform="news"),
        )
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)

        assert metric.attention_index == 1927.0
        # discussion = social 帖评论之和：200 + 150 + 500 = 850（news 帖被过滤）
        assert metric.discussion_volume == 850
        assert metric.media_volume == 2
        # (500+300+1000)×1 + (200+150+500)×5 + (100+50+200)×10 = 1800+4250+3500 = 9550
        # news posts excluded from social engagement (platform != news)
        assert metric.interaction_intensity == 9550.0

    @pytest.mark.asyncio
    async def test_calculate_range(self, db, vehicle):
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        d1, d2 = date(2026, 5, 19), date(2026, 5, 20)
        await _seed(db, _make_post(vehicle.id, d1), _make_post(vehicle.id, d2))
        calc = HeatMetricCalculator(db)
        results = await calc.calculate_range(vehicle.id, d1, d2)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_no_posts_returns_none(self, db, vehicle):
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        calc = HeatMetricCalculator(db)
        result = await calc.calculate_daily(vehicle.id, date(2026, 5, 20))
        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_on_recalculate(self, db, vehicle):
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        await _seed(db, _make_post(vehicle.id, day))
        calc = HeatMetricCalculator(db)
        await calc.calculate_daily(vehicle.id, day)
        await calc.calculate_daily(vehicle.id, day)
        rows = (await db.execute(select(HeatMetric))).scalars().all()
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_get_metrics(self, db, vehicle):
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        await _seed(db, _make_post(vehicle.id, day))
        calc = HeatMetricCalculator(db)
        await calc.calculate_daily(vehicle.id, day)
        metrics = await calc.get_metrics(vehicle.id, day, day)
        assert len(metrics) == 1


class TestRankAndPercentile:
    """Rank + percentile over 30-day window."""

    @pytest.mark.asyncio
    async def test_metric_has_rank_and_percentile(self, db, vehicle):
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)

        # Add historical metrics for percentile calculation
        for i in range(5):
            d = date(2026, 5, 15) + timedelta(days=i)
            db.add(HeatMetric(
                id=str(uuid.uuid4()), vehicle_id=vehicle.id, date=d,
                interaction_intensity=float(20 + i * 10),
            ))
        await db.commit()

        await _seed(db, _make_post(vehicle.id, day))
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        assert metric is not None
        assert metric.rank is not None
        assert metric.percentile is not None
        assert metric.rank != "无历史数据"

    @pytest.mark.asyncio
    async def test_no_history_gives_default_rank(self, db, vehicle):
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)

        # No historical metrics, but the metric itself has interaction > 0
        await _seed(db, _make_post(vehicle.id, day, likes=10, comments=5, shares=2))
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)

        # Only 1 value in the 30-day window (itself), rank_pos=0
        # percentile = (1 - 0/1)*100 = 100.0 -> "近30天最高"
        assert metric is not None
        assert metric.rank == "近30天最高"
        assert metric.percentile == 100.0

    @pytest.mark.asyncio
    async def test_top_rank_when_highest(self, db, vehicle):
        """Highest intensity in window gets '近30天最高'."""
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)

        # Historical metrics with low values
        for i in range(10):
            d = date(2026, 5, 10) + timedelta(days=i)
            db.add(HeatMetric(
                id=str(uuid.uuid4()), vehicle_id=vehicle.id, date=d,
                interaction_intensity=float(10 + i),
            ))
        await db.commit()

        # Today's metric will have interaction_intensity = 55.0
        # which is higher than all historical (max 19).
        # Sorted desc: [55, 19, 18, ..., 10]. rank_pos=0
        # percentile = (1 - 0/11)*100 = 100.0 -> "近30天最高"
        await _seed(db, _make_post(vehicle.id, day, likes=10, comments=5, shares=2))
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)

        assert metric.rank == "近30天最高"
        assert metric.interaction_intensity == 55.0
        assert metric.percentile >= 99

    @pytest.mark.asyncio
    async def test_zero_interaction_no_history(self, db, vehicle):
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)

        # Only a news post — interaction_intensity will be 0
        await _seed(db, _make_post(vehicle.id, day, source="bocha", platform="news"))
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)

        assert metric is not None
        assert metric.rank == "无历史数据"
        assert metric.percentile == 0.0


class TestSocialPlatformSemantics:
    """P0-1：社媒帖判定 = platform != "news"（原 source 白名单随 provider 枚举增殖漏配）。"""

    @pytest.mark.asyncio
    async def test_oneapi_tikhub_posts_count_as_social(self, db, vehicle):
        """09-10 起 source=oneapi / 09-11 起 source=tikhub 的帖必须进 discussion。"""
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        await _seed(db,
            _make_post(vehicle.id, day, source="oneapi", platform="weibo",
                       likes=10, comments=7, shares=0),
            _make_post(vehicle.id, day, source="tikhub", platform="xiaohongshu",
                       likes=0, comments=3, shares=0),
        )
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        assert metric.discussion_volume == 10            # 7 + 3
        # 10×1 + 7×5 + 0 + 0×1 + 3×5 + 0 = 10 + 35 + 15 = 60
        assert metric.interaction_intensity == 60.0

    @pytest.mark.asyncio
    async def test_news_posts_never_count_as_social(self, db, vehicle):
        """反例：只有 news 帖的日子 discussion/interaction 必须为 0（媒体量另计）。"""
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        await _seed(db,
            _make_post(vehicle.id, day, source="bocha", platform="news",
                       likes=999, comments=500, shares=99),
            _make_post(vehicle.id, day, source="anspire", platform="news",
                       likes=1, comments=1, shares=1),
        )
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        assert metric.discussion_volume == 0
        assert metric.interaction_intensity == 0.0
        assert metric.media_volume == 2

    def test_source_whitelist_enum_removed(self):
        """白名单枚举已删（防回归）：模块不再导出 SOCIAL_SOURCES。"""
        from pipeline.analysis import heat_calculator
        assert not hasattr(heat_calculator, "SOCIAL_SOURCES")
        assert heat_calculator.NEWS_PLATFORM == "news"


class TestHeatCaliberAuditPhase2:
    """Phase 2 §9.1: 热度口径加 SELF+AUTH，竞品/官方/营销号/导流帖不计入。"""

    @pytest.mark.asyncio
    async def test_heat_excludes_competitor_post(self, db, vehicle):
        """competitor 帖不计入 discussion_volume。"""
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        from models.schemas import AnalyzedPost
        day = date(2026, 5, 20)
        # self 帖（计入，无 AnalyzedPost 行兜底为 self）
        p_self = _make_post(vehicle.id, day, comments=10)
        # competitor 帖（不计入，建 AnalyzedPost subject=competitor）
        p_comp = _make_post(vehicle.id, day, comments=999)
        db.add_all([p_self, p_comp,
            AnalyzedPost(id=str(uuid.uuid4()), post_id=p_comp.id, vehicle_id=vehicle.id,
                         sentiment="neutral", subject="competitor")])
        await db.commit()
        calc = HeatMetricCalculator(db)
        await calc.calculate_daily(vehicle.id, day)
        metric = (await db.execute(select(HeatMetric).where(
            HeatMetric.vehicle_id == vehicle.id, HeatMetric.date == day))).scalar_one()
        # discussion_volume = 社媒评论数，competitor 的 999 不计入
        assert metric.discussion_volume == 10, f"competitor 帖不应计入，实际 {metric.discussion_volume}"

    @pytest.mark.asyncio
    async def test_heat_excludes_official_marketing_post(self, db, vehicle):
        """官方/经销商/营销号帖不计入 discussion_volume。"""
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 21)
        await _seed(db,
            _make_post(vehicle.id, day, author_type="organic", comments=10),
            _make_post(vehicle.id, day, author_type="brand_official", comments=999),
            _make_post(vehicle.id, day, author_type="dealer", comments=999),
            _make_post(vehicle.id, day, author_type="marketing_account", comments=999),
        )
        calc = HeatMetricCalculator(db)
        await calc.calculate_daily(vehicle.id, day)
        metric = (await db.execute(select(HeatMetric).where(
            HeatMetric.vehicle_id == vehicle.id, HeatMetric.date == day))).scalar_one()
        assert metric.discussion_volume == 10, f"官方/经销商/营销号帖不应计入，实际 {metric.discussion_volume}"

    @pytest.mark.asyncio
    async def test_heat_excludes_promo_post(self, db, vehicle):
        """is_promo=True 导流帖不计入 discussion_volume。"""
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 22)
        await _seed(db,
            _make_post(vehicle.id, day, is_promo=False, comments=10),
            _make_post(vehicle.id, day, is_promo=True, comments=999),
        )
        calc = HeatMetricCalculator(db)
        await calc.calculate_daily(vehicle.id, day)
        metric = (await db.execute(select(HeatMetric).where(
            HeatMetric.vehicle_id == vehicle.id, HeatMetric.date == day))).scalar_one()
        assert metric.discussion_volume == 10, f"导流帖不应计入，实际 {metric.discussion_volume}"


class TestHeatTimeWindowAuditPhase2:
    """Phase 2 §9.2: 热度时间用 coalesce，NULL published_at 用 collected_at 兜底。"""

    @pytest.mark.asyncio
    async def test_heat_null_published_at_counted(self, db, vehicle):
        """published_at=NULL 但 collected_at 在窗内 → 计入 discussion_volume。"""
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 23)
        # 帖1：published_at 正常 + collected_at 同日
        p1 = _make_post(vehicle.id, day, comments=10)
        # 帖2：published_at=None + collected_at 在窗内
        p2 = _make_post(vehicle.id, day, comments=20)
        p2.published_at = None
        p2.collected_at = datetime.combine(day, datetime.min.time())
        await _seed(db, p1, p2)
        calc = HeatMetricCalculator(db)
        await calc.calculate_daily(vehicle.id, day)
        metric = (await db.execute(select(HeatMetric).where(
            HeatMetric.vehicle_id == vehicle.id, HeatMetric.date == day))).scalar_one()
        # 两帖都应计入（coalesce 兜底 NULL published_at）
        assert metric.discussion_volume == 30, f"NULL published_at 应 coalesce 兜底计入，实际 {metric.discussion_volume}"
