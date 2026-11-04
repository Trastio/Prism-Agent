"""T1.1 Tests: 采集关键词扩词——车名+故障词组合。

实测"风云T7 仪表盘"类缺陷帖只搜车名采不到（返回评测/提车帖）。拼成
"车名 故障词"后搜索可命中。本模块测 expand_defect_keywords 函数与
collect_vehicle 接线。2026-09-28 T1 全量启用 12 词（去 [:8] 截断）。
"""
import uuid
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.schemas import Base, CollectionStatus, RawPost, Vehicle
from pipeline.collectors.post_utils import (
    DEFECT_SEED_KEYWORDS,
    expand_defect_keywords,
)


class TestExpandDefectKeywords:
    def test_returns_twelve_combos(self):
        """每车 12 个扩展词（全量启用，去截断）。"""
        result = expand_defect_keywords("风云T7", "奇瑞")
        assert len(result) == 12

    def test_combo_format_is_vehicle_plus_defect(self):
        """扩展关键词是"车名+故障词"组合。"""
        result = expand_defect_keywords("风云T7")
        for combo in result:
            assert combo.startswith("风云T7 ")
            # 故障词来自种子表
            defect_word = combo[len("风云T7 "):]
            assert defect_word in DEFECT_SEED_KEYWORDS

    def test_uses_all_twelve_seed_words(self):
        """全量使用种子表 12 个故障词（不截断）。"""
        result = expand_defect_keywords("海豹")
        expected = [f"海豹 {w}" for w in DEFECT_SEED_KEYWORDS]
        assert result == expected

    def test_core_keyword_not_in_defect_combos(self):
        """主关键词（车名本身）不在缺陷扩词里——由调用方主关键词列表提供。"""
        result = expand_defect_keywords("海豹")
        assert "海豹" not in result

    def test_different_vehicles_produce_different_combos(self):
        a = expand_defect_keywords("风云T7")
        b = expand_defect_keywords("海豹")
        assert a != b
        assert all(c.startswith("风云T7 ") for c in a)
        assert all(c.startswith("海豹 ") for c in b)

    def test_empty_name_returns_empty(self):
        assert expand_defect_keywords("") == []

    def test_brand_param_accepted_but_unused(self):
        """brand 保留参数（后续可按品牌特化），当前不影响输出。"""
        assert expand_defect_keywords("M03", "小鹏") == expand_defect_keywords("M03")


class TestBuildCollectionKeywords:
    """_build_collection_keywords（2026-10-15 R43 拼序）：core + 双关键词2 +
    轮换缺陷词3 + 其余——[:6] 截断构成 = 核心1+双2+缺陷3。"""

    def _scheduler(self):
        from pipeline.scheduler import CollectionScheduler
        return CollectionScheduler.__new__(CollectionScheduler)

    def test_first_six_composition(self):
        """max_keywords=6 截断时，前 6 = 核心1 + 双关键词2 + 轮换缺陷词3。"""
        from pipeline.scheduler import rotate_defect_words
        s = self._scheduler()
        base = ["海豹"] + [f"海豹 变体{i}" for i in range(9)]
        result = s._build_collection_keywords(base, "海豹", "比亚迪")
        expected_defects = rotate_defect_words(expand_defect_keywords("海豹"))
        assert result[:3] == ["海豹", "海豹 变体0", "海豹 变体1"]
        assert result[3:6] == expected_defects  # 轮换组（与纯函数同日同组）
        # 变体 2+ 退到缺陷词之后（仍在全量列表里）
        assert "海豹 变体2" in result[6:]

    def test_full_list_still_contains_all_base(self):
        """非截断消费方仍拿得到全部基础词（顺序调整不丢词）。"""
        s = self._scheduler()
        base = ["风云T7"] + [f"风云T7 LLM{i}" for i in range(9)]
        result = s._build_collection_keywords(base, "风云T7", "奇瑞")
        assert result[0] == "风云T7"
        assert "风云T7 LLM0" in result
        assert all(kw in result for kw in base)

    def test_core_keyword_preserved(self):
        """主关键词（核心词）始终在结果里。"""
        s = self._scheduler()
        result = s._build_collection_keywords(["海豹EV"], "海豹", "比亚迪")
        assert "海豹EV" in result

    def test_dedup_with_base(self):
        """缺陷词与 base 重复时不重复加入。"""
        s = self._scheduler()
        base = ["风云T7", "风云T7 仪表盘"]  # 仪表盘已在 base
        result = s._build_collection_keywords(base, "风云T7", "奇瑞")
        assert result.count("风云T7 仪表盘") == 1

    def test_empty_defect_returns_base(self):
        """空车名 → 无缺陷词，返回 base 原样。"""
        s = self._scheduler()
        base = ["测试车"]
        result = s._build_collection_keywords(base, "", "")
        assert result == base


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
    v = Vehicle(id="v001", name="海豹", brand="比亚迪", search_keywords='["海豹EV"]')
    db.add(v)
    await db.commit()
    return v


class TestCollectVehicleWiring:
    """collect_vehicle 应把缺陷扩词拼进 all_keywords 传给采集阶段。"""

    @pytest.mark.asyncio
    async def test_social_platform_receives_defect_combos(self, db, vehicle):
        """_collect_social_platform 收到的关键词含"车名+故障词"组合（轮换组 3 个）。"""
        from pipeline.scheduler import CollectionScheduler, rotate_defect_words
        s = CollectionScheduler(db)
        captured: dict[str, list[str]] = {}

        async def _fake_collect_social(vid, platform, keywords, progress, **kw):
            captured[platform] = list(keywords)
            return [], []

        with patch.object(s, "_collect_social_platform", AsyncMock(side_effect=_fake_collect_social)), \
             patch.object(s, "_resolve_collector", AsyncMock(return_value=(object(), "tikhub"))), \
             patch.object(s, "_crawl_full_texts", AsyncMock(side_effect=lambda p: p)), \
             patch.object(s, "_resolve_urls", AsyncMock(side_effect=lambda p: p)), \
             patch.object(s, "_run_dedup", side_effect=lambda p: p), \
             patch.object(s, "_expand_keywords_if_needed", AsyncMock(return_value=["海豹EV"])), \
             patch.object(s._index, "is_available", AsyncMock(return_value=False)), \
             patch("pipeline.scheduler.asyncio.sleep", AsyncMock()):
            await s.collect_vehicle(vehicle.id)
        # 至少一个平台收到含缺陷扩词的关键词列表
        flat = [kw for kws in captured.values() for kw in kws]
        assert "海豹EV" in flat  # 主关键词仍在
        # 2026-10-15 R43：缺陷词按日轮换，只进 3 个（与纯函数同日同组；
        # 两平台各收同一份 all_keywords，按去重集合断言）
        expected = rotate_defect_words(expand_defect_keywords("海豹"))
        assert all(kw in flat for kw in expected)
        assert len({kw for kw in flat if kw.startswith("海豹 ")}) == 3

    @pytest.mark.asyncio
    async def test_news_not_called_after_deprecation(self, db, vehicle):
        """R31（2026-10-15）：news 停采——collect_vehicle 全程不调 _collect_news。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        mock_news = AsyncMock(return_value=[])

        with patch.object(s, "_collect_news", mock_news), \
             patch.object(s, "_collect_social_platform", AsyncMock(return_value=([], []))), \
             patch.object(s, "_resolve_collector", AsyncMock(return_value=(object(), "tikhub"))), \
             patch.object(s, "_crawl_full_texts", AsyncMock(side_effect=lambda p: p)), \
             patch.object(s, "_resolve_urls", AsyncMock(side_effect=lambda p: p)), \
             patch.object(s, "_run_dedup", side_effect=lambda p: p), \
             patch.object(s, "_expand_keywords_if_needed", AsyncMock(return_value=["海豹EV"])), \
             patch.object(s._index, "is_available", AsyncMock(return_value=False)):
            await s.collect_vehicle(vehicle.id)
        mock_news.assert_not_called()
