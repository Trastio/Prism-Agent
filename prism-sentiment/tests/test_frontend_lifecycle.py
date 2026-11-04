"""Tests: 前端生命周期（ECharts 白图 / 竞态 / 判空）。

前端无单元测试框架，用源码字符串断言验证修复模式存在。
"""
import re
from pathlib import Path

APP_JS = Path(__file__).resolve().parents[1] / "frontend" / "static" / "js" / "app.js"
INDEX_HTML = Path(__file__).resolve().parents[1] / "frontend" / "index.html"


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_echarts_empty_branch_not_destroy_canvas():
    """ECharts 空数据分支 dispose 旧实例，重渲染时重新 init（§11.1 白图修复）。

    v3 §11.1：空数据→有数据切换后图表永久空白，因 el.textContent 抹掉 canvas，
    重渲染时 if(!chart) 跳过 init。修复：空数据分支 dispose() + 置 null，
    重渲染时 if(!chart) 重新 init 新 canvas。
    """
    src = _src(APP_JS)
    dispose_count = src.count("Chart.dispose()")
    # 2026-10-17 change2 块A 并图（删负面声量独立图/观点标签榜）后 5→4
    assert dispose_count >= 4, (
        f"空数据分支应有 ≥5 处 dispose()（销毁旧实例让重渲染重新 init），实际 {dispose_count}"
    )


def test_echarts_reinit_after_empty():
    """空数据后重渲染应正常 init——重渲染前 dispose 旧实例或 clear 不销毁。"""
    src = _src(APP_JS)
    # 验证至少 sentimentDonutChart 空数据分支用 clear 不 dispose canvas
    # 或重渲染前有 dispose 调用
    has_clear = "chart.clear()" in src or ".clear()" in src
    assert has_clear, "应有 chart.clear() 调用"


def test_on_vehicle_change_request_id_guard():
    """onVehicleChange 加 requestId 守卫，旧请求晚回不覆盖新车数据（§11.2）。"""
    src = _src(APP_JS)
    # 修复后应有 requestId 或 _vehicleChangeId 计数器
    has_guard = ("requestId" in src or "_vehicleChangeId" in src
                 or "vehicleChangeToken" in src or "_lastVehicleChange" in src)
    assert has_guard, "onVehicleChange 应加 requestId/token 守卫防竞态"


def test_on_vehicle_change_clears_pipeline_poll():
    """P2-5：切车清理采集轮询并复位 loading（轮询按 currentVehicleId 取值，不清会漂移）。"""
    src = _src(APP_JS)
    m = re.search(r'async onVehicleChange\(\)\s*\{', src)
    assert m, "onVehicleChange 应存在"
    body = src[m.end():m.end() + 3500]
    assert "clearInterval(this.pipelinePollTimer)" in body, "切车应清 pipelinePollTimer"
    assert "this.loading = false" in body, "切车应复位 loading（无轮询则按钮永卡）"
    assert "_startPolling()" in body, "新车若有活跃 phase 应恢复轮询"


def test_static_assets_carry_version_markers():
    """cache-bust 自动化依赖 ?v= 标记：服务端按标记重写为 mtime，漏标记=漏重写。"""
    html = _src(INDEX_HTML)
    for asset in ("app.js?v=", "style.css?v=", "echarts.min.js?v=", "echarts-wordcloud.min.js?v="):
        assert asset in html, f"index.html 应引用 {asset}（带版本标记，服务端自动化重写的前提）"


def test_health_score_null_check_not_fallback():
    """index.html 健康分判空用 != null 而非 ||（防真实 0 分渲染成 --）（§11.3）。"""
    src = _src(INDEX_HTML)
    # health_score 渲染处应为 != null，不是 ||
    # 找 health_score 后紧跟的判空模式
    m = re.search(r'health_score[^}]*', src)
    assert m, "index.html 应有 health_score 渲染"
    render = m.group()
    assert "!= null" in render or "??" in render, (
        f"health_score 应用 != null 判空，实际: {render[:80]}"
    )
    assert "||" not in render, (
        f"health_score 不应用 || 判空（会把真实 0 分渲染成 --），实际: {render[:80]}"
    )


def test_postdetail_url_scheme_filter():
    """postDetail.url 过滤 javascript: 伪协议（§11.3 L3 替代项）。"""
    # safeUrl method 在 app.js，index.html 调 :href="safeUrl(...)"
    html = _src(INDEX_HTML)
    js = _src(APP_JS)
    # index.html 应用 safeUrl 过滤
    has_safe_call = "safeUrl(" in html or "sanitizeUrl(" in html
    # app.js 应有 safeUrl method 含 javascript: 过滤
    has_filter_impl = ("javascript:" in js and "safeUrl" in js) or "sanitizeUrl" in js
    assert has_safe_call, "index.html postDetail.url 应绑 safeUrl(...) 过滤"
    assert has_filter_impl, "app.js 应有 safeUrl method 过滤 javascript: 伪协议"
