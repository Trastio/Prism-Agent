"""多引擎搜索层 — Tavily（优先）+ DuckDuckGo（免费保底）"""
from __future__ import annotations
import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

def _get_tavily_key(env_override: str = "") -> str:
    if env_override and env_override.startswith("tvly"):
        return env_override
    env_val = os.environ.get("TAVILY_API_KEY", "")
    if env_val and env_val.startswith("tvly"):
        return env_val
    return TAVILY_API_KEY


@dataclass
class SearchResult:
    title: str
    url: str
    description: str = ""
    raw_content: Optional[str] = None
    source: str = ""


class SearchProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def auto_detect_order(self) -> int:
        return 100

    @abstractmethod
    async def search(self, query: str, num_results: int = 5,
                     lang: str = "zh", country: str = "cn") -> list[SearchResult]: ...

    @property
    def requires_key(self) -> bool:
        return False

    def is_configured(self) -> bool:
        return True


class TavilyProvider(SearchProvider):
    name = "tavily"

    def __init__(self, api_key: str = ""):
        self._api_key = _get_tavily_key(api_key or os.environ.get("TAVILY_API_KEY", ""))

    @property
    def auto_detect_order(self) -> int:
        return 10

    @property
    def requires_key(self) -> bool:
        return True

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def search(self, query: str, num_results: int = 5,
                     lang: str = "zh", country: str = "cn") -> list[SearchResult]:
        if not self._api_key:
            raise ValueError("TAVILY_API_KEY not configured")

        from tavily import AsyncTavilyClient
        client = AsyncTavilyClient(api_key=self._api_key)
        data = await client.search(query, max_results=num_results)

        results = []
        for r in (data.get("results") or [])[:num_results]:
            results.append(SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                description=r.get("content", ""),
                raw_content=r.get("raw_content", ""),
                source="tavily",
            ))
        return results


class DuckDuckGoProvider(SearchProvider):
    name = "duckduckgo"

    @property
    def auto_detect_order(self) -> int:
        return 100

    def is_configured(self) -> bool:
        try:
            from ddgs import DDGS  # noqa: F401
            return True
        except ImportError:
            try:
                from duckduckgo_search import DDGS  # noqa: F401
                return True
            except ImportError:
                return False

    async def search(self, query: str, num_results: int = 5,
                     lang: str = "zh", country: str = "cn") -> list[SearchResult]:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        loop = asyncio.get_event_loop()

        def _do_search():
            with DDGS() as ddgs:
                try:
                    return list(ddgs.text(query, max_results=num_results))
                except TypeError:
                    return list(ddgs.text(keywords=query, max_results=num_results,
                                          region=f"{country}-{lang}"))

        raw_results = await loop.run_in_executor(None, _do_search)

        results = []
        for r in raw_results:
            results.append(SearchResult(
                title=r.get("title", ""),
                url=r.get("href", r.get("link", "")),
                description=r.get("body", r.get("description", "")),
                source="duckduckgo",
            ))
        return results


class SearchEngine:
    """多引擎降级链：按 auto_detect_order 排序，有 Key 的优先，逐个尝试"""

    def __init__(self, providers: list[SearchProvider] | None = None,
                 max_retries: int = 2, retry_delay: float = 1.0):
        self._providers = providers or []
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def add_provider(self, provider: SearchProvider):
        self._providers.append(provider)

    def _get_candidates(self) -> list[SearchProvider]:
        configured = [p for p in self._providers if p.is_configured()]
        return sorted(configured, key=lambda p: p.auto_detect_order)

    async def search(self, query: str, num_results: int = 5) -> list[SearchResult]:
        candidates = self._get_candidates()
        if not candidates:
            raise RuntimeError("没有可用的搜索引擎")

        last_error = None
        for provider in candidates:
            for attempt in range(self.max_retries + 1):
                try:
                    results = await provider.search(query, num_results)
                    if results:
                        logger.info(f"Search via {provider.name}: {len(results)} results")
                        return results
                    break
                except Exception as e:
                    last_error = e
                    logger.warning(f"{provider.name} attempt {attempt + 1} failed: {e}")
                    if attempt < self.max_retries:
                        await asyncio.sleep(self.retry_delay * (attempt + 1))

        raise RuntimeError(f"所有搜索引擎均失败。最后错误: {last_error}")


_global_engine: SearchEngine | None = None


def get_search_engine() -> SearchEngine:
    global _global_engine
    if _global_engine is None:
        providers = []
        tavily_key = _get_tavily_key(os.environ.get("TAVILY_API_KEY", ""))
        if tavily_key:
            providers.append(TavilyProvider(tavily_key))
        providers.append(DuckDuckGoProvider())
        _global_engine = SearchEngine(providers)
    return _global_engine


def init_search_engine(tavily_api_key: str = "") -> SearchEngine:
    global _global_engine
    key = _get_tavily_key(tavily_api_key or os.environ.get("TAVILY_API_KEY", ""))
    providers = []
    if key:
        providers.append(TavilyProvider(key))
    providers.append(DuckDuckGoProvider())
    _global_engine = SearchEngine(providers)
    return _global_engine
