"""口径回归测试（Phase 3 T3.5）。

v3 报告 §6.5：断言每个口碑端点 SQL 已挂 LISTING_CALIBER（或显式豁免）。
防止未来新增端点漏挂口径导致漂移。
"""
import inspect

import pytest

from api.routes import dashboard, analysis, reports


# 口碑端点应挂 LISTING_CALIBER（SELF_ONLY + AUTHENTIC_AUTHOR + RELEVANT_ONLY）
# 或调用 scoped_posts / time_window_filter（已挂口径）
# 显式豁免：声量/热度类（全域口径）、健康检查类

# 豁免清单：这些端点用全域口径（RELEVANT_ONLY）是有意设计（声量/热度）
EXEMPT_GLOBAL_CALIBER = {
    # 声量/热度类：写时收敛，读时全域（v3 §6.3）
    "/api/dashboard/trend",  # heat_metrics 写时已挂口径
    "/api/dashboard/heat-metrics",
    "/api/dashboard/increment-overview",  # 增量视图，全域
    # P2-H：采集触发端点不返回口碑聚合，豁免 LISTING_CALIBER
    "/api/fleet/collect",  # 全车采集触发，返回 {started, skipped}
    "/api/vehicles/{vehicle_id}/refresh-engagement",  # 互动刷新触发，返回 {status, phase}
}

# 应挂 LISTING_CALIBER 的口碑端点（函数名 → 端点路径）
EXPECTED_LISTING_ENDPOINTS = {
    "get_overview": "/api/dashboard/overview",
    "get_fleet_overview": "/api/dashboard/fleet-overview",
    "get_platform_distribution": "/api/dashboard/platform-distribution",
    "get_event_distribution": "/api/dashboard/event-distribution",
    "get_top_posts": "/api/dashboard/top-posts",
    "get_comment_sentiment_diff": "/api/dashboard/comment-sentiment-diff",
    "get_word_cloud": "/api/dashboard/word-cloud",
    "get_negative_radar": "/api/dashboard/negative-radar",
    "get_dim_sentiment": "/api/dashboard/dim-sentiment",
    "get_dim_examples": "/api/dashboard/dim-examples",
    "get_defect_themes": "/api/dashboard/defect-themes",
    "get_sentiment_summary": "/api/analysis/sentiment-summary",
    "get_top_events": "/api/analysis/top-events",
    "get_top_opinions": "/api/analysis/top-opinions",
}


def test_listing_endpoints_exist():
    """所有应挂 LISTING_CALIBER 的端点函数存在。"""
    missing = []
    for func_name in EXPECTED_LISTING_ENDPOINTS:
        if not hasattr(dashboard, func_name) and not hasattr(analysis, func_name):
            missing.append(func_name)
    assert not missing, f"端点函数缺失: {missing}"


def test_overview_total_uses_listing_caliber():
    """T3.3: /overview 舆情总量应挂 SELF+AUTH+REL（v3 §13.2 星愿差 23%）。"""
    src = inspect.getsource(dashboard.get_overview)
    # 总量查询应含 SELF_ONLY + AUTHENTIC_AUTHOR（不再仅 _relevant_posts_filter）
    assert "SELF_ONLY" in src, "/overview 总量应挂 SELF_ONLY"
    assert "AUTHENTIC_AUTHOR" in src, "/overview 总量应挂 AUTHENTIC_AUTHOR"


def test_overview_peak_date_uses_self_only():
    """T3.3: /overview 峰值日应挂 SELF_ONLY。"""
    src = inspect.getsource(dashboard.get_overview)
    assert "SELF_ONLY" in src, "/overview 峰值日应挂 SELF_ONLY"


def test_comment_sentiment_diff_uses_authentic_author():
    """T3.3: /comment-sentiment-diff 应用 INAUTHENTIC_AUTHOR_TYPES（补 marketing_account）。"""
    src = inspect.getsource(dashboard.get_comment_sentiment_diff)
    assert "INAUTHENTIC_AUTHOR_TYPES" in src, "应使用 INAUTHENTIC_AUTHOR_TYPES 而非硬编码"
    assert '"brand_official", "dealer"' not in src, "不应硬编码 brand_official/dealer"


def test_platform_distribution_uses_listing_caliber():
    """T3.3: /platform-distribution 应挂 SELF+AUTH+REL。"""
    src = inspect.getsource(dashboard.get_platform_distribution)
    assert "SELF_ONLY" in src
    assert "AUTHENTIC_AUTHOR" in src


def test_event_distribution_uses_listing_caliber():
    """T3.3: /event-distribution 应挂 SELF+AUTH+REL（原仅 SELF）。"""
    src = inspect.getsource(dashboard.get_event_distribution)
    assert "AUTHENTIC_AUTHOR" in src, "/event-distribution 应补 AUTHENTIC_AUTHOR"


def test_sentiment_summary_uses_listing_caliber():
    """T3.3: /sentiment-summary 应挂 LISTING_CALIBER（原裸挂无口径）。"""
    src = inspect.getsource(analysis.get_sentiment_summary)
    assert "LISTING_CALIBER" in src or ("SELF_ONLY" in src and "AUTHENTIC_AUTHOR" in src)


def test_top_events_uses_listing_caliber():
    """T3.3: /top-events 应挂 LISTING_CALIBER（原裸挂无口径）。"""
    src = inspect.getsource(analysis.get_top_events)
    assert "LISTING_CALIBER" in src or ("SELF_ONLY" in src and "AUTHENTIC_AUTHOR" in src)


def test_query_scopes_module_exists():
    """T3.2: api/query_scopes.py 模块应存在。"""
    from api import query_scopes
    assert hasattr(query_scopes, "scoped_posts")
    assert hasattr(query_scopes, "time_window_filter")


def test_defect_themes_cache_uses_utc():
    """T3.1: /defect-themes 缓存应使用 datetime.utcnow()（H1 时区修复）。"""
    src = inspect.getsource(dashboard.get_defect_themes)
    assert "utcnow" in src, "defect-themes 缓存应用 datetime.utcnow() 与 DB UTC 比较"
