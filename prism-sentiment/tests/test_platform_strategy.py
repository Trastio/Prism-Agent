"""Tests: platform-specific collection strategies."""
from pipeline.collectors.platform_strategy import (
    DOUYIN,
    KUAISHOU,
    WEIBO,
    XIAOHONGSHU,
    NEWS,
    PLATFORM_MAP,
    PLATFORM_STRATEGIES,
    get_strategy,
)


class TestPlatformStrategies:
    # OneAPI 时代（2026-09-10）起：社媒策略从风控规避改为按调用次数（计费）控制。
    # 2026-10-15 舆情降本（R32/R43）：社媒词数 15→6（核心1+双关键词2+缺陷词3）。
    def test_douyin_billing_quota(self):
        assert DOUYIN.risk_level == "low"
        assert DOUYIN.max_keywords == 6
        assert DOUYIN.max_pages == 2
        assert DOUYIN.inter_request_delay == 1

    def test_kuaishou_matches_douyin(self):
        # 2026-10-15 R23 停采归档：策略对象仍保留且与 douyin 同参（仅不在注册表）
        assert KUAISHOU.risk_level == DOUYIN.risk_level
        assert KUAISHOU.max_keywords == DOUYIN.max_keywords
        assert KUAISHOU.max_pages == DOUYIN.max_pages
        assert KUAISHOU.inter_request_delay == DOUYIN.inter_request_delay

    def test_xiaohongshu_billing_quota(self):
        assert XIAOHONGSHU.risk_level == "low"
        assert XIAOHONGSHU.max_keywords == 6
        assert XIAOHONGSHU.max_pages == 1
        assert XIAOHONGSHU.inter_request_delay == 1

    def test_weibo_billing_quota(self):
        # 2026-10-15 R23 停采归档：策略对象保留原 15 词参数（不在注册表）
        assert WEIBO.risk_level == "low"
        assert WEIBO.max_keywords == 15
        assert WEIBO.max_pages == 2
        assert WEIBO.inter_request_delay == 1

    def test_news_safe(self):
        assert NEWS.risk_level == "none"
        assert NEWS.is_safe is True
        assert NEWS.max_keywords == 10
        assert NEWS.inter_request_delay == 0


class TestPlatformMap:
    def test_all_keys(self):
        assert set(PLATFORM_MAP.keys()) == {
            "xiaohongshu", "weibo", "douyin", "kuaishou",
        }

    def test_mappings(self):
        assert PLATFORM_MAP["xiaohongshu"] == "xhs"
        assert PLATFORM_MAP["weibo"] == "wb"
        assert PLATFORM_MAP["douyin"] == "dy"
        assert PLATFORM_MAP["kuaishou"] == "ks"


class TestStrategyRegistry:
    def test_active_platforms_registered(self):
        # 2026-10-15 R23/R31：news/weibo/kuaishou 移出注册表（停采），
        # 策略对象保留归档、get_strategy 对其回落 _DEFAULT。
        assert set(PLATFORM_STRATEGIES.keys()) == {
            "xiaohongshu",
            "douyin",
            "chezhiwang",
        }

    def test_stopped_platforms_fall_back_to_default(self):
        for stopped in ("news", "weibo", "kuaishou"):
            s = get_strategy(stopped)
            assert s.risk_level == "high"
            assert s.max_keywords == 1

    def test_get_strategy_returns_correct(self):
        assert get_strategy("douyin") is DOUYIN
        assert get_strategy("xiaohongshu") is XIAOHONGSHU

    def test_get_strategy_unknown_defaults_conservative(self):
        s = get_strategy("unknown_platform")
        assert s.risk_level == "high"
        assert s.max_keywords == 1
        assert s.max_pages == 1
        assert s.inter_request_delay == 8
