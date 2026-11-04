"""T1.3 Tests: 车质网 ChezhiwangCollector — 质量投诉采集。

覆盖：seriesId 解析、列表页解析、详情正文提取、窗口过滤、错误容错。
不依赖网络（httpx.MockTransport 注入响应）。
"""
import pytest
import httpx

from pipeline.collectors.chezhiwang_collector import (
    ChezhiwangCollector,
    resolve_series_id,
)


def _make_collector(transport, **kw):
    """构造 collector 并 monkey-patch 其 client 工厂使用 MockTransport。"""
    c = ChezhiwangCollector(**kw)
    # patch _fetch_list_page / _fetch_detail 使用的 AsyncClient 构造
    import pipeline.collectors.chezhiwang_collector as mod
    orig_init = httpx.AsyncClient.__init__

    def patched_init(self, *a, **k):
        k.setdefault("transport", transport)
        return orig_init(self, *a, **k)

    mod.httpx.AsyncClient.__init__ = patched_init
    return c, lambda: setattr(mod.httpx.AsyncClient, "__init__", orig_init)


# ── seriesId 解析 ─────────────────────────────────────────────────────────────


def test_resolve_series_id_exact():
    assert resolve_series_id("星愿") == 4070
    assert resolve_series_id("SU7") == 3902
    assert resolve_series_id("MONA M03") == 4025
    # 3511 是"斯达泰克Model Y"同名错配（BBS title 实证），更正为特斯拉中国
    assert resolve_series_id("Model Y") == 3003


def test_resolve_series_id_t25_full_coverage():
    """T2.5 全量补齐：23 车在监车型全部命中（brandsHaveSeries.js 查得+BBS 探活核验）。"""
    from pipeline.collectors.chezhiwang_collector import SERIES_ID_MAP
    expected = {
        "MG4X": 4527, "元PLUS": 3234, "元UP": 3898, "华境s": 4505,
        "海狮06": 4266, "特斯拉model 3": 2554, "铂智3X": 4156,
        "银河A7": 4283, "银河E5": 3997, "银河M9": 4338, "银河TT": 4607,
        "零跑A10": 4429, "零跑B01": 4267, "零跑B10": 4187, "零跑D19": 4449,
        "风云A9": 4568, "风云T11": 4376, "风云T7": 4590, "风云T9L": 4446,
    }
    for name, sid in expected.items():
        assert SERIES_ID_MAP.get(name) == sid, name
        assert resolve_series_id(name) == sid, name
    # DB 车名带品牌前缀的包含匹配
    assert resolve_series_id("吉利银河E5") == 3997
    assert resolve_series_id("奇瑞风云T7") == 4590


def test_resolve_series_id_contains_match():
    # 车型名带品牌前缀也应命中（"小鹏MONA M03" 含 "MONA M03"）
    assert resolve_series_id("小鹏MONA M03") == 4025
    assert resolve_series_id("小米SU7") == 3902


def test_resolve_series_id_unknown_returns_none():
    assert resolve_series_id("不存在的车") is None
    assert resolve_series_id("") is None
    assert resolve_series_id(None) is None


# ── 列表页解析 ─────────────────────────────────────────────────────────────────


_LIST_HTML = (
    '<a href="https://bbs.12365auto.com/threadforum/20260918/274813.shtml#f=s">小米SU7尾灯内裂进水 售后逼车主分摊费用</a>'
    '<a href="https://bbs.12365auto.com/threadforum/20260908/274269.shtml#f=s">小米SU7多轮毂氧化腐蚀只修不换</a>'
    '<a href="https://bbs.12365auto.com/threadforum/20260101/250000.shtml#f=s">老帖应被窗口过滤掉</a>'
    '<a href="https://bbs.12365auto.com/threadforum/20260920/274900.shtml#f=s">短</a>'
)


def _list_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=_LIST_HTML.encode("utf-8"))


async def test_list_page_parses_posts():
    transport = httpx.MockTransport(_list_handler)
    c, restore = _make_collector(transport, max_pages=1)
    try:
        posts = await c.search("小米SU7", "2026-06-01", "2026-09-27")
    finally:
        restore()
    # 4 anchors, "短" filtered (len<4), "老帖" filtered (before floor) → 2
    assert len(posts) == 2
    assert posts[0]["title"] == "小米SU7尾灯内裂进水 售后逼车主分摊费用"
    assert posts[0]["url"] == "https://bbs.12365auto.com/threadforum/20260918/274813.shtml"
    assert posts[0]["published_at"] == "2026-09-18"
    assert posts[0]["platform"] == "chezhiwang"
    assert posts[0]["source"] == "chezhiwang"


async def test_list_page_protocol_relative_url():
    """//bbs.12365auto.com/... 协议相对 URL 应补 https:"""
    html = '<a href="//bbs.12365auto.com/threadforum/20260915/274600.shtml#f=s">小米SU7投诉帖测试标题足够长</a>'

    def handler(request):
        return httpx.Response(200, content=html.encode("utf-8"))

    transport = httpx.MockTransport(handler)
    c, restore = _make_collector(transport, max_pages=1)
    try:
        posts = await c.search("小米SU7", "2026-01-01", "2026-09-27")
    finally:
        restore()
    assert len(posts) == 1
    assert posts[0]["url"].startswith("https://")


async def test_no_series_id_returns_empty():
    c = ChezhiwangCollector()
    posts = await c.search("未知车型", "2026-01-01", "2026-09-27")
    assert posts == []


async def test_empty_list_page_returns_empty():
    def handler(request):
        return httpx.Response(200, content=b"<html></html>")

    transport = httpx.MockTransport(handler)
    c, restore = _make_collector(transport, max_pages=1)
    try:
        posts = await c.search("小米SU7", "2026-01-01", "2026-09-27")
    finally:
        restore()
    assert posts == []


# ── 详情正文提取 ───────────────────────────────────────────────────────────────


_DETAIL_HTML = (
    '<div class="nr_r_r"><div class="neirong" id="rcontent_750119">'
    '<p>小米SU7无磕碰无撞击，尾灯内部自行开裂，裂纹不断扩大，灯腔积攒大量水渍，'
    '明显是原厂零部件工艺缺陷，本应享受三包质保。</p>'
    '</div><div class=\'nr_r_b\'><a class="coll">收藏</a></div></div>'
)


async def test_detail_content_extracted():
    list_html = '<a href="https://bbs.12365auto.com/threadforum/20260918/274813.shtml#f=s">小米SU7尾灯内裂投诉帖标题足够长</a>'

    def handler(request):
        if "seriesforum" in str(request.url):
            return httpx.Response(200, content=list_html.encode("utf-8"))
        return httpx.Response(200, content=_DETAIL_HTML.encode("utf-8"))

    transport = httpx.MockTransport(handler)
    c, restore = _make_collector(transport, max_pages=1)
    try:
        posts = await c.search("小米SU7", "2026-01-01", "2026-09-27")
    finally:
        restore()
    assert len(posts) == 1
    fc = posts[0].get("full_content", "")
    assert "尾灯内部自行开裂" in fc
    assert "三包质保" in fc


async def test_detail_fetch_failure_does_not_crash():
    """详情页抓取失败时 full_content 留空，不影响列表帖入库。"""
    list_html = '<a href="https://bbs.12365auto.com/threadforum/20260918/274813.shtml#f=s">小米SU7尾灯内裂投诉帖标题足够长</a>'

    def handler(request):
        if "seriesforum" in str(request.url):
            return httpx.Response(200, content=list_html.encode("utf-8"))
        return httpx.Response(500, content=b"server error")

    transport = httpx.MockTransport(handler)
    c, restore = _make_collector(transport, max_pages=1)
    try:
        posts = await c.search("小米SU7", "2026-01-01", "2026-09-27")
    finally:
        restore()
    assert len(posts) == 1
    assert posts[0].get("full_content") in (None, "")


async def test_list_fetch_error_returns_empty():
    def handler(request):
        raise httpx.ConnectError("network down")

    transport = httpx.MockTransport(handler)
    c, restore = _make_collector(transport, max_pages=1)
    try:
        posts = await c.search("小米SU7", "2026-01-01", "2026-09-27")
    finally:
        restore()
    assert posts == []


# ── 去重 ──────────────────────────────────────────────────────────────────────


async def test_dedup_across_pages():
    """同一帖跨页出现应去重。"""
    page_html = '<a href="https://bbs.12365auto.com/threadforum/20260918/274813.shtml#f=s">小米SU7尾灯内裂投诉帖标题足够长</a>'

    def handler(request):
        if "seriesforum" in str(request.url):
            return httpx.Response(200, content=page_html.encode("utf-8"))
        return httpx.Response(200, content=_DETAIL_HTML.encode("utf-8"))

    transport = httpx.MockTransport(handler)
    c, restore = _make_collector(transport, max_pages=2)
    try:
        posts = await c.search("小米SU7", "2026-01-01", "2026-09-27")
    finally:
        restore()
    # 两页都返回同一帖，去重后只 1 条
    assert len(posts) == 1


# ── search max_pages 覆盖（T2 独立宽窗）────────────────────────────────────────


async def test_search_max_pages_override_uses_param_not_default():
    """search(max_pages=5) 覆盖实例默认（3），翻 5 页而非 3 页。"""
    seen_pages: list[int] = []

    def handler(request):
        if "seriesforum" in str(request.url):
            # URL: seriesforum/{sid}-1-{page}-0.shtml → page 是倒数第二段
            url = str(request.url)
            parts = url.rsplit("-", 3)
            page = int(parts[-2]) if len(parts) == 4 else 0
            seen_pages.append(page)
            # 第 5 页起返回空（模拟到末尾），让前 5 页都被请求
            if page >= 5:
                return httpx.Response(200, content=b"")
            return httpx.Response(200, content=_LIST_HTML.encode("utf-8"))
        return httpx.Response(200, content=_DETAIL_HTML.encode("utf-8"))

    transport = httpx.MockTransport(handler)
    # 实例默认 max_pages=3，传 max_pages=5 应翻 5 页
    c, restore = _make_collector(transport, max_pages=3)
    try:
        await c.search("小米SU7", "2026-01-01", "2026-09-27", max_pages=5)
    finally:
        restore()
    # 前 5 页（0-4）都被请求；第 5 页（page=5）空触发 break
    assert max(seen_pages) >= 4


async def test_search_max_pages_none_falls_back_to_instance_default():
    """max_pages=None 时用实例默认值（不覆盖）。"""
    seen_pages: list[int] = []

    def handler(request):
        if "seriesforum" in str(request.url):
            url = str(request.url)
            parts = url.rsplit("-", 3)
            page = int(parts[-2]) if len(parts) == 4 else 0
            seen_pages.append(page)
            if page >= 3:
                return httpx.Response(200, content=b"")
            return httpx.Response(200, content=_LIST_HTML.encode("utf-8"))
        return httpx.Response(200, content=_DETAIL_HTML.encode("utf-8"))

    transport = httpx.MockTransport(handler)
    c, restore = _make_collector(transport, max_pages=3)
    try:
        await c.search("小米SU7", "2026-01-01", "2026-09-27")
    finally:
        restore()
    # 实例默认 3 → 翻 3 页（0-2），第 3 页空 break
    assert max(seen_pages) <= 3


# ── 平台常量与策略 ─────────────────────────────────────────────────────────────


def test_platform_registered():
    from pipeline.platforms import ALL_PLATFORMS, CHEZHIWANG, platform_label
    assert CHEZHIWANG == "chezhiwang"
    assert "chezhiwang" in ALL_PLATFORMS
    assert platform_label("chezhiwang") == "车质网"


def test_strategy_registered():
    from pipeline.collectors.platform_strategy import get_strategy
    s = get_strategy("chezhiwang")
    assert s.risk_level == "none"
    assert s.max_pages >= 1


def test_progress_platform_registered():
    from api.pipeline_state import PipelineProgress
    p = PipelineProgress()
    p.init_platforms()
    assert "chezhiwang" in p.platforms
