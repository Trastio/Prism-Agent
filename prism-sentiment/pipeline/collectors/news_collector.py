import asyncio
import hashlib
import json
import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

SECRETS_PATH = ".secrets"


def _load_api_keys() -> dict:
    if not os.path.exists(SECRETS_PATH):
        return {}
    with open(SECRETS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _dedup_key(item: dict) -> str:
    url = item.get("url", "")
    if url:
        return hashlib.md5(url.encode()).hexdigest()
    return hashlib.md5(item.get("title", "").encode()).hexdigest()


_CONFIG_URL_PATTERNS = re.compile(
    r"/config|/parameter|/dealer|pk\.16888\.com|/compare|/art\.html$|carsbooks\.com",
    re.IGNORECASE,
)


def _is_config_page(item: dict) -> bool:
    url = item.get("url", "")
    if _CONFIG_URL_PATTERNS.search(url):
        return True
    title = item.get("title", "")
    config_title_words = ["参数配置", "配置及参数", "车型对比"]
    if any(w in title for w in config_title_words):
        return True
    return False


class NewsCollector:
    def __init__(self):
        secrets = _load_api_keys()
        self._tavily_key = secrets.get("tavily", {}).get("api_key", "")
        self._bocha_key = secrets.get("bocha", {}).get("api_key", "")
        self._anspire_key = secrets.get("anspire", {}).get("api_key", "")

    async def search_all(self, keyword: str, start_date: str, end_date: str) -> list[dict]:
        results = await asyncio.gather(
            self.search_bocha(keyword, start_date, end_date),
            self.search_anspire(keyword, start_date, end_date),
            return_exceptions=True,
        )
        all_items, seen = [], set()
        for result in results:
            if isinstance(result, Exception):
                continue
            for item in result:
                if _is_config_page(item):
                    continue
                key = _dedup_key(item)
                if key not in seen:
                    seen.add(key)
                    all_items.append(item)
        all_items.sort(key=lambda x: x.get("published_at") or "", reverse=True)
        logger.info("search_all returned %d results for '%s'", len(all_items), keyword)
        return all_items

    async def search_tavily(self, keyword: str, start_date: str, end_date: str) -> list[dict]:
        if not self._tavily_key:
            return []
        try:
            logger.debug("Tavily request: keyword=%s, start=%s, end=%s", keyword, start_date, end_date)
            query = f"{keyword} 汽车测评"
            include_domains = [
                "autohome.com.cn", "dongchedi.com", "yiche.com",
                "zhihu.com", "toutiao.com", "pcauto.com.cn",
                "xcar.com.cn", "auto.sohu.com", "auto.qq.com",
                "36kr.com", "ithome.com", "bilibili.com",
            ]
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post("https://api.tavily.com/search", json={
                    "api_key": self._tavily_key, "query": query, "topic": "news",
                    "search_depth": "basic", "max_results": 30,
                    "start_date": start_date, "end_date": end_date,
                    "include_domains": include_domains,
                })
                resp.raise_for_status()
                data = resp.json()
            items = [{"title": r.get("title", ""), "content": r.get("content", ""),
                     "url": r.get("url", ""), "author": r.get("author", ""),
                     "published_at": r.get("published_date", ""),
                     "source": "tavily", "platform": "news"}
                    for r in data.get("results", [])]
            logger.info("Tavily returned %d results for '%s'", len(items), keyword)
            return items
        except Exception as e:
            logger.warning("Tavily search failed: %s", e)
            return []

    async def search_bocha(self, keyword: str, start_date: str, end_date: str) -> list[dict]:
        if not self._bocha_key:
            return []
        try:
            logger.debug("Bocha request: keyword=%s, start=%s, end=%s", keyword, start_date, end_date)
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post("https://api.bochaai.com/v1/web-search",
                    headers={"Authorization": f"Bearer {self._bocha_key}"},
                    json={"query": keyword, "freshness": f"{start_date}_{end_date}",
                          "summary": False, "count": 20})
                resp.raise_for_status()
                data = resp.json()
            items = [{"title": r.get("name", ""), "content": r.get("snippet", ""),
                     "url": r.get("url", ""), "author": "",
                     "published_at": r.get("dateLastCrawled", ""),
                     "source": "bocha", "platform": "news"}
                    for r in data.get("data", {}).get("webPages", {}).get("value", [])]
            logger.info("Bocha returned %d results for '%s'", len(items), keyword)
            return items
        except Exception as e:
            logger.warning("Bocha search failed: %s", e)
            return []

    async def search_anspire(self, keyword: str, start_date: str, end_date: str) -> list[dict]:
        if not self._anspire_key:
            return []
        try:
            logger.debug("Anspire request: keyword=%s, start=%s, end=%s", keyword, start_date, end_date)
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get("https://plugin.anspire.cn/api/ntsearch/search",
                    headers={"Authorization": f"Bearer {self._anspire_key}"},
                    params={"query": keyword, "limit": 20})
                resp.raise_for_status()
                data = resp.json()
            items = [{"title": r.get("title", ""), "content": r.get("content", ""),
                     "url": r.get("url", ""), "author": "",
                     "published_at": r.get("date", ""),
                     "source": "anspire", "platform": "news"}
                    for r in data.get("results", []) if r.get("url")]
            logger.info("Anspire returned %d results for '%s'", len(items), keyword)
            return items
        except Exception as e:
            logger.warning("Anspire search failed: %s", e)
            return []
