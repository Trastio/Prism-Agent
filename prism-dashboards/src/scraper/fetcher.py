"""轻量级 HTTP 页面抓取器 — 纯 httpx，无 Playwright 依赖"""
import asyncio
import logging
import random

import httpx

logger = logging.getLogger(__name__)

_BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.autohome.com.cn/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class ReviewFetcher:
    """httpx 替代 Playwright 的页面抓取器，保持接口兼容"""

    BASE_URL = "https://k.autohome.com.cn"

    def __init__(self, headless: bool = True, min_delay: float = 0.3, max_delay: float = 0.8):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=_BASE_HEADERS,
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
            )
        return self._client

    def build_url(self, series_id: str, page: int = 1) -> str:
        if page == 1:
            return f"{self.BASE_URL}/{series_id}/"
        return f"{self.BASE_URL}/{series_id}/index_{page}.html"

    def random_delay(self) -> float:
        return random.uniform(self.min_delay, self.max_delay)

    async def fetch_page(self, url: str, retries: int = 3,
                         wait_selector: str = "", timeout: int = 30000) -> str:
        client = await self._get_client()
        last_error = None
        for attempt in range(retries):
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return resp.text
                logger.warning(f"Fetch {url} 返回 {resp.status_code}, 尝试 {attempt + 1}/{retries}")
            except httpx.HTTPError as e:
                last_error = e
                logger.warning(f"Fetch {url} 失败: {e}, 尝试 {attempt + 1}/{retries}")
            if attempt < retries - 1:
                await asyncio.sleep(1.0 * (attempt + 1))
        raise RuntimeError(f"Failed to fetch {url}: {last_error}")

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None


_shared_fetcher: ReviewFetcher | None = None
_fetcher_lock = asyncio.Lock()


def get_shared_fetcher() -> ReviewFetcher:
    global _shared_fetcher
    if _shared_fetcher is None:
        _shared_fetcher = ReviewFetcher()
    return _shared_fetcher


async def get_shared_fetcher_async() -> ReviewFetcher:
    global _shared_fetcher
    async with _fetcher_lock:
        if _shared_fetcher is None:
            _shared_fetcher = ReviewFetcher()
        return _shared_fetcher


async def close_shared_fetcher():
    global _shared_fetcher
    if _shared_fetcher:
        await _shared_fetcher.close()
        _shared_fetcher = None
