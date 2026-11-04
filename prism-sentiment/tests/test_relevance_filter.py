"""Tests: Two-stage relevance filter — rule engine + LLM."""
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

from pipeline.analysis.relevance_filter import (
    RuleBasedFilter, LLMRelevanceChecker, RelevanceFilter, Relevance, VehicleProfile,
)


def _make_profile():
    return VehicleProfile(
        name="比亚迪海豚", brand="比亚迪", launch_date="2021-08-01",
        vehicle_type="纯电两厢车", aliases=["海豚EV"],
    )


# ── Rule Engine Tests ─────────────────────────────────────────────────────

class TestRuleEngine:
    def setup_method(self):
        self.filter = RuleBasedFilter()
        self.profile = _make_profile()

    # Rule 1: Time window
    def test_reject_before_launch(self):
        post = {"title": "海豚很好", "content": "续航不错", "url": "",
                "published_at": date(2020, 5, 1), "platform": "news"}
        assert self.filter.check(post, self.profile) == Relevance.REJECT

    def test_pass_after_launch(self):
        post = {"title": "海豚很好", "content": "续航不错", "published_at": date(2025, 5, 1),
                "url": "", "platform": "news"}
        # Has car context "续航" → PASS
        assert self.filter.check(post, self.profile) == Relevance.PASS

    # Rule 2: URL blacklist
    def test_reject_config_page(self):
        post = {"title": "海豚配置", "content": "参数表", "url": "https://auto.com/海豚/config/",
                "published_at": date(2025, 5, 1), "platform": "news"}
        assert self.filter.check(post, self.profile) == Relevance.REJECT

    def test_reject_picture_page(self):
        post = {"title": "图片", "content": "壁纸", "url": "https://auto.com/海豚/picture/",
                "published_at": date(2025, 5, 1), "platform": "news"}
        assert self.filter.check(post, self.profile) == Relevance.REJECT

    # Rule 3: Exclude patterns
    def test_reject_animal_dolphin(self):
        post = {"title": "海洋馆海豚表演", "content": "海豚跳圈真可爱", "url": "",
                "published_at": date(2025, 5, 1), "platform": "wb"}
        assert self.filter.check(post, self.profile) == Relevance.REJECT

    def test_reject_emulator(self):
        post = {"title": "Dolphin模拟器下载", "content": "游戏模拟器", "url": "",
                "published_at": date(2025, 5, 1), "platform": "news"}
        assert self.filter.check(post, self.profile) == Relevance.REJECT

    def test_reject_document(self):
        post = {"title": "海豚.ppt", "content": "文档内容", "url": "",
                "published_at": date(2025, 5, 1), "platform": "news"}
        assert self.filter.check(post, self.profile) == Relevance.REJECT

    # Rule 4: Car context keywords
    def test_pass_car_context(self):
        post = {"title": "海豚测评", "content": "续航里程500公里", "url": "",
                "published_at": date(2025, 5, 1), "platform": "xhs"}
        assert self.filter.check(post, self.profile) == Relevance.PASS

    def test_pass_charging_keyword(self):
        # Rule 4 新规则：含本车名 + 汽车语境词 → PASS
        post = {"title": "海豚充电体验", "content": "快充速度不错", "url": "",
                "published_at": date(2025, 5, 1), "platform": "wb"}
        assert self.filter.check(post, self.profile) == Relevance.PASS

    def test_limbo_car_context_without_self_name(self):
        # Rule 4 新规则：不含本车名但有汽车语境词 → LIMBO（交 LLM 判断）
        post = {"title": "充电体验", "content": "快充速度不错", "url": "",
                "published_at": date(2025, 5, 1), "platform": "wb"}
        assert self.filter.check(post, self.profile) == Relevance.LIMBO

    # Rule 5: News with brand mention → PASS
    def test_pass_news_with_brand(self):
        post = {"title": "比亚迪海豚降价", "content": "最新消息", "url": "",
                "published_at": date(2025, 5, 1), "platform": "news", "source": "news"}
        assert self.filter.check(post, self.profile) == Relevance.PASS

    def test_pass_news_with_alias(self):
        post = {"title": "海豚EV上市", "content": "新车发布", "url": "",
                "published_at": date(2025, 5, 1), "platform": "news", "source": "news"}
        assert self.filter.check(post, self.profile) == Relevance.PASS

    # Limbo cases
    def test_limbo_no_context_no_brand(self):
        post = {"title": "海豚怎么样", "content": "最近看到很多讨论", "url": "",
                "published_at": date(2025, 5, 1), "platform": "wb"}
        # No car context, no brand → LIMBO
        assert self.filter.check(post, self.profile) == Relevance.LIMBO

    def test_limbo_short_social_post(self):
        post = {"title": "", "content": "海豚好看", "url": "",
                "published_at": date(2025, 5, 1), "platform": "xhs"}
        assert self.filter.check(post, self.profile) == Relevance.LIMBO


class TestVehicleProfile:
    def test_known_vehicle(self):
        from models.schemas import Vehicle
        v = Vehicle(id="v1", name="比亚迪海豚", brand="比亚迪")
        profile = VehicleProfile.from_vehicle(v)
        assert profile.launch_date == "2021-08-01"
        assert profile.vehicle_type == "纯电两厢车"
        assert "海豚EV" in profile.aliases

    def test_unknown_vehicle_fallback(self):
        from models.schemas import Vehicle
        v = Vehicle(id="v2", name="小米SU7", brand="小米")
        profile = VehicleProfile.from_vehicle(v)
        assert profile.name == "小米SU7"
        assert profile.launch_date == "2020-01-01"  # safe default


class TestLLMChecker:
    @pytest.mark.asyncio
    async def test_check_relevant_post(self):
        checker = LLMRelevanceChecker(api_key="test", api_url="http://test/v1/chat/completions")
        mock_resp = '{"relevant": true, "confidence": 0.95}'
        with patch.object(checker, "_call_api", new_callable=AsyncMock, return_value=mock_resp):
            is_rel, conf = await checker.check(
                {"title": "海豚续航实测", "content": "跑了500公里"},
                _make_profile(),
            )
        assert is_rel is True
        assert conf == 0.95

    @pytest.mark.asyncio
    async def test_check_irrelevant_post(self):
        checker = LLMRelevanceChecker(api_key="test", api_url="http://test/v1/chat/completions")
        mock_resp = '{"relevant": false, "confidence": 0.9}'
        with patch.object(checker, "_call_api", new_callable=AsyncMock, return_value=mock_resp):
            is_rel, conf = await checker.check(
                {"title": "海洋馆游记", "content": "海豚很可爱"},
                _make_profile(),
            )
        assert is_rel is False
        assert conf == 0.9

    @pytest.mark.asyncio
    async def test_handles_json_in_code_block(self):
        checker = LLMRelevanceChecker(api_key="test", api_url="http://test/v1/chat/completions")
        mock_resp = '```json\n{"relevant": true, "confidence": 0.8}\n```'
        with patch.object(checker, "_call_api", new_callable=AsyncMock, return_value=mock_resp):
            is_rel, conf = await checker.check(
                {"title": "test", "content": "test"},
                _make_profile(),
            )
        assert is_rel is True

    @pytest.mark.asyncio
    async def test_failure_returns_safe_default(self):
        checker = LLMRelevanceChecker(api_key="test", api_url="http://test/v1/chat/completions")
        with patch.object(checker, "_call_api", new_callable=AsyncMock, side_effect=Exception("API down")):
            is_rel, conf = await checker.check(
                {"title": "test", "content": "test"},
                _make_profile(),
            )
        assert is_rel is False
        assert conf == 0.0

    @pytest.mark.asyncio
    async def test_check_batch(self):
        checker = LLMRelevanceChecker(api_key="test", api_url="http://test/v1/chat/completions")
        responses = [
            '{"relevant": true, "confidence": 0.9}',
            '{"relevant": false, "confidence": 0.8}',
        ]
        with patch.object(checker, "_call_api", new_callable=AsyncMock, side_effect=responses):
            results = await checker.check_batch(
                [{"title": "A", "content": "a"}, {"title": "B", "content": "b"}],
                _make_profile(),
            )
        assert len(results) == 2
        assert results[0] == (True, 0.9)
        assert results[1] == (False, 0.8)


class TestRelevanceFilter:
    def test_filter_posts_rule_pass(self):
        rf = RelevanceFilter()
        posts = [
            {"title": "海豚续航好", "content": "充电体验", "url": "", "published_at": date(2025, 5, 1), "platform": "xhs"},
        ]
        results = rf.filter_posts(posts, _make_profile())
        assert results[0]["relevance_score"] == 1.0

    def test_filter_posts_rule_reject(self):
        rf = RelevanceFilter()
        posts = [
            {"title": "海豚动物", "content": "海洋馆海豚表演", "url": "",
             "published_at": date(2025, 5, 1), "platform": "xhs"},
        ]
        results = rf.filter_posts(posts, _make_profile())
        assert results[0]["relevance_score"] == 0.0
        assert results[0]["analysis_status"] == "irrelevant"

    def test_filter_posts_limbo_needs_llm(self):
        rf = RelevanceFilter()
        posts = [
            {"title": "海豚怎么样", "content": "最近很多讨论", "url": "",
             "published_at": date(2025, 5, 1), "platform": "wb"},
        ]
        results = rf.filter_posts(posts, _make_profile())
        assert results[0]["relevance_score"] is None  # needs LLM

    @pytest.mark.asyncio
    async def test_filter_limbo_with_llm(self):
        checker = LLMRelevanceChecker(api_key="test", api_url="http://test/v1/chat/completions")
        rf = RelevanceFilter(llm_checker=checker)

        posts = [
            {"title": "海豚怎么样", "content": "很多讨论", "url": "",
             "published_at": date(2025, 5, 1), "platform": "wb", "relevance_score": None},
        ]
        with patch.object(checker, "check_batch", new_callable=AsyncMock,
                          return_value=[(True, 0.85)]):
            results = await rf.filter_limbo_posts(posts, _make_profile())
        assert results[0]["relevance_score"] == 0.85

    @pytest.mark.asyncio
    async def test_filter_limbo_no_llm_defaults_to_keep(self):
        rf = RelevanceFilter(llm_checker=None)
        posts = [{"title": "t", "content": "c", "relevance_score": None}]
        results = await rf.filter_limbo_posts(posts, _make_profile())
        assert results[0]["relevance_score"] == 0.5  # default: keep

    def test_full_pipeline_stats(self):
        """Test that filter_posts produces correct statistics."""
        rf = RelevanceFilter()
        profile = _make_profile()
        posts = [
            # PASS: has car context + after launch + 本车名
            {"title": "海豚续航实测", "content": "充电快", "url": "",
             "published_at": date(2025, 5, 1), "platform": "xhs"},
            # REJECT: before launch
            {"title": "海豚好", "content": "续航好", "url": "",
             "published_at": date(2020, 5, 1), "platform": "news"},
            # REJECT: animal dolphin
            {"title": "海洋馆", "content": "海豚表演", "url": "",
             "published_at": date(2025, 5, 1), "platform": "wb"},
            # LIMBO: no context, no brand
            {"title": "海豚怎么样", "content": "讨论很多", "url": "",
             "published_at": date(2025, 5, 1), "platform": "wb"},
        ]
        results = rf.filter_posts(posts, profile)
        assert results[0]["relevance_score"] == 1.0   # PASS
        assert results[1]["relevance_score"] == 0.0   # REJECT (time)
        assert results[2]["relevance_score"] == 0.0   # REJECT (exclude)
        assert results[3]["relevance_score"] is None   # LIMBO


class TestLLMPromptCrossModel:
    def test_prompt_has_cross_model_rule(self):
        """LLM prompt 必须含'同品牌不同车型'排除规则 + 动态清单占位（v3）。"""
        from pipeline.analysis.relevance_filter import _RELEVANCE_PROMPT
        assert "同品牌不同车型" in _RELEVANCE_PROMPT, "prompt 缺同品牌不同车型校验"
        assert "{confusables}" in _RELEVANCE_PROMPT, "prompt 缺动态易混清单占位符"
        assert "配置版本" in _RELEVANCE_PROMPT, "prompt 缺 trim≠车型判别指引"

    def test_prompt_renders_vehicle_name(self):
        """prompt 渲染时 vehicle_name 应填入（v3：format 需带 confusables）。"""
        from pipeline.analysis.relevance_filter import _RELEVANCE_PROMPT
        rendered = _RELEVANCE_PROMPT.format(
            vehicle_name="海狮06", brand="比亚迪", vehicle_type="纯电SUV",
            confusables="- 海狮07（≠海狮06）",
            title="测试标题", content="测试内容",
        )
        assert "海狮06" in rendered
        assert "比亚迪" in rendered
        assert "海狮07" in rendered  # 动态清单注入


class TestVehicleProfileAliases:
    def test_tesla_model_3_aliases(self):
        """特斯拉 model 3 别名含型号变体，'特斯拉'不是别名。"""
        from pipeline.analysis.relevance_filter import VehicleProfile
        from models.schemas import Vehicle
        v = Vehicle(id="t1", name="特斯拉model 3", brand="特斯拉")
        p = VehicleProfile.from_vehicle(v)
        assert "Model 3" in p.aliases
        assert "model 3" in p.aliases
        assert "特斯拉" not in p.aliases, "'特斯拉'不是 model 3 别名"

    def test_tesla_brand_only_not_pass(self):
        """只含'特斯拉'不含'model 3'→ 不 PASS（进 LIMBO）。"""
        from pipeline.analysis.relevance_filter import VehicleProfile, RuleBasedFilter, Relevance
        from models.schemas import Vehicle
        v = Vehicle(id="t1", name="特斯拉model 3", brand="特斯拉")
        p = VehicleProfile.from_vehicle(v)
        f = RuleBasedFilter()
        post = {"title": "特斯拉销量创新高", "content": "财报数据", "url": "",
                "published_at": date(2025, 5, 1), "platform": "xhs"}
        assert f.check(post, p) == Relevance.LIMBO

    def test_sea_lion_06_aliases(self):
        """海狮06 别名含型号变体。"""
        from pipeline.analysis.relevance_filter import VehicleProfile
        from models.schemas import Vehicle
        v = Vehicle(id="t2", name="海狮06", brand="比亚迪")
        p = VehicleProfile.from_vehicle(v)
        assert "海狮06" in p.aliases

    def test_model3_no_space_alias(self):
        """Model3（无空格）是特斯拉model 3 别名。"""
        from pipeline.analysis.relevance_filter import VehicleProfile
        from models.schemas import Vehicle
        v = Vehicle(id="t1", name="特斯拉model 3", brand="特斯拉")
        p = VehicleProfile.from_vehicle(v)
        assert "Model3" in p.aliases, "aliases 应含 Model3 无空格变体"
        assert "model3" in p.aliases

    def test_sea_lion_06_ev_variant_aliases(self):
        """海狮06EV/DMI 是海狮06 别名（同车版本）。"""
        from pipeline.analysis.relevance_filter import VehicleProfile
        from models.schemas import Vehicle
        v = Vehicle(id="t2", name="海狮06", brand="比亚迪")
        p = VehicleProfile.from_vehicle(v)
        assert "海狮06EV" in p.aliases
        assert "海狮06DMI" in p.aliases

    def test_model_y_aliases(self):
        """Model Y 别名含 ModelY/Model YL（同车版本）。"""
        from pipeline.analysis.relevance_filter import VehicleProfile
        from models.schemas import Vehicle
        v = Vehicle(id="t3", name="Model Y", brand="特斯拉")
        p = VehicleProfile.from_vehicle(v)
        assert "ModelY" in p.aliases
        assert "Model YL" in p.aliases

    def test_mona_m03_aliases(self):
        """小鹏MONA M03 别名含 MONAM03。"""
        from pipeline.analysis.relevance_filter import VehicleProfile
        from models.schemas import Vehicle
        v = Vehicle(id="t4", name="小鹏MONA M03", brand="小鹏")
        p = VehicleProfile.from_vehicle(v)
        assert "MONAM03" in p.aliases
