"""T3.2 Tests: Frontend files — 5 tests."""
import os

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


def test_index_html_exists():
    path = os.path.join(FRONTEND_DIR, "index.html")
    assert os.path.exists(path)


def test_index_html_contains_vue_and_echarts():
    path = os.path.join(FRONTEND_DIR, "index.html")
    content = open(path, encoding="utf-8").read()
    assert "vue" in content.lower() or "Vue" in content
    assert "echarts" in content.lower() or "ECharts" in content


def test_app_js_exists_and_parseable():
    path = os.path.join(FRONTEND_DIR, "static", "js", "app.js")
    assert os.path.exists(path)
    content = open(path, encoding="utf-8").read()
    assert "createApp" in content or "Vue" in content


def test_style_css_exists():
    path = os.path.join(FRONTEND_DIR, "static", "css", "style.css")
    assert os.path.exists(path)
    content = open(path, encoding="utf-8").read()
    assert len(content) > 100


def test_index_has_dashboard_sections():
    path = os.path.join(FRONTEND_DIR, "index.html")
    content = open(path, encoding="utf-8").read()
    assert "overview" in content.lower() or "概览" in content
    assert "trend" in content.lower() or "趋势" in content or "chart" in content.lower()


def test_default_range_is_30_days():
    """T1.5：默认 rangeStart 应为近 30 天（start30），而非 7 天。"""
    path = os.path.join(FRONTEND_DIR, "static", "js", "app.js")
    content = open(path, encoding="utf-8").read()
    # 默认值绑定到 start30
    assert "rangeStart: start30" in content
    # 不应回退为 start7 作默认
    assert "rangeStart: start7" not in content


def test_chart_granularity_adaptive():
    """T1.6：情感/负面趋势图应按时间窗跨度自适应日/周粒度。"""
    path = os.path.join(FRONTEND_DIR, "static", "js", "app.js")
    content = open(path, encoding="utf-8").read()
    assert "_chartGranularity" in content
    assert "_sentimentBucketKey" in content
    assert "86400000" in content  # 跨度计算


def test_sample_insufficient_banner():
    """T1.7：index.html 应有 sample_insufficient 提示。"""
    path = os.path.join(FRONTEND_DIR, "index.html")
    content = open(path, encoding="utf-8").read()
    assert "sample_insufficient" in content
    assert "样本不足" in content
