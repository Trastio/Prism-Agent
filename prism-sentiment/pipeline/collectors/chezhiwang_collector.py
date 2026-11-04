"""车质网（12365auto.com）投诉采集器 —— 质量投诉主阵地。

车质网是国内最大的汽车质量投诉平台，BBS 按车系分版块，每条帖子是一起
真实车主投诉（故障/缺陷/售后纠纷）。对缺陷监控价值最高：投诉帖天然就是
缺陷话题的种子数据，可直接进缺陷监控评论池。

接入方式（2026-09-27 调研定稿）：
- 无公开 API。BBS 走 aspx 后端，帖子列表页 server-rendered（UTF-8）。
- 列表 URL：https://bbs.12365auto.com/seriesforum/{seriesID}-{sort}-{page}-{filter}.shtml
  sort=1 按时间倒序；page 从 0 起（0=第1页）；filter=0 全部。
- 帖子 URL：https://bbs.12365auto.com/threadforum/{YYYYMMDD}/{id}.shtml
- 无需登录、无验证码、无 JS 渲染依赖（列表页 HTML 直出）。
- 详情页正文在 <div class="neirong"> 容器内（主楼正文）。

seriesID 映射：车质网用数字 seriesId 标识车系（见 brandsHaveSeries.js）。
本采集器内置项目在监车辆映射，未命中时返回空（避免误采他车）。

入库语义：platform="chezhiwang"，source="chezhiwang"。投诉帖无点赞/转发
等社媒互动指标，likes/comments/shares 置 0；正文走 full_content。
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

BASE = "https://bbs.12365auto.com"
LIST_URL = f"{BASE}/seriesforum/{{sid}}-1-{{page}}-0.shtml"

# 车质网 seriesId 映射（权威源 brandsHaveSeries.js，2026-09-28 全量补齐）。
# 仅收录项目在监车型；新增车型跑 scripts/find_chezhiwang_seriesids.py
# 查得（含 BBS 探活核 title，防同名车系错配）后在此补一行。
# ⚠ Model Y 原 3511 是"斯达泰克Model Y"（同名错配，BBS title 实证），
# 已更正为特斯拉中国 Model Y=3003。
# 银河A7 车质网拆 EM/EV 两车系，取投诉量大的主销 EM 版（EV=4512 备查）。
SERIES_ID_MAP: dict[str, int] = {
    "星愿": 4070,
    "MONA M03": 4025,
    "MONA L03": 4555,
    "SU7": 3902,
    "Model Y": 3003,
    # ── 2026-09-28 T2.5 全量补齐（23 车在监全覆盖）──────────────────
    "MG4X": 4527,
    "元PLUS": 3234,
    "元UP": 3898,
    "华境s": 4505,
    "海狮06": 4266,
    "特斯拉model 3": 2554,
    "铂智3X": 4156,
    "银河A7": 4283,
    "银河E5": 3997,
    "银河M9": 4338,
    "银河TT": 4607,
    "零跑A10": 4429,
    "零跑B01": 4267,
    "零跑B10": 4187,
    "零跑D19": 4449,
    "风云A9": 4568,
    "风云T11": 4376,
    "风云T7": 4590,
    "风云T9L": 4446,
}

DEFAULT_TIMEOUT = 20
DEFAULT_MAX_PAGES = 3          # 每车系最多翻 3 页（约 30-45 帖，足够缺陷监控）
INTER_PAGE_DELAY = 1           # 翻页礼貌位（秒）

# 帖子链接正则：threadforum/YYYYMMDD/id.shtml
_POST_RE = re.compile(
    r"""<a[^>]+href=["']([^"']+threadforum/\d{8}/\d+\.shtml(?:#[^"']*)?)["'][^>]*>([^<]+)</a>""",
    re.IGNORECASE,
)
# 帖子正文容器：<div class="neirong" id="rcontent_XXX"> ... </div>
# 这是主楼正文 div，跨新旧版页面稳定（2026-09-27 调研验证）。
_CONTENT_RE = re.compile(
    r'<div\s+class="neirong"[^>]*>(.*?)</div>\s*<div[^>]*class=[\'"]nr_r_b',
    re.S,
)


def resolve_series_id(vehicle_name: str) -> int | None:
    """车型名 → 车质网 seriesId。未命中返回 None。

    精确匹配优先；否则尝试包含匹配（"小鹏MONA M03" 含 "MONA M03"）。
    """
    if not vehicle_name:
        return None
    if vehicle_name in SERIES_ID_MAP:
        return SERIES_ID_MAP[vehicle_name]
    for key, sid in SERIES_ID_MAP.items():
        if key in vehicle_name:
            return sid
    return None


class ChezhiwangCollector:
    """车质网投诉帖采集器。按车系 seriesId 抓 BBS 列表 + 详情正文。"""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT, max_pages: int = DEFAULT_MAX_PAGES):
        self._timeout = timeout
        self._max_pages = max_pages

    async def search(
        self, vehicle_name: str, start_date: str, end_date: str,
        max_pages: int | None = None,
    ) -> list[dict]:
        """按车型采集投诉帖。

        Args:
            vehicle_name: 车型名（用于解析 seriesId）。
            start_date / end_date: ISO 日期串（YYYY-MM-DD），用于过滤发表时间
                早于 start_date 的老帖（车质网帖子跨度大，避免拉入数年前旧帖）。
            max_pages: 翻页深度覆盖。None 用实例默认（DEFAULT_MAX_PAGES=3）；
                首次接入传 5 拉宽历史回溯，增量传 3 够用（2026-09-28 T2 独立宽窗）。

        Returns:
            帖子 dict 列表，字段与 NewsCollector 对齐：
            title / content / url / author / published_at / source / platform。
        """
        sid = resolve_series_id(vehicle_name)
        if sid is None:
            logger.info("车质网未配置 '%s' 的 seriesId，跳过", vehicle_name)
            return []

        page_limit = max_pages if max_pages is not None else self._max_pages
        floor = self._parse_date(start_date)
        posts: list[dict] = []
        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers={"User-Agent": _UA},
            follow_redirects=True,
        ) as client:
            for page in range(page_limit):
                url = LIST_URL.format(sid=sid, page=page)
                try:
                    items = await self._fetch_list_page(client, url, floor)
                except Exception as e:
                    logger.warning("车质网列表页 %s 抓取失败: %s", url, e)
                    break
                if not items:
                    break  # 空页=已到末尾
                posts.extend(items)
                # 列表按时间倒序，末帖仍在窗口内才翻下一页（避免无效翻页）
                last_date = items[-1].get("_raw_date")
                if floor and last_date and last_date < floor:
                    break
                if page < page_limit - 1:
                    await asyncio.sleep(INTER_PAGE_DELAY)

        # 去重（同一帖可能跨页出现）
        seen: set[str] = set()
        unique: list[dict] = []
        for p in posts:
            u = p.get("url", "")
            if u and u in seen:
                continue
            seen.add(u)
            unique.append(p)

        # 抓详情正文（列表页只有标题，正文需进详情页）。
        # 并发限速：车质网 BBS 对并发敏感（20 并发实测 16 失败），semaphore=3
        # + 页间 0.3s 间隔保证稳定性（投诉帖量小，吞吐不是瓶颈）。
        if unique:
            sem = asyncio.Semaphore(3)
            async with httpx.AsyncClient(
                timeout=self._timeout, headers={"User-Agent": _UA}, follow_redirects=True,
            ) as client:
                async def _limited(p):
                    async with sem:
                        result = await self._fetch_detail(client, p)
                        await asyncio.sleep(0.3)
                        return result
                detail_tasks = [_limited(p) for p in unique]
                results = await asyncio.gather(*detail_tasks, return_exceptions=True)
                for p, r in zip(unique, results):
                    if isinstance(r, Exception):
                        logger.debug("车质网详情抓取失败 %s: %s", p.get("url"), r)
                        continue
                    if r:
                        p["full_content"] = r
                        # 详情页标题更准（列表页标题已够用，不覆盖）

        # 清理内部字段
        for p in unique:
            p.pop("_raw_date", None)

        logger.info("车质网 '%s'(sid=%s) 采集 %d 帖", vehicle_name, sid, len(unique))
        return unique

    async def _fetch_list_page(
        self, client: httpx.AsyncClient, url: str, floor: datetime | None,
    ) -> list[dict]:
        resp = await client.get(url)
        resp.raise_for_status()
        # 列表页是 UTF-8（与主站 /parts 的 GBK 不同）
        text = resp.content.decode("utf-8", errors="replace")
        items: list[dict] = []
        for match in _POST_RE.finditer(text):
            raw_url = match.group(1)
            title = match.group(2).strip()
            if not title or len(title) < 4:
                continue
            # 规范化 URL（去 #f=s 锚点、补协议）
            clean_url = raw_url.split("#")[0]
            if clean_url.startswith("//"):
                clean_url = "https:" + clean_url
            elif clean_url.startswith("/"):
                clean_url = BASE + clean_url
            # 从 URL 提取日期（threadforum/YYYYMMDD/id.shtml）
            date_part = re.search(r"threadforum/(\d{8})/", clean_url)
            published_at = ""
            raw_date = None
            if date_part:
                d = date_part.group(1)
                published_at = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                raw_date = self._parse_date(published_at)
            # 窗口过滤（floor 之前的老帖跳过）
            if floor and raw_date and raw_date < floor:
                continue
            items.append({
                "title": title,
                "content": title,  # 列表页只有标题，详情正文后补
                "url": clean_url,
                "author": "",
                "published_at": published_at,
                "source": "chezhiwang",
                "platform": "chezhiwang",
                "_raw_date": raw_date,
            })
        return items

    async def _fetch_detail(self, client: httpx.AsyncClient, post: dict) -> str:
        url = post.get("url", "")
        if not url:
            return ""
        resp = await client.get(url)
        resp.raise_for_status()
        text = resp.content.decode("utf-8", errors="replace")
        # 提取正文：<div class="neirong"> 主楼正文容器
        m = _CONTENT_RE.search(text)
        if not m:
            return ""
        body = m.group(1)
        body = re.sub(r"<[^>]+>", " ", body)
        body = re.sub(r"\s+", " ", body).strip()
        return body[:5000] if body else ""

    @staticmethod
    def _parse_date(s: str) -> datetime | None:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s[:10])
        except (ValueError, TypeError):
            return None


_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
