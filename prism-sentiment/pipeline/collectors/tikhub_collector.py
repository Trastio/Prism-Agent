"""TikHub Collector — api.tikhub.dev 采集器（2026-09-27 起 OneAPI 退役，社媒单 provider）。

四平台策略：
- 微博：web_v2 高级搜索（3 页翻页实测通）
- 小红书：app_v2（搜索 + 评论）
- 快手：app search_comprehensive（mixFeeds[].feed）
- 抖音：搜索 = search 命名空间 v1（app/v3 搜索端点 404，见
  douyin_search_v1_p1.json）；评论 + 批量播放统计走 app_v3

计费（美元/次，logs/tikhub_test/round2/_billing.json 实测；详情端点为
logs/tikhub_test/probe/wb_detail_webv2_*.json 实测）：
微博搜索/评论/详情 $0.001；抖音搜索 $0.01、评论 $0.001、批量统计 $0.025；
xhs 搜索/评论 $0.01；快手搜索 $0.01、评论 $0.001。4xx 不计费。

契约要点（11 端点实测样本，logs/tikhub_test/round2/）：
- 信封 {code, message, data, cache_url}，HTTP 200 + code==200 才算成功；
  HTTP 401/403 是 key/账户问题 → TikHubAuthError 直抛不重试；4xx 快速
  失败但 400 三形态区分（_flaky_400_body，2026-09-27 探针）：{"detail":
  "文案"} 请求级不重试，顶层 {"code": 400} 与 {"detail": {"code": 400}}
  嵌套均为上游瞬时故障保留重试（429 限流 + xhs 400 预热同）
- xhs 双层信封：outer code==200 后内层 data.code==0 / success 才是真负载
- 除 douyin.search（POST JSON body，search 命名空间）外全部 GET + query
  params（中文 UTF-8 百分号编码由 httpx 保证）
- 微博搜索互动数恒 0（interaction 三键全 0，63/63 实证）→ top-N 帖走详情
  端点三合一回填（enrich_weibo_details：真互动数 + 带年份时间 + 长文全文），
  其余帖 comments 靠评论响应的 total_number 回填兜底

对外接口：search / fetch_comments_for_post / is_available。post/comment dict
复用 post_utils._make_post/_make_comment，source="tikhub"；附加字段
（weibo_id / photo_id / xsec_token / ip 属地）随 dict 透传，
scheduler._store_posts/_store_comments 只取已知键，多余键无害。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import date, timedelta
from typing import Any

import httpx
from dotenv import load_dotenv

from pipeline import platforms
from pipeline.collectors.budget import TikHubBudgetExceeded, count_and_check  # noqa: F401（re-export：scheduler 从本模块 import 异常类）
from pipeline.collectors.post_utils import (
    _dy_publish_time,
    _make_comment,
    _make_post,
    _parse_datetime,
    _path_tail,
    _safe_int,
    _strip_html,
    _truthy,
    comment_max_pages,
)
from pipeline.collectors.ip_location import normalize_ip_location
from utils.config import env_int

logger = logging.getLogger(__name__)

# ── 端点注册表（路径 + 参数名经 openapi + round2 实测双重核对）─────────
ENDPOINTS: dict[str, str] = {
    "weibo.search": "/api/v1/weibo/web_v2/fetch_advanced_search",  # q, page
    "weibo.fetch_post_detail": "/api/v1/weibo/web_v2/fetch_post_detail",  # id, is_get_long_text
    "weibo.fetch_post_comments": "/api/v1/weibo/web_v2/fetch_post_comments",  # id, count, max_id
    "douyin.search": "/api/v1/douyin/search/fetch_video_search_v1",  # POST body（唯一 POST 端点）: keyword, cursor, sort_type, publish_time, search_id, backtrace
    "douyin.fetch_video_comments": "/api/v1/douyin/app/v3/fetch_video_comments",  # aweme_id, cursor, count
    "douyin.fetch_multi_video_statistics": "/api/v1/douyin/app/v3/fetch_multi_video_statistics",  # aweme_ids(逗号连接)
    "xiaohongshu.search_notes": "/api/v1/xiaohongshu/app_v2/search_notes",  # keyword, page, sort_type, note_type, time_filter, search_id?, search_session_id?
    "xiaohongshu.get_note_comments": "/api/v1/xiaohongshu/app_v2/get_note_comments",  # note_id, share_text, cursor, index, pageArea, sort_strategy
    "xiaohongshu.get_note_detail": "/api/v1/xiaohongshu/app_v2/get_image_note_detail",  # note_id — 互动刷新笔记详情（图文+视频通用，免 xsec_token）
    "kuaishou.search_comprehensive": "/api/v1/kuaishou/app/search_comprehensive",  # keyword, pcursor?, sort_type, publish_time
    "kuaishou.fetch_video_comment": "/api/v1/kuaishou/app/fetch_video_comment",  # photo_id, pcursor?
    "kuaishou.fetch_videos_batch": "/api/v1/kuaishou/app/fetch_videos_batch",  # photo_ids(逗号连接, ≤40) — 互动刷新批量详情
    # 搜索指数（IndexCollector 用；均 09-12 index_probe.py 实测）
    "douyin.index_trend": "/api/v1/douyin/index/fetch_multi_keyword_hot_trend",  # POST+query: keyword_list(逗号), start/end_date(YYYYMMDD), app_name(aweme/toutiao)
    "xiaohongshu.pgy_keyword_daily": "/api/v1/xiaohongshu/pgy/get_keyword_daily",  # POST JSON: search_word；返回固定近三月
}

DEFAULT_BASE_URL = "https://api.tikhub.dev"

# 信封业务码：HTTP 恒 200（4xx 也不计费），成败看 JSON code
CODE_OK = 200

# 同一端点总尝试次数上限（保守护栏）
MAX_ATTEMPTS = env_int("TIKHUB_MAX_ATTEMPTS", 5)

# 单次搜索内抓评论的帖数上限（按计费控制）
_COMMENT_POST_LIMIT = env_int("TIKHUB_COMMENT_POST_LIMIT", 5)
# 单次搜索内详情回填的微博帖数上限（按计费控制，$0.001/帖）
_DETAIL_POST_LIMIT = env_int("TIKHUB_DETAIL_POST_LIMIT", 5)
# 单帖评论翻页上限：共享 post_utils.comment_max_pages()（env
# COMMENT_MAX_PAGES，默认 3——看板评估 P1-6 的 2→3）
# 抖音批量统计单批上限（aweme_ids 逗号连接，openapi 无显式上限，20 稳妥）
_STATS_BATCH_SIZE = env_int("TIKHUB_STATS_BATCH_SIZE", 20)
# 搜索翻页上限（计费护栏）：initial 首轮大窗 / incremental 日常增量
_SEARCH_PAGES_INITIAL = env_int("TIKHUB_SEARCH_PAGES_INITIAL", 3)
_SEARCH_PAGES_INCREMENTAL = env_int("TIKHUB_SEARCH_PAGES_INCREMENTAL", 2)  # 归档：R33 接线后 incremental 走策略值


def _search_max_pages(platform: str, mode: str) -> int:
    """搜索翻页数（R33 接线，2026-10-16 Step6）：incremental 消费
    platform_strategy.max_pages（xhs=1 / dy=2——此前该字段是死配置，实测
    四平台统一翻 2 页）；initial 维持 env _SEARCH_PAGES_INITIAL（30 天回补
    窗需要 ≥3 页深度，策略 max_pages 是增量口径）。**仅活跃平台接线**——
    停采平台（weibo/ks）走归档分支保持 env 常量原样，不经本函数。"""
    if mode == "initial":
        return _SEARCH_PAGES_INITIAL
    from pipeline.collectors.platform_strategy import get_strategy
    return get_strategy(platform).max_pages


# ======================================================================
# Helpers
# ======================================================================


def _tikhub_post(**kwargs) -> dict:
    """_make_post 包装：source 标 tikhub（cdp 版硬编码 source="cdp"）。"""
    post = _make_post(**kwargs)
    post["source"] = "tikhub"
    return post


# xhs time_filter：window_days → 中文枚举档（契约枚举：不限/一天内/一周内/半年内）
def _xhs_time_filter(window_days: int) -> str:
    if window_days <= 1:
        return "一天内"
    if window_days <= 7:
        return "一周内"
    if window_days <= 180:
        return "半年内"
    return "不限"


# 快手 publish_time：window_days → 英文枚举档（one_day/one_week/one_month/all）
def _ks_publish_time(window_days: int) -> str:
    if window_days <= 1:
        return "one_day"
    if window_days <= 7:
        return "one_week"
    if window_days <= 31:
        return "one_month"
    return "all"


# 微博评论 source 的 IP 属地："来自 广东" → "广东"（区别于搜索结果的"微博网页版"
# 设备来源，评论的 source 实测均为属地语义）
_WEIBO_IP_RE = re.compile(r"来自\s*(.+)$")


# ======================================================================
# Errors + client
# ======================================================================


class TikHubError(Exception):
    """TikHub 请求失败（重试耗尽 / 业务 code 异常 / 端点未知）。"""


class TikHubAuthError(TikHubError):
    """不可重试的账户级错误：HTTP 401 key 无效 / 402 余额耗尽 / 403 账户不可用。"""


def _error_detail(resp) -> str:
    """4xx 快速失败的消息正文：优先 JSON detail 字段（TikHub 4xx 惯例，
    body 是 {"detail": ...} 无顶层 code），非 JSON 兜底取前 200 字符。"""
    try:
        payload = resp.json()
    except Exception:
        payload = None
    if isinstance(payload, dict) and payload.get("detail"):
        d = payload["detail"]
        if isinstance(d, dict):
            # 嵌套信封形态（2026-09-27 实测）：{"detail": {"code": 400,
            # "message": ...}}——取 code+message，比整 dict repr 可读
            return f"{d.get('code', '')} {d.get('message', '')}".strip()[:200]
        return str(d)[:200]
    return (resp.text or "")[:200]


def _flaky_400_body(body: Any) -> bool:
    """HTTP 400 的上游瞬时故障判定（官方"Please retry"，4xx 不计费）。

    实测三形态（2026-09-27 探针：dy search 第 1 页连 4 次 400 后第 5 次
    成功；统计端点 400→重试即 200）：
    1. 顶层 {"code": 400, "message": "Request failed. Please retry"}
    2. {"detail": {"code": 400, "message": ..., "request_id": ...}}（code
       嵌在 detail 里——旧判定只看顶层 code，漏判成请求级错误直接抛，
       即"搜索第 2 页 400 / 统计端点 400"实采症状的根因）
    3. {"detail": "具体错误文案"}（字符串）——请求级参数错，不重试。

    v3 报告 §8.1 修正（2026-10-06）：code=-1 是永久错误（"Please retry"
    但重试 5 次仍失败），不算 flaky，不重试。只有 code=400（预热/瞬时）
    才重试。
    """
    if not isinstance(body, dict):
        return False
    if "code" in body:
        # code=400 是上游瞬时故障（预热/官方让 retry）；code=-1 是永久错误不重试
        return _safe_int(body.get("code"), default=-1) == 400
    detail = body.get("detail")
    if isinstance(detail, dict) and "code" in detail:
        return _safe_int(detail.get("code"), default=-1) == 400
    return False


class TikHubClient:
    """TikHub 通用异步 client：GET + 信封解析 + 重试退避。

    调用约束（round2 实测 + 官方文档 + M03 实采 + 2026-09-27 探针）：
    HTTP 200 + envelope code==200 成功计费；HTTP 401/403 → key/账户错误
    （4xx 不计费），重试无意义直接抛 TikHubAuthError；429 限流 → 保留重试
    （退避有意义）；HTTP 400 三形态（_flaky_400_body）：顶层带 code 键或
    {"detail": {code, message}} 嵌套 = 上游瞬时故障保留重试（官方让
    retry 且 4xx 不计费；2026-09-27 探针：dy search 第 1 页连 4 次 400
    第 5 次成功、统计端点 400 重试即 200——嵌套形态是"搜索第 2 页 400 /
    统计端点 400"两实采症状的根因），{"detail": "文案"} = 请求级参数错
    不重试；xiaohongshu.* 的 400 同为保留重试（官方文档：xhs 后端预热
    慢，首访常 400，重试 1-2 次即成功）；其余 4xx → 请求级错误立即抛不
    重试；envelope code!=200 业务失败 → 重试（指数退避 1s×2^n）。
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 60.0,
        max_attempts: int = MAX_ATTEMPTS,
        retry_backoff: float = 1.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        load_dotenv()
        self._base_url = (base_url or os.getenv("TIKHUB_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        # 显式传 ""（测试强制无 key）不回退环境变量，None 才走 .env
        if api_key is None:
            api_key = os.getenv("TIKHUB_KEY", "")
        self._api_key = api_key
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._retry_backoff = retry_backoff
        # 测试注入口：httpx.MockTransport 抓真实请求行（中文参数编码断言用）
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    async def get(self, endpoint: str, params: dict | None = None) -> Any:
        """GET 一个端点（query params），返回信封里的 data；失败按约束重试。"""
        return await self._send("GET", endpoint, params, as_query=True)

    async def post(self, endpoint: str, params: dict | None = None) -> Any:
        """POST 一个端点（params 走 JSON body），返回信封里的 data。

        目前仅 douyin.search（search 命名空间 v1，round2 billing 实测
        method=POST）；重试/4xx 快速失败语义与 get() 完全一致。
        """
        return await self._send("POST", endpoint, params, as_query=False)

    async def post_query(self, endpoint: str, params: dict | None = None) -> Any:
        """POST 但参数挂 query string（TikHub 不一致面）：douyin 指数端点
        实测 HTTP 405 拒 GET、参数在 query（index_probe.py 09-12）。"""
        return await self._send("POST", endpoint, params, as_query=True)

    async def _send(self, method: str, endpoint: str, params: dict | None,
                    as_query: bool = True) -> Any:
        """get/post 共用请求核：URL 装配 + 信封解析 + 重试退避。"""
        if endpoint not in ENDPOINTS:
            raise TikHubError(f"未知端点: {endpoint}")
        if not self._api_key:
            raise TikHubAuthError("TIKHUB_KEY 未配置（.env）")
        # 日预算护栏（T2/L6，方案 R43）：get/post/post_query 全过 _send，**每次
        # HTTP 尝试前**计数校验（P2①·Step7 审查：原实现计数在重试循环外，一次
        # _send 内最多 _max_attempts 次计费请求只计 1，429/瞬时故障重试可穿透
        # 预算）。超限抛 TikHubBudgetExceeded 且该次请求不发出。该异常故意不
        # 继承 TikHubError——关键词级 except 不吞预算事件，且本循环的 except 面
        # （TikHubAuthError 直抛 / 网络三态可重试）也不会捕获它，直接冒泡到
        # collect_vehicle 顶层标 budget_capped + 登记未采车。
        url = f"{self._base_url}{ENDPOINTS[endpoint]}"
        # None / 空串参数不发送（与"首页不带翻页游标"的调用约定一致；int 0 保留）
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        last_err: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            count_and_check()
            try:
                async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                    if method == "POST" and as_query:
                        resp = await client.post(url, params=clean, headers=self._auth_headers())
                    elif method == "POST":
                        resp = await client.post(url, json=clean, headers=self._auth_headers())
                    else:
                        resp = await client.get(url, params=clean, headers=self._auth_headers())
                if resp.status_code in (401, 403, 402):
                    # HTTP 层 key/账户错误：401 无效 key / 403 账户不可用 /
                    # 402 余额耗尽（2026-09-12 实采实证：烧完后所有端点 402，
                    # 4xx 不计费重试无意义；当普通 4xx 吞掉会伪装成"完成"）
                    raise TikHubAuthError(
                        f"TikHub {endpoint} HTTP {resp.status_code}: {resp.text[:120]}")
                if (400 <= resp.status_code < 500 and resp.status_code != 429):
                    # 400 双形态→三形态（M03 实采 + 2026-09-27 探针）：
                    # _flaky_400_body 命中（顶层 code 或 detail 嵌套 code）=
                    # 上游瞬时故障，官方让 retry 且 4xx 不计费 → 落到下方
                    # 信封解析走重试；其余 4xx 一律请求级快速失败。
                    # 429 限流与 xhs 400 预热同样走重试（xhs 后端冷启动慢）。
                    upstream_flaky = False
                    if resp.status_code == 400:
                        try:
                            upstream_flaky = _flaky_400_body(resp.json())
                        except ValueError:
                            upstream_flaky = False
                    if not upstream_flaky:
                        # v3 报告 §8.1：移除 xhs 豁免，所有平台永久 4xx
                        # （_flaky_400_body False）都立即抛不重试。xhs 预热
                        # 400（code=400）由 _flaky_400_body 判 True 保留重试。
                        raise TikHubError(
                            f"TikHub {endpoint} HTTP {resp.status_code}: "
                            f"{_error_detail(resp)}")
                payload = resp.json()
            except TikHubAuthError:
                raise
            except (httpx.TimeoutException, httpx.TransportError, ValueError) as e:
                # 网络层异常 / 非 JSON 响应 —— 可重试
                last_err = e
                logger.warning("TikHub %s 请求异常 (attempt %d/%d): %s",
                               endpoint, attempt, self._max_attempts, e)
            else:
                code = _safe_int(payload.get("code"), default=-1)
                if code == CODE_OK:
                    return payload.get("data")
                last_err = TikHubError(
                    f"TikHub {endpoint} 业务失败 code={code}: "
                    f"{payload.get('message') or _error_detail(resp)}")
                logger.warning("%s (attempt %d/%d)", last_err, attempt, self._max_attempts)
            if attempt < self._max_attempts:
                await asyncio.sleep(self._retry_backoff * (2 ** (attempt - 1)))
        raise TikHubError(f"TikHub {endpoint} 重试耗尽: {last_err}")

    # ── 批量工具（热度刷新 / 播放量补全）──────────────────────────

    async def fetch_douyin_play_stats(self, aweme_ids: list[str]) -> dict[str, dict]:
        """抖音批量统计（app_v3）——播放量补全位，$0.025/批。

        aweme_ids 逗号连接（≤20 一批）；返回 {aweme_id: 原始统计 dict}。
        实测字段 aweme_id/play_count/digg_count（share_count 未出现在样本，
        上游若有会随原始 dict 透传）。
        """
        out: dict[str, dict] = {}
        for i in range(0, len(aweme_ids), _STATS_BATCH_SIZE):
            batch = [str(a) for a in aweme_ids[i:i + _STATS_BATCH_SIZE]]
            data = await self.get("douyin.fetch_multi_video_statistics",
                                  params={"aweme_ids": ",".join(batch)})
            for st in (data or {}).get("statistics_list") or []:
                aid = str(st.get("aweme_id") or "")
                if aid:
                    out[aid] = st
        return out


# ======================================================================
# Collector
# ======================================================================


class TikHubCollector:
    """TikHub 采集器。

    增量分层与 OneAPI 一致：collector 不碰 DB，去重/时间窗截断在 scheduler
    _store_posts（URL dedup + min_date floor）。本层做的增量：
    - xhs time_filter / kuaishou publish_time 时间窗参数
    - 微博页级时间截断（publish_time 出窗即停翻页）
    """

    def __init__(
        self,
        client: TikHubClient | None = None,
        comment_post_limit: int = _COMMENT_POST_LIMIT,
        detail_post_limit: int = _DETAIL_POST_LIMIT,
        drop_at_comments: bool = True,
    ) -> None:
        self._client = client or TikHubClient()
        self._comment_post_limit = comment_post_limit
        self._detail_post_limit = detail_post_limit
        # @ 开头评论多为呼唤好友/回复他人，无实质内容（数据整理报告 §6），默认过滤
        self._drop_at_comments = drop_at_comments

    async def is_available(self) -> bool:
        """TikHub 无免费探活端点（每次调用都计费），只做本地配置检查。"""
        return self._client.configured

    async def search(
        self,
        keyword: str,
        platform: str,
        window_days: int = 7,
        mode: str = "incremental",
    ) -> tuple[list[dict], list[dict]]:
        """Search a platform, returning (posts, comments)。"""
        if platform in ("weibo", "wb"):
            return await self._search_weibo(keyword, window_days, mode)
        if platform in ("xiaohongshu", "xhs"):
            return await self._search_xhs(keyword, window_days, mode)
        if platform in ("kuaishou", "ks"):
            return await self._search_kuaishou(keyword, window_days, mode)
        if platform in ("douyin", "dy"):
            return await self._search_douyin(keyword, window_days, mode)
        return [], []

    async def fetch_comments_for_post(self, url: str, platform: str) -> list[dict]:
        """按 URL 补抓单帖评论。"""
        post = {"url": url}
        plat = platform.lower()
        if plat in ("weibo", "wb"):
            return await self._fetch_weibo_comments(post)
        if plat in ("douyin", "dy"):
            return await self._fetch_douyin_comments(post)
        if plat in ("xiaohongshu", "xhs"):
            return await self._fetch_xhs_comments(post)
        if plat in ("kuaishou", "ks"):
            return await self._fetch_kuaishou_comments(post)
        return []

    # ── 评论公共流程 ─────────────────────────────────────────────

    def _drop_at(self, text) -> bool:
        """@ 开头评论过滤开关（数据整理报告 §6：多为呼唤好友/回复他人，无实质内容）。"""
        return self._drop_at_comments and bool(text) and str(text).lstrip().startswith("@")

    async def _collect_comments_for_posts(
        self, posts: list[dict], fetcher, window_days: int | None = None,
        rank_by_time: bool = False,
    ) -> list[dict]:
        """对 top-N 的帖抓评论（按计费控制上限）。

        window_days：只对窗口内帖子抓评论——窗口外老帖会被 scheduler 的
        min_date floor 丢弃，其评论抓来即成孤儿（OneAPI 实采教训）。
        floor 对齐（T2.4 修）：scheduler 的 min_date floor = start_date，而
        window_days = (today - start_date).days + 1（含首尾两天），故评论候选
        下限 = today - (window_days - 1) = start_date。旧算法 today - window_days
        = start_date - 1，比入库 floor 松一天——恰在 start_date 前一天发布的
        帖评论照抓、入库被 floor 丢弃，白烧评论费还制造 unmatched。
        rank_by_time：微博帖互动数全 0（TikHub 契约），likes 排名与 comments>0
        过滤都无意义 → 改按 published_at 新→旧选帖。
        """
        candidates = posts
        if window_days:
            floor = (date.today() - timedelta(days=window_days - 1)).isoformat()
            candidates = [p for p in posts if (p.get("published_at") or "")[:10] >= floor]
        if rank_by_time:
            ranked = sorted(
                (p for p in candidates if p.get("published_at")),
                key=lambda p: p["published_at"], reverse=True,
            )[: self._comment_post_limit]
        else:
            ranked = sorted(
                (p for p in candidates if p.get("comments", 0) > 0),
                key=lambda p: p.get("likes", 0),
                reverse=True,
            )[: self._comment_post_limit]
        out: list[dict] = []
        for post in ranked:
            try:
                out.extend(await fetcher(post))
            except TikHubAuthError:
                raise  # 账户级错误继续抓只会白烧重试
            except Exception as e:
                logger.warning("TikHub 评论抓取失败 %s: %s", post.get("url"), e)
        return out

    # ── 微博 ─────────────────────────────────────────────────────

    async def _search_weibo(
        self, keyword: str, window_days: int = 7, mode: str = "incremental",
    ) -> tuple[list[dict], list[dict]]:
        """高级搜索（web_v2）：initial 3 页 / incremental 2 页。

        翻页语义（实测 3 页全通，区别于 OneAPI 上游 page>=2 固定失败）：
        - weibo_id 去重
        - 时间截断：搜索整体新→旧，该页最旧帖已出窗 → 后续页更老，停止翻页
          （本页帖子照常返回，floor 过滤是 scheduler 的事）
        - 翻页失败不炸整个搜索：保留已采帖中断翻页（同 OneAPI 快手语义）

        搜索后先 enrich_weibo_details 给 top-N 帖补三合一真值（真互动数/
        带年份时间/长文全文），再抓评论——与评论端点 total_number 回填是
        叠加关系：详情给 top-N 真值，评论端点 total_number 兜底其余帖，
        两侧都 >现值才写，互不覆盖。
        """
        # 停采平台不接线（Step6 裁决）：归档路径行为零变化，env 常量原样
        max_pages = _SEARCH_PAGES_INITIAL if mode == "initial" else _SEARCH_PAGES_INCREMENTAL
        floor = (date.today() - timedelta(days=window_days)).isoformat()
        posts: list[dict] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            try:
                data = await self._client.get(
                    "weibo.search", params={"q": keyword, "page": page})
            except TikHubAuthError:
                raise
            except Exception as e:
                if not posts:
                    raise  # 首页即失败：如实上抛
                logger.warning("TikHub weibo 搜索第 %d 页失败，保留已采 %d 帖: %s",
                               page, len(posts), e)
                break
            results = ((data or {}).get("parsed_data") or {}).get("results") or []
            if not results:
                break
            page_posts: list[dict] = []
            for r in results:
                if not isinstance(r, dict):
                    continue
                wid = str(r.get("weibo_id") or "")
                if not wid or wid in seen:
                    continue
                seen.add(wid)
                page_posts.append(self._weibo_post(r, wid))
            posts.extend(page_posts)
            page_pubs = [p["published_at"] for p in page_posts if p.get("published_at")]
            if page_pubs and min(page_pubs) < floor:
                break  # 时间截断：该页最旧帖已出窗
        # 详情回填在评论抓取之前：真互动数/带年份时间先落到帖上，评论选帖
        # （rank_by_time）即基于真时间；total_number 再兜底（两侧 >现值才写）
        await self.enrich_weibo_details(posts)
        comments = await self._collect_comments_for_posts(
            posts, self._fetch_weibo_comments, window_days=window_days, rank_by_time=True)
        return posts, comments

    @staticmethod
    def _weibo_post(r: dict, wid: str) -> dict:
        """advanced_search result → 标准帖。

        契约（weibo_advanced_p1.json）：content 纯文本（防御性剥标签）、
        post_url 协议相对且尾段是 bid（base62 非数字）、interaction 三键
        实测全 0（TikHub 不回传互动数，帖子 comments 靠评论 total_number
        回填）。URL 一律用数字 weibo_id 拼 m.weibo.cn/status/{wid}（与
        OneAPI _weibo_post 惯例一致）：评论端点吃数字 id，而 scheduler
        fetch_top_comments 只拿 URL 从尾段提 id，bid 回链必错；wid 缺失
        时才兜底原 post_url（协议相对补 https:）。
        """
        text = _strip_html(r.get("content") or "")
        raw_url = str(r.get("post_url") or "").strip()
        if wid:
            url = f"https://m.weibo.cn/status/{wid}"
        else:
            url = f"https:{raw_url}" if raw_url.startswith("//") else raw_url
        inter = r.get("interaction") or {}
        post = _tikhub_post(
            title=text[:80],
            content=text,
            author=r.get("user_nick") or r.get("user_name") or "",
            url=url,
            likes=inter.get("like_count"),
            comments_count=inter.get("comment_count"),
            shares=inter.get("repost_count"),
            platform=platforms.WEIBO,
            published_at=r.get("publish_time"),  # "09月09日 19:38" 等相对格式
        )
        # post_url 尾段是 bid（非数字 id），评论接口吃数字 id → 必须随 dict 透传
        post["weibo_id"] = wid
        return post

    async def enrich_weibo_details(self, posts: list[dict],
                                   limit: int | None = None) -> list[dict]:
        """微博 top-N 详情回填：搜索级三缺口一次补齐（探针实证）。

        web_v2/fetch_post_detail（GET，params: id + is_get_long_text=true，
        $0.001/帖）的 data 即扁平 mblog，一次调用同时给出：
        - 真互动数 reposts/comments/attitudes_count——搜索级 interaction 三键
          恒 0 的唯一真值来源（字符串/整数两种形态实测都见过 → _safe_int
          归一；>现值才写，防旧详情覆盖新值）
        - 带年份 created_at（英文全格式 "Tue Sep 08 17:22:04 +0800 2026"，
          _parse_datetime 现成分支）——搜索级 "MM月DD日 HH:MM" 无年份
        - 长文全文 text_raw（isLongText 时搜索级 content 是截断预览，探针
          实测 167 vs 297 字；更长才替换的护栏，处理字段同为 content）

        非 weibo 帖跳过；按 published_at 新→旧取 top-limit（默认
        _DETAIL_POST_LIMIT）。单帖失败 log warning 继续（不炸整批）；
        TikHubAuthError 直抛（账户级错误继续抓只会白烧重试，计费护栏同款）。
        """
        n = self._detail_post_limit if limit is None else limit
        if n <= 0:
            return posts
        candidates = sorted(
            (p for p in posts if p.get("platform") == platforms.WEIBO),
            key=lambda p: p.get("published_at") or "", reverse=True,
        )[:n]
        for post in candidates:
            mid = str(post.get("weibo_id") or "") or _path_tail(post.get("url") or "")
            if not mid:
                continue
            try:
                data = await self._client.get(
                    "weibo.fetch_post_detail",
                    params={"id": mid, "is_get_long_text": "true"})
            except TikHubAuthError:
                raise
            except Exception as e:
                logger.warning("TikHub weibo 详情回填失败 %s: %s", mid, e)
                continue
            mb = data or {}
            for key, field in (("likes", "attitudes_count"),
                               ("shares", "reposts_count"),
                               ("comments", "comments_count")):
                val = _safe_int(mb.get(field))
                if val > _safe_int(post.get(key)):
                    post[key] = val
            dt = _parse_datetime(mb.get("created_at"))
            if dt:
                post["published_at"] = dt  # 带年份真值覆盖无年份的搜索级解析
            if mb.get("isLongText"):
                full = (mb.get("text_raw")
                        or (mb.get("longText") or {}).get("content") or "")
                if len(full) > len(post.get("content") or ""):
                    post["content"] = full
        return posts

    async def _fetch_weibo_comments(self, post: dict) -> list[dict]:
        """微博评论（web_v2，m.weibo.cn 原生结构）。

        契约（weibo_comments.json）：data.data[] 每条 created_at 英文全格式带年、
        text_raw 纯文本优先（官方契约更正）、text 为 HTML 版兜底剥标签、
        user.screen_name、点赞字段实测是 like_counts
        （like_count 恒 None）、source "来自 广东" 是 IP 属地；data.max_id=0 末页；
        data.total_number 是帖评论总数——搜索互动全 0 的唯一真实数据源，回填
        post["comments"]（>现值才写，防止旧数据回退）。
        """
        mid = str(post.get("weibo_id") or "") or _path_tail(post["url"])
        out: list[dict] = []
        max_id = ""
        for _page in range(comment_max_pages()):
            params: dict[str, Any] = {"id": mid, "count": 20}
            if max_id:
                params["max_id"] = max_id  # 首页不带
            data = await self._client.get("weibo.fetch_post_comments", params=params)
            data = data or {}
            for c in data.get("data") or []:
                if c is None:
                    continue
                # text_raw 纯文本优先（官方契约更正），缺失兜底剥 text 的 HTML
                content = c.get("text_raw") or _strip_html(c.get("text") or "")
                if self._drop_at(content):
                    continue
                user = c.get("user") or {}
                comment = _make_comment(
                    content=content,
                    author=user.get("screen_name") or user.get("nickname") or "",
                    likes=(c.get("like_count") if c.get("like_count") is not None
                           else c.get("like_counts")),
                    platform=platforms.WEIBO,
                    post_url=post["url"],
                    post_note_id=mid,
                    published_at=c.get("created_at"),
                )
                m = _WEIBO_IP_RE.search(str(c.get("source") or ""))
                comment["ip_region"] = m.group(1).strip() if m else ""
                comment["comment_cid"] = str(c.get("id") or c.get("rootidstr") or "")
                out.append(comment)
            total = _safe_int(data.get("total_number"))
            if total > _safe_int(post.get("comments")):
                post["comments"] = total
            max_id = str(data.get("max_id") or "")
            if not max_id or max_id == "0":  # 0 = 末页（int/str 两种都见过）
                break
        return out

    # ── 小红书 ───────────────────────────────────────────────────

    async def _search_xhs(
        self, keyword: str, window_days: int = 7, mode: str = "incremental",
    ) -> tuple[list[dict], list[dict]]:
        """笔记搜索（app_v2）：双层信封 + 翻页凭证回传。

        契约（xhs_search_p1.json）：outer code==200 后 data.code==0/success
        才是真负载；翻页凭证 search_id / search_session_id 在 data 层（与
        data.data.items 同级），首页省略、翻页回传上一页响应的值。
        """
        max_pages = _search_max_pages("xiaohongshu", mode)
        posts: list[dict] = []
        seen: set[str] = set()
        search_id = ""
        session_id = ""
        for page in range(1, max_pages + 1):
            params: dict[str, Any] = {
                "keyword": keyword, "page": page,
                "sort_type": "general", "note_type": "不限",
                "time_filter": _xhs_time_filter(window_days),
            }
            if search_id and session_id:
                params["search_id"] = search_id
                params["search_session_id"] = session_id
            try:
                data = await self._client.get("xiaohongshu.search_notes", params=params)
            except TikHubAuthError:
                raise
            except Exception as e:
                if not posts:
                    raise
                logger.warning("TikHub xhs 搜索第 %d 页失败，保留已采 %d 帖: %s",
                               page, len(posts), e)
                break
            data = data or {}
            if not (_safe_int(data.get("code"), default=-1) == 0
                    or _truthy(data.get("success"))):
                if not posts:
                    raise TikHubError(
                        f"TikHub xhs 搜索内层失败 code={data.get('code')}")
                logger.warning("TikHub xhs 搜索第 %d 页内层失败，保留已采 %d 帖",
                               page, len(posts))
                break
            items = ((data.get("data") or {}).get("items")) or []
            if not items:
                break
            for it in items:
                n = (it or {}).get("note") or {}
                nid = str(n.get("id") or n.get("note_id") or "")  # 实测键名是 id
                if not nid or nid in seen:
                    continue
                seen.add(nid)
                posts.append(self._xhs_note_post(n, nid))
            search_id = str(data.get("search_id") or "")
            session_id = str(data.get("search_session_id") or "")
        comments = await self._collect_comments_for_posts(
            posts, self._fetch_xhs_comments, window_days=window_days)
        return posts, comments

    @staticmethod
    def _xhs_note_post(n: dict, nid: str) -> dict:
        """搜索 item.note → 标准帖（URL 惯例与 OneAPI 一致：xsec_token 进 query）。"""
        xsec = n.get("xsec_token") or ""
        url = f"https://www.xiaohongshu.com/explore/{nid}"
        if xsec:
            # xsec_token 是详情抓取凭证，必须入库 —— RawPost 无独立列，靠 URL query 持久化
            url = f"{url}?xsec_token={xsec}"
        post = _tikhub_post(
            title=n.get("title") or "",  # 空串时 _make_post 用 desc 兜底
            content=n.get("desc") or "",
            author=(n.get("user") or {}).get("nickname") or "",
            url=url,
            likes=n.get("liked_count"),
            comments_count=n.get("comments_count"),
            shares=n.get("shared_count"),
            platform=platforms.XIAOHONGSHU,
            published_at=n.get("timestamp"),  # Unix 秒
        )
        if xsec:
            post["xsec_token"] = xsec
        post["collected"] = _safe_int(n.get("collected_count"))
        return post

    async def _fetch_xhs_comments(self, post: dict) -> list[dict]:
        """笔记评论（app_v2 get_note_comments）。

        契约（xhs_comments.json）：双层信封（data.code==0/success）；
        data.data.comments[]（置顶槽位可能为 null 条目，直接跳过）；
        cursor 是 JSON 字符串对象（{contextId, cursor=末条id, index, pageArea}）
        下页整串原样回传 + index+1；ip_location 英文省名 → normalize 归一中文。
        """
        nid = _path_tail(post["url"])
        out: list[dict] = []
        cursor = ""
        index = 0
        for _page in range(comment_max_pages()):
            params: dict[str, Any] = {
                "note_id": nid, "share_text": "", "cursor": cursor, "index": index,
                "pageArea": "UNFOLDED", "sort_strategy": "latest_v2",
            }
            data = await self._client.get("xiaohongshu.get_note_comments", params=params) or {}
            if not (_safe_int(data.get("code"), default=-1) == 0
                    or _truthy(data.get("success"))):
                raise TikHubError(f"TikHub xhs 评论内层失败 code={data.get('code')}")
            payload = data.get("data") or {}
            for c in payload.get("comments") or []:
                if c is None:  # 置顶评论槽位为 null
                    continue
                if self._drop_at(c.get("content")):
                    continue
                comment = _make_comment(
                    content=c.get("content") or "",
                    author=(c.get("user") or {}).get("nickname") or "",
                    likes=c.get("like_count"),
                    platform=platforms.XIAOHONGSHU,
                    post_url=post["url"],
                    post_note_id=nid,
                    published_at=c.get("time"),  # Unix 秒
                )
                comment["ip_label"] = normalize_ip_location(c.get("ip_location"))
                comment["reply_count"] = _safe_int(c.get("sub_comment_count"))
                comment["comment_cid"] = str(c.get("id") or "")  # 评论去重键
                out.append(comment)
            if not _truthy(payload.get("has_more")):
                break
            cursor = payload.get("cursor") or ""  # JSON 字符串对象，整串回传
            index += 1
        return out

    # ── 快手 ─────────────────────────────────────────────────────

    async def _search_kuaishou(
        self, keyword: str, window_days: int = 7, mode: str = "incremental",
    ) -> tuple[list[dict], list[dict]]:
        """综合搜索（app search_comprehensive）：结构与 OneAPI v3 同构。

        翻页三重停止条件（推荐流 overlap 大，OneAPI v3 实测同款）：
        1. pcursor 空 / "no_more" / 与上页相同（死循环保险丝；注意样本
           pcursor 是 int 1，str 化后回传）
        2. 本页 photo_id 全重复（无新增）
        3. 新增率 < 50%（重叠率过高 → 收益崩塌，防空转烧钱）
        itemType=9 广告卡无 photo_id 等字段，取键即跳过。
        """
        # 停采平台不接线（Step6 裁决）：归档路径行为零变化，env 常量原样
        max_pages = _SEARCH_PAGES_INITIAL if mode == "initial" else _SEARCH_PAGES_INCREMENTAL
        posts: list[dict] = []
        seen: set[str] = set()
        pcursor = ""
        for _page in range(max_pages):
            params: dict[str, Any] = {
                "keyword": keyword, "sort_type": "all",
                "publish_time": _ks_publish_time(window_days),
            }
            if pcursor:
                params["pcursor"] = pcursor  # 首页不带
            try:
                data = await self._client.get("kuaishou.search_comprehensive", params=params)
            except TikHubAuthError:
                raise
            except Exception as e:
                if not posts:
                    raise
                logger.warning("TikHub kuaishou 搜索翻页失败，保留已采 %d 帖: %s",
                               len(posts), e)
                break
            data = data or {}
            feeds = [it.get("feed") or {} for it in data.get("mixFeeds") or []]
            new_count = 0
            for f in feeds:
                pid = str(f.get("photo_id") or "")
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                new_count += 1
                posts.append(self._kuaishou_post(f, pid))
            next_cursor = str(data.get("pcursor") or "")
            if not feeds or not next_cursor or next_cursor in ("no_more", pcursor):
                break
            if new_count * 2 < len(feeds):
                break  # 重叠率 ≥ 50%，停止翻页（本页新帖已并入）
            pcursor = next_cursor
        comments = await self._collect_comments_for_posts(
            posts, self._fetch_kuaishou_comments, window_days=window_days)
        return posts, comments

    @staticmethod
    def _kuaishou_post(f: dict, pid: str) -> dict:
        """mixFeeds[].feed → 标准帖（与 OneAPI v3 同构）。"""
        caption = f.get("caption") or ""
        post = _tikhub_post(
            title=caption[:80],
            content=caption,
            author=f.get("user_name") or "",
            url=f"https://www.kuaishou.com/short-video/{pid}",  # 标准永久链
            likes=f.get("like_count"),
            comments_count=f.get("comment_count"),
            shares=f.get("share_count"),
            platform=platforms.KUAISHOU,
            published_at=f.get("timestamp"),  # Unix 毫秒，_parse_datetime 自动 ÷1000
        )
        post["photo_id"] = pid            # 评论回链/批量详情都用它
        post["view_count"] = _safe_int(f.get("view_count"))
        post["collected"] = _safe_int(f.get("collect_count"))
        post["forward_count"] = _safe_int(f.get("forward_count"))
        return post

    async def _fetch_kuaishou_comments(self, post: dict) -> list[dict]:
        """快手评论（app fetch_video_comment）：字段与 OneAPI 同名同构。

        契约（kuaishou_comments.json）：rootComments[] 的 likedCount（camelCase
        无 d）/ authorArea（中文属地直用）/ subCommentCount；下一页 pcursor 在
        data.pcursor 层，"no_more"/空即止。
        """
        pid = str(post.get("photo_id") or "") or _path_tail(post["url"])
        out: list[dict] = []
        pcursor = ""
        for _page in range(comment_max_pages()):
            params: dict[str, Any] = {"photo_id": pid}
            if pcursor:
                params["pcursor"] = pcursor  # 首页不带
            data = await self._client.get("kuaishou.fetch_video_comment", params=params) or {}
            for c in data.get("rootComments") or []:
                if c is None or self._drop_at(c.get("content")):
                    continue
                comment = _make_comment(
                    content=c.get("content") or "",
                    author=c.get("author_name") or "",
                    likes=c.get("likedCount"),
                    platform=platforms.KUAISHOU,
                    post_url=post["url"],
                    post_note_id=str(c.get("photo_id") or pid),
                    published_at=c.get("timestamp"),  # 毫秒
                )
                comment["comment_id"] = str(c.get("comment_id") or "")
                comment["ip_label"] = c.get("authorArea") or ""  # 中文属地直用
                comment["reply_count"] = _safe_int(c.get("subCommentCount"))
                out.append(comment)
            next_cursor = str(data.get("pcursor") or "")
            if not next_cursor or next_cursor in ("no_more", pcursor):
                break
            pcursor = next_cursor
        return out

    # ── 抖音（搜索备胎 + 评论 + 统计）────────────────────────────

    async def _search_douyin(
        self, keyword: str, window_days: int = 7, mode: str = "incremental",
    ) -> tuple[list[dict], list[dict]]:
        """搜索 v1（search 命名空间，唯一 POST 端点）：抖音搜索主路径
        （2026-09-27 OneAPI 退役后无备胎），$0.01/页。

        契约（douyin_search_v1_p1.json + 2026-09-27 翻页探针）：视频在
        data.data[].aweme_info——type=1 才是视频卡（type=6 等无 aweme_info
        直接跳过），顶层 data.aweme_list 是空壳恒 0；statistics 全 0 →
        搜索后必须批量统计回填真值（digg/play 真实，comment/share 实测
        可为 None）；翻页三件套 has_more + cursor（int 递增）+
        search_id=上页 log_pb.impr_id——探针实证：缺 search_id 时第 2 页
        4 连 400 确定性失败（旧"瞬时故障重试即好"结论只对了一半：
        重试救不了缺参数，但第 1 页偶发 400 确是瞬时故障）。

        评论选帖用 rank_by_time：搜索级互动恒 0、stats 回填又不保证
        comment_count（样本三帖全 None）→ comments>0 过滤会把所有帖饿死，
        同微博互动全 0 的 P0-2 先例，改按时间新→旧选帖。
        """
        max_pages = _search_max_pages("douyin", mode)
        posts: list[dict] = []
        seen: set[str] = set()
        cursor = 0
        search_id = ""   # 翻页凭证：上页 log_pb.impr_id（首页空串被 client 过滤不发送）
        for _page in range(max_pages):
            try:
                data = await self._client.post("douyin.search", params={
                    "keyword": keyword, "cursor": cursor,
                    "sort_type": "2",  # 最新发布（与 OneAPI 同款，增量最友好）
                    "publish_time": _dy_publish_time(window_days),
                    "search_id": search_id,
                })
            except TikHubAuthError:
                raise
            except Exception as e:
                if not posts:
                    raise  # 首页即失败：如实上抛
                logger.warning("TikHub douyin 搜索第 %d 页失败，保留已采 %d 帖: %s",
                               _page + 1, len(posts), e)
                break
            data = data or {}
            items = data.get("data") or []
            new_count = 0
            for it in items:
                a = (it or {}).get("aweme_info") or {}
                vid = str(a.get("aweme_id") or "")
                if not vid or vid in seen:
                    continue
                seen.add(vid)
                new_count += 1
                posts.append(self._douyin_post(a, vid))
            next_search_id = str(((data.get("log_pb") or {}).get("impr_id")) or "")
            if not _truthy(data.get("has_more")):
                break
            next_cursor = _safe_int(data.get("cursor"), default=-1)
            if next_cursor < 0 or next_cursor == cursor or new_count == 0:
                break  # 末页 / 游标不前进（死循环保险丝）/ 本页全重复
            if not next_search_id:
                break  # 无翻页凭证：硬请求第 2 页必 400（探针 D1），到此为止
            cursor = next_cursor
            search_id = next_search_id
        await self._enrich_douyin_stats(posts)
        comments = await self._collect_comments_for_posts(
            posts, self._fetch_douyin_comments, window_days=window_days,
            rank_by_time=True)
        return posts, comments

    @staticmethod
    def _douyin_post(a: dict, vid: str) -> dict:
        """搜索卡 aweme_info → 标准帖（URL 与 OneAPI 惯例一致，评论回链吃尾段）。"""
        desc = a.get("desc") or ""
        st = a.get("statistics") or {}
        post = _tikhub_post(
            title=desc[:80],
            content=desc,
            author=(a.get("author") or {}).get("nickname") or "",
            url=f"https://www.douyin.com/video/{vid}",
            likes=st.get("digg_count"),        # 搜索级恒 0，_enrich_douyin_stats 回填真值
            comments_count=st.get("comment_count"),
            shares=st.get("share_count"),
            platform=platforms.DOUYIN,
            published_at=a.get("create_time"),  # Unix 秒
        )
        post["ip_label"] = a.get("ip_attribution") or ""  # 发帖属地（中文直用）
        return post

    async def _enrich_douyin_stats(self, posts: list[dict]) -> None:
        """批量统计回填：搜索卡 statistics 恒 0 的真值来源（$0.025/批 ≤20 帖）。

        实测 play_count/digg_count 真实，comment/share/collect_count 可为
        None（样本三帖全 None，上游按热度选择性回填）→ _safe_int 缺省 0、
        >现值才写防回退。失败不炸搜索：帖照常入库，只是互动数为 0
        （同 OneAPI 空窗语义，热度以详情/评论端点为准）。
        """
        vids = [_path_tail(p.get("url") or "")
                for p in posts if p.get("platform") == platforms.DOUYIN]
        if not vids:
            return
        try:
            stats = await self._client.fetch_douyin_play_stats(vids)
        except TikHubAuthError:
            raise
        except Exception as e:
            logger.warning("TikHub douyin 统计回填失败（%d 帖互动数留 0）: %s",
                           len(vids), e)
            return
        for p in posts:
            if p.get("platform") != platforms.DOUYIN:
                continue
            st = stats.get(_path_tail(p.get("url") or ""))
            if not st:
                continue
            for key, field in (("likes", "digg_count"),
                               ("comments", "comment_count"),
                               ("shares", "share_count")):
                val = _safe_int(st.get(field))
                if val > _safe_int(p.get(key)):
                    p[key] = val
            play = _safe_int(st.get("play_count"))
            if play > _safe_int(p.get("view_count")):
                p["view_count"] = play
            collected = _safe_int(st.get("collect_count"))
            if collected:
                p["collected"] = collected

    async def _fetch_douyin_comments(self, post: dict) -> list[dict]:
        """抖音评论（app_v3）：URL 提 aweme_id，cursor int 递增 20。

        契约（douyin_comments.json）：data.comments[] 的 cid/text/create_time
        （Unix 秒）/digg_count/ip_label（中文直用）/user.nickname；
        翻页 has_more（int 0/1）+ data.cursor；data.total 是帖评论总数——
        搜索级 statistics 恒 0、批量统计 comment_count 实测可为 None，
        这里是 dy 帖 comments 计数的可靠来源（>现值才写，同微博 total_number）。
        200-空防御（官方文档）：响应无评论但带 data.filter_list = 帖被可见性
        过滤，log info 归因后终止翻页（不重试不炸）。
        """
        vid = _path_tail(post["url"])
        out: list[dict] = []
        cursor = 0
        for _page in range(comment_max_pages()):
            data = await self._client.get("douyin.fetch_video_comments", params={
                "aweme_id": vid, "cursor": cursor, "count": 20,
            }) or {}
            comments = data.get("comments") or []
            if not comments and data.get("filter_list"):
                # 官方文档 filter_list 映射：8=版权问题/已删除、5=私密、
                # 10=部分可见。无实测样本，按文档防御性 .get 链。
                first = (data.get("filter_list") or [{}])[0] or {}
                logger.info(
                    "TikHub douyin %s 无评论（filter_list 过滤，8=版权/已删 "
                    "5=私密 10=部分可见）: reason=%s filter_code=%s",
                    vid, first.get("reason"), first.get("filter_code"))
                break
            for c in comments:
                if c is None or self._drop_at(c.get("text")):
                    continue
                comment = _make_comment(
                    content=c.get("text") or "",
                    author=(c.get("user") or {}).get("nickname") or "",
                    likes=c.get("digg_count"),
                    platform=platforms.DOUYIN,
                    post_url=post["url"],
                    post_note_id=vid,
                    published_at=c.get("create_time"),  # Unix 秒
                )
                comment["ip_label"] = c.get("ip_label") or ""
                comment["reply_count"] = _safe_int(c.get("reply_comment_total"))
                comment["comment_cid"] = str(c.get("cid") or "")  # 评论去重键
                out.append(comment)
            total = _safe_int(data.get("total"))
            if total > _safe_int(post.get("comments")):
                post["comments"] = total
            if not _truthy(data.get("has_more")):
                break
            cursor = _safe_int(data.get("cursor"), default=cursor + 20)
        return out
