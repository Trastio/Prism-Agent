"""Tests for TikHub Collector — fixture 全部为测试内构造的 dict。

不依赖 logs/tikhub_test/round2 样本文件入库：fixture 结构按 round2 实测响应
复刻（字段路径/键名以样本为准），日期一律动态生成（09-10 日期炸弹教训：
期望值用 datetime.now()/date.today() 推算，unix 时间戳相对 now 生成）。

不发任何真实 HTTP 请求：client 层 mock httpx（信封/重试/HTTP 401）或
httpx.MockTransport（抓真实请求行断言中文参数百分号编码）；adapter 层
patch.object(client, "get")（信封已在 client 层剥掉，adapter 直接吃 data）。
"""

from datetime import date, datetime, timedelta, timezone
import json
import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pipeline.collectors.post_utils import _parse_datetime
from pipeline.collectors.tikhub_collector import (
    ENDPOINTS,
    TikHubAuthError,
    TikHubClient,
    TikHubCollector,
    TikHubError,
    _ks_publish_time,
    _search_max_pages,
    _xhs_time_filter,
)

# ── 动态日期工具（杜绝硬编码日期）────────────────────────────────────

_EN_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_EN_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _weibo_en(dt: datetime) -> str:
    """微博英文全格式（locale 无关，手拼星期/月份防 C locale 差异）。"""
    return (f"{_EN_DAYS[dt.weekday()]} {_EN_MONTHS[dt.month - 1]} "
            f"{dt.day:02d} {dt:%H:%M:%S} +0800 {dt.year}")


def _iso_utc(ts: int) -> str:
    """unix 秒 → ISO（与 _parse_datetime 数值分支同口径：UTC）。"""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _mocked_collector(**collector_kwargs) -> tuple[TikHubCollector, TikHubClient]:
    client = TikHubClient(base_url="https://tikhub.test", api_key="test-key")
    collector = TikHubCollector(client=client, **collector_kwargs)
    return collector, client


def _resp(payload: dict, status_code: int = 200) -> MagicMock:
    """Mock 一个 httpx.Response（默认 HTTP 200 + 同步 json()）。"""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=payload)
    resp.text = "error-body"
    return resp


# ── fixture 构造器：微博 ──────────────────────────────────────────────


def _weibo_item(wid: str, publish_time: str, content: str = "小鹏M03 提车三周报告",
                nick: str = "车主阿强", url: str | None = None) -> dict:
    if url is None:
        url = "//weibo.com/1693501760/RhkYH7HiL?refer_flag=1001030103_"
    return {
        "weibo_id": wid,
        "user_name": nick,
        "user_nick": nick,
        "publish_time": publish_time,
        "post_url": url,
        "content": content,
        "source": "微博网页版",
        "weibo_type": "original",
        "interaction": {"repost_count": 0, "comment_count": 0, "like_count": 0},
    }


def _weibo_page(*results: dict) -> dict:
    return {"parsed_data": {"results": list(results), "parse_success": True}}


def _weibo_mmdd(hours_ago: float) -> str:
    return (datetime.now() - timedelta(hours=hours_ago)).strftime("%m月%d日 %H:%M")


def _wb_detail(wid: str, *, attitudes: object = "139", comments: object = "24",
               reposts: object = "7", is_long: bool = False,
               text_raw: str = "风掠过垭口，草甸翻着绿浪。", hours_ago: float = 2.0) -> dict:
    """fetch_post_detail 的 data（扁平 mblog，探针样本结构复刻）。

    互动数默认给字符串形态（探针契约注明 str/int 两种都见过，_safe_int 归一）；
    created_at 用动态时刻手拼英文全格式（带年份，区别于搜索级 MM月DD日）。
    """
    return {
        "id": wid, "mid": wid, "idstr": wid, "mblogid": "RhavRllO2",
        "created_at": _weibo_en(datetime.now() - timedelta(hours=hours_ago)),
        "reposts_count": reposts, "comments_count": comments,
        "attitudes_count": attitudes, "isLongText": is_long,
        "text_raw": text_raw, "text": f"<p>{text_raw}</p>",
        "region_name": "发布于 广东", "source": "微博网页版",
        "user": {"screen_name": "小鹏MONA", "verified": True},
    }


# ── fixture 构造器：小红书 ────────────────────────────────────────────


def _xhs_note(nid: str, comments: int = 5, liked: int = 10,
              hours_ago: float = 1.0, xsec: str = "tok_abc123") -> dict:
    return {
        "id": nid, "xsec_token": xsec, "title": "M03 提车记", "desc": "正文内容",
        "liked_count": liked, "comments_count": comments,
        "collected_count": 3, "shared_count": 2,
        "timestamp": int((datetime.now() - timedelta(hours=hours_ago)).timestamp()),
        "user": {"nickname": "笔记作者"}, "type": "normal",
    }


def _xhs_search_data(*notes: dict, search_id: str = "sid-1",
                     session_id: str = "sess-1") -> dict:
    return {
        "code": 0, "success": True, "msg": "成功",
        "data": {"items": [{"note": n} for n in notes]},
        "search_id": search_id, "search_session_id": session_id,
        "page": 1, "next_page": 2,
    }


def _xhs_comment(cid: str = "c1", ip: str = "Shanghai", likes: int = 5,
                 minutes_ago: float = 30) -> dict:
    return {
        "id": cid, "content": "这车真的不错", "like_count": likes,
        "sub_comment_count": 4,
        "time": int((datetime.now() - timedelta(minutes=minutes_ago)).timestamp()),
        "ip_location": ip,
        "user": {"nickname": "评论者", "red_id": "123"},
    }


def _xhs_comment_payload(comments: list, cursor: str = "", has_more: bool = False) -> dict:
    return {"code": 0, "success": True,
            "data": {"comments": comments, "cursor": cursor, "has_more": has_more}}


# ── fixture 构造器：快手 / 抖音 ───────────────────────────────────────


def _ks_feed(pid: str, caption: str = "快手 M03 实测", hours_ago: float = 2.0) -> dict:
    return {
        "photo_id": pid, "caption": caption,
        "timestamp": int((datetime.now() - timedelta(hours=hours_ago)).timestamp() * 1000),
        "like_count": 12, "comment_count": 3, "view_count": 400,
        "share_count": 1, "collect_count": 6, "forward_count": 0,
        "user_name": "快手作者",
    }


def _ks_page(*feeds: dict, pcursor: object = "1") -> dict:
    return {"mixFeeds": [{"feed": f, "itemType": 1} for f in feeds], "pcursor": pcursor}


def _ks_root_comment(timestamp_ms: int) -> dict:
    return {
        "comment_id": 889001835226, "content": "这车续航如何", "timestamp": timestamp_ms,
        "likedCount": 64, "authorArea": "北京", "author_name": "翔际",
        "subCommentCount": 20, "photo_id": 5252886156194117913,
    }


def _dy_comment(cid: str = "7684068765316055857") -> dict:
    return {
        "cid": cid, "text": "帮帮忙一直忙", "create_time": int(time.time()) - 600,
        "digg_count": 3, "ip_label": "广西", "reply_comment_total": 2,
        "user": {"nickname": "郑在输入中……", "uid": "540562842194475"},
    }


def _dy_aweme(vid: str, hours_ago: float = 2.0, desc: str = "M03 城市续航实测",
              digg: int = 0) -> dict:
    """search v1 视频卡的 aweme_info（statistics 恒 0 是契约要点）。"""
    return {
        "aweme_id": vid, "desc": desc,
        "create_time": int((datetime.now() - timedelta(hours=hours_ago)).timestamp()),
        "author": {"nickname": "抖音作者"},
        "ip_attribution": "广西",
        "share_url": f"https://www.iesdouyin.com/share/video/{vid}/",
        "statistics": {"digg_count": digg, "comment_count": 0, "share_count": 0,
                       "play_count": 0},
    }


def _dy_search_data(*cards: dict, has_more: int = 0, cursor: int = 0,
                    impr_id: str | None = None) -> dict:
    """search v1 顶层 data：aweme_list 是空壳（契约），真负载在 data[] 卡片；
    log_pb.impr_id 是第 2 页的 search_id 翻页凭证（2026-09-27 探针 D1/D2：
    缺它第 2 页 4 连 400 确定性失败，传上页值即 200）。"""
    return {"aweme_list": [], "has_more": has_more, "cursor": cursor,
            "log_pb": {"impr_id": impr_id if impr_id is not None else f"impr-{cursor}"},
            "data": list(cards)}


# ======================================================================
# Client：信封 / 重试 / 异常路径 / 编码
# ======================================================================


class TestTikHubClient:
    def test_registry_has_all_14_endpoints_with_v1_paths(self):
        assert len(ENDPOINTS) == 14
        paths = list(ENDPOINTS.values())
        assert len(paths) == len(set(paths))          # 路径不重复
        assert all(p.startswith("/api/v1/") for p in paths)

    @pytest.mark.asyncio
    async def test_envelope_code_200_returns_data(self):
        client = TikHubClient(base_url="https://tikhub.test", api_key="k")
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_resp(
                {"code": 200, "message": "ok", "data": {"x": 1}}))):
            assert await client.get("weibo.search", {"q": "m"}) == {"x": 1}

    @pytest.mark.asyncio
    async def test_envelope_code_as_string_accepted(self):
        # 防御：信封 code 若为字符串 "200" 也判成功
        client = TikHubClient(base_url="https://tikhub.test", api_key="k")
        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=_resp(
                {"code": "200", "message": "ok", "data": [1, 2]}))):
            assert await client.get("weibo.search") == [1, 2]

    @pytest.mark.asyncio
    async def test_business_code_fail_retries_then_raises(self):
        # code!=200 业务失败（HTTP 200）→ 重试耗尽后抛 TikHubError
        client = TikHubClient(base_url="https://tikhub.test", api_key="k",
                              max_attempts=3, retry_backoff=0)
        mock = AsyncMock(return_value=_resp({"code": 404, "message": "no such"}))
        with patch("httpx.AsyncClient.get", new=mock):
            with pytest.raises(TikHubError, match="重试耗尽"):
                await client.get("weibo.search")
        assert mock.call_count == 3

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [401, 402, 403])
    async def test_http_auth_error_raises_immediately_no_retry(self, status):
        # 402=余额耗尽（2026-09-12 实采：烧完后全端点 402，必须账户级暴露
        # 而非普通 4xx 静默吞掉——否则平台 0 帖照样"完成"）
        client = TikHubClient(base_url="https://tikhub.test", api_key="bad-key",
                              retry_backoff=0)
        mock = AsyncMock(return_value=_resp({"code": 200, "data": {}}, status_code=status))
        with patch("httpx.AsyncClient.get", new=mock):
            with pytest.raises(TikHubAuthError, match=str(status)):
                await client.get("weibo.search")
        assert mock.call_count == 1  # 不重试

    @pytest.mark.asyncio
    async def test_http_404_fails_fast_no_retry(self):
        # 4xx（非 401/403/429）请求级错误：body {"detail": ...} 无顶层 code，
        # 空跑满 5 次重试无意义 → 一次即抛
        client = TikHubClient(base_url="https://tikhub.test", api_key="k",
                              retry_backoff=0)
        mock = AsyncMock(return_value=_resp({"detail": "Not Found"}, status_code=404))
        with patch("httpx.AsyncClient.get", new=mock):
            with pytest.raises(TikHubError, match="HTTP 404.*Not Found"):
                await client.get("weibo.search")
        assert mock.call_count == 1  # 快速失败：不重试

    @pytest.mark.asyncio
    async def test_http_4xx_non_json_body_carries_first_200_chars(self):
        resp = MagicMock()
        resp.status_code = 400
        resp.text = "plain text body " * 40  # 600 字符 → 只带前 200
        resp.json = MagicMock(side_effect=ValueError("not json"))
        client = TikHubClient(base_url="https://tikhub.test", api_key="k",
                              retry_backoff=0)
        mock = AsyncMock(return_value=resp)
        with patch("httpx.AsyncClient.get", new=mock):
            with pytest.raises(TikHubError) as ei:
                await client.get("weibo.search")
        assert mock.call_count == 1
        assert "HTTP 400" in str(ei.value)
        assert resp.text[:200] in str(ei.value)  # 非 JSON body 截前 200 字符

    @pytest.mark.asyncio
    async def test_http_429_still_retries_to_exhaustion(self):
        # 429 限流退避有意义：不快速失败，走正常重试链路（耗尽后抛）
        client = TikHubClient(base_url="https://tikhub.test", api_key="k",
                              max_attempts=3, retry_backoff=0)
        mock = AsyncMock(return_value=_resp({"detail": "Too Many Requests"},
                                            status_code=429))
        with patch("httpx.AsyncClient.get", new=mock):
            with pytest.raises(TikHubError, match="重试耗尽"):
                await client.get("weibo.search")
        assert mock.call_count == 3

    @pytest.mark.asyncio
    async def test_xhs_400_cold_start_retries_then_succeeds(self):
        # 官方文档：xhs 后端预热慢首访常 400，重试 1-2 次即成功（400 不计费）
        # → xiaohongshu.* 端点的 400 是 4xx 快速失败的唯一例外，走重试
        client = TikHubClient(base_url="https://tikhub.test", api_key="k",
                              retry_backoff=0)
        mock = AsyncMock(side_effect=[
            _resp({"code": 400, "message": "Request failed. Please retry"}, status_code=400),
            _resp({"code": 200, "message": "ok", "data": {"items": []}}),
        ])
        with patch("httpx.AsyncClient.get", new=mock):
            out = await client.get("xiaohongshu.search_notes", {"keyword": "m"})
        assert out == {"items": []}
        assert mock.call_count == 2              # 400 → 重试 → 第二次成功

    @pytest.mark.asyncio
    async def test_non_xhs_400_still_fails_fast(self):
        # 400 快速失败例外仅限 xiaohongshu.*：其余端点 400 一次即抛
        client = TikHubClient(base_url="https://tikhub.test", api_key="k",
                              retry_backoff=0)
        mock = AsyncMock(return_value=_resp({"detail": "bad request"},
                                            status_code=400))
        with patch("httpx.AsyncClient.get", new=mock):
            with pytest.raises(TikHubError, match="HTTP 400"):
                await client.get("weibo.fetch_post_comments", params={"id": "1"})
        assert mock.call_count == 1

    @pytest.mark.asyncio
    async def test_envelope_form_400_upstream_flaky_retries(self):
        """400 双形态（M03 实采）：body 带 code 键 = 上游瞬时故障（官方
        "Please retry"，4xx 不计费）→ 走重试链路而非快速失败。"""
        client = TikHubClient(base_url="https://tikhub.test", api_key="k",
                              max_attempts=2, retry_backoff=0)
        mock = AsyncMock(side_effect=[
            _resp({"code": 400, "message": "Request failed. Please retry"},
                  status_code=400),
            _resp({"code": 200, "data": {"data": []}}),
        ])
        with patch("httpx.AsyncClient.post", new=mock):
            out = await client.post("douyin.search", params={"keyword": "m"})
        assert out == {"data": []}
        assert mock.call_count == 2               # 400 → 重试 → 成功

    @pytest.mark.asyncio
    async def test_envelope_form_400_retries_to_exhaustion(self):
        client = TikHubClient(base_url="https://tikhub.test", api_key="k",
                              max_attempts=2, retry_backoff=0)
        mock = AsyncMock(return_value=_resp(
            {"code": 400, "message": "Request failed. Please retry"},
            status_code=400))
        with patch("httpx.AsyncClient.post", new=mock):
            with pytest.raises(TikHubError):
                await client.post("douyin.search")
        assert mock.call_count == 2               # 重试耗尽（非快速失败）

    @pytest.mark.asyncio
    async def test_detail_form_400_never_retries_even_with_code_endpoint(self):
        # 同一端点上 {"detail": ...} 形态仍是请求级错误：一次即抛
        client = TikHubClient(base_url="https://tikhub.test", api_key="k",
                              retry_backoff=0)
        mock = AsyncMock(return_value=_resp({"detail": "bad kw"},
                                            status_code=400))
        with patch("httpx.AsyncClient.post", new=mock):
            with pytest.raises(TikHubError, match="HTTP 400"):
                await client.post("douyin.search")
        assert mock.call_count == 1

    @pytest.mark.asyncio
    async def test_detail_nested_code_400_retries_then_succeeds(self):
        """400 第三形态（2026-09-27 探针）：{"detail": {"code": 400, ...}} —
        code 嵌在 detail 里也是上游瞬时故障（统计端点/搜索第 1 页实采 400
        症状的根因；探针 C2 实证重试即 200）→ 走重试链路。"""
        client = TikHubClient(base_url="https://tikhub.test", api_key="k",
                              max_attempts=2, retry_backoff=0)
        mock = AsyncMock(side_effect=[
            _resp({"detail": {"code": 400, "request_id": "r1",
                              "message": "Request failed. Please retry"}},
                  status_code=400),
            _resp({"code": 200, "data": {"statistics_list": []}}),
        ])
        with patch("httpx.AsyncClient.get", new=mock):
            out = await client.get("douyin.fetch_multi_video_statistics",
                                   params={"aweme_ids": "7690106919554598602"})
        assert out == {"statistics_list": []}
        assert mock.call_count == 2               # 400 → 重试 → 成功

    @pytest.mark.asyncio
    async def test_transport_error_then_success(self):
        client = TikHubClient(base_url="https://tikhub.test", api_key="k", retry_backoff=0)
        mock = AsyncMock(side_effect=[
            httpx.ConnectError("boom"),
            _resp({"code": 200, "data": {"ok": True}}),
        ])
        with patch("httpx.AsyncClient.get", new=mock):
            assert await client.get("weibo.search") == {"ok": True}
        assert mock.call_count == 2

    @pytest.mark.asyncio
    async def test_unknown_endpoint_raises_without_http(self):
        client = TikHubClient(base_url="https://tikhub.test", api_key="k")
        mock = AsyncMock()
        with patch("httpx.AsyncClient.get", new=mock):
            with pytest.raises(TikHubError, match="未知端点"):
                await client.get("nope.nope")
        mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_key_raises(self):
        client = TikHubClient(base_url="https://tikhub.test", api_key="")
        with pytest.raises(TikHubAuthError, match="TIKHUB_KEY"):
            await client.get("weibo.search")

    @pytest.mark.asyncio
    async def test_utf8_params_percent_encoded_and_auth_header(self):
        """走真实 httpx 栈（MockTransport）：中文参数 UTF-8 百分号编码 + Bearer。"""
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("Authorization")
            return httpx.Response(200, json={"code": 200, "message": "ok", "data": {}})

        client = TikHubClient(base_url="https://tikhub.test", api_key="my-key",
                              transport=httpx.MockTransport(handler))
        out = await client.get("kuaishou.search_comprehensive",
                               {"keyword": "小鹏M03", "pcursor": None})
        assert out == {}
        assert captured["url"].startswith(
            "https://tikhub.test/api/v1/kuaishou/app/search_comprehensive")
        # 小鹏 = E5 B0 8F / E9 B9 8F —— UTF-8 百分号编码
        assert "keyword=%E5%B0%8F%E9%B9%8FM03" in captured["url"]
        assert "pcursor" not in captured["url"]  # None 参数被过滤
        assert captured["auth"] == "Bearer my-key"

    @pytest.mark.asyncio
    async def test_empty_and_none_params_filtered_int_zero_kept(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["params"] = dict(request.url.params)
            return httpx.Response(200, json={"code": 200, "data": {}})

        client = TikHubClient(base_url="https://tikhub.test", api_key="k",
                              transport=httpx.MockTransport(handler))
        await client.get("douyin.fetch_video_comments",
                         {"aweme_id": "1", "cursor": 0, "max_id": "", "junk": None})
        assert captured["params"] == {"aweme_id": "1", "cursor": "0"}

    # ── POST 端点（douyin.search v1，唯一 POST）──────────────────

    @pytest.mark.asyncio
    async def test_post_sends_json_body_and_parses_envelope(self):
        """POST：params 走 JSON body（非 query），空串过滤 / int 0 保留与 GET 一致。"""
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.content)
            captured["auth"] = request.headers.get("Authorization")
            return httpx.Response(200, json={"code": 200, "data": {"ok": 1}})

        client = TikHubClient(base_url="https://tikhub.test", api_key="k",
                              transport=httpx.MockTransport(handler))
        out = await client.post("douyin.search",
                                {"keyword": "小鹏M03", "cursor": 0, "search_id": ""})
        assert out == {"ok": 1}
        assert captured["method"] == "POST"
        assert captured["url"].endswith("/api/v1/douyin/search/fetch_video_search_v1")
        assert "?" not in captured["url"]                       # 参数不在 query
        assert captured["body"] == {"keyword": "小鹏M03", "cursor": 0}
        assert captured["auth"] == "Bearer k"

    @pytest.mark.asyncio
    async def test_post_404_fails_fast_no_retry(self):
        # POST 与 GET 同语义：4xx（非 401/403/429）请求级错误一次即抛
        client = TikHubClient(base_url="https://tikhub.test", api_key="k",
                              retry_backoff=0)
        mock = AsyncMock(return_value=_resp({"detail": "Not Found"}, status_code=404))
        with patch("httpx.AsyncClient.post", new=mock):
            with pytest.raises(TikHubError, match="HTTP 404"):
                await client.post("douyin.search")
        assert mock.call_count == 1

    @pytest.mark.asyncio
    async def test_post_business_code_fail_retries_then_raises(self):
        client = TikHubClient(base_url="https://tikhub.test", api_key="k",
                              max_attempts=2, retry_backoff=0)
        mock = AsyncMock(return_value=_resp({"code": 500, "message": "upstream"}))
        with patch("httpx.AsyncClient.post", new=mock):
            with pytest.raises(TikHubError, match="重试耗尽"):
                await client.post("douyin.search")
        assert mock.call_count == 2


# ======================================================================
# 微博 adapter
# ======================================================================


class TestWeiboAdapter:
    @pytest.mark.asyncio
    async def test_search_maps_fields(self):
        collector, client = _mocked_collector(comment_post_limit=0, detail_post_limit=0)
        dt = datetime.now() - timedelta(hours=2)
        item = _weibo_item("5341322191834751", dt.strftime("%m月%d日 %H:%M"),
                           content="小鹏M03 真香")
        with patch.object(client, "get", AsyncMock(return_value=_weibo_page(item))):
            posts, comments = await collector.search("小鹏M03", "weibo")

        assert comments == []
        p0 = posts[0]
        # URL 用数字 weibo_id 拼 m.weibo.cn（与 OneAPI 一致）：post_url 尾段是
        # bid，fetch_top_comments 从 URL 尾段提 id 传评论接口，bid 必错
        assert p0["url"] == "https://m.weibo.cn/status/5341322191834751"
        assert p0["author"] == "车主阿强"          # user_nick
        assert p0["title"] == "小鹏M03 真香"
        assert p0["likes"] == 0 and p0["comments"] == 0 and p0["shares"] == 0  # 互动恒 0
        assert p0["published_at"] == f"{dt:%Y-%m-%d}T{dt:%H:%M}:00"
        assert p0["weibo_id"] == "5341322191834751"  # 评论回链键
        assert p0["platform"] == "weibo" and p0["source"] == "tikhub"

    @pytest.mark.asyncio
    async def test_url_always_from_weibo_id_regardless_of_post_url(self):
        # URL 恒由数字 weibo_id 生成，post_url（bid 尾段）不进库
        collector, client = _mocked_collector(comment_post_limit=0, detail_post_limit=0)
        item = _weibo_item("5341322191834751", _weibo_mmdd(2), url="")
        with patch.object(client, "get", AsyncMock(return_value=_weibo_page(item))):
            posts, _ = await collector.search("m", "wb")
        assert posts[0]["url"] == "https://m.weibo.cn/status/5341322191834751"

    def test_weibo_post_wid_missing_falls_back_to_post_url(self):
        # wid 缺失的防御路径（搜索入口 wid 空帖直接跳过）：兜底原 post_url，
        # 协议相对补 https:
        r = _weibo_item("", _weibo_mmdd(1), url="//weibo.com/1693501760/RhkYH7HiL")
        post = TikHubCollector._weibo_post(r, "")
        assert post["url"] == "https://weibo.com/1693501760/RhkYH7HiL"

    @pytest.mark.asyncio
    async def test_page_counts_initial_3_vs_incremental_2(self):
        # initial 3 页 / incremental 2 页（时间全在窗内 → 翻满页数上限）
        pages = [_weibo_page(_weibo_item(f"100{i}", _weibo_mmdd(i + 1)))
                 for i in range(3)]
        collector, client = _mocked_collector(comment_post_limit=0, detail_post_limit=0)
        mock = AsyncMock(side_effect=pages)
        with patch.object(client, "get", mock):
            _, _ = await collector.search("m", "weibo", mode="initial")
        assert mock.call_count == 3                       # initial 翻满 3 页
        assert [c.kwargs["params"]["page"] for c in mock.call_args_list] == [1, 2, 3]

        collector2, client2 = _mocked_collector(comment_post_limit=0, detail_post_limit=0)
        mock2 = AsyncMock(side_effect=pages)
        with patch.object(client2, "get", mock2):
            _, _ = await collector2.search("m", "weibo", mode="incremental")
        assert mock2.call_count == 2                      # incremental 只翻 2 页

    @pytest.mark.asyncio
    async def test_search_page_params(self):
        collector, client = _mocked_collector(comment_post_limit=0)
        mock = AsyncMock(return_value={"parsed_data": {"results": []}})
        with patch.object(client, "get", mock):
            await collector.search("小鹏M03", "weibo", mode="incremental")
        assert mock.call_args_list[0].args == ("weibo.search",)
        assert mock.call_args_list[0].kwargs["params"] == {"q": "小鹏M03", "page": 1}

    @pytest.mark.asyncio
    async def test_time_truncation_breaks_pagination(self):
        """页级时间截断：第 2 页最旧帖出窗 → 不再翻第 3 页（initial 上限 3 页）。"""
        fresh = _weibo_page(_weibo_item("2001", _weibo_mmdd(1)),
                            _weibo_item("2002", _weibo_mmdd(2)))
        old = _weibo_page(_weibo_item("2003", _weibo_mmdd(30 * 24)))  # 30 天前，窗 7 天外
        third = _weibo_page(_weibo_item("2004", _weibo_mmdd(30 * 24)))
        collector, client = _mocked_collector(comment_post_limit=0, detail_post_limit=0)
        mock = AsyncMock(side_effect=[fresh, old, third])
        with patch.object(client, "get", mock):
            posts, _ = await collector.search("m", "weibo", window_days=7, mode="initial")
        assert mock.call_count == 2          # 第 2 页出窗即停，第 3 页没打
        assert len(posts) == 3               # 出窗页的帖子照常返回（floor 是 scheduler 的事）
        assert {p["weibo_id"] for p in posts} == {"2001", "2002", "2003"}

    @pytest.mark.asyncio
    async def test_weibo_id_dedup_across_pages(self):
        item = _weibo_item("3001", _weibo_mmdd(1))
        collector, client = _mocked_collector(comment_post_limit=0, detail_post_limit=0)
        mock = AsyncMock(side_effect=[_weibo_page(item), _weibo_page(item, item)])
        with patch.object(client, "get", mock):
            posts, _ = await collector.search("m", "weibo", mode="incremental")
        assert len(posts) == 1

    @pytest.mark.asyncio
    async def test_interaction_zero_still_fetches_comments_by_recency(self):
        """互动全 0 契约下不按 comments>0 过滤：按 published_at 新→旧选 top-N。

        3 帖全部 comments=0（时间顺序打乱：最旧在前），limit=2 → 只抓最新两条。
        """
        # 老帖（C，5 小时前）排最前，新帖（A，1 小时前）排中间——顺序不能决定选谁
        page = _weibo_page(
            _weibo_item("C000", _weibo_mmdd(5)),
            _weibo_item("A000", _weibo_mmdd(1)),
            _weibo_item("B000", _weibo_mmdd(3)),
        )
        empty_page = _weibo_page()                  # 第 2 页空 → 搜索即止
        cmt_page = {"data": [], "max_id": 0, "total_number": 8}
        collector, client = _mocked_collector(comment_post_limit=2, detail_post_limit=0)
        mock = AsyncMock(side_effect=[page, empty_page, cmt_page, cmt_page])
        with patch.object(client, "get", mock):
            posts, comments = await collector.search("m", "weibo", window_days=7)

        assert comments == []                       # mock 评论页无条目，但回填生效
        assert mock.call_count == 4                 # 2 搜索页 + 2 条最新帖的评论
        # 选中 A（1h 前）与 B（3h 前）——按时间而非出现顺序
        assert [c.kwargs["params"]["id"] for c in mock.call_args_list[2:]] == ["A000", "B000"]
        by_id = {p["weibo_id"]: p for p in posts}
        assert by_id["A000"]["comments"] == 8       # total_number 回填（互动 0 的唯一真实源）
        assert by_id["B000"]["comments"] == 8
        assert by_id["C000"]["comments"] == 0       # 未选中 → 不回填

    @pytest.mark.asyncio
    async def test_comment_mapping_ip_region_and_backfill(self):
        collector, client = _mocked_collector()
        dt = datetime.now() - timedelta(hours=1)
        cmt = {
            "created_at": _weibo_en(dt),           # 英文全格式带年（现有分支）
            "text": '这车<a href="/x">真不错</a><br />推荐',
            "text_raw": "这车真不错\n推荐",          # 纯文本（官方契约更正）
            "source": "来自 广东",
            "like_count": None, "like_counts": 2,  # 实测字段是 like_counts
            "user": {"screen_name": "汽车思考评论"},
        }
        data = {"data": [cmt], "max_id": 0, "total_number": 8}
        post = {"url": "https://m.weibo.cn/status/5341322191834751",
                "weibo_id": "5341322191834751", "comments": 0}
        with patch.object(client, "get", AsyncMock(return_value=data)):
            comments = await collector._fetch_weibo_comments(post)

        c0 = comments[0]
        assert c0["content"] == "这车真不错\n推荐"     # text_raw 直取
        assert c0["author"] == "汽车思考评论"
        assert c0["likes"] == 2                         # like_count None → like_counts
        assert c0["ip_region"] == "广东"                 # source "来自 广东" 正则提取
        assert c0["published_at"] == f"{dt:%Y-%m-%dT%H:%M:%S}"
        assert c0["post_note_id"] == "5341322191834751"
        assert c0["platform"] == "weibo"
        assert post["comments"] == 8                     # total_number 回填

    @pytest.mark.asyncio
    async def test_comment_non_ip_source_yields_empty_region(self):
        collector, client = _mocked_collector()
        cmt = {"created_at": _weibo_en(datetime.now()), "text": "纯评论",
               "source": "微博网页版", "like_counts": 0,
               "user": {"screen_name": "n"}}
        data = {"data": [cmt], "max_id": 0, "total_number": 1}
        with patch.object(client, "get", AsyncMock(return_value=data)):
            comments = await collector._fetch_weibo_comments({"url": "u", "comments": 0})
        assert comments[0]["ip_region"] == ""            # 设备来源非属地 → 空
        assert comments[0]["content"] == "纯评论"          # 无 text_raw → 剥 text 兜底

    @pytest.mark.asyncio
    async def test_comment_backfill_never_decreases(self):
        collector, client = _mocked_collector()
        data = {"data": [], "max_id": 0, "total_number": 3}
        post = {"url": "u", "comments": 50}
        with patch.object(client, "get", AsyncMock(return_value=data)):
            await collector._fetch_weibo_comments(post)
        assert post["comments"] == 50                    # 3 < 50 不回退

    @pytest.mark.asyncio
    async def test_comment_max_id_pagination(self):
        collector, client = _mocked_collector()
        page1 = {"data": [{"created_at": _weibo_en(datetime.now()), "text": "1",
                           "like_counts": 0, "user": {"screen_name": "a"}}],
                 "max_id": "218699834582", "total_number": 9}
        page2 = {"data": [], "max_id": 0, "total_number": 9}  # int 0 = 末页
        mock = AsyncMock(side_effect=[page1, page2])
        with patch.object(client, "get", mock):
            await collector._fetch_weibo_comments({"url": "u", "weibo_id": "5341", "comments": 0})

        assert mock.call_count == 2
        assert mock.call_args_list[0].kwargs["params"] == {"id": "5341", "count": 20}
        assert mock.call_args_list[1].kwargs["params"]["max_id"] == "218699834582"

    @pytest.mark.asyncio
    async def test_comment_pages_follow_env_knob(self, monkeypatch):
        # 翻页旋钮接线（P1-6）：COMMENT_MAX_PAGES=1 时非末页也只翻 1 页
        monkeypatch.setenv("COMMENT_MAX_PAGES", "1")
        collector, client = _mocked_collector()
        page = {"data": [{"created_at": _weibo_en(datetime.now()), "text": "1",
                          "like_counts": 0, "user": {"screen_name": "a"}}],
                "max_id": "123", "total_number": 9}   # max_id 非零 = 还有下页
        mock = AsyncMock(return_value=page)
        with patch.object(client, "get", mock):
            await collector._fetch_weibo_comments({"url": "u", "weibo_id": "1", "comments": 0})
        assert mock.call_count == 1

    @pytest.mark.asyncio
    async def test_comment_url_only_post_uses_path_tail(self):
        # fetch_comments_for_post 无 weibo_id → URL 尾段兜底
        collector, client = _mocked_collector()
        data = {"data": [], "max_id": 0, "total_number": 0}
        mock = AsyncMock(return_value=data)
        with patch.object(client, "get", mock):
            await collector.fetch_comments_for_post(
                "https://m.weibo.cn/status/5341322191834751", "weibo")
        assert mock.call_args.kwargs["params"]["id"] == "5341322191834751"

    @pytest.mark.asyncio
    async def test_comment_window_floor_aligned_with_store_floor(self):
        """T2.4：评论候选下限对齐 scheduler min_date floor（= start_date）。

        window_days = (today - start_date).days + 1（含首尾），故 floor =
        today - (window_days - 1)。旧算法 today - window_days 松一天——
        start_date 前一天发布的帖评论照抓、入库被 floor 丢弃成 unmatched。
        """
        collector, _client = _mocked_collector(comment_post_limit=10)
        posts = [
            # 窗口内（6 天前，window_days=7 → floor=today-6）
            {"url": "u-in", "published_at": (date.today() - timedelta(days=6)).isoformat(),
             "comments": 5, "likes": 1},
            # 恰在 start_date 前一天（7 天前）——对齐后不再抓评论
            {"url": "u-out", "published_at": (date.today() - timedelta(days=7)).isoformat(),
             "comments": 5, "likes": 2},
        ]
        fetched: list[str] = []

        async def fetcher(p):
            fetched.append(p["url"])
            return []

        await collector._collect_comments_for_posts(posts, fetcher, window_days=7)
        assert fetched == ["u-in"]


# ======================================================================
# 微博详情回填（web_v2/fetch_post_detail，probe 样本结构复刻）
# ======================================================================


class TestWeiboDetailEnrich:
    def _post(self, wid: str = "5340925469657523", hours_ago: float = 2.0,
              content: str = "小鹏M03 提车三周报告") -> dict:
        """搜索级帖（互动恒 0 / 无年份 MM月DD日 / 截断 content）。"""
        item = _weibo_item(wid, _weibo_mmdd(hours_ago), content=content)
        return TikHubCollector._weibo_post(item, wid)

    @pytest.mark.asyncio
    async def test_backfills_true_interactions_with_int_coercion(self):
        """三互动字段回填：字符串计数 _safe_int 转 int（探针契约 str/int 都见过）。"""
        post = self._post()
        collector, client = _mocked_collector()
        detail = _wb_detail("5340925469657523",
                            attitudes="139", comments="24", reposts="7")
        mock = AsyncMock(return_value=detail)
        with patch.object(client, "get", mock):
            await collector.enrich_weibo_details([post])
        assert mock.call_args.args == ("weibo.fetch_post_detail",)
        assert mock.call_args.kwargs["params"] == {
            "id": "5340925469657523", "is_get_long_text": "true"}
        assert post["likes"] == 139                    # attitudes_count
        assert post["comments"] == 24                  # comments_count
        assert post["shares"] == 7                     # reposts_count
        assert isinstance(post["likes"], int)

    @pytest.mark.asyncio
    async def test_int_form_counts_also_accepted(self):
        post = self._post()
        collector, client = _mocked_collector()
        detail = _wb_detail("5340925469657523",
                            attitudes=115692, comments=42521, reposts=41970)
        with patch.object(client, "get", AsyncMock(return_value=detail)):
            await collector.enrich_weibo_details([post])
        assert (post["likes"], post["comments"], post["shares"]) == (115692, 42521, 41970)

    @pytest.mark.asyncio
    async def test_published_at_upgraded_to_with_year_format(self):
        """带年份英文全格式 created_at 覆盖搜索级无年份 MM月DD日 解析。"""
        post = self._post()
        collector, client = _mocked_collector()
        detail = _wb_detail("5340925469657523")
        dt = datetime.now() - timedelta(hours=5)   # 与 fixture 内时刻解耦，同一 dt 断言
        detail["created_at"] = _weibo_en(dt)
        with patch.object(client, "get", AsyncMock(return_value=detail)):
            await collector.enrich_weibo_details([post])
        assert post["published_at"] == f"{dt:%Y-%m-%dT%H:%M:%S}"  # 时分秒真值

    @pytest.mark.asyncio
    async def test_long_text_replaces_truncated_content(self):
        """isLongText + text_raw 更长 → 截断 content 换全文（探针 167 vs 297 字）。"""
        truncated = "小鹏 MAX 的第二代 VLA 蒸馏版终于来了！当然首先出场的是单图灵版本……" * 2
        full = truncated + " 究竟该买个 MAX 就够用了，还是能买 Ultra 就还得买 Ultra 呢？" * 5
        post = self._post(content=truncated)
        collector, client = _mocked_collector()
        detail = _wb_detail("5340925469657523", is_long=True, text_raw=full)
        with patch.object(client, "get", AsyncMock(return_value=detail)):
            await collector.enrich_weibo_details([post])
        assert post["content"] == full

    @pytest.mark.asyncio
    async def test_non_long_text_content_untouched(self):
        """isLongText=false → 即便 text_raw 更长也不动搜索级 content。"""
        original = "小鹏M03 提车三周报告"
        post = self._post(content=original)
        collector, client = _mocked_collector()
        detail = _wb_detail("5340925469657523", is_long=False,
                            text_raw=original + "（详情级更长的正文）")
        with patch.object(client, "get", AsyncMock(return_value=detail)):
            await collector.enrich_weibo_details([post])
        assert post["content"] == original

    @pytest.mark.asyncio
    async def test_never_downgrades_existing_values(self):
        """>现值才写：详情值更小时保留现值（防旧详情覆盖新值）。"""
        post = self._post()
        post.update({"likes": 500, "comments": 80, "shares": 60})
        collector, client = _mocked_collector()
        detail = _wb_detail("5340925469657523",
                            attitudes="139", comments="24", reposts="7")
        with patch.object(client, "get", AsyncMock(return_value=detail)):
            await collector.enrich_weibo_details([post])
        assert (post["likes"], post["comments"], post["shares"]) == (500, 80, 60)

    @pytest.mark.asyncio
    async def test_single_post_failure_continues_others(self, caplog):
        """单帖失败 log warning 不炸整批，其余帖照常回填。"""
        posts = [self._post("W1", hours_ago=1.0), self._post("W2", hours_ago=2.0)]
        collector, client = _mocked_collector()
        mock = AsyncMock(side_effect=[
            TikHubError("业务失败 code=500"),
            _wb_detail("W2", attitudes="51"),
        ])
        with patch.object(client, "get", mock), caplog.at_level(
                logging.WARNING, logger="pipeline.collectors.tikhub_collector"):
            await collector.enrich_weibo_details(posts)
        assert mock.call_count == 2
        assert posts[0]["likes"] == 0                    # 失败帖保持搜索级 0
        assert posts[1]["likes"] == 51                   # 后续帖照常回填
        assert any("详情回填失败" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_auth_error_propagates(self):
        """账户级错误直抛（继续抓只会白烧重试）——计费护栏同款。"""
        post = self._post()
        collector, client = _mocked_collector()
        with patch.object(client, "get",
                          AsyncMock(side_effect=TikHubAuthError("HTTP 401"))):
            with pytest.raises(TikHubAuthError):
                await collector.enrich_weibo_details([post])

    @pytest.mark.asyncio
    async def test_limit_selects_newest_weibo_only(self):
        """limit 生效：按 published_at 新→旧取 top-N；非微博帖跳过。"""
        posts = [self._post(f"W{i}", hours_ago=float(i)) for i in range(1, 8)]
        posts.append({"platform": "xiaohongshu", "url": "https://x/y",
                      "likes": 0, "comments": 0, "shares": 0})
        collector, client = _mocked_collector()
        mock = AsyncMock(return_value=_wb_detail("W1"))
        with patch.object(client, "get", mock):
            await collector.enrich_weibo_details(posts, limit=3)
        assert mock.call_count == 3                      # xhs 帖不在内
        assert [c.kwargs["params"]["id"] for c in mock.call_args_list] == \
            ["W1", "W2", "W3"]                           # 最新 3 帖（1h/2h/3h 前）

    @pytest.mark.asyncio
    async def test_zero_limit_no_calls(self):
        collector, client = _mocked_collector()
        mock = AsyncMock()
        with patch.object(client, "get", mock):
            await collector.enrich_weibo_details([self._post()], limit=0)
        mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_wires_enrich_before_comments(self):
        """_search_weibo 接线：搜索 → 详情回填（top-N）→ 评论；与 total_number
        回填叠加（两侧都 >现值才写，互不覆盖）。"""
        newest = _weibo_item("A000", _weibo_mmdd(1))
        older = _weibo_item("B000", _weibo_mmdd(3))
        empty_page = _weibo_page()
        cmt_page = {"data": [], "max_id": 0, "total_number": 30}
        det_a = _wb_detail("A000", attitudes="139", comments="24", reposts="7")
        det_b = _wb_detail("B000", attitudes="51", comments="11", reposts="6")
        collector, client = _mocked_collector(comment_post_limit=2)
        mock = AsyncMock(side_effect=[
            _weibo_page(newest, older), empty_page, det_a, det_b, cmt_page, cmt_page])
        with patch.object(client, "get", mock):
            posts, comments = await collector.search("m", "weibo", window_days=7)

        assert comments == []
        assert mock.call_count == 6                      # 2 搜索 + 2 详情 + 2 评论
        by_ep = [c.args[0] for c in mock.call_args_list]
        assert by_ep == ["weibo.search", "weibo.search",
                         "weibo.fetch_post_detail", "weibo.fetch_post_detail",
                         "weibo.fetch_post_comments", "weibo.fetch_post_comments"]
        # 详情在评论之前，且评论端点 id 对得上（详情不改变选帖顺序）
        assert [c.kwargs["params"]["id"] for c in mock.call_args_list[2:4]] == ["A000", "B000"]
        assert [c.kwargs["params"]["id"] for c in mock.call_args_list[4:]] == ["A000", "B000"]
        by_id = {p["weibo_id"]: p for p in posts}
        # 叠加关系：A 详情 comments=24 < 评论 total_number=30 → 取 30；
        # B 详情 11 < 30 → 30；likes 只来自详情（139/51）
        assert by_id["A000"]["comments"] == 30 and by_id["A000"]["likes"] == 139
        assert by_id["B000"]["comments"] == 30 and by_id["B000"]["likes"] == 51


# ======================================================================
# 小红书 adapter
# ======================================================================


class TestXhsAdapter:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("window_days,expected", [
        (1, "一天内"), (7, "一周内"), (180, "半年内"), (365, "不限"),
    ])
    async def test_time_filter_mapping(self, window_days, expected):
        assert _xhs_time_filter(window_days) == expected
        collector, client = _mocked_collector(comment_post_limit=0)
        mock = AsyncMock(return_value=_xhs_search_data())  # 空页即停
        with patch.object(client, "get", mock):
            await collector.search("m", "xhs", window_days=window_days)
        params = mock.call_args.kwargs["params"]
        assert params["time_filter"] == expected
        assert params["sort_type"] == "general"
        assert params["note_type"] == "不限"
        assert params["keyword"] == "m"

    @pytest.mark.asyncio
    async def test_pagination_passes_search_credentials(self):
        """翻页回传上一页 data 层的 search_id/search_session_id（首页省略）。"""
        page1 = _xhs_search_data(_xhs_note("nid-1"), search_id="sid-9", session_id="sess-9")
        page2 = _xhs_search_data()  # 空页即停
        collector, client = _mocked_collector(comment_post_limit=0)
        mock = AsyncMock(side_effect=[page1, page2])
        with patch.object(client, "get", mock):
            posts, _ = await collector.search("m", "xhs", mode="initial")

        assert len(posts) == 1
        assert mock.call_count == 2
        first_params = mock.call_args_list[0].kwargs["params"]
        second_params = mock.call_args_list[1].kwargs["params"]
        assert "search_id" not in first_params and "search_session_id" not in first_params
        assert second_params["search_id"] == "sid-9"
        assert second_params["search_session_id"] == "sess-9"
        assert second_params["page"] == 2

    @pytest.mark.asyncio
    async def test_note_id_and_xsec_token_in_url(self):
        collector, client = _mocked_collector(comment_post_limit=0)
        note = _xhs_note("6a86c2fe000000002500d609", xsec="YBO_tk=")
        with patch.object(client, "get", AsyncMock(return_value=_xhs_search_data(note))):
            posts, _ = await collector.search("m", "xhs")

        p0 = posts[0]
        # 与 OneAPI 惯例一致：xsec_token 进 URL query（详情凭证靠它持久化）
        assert p0["url"] == ("https://www.xiaohongshu.com/explore/"
                             "6a86c2fe000000002500d609?xsec_token=YBO_tk=")
        assert p0["xsec_token"] == "YBO_tk="
        assert p0["title"] == "M03 提车记"
        assert p0["author"] == "笔记作者"
        assert p0["likes"] == 10 and p0["comments"] == 5 and p0["shares"] == 2
        assert p0["collected"] == 3
        assert p0["published_at"] == _iso_utc(note["timestamp"])
        assert p0["platform"] == "xiaohongshu" and p0["source"] == "tikhub"

    @pytest.mark.asyncio
    async def test_inner_envelope_failure_raises_on_first_page(self):
        collector, client = _mocked_collector(comment_post_limit=0)
        bad = {"code": -1, "success": False, "data": None}
        with patch.object(client, "get", AsyncMock(return_value=bad)):
            with pytest.raises(TikHubError, match="内层失败"):
                await collector.search("m", "xhs")

    @pytest.mark.asyncio
    async def test_comment_cursor_json_passthrough_and_index_increment(self):
        cursor_json = '{"contextId":"8cd9f5","cursor":"6a792544","index":2,"pageArea":"ALL"}'
        page1 = _xhs_comment_payload([_xhs_comment("c1")], cursor=cursor_json, has_more=True)
        page2 = _xhs_comment_payload([])  # has_more False 即停
        collector, client = _mocked_collector()
        mock = AsyncMock(side_effect=[page1, page2])
        with patch.object(client, "get", mock):
            comments = await collector.fetch_comments_for_post(
                "https://www.xiaohongshu.com/explore/69854d140000000022008776", "xhs")

        assert mock.call_count == 2
        first_params = mock.call_args_list[0].kwargs["params"]
        second_params = mock.call_args_list[1].kwargs["params"]
        # 首页 cursor/share_text 空串（client 层过滤后不发送）；翻页 cursor JSON
        # 整串回传 + index+1
        assert first_params["cursor"] == "" and first_params["index"] == 0
        assert first_params["share_text"] == ""
        assert first_params["pageArea"] == "UNFOLDED"
        assert first_params["sort_strategy"] == "latest_v2"
        assert second_params["cursor"] == cursor_json
        assert second_params["index"] == 1
        assert first_params["note_id"] == "69854d140000000022008776"
        assert len(comments) == 1

    @pytest.mark.asyncio
    async def test_comment_field_mapping_and_ip_normalize(self):
        c = _xhs_comment("c9", ip="Shanghai", likes=5, minutes_ago=30)
        page = _xhs_comment_payload([c])
        collector, client = _mocked_collector()
        with patch.object(client, "get", AsyncMock(return_value=page)):
            comments = await collector.fetch_comments_for_post(
                "https://www.xiaohongshu.com/explore/69854d14", "xiaohongshu")

        c0 = comments[0]
        assert c0["content"] == "这车真的不错"
        assert c0["author"] == "评论者"
        assert c0["likes"] == 5
        assert c0["ip_label"] == "上海"                  # Shanghai → 中文
        assert c0["reply_count"] == 4                    # sub_comment_count
        assert c0["published_at"] == _iso_utc(c["time"])  # time unix 秒
        assert c0["post_note_id"] == "69854d14"
        assert c0["platform"] == "xiaohongshu"

    @pytest.mark.asyncio
    async def test_pinned_null_comment_skipped(self):
        # 置顶评论槽位为 null 的条目直接跳过（防御，样本中未出现但契约如此）
        page = _xhs_comment_payload([None, _xhs_comment("c2")])
        collector, client = _mocked_collector()
        with patch.object(client, "get", AsyncMock(return_value=page)):
            comments = await collector.fetch_comments_for_post(
                "https://www.xiaohongshu.com/explore/69854d14", "xhs")
        assert len(comments) == 1 and comments[0]["author"] == "评论者"

    @pytest.mark.asyncio
    async def test_zero_comment_notes_not_selected_for_comments(self):
        """默认排名路径（互动真实）：comments_count=0 的笔记不抓评论。
        （R33 接线后 xhs 增量仅 1 搜索页——Step6 调整夹具顺序）"""
        page1 = _xhs_search_data(_xhs_note("has-c", comments=5), _xhs_note("no-c", comments=0))
        collector, client = _mocked_collector(comment_post_limit=5)
        cmt = _xhs_comment_payload([])
        mock = AsyncMock(side_effect=[page1, cmt])
        with patch.object(client, "get", mock):
            _, comments = await collector.search("m", "xhs", window_days=7)
        assert mock.call_count == 2                     # 1 搜索页（策略 max_pages=1）+ 仅 has-c 一次评论调用
        assert mock.call_args_list[1].kwargs["params"]["note_id"] == "has-c"


# ======================================================================
# 快手 adapter
# ======================================================================


class TestKuaishouAdapter:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("window_days,expected", [
        (1, "one_day"), (7, "one_week"), (31, "one_month"), (365, "all"),
    ])
    async def test_publish_time_mapping(self, window_days, expected):
        assert _ks_publish_time(window_days) == expected
        collector, client = _mocked_collector(comment_post_limit=0)
        mock = AsyncMock(return_value=_ks_page(pcursor="no_more"))
        with patch.object(client, "get", mock):
            await collector.search("m", "kuaishou", window_days=window_days)
        params = mock.call_args.kwargs["params"]
        assert params["publish_time"] == expected
        assert params["sort_type"] == "all"
        assert params["keyword"] == "m"
        assert "pcursor" not in params                   # 首页不带

    @pytest.mark.asyncio
    async def test_feed_fields_and_ms_timestamp(self):
        feed = _ks_feed("5252886156194117913")
        collector, client = _mocked_collector(comment_post_limit=0)
        mock = AsyncMock(return_value=_ks_page(feed, pcursor="no_more"))
        with patch.object(client, "get", mock):
            posts, _ = await collector.search("m", "ks")

        p0 = posts[0]
        assert p0["url"] == "https://www.kuaishou.com/short-video/5252886156194117913"
        assert p0["photo_id"] == "5252886156194117913"   # 评论回链键
        assert p0["author"] == "快手作者"
        assert p0["likes"] == 12 and p0["comments"] == 3 and p0["shares"] == 1
        assert p0["view_count"] == 400 and p0["collected"] == 6
        assert p0["forward_count"] == 0
        # 毫秒 → 秒：与 _parse_datetime 数值分支同口径（UTC）
        assert p0["published_at"] == _iso_utc(feed["timestamp"] // 1000)
        assert p0["platform"] == "kuaishou" and p0["source"] == "tikhub"

    @pytest.mark.asyncio
    async def test_pcursor_pagination_and_no_more_stop(self):
        feed1, feed2 = _ks_feed("52001"), _ks_feed("52002")
        page1 = _ks_page(feed1, pcursor=1)              # 样本实锤：pcursor 可为 int
        page2 = _ks_page(feed2, pcursor="no_more")
        collector, client = _mocked_collector(comment_post_limit=0)
        mock = AsyncMock(side_effect=[page1, page2])
        with patch.object(client, "get", mock):
            posts, _ = await collector.search("m", "kuaishou", mode="incremental")

        assert len(posts) == 2
        assert mock.call_count == 2
        assert mock.call_args_list[1].kwargs["params"]["pcursor"] == "1"  # int 已 str 化回传

    @pytest.mark.asyncio
    async def test_all_duplicate_page_stops_pagination(self):
        feed = _ks_feed("53001")
        page1 = _ks_page(feed, pcursor="1")
        page2 = _ks_page(feed, feed, pcursor="2")       # 全重复
        collector, client = _mocked_collector(comment_post_limit=0)
        mock = AsyncMock(side_effect=[page1, page2])
        with patch.object(client, "get", mock):
            posts, _ = await collector.search("m", "kuaishou")
        assert mock.call_count == 2                      # 全重复即停（即便还有 pcursor）
        assert len(posts) == 1

    @pytest.mark.asyncio
    async def test_ad_card_without_photo_id_skipped(self):
        ad_card = {"itemType": 9, "feed": {"caption": "广告"}}  # 无 photo_id
        payload = {"mixFeeds": [ad_card, {"feed": _ks_feed("54001")}], "pcursor": "no_more"}
        collector, client = _mocked_collector(comment_post_limit=0)
        with patch.object(client, "get", AsyncMock(return_value=payload)):
            posts, _ = await collector.search("m", "ks")
        assert len(posts) == 1 and posts[0]["photo_id"] == "54001"

    @pytest.mark.asyncio
    async def test_comment_field_mapping_and_pagination(self):
        ts_ms = int((datetime.now() - timedelta(minutes=10)).timestamp() * 1000)
        page1 = {"rootComments": [_ks_root_comment(ts_ms)], "pcursor": "V2#next#dph#30",
                 "commentCount": 968}
        page2 = {"rootComments": [], "pcursor": "no_more"}
        collector, client = _mocked_collector()
        mock = AsyncMock(side_effect=[page1, page2])
        with patch.object(client, "get", mock):
            comments = await collector.fetch_comments_for_post(
                "https://www.kuaishou.com/short-video/5252886156194117913", "kuaishou")

        assert mock.call_count == 2
        assert mock.call_args_list[1].kwargs["params"]["pcursor"] == "V2#next#dph#30"
        c0 = comments[0]
        assert c0["content"] == "这车续航如何"
        assert c0["author"] == "翔际"
        assert c0["likes"] == 64                          # likedCount（camelCase 无 d）
        assert c0["ip_label"] == "北京"                    # authorArea 中文直用
        assert c0["reply_count"] == 20                    # subCommentCount
        assert c0["comment_id"] == "889001835226"
        assert c0["published_at"] == _iso_utc(ts_ms // 1000)
        assert c0["post_note_id"] == "5252886156194117913"  # photo_id 回链
        assert c0["platform"] == "kuaishou"


# ======================================================================
# 抖音评论（搜索不在本 collector）
# ======================================================================


class TestDouyinSearch:
    """搜索 v1（search 命名空间，唯一 POST 端点）：OneAPI 空窗备胎。"""

    @pytest.mark.asyncio
    async def test_routes_douyin_alias_to_search_v1(self):
        """douyin/dy 别名走 douyin.search（旧"路由 OneAPI 硬抛错"已随备胎作废）。"""
        collector, client = _mocked_collector(comment_post_limit=0)
        with patch.object(client, "post",
                          AsyncMock(return_value=_dy_search_data())) as mock_post:
            posts, comments = await collector.search("kw", "dy")
        assert mock_post.call_args.args == ("douyin.search",)
        assert posts == [] and comments == []

    @pytest.mark.asyncio
    async def test_post_params_contract(self):
        """参数契约：sort_type/publish_time 字符串、search_id 空串被过滤。"""
        collector, client = _mocked_collector(comment_post_limit=0)
        with patch.object(client, "post",
                          AsyncMock(return_value=_dy_search_data())) as mock_post:
            await collector.search("小鹏M03", "douyin", window_days=7,
                                   mode="incremental")
        assert mock_post.call_args.kwargs["params"] == {
            "keyword": "小鹏M03", "cursor": 0, "sort_type": "2",
            "publish_time": "7", "search_id": ""}  # 空串在 client._send 过滤

    @pytest.mark.asyncio
    async def test_parses_video_cards_skips_non_video_and_dedup(self):
        a1 = _dy_aweme("7684094850217015534", hours_ago=1)
        a2 = _dy_aweme("7684091240073761957", hours_ago=2)
        page = _dy_search_data(
            {"type": 1, "aweme_info": a1},
            {"type": 6},                          # 广告/推荐卡：无 aweme_info
            {"type": 1},                          # 空卡防御
            {"type": 1, "aweme_info": a2},
            {"type": 1, "aweme_info": dict(a1)},  # 重复 aweme_id 去重
        )
        collector, client = _mocked_collector(comment_post_limit=0)
        with patch.object(client, "post", AsyncMock(return_value=page)), \
             patch.object(client, "get",
                          AsyncMock(return_value={"statistics_list": []})):
            posts, _ = await collector.search("kw", "douyin")
        assert [p["url"] for p in posts] == [
            "https://www.douyin.com/video/7684094850217015534",
            "https://www.douyin.com/video/7684091240073761957"]
        p0 = posts[0]
        assert p0["platform"] == "douyin"
        assert p0["source"] == "tikhub"
        assert p0["author"] == "抖音作者"
        assert p0["ip_label"] == "广西"                  # ip_attribution 中文直用
        assert p0["published_at"] == _iso_utc(a1["create_time"])  # Unix 秒
        assert p0["content"] == "M03 城市续航实测"

    @pytest.mark.asyncio
    async def test_stats_backfill_merges_real_counts(self):
        """搜索级 statistics 恒 0 → 批量统计回填 digg/play 真值（None 字段跳过）。"""
        page = _dy_search_data(
            {"type": 1, "aweme_info": _dy_aweme("111")},
            {"type": 1, "aweme_info": _dy_aweme("222")},
        )
        collector, client = _mocked_collector(comment_post_limit=0)
        stats_data = {"statistics_list": [
            {"aweme_id": "111", "play_count": 1446, "digg_count": 2009,
             "share_count": 7},
            {"aweme_id": "222", "play_count": 88, "digg_count": 91,
             "comment_count": None},   # 契约：可为 None → 不写
        ]}
        with patch.object(client, "post", AsyncMock(return_value=page)), \
             patch.object(client, "get", AsyncMock(return_value=stats_data)):
            posts, _ = await collector.search("kw", "douyin")
        p1, p2 = posts
        assert p1["likes"] == 2009 and p1["shares"] == 7 and p1["view_count"] == 1446
        assert p2["likes"] == 91 and p2["view_count"] == 88
        assert p2["comments"] == 0                     # None → 保持 0 不写

    @pytest.mark.asyncio
    async def test_stats_failure_keeps_posts_with_zero_counts(self):
        """统计回填失败不炸搜索：帖照常返回，互动数留 0。"""
        page = _dy_search_data({"type": 1, "aweme_info": _dy_aweme("111")})
        collector, client = _mocked_collector(comment_post_limit=0)
        with patch.object(client, "post", AsyncMock(return_value=page)), \
             patch.object(client, "get",
                          AsyncMock(side_effect=TikHubError("stats boom"))):
            posts, _ = await collector.search("kw", "douyin")
        assert len(posts) == 1 and posts[0]["likes"] == 0

    @pytest.mark.asyncio
    async def test_comments_collected_despite_zero_interaction(self):
        """rank_by_time 选帖：comments=0 不再被 comments>0 过滤饿死（P0-2 同款）；
        评论端点 total 回填帖评论数（搜索级恒 0 的可靠来源）。"""
        page = _dy_search_data({"type": 1, "aweme_info": _dy_aweme("111", hours_ago=1)})
        collector, client = _mocked_collector()
        stats_data = {"statistics_list": [
            {"aweme_id": "111", "play_count": 10, "digg_count": 3}]}
        comments_page = {"comments": [_dy_comment()], "has_more": 0, "total": 5}
        with patch.object(client, "post", AsyncMock(return_value=page)), \
             patch.object(client, "get",
                          AsyncMock(side_effect=[stats_data, comments_page])):
            posts, comments = await collector.search("kw", "douyin", window_days=7)
        assert len(comments) == 1
        assert comments[0]["post_note_id"] == "111"
        assert posts[0]["comments"] == 5                # total 回填 > 0

    @pytest.mark.asyncio
    async def test_pagination_cursor_advance_and_stop(self):
        """翻页：cursor 递进回传 + search_id 传上页 log_pb.impr_id（探针 D2
        契约）+ has_more=0 停 + aweme_id 去重跨页生效。"""
        p1 = _dy_search_data({"type": 1, "aweme_info": _dy_aweme("111")},
                             has_more=1, cursor=8, impr_id="impr-page1")
        p2 = _dy_search_data({"type": 1, "aweme_info": _dy_aweme("222")},
                             has_more=0, cursor=16)
        collector, client = _mocked_collector(comment_post_limit=0)
        with patch.object(client, "post",
                          AsyncMock(side_effect=[p1, p2])) as mock_post, \
             patch.object(client, "get",
                          AsyncMock(return_value={"statistics_list": []})):
            posts, _ = await collector.search("kw", "douyin")
        assert mock_post.call_count == 2
        assert mock_post.call_args_list[1].kwargs["params"]["cursor"] == 8
        assert mock_post.call_args_list[1].kwargs["params"]["search_id"] == "impr-page1"
        assert len(posts) == 2

    @pytest.mark.asyncio
    async def test_pagination_without_impr_id_stops(self):
        """无翻页凭证保险丝：has_more=1 但响应无 log_pb.impr_id → 不硬翻第 2
        页（探针 D1：缺 search_id 的第 2 页 4 连 400 确定性失败）。"""
        p1 = _dy_search_data({"type": 1, "aweme_info": _dy_aweme("111")},
                             has_more=1, cursor=8, impr_id="")
        collector, client = _mocked_collector(comment_post_limit=0)
        with patch.object(client, "post",
                          AsyncMock(side_effect=[p1])) as mock_post, \
             patch.object(client, "get",
                          AsyncMock(return_value={"statistics_list": []})):
            posts, _ = await collector.search("kw", "douyin")
        assert mock_post.call_count == 1      # 第 2 页根本不发
        assert len(posts) == 1

    @pytest.mark.asyncio
    async def test_page_failure_keeps_collected_posts(self):
        """翻页失败不炸：保留已采帖中断（同微博/快手语义）。"""
        p1 = _dy_search_data({"type": 1, "aweme_info": _dy_aweme("111")},
                             has_more=1, cursor=8)
        collector, client = _mocked_collector(comment_post_limit=0)
        with patch.object(client, "post",
                          AsyncMock(side_effect=[p1, TikHubError("page2 boom")])), \
             patch.object(client, "get",
                          AsyncMock(return_value={"statistics_list": []})):
            posts, _ = await collector.search("kw", "douyin")
        assert len(posts) == 1

    @pytest.mark.asyncio
    async def test_first_page_failure_raises(self):
        collector, client = _mocked_collector(comment_post_limit=0)
        with patch.object(client, "post",
                          AsyncMock(side_effect=TikHubError("all boom"))):
            with pytest.raises(TikHubError, match="all boom"):
                await collector.search("kw", "douyin")


class TestDouyinComments:
    @pytest.mark.asyncio
    async def test_aweme_id_from_url_and_field_mapping(self):
        c = _dy_comment()
        page1 = {"comments": [c], "cursor": 20, "has_more": 1, "total": 1}
        page2 = {"comments": [], "cursor": 40, "has_more": 0}
        collector, client = _mocked_collector()
        mock = AsyncMock(side_effect=[page1, page2])
        with patch.object(client, "get", mock):
            comments = await collector.fetch_comments_for_post(
                "https://www.douyin.com/video/7684062274742778793", "douyin")

        assert mock.call_count == 2
        c0 = comments[0]
        assert c0["content"] == "帮帮忙一直忙"
        assert c0["author"] == "郑在输入中……"             # user.nickname
        assert c0["likes"] == 3                           # digg_count
        assert c0["ip_label"] == "广西"                    # 中文直用
        assert c0["reply_count"] == 2                     # reply_comment_total
        assert c0["published_at"] == _iso_utc(c["create_time"])
        assert c0["post_note_id"] == "7684062274742778793"
        assert c0["platform"] == "douyin"

    @pytest.mark.asyncio
    async def test_cursor_increments_by_count(self):
        page1 = {"comments": [], "cursor": 20, "has_more": 1}
        page2 = {"comments": [], "has_more": 0}
        collector, client = _mocked_collector()
        mock = AsyncMock(side_effect=[page1, page2])
        with patch.object(client, "get", mock):
            await collector.fetch_comments_for_post("https://www.douyin.com/video/42", "dy")
        first_params = mock.call_args_list[0].kwargs["params"]
        second_params = mock.call_args_list[1].kwargs["params"]
        assert first_params == {"aweme_id": "42", "cursor": 0, "count": 20}
        assert second_params["cursor"] == 20              # 0 → 20 递增

    @pytest.mark.asyncio
    async def test_single_page_when_has_more_false(self):
        page = {"comments": [_dy_comment()], "cursor": 20, "has_more": 0}
        collector, client = _mocked_collector()
        mock = AsyncMock(return_value=page)
        with patch.object(client, "get", mock):
            comments = await collector.fetch_comments_for_post(
                "https://www.douyin.com/video/7", "douyin")
        assert mock.call_count == 1 and len(comments) == 1

    @pytest.mark.asyncio
    async def test_empty_comments_with_filter_list_logged_not_raised(self, caplog):
        """200-空防御（官方文档，无实测样本）：无评论 + filter_list = 可见性过滤
        （filter_code 8=版权/已删除 5=私密 10=部分可见），log info 归因，
        不重试不炸，直接终止翻页。"""
        page = {"comments": [], "cursor": 20, "has_more": 1,  # has_more=1 也不翻页
                "filter_list": [{"filter_code": 8, "reason": "视频因版权问题不可见"}]}
        collector, client = _mocked_collector()
        mock = AsyncMock(return_value=page)
        with patch.object(client, "get", mock):
            with caplog.at_level(logging.INFO,
                                 logger="pipeline.collectors.tikhub_collector"):
                comments = await collector.fetch_comments_for_post(
                    "https://www.douyin.com/video/7", "douyin")
        assert comments == []
        assert mock.call_count == 1                      # 不重试、不翻页
        assert any("版权" in r.message for r in caplog.records)  # reason 归因入日志


class TestDouyinStats:
    @pytest.mark.asyncio
    async def test_comma_join_and_statistics_map(self):
        data = {"statistics_list": [
            {"aweme_id": 7684094850217015534, "play_count": 7, "digg_count": 1},
            {"aweme_id": "7684062274742778793", "play_count": 100, "digg_count": 2},
        ]}
        client = TikHubClient(base_url="https://tikhub.test", api_key="k")
        mock = AsyncMock(return_value=data)
        with patch.object(client, "get", mock):
            stats = await client.fetch_douyin_play_stats(
                ["7684094850217015534", "7684062274742778793"])
        assert mock.call_args.kwargs["params"] == {
            "aweme_ids": "7684094850217015534,7684062274742778793"}
        assert stats["7684094850217015534"]["play_count"] == 7
        assert stats["7684062274742778793"]["digg_count"] == 2
        assert len(stats) == 2

    @pytest.mark.asyncio
    async def test_batches_over_20(self):
        ids = [f"aweme{i}" for i in range(21)]
        client = TikHubClient(base_url="https://tikhub.test", api_key="k")
        mock = AsyncMock(return_value={"statistics_list": []})
        with patch.object(client, "get", mock):
            await client.fetch_douyin_play_stats(ids)
        assert mock.call_count == 2
        first = mock.call_args_list[0].kwargs["params"]["aweme_ids"]
        second = mock.call_args_list[1].kwargs["params"]["aweme_ids"]
        assert first.count(",") == 19                    # 20 个一批
        assert first.split(",")[-1] == "aweme19"
        assert second == "aweme20"

    @pytest.mark.asyncio
    async def test_empty_ids_no_call(self):
        client = TikHubClient(base_url="https://tikhub.test", api_key="k")
        mock = AsyncMock()
        with patch.object(client, "get", mock):
            assert await client.fetch_douyin_play_stats([]) == {}
        mock.assert_not_called()


# ======================================================================
# _parse_datetime 新分支（微博相对/无年份格式，全动态日期）
# ======================================================================


class TestParseDatetimeWeibo:
    def test_minutes_ago_minute_precision(self):
        result = _parse_datetime("44分钟前")
        expected = (datetime.now() - timedelta(minutes=44)).replace(second=0, microsecond=0)
        # 容差断言：测试执行与解析时刻可能跨分钟边界
        delta = abs((datetime.fromisoformat(result) - expected).total_seconds())
        assert delta <= 60
        assert datetime.fromisoformat(result).second == 0

    def test_today_hhmm(self):
        result = _parse_datetime("今天09:30")            # 冒号前无空格
        assert result == f"{date.today():%Y-%m-%d}T09:30:00"
        assert _parse_datetime("今天 09:30") == result   # 带空格同义

    def test_yesterday_hhmm_keeps_time(self):
        result = _parse_datetime("昨天 08:59")
        yesterday = date.today() - timedelta(days=1)
        assert result == f"{yesterday:%Y-%m-%d}T08:59:00"

    def test_yesterday_without_time_falls_back(self):
        # 无时分的 '昨天' 兜底语义不变（00:00:00）
        result = _parse_datetime("昨天山东")
        yesterday = date.today() - timedelta(days=1)
        assert result == f"{yesterday:%Y-%m-%d}T00:00:00"

    def test_mmdd_this_year(self):
        # 过去日期（5 天前）→ 当年（1 月初跑跨年时解析自动回退上一年，期望值
        # 用同一 datetime 推算，天然正确）
        d = datetime.now() - timedelta(days=5)
        result = _parse_datetime(d.strftime("%m月%d日 08:00"))
        assert result == f"{d:%Y-%m-%d}T08:00:00"

    def test_mmdd_future_rolls_back_to_last_year(self):
        """未来日期（today+15d）→ 去年；若构造跨年（12 月）则换 today-15d 反向断言。"""
        future = date.today() + timedelta(days=15)
        if future.year == date.today().year:
            result = _parse_datetime(future.strftime("%m月%d日 08:00"))
            assert result == f"{future.year - 1:04d}-{future:%m-%d}T08:00:00"
        else:
            # today+15d 跨入下一年（today 在 12 月）→ 改用过去日期：当年不变
            past = date.today() - timedelta(days=15)
            result = _parse_datetime(past.strftime("%m月%d日 08:00"))
            assert result == f"{past:%Y-%m-%d}T08:00:00"

    def test_mmdd_invalid_date_returns_empty(self):
        assert _parse_datetime("2月30日 10:00") == ""

    def test_branch_order_no_regression(self):
        # 既有分支语义不回归
        assert _parse_datetime(1748217600) == "2025-05-26T00:00:00"
        assert _parse_datetime("Sun Jun 29 10:00:00 +0800 2025") == "2025-06-29T10:00:00"
        assert _parse_datetime("06-07 浙江").startswith(f"{date.today().year}-06-07")
        assert _parse_datetime("7天前浙江") == \
            f"{date.today() - timedelta(days=7):%Y-%m-%d}T00:00:00"


# ======================================================================
# Availability
# ======================================================================


class TestAvailability:
    @pytest.mark.asyncio
    async def test_is_available_with_key(self):
        collector, _ = _mocked_collector()
        assert await collector.is_available() is True

    @pytest.mark.asyncio
    async def test_not_available_without_key(self):
        collector = TikHubCollector(client=TikHubClient(api_key=""))
        assert await collector.is_available() is False


class TestSearchMaxPagesWiring:
    """R33 接线（Step6, 2026-10-16）：incremental 翻页消费策略 max_pages。

    接线前实测四平台统一翻 2 页（xhs 策略 max_pages=1 是死配置）；接线后
    xhs 增量 1 页（省 6 次/车/天）、dy 2 页、initial 维持 env 3 页。
    """

    def test_helper_strategy_values(self):
        assert _search_max_pages("xiaohongshu", "incremental") == 1
        assert _search_max_pages("douyin", "incremental") == 2
        # 停采平台经 get_strategy 回落 _DEFAULT（max_pages=1）
        assert _search_max_pages("weibo", "incremental") == 1
        assert _search_max_pages("kuaishou", "incremental") == 1

    def test_helper_initial_uses_env_constant(self):
        assert _search_max_pages("xiaohongshu", "initial") == 3
        assert _search_max_pages("douyin", "initial") == 3

    @pytest.mark.asyncio
    async def test_xhs_incremental_fetches_single_page(self):
        """首页有帖且有续页凭证（next_page=2）时，增量模式也只翻 1 页。"""
        page1 = _xhs_search_data(_xhs_note("nid-1"), search_id="sid-9",
                                 session_id="sess-9")
        collector, client = _mocked_collector(comment_post_limit=0)
        mock = AsyncMock(side_effect=[page1, _xhs_search_data()])
        with patch.object(client, "get", mock):
            posts, _ = await collector.search("m", "xhs", mode="incremental")
        assert len(posts) == 1
        assert mock.call_count == 1  # 策略 max_pages=1 截断，第 2 页不请求

    @pytest.mark.asyncio
    async def test_xhs_initial_still_paginates(self):
        """initial 维持 env 3 页：首页有帖、第 2 页空即停（翻页能力未损失）。"""
        page1 = _xhs_search_data(_xhs_note("nid-1"), search_id="sid-9",
                                 session_id="sess-9")
        collector, client = _mocked_collector(comment_post_limit=0)
        mock = AsyncMock(side_effect=[page1, _xhs_search_data()])
        with patch.object(client, "get", mock):
            posts, _ = await collector.search("m", "xhs", mode="initial")
        assert len(posts) == 1
        assert mock.call_count == 2  # 空页自然停，未触及 3 页帽
