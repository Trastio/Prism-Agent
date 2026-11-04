# -*- coding: utf-8 -*-
"""cross-model-leak-v3 回归：三层边界（采集词元/Rule4/prompt 动态清单）。

背景（2026-10-08 审计）：银河A7 混入星舰7/奥迪A7L/索尼A7V 等 ~147 帖全车队污染。
根因 = 采集层弱词元子串命中 + Rule4 子串洞 + LLM prompt 静态三家示例。
"""
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from models.schemas import Base, RawPost, Vehicle
from pipeline.analysis.relevance_filter import (
    RelevanceFilter, RuleBasedFilter, VehicleProfile, _format_confusables,
)
from pipeline.scheduler import (
    CollectionScheduler, _extract_brand_keywords, _name_tokens, _token_in_text,
)


# ── 采集层：词元边界 ─────────────────────────────────────────────────

class TestTokenBoundary:
    def test_a7_not_matching_a7l_or_a7v(self):
        """字母数字词元带边界：A7 ⊄ A7L / A7V（奥迪A7L/索尼A7V 不再放行）。"""
        assert _token_in_text("A7", "奥迪a7l 提车24小时大灯被砸") is False
        assert _token_in_text("A7", "索尼a7v 相机评测") is False
        assert _token_in_text("A7", "25款银河a7 em高速异响") is True
        assert _token_in_text("A7", "裸车11w拿下银河 A7") is True  # 空格边界

    def test_m03_not_matching_mona03(self):
        assert _token_in_text("M03", "小鹏mona03 怎么选") is False
        assert _token_in_text("M03", "小鹏 mona m03 提车") is True

    def test_model_not_matching_model3(self):
        """Model Y 丢单字符 Y 后剩 Model 词元：带边界仍命中 Model 3——靠车名级 AND 根治。"""
        assert _token_in_text("Model", "model 3 提车作业") is True
        assert _token_in_text("Model", "remodel 装修") is False

    def test_chinese_token_keeps_substring(self):
        """纯中文词元维持子串（"银河"须命中"吉利银河A7"）。"""
        assert _token_in_text("银河", "吉利银河a7 车主") is True
        assert _token_in_text("银河", "银河系漫游指南") is True  # 有意保留（撞名交给语义层）

    def test_name_tokens_excludes_brand(self):
        assert _name_tokens("银河A7") == ["银河", "A7"]
        assert _extract_brand_keywords("银河A7", "吉利") == ["银河", "A7", "吉利"]


# ── 采集层：社媒车名级 AND 放行 ───────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _post(title, platform="xiaohongshu", url=None):
    # URL 唯一（_store_posts 按 URL path 去重，同 URL 第二帖会被丢）
    url = url or f"https://x.com/{abs(hash(title)) % 10**8}"
    return {"title": title, "content": "", "url": url,
            "source": "tikhub", "platform": platform,
            "published_at": (date.today() - timedelta(days=1)).isoformat()}


async def test_social_and_gate_rejects_sibling_models(db):
    """社媒：银河A7 词元 AND——星舰7（含银河无A7）不再放行。"""
    async with db() as session:
        session.add(Vehicle(id="v1", name="银河A7", brand="吉利"))
        s = CollectionScheduler(session)
        n = await s._store_posts("v1", [
            _post("吉利银河星舰7 大晚上开着开着突然黑屏"),
            _post("吉利银河星舰7简直不要太离谱"),
        ], min_date=None, vehicle_name="银河A7", vehicle_brand="吉利")
    assert n == {}  # 全被品牌过滤拦下


async def test_social_and_gate_allows_own_trim(db):
    """社媒：A7 星舰版（trim）词元全命中仍放行——不误杀本车配置版帖。"""
    async with db() as session:
        session.add(Vehicle(id="v2", name="银河A7", brand="吉利"))
        s = CollectionScheduler(session)
        n = await s._store_posts("v2", [
            _post("25款银河A7 EM高速异响终于解决了"),
            _post("银河A7 星舰版 纯电续航140km"),
        ], min_date=None, vehicle_name="银河A7", vehicle_brand="吉利")
    assert n.get("xiaohongshu") == 2


async def test_social_alias_token_sets_pass(db):
    """C-1 回归：alias 连写/简写拼法的本车帖不能被 AND 门丢弃。

    review 实测反例：model3提车作业 / MONAM03车主群 / 海狮06EV 510km旗舰提车
    （旧 OR 门放行，v3 初版 AND 门不认 aliases 静默丢弃——净回归）。
    """
    async with db() as session:
        session.add(Vehicle(id="va", name="特斯拉model 3", brand="特斯拉"))
        s = CollectionScheduler(session)
        n = await s._store_posts("va", [
            _post("model3提车作业分享"),
        ], min_date=None, vehicle_name="特斯拉model 3", vehicle_brand="特斯拉",
            aliases=["Model 3", "model3", "Model3"])
    assert n.get("xiaohongshu") == 1

    async with db() as session:
        session.add(Vehicle(id="vb", name="小鹏MONA M03", brand="小鹏"))
        s = CollectionScheduler(session)
        n = await s._store_posts("vb", [
            _post("MONAM03车主群 入群须知"),
            _post("M03提车一月感受"),
        ], min_date=None, vehicle_name="小鹏MONA M03", vehicle_brand="小鹏",
            aliases=["MONAM03", "M03"])
    assert n.get("xiaohongshu") == 2

    async with db() as session:
        session.add(Vehicle(id="vc", name="海狮06", brand="比亚迪"))
        s = CollectionScheduler(session)
        n = await s._store_posts("vc", [
            _post("海狮06EV 510km旗舰提车"),
        ], min_date=None, vehicle_name="海狮06", vehicle_brand="比亚迪",
            aliases=["海狮06EV", "海狮06DMI"])
    assert n.get("xiaohongshu") == 1


async def test_social_rejects_cross_brand_name_collision(db):
    """社媒：奥迪A7L（含a7l 不含独立a7）不再放行；单中文词元车（海豚）不受影响。"""
    async with db() as session:
        session.add(Vehicle(id="v3", name="银河A7", brand="吉利"))
        s = CollectionScheduler(session)
        n = await s._store_posts("v3", [
            _post("奥迪A7L提车24小时大灯被砸"),
            _post("【索尼A7V 彻底重构】3300万像素"),
        ], min_date=None, vehicle_name="银河A7", vehicle_brand="吉利")
    assert n == {}

    # 单词元车（比亚迪海豚→[海豚]）：AND 退化为单命中，行为不变
    async with db() as session:
        session.add(Vehicle(id="v4", name="比亚迪海豚", brand="比亚迪"))
        s = CollectionScheduler(session)
        n = await s._store_posts("v4", [
            _post("海豚测评 3000公里小结"),
        ], min_date=None, vehicle_name="比亚迪海豚", vehicle_brand="比亚迪")
    assert n.get("xiaohongshu") == 1


async def test_news_gate_removed_with_deprecation(db):
    """（2026-10-15 R31：news 停采，OR 门随分支删除——news 帖不再有独立放行
    通道；历史 news 存量帖的展示不受影响。用例改为守护"news 帖如今走社媒
    AND 门"：不含车名词元的品牌级新闻会被过滤。）"""
    async with db() as session:
        session.add(Vehicle(id="v5", name="银河A7", brand="吉利"))
        s = CollectionScheduler(session)
        n = await s._store_posts("v5", [
            _post("吉利银河全系9月销量出炉", platform="news"),
        ], min_date=None, vehicle_name="银河A7", vehicle_brand="吉利")
    assert n.get("news", 0) == 0  # 无车名词元（银河A7）→ AND 门拦截


# ── Rule 4 边界 ──────────────────────────────────────────────────────

class TestRule4Boundary:
    def _profile(self, name, brand, aliases=None):
        return VehicleProfile(name=name, brand=brand, launch_date="2020-01-01",
                              aliases=aliases or [])

    def test_t9l_not_pass_via_t9_substring(self):
        """风云T9L 帖不再因含"T9"（风云T9 子串）而 Rule4 PASS——进 LLM。"""
        p = self._profile("风云T9", "奇瑞")
        f = RuleBasedFilter()
        post = {"title": "试驾风云T9L，优缺点太明显", "content": "续航 车机",
                "platform": "xiaohongshu"}
        assert f.check(post, p).value != "pass"  # 不 PASS（LIMBO 或 REJECT）

    def test_own_name_still_passes(self):
        p = self._profile("风云T9", "奇瑞")
        f = RuleBasedFilter()
        post = {"title": "风云T9 提车两周体验", "content": "续航 车机",
                "platform": "xiaohongshu"}
        assert f.check(post, p).value == "pass"

    def test_a9l_not_pass_via_a9(self):
        p = self._profile("风云A9", "奇瑞")
        f = RuleBasedFilter()
        post = {"title": "A9L新车5000公里真实吐槽", "content": "越开越闹心 驾驶",
                "platform": "xiaohongshu"}
        assert f.check(post, p).value != "pass"

    def test_brand_prefix_short_name_still_matches(self):
        """去品牌前缀短名（比亚迪海豚→海豚）仍命中——边界不误伤中文短名。"""
        p = self._profile("比亚迪海豚", "比亚迪")
        f = RuleBasedFilter()
        post = {"title": "海豚测评：城市通勤利器", "content": "充电 续航",
                "platform": "xiaohongshu"}
        assert f.check(post, p).value == "pass"


# ── 动态易混清单 ─────────────────────────────────────────────────────

class TestConfusables:
    def test_format_nonempty(self):
        out = _format_confusables(["星舰7", "银河E5", "银河M9"], "银河A7", "吉利")
        assert "星舰7" in out and "银河E5" in out
        assert "≠银河A7" in out

    def test_format_empty_placeholder(self):
        out = _format_confusables([], "海豚", "比亚迪")
        assert "暂无其他在库车型" in out

    async def test_relevance_prompt_contains_dynamic_list(self):
        """LLM prompt 注入动态清单（静态三家硬编码已删）。"""
        from pipeline.analysis.relevance_filter import LLMRelevanceChecker, _RELEVANCE_PROMPT
        profile = VehicleProfile(name="银河A7", brand="吉利", launch_date="2020-01-01",
                                 confusables=["星舰7", "银河E5"])
        checker = LLMRelevanceChecker(api_key="k", api_url="http://x")
        with patch.object(checker, "_call_api", new=AsyncMock(return_value='{"relevant": false, "confidence": 0.9}')) as m:
            await checker.check({"title": "吉利银河星舰7黑屏", "content": "车机 故障"}, profile)
        sent_prompt = m.call_args[0][0]
        assert "星舰7" in sent_prompt and "银河E5" in sent_prompt
        # 静态三家硬编码示例已移除（撞名提示段的通用词"风云"不算——它不是车型示例）
        assert "风云A9" not in sent_prompt and "海狮06" not in sent_prompt
        assert "配置版本" in sent_prompt  # trim≠车型判别指引

    async def test_analyzer_prompt_contains_dynamic_list(self):
        from pipeline.analysis.analyzer import AnalysisPipeline, COMBINED_ANALYSIS_PROMPT
        p = AnalysisPipeline.__new__(AnalysisPipeline)  # 不走 __init__（免 env 依赖）
        p._api_key, p._api_url, p._model = "k", "http://x", "m"
        p._use_anthropic_format = False
        with patch.object(p, "_call_api", new=AsyncMock(
                return_value='{"event_tags": [], "opinion_tags": [], "sentiment": "neutral", '
                             '"dim_sentiment": {}, "subject": "competitor", "subject_name": "星舰7", "confidence": 0.9}')) as m:
            await p.analyze_single("吉利银河星舰7 大晚上黑屏", "银河A7", "吉利",
                                   confusables=["星舰7", "银河E5"])
        sent_prompt = m.call_args[0][0]
        assert "星舰7" in sent_prompt and "T9L≠T9" in sent_prompt
