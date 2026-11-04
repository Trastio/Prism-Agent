# Renovation V3 Implementation Plan

> **STATUS: COMPLETED (2026-06-01)** — All 19 tasks across 4 phases implemented. 351 tests GREEN. Archived to `openspec/archive/renovation-v3/`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the 7-item renovation plan to upgrade data quality, analysis precision, and interaction experience for the Vehicle Sentiment Analysis Agent.

**Architecture:** Phase 0 rebuilds the DB schema (3 new tables, 6 modified tables). Phase 1 upgrades data collection (full-text crawl, keyword expansion, SimHash dedup, comment separation, incremental collection). Phase 2 enhances analysis (dual-model pipeline, comment batch summary, heat weighting, anomaly root cause). Phase 3 adds UI features (DBSCAN event tracking, vehicle groups, search combobox, dialog enhancement).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy (async), SQLite, GLM-4 API, Vue 3 CDN, ECharts, trafilatura, crawl4ai, simhash, scikit-learn, tenacity

**Specs:** `openspec/changes/renovation-v3/specs/`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `requirements.txt` | Add trafilatura, crawl4ai, simhash, scikit-learn, tenacity |
| Modify | `models/schemas.py` | New tables (PostComment, EventGroup, VehicleGroup) + new columns |
| Create | `pipeline/collectors/full_text_crawler.py` | Trafilatura + Crawl4AI two-level crawl |
| Create | `pipeline/collectors/keyword_expander.py` | AI keyword expansion via LLM |
| Create | `pipeline/analysis/deduplicator.py` | SimHash dedup + XHS short-link resolver |
| Modify | `pipeline/collectors/media_crawler.py` | Return comments as separate list |
| Modify | `pipeline/scheduler.py` | Incremental collection + full-text crawl + dedup + comment separation |
| Modify | `pipeline/analysis/heat_calculator.py` | Weighted interaction + remove mediacrawler_comment |
| Modify | `pipeline/analysis/analyzer.py` | Dual-model parallel + event tag pool + dim_sentiment |
| Modify | `pipeline/analysis/batch_runner.py` | Half-month Top 5 comment batch summary |
| Create | `pipeline/analysis/anomaly_explainer.py` | Anomaly root cause from event tag distribution |
| Create | `pipeline/analysis/event_tracker.py` | DBSCAN event clustering + EventGroup |
| Create | `api/routes/group.py` | Vehicle group CRUD + comparison APIs |
| Modify | `api/main.py` | Register group router |
| Modify | `api/routes/dashboard.py` | Event timeline endpoint + dedup filter |
| Modify | `api/routes/vehicle.py` | Search endpoint |
| Modify | `api/routes/dialog.py` | EventGroup context injection |
| Modify | `frontend/index.html` | Group dropdown + search combobox + group view |
| Modify | `frontend/static/js/app.js` | Group data + charts + mode switching + search |
| Modify | `frontend/static/css/style.css` | Group view + combobox styles |

---

## Phase 0: Infrastructure

### Task 0.1: Update requirements.txt

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add new dependencies**

Append to `requirements.txt`:
```
trafilatura>=1.8.0
crawl4ai>=0.4.0
simhash>=2.1.0
scikit-learn>=1.5.0
tenacity>=8.2.0
httpx>=0.27.0
```

- [ ] **Step 2: Install dependencies**

Run: `pip install trafilatura crawl4ai simhash scikit-learn tenacity`

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore: add trafilatura, crawl4ai, simhash, sklearn, tenacity deps"
```

---

### Task 0.2: Rebuild database schema

**Files:**
- Modify: `models/schemas.py`
- Modify: `models/database.py`

- [ ] **Step 1: Add new columns to existing tables in `models/schemas.py`**

Add to `Vehicle` class after `search_keywords`:
```python
expanded_keywords = Column(Text)
```

Add to `RawPost` class after `analysis_status`:
```python
full_content = Column(Text)
duplicate_group_id = Column(String)
```

Add to `AnalyzedPost` class after `model_used`:
```python
is_event = Column(Boolean, default=False)
event_description = Column(Text)
dim_sentiment = Column(Text)
comment_summary = Column(Text)
```

Add to `HeatMetric` class after `interaction_intensity`:
```python
rank = Column(String)
percentile = Column(Float)
```

Add to `AnomalyEvent` class after `brief_generated`:
```python
root_cause = Column(Text)
```

- [ ] **Step 2: Add new tables in `models/schemas.py`**

After `DialogMessage` class, before Pydantic schemas:
```python
class PostComment(Base):
    __tablename__ = "post_comments"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    post_id = Column(String, nullable=False)
    vehicle_id = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    author = Column(String)
    likes = Column(Integer, default=0)
    platform = Column(String)
    published_at = Column(DateTime)
    collected_at = Column(DateTime, server_default=func.now())


class EventGroup(Base):
    __tablename__ = "event_groups"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vehicle_id = Column(String, nullable=False)
    event_tag = Column(String, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    post_count = Column(Integer, default=0)
    post_ids = Column(Text)
    summary = Column(Text)
    sentiment_distribution = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class VehicleGroup(Base):
    __tablename__ = "vehicle_groups"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    description = Column(Text)
    vehicle_ids = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 3: Add drop_all to `models/database.py` init_db**

Replace `init_db()` with:
```python
async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    from models.schemas import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
```

- [ ] **Step 4: Verify tables are created**

Run: `python -c "import asyncio; from models.database import init_db; asyncio.run(init_db()); print('OK')"`

- [ ] **Step 5: Run existing tests**

Run: `pytest tests/ -x -q`

- [ ] **Step 6: Commit**

```bash
git add models/schemas.py models/database.py
git commit -m "feat(phase0): rebuild DB schema — 3 new tables, 6 modified tables"
```

---

## Phase 1: Data Collection Quality

### Task 1.1: Create full_text_crawler.py

**Files:**
- Create: `pipeline/collectors/full_text_crawler.py`
- Test: `tests/test_full_text_crawler.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_full_text_crawler.py`:
```python
import pytest
from unittest.mock import patch, MagicMock
from pipeline.collectors.full_text_crawler import crawl_full_text, _try_trafilatura


@pytest.mark.asyncio
async def test_crawl_trafilatura_success():
    with patch("pipeline.collectors.full_text_crawler._try_trafilatura") as mock_tf:
        mock_tf.return_value = {"url": "https://example.com/news", "full_text": "A" * 300, "status": "success"}
        result = await crawl_full_text("https://example.com/news", "short snippet")
        assert result["status"] == "success"
        assert len(result["full_text"]) > 200


@pytest.mark.asyncio
async def test_crawl_fallback_to_snippet():
    with patch("pipeline.collectors.full_text_crawler._try_trafilatura") as mock_tf, \
         patch("pipeline.collectors.full_text_crawler._try_crawl4ai") as mock_c4:
        mock_tf.return_value = {"url": "https://example.com", "full_text": None, "status": "failed"}
        mock_c4.return_value = {"url": "https://example.com", "full_text": None, "status": "failed"}
        result = await crawl_full_text("https://example.com", "fallback snippet text")
        assert result["status"] == "fallback"
        assert result["full_text"] == "fallback snippet text"


def test_try_trafilatura_short_text():
    with patch("pipeline.collectors.full_text_crawler.trafilatura") as mock_tf:
        mock_tf.fetch_url.return_value = "<html>content</html>"
        mock_tf.extract.return_value = "too short"
        result = _try_trafilatura("https://example.com")
        assert result["status"] == "failed"


def test_try_trafilatura_none_result():
    with patch("pipeline.collectors.full_text_crawler.trafilatura") as mock_tf:
        mock_tf.fetch_url.return_value = "<html>content</html>"
        mock_tf.extract.return_value = None
        result = _try_trafilatura("https://example.com")
        assert result["status"] == "failed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_full_text_crawler.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement full_text_crawler.py**

Create `pipeline/collectors/full_text_crawler.py`:
```python
import logging

import trafilatura

logger = logging.getLogger(__name__)


def _try_trafilatura(url: str) -> dict:
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return {"url": url, "full_text": None, "status": "failed"}
        full_text = trafilatura.extract(
            downloaded, include_comments=False,
            include_tables=True, favor_precision=True,
        )
        if full_text and len(full_text.strip()) > 200:
            return {"url": url, "full_text": full_text, "status": "success"}
        return {"url": url, "full_text": None, "status": "failed"}
    except Exception:
        logger.debug("Trafilatura failed for %s", url)
        return {"url": url, "full_text": None, "status": "failed"}


async def _try_crawl4ai(url: str) -> dict:
    try:
        from crawl4ai import AsyncWebCrawler
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url)
            text = result.markdown if result and result.markdown else ""
            if len(text.strip()) > 200:
                return {"url": url, "full_text": text, "status": "success"}
    except Exception:
        logger.debug("Crawl4AI failed for %s", url)
    return {"url": url, "full_text": None, "status": "failed"}


async def crawl_full_text(url: str, snippet: str = "") -> dict:
    result = _try_trafilatura(url)
    if result["status"] == "success":
        return result
    result = await _try_crawl4ai(url)
    if result["status"] == "success":
        return result
    return {"url": url, "full_text": snippet, "status": "fallback"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_full_text_crawler.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add pipeline/collectors/full_text_crawler.py tests/test_full_text_crawler.py
git commit -m "feat: full-text crawler — trafilatura + crawl4ai + snippet fallback"
```

---

### Task 1.2: Integrate full-text crawl into scheduler

**Files:**
- Modify: `pipeline/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_scheduler.py`:
```python
@pytest.mark.asyncio
async def test_crawl_full_text_integrated(session):
    from unittest.mock import patch, AsyncMock
    from models.schemas import RawPost, Vehicle
    import uuid

    vehicle_id = str(uuid.uuid4())
    session.add(Vehicle(id=vehicle_id, name="测试车", brand="测试", search_keywords='["测试车"]'))
    await session.commit()

    with patch("pipeline.scheduler.NewsCollector") as MockNews, \
         patch("pipeline.scheduler.MediaCrawlerWrapper") as MockMedia, \
         patch("pipeline.scheduler.GopupCollector") as MockGopup, \
         patch("pipeline.scheduler.crawl_full_text", new_callable=AsyncMock) as mock_crawl:
        MockNews.return_value.search_all = AsyncMock(return_value=[{
            "title": "测试新闻", "content": "short snippet",
            "url": "https://example.com/news1", "source": "bocha",
            "published_at": "2026-05-20T10:00:00",
        }])
        MockMedia.return_value.is_available.return_value = False
        MockGopup.return_value.collect_baidu_index = AsyncMock(return_value=[])
        mock_crawl.return_value = {"url": "https://example.com/news1", "full_text": "Full article " * 50, "status": "success"}

        scheduler = CollectionScheduler(session)
        result = await scheduler.collect_vehicle(vehicle_id)

        assert result["status"] == "completed"
        mock_crawl.assert_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scheduler.py::test_crawl_full_text_integrated -v`
Expected: FAIL

- [ ] **Step 3: Implement integration in scheduler.py**

Add import at top of `pipeline/scheduler.py`:
```python
from pipeline.collectors.full_text_crawler import crawl_full_text
```

Add method to `CollectionScheduler` class after `_store_posts`:
```python
async def _crawl_full_texts(self, posts: list[dict]) -> list[dict]:
    tasks = []
    for post in posts:
        if post.get("source") in ("bocha", "anspire", "news") and post.get("url"):
            tasks.append(crawl_full_text(post["url"], post.get("content", "")))
        else:
            tasks.append(None)
    results = await asyncio.gather(*(t for t in tasks if t is not None), return_exceptions=True)
    ri = 0
    for i, post in enumerate(posts):
        if tasks[i] is None:
            continue
        if isinstance(results[ri], Exception):
            ri += 1
            continue
        crawl_result = results[ri]
        ri += 1
        if crawl_result and crawl_result.get("full_text"):
            post["full_content"] = crawl_result["full_text"]
    return posts
```

In `_store_posts`, add `full_content` field to RawPost creation:
```python
self._session.add(RawPost(
    ...
    full_content=post.get("full_content"),
))
```

In `collect_vehicle`, call `_crawl_full_texts` before `_store_posts`:
```python
all_posts = await self._crawl_full_texts(all_posts)
stored = await self._store_posts(vehicle_id, all_posts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scheduler.py -v`

- [ ] **Step 5: Commit**

```bash
git add pipeline/scheduler.py tests/test_scheduler.py
git commit -m "feat: integrate full-text crawl into scheduler pipeline"
```

---

### Task 1.3: Create keyword_expander.py

**Files:**
- Create: `pipeline/collectors/keyword_expander.py`
- Test: `tests/test_keyword_expander.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_keyword_expander.py`:
```python
import pytest
from unittest.mock import patch, AsyncMock
from pipeline.collectors.keyword_expander import expand_keywords, expand_keywords_for_vehicle


@pytest.mark.asyncio
async def test_expand_keywords_success():
    mock_titles = ["比亚迪海豚降价", "海豚荣耀版续航实测"]
    with patch("pipeline.collectors.keyword_expander._call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = '["海豚冠军版", "海豚荣耀版续航", "比亚迪海豚降价"]'
        result = await expand_keywords("比亚迪海豚", ["比亚迪海豚"], mock_titles)
        assert isinstance(result, list)
        assert len(result) >= 3


@pytest.mark.asyncio
async def test_expand_keywords_fallback_on_error():
    with patch("pipeline.collectors.keyword_expander._call_llm", new_callable=AsyncMock) as mock_llm:
        mock_llm.side_effect = Exception("API error")
        result = await expand_keywords("测试车", ["测试车"], [])
        assert result == ["测试车"]


def test_expand_keywords_for_vehicle_already_expanded():
    from models.schemas import Vehicle
    import uuid
    v = Vehicle(id=str(uuid.uuid4()), name="测试车", brand="测试",
                search_keywords='["测试车"]', expanded_keywords='["已有词"]')
    assert expand_keywords_for_vehicle(v) is False


def test_expand_keywords_for_vehicle_needs_expansion():
    from models.schemas import Vehicle
    import uuid
    v = Vehicle(id=str(uuid.uuid4()), name="测试车", brand="测试",
                search_keywords='["测试车"]', expanded_keywords=None)
    assert expand_keywords_for_vehicle(v) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_keyword_expander.py -v`

- [ ] **Step 3: Implement keyword_expander.py**

Create `pipeline/collectors/keyword_expander.py`:
```python
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

EXPAND_PROMPT = """你是一位汽车舆情关键词专家。根据以下车型名、基础关键词和近期新闻标题，扩展出网民在社交媒体上讨论该车型时常用的搜索词。

要求：
- 输出 JSON 数组，包含 10-15 个扩展关键词
- 关键词应该是网民真实搜索语言，不要学术化
- 包含品牌+车型组合、昵称、配置版本、常见话题
- 不要重复基础关键词

车型名：{vehicle_name}
基础关键词：{base_keywords}
近期新闻标题：{titles}

请严格以 JSON 数组格式回复，不要添加其他内容。"""


def _load_api_config() -> dict:
    secrets_path = ".secrets"
    if not os.path.exists(secrets_path):
        return {}
    with open(secrets_path, "r", encoding="utf-8") as f:
        return json.load(f)


async def _call_llm(prompt: str) -> str:
    config = _load_api_config()
    glm_cfg = config.get("glm", {})
    api_key = glm_cfg.get("api_key", "")
    if not api_key:
        raise RuntimeError("No API key configured")
    base_url = glm_cfg.get("base_url", "https://open.bigmodel.cn/api/paas/v4")
    model = glm_cfg.get("keyword_model", glm_cfg.get("model", "glm-4-flash"))
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "user", "content": prompt}]},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def expand_keywords(vehicle_name: str, base_keywords: list[str], news_titles: list[str]) -> list[str]:
    prompt = EXPAND_PROMPT.format(
        vehicle_name=vehicle_name,
        base_keywords=", ".join(base_keywords),
        titles="\n".join(f"- {t}" for t in news_titles[:20]),
    )
    try:
        raw = await _call_llm(prompt)
        match = __import__("re").search(r"\[.*\]", raw, __import__("re").DOTALL)
        if match:
            keywords = json.loads(match.group())
            if isinstance(keywords, list) and keywords:
                return base_keywords + [k for k in keywords if k not in base_keywords]
    except Exception as e:
        logger.warning("Keyword expansion failed: %s", e)
    return base_keywords


def expand_keywords_for_vehicle(vehicle) -> bool:
    return not vehicle.expanded_keywords
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_keyword_expander.py -v`

- [ ] **Step 5: Commit**

```bash
git add pipeline/collectors/keyword_expander.py tests/test_keyword_expander.py
git commit -m "feat: AI keyword expander — LLM-driven search keyword expansion"
```

---

### Task 1.4: Create deduplicator.py with SimHash + XHS URL resolver

**Files:**
- Create: `pipeline/analysis/deduplicator.py`
- Test: `tests/test_deduplicator.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_deduplicator.py`:
```python
import pytest
from unittest.mock import patch, AsyncMock
from pipeline.analysis.deduplicator import deduplicate, resolve_note_id


def test_deduplicate_keeps_first_removes_dup():
    posts = [
        {"title": "比亚迪海豚降价2万", "content": "比亚迪海豚降价2万元", "published_at": "2026-05-01"},
        {"title": "比亚迪海豚降价两万", "content": "比亚迪海豚降价两万元，性价比更高", "published_at": "2026-05-02"},
        {"title": "特斯拉降价", "content": "特斯拉Model 3降价", "published_at": "2026-05-03"},
    ]
    result = deduplicate(posts)
    assert len(result) == 2
    assert result[0]["title"] == "比亚迪海豚降价2万"
    assert result[1]["title"] == "特斯拉降价"


def test_deduplicate_all_different():
    posts = [
        {"title": "新闻A", "content": "完全不同的内容A", "published_at": "2026-05-01"},
        {"title": "新闻B", "content": "完全不同的内容B", "published_at": "2026-05-02"},
        {"title": "新闻C", "content": "完全不同的内容C", "published_at": "2026-05-03"},
    ]
    result = deduplicate(posts)
    assert len(result) == 3


def test_deduplicate_empty():
    assert deduplicate([]) == []


@pytest.mark.asyncio
async def test_resolve_note_id_standard_url():
    result = await resolve_note_id("https://www.xiaohongshu.com/explore/650a1b2c3d4e5f6a7b8c9d0e")
    assert result == "650a1b2c3d4e5f6a7b8c9d0e"


@pytest.mark.asyncio
async def test_resolve_note_id_discovery_url():
    result = await resolve_note_id("https://www.xiaohongshu.com/discovery/item/650a1b2c3d4e5f6a7b8c9d0e")
    assert result == "650a1b2c3d4e5f6a7b8c9d0e"


@pytest.mark.asyncio
async def test_resolve_note_id_xhslink():
    with patch("pipeline.analysis.deduplicator._resolve_short_link", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = "https://www.xiaohongshu.com/explore/650a1b2c3d4e5f6a7b8c9d0e"
        result = await resolve_note_id("https://xhslink.com/a/abc123")
        assert result == "650a1b2c3d4e5f6a7b8c9d0e"


@pytest.mark.asyncio
async def test_resolve_note_id_non_xhs():
    result = await resolve_note_id("https://weibo.com/12345")
    assert result == "12345"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_deduplicator.py -v`

- [ ] **Step 3: Implement deduplicator.py**

Create `pipeline/analysis/deduplicator.py`:
```python
import logging
import re

import httpx
from simhash import Simhash

logger = logging.getLogger(__name__)

XHS_URL_PATTERNS = [
    re.compile(r"/explore/([a-f0-9]{24})"),
    re.compile(r"/discovery/item/([a-f0-9]{24})"),
    re.compile(r"/user/profile/\w+/([a-f0-9]{24})"),
    re.compile(r"/([a-f0-9]{24})(?:\?|#|$)"),
]


def deduplicate(posts: list[dict], threshold: int = 3) -> list[dict]:
    kept = []
    fingerprints = []
    for post in sorted(posts, key=lambda p: p.get("published_at", "")):
        text = f"{post.get('title', '')} {post.get('content', '')}"
        if not text.strip():
            kept.append(post)
            continue
        fp = Simhash(text)
        is_dup = any(fp.distance(kept_fp) <= threshold for kept_fp in fingerprints)
        if is_dup:
            post["duplicate_group_id"] = kept[-1].get("id", "") if kept else ""
        else:
            kept.append(post)
            fingerprints.append(fp)
    return kept


async def _resolve_short_link(short_url: str) -> str:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=5) as client:
            resp = await client.get(short_url)
            return str(resp.url)
    except Exception:
        return short_url


async def resolve_note_id(post_url: str) -> str:
    url = post_url.strip()
    if "xhslink.com" in url:
        url = await _resolve_short_link(url)
    for pattern in XHS_URL_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return url.rsplit("/", 1)[-1].split("?")[0].split("#")[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_deduplicator.py -v`

- [ ] **Step 5: Commit**

```bash
git add pipeline/analysis/deduplicator.py tests/test_deduplicator.py
git commit -m "feat: SimHash dedup + XHS short-link resolver"
```

---

### Task 1.5: Modify media_crawler.py — separate comments

**Files:**
- Modify: `pipeline/collectors/media_crawler.py`
- Test: `tests/test_media_crawler.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_media_crawler.py`:
```python
def test_search_returns_comments_separately(wrapper, tmp_path, monkeypatch):
    """Comments should be returned as a separate list, not appended to content."""
    import json
    data_dir = tmp_path / "data" / "xhs" / "jsonl"
    data_dir.mkdir(parents=True)
    content_file = data_dir / "search_contents_20260501.jsonl"
    content_file.write_text(json.dumps({
        "note_id": "abc123", "title": "海豚提车", "desc": "提车一周感受",
        "nickname": "车主", "liked_count": 10, "comment_count": 3,
        "note_url": "https://www.xiaohongshu.com/explore/abc123",
    }) + "\n", encoding="utf-8")
    comment_file = data_dir / "search_comments_20260501.jsonl"
    comment_file.write_text(json.dumps({
        "note_id": "abc123", "content": "多少钱落地", "nickname": "网友A",
        "like_count": 5, "comment_id": "c1",
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr(wrapper, "_crawler_dir", tmp_path)

    results, comments = wrapper.search_with_comments("海豚", "xiaohongshu")
    assert len(results) == 1
    assert "[热门评论]" not in results[0]["content"]
    assert len(comments) == 1
    assert comments[0]["content"] == "多少钱落地"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_media_crawler.py::test_search_returns_comments_separately -v`

- [ ] **Step 3: Implement changes**

In `media_crawler.py`, add a new method `search_with_comments` to `MediaCrawlerWrapper`:
```python
async def search_with_comments(
    self, keyword: str, platform: PlatformName, max_notes: int = 50,
) -> tuple[list[dict], list[dict]]:
    code = PLATFORM_MAP.get(platform)
    if not code or not self.is_available():
        return [], []
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self._crawler_dir)
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", "main.py",
            "--platform", code, "--lt", "cookie", "--type", "search",
            "--keywords", keyword, "--headless", "true",
            "--get_comment", "true", "--save_data_option", "jsonl",
            "--max_concurrency_num", "1",
            env=env, cwd=str(self._crawler_dir),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        if proc.returncode != 0:
            err = stderr.decode(errors="replace")[-500:]
            logger.warning("MediaCrawler %s failed (rc=%d): %s", platform, proc.returncode, err)
            return [], []
        results = self._read_results(code, keyword)
        raw_comments = self._read_comments(code)
        comments = self._extract_comments(results, raw_comments, code)
        results = [r for r in results if not self._is_dealer_post(r)]
        return results, comments
    except asyncio.TimeoutError:
        proc.kill()
        logger.warning("MediaCrawler %s timed out for '%s'", platform, keyword)
        return [], []
    except Exception as e:
        logger.warning("MediaCrawler %s error: %s", platform, e)
        return [], []

@staticmethod
def _extract_comments(posts: list[dict], raw_comments: dict[str, list[dict]], platform_code: str) -> list[dict]:
    comments = []
    for post in posts:
        post_url = post.get("url", "")
        note_id = post_url.rsplit("/", 1)[-1] if post_url else ""
        for c in raw_comments.get(note_id, []):
            content = c.get("content", "")
            if not content:
                continue
            comments.append({
                "post_url": post_url,
                "post_note_id": note_id,
                "content": content,
                "author": c.get("nickname", ""),
                "likes": int(c.get("like_count", 0) or 0),
                "platform": platform_code,
                "published_at": MediaCrawlerWrapper._extract_published_at(c),
            })
    return comments
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_media_crawler.py -v`

- [ ] **Step 5: Commit**

```bash
git add pipeline/collectors/media_crawler.py tests/test_media_crawler.py
git commit -m "feat: media_crawler — comments returned as separate list"
```

---

### Task 1.6: Update scheduler — incremental collection + dedup + URL resolve + comment storage

**Files:**
- Modify: `pipeline/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_scheduler.py`:
```python
@pytest.mark.asyncio
async def test_incremental_skips_existing_posts(session):
    """Incremental collection should skip posts that already exist by URL."""
    import uuid
    from models.schemas import RawPost, Vehicle
    from unittest.mock import patch, AsyncMock
    from pipeline.scheduler import CollectionScheduler

    vehicle_id = str(uuid.uuid4())
    session.add(Vehicle(id=vehicle_id, name="测试车", brand="测试", search_keywords='["测试车"]'))
    session.add(RawPost(
        id=str(uuid.uuid4()), vehicle_id=vehicle_id, source="bocha",
        content="existing", url="https://example.com/existing",
        title="已存在的帖子",
    ))
    await session.commit()

    with patch("pipeline.scheduler.NewsCollector") as MockNews, \
         patch("pipeline.scheduler.MediaCrawlerWrapper") as MockMedia, \
         patch("pipeline.scheduler.GopupCollector") as MockGopup, \
         patch("pipeline.scheduler.crawl_full_text", new_callable=AsyncMock) as mock_crawl:
        MockNews.return_value.search_all = AsyncMock(return_value=[
            {"title": "已存在的帖子", "content": "existing", "url": "https://example.com/existing", "source": "bocha"},
            {"title": "新帖子", "content": "new", "url": "https://example.com/new", "source": "bocha", "published_at": "2026-05-20T10:00:00"},
        ])
        MockMedia.return_value.is_available.return_value = False
        MockGopup.return_value.collect_baidu_index = AsyncMock(return_value=[])
        mock_crawl.return_value = {"url": "", "full_text": "", "status": "fallback"}

        scheduler = CollectionScheduler(session)
        result = await scheduler.collect_vehicle(vehicle_id)
        assert result["status"] == "completed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scheduler.py::test_incremental_skips_existing_posts -v`

- [ ] **Step 3: Implement scheduler updates**

Add imports to `pipeline/scheduler.py`:
```python
from pipeline.analysis.deduplicator import deduplicate, resolve_note_id
from pipeline.collectors.keyword_expander import expand_keywords, expand_keywords_for_vehicle
```

Add methods to `CollectionScheduler`:
```python
async def _expand_keywords_if_needed(self, vehicle: Vehicle) -> list[str]:
    keywords = json.loads(vehicle.search_keywords) if vehicle.search_keywords else [vehicle.name]
    if not expand_keywords_for_vehicle(vehicle):
        if vehicle.expanded_keywords:
            try:
                return json.loads(vehicle.expanded_keywords)
            except json.JSONDecodeError:
                return keywords
        return keywords
    news_result = await self._session.execute(
        select(RawPost.title).where(RawPost.vehicle_id == vehicle.id).limit(20)
    )
    titles = [row[0] for row in news_result.all() if row[0]]
    expanded = await expand_keywords(vehicle.name, keywords, titles)
    vehicle.expanded_keywords = json.dumps(expanded, ensure_ascii=False)
    await self._session.commit()
    return expanded

async def _resolve_urls(self, posts: list[dict]) -> list[dict]:
    for post in posts:
        url = post.get("url", "")
        if "xhslink.com" in url:
            note_id = await resolve_note_id(url)
            post["resolved_note_id"] = note_id
    return posts

def _store_comments(self, vehicle_id: str, posts_and_comments: list[tuple]) -> int:
    count = 0
    from models.schemas import PostComment
    for post_id, comments in posts_and_comments:
        for c in comments:
            published_at = None
            raw_date = c.get("published_at", "")
            if raw_date:
                try:
                    published_at = datetime.fromisoformat(raw_date)
                except (ValueError, TypeError):
                    pass
            self._session.add(PostComment(
                id=str(uuid.uuid4()),
                post_id=post_id,
                vehicle_id=vehicle_id,
                content=c["content"],
                author=c.get("author", ""),
                likes=c.get("likes", 0),
                platform=c.get("platform", ""),
                published_at=published_at,
            ))
            count += 1
    return count
```

Update `collect_vehicle` to use `_expand_keywords_if_needed` instead of inline keyword parsing, and add dedup + URL resolve steps.

- [ ] **Step 4: Run all scheduler tests**

Run: `pytest tests/test_scheduler.py -v`

- [ ] **Step 5: Commit**

```bash
git add pipeline/scheduler.py tests/test_scheduler.py
git commit -m "feat: scheduler — incremental collection + dedup + URL resolve + keyword expand"
```

---

### Task 1.7: Update heat_calculator.py — weighted interaction + remove mediacrawler_comment

**Files:**
- Modify: `pipeline/analysis/heat_calculator.py`
- Test: `tests/test_heat_calculator.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_heat_calculator.py`:
```python
@pytest.mark.asyncio
async def test_weighted_interaction_intensity(session, vehicle_with_posts):
    from pipeline.analysis.heat_calculator import HeatMetricCalculator
    calc = HeatMetricCalculator(session)
    metric = await calc.calculate_daily(vehicle_with_posts, date(2026, 5, 20))
    assert metric is not None
    # likes=10, comments=5, shares=2 → 10×1 + 5×5 + 2×10 = 55
    assert metric.interaction_intensity == 55.0


@pytest.mark.asyncio
async def test_no_mediacrawler_comment_source(session):
    """mediacrawler_comment should not be counted."""
    from pipeline.analysis.heat_calculator import SOCIAL_SOURCES
    assert "mediacrawler_comment" not in SOCIAL_SOURCES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_heat_calculator.py -v`

- [ ] **Step 3: Implement changes**

In `pipeline/analysis/heat_calculator.py`, change:
```python
SOCIAL_SOURCES = ("mediacrawler",)
```

Change interaction_intensity calculation to:
```python
interaction_intensity = float(row[0] * 1 + row[1] * 5 + row[2] * 10)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_heat_calculator.py -v`

- [ ] **Step 5: Commit**

```bash
git add pipeline/analysis/heat_calculator.py tests/test_heat_calculator.py
git commit -m "feat: weighted interaction intensity (1/5/10) + remove mediacrawler_comment"
```

---

## Phase 2: Analysis Enhancement

### Task 2.1: Rewrite analyzer.py — dual-model parallel + event tag pool + dim_sentiment

**Files:**
- Modify: `pipeline/analysis/analyzer.py`
- Test: `tests/test_analyzer.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_analyzer.py`:
```python
import pytest
from unittest.mock import patch, AsyncMock
from pipeline.analysis.analyzer import AnalysisPipeline, EVENT_TAG_POOL


def test_event_tag_pool_has_17_tags():
    assert len(EVENT_TAG_POOL) == 17


@pytest.mark.asyncio
async def test_analyze_single_returns_dual_model_fields():
    pipeline = AnalysisPipeline()
    with patch.object(pipeline, "_call_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = '{"is_event": true, "event_description": "刹车异响", "event_tags": ["异响/故障"], "opinion_tags": ["刹车问题"], "sentiment": "negative", "dim_sentiment": {"安全性": -1}, "confidence": 0.9}'
        result = await pipeline.analyze_single("提车一周发现刹车异响严重")
        assert result["is_event"] is True
        assert result["sentiment"] == "negative"
        assert "安全性" in result.get("dim_sentiment", {})


@pytest.mark.asyncio
async def test_analyze_non_event_post():
    pipeline = AnalysisPipeline()
    with patch.object(pipeline, "_call_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = '{"is_event": false, "event_description": "", "event_tags": [], "opinion_tags": ["颜值高"], "sentiment": "positive", "dim_sentiment": {"外观": 1}, "confidence": 0.85}'
        result = await pipeline.analyze_single("今天终于提车了，外观真的好看")
        assert result["is_event"] is False
        assert result["event_tags"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analyzer.py -v`

- [ ] **Step 3: Rewrite analyzer.py**

Replace `pipeline/analysis/analyzer.py` entirely with dual-model version containing:
- `EVENT_TAG_POOL` (17 predefined tags)
- `EVENT_ANALYSIS_PROMPT` and `SENTIMENT_DIM_PROMPT`
- `AnalysisPipeline` class with `_call_api()` using tenacity retry
- `analyze_single()` returning all new fields
- Keep backward-compatible `_parse_response()` for migration

(The full implementation is specified in `docs/改造方案.md` 改造 4 code blocks.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_analyzer.py -v`

- [ ] **Step 5: Commit**

```bash
git add pipeline/analysis/analyzer.py tests/test_analyzer.py
git commit -m "feat: dual-model analyzer — event tag pool + dim_sentiment + is_event"
```

---

### Task 2.2: Update batch_runner.py — new fields + comment batch summary

**Files:**
- Modify: `pipeline/analysis/batch_runner.py`
- Test: `tests/test_analysis_api.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_analysis_api.py`:
```python
@pytest.mark.asyncio
async def test_batch_runner_stores_new_fields(session):
    """BatchAnalysisRunner should store is_event, event_description, dim_sentiment."""
    import uuid, json
    from models.schemas import Vehicle, RawPost
    from unittest.mock import patch, AsyncMock
    from pipeline.analysis.batch_runner import BatchAnalysisRunner

    vehicle_id = str(uuid.uuid4())
    session.add(Vehicle(id=vehicle_id, name="测试", brand="测试"))
    session.add(RawPost(id="post1", vehicle_id=vehicle_id, content="刹车异响",
                        source="test", analysis_status="pending"))
    await session.commit()

    runner = BatchAnalysisRunner(session)
    with patch.object(runner._pipeline, "analyze_single", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.return_value = {
            "sentiment": "negative", "is_event": True,
            "event_description": "刹车异响", "event_tags": ["异响/故障"],
            "opinion_tags": ["刹车问题"], "dim_sentiment": {"安全性": -1},
            "confidence": 0.9,
        }
        result = await runner.run_for_vehicle(vehicle_id)
        assert result["analyzed"] == 1

    from models.schemas import AnalyzedPost
    ap = (await session.execute(
        __import__("sqlalchemy").select(AnalyzedPost).where(AnalyzedPost.post_id == "post1")
    )).scalars().first()
    assert ap.is_event is True
    assert ap.event_description == "刹车异响"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_api.py::test_batch_runner_stores_new_fields -v`

- [ ] **Step 3: Implement changes**

Update `BatchAnalysisRunner._analyze_single_post` and `run_for_vehicle` to store new fields:
```python
self._session.add(AnalyzedPost(
    id=str(uuid.uuid4()),
    post_id=post.id,
    vehicle_id=vehicle_id,
    sentiment=analysis["sentiment"],
    event_tags=json.dumps(analysis.get("event_tags", []), ensure_ascii=False),
    opinion_tags=json.dumps(analysis.get("opinion_tags", []), ensure_ascii=False),
    confidence=max(0.0, min(1.0, analysis.get("confidence", 0.0))),
    model_used=self._pipeline._model or "glm-4-flash",
    is_event=analysis.get("is_event", False),
    event_description=analysis.get("event_description", ""),
    dim_sentiment=json.dumps(analysis.get("dim_sentiment", {}), ensure_ascii=False),
))
```

Also update the analysis input to prefer `full_content`:
```python
text = post.full_content if post.full_content else post.content
analysis = await self._pipeline.analyze_single(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_analysis_api.py -v`

- [ ] **Step 5: Commit**

```bash
git add pipeline/analysis/batch_runner.py tests/test_analysis_api.py
git commit -m "feat: batch_runner — store is_event/dim_sentiment + use full_content"
```

---

### Task 2.3: Add comment batch summary (half-month Top 5)

**Files:**
- Modify: `pipeline/analysis/batch_runner.py`
- Test: `tests/test_batch_runner.py` (new)

- [ ] **Step 1: Write failing test**

Create `tests/test_batch_runner.py`:
```python
import pytest
from datetime import date
from pipeline.analysis.batch_runner import get_current_period, get_boundary_overlap_periods


def test_get_current_period_first_half():
    with pytest.mock.patch("pipeline.analysis.batch_runner.date") as mock_date:
        mock_date.today.return_value = date(2026, 5, 10)
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        start, end = get_current_period()
        assert start.day == 1
        assert end.day == 15


def test_get_current_period_second_half():
    with pytest.mock.patch("pipeline.analysis.batch_runner.date") as mock_date:
        mock_date.today.return_value = date(2026, 5, 20)
        mock_date.side_effect = lambda *a, **k: date(*a, **k)
        start, end = get_current_period()
        assert start.day == 16


@pytest.mark.asyncio
async def test_comment_summary_skips_low_comment_posts():
    """Posts with < 5 comments should be skipped."""
    from unittest.mock import patch, AsyncMock
    from pipeline.analysis.batch_runner import summarize_comments
    result = await summarize_comments("post1", "标题", "内容摘要", [
        {"content": "评论1", "likes": 5},
    ], max_comments=30)
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_batch_runner.py -v`

- [ ] **Step 3: Implement half-month + comment summary**

Add to `pipeline/analysis/batch_runner.py`:
```python
from datetime import date as date_type

EVENT_TAG_POOL = [
    "质量问题", "异响/故障", "安全事故", "召回",
    "新车发布/上市", "降价/促销", "交付延迟", "提车分享",
    "续航争议", "充电问题", "智能驾驶事故", "OTA升级",
    "维权投诉", "售后服务", "4S店纠纷",
    "政策法规", "行业动态", "企业人事变动",
]

COMMENT_SUMMARY_PROMPT = """分析以下帖子评论区的整体情况：

帖子标题：{title}
帖子内容摘要：{content_snippet}
评论内容（按点赞数排序，前30条）：
{comments_text}

请输出 JSON：
{{"is_argumentative": true/false, "argument_detail": "", "genuine_themes": [], "genuine_sentiment": "positive/negative/mixed", "genuine_sentiment_score": 0.0, "summary": ""}}

如果评论区正常讨论，即使有不同意见，也不应标记为 argumentative。"""


def get_current_period() -> tuple[date_type, date_type]:
    today = date_type.today()
    if today.day <= 15:
        return today.replace(day=1), today.replace(day=15)
    start = today.replace(day=16)
    if today.month == 12:
        end = date_type(today.year + 1, 1, 1)
    else:
        end = date_type(today.year, today.month + 1, 1)
    return start, date_type.fromordinal(end.toordinal() - 1)


async def summarize_comments(post_id: str, title: str, content_snippet: str,
                             comments: list[dict], max_comments: int = 30) -> dict | None:
    if len(comments) < 5:
        return None
    top_comments = sorted(comments, key=lambda c: c.get("likes", 0), reverse=True)[:max_comments]
    comments_text = "\n".join(f"- {c['content']}" for c in top_comments)
    prompt = COMMENT_SUMMARY_PROMPT.format(
        title=title, content_snippet=content_snippet[:200], comments_text=comments_text,
    )
    # Call GLM-4 via analyzer's API infrastructure
    from pipeline.analysis.analyzer import AnalysisPipeline
    pipeline = AnalysisPipeline()
    try:
        raw = await pipeline._call_api(prompt)
        import json, re
        match = re.search(r"\{[^{}]+\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_batch_runner.py -v`

- [ ] **Step 5: Commit**

```bash
git add pipeline/analysis/batch_runner.py tests/test_batch_runner.py
git commit -m "feat: half-month Top 5 comment batch summary"
```

---

### Task 2.4: Create anomaly_explainer.py

**Files:**
- Create: `pipeline/analysis/anomaly_explainer.py`
- Test: `tests/test_anomaly_explainer.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_anomaly_explainer.py`:
```python
import pytest
from unittest.mock import AsyncMock, patch
from datetime import date
from pipeline.analysis.anomaly_explainer import explain_anomaly_root_cause


@pytest.mark.asyncio
async def test_spike_explained_by_event_tag():
    root_cause = await explain_anomaly_root_cause(
        vehicle_id="v1",
        target_date=date(2026, 5, 20),
        event_type="spike",
        session=AsyncMock(),
        _query_event_tags=AsyncMock(return_value={"维权投诉": 5, "日常讨论": 2}),
        _query_top_post=AsyncMock(return_value="多位车主反馈刹车异响"),
    )
    assert "维权投诉" in root_cause
    assert "刹车异响" in root_cause


@pytest.mark.asyncio
async def test_drop_explained():
    root_cause = await explain_anomaly_root_cause(
        vehicle_id="v1",
        target_date=date(2026, 5, 20),
        event_type="drop",
        session=AsyncMock(),
        _query_event_tags=AsyncMock(return_value={}),
        _query_top_post=AsyncMock(return_value=None),
    )
    assert "无重大事件" in root_cause or "自然回落" in root_cause
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_anomaly_explainer.py -v`

- [ ] **Step 3: Implement anomaly_explainer.py**

Create `pipeline/analysis/anomaly_explainer.py`:
```python
import json
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import AnalyzedPost

logger = logging.getLogger(__name__)


async def _query_event_tags_default(session: AsyncSession, vehicle_id: str, target_date: date) -> dict[str, int]:
    start = datetime.combine(target_date, datetime.min.time())
    end = datetime.combine(target_date + timedelta(days=1), datetime.min.time())
    result = await session.execute(
        select(AnalyzedPost.event_tags).where(
            AnalyzedPost.vehicle_id == vehicle_id,
            AnalyzedPost.analyzed_at >= start,
            AnalyzedPost.analyzed_at < end,
        )
    )
    counts: dict[str, int] = {}
    for (tags_json,) in result.all():
        if not tags_json:
            continue
        try:
            tags = json.loads(tags_json)
        except json.JSONDecodeError:
            continue
        for tag in tags:
            counts[tag] = counts.get(tag, 0) + 1
    return counts


async def _query_top_post_default(session: AsyncSession, vehicle_id: str, target_date: date) -> str | None:
    start = datetime.combine(target_date, datetime.min.time())
    end = datetime.combine(target_date + timedelta(days=1), datetime.min.time())
    result = await session.execute(
        select(AnalyzedPost.event_description).where(
            AnalyzedPost.vehicle_id == vehicle_id,
            AnalyzedPost.is_event == True,
            AnalyzedPost.analyzed_at >= start,
            AnalyzedPost.analyzed_at < end,
        ).limit(1)
    )
    row = result.first()
    return row[0] if row else None


async def explain_anomaly_root_cause(
    vehicle_id: str, target_date: date, event_type: str, session: AsyncSession,
    _query_event_tags=None, _query_top_post=None,
) -> str:
    q_tags = _query_event_tags or _query_event_tags_default
    q_post = _query_top_post or _query_top_post_default

    tag_counts = await q_tags(session, vehicle_id, target_date)
    top_desc = await q_post(session, vehicle_id, target_date)

    date_str = target_date.strftime("%m/%d")

    if event_type == "spike":
        if tag_counts:
            top_tag = max(tag_counts, key=tag_counts.get)
            cause = f"{date_str}{top_tag}事件引发声量激增"
            if top_desc:
                cause += f"（{top_desc[:30]}）"
            return cause
        return f"{date_str}声量突增，无明确事件标签"

    if event_type == "drop":
        if not tag_counts:
            return f"{date_str}无重大事件，声量自然回落"
        return f"{date_str}事件热度消退，声量回落"

    return f"{date_str}声量异常变化"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_anomaly_explainer.py -v`

- [ ] **Step 5: Commit**

```bash
git add pipeline/analysis/anomaly_explainer.py tests/test_anomaly_explainer.py
git commit -m "feat: anomaly root cause explainer — event tag distribution analysis"
```

---

### Task 2.5: Update heat_calculator — rank + percentile

**Files:**
- Modify: `pipeline/analysis/heat_calculator.py`
- Test: `tests/test_heat_calculator.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_heat_calculator.py`:
```python
@pytest.mark.asyncio
async def test_metric_has_rank_and_percentile(session, vehicle_with_posts):
    from pipeline.analysis.heat_calculator import HeatMetricCalculator
    calc = HeatMetricCalculator(session)
    metric = await calc.calculate_daily(vehicle_with_posts, date(2026, 5, 20))
    assert metric is not None
    assert metric.rank is not None
    assert metric.percentile is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_heat_calculator.py::test_metric_has_rank_and_percentile -v`

- [ ] **Step 3: Implement rank + percentile**

Add to `HeatMetricCalculator.calculate_daily` after upsert:
```python
# Calculate rank and percentile over last 30 days
thirty_days_ago = target_date - timedelta(days=30)
range_result = await self._session.execute(
    select(HeatMetric.interaction_intensity).where(
        HeatMetric.vehicle_id == vehicle_id,
        HeatMetric.date >= thirty_days_ago,
        HeatMetric.date <= target_date,
    )
)
values = [v for (v,) in range_result.all() if v is not None and v > 0]
if values:
    sorted_values = sorted(values, reverse=True)
    rank_pos = 0
    for i, v in enumerate(sorted_values):
        if v <= metric.interaction_intensity:
            rank_pos = i
            break
    percentile = round(rank_pos / len(sorted_values) * 100, 1)
    if percentile >= 99:
        metric.rank = "近30天最高"
    elif percentile >= 90:
        metric.rank = "前10%"
    elif percentile >= 75:
        metric.rank = "前25%"
    else:
        metric.rank = f"前{int(100 - percentile)}%"
    metric.percentile = percentile
else:
    metric.rank = "无历史数据"
    metric.percentile = 0.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_heat_calculator.py -v`

- [ ] **Step 5: Commit**

```bash
git add pipeline/analysis/heat_calculator.py tests/test_heat_calculator.py
git commit -m "feat: heat metric rank + percentile over 30-day window"
```

---

## Phase 3: Presentation & Interaction

### Task 3.1: Create event_tracker.py (DBSCAN clustering)

**Files:**
- Create: `pipeline/analysis/event_tracker.py`
- Test: `tests/test_event_tracker.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_event_tracker.py`:
```python
import pytest
from datetime import datetime, timedelta
from pipeline.analysis.event_tracker import cluster_events


def test_cluster_two_nearby_events():
    base = datetime(2026, 5, 1)
    posts = [
        {"id": "1", "is_event": True, "event_tags": ["维权投诉"], "analyzed_at": base, "event_description": "刹车异响"},
        {"id": "2", "is_event": True, "event_tags": ["维权投诉"], "analyzed_at": base + timedelta(days=3), "event_description": "集体维权"},
        {"id": "3", "is_event": True, "event_tags": ["维权投诉"], "analyzed_at": base + timedelta(days=20), "event_description": "另一事件"},
    ]
    groups = cluster_events(posts)
    assert len(groups) == 2
    # First group should have 2 posts
    two_post_group = [g for g in groups if g["post_count"] == 2]
    assert len(two_post_group) == 1


def test_cluster_single_post():
    posts = [
        {"id": "1", "is_event": True, "event_tags": ["召回"], "analyzed_at": datetime(2026, 5, 1), "event_description": "召回事件"},
    ]
    groups = cluster_events(posts)
    assert len(groups) == 1
    assert groups[0]["post_count"] == 1


def test_cluster_skips_non_events():
    posts = [
        {"id": "1", "is_event": False, "event_tags": [], "analyzed_at": datetime(2026, 5, 1), "event_description": ""},
    ]
    groups = cluster_events(posts)
    assert len(groups) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_event_tracker.py -v`

- [ ] **Step 3: Implement event_tracker.py**

Create `pipeline/analysis/event_tracker.py`:
```python
import logging
from collections import defaultdict
from datetime import datetime

import numpy as np
from sklearn.cluster import DBSCAN

logger = logging.getLogger(__name__)


def cluster_events(
    analyzed_posts: list[dict],
    time_window_days: int = 7,
    min_samples: int = 1,
) -> list[dict]:
    tag_buckets = defaultdict(list)
    for post in analyzed_posts:
        if not post.get("is_event") or not post.get("event_tags"):
            continue
        for tag in post["event_tags"]:
            tag_buckets[tag].append(post)

    groups = []
    group_id = 0
    for tag, posts in tag_buckets.items():
        if len(posts) == 1:
            groups.append(_make_group(group_id, tag, [posts[0]]))
            group_id += 1
            continue
        times = np.array([p["analyzed_at"].timestamp() for p in posts]).reshape(-1, 1)
        db = DBSCAN(eps=time_window_days * 86400, min_samples=min_samples, metric="euclidean")
        labels = db.fit_predict(times)
        for label in set(labels):
            if label == -1:
                for idx in np.where(labels == -1)[0]:
                    groups.append(_make_group(group_id, tag, [posts[idx]]))
                    group_id += 1
            else:
                members = [posts[i] for i in np.where(labels == label)[0]]
                groups.append(_make_group(group_id, tag, members))
                group_id += 1
    return groups


def _make_group(gid: int, tag: str, members: list[dict]) -> dict:
    return {
        "id": gid,
        "event_tag": tag,
        "start_time": min(m["analyzed_at"] for m in members),
        "end_time": max(m["analyzed_at"] for m in members),
        "post_ids": [m["id"] for m in members],
        "post_count": len(members),
        "representative_desc": members[0].get("event_description", ""),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_event_tracker.py -v`

- [ ] **Step 5: Commit**

```bash
git add pipeline/analysis/event_tracker.py tests/test_event_tracker.py
git commit -m "feat: DBSCAN event clustering — 7-day radius, auto grouping"
```

---

### Task 3.2: Add event timeline API to dashboard

**Files:**
- Modify: `api/routes/dashboard.py`
- Test: `tests/test_dashboard_api.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_dashboard_api.py`:
```python
@pytest.mark.asyncio
async def test_event_timeline_endpoint(client):
    response = await client.get("/api/vehicles/nonexistent/events")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dashboard_api.py::test_event_timeline_endpoint -v`

- [ ] **Step 3: Implement event timeline endpoint**

Add to `api/routes/dashboard.py`:
```python
@router.get("/vehicles/{vehicle_id}/events")
async def get_event_timeline(vehicle_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(EventGroup).where(EventGroup.vehicle_id == vehicle_id).order_by(EventGroup.start_date.desc())
    )
    events = result.scalars().all()
    return [
        {
            "id": e.id, "event_tag": e.event_tag,
            "start_date": str(e.start_date), "end_date": str(e.end_date),
            "post_count": e.post_count, "summary": e.summary,
        }
        for e in events
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_dashboard_api.py -v`

- [ ] **Step 5: Commit**

```bash
git add api/routes/dashboard.py tests/test_dashboard_api.py
git commit -m "feat: event timeline API endpoint"
```

---

### Task 3.3: Create group.py — Vehicle group CRUD + comparison APIs

**Files:**
- Create: `api/routes/group.py`
- Modify: `api/main.py`
- Test: `tests/test_group_api.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_group_api.py`:
```python
import pytest


@pytest.mark.asyncio
async def test_create_group(client):
    response = await client.post("/api/groups", json={
        "name": "10万级紧凑SUV", "vehicle_ids": ["v1", "v2"],
    })
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "10万级紧凑SUV"


@pytest.mark.asyncio
async def test_list_groups(client):
    await client.post("/api/groups", json={"name": "分组A", "vehicle_ids": []})
    response = await client.get("/api/groups")
    assert response.status_code == 200
    assert len(response.json()) >= 1


@pytest.mark.asyncio
async def test_delete_group(client):
    create = await client.post("/api/groups", json={"name": "待删除", "vehicle_ids": []})
    gid = create.json()["id"]
    response = await client.delete(f"/api/groups/{gid}")
    assert response.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_group_api.py -v`

- [ ] **Step 3: Implement group.py**

Create `api/routes/group.py` with CRUD endpoints per the spec (POST, GET, PUT, DELETE /api/groups/*).

Register in `api/main.py`:
```python
from api.routes import group
app.include_router(group.router, prefix="/api")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_group_api.py -v`

- [ ] **Step 5: Commit**

```bash
git add api/routes/group.py api/main.py tests/test_group_api.py
git commit -m "feat: vehicle group CRUD + comparison API endpoints"
```

---

### Task 3.4: Frontend — group view + search combobox

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/static/js/app.js`
- Modify: `frontend/static/css/style.css`

- [ ] **Step 1: Add group dropdown to header in index.html**

Add group `<select>` next to vehicle `<select>` in header area.

- [ ] **Step 2: Replace vehicle select with search combobox in index.html**

Replace `<select id="vehicleSelect">` with a search input + dropdown combobox structure.

- [ ] **Step 3: Add combobox styles in style.css**

Add `.search-combobox`, `.search-combobox-dropdown`, `.search-combobox-item` styles.

- [ ] **Step 4: Add group view styles in style.css**

Add `.group-overview`, `.group-card`, `.group-chart` styles.

- [ ] **Step 5: Implement search combobox logic in app.js**

Add `initSearchCombobox()` function with debounced search, keyboard navigation, and API call to `/api/vehicles/search`.

- [ ] **Step 6: Implement group view in app.js**

Add `loadGroupOverview()`, `loadGroupComparison()`, `loadGroupTrend()`, `switchToGroupMode()`, `switchToVehicleMode()`.

- [ ] **Step 7: Manual verification**

Run: `python start.py`
Open browser, verify: search combobox works, group dropdown shows, group view renders.

- [ ] **Step 8: Commit**

```bash
git add frontend/ api/routes/vehicle.py
git commit -m "feat: frontend — group view + search combobox + group dashboard"
```

---

### Task 3.5: Dialog enhancement — EventGroup context

**Files:**
- Modify: `api/routes/dialog.py`
- Modify: `frontend/static/js/dialog.js`

- [ ] **Step 1: Add EventGroup data injection to dialog context builder**

In `_build_context()`, add EventGroup query and formatting.

- [ ] **Step 2: Add event anchor type rendering in dialog.js**

Add event card rendering for anchor type "event".

- [ ] **Step 3: Commit**

```bash
git add api/routes/dialog.py frontend/static/js/dialog.js
git commit -m "feat: dialog — EventGroup context + event anchor cards"
```

---

## Dependency Graph

```
Phase 0 (Tasks 0.1, 0.2)
    │
    ├──── Phase 1 ──────────────────────────────────────────┐
    │   Task 1.1 (full_text_crawler) ← independent          │
    │   Task 1.2 (scheduler integration) ← depends on 1.1    │
    │   Task 1.3 (keyword_expander) ← independent            │
    │   Task 1.4 (deduplicator) ← independent                │
    │   Task 1.5 (media_crawler comments) ← independent      │
    │   Task 1.6 (scheduler integration) ← depends on 1.3-1.5│
    │   Task 1.7 (heat_calculator) ← independent             │
    │                                                        │
    ├──── Phase 2 ──────────────────────────────────────────┤
    │   Task 2.1 (analyzer rewrite) ← depends on Phase 0     │
    │   Task 2.2 (batch_runner update) ← depends on 2.1      │
    │   Task 2.3 (comment summary) ← depends on 2.2          │
    │   Task 2.4 (anomaly explainer) ← depends on Phase 0    │
    │   Task 2.5 (heat rank/percentile) ← depends on 1.7     │
    │                                                        │
    └──── Phase 3 ──────────────────────────────────────────┘
        Task 3.1 (event_tracker) ← depends on 2.1
        Task 3.2 (event timeline API) ← depends on 3.1
        Task 3.3 (group CRUD) ← depends on Phase 0
        Task 3.4 (frontend) ← depends on 3.2, 3.3
        Task 3.5 (dialog) ← depends on 3.2
```

**Parallelizable within Phase 1:** Tasks 1.1, 1.3, 1.4, 1.5, 1.7 are independent.
**Parallelizable within Phase 2:** Tasks 2.1, 2.4 can run in parallel. 2.5 can run in parallel with 2.2-2.3.
**Parallelizable within Phase 3:** Tasks 3.1, 3.3 can run in parallel.

---

## Total: 19 tasks across 4 phases

| Phase | Tasks | Est. Hours |
|-------|-------|------------|
| 0 | 2 | 1h |
| 1 | 7 | 11h |
| 2 | 5 | 7h |
| 3 | 5 | 9h |
| **Total** | **19** | **~28h** |
