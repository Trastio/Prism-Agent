"""platforms 单一真理源单测（主题 B Task1）。"""
from pipeline.platforms import (
    ALL_PLATFORMS,
    DOUYIN,
    KUAISHOU,
    NEWS,
    SOCIAL_PLATFORMS,
    WEIBO,
    XIAOHONGSHU,
    normalize_platform,
    platform_label,
    platform_query_values,
)


class TestNormalize:
    def test_abbreviation_to_full(self):
        assert normalize_platform("dy") == "douyin"
        assert normalize_platform("xhs") == "xiaohongshu"
        assert normalize_platform("wb") == "weibo"
        assert normalize_platform("ks") == "kuaishou"

    def test_full_name_idempotent(self):
        assert normalize_platform("douyin") == "douyin"
        assert normalize_platform("xiaohongshu") == "xiaohongshu"

    def test_case_insensitive(self):
        assert normalize_platform("DOUYIN") == "douyin"
        assert normalize_platform("Xhs") == "xiaohongshu"
        assert normalize_platform("WB") == "weibo"

    def test_none_and_empty(self):
        assert normalize_platform(None) is None
        assert normalize_platform("") is None

    def test_unknown_passthrough(self):
        assert normalize_platform("unknown_x") == "unknown_x"
        assert normalize_platform("news") == "news"


class TestLabel:
    def test_known(self):
        assert platform_label("xhs") == "小红书"
        assert platform_label("douyin") == "抖音"
        assert platform_label("ks") == "快手"
        assert platform_label("news") == "新闻源"

    def test_unknown(self):
        assert platform_label("foobar") == "foobar"

    def test_none(self):
        assert platform_label(None) == ""


class TestConstants:
    def test_social_excludes_news(self):
        # 2026-10-15 舆情降本 R23：社媒收敛为 小红书/抖音 两平台（调度面）；
        # WEIBO/KUAISHOU 身份常量保留（历史数据查询/归档用）。
        assert NEWS not in SOCIAL_PLATFORMS
        assert WEIBO not in SOCIAL_PLATFORMS
        assert KUAISHOU not in SOCIAL_PLATFORMS
        assert set(SOCIAL_PLATFORMS) == {XIAOHONGSHU, DOUYIN}

    def test_all_includes_news(self):
        assert NEWS in ALL_PLATFORMS
        assert len(ALL_PLATFORMS) == 6


class TestQueryValues:
    def test_full_name_includes_abbreviation(self):
        assert set(platform_query_values("douyin")) == {"douyin", "dy"}
        assert set(platform_query_values("weibo")) == {"weibo", "wb"}

    def test_abbreviation_includes_full(self):
        assert set(platform_query_values("xhs")) == {"xiaohongshu", "xhs"}
        assert set(platform_query_values("ks")) == {"kuaishou", "ks"}

    def test_none_and_empty(self):
        assert platform_query_values(None) == ()
        assert platform_query_values("") == ()

    def test_news_single(self):
        assert platform_query_values("news") == ("news",)

    def test_case_insensitive(self):
        assert set(platform_query_values("DOUYIN")) == {"douyin", "dy"}
