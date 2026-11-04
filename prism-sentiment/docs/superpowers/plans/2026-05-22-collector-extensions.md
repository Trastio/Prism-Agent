# Collector Extensions Implementation Plan

> **STATUS: DEFERRED** — Plan created but not executed. Only logging was partially applied. Anspire data source and toutiao/google index remain unimplemented. Revive when needed.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Anspire data source, toutiao/google index, and 3-level logging to all collectors and scheduler.

**Architecture:** Extend existing files in-place — add methods and logger instances without splitting files or changing import chains. Gopup collector gets a shared `_collect_index_sync` helper to deduplicate 4 near-identical index methods.

**Tech Stack:** Python 3.12, httpx, gopup, pytest, pytest-asyncio, logging

---

## File Structure

| File | Change |
|------|--------|
| `pipeline/collectors/news_collector.py` | Add `import logging`, `logger`, `_anspire_key` in init, `search_anspire()`, logging in all methods, `search_anspire` in `search_all` gather |
| `pipeline/collectors/gopup_collector.py` | Add `import logging`, `logger`, `_collect_index_sync()`, refactor baidu/weibo, add `collect_toutiao_index()`, `collect_google_index()` |
| `pipeline/scheduler.py` | Add `import logging`, `logger`, toutiao/google calls in `_run_collectors`, `_store_index_data` to `*data_sets` signature, logging |
| `tests/test_news_collector.py` | Add 4 tests for Anspire, update 3 existing tests for `_anspire_key` |
| `tests/test_gopup_collector.py` | **Create new** — 5 tests for `_collect_index_sync` + toutiao/google delegation |
| `tests/test_scheduler.py` | Add 1 test for `_store_index_data` with multiple sources |
| `.secrets` | Add `"anspire": {"api_key": ""}` |

---

### Task 1: news_collector — add logging + anspire key init

**Files:**
- Modify: `pipeline/collectors/news_collector.py`

This is a refactor — no new tests. Existing tests mock `__init__` so they won't notice the new `_anspire_key`.

- [ ] **Step 1: Add logging import and logger, add _anspire_key to init**

Replace lines 1-29 of `pipeline/collectors/news_collector.py` with:

```python
import asyncio
import hashlib
import json
import logging
import os

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


class NewsCollector:
    def __init__(self):
        secrets = _load_api_keys()
        self._tavily_key = secrets.get("tavily", {}).get("api_key", "")
        self._bocha_key = secrets.get("bocha", {}).get("api_key", "")
        self._anspire_key = secrets.get("anspire", {}).get("api_key", "")
```

Leave the rest of the file unchanged for now.

- [ ] **Step 2: Run existing tests to verify nothing breaks**

Run: `cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent && python -m pytest tests/test_news_collector.py -v`
Expected: All 7 existing tests PASS.

- [ ] **Step 3: Add logging to search_tavily**

Replace `search_tavily` method (lines 49-66) with:

```python
    async def search_tavily(self, keyword: str, start_date: str, end_date: str) -> list[dict]:
        if not self._tavily_key:
            return []
        try:
            logger.debug("Tavily request: keyword=%s, start=%s, end=%s", keyword, start_date, end_date)
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post("https://api.tavily.com/search", json={
                    "api_key": self._tavily_key, "query": keyword, "topic": "news",
                    "search_depth": "basic", "max_results": 20,
                    "start_date": start_date, "end_date": end_date,
                })
                resp.raise_for_status()
                data = resp.json()
            items = [{"title": r.get("title", ""), "content": r.get("content", ""),
                     "url": r.get("url", ""), "author": r.get("author", ""),
                     "published_at": r.get("published_date", ""),
                     "source": "tavily", "platform": "news"}
                    for r in data.get("results", [])]
            logger.debug("Tavily response: count=%d", len(items))
            logger.info("Tavily returned %d results for '%s'", len(items), keyword)
            return items
        except Exception as e:
            logger.warning("Tavily search failed: %s", e)
            return []
```

- [ ] **Step 4: Add logging to search_bocha**

Replace `search_bocha` method (lines 69-87) with:

```python
    async def search_bocha(self, keyword: str, start_date: str, end_date: str) -> list[dict]:
        if not self._bocha_key:
            return []
        try:
            logger.debug("Bocha request: keyword=%s, start=%s, end=%s", keyword, start_date, end_date)
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post("https://api.bocha.io/v1/web-search",
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
            logger.debug("Bocha response: count=%d", len(items))
            logger.info("Bocha returned %d results for '%s'", len(items), keyword)
            return items
        except Exception as e:
            logger.warning("Bocha search failed: %s", e)
            return []
```

- [ ] **Step 5: Run tests to verify nothing breaks**

Run: `cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent && python -m pytest tests/test_news_collector.py -v`
Expected: All 7 existing tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent
git add pipeline/collectors/news_collector.py
git commit -m "refactor: add logging + anspire key init to news_collector"
```

---

### Task 2: news_collector — search_anspire TDD

**Files:**
- Modify: `pipeline/collectors/news_collector.py`
- Modify: `tests/test_news_collector.py`

- [ ] **Step 1: Write failing test for search_anspire no key**

Append to `tests/test_news_collector.py`:

```python


async def test_search_anspire_no_key():
    from pipeline.collectors.news_collector import NewsCollector
    with patch.object(NewsCollector, "__init__", lambda self: None):
        c = NewsCollector()
        c._anspire_key = ""
        assert await c.search_anspire("海豹", "2026-01-01", "2026-05-01") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent && python -m pytest tests/test_news_collector.py::test_search_anspire_no_key -v`
Expected: FAIL — `AttributeError: 'NewsCollector' object has no attribute 'search_anspire'`

- [ ] **Step 3: Write failing test for search_anspire success**

Append to `tests/test_news_collector.py`:

```python


async def test_search_anspire_success():
    from pipeline.collectors.news_collector import NewsCollector
    with patch.object(NewsCollector, "__init__", lambda self: None):
        c = NewsCollector()
        c._anspire_key = "key"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"results": [
            {"title": "海豹新闻", "content": "内容", "url": "http://x.com",
             "published_at": "2026-05-01", "author": "test"},
        ]}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await c.search_anspire("海豹", "2026-01-01", "2026-05-01")
    assert len(result) == 1
    assert result[0]["source"] == "anspire"
    assert result[0]["platform"] == "news"
    assert result[0]["title"] == "海豹新闻"
```

- [ ] **Step 4: Write failing test for search_anspire API error**

Append to `tests/test_news_collector.py`:

```python


async def test_search_anspire_api_error():
    from pipeline.collectors.news_collector import NewsCollector
    with patch.object(NewsCollector, "__init__", lambda self: None):
        c = NewsCollector()
        c._anspire_key = "key"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.HTTPStatusError(
            "err", request=MagicMock(), response=MagicMock(status_code=500)))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await c.search_anspire("海豹", "2026-01-01", "2026-05-01")
    assert result == []
```

- [ ] **Step 5: Run all 3 new tests to verify they fail**

Run: `cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent && python -m pytest tests/test_news_collector.py -k "anspire" -v`
Expected: All 3 FAIL.

- [ ] **Step 6: Implement search_anspire**

Append to `pipeline/collectors/news_collector.py` (after `search_bocha`):

```python

    async def search_anspire(self, keyword: str, start_date: str, end_date: str) -> list[dict]:
        if not self._anspire_key:
            return []
        try:
            logger.debug("Anspire request: keyword=%s, start=%s, end=%s", keyword, start_date, end_date)
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post("https://api.anspire.ai/v1/news/search",
                    headers={"Authorization": f"Bearer {self._anspire_key}"},
                    json={"query": keyword, "start_date": start_date,
                          "end_date": end_date, "limit": 20})
                resp.raise_for_status()
                data = resp.json()
            items = [{"title": r.get("title", ""), "content": r.get("content", ""),
                     "url": r.get("url", ""), "author": r.get("author", ""),
                     "published_at": r.get("published_at", ""),
                     "source": "anspire", "platform": "news"}
                    for r in data.get("results", [])]
            logger.debug("Anspire response: count=%d", len(items))
            logger.info("Anspire returned %d results for '%s'", len(items), keyword)
            return items
        except Exception as e:
            logger.warning("Anspire search failed: %s", e)
            return []
```

- [ ] **Step 7: Run all news_collector tests to verify they pass**

Run: `cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent && python -m pytest tests/test_news_collector.py -v`
Expected: All 10 tests PASS (7 existing + 3 new).

- [ ] **Step 8: Commit**

```bash
cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent
git add pipeline/collectors/news_collector.py tests/test_news_collector.py
git commit -m "feat: add search_anspire to news_collector — TDD (3 tests)"
```

---

### Task 3: news_collector — search_all includes anspire TDD

**Files:**
- Modify: `pipeline/collectors/news_collector.py`
- Modify: `tests/test_news_collector.py`

- [ ] **Step 1: Write failing test for search_all including anspire dedup**

Append to `tests/test_news_collector.py`:

```python


async def test_search_all_includes_anspire():
    from pipeline.collectors.news_collector import NewsCollector
    with patch.object(NewsCollector, "__init__", lambda self: None):
        c = NewsCollector()
        c._tavily_key = ""
        c._bocha_key = ""
        c._anspire_key = "key"
        with patch.object(c, "search_tavily", return_value=[]):
            with patch.object(c, "search_bocha", return_value=[]):
                with patch.object(c, "search_anspire", return_value=[
                    {"title": "A", "url": "http://a.com", "published_at": "2026-05-01",
                     "source": "anspire", "platform": "news"},
                ]):
                    result = await c.search_all("海豹", "2026-01-01", "2026-05-01")
    assert len(result) == 1
    assert result[0]["source"] == "anspire"
```

- [ ] **Step 2: Run new test to verify it fails**

Run: `cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent && python -m pytest tests/test_news_collector.py::test_search_all_includes_anspire -v`
Expected: FAIL — search_all doesn't call search_anspire, so anspire results are missing.

- [ ] **Step 3: Update existing tests to add _anspire_key mock**

In `tests/test_news_collector.py`, update 3 existing `search_all` tests to add `c._anspire_key = ""`:

In `test_search_all_no_keys` (line 14), add after `c._bocha_key = ""`:
```python
        c._anspire_key = ""
```

In `test_search_all_dedup_by_url` (line 22), add after `c._bocha_key = ""`:
```python
        c._anspire_key = ""
```

In `test_search_all_sorted_by_date` (line 74), add after `c._bocha_key = ""`:
```python
        c._anspire_key = ""
```

- [ ] **Step 4: Update search_all to include search_anspire in gather**

In `pipeline/collectors/news_collector.py`, replace `search_all` method:

```python
    async def search_all(self, keyword: str, start_date: str, end_date: str) -> list[dict]:
        results = await asyncio.gather(
            self.search_tavily(keyword, start_date, end_date),
            self.search_bocha(keyword, start_date, end_date),
            self.search_anspire(keyword, start_date, end_date),
            return_exceptions=True,
        )
        all_items, seen = [], set()
        for result in results:
            if isinstance(result, Exception):
                continue
            for item in result:
                key = _dedup_key(item)
                if key not in seen:
                    seen.add(key)
                    all_items.append(item)
        all_items.sort(key=lambda x: x.get("published_at", ""), reverse=True)
        logger.info("search_all returned %d results for '%s'", len(all_items), keyword)
        return all_items
```

- [ ] **Step 5: Run all news_collector tests to verify they pass**

Run: `cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent && python -m pytest tests/test_news_collector.py -v`
Expected: All 11 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent
git add pipeline/collectors/news_collector.py tests/test_news_collector.py
git commit -m "feat: search_all includes anspire — TDD (1 test + 3 fixes)"
```

---

### Task 4: gopup_collector — _collect_index_sync refactor + logging

**Files:**
- Modify: `pipeline/collectors/gopup_collector.py`

This is a refactor. No new tests file yet — existing scheduler tests mock `_run_collectors` so they don't call gopup directly.

- [ ] **Step 1: Replace entire gopup_collector.py with refactored version**

```python
import asyncio
import logging
import sys
from typing import Callable

try:
    import gopup as gp
except ImportError:
    if "demjson" not in sys.modules:
        import importlib
        sys.modules["demjson"] = importlib.import_module("demjson3")
    import gopup as gp

import pandas as pd

from pipeline.collectors.cookie_manager import CookieManager

logger = logging.getLogger(__name__)


class GopupCollector:
    def __init__(self):
        self._cookie_mgr = CookieManager()

    def _ensure_cookie(self):
        cookie = self._cookie_mgr.get_baidu_cookie()
        if cookie:
            try:
                gp.cookie_baidu(cookie_str=cookie)
            except Exception:
                pass

    def _collect_index_sync(self, index_func: Callable, source_name: str,
                            keyword: str, start_date: str, end_date: str) -> list[dict]:
        try:
            logger.debug("%s_index request: keyword=%s, start=%s, end=%s",
                         source_name, keyword, start_date, end_date)
            df = index_func(word=keyword, start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                logger.info("%s_index returned 0 data points for '%s'", source_name, keyword)
                return []
            index_col = f"{source_name}_index"
            results = [{"date": str(row.get("date", "")), "keyword": keyword,
                        "index": int(row.get(index_col, 0)), "source": source_name}
                       for _, row in df.iterrows()]
            logger.debug("%s_index response: count=%d", source_name, len(results))
            logger.info("%s_index collected %d data points for '%s'",
                        source_name, len(results), keyword)
            return results
        except Exception as e:
            logger.warning("%s_index failed for '%s': %s", source_name, keyword, e)
            return []

    async def collect_baidu_index(self, keyword: str, start_date: str, end_date: str) -> list[dict]:
        self._ensure_cookie()
        return await asyncio.to_thread(
            self._collect_index_sync, gp.baidu_index, "baidu", keyword, start_date, end_date
        )

    async def collect_weibo_index(self, keyword: str, start_date: str, end_date: str) -> list[dict]:
        return await asyncio.to_thread(
            self._collect_index_sync, gp.weibo_index, "weibo", keyword, start_date, end_date
        )

    async def collect_toutiao_index(self, keyword: str, start_date: str, end_date: str) -> list[dict]:
        return await asyncio.to_thread(
            self._collect_index_sync, gp.toutiao_index, "toutiao", keyword, start_date, end_date
        )

    async def collect_google_index(self, keyword: str, start_date: str, end_date: str) -> list[dict]:
        return await asyncio.to_thread(
            self._collect_index_sync, gp.google_index, "google", keyword, start_date, end_date
        )
```

**Key differences from original:**
- `_baidu_sync` and `_weibo_sync` removed, replaced by `_collect_index_sync`
- All 4 index methods delegate to `_collect_index_sync` via `asyncio.to_thread`
- `collect_baidu_index` still calls `self._ensure_cookie()` before the thread
- Return dicts now include `"source"` field

- [ ] **Step 2: Run all tests to verify nothing breaks**

Run: `cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent && python -m pytest tests/ -v`
Expected: All 139 tests PASS.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent
git add pipeline/collectors/gopup_collector.py
git commit -m "refactor: gopup_collector — _collect_index_sync helper + logging + toutiao/google"
```

---

### Task 5: gopup_collector — toutiao/google TDD

**Files:**
- Create: `tests/test_gopup_collector.py`

- [ ] **Step 1: Write failing tests for _collect_index_sync and toutiao/google**

Create `tests/test_gopup_collector.py`:

```python
"""Tests: Gopup Collector — _collect_index_sync + toutiao/google delegation."""
import pytest
import pandas as pd
from unittest.mock import patch, AsyncMock

from pipeline.collectors.gopup_collector import GopupCollector


def _no_init(self):
    pass


def _make_df(index_name: str, dates: list[str], values: list[int]) -> pd.DataFrame:
    return pd.DataFrame({"date": dates, index_name: values})


def _raise(**kwargs):
    raise Exception("API down")


class TestCollectIndexSync:
    def test_success_returns_dicts_with_source(self):
        with patch.object(GopupCollector, "__init__", _no_init):
            c = GopupCollector()
            mock_df = _make_df("toutiao_index", ["2026-05-01", "2026-05-02"], [100, 200])
            result = c._collect_index_sync(lambda **kw: mock_df, "toutiao", "海豹", "2026-05-01", "2026-05-02")
        assert len(result) == 2
        assert result[0] == {"date": "2026-05-01", "keyword": "海豹", "index": 100, "source": "toutiao"}
        assert result[1] == {"date": "2026-05-02", "keyword": "海豹", "index": 200, "source": "toutiao"}

    def test_empty_df_returns_empty_list(self):
        with patch.object(GopupCollector, "__init__", _no_init):
            c = GopupCollector()
            result = c._collect_index_sync(lambda **kw: pd.DataFrame(), "toutiao", "海豹", "2026-05-01", "2026-05-02")
        assert result == []

    def test_exception_returns_empty_list(self):
        with patch.object(GopupCollector, "__init__", _no_init):
            c = GopupCollector()
            result = c._collect_index_sync(_raise, "toutiao", "海豹", "2026-05-01", "2026-05-02")
        assert result == []


class TestToutiaoGoogleDelegation:
    @pytest.mark.asyncio
    async def test_collect_toutiao_index_delegates(self):
        with patch.object(GopupCollector, "__init__", _no_init):
            c = GopupCollector()
            expected = [{"date": "2026-05-01", "keyword": "海豹", "index": 100, "source": "toutiao"}]
            with patch.object(c, "_collect_index_sync", return_value=expected) as mock_sync:
                result = await c.collect_toutiao_index("海豹", "2026-05-01", "2026-05-02")
                mock_sync.assert_called_once()
        assert result == expected

    @pytest.mark.asyncio
    async def test_collect_google_index_delegates(self):
        with patch.object(GopupCollector, "__init__", _no_init):
            c = GopupCollector()
            expected = [{"date": "2026-05-01", "keyword": "海豹", "index": 50, "source": "google"}]
            with patch.object(c, "_collect_index_sync", return_value=expected) as mock_sync:
                result = await c.collect_google_index("海豹", "2026-05-01", "2026-05-02")
                mock_sync.assert_called_once()
        assert result == expected
```

- [ ] **Step 2: Run new tests to verify they pass**

Run: `cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent && python -m pytest tests/test_gopup_collector.py -v`
Expected: All 5 tests PASS (implementation was done in Task 4).

- [ ] **Step 3: Run full test suite**

Run: `cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent && python -m pytest tests/ -v`
Expected: 144 tests PASS (139 existing + 5 new).

- [ ] **Step 4: Commit**

```bash
cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent
git add tests/test_gopup_collector.py
git commit -m "test: gopup collector — _collect_index_sync + toutiao/google delegation (5 tests)"
```

---

### Task 6: scheduler — logging + _store_index_data + new index calls TDD

**Files:**
- Modify: `pipeline/scheduler.py`
- Modify: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing test for _store_index_data with multiple sources**

Append to `tests/test_scheduler.py`:

```python


class TestStoreIndexData:
    @pytest.mark.asyncio
    async def test_stores_multiple_index_sources(self, db, vehicle):
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        baidu_data = [{"date": "2026-05-01", "keyword": "海豹", "index": 100, "source": "baidu"}]
        weibo_data = [{"date": "2026-05-01", "keyword": "海豹", "index": 80, "source": "weibo"}]
        toutiao_data = [{"date": "2026-05-02", "keyword": "海豹", "index": 60, "source": "toutiao"}]
        google_data = [{"date": "2026-05-02", "keyword": "海豹", "index": 40, "source": "google"}]
        await s._store_index_data(vehicle.id, baidu_data, weibo_data, toutiao_data, google_data)
        from models.schemas import HeatMetric
        metrics = (await db.execute(
            select(HeatMetric).where(HeatMetric.vehicle_id == vehicle.id)
        )).scalars().all()
        assert len(metrics) == 4

    @pytest.mark.asyncio
    async def test_store_index_data_empty(self, db, vehicle):
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        await s._store_index_data(vehicle.id, [], [])
        from models.schemas import HeatMetric
        metrics = (await db.execute(
            select(HeatMetric).where(HeatMetric.vehicle_id == vehicle.id)
        )).scalars().all()
        assert len(metrics) == 0
```

- [ ] **Step 2: Run new test to verify it fails**

Run: `cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent && python -m pytest tests/test_scheduler.py::TestStoreIndexData -v`
Expected: FAIL — `_store_index_data` still takes `(vehicle_id, baidu_data, weibo_data)` positional args.

- [ ] **Step 3: Update scheduler.py — add logging, _store_index_data signature, new index calls**

Add at top of `pipeline/scheduler.py` after the existing imports:

```python
import logging
```

Add after the import block:

```python
logger = logging.getLogger(__name__)
```

Replace `_run_collectors` method:

```python
    async def _run_collectors(self, keyword: str, start_date: str, end_date: str, vehicle_id: str) -> list[dict]:
        logger.info("Collecting keyword='%s', range=%s to %s", keyword, start_date, end_date)
        results = []
        news_posts = await self._news.search_all(keyword, start_date, end_date)
        results.extend(news_posts)

        if self._media.is_available():
            for platform in ["xiaohongshu", "bilibili", "zhihu", "weibo", "douyin", "kuaishou", "tieba"]:
                posts = await self._media.search(keyword, platform)
                results.extend(posts)

        baidu_index = await self._gopup.collect_baidu_index(keyword, start_date, end_date)
        weibo_index = await self._gopup.collect_weibo_index(keyword, start_date, end_date)
        toutiao_index = await self._gopup.collect_toutiao_index(keyword, start_date, end_date)
        google_index = await self._gopup.collect_google_index(keyword, start_date, end_date)
        await self._store_index_data(vehicle_id, baidu_index, weibo_index, toutiao_index, google_index)

        index_total = len(baidu_index) + len(weibo_index) + len(toutiao_index) + len(google_index)
        logger.info("Collection done for '%s': %d posts, %d index points", keyword, len(results), index_total)
        return results
```

Replace `_store_index_data` method:

```python
    async def _store_index_data(self, vehicle_id: str, *data_sets: list[dict]):
        for data_set in data_sets:
            for item in data_set:
                raw_date = item.get("date", "")
                if not raw_date:
                    continue
                try:
                    d = date.fromisoformat(raw_date)
                except ValueError:
                    continue
                self._session.add(HeatMetric(
                    id=str(uuid.uuid4()),
                    vehicle_id=vehicle_id,
                    date=d,
                    attention_index=float(item.get("index", 0)),
                ))
        if any(data_sets):
            await self._session.commit()
```

Replace `collect_vehicle` method (add logging):

```python
    async def collect_vehicle(self, vehicle_id: str) -> dict:
        vehicle = await self._session.get(Vehicle, vehicle_id)
        if not vehicle:
            return {"vehicle_id": vehicle_id, "status": "error", "posts_collected": 0, "error": "Vehicle not found"}

        try:
            mode, last_collected = await self._determine_mode(vehicle_id)
            date_ranges = self._get_date_ranges(mode, last_collected)
            logger.info("开始采集 vehicle=%s mode=%s ranges=%d", vehicle.name, mode, len(date_ranges))
            keywords = json.loads(vehicle.search_keywords) if vehicle.search_keywords else [vehicle.name]

            all_posts: list[dict] = []
            for keyword in keywords:
                for start, end in date_ranges:
                    posts = await self._run_collectors(keyword, start, end, vehicle_id)
                    all_posts.extend(posts)

            stored = await self._store_posts(vehicle_id, all_posts)
            await self._update_status(vehicle_id, mode, stored)
            logger.info("采集完成: %d posts stored for %s", stored, vehicle.name)
            return {"vehicle_id": vehicle_id, "mode": mode, "posts_collected": stored, "status": "completed"}
        except Exception as e:
            await self._session.rollback()
            logger.warning("采集失败 vehicle=%s: %s", vehicle_id, e)
            try:
                await self._update_status(vehicle_id, "unknown", 0, str(e))
            except Exception:
                pass
            return {"vehicle_id": vehicle_id, "status": "error", "posts_collected": 0, "error": str(e)}
```

- [ ] **Step 4: Run scheduler tests to verify they pass**

Run: `cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent && python -m pytest tests/test_scheduler.py -v`
Expected: All tests PASS (10 existing + 2 new).

- [ ] **Step 5: Run full test suite**

Run: `cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent && python -m pytest tests/ -v`
Expected: 146 tests PASS.

- [ ] **Step 6: Commit**

```bash
cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent
git add pipeline/scheduler.py tests/test_scheduler.py
git commit -m "feat: scheduler logging + _store_index_data *args + toutiao/google calls — TDD (2 tests)"
```

---

### Task 7: .secrets — add anspire key

**Files:**
- Modify: `.secrets`

- [ ] **Step 1: Update .secrets**

Replace `.secrets` content with:

```json
{
  "baidu": {
    "username": "13800000000",
    "password": "CHANGE_ME_PASSWORD",
    "note": "gopup百度指数Cookie获取用，通过Playwright自动登录，不写入代码日志"
  },
  "anspire": {
    "api_key": ""
  }
}
```

- [ ] **Step 2: Run full test suite to verify nothing breaks**

Run: `cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent && python -m pytest tests/ -v`
Expected: 146 tests PASS.

- [ ] **Step 3: Commit**

```bash
cd /c/Users/<you>/Desktop/Vehicle\ Sentiment\ Analysis\ Agent
git add .secrets
git commit -m "chore: add anspire api_key placeholder to .secrets"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- Anspire data source → Task 2 (search_anspire) + Task 3 (search_all includes anspire) + Task 7 (.secrets)
- 头条/谷歌指数 → Task 4 (_collect_index_sync + new methods) + Task 5 (tests) + Task 6 (scheduler calls)
- Logging → Task 1 (news_collector), Task 4 (gopup_collector), Task 6 (scheduler)
- Scheduler _store_index_data → Task 6

**2. Placeholder scan:** No TBD, TODO, or vague steps found.

**3. Type consistency:**
- `_collect_index_sync` returns `list[dict]` with keys `{"date", "keyword", "index", "source"}` — consistent across Task 4, 5, 6
- `_store_index_data` accepts `*data_sets: list[dict]` — consistent with calls in Task 6
- `_anspire_key` initialized in Task 1, used in Task 2, mocked in Task 3 — consistent
- `search_anspire` returns same format as Tavily/Bocha — consistent
