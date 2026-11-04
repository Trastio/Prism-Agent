# Analysis Pipeline Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure analysis pipeline — posts API-only, comments local ABSA, split social/news events, remove anomaly detection, implement fetch_top_comments.

**Architecture:** 7 independent tasks across 4 layers: deletion (Task 1), analyzer refactor (Task 2, 3), scheduler refactor (Task 4), event refactor (Task 5), integration (Task 6, 7). Tasks are ordered to minimize merge conflicts.

**Tech Stack:** Python + FastAPI + SQLAlchemy async + SQLite + Qwen3-4B LoRA (local GPU) + glm-4-flash (API)

---

## File Impact Map

| File | Task 1 | Task 2 | Task 3 | Task 4 | Task 5 | Task 6 | Task 7 |
|------|--------|--------|--------|--------|--------|--------|--------|
| `api/routes/analysis.py` | modify | | | | modify | | |
| `api/routes/collection.py` | modify | | | | modify | | |
| `api/routes/dashboard.py` | modify | | | | | | |
| `pipeline/analysis/analyzer.py` | | **rewrite** | | | | | |
| `pipeline/analysis/batch_runner.py` | | modify | **add** | | | | |
| `pipeline/analysis/local_absa.py` | | | modify | | | | |
| `pipeline/scheduler.py` | | | | **rewrite** | | | |
| `pipeline/collectors/cdp_collector.py` | | | | modify | | | |
| `pipeline/analysis/event_tracker.py` | | | | | **rewrite** | | |
| `pipeline/analysis/anomaly_detector.py` | **delete** | | | | | | |
| `pipeline/analysis/anomaly_explainer.py` | **delete** | | | | | | |
| `models/schemas.py` | modify | | | | | | |
| `frontend/index.html` | | | | | | modify | |
| `frontend/static/js/app.js` | | | | | | modify | |
| Tests | modify | modify | **create** | modify | modify | | |

---

### Task 1: Delete anomaly detection

**Goal:** Remove anomaly_detector.py, anomaly_explainer.py, their pipeline calls, dashboard endpoint, and AnomalyEvent table.

**Files:**
- Delete: `pipeline/analysis/anomaly_detector.py`
- Delete: `pipeline/analysis/anomaly_explainer.py`
- Modify: `api/routes/analysis.py:44-51` — remove AnomalyDetector call
- Modify: `api/routes/collection.py:48-56` — remove AnomalyDetector call
- Modify: `api/routes/dashboard.py:286-325` — remove /anomaly-timeline endpoint
- Modify: `models/schemas.py:101-115` — comment out AnomalyEvent table (keep for migration)
- Modify: `tests/test_anomaly_detector.py` — delete
- Modify: `tests/test_anomaly_explainer.py` — delete
- Modify: `frontend/index.html` — remove anomaly-timeline section
- Modify: `frontend/static/js/app.js` — remove anomaly chart rendering

- [ ] **Step 1: Remove pipeline calls**

`api/routes/analysis.py` — remove lines 44-51:
```python
# DELETE these lines:
        # Phase 4: Anomaly detection
        end = date.today()
        start = end - timedelta(days=90)
        from pipeline.analysis.anomaly_detector import AnomalyDetector
        detector = AnomalyDetector(session)
        await detector.check_range(vehicle_id, start, end)
```

Also remove `from datetime import timedelta` if no longer needed, or check other usages.

`api/routes/collection.py` — remove lines 48-56:
```python
# DELETE these lines:
        # Phase 4: Anomaly detection
        end = date.today()
        start = end - timedelta(days=90)
        from pipeline.analysis.anomaly_detector import AnomalyDetector
        detector = AnomalyDetector(session)
        await detector.check_range(vehicle_id, start, end)
```

Similarly remove `timedelta` import if only used here.

- [ ] **Step 2: Delete anomaly files and tests**

```bash
rm pipeline/analysis/anomaly_detector.py
rm pipeline/analysis/anomaly_explainer.py
rm tests/test_anomaly_detector.py
rm tests/test_anomaly_explainer.py
```

- [ ] **Step 3: Comment out AnomalyEvent table**

In `models/schemas.py`, wrap lines 101-115 with a comment explaining deprecation:
```python
# DEPRECATED: AnomalyEvent removed in 2026-06 analysis redesign.
# Table kept for backward-compat migration reference.
# class AnomalyEvent(Base):
#     __tablename__ = "anomaly_events"
#     ...
```

- [ ] **Step 4: Remove dashboard endpoint**

Remove `get_anomaly_timeline` function (lines 286-325) from `api/routes/dashboard.py`.

- [ ] **Step 5: Remove frontend anomaly component**

In `frontend/index.html`, remove the anomaly timeline section (look for "anomaly" or "异常" in section divs).

In `frontend/static/js/app.js`, remove anomaly-related chart rendering and data fetching.

- [ ] **Step 6: Run tests to verify no regressions**

```bash
conda run -n base python -m pytest tests/ -q --tb=no --ignore=tests/test_anomaly_detector.py --ignore=tests/test_anomaly_explainer.py
```

Expected: all pass (except known asyncio error).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: remove anomaly detection pipeline and endpoints"
```

---

### Task 2: Switch post analysis to API-only

**Goal:** Remove local ABSA usage from post analysis. All fields (sentiment, dim_sentiment, event_tags, subject, etc.) come from API LLM via COMBINED_ANALYSIS_PROMPT. Local ABSA stays available for comment analysis (Task 3).

**Files:**
- Modify: `pipeline/analysis/analyzer.py` — remove dual-mode, simplify to API-only
- Modify: `pipeline/analysis/batch_runner.py:163-180` — no change needed (already calls analyze_batch)
- Modify: `tests/test_analyzer.py` — update tests for API-only mode

- [ ] **Step 1: Simplify AnalysisPipeline to API-only**

In `analyzer.py`:
- Remove `_use_local`, `_local_absa` references from `__init__` (lines 120-133)
- Simplify `analyze_single` to always use COMBINED_ANALYSIS_PROMPT (keep lines 201-216, remove dual-mode block lines 175-199)
- Simplify `analyze_batch` to always use API-only path — remove `_analyze_batch_dual` method and its call
- Remove `from pipeline.analysis.local_absa import ALL_DIMENSIONS, LocalABSAModel` import
- Keep `_parse_response`, `_fallback_result`, `EVENT_ONLY_PROMPT` (for event detection), event tag pool
- Keep API call retry logic and semaphore

The simplified `analyze_single`:
```python
async def analyze_single(self, text: str, vehicle_name: str = "", vehicle_brand: str = "") -> dict:
    if not text or not text.strip():
        return self._fallback_result()
    vehicle_name = vehicle_name or ""
    vehicle_brand = vehicle_brand or ""
    prompt = COMBINED_ANALYSIS_PROMPT.format(
        event_tags=", ".join(EVENT_TAG_POOL),
        vehicle_name=vehicle_name, vehicle_brand=vehicle_brand,
    )
    try:
        raw = await self._call_api(prompt, text)
        return self._parse_response(raw)
    except Exception:
        logger.warning("analyze_single API failed, returning fallback")
        return self._fallback_result()
```

The simplified `analyze_batch`:
```python
async def analyze_batch(self, posts: list[dict], vehicle_name: str = "", vehicle_brand: str = "") -> list[dict]:
    async def _analyze_one(post):
        text = post.get("content", "")
        return await self.analyze_single(text, vehicle_name, vehicle_brand)
    
    sem = asyncio.Semaphore(self._semaphore_limit)
    async def _limited(post):
        async with sem:
            return await _analyze_one(post)
    
    tasks = [_limited(p) for p in posts]
    return await asyncio.gather(*tasks)
```

- [ ] **Step 2: Update batch_runner imports if needed**

Check `batch_runner.py` imports — if it imports from `local_absa`, remove. If `AnalysisPipeline` no longer accepts local model params, update constructor call.

- [ ] **Step 3: Update tests**

`tests/test_analyzer.py` — remove dual-mode tests (`TestDualModel` class). Keep API-only tests. Run:
```bash
conda run -n base python -m pytest tests/test_analyzer.py -v
```

- [ ] **Step 4: Verify no other code imports LocalABSAModel for post analysis**

```bash
rg "LocalABSAModel" --type py | grep -v test | grep -v local_absa
```
Should only show `local_absa.py` itself and future comment analysis code.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: switch post analysis to API-only, remove dual-model mode"
```

---

### Task 3: Add comment-level ABSA via local model

**Goal:** Analyze comments through the local Qwen3-4B ABSA model. Each comment gets dimension-level sentiment scored. Results stored in a new `comment_analysis` JSON column on PostComment, or aggregated per post.

**Design decision:** Store per-comment dim_sentiment on a new `dim_sentiment` column on PostComment. Aggregate at dashboard query time.

**Files:**
- Modify: `models/schemas.py` — add `dim_sentiment` column to `PostComment`
- Modify: `models/database.py` — add migration
- Modify: `pipeline/analysis/batch_runner.py` — add `run_comment_analysis` method
- Create: `tests/test_comment_analysis.py`

- [ ] **Step 1: Add dim_sentiment column to PostComment**

In `models/schemas.py`, add after `author` column (line 156):
```python
    # dim_sentiment: 15-dimension ABSA result from local model (JSON: {"维度名": score})
    dim_sentiment = Column(Text)
```

- [ ] **Step 2: Add migration**

In `models/database.py`, add after the `_migrate_subject_name` block:
```python
        def _migrate_comment_dim(sync_conn):
            sync_conn.execute(text(
                "ALTER TABLE post_comments ADD COLUMN dim_sentiment TEXT"
            ))
        try:
            await conn.run_sync(_migrate_comment_dim)
        except Exception:
            pass  # Column already exists
```

- [ ] **Step 3: Add run_comment_analysis to BatchAnalysisRunner**

New method in `batch_runner.py`:
```python
async def run_comment_analysis(self, vehicle_id: str) -> int:
    """Analyze comments with local ABSA model for dimension sentiment."""
    from pipeline.analysis.local_absa import LocalABSAModel
    
    local_model = LocalABSAModel.get()
    if not local_model._loaded:
        logger.warning("Local ABSA model not loaded, skipping comment analysis")
        return 0
    
    # Select comments to analyze: top-N recent comments without dim_sentiment
    result = await self._session.execute(
        select(PostComment).where(
            PostComment.vehicle_id == vehicle_id,
            or_(PostComment.dim_sentiment.is_(None), PostComment.dim_sentiment == ""),
        ).limit(500)  # batch size cap
    )
    comments = result.scalars().all()
    
    if not comments:
        return 0
    
    texts = [c.content for c in comments if c.content and c.content.strip()]
    batch_results = local_model.predict_batch(texts)
    
    analyzed = 0
    result_idx = 0
    for comment in comments:
        if not comment.content or not comment.content.strip():
            continue
        if result_idx < len(batch_results):
            dims = batch_results[result_idx].get("dim_sentiment", {})
            comment.dim_sentiment = json.dumps(dims, ensure_ascii=False) if dims else "{}"
            analyzed += 1
            result_idx += 1
    
    await self._session.commit()
    return analyzed
```

Add import at top: `from models.schemas import PostComment` and `from sqlalchemy import or_`.

- [ ] **Step 4: Wire into analysis pipeline**

In `api/routes/analysis.py` `_run_analysis_pipeline`, after `run_for_vehicle` and after `run_comment_summaries`, add:
```python
# Comment dimension analysis (local GPU)
cmt_analyzed = await runner.run_comment_analysis(vehicle_id)
pipeline_phases[vehicle_id].setdefault("comments_analyzed", cmt_analyzed)
```

Also do the same in `api/routes/collection.py` `_run_full_pipeline`.

- [ ] **Step 5: Write test**

`tests/test_comment_analysis.py`:
```python
"""Test comment dimension analysis with local ABSA."""
import json
import pytest
from models.schemas import PostComment, AnalyzedPost


def test_postcomment_has_dim_sentiment_column():
    assert hasattr(PostComment, "dim_sentiment")


def test_dim_sentiment_stores_json():
    pc = PostComment(
        id="test-c1", post_id="p1", vehicle_id="v1",
        content="续航不行但空间大", author="用户A",
        dim_sentiment='{"续航里程": -1, "空间": 1}',
    )
    dims = json.loads(pc.dim_sentiment)
    assert dims["续航里程"] == -1
    assert dims["空间"] == 1
```

- [ ] **Step 6: Run tests**

```bash
conda run -n base python -m pytest tests/test_comment_analysis.py -v
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: add comment-level ABSA via local GPU model"
```

---

### Task 4: Implement fetch_top_comments

**Goal:** Replace no-op `fetch_top_comments` with real CDP comment fetching for top-5 posts per platform.

**Files:**
- Modify: `pipeline/scheduler.py:543-547` — implement fetch_top_comments
- Modify: `pipeline/collectors/cdp_collector.py` — add `fetch_comments_for_post` method
- Modify: `tests/test_scheduler.py` — update mock

- [ ] **Step 1: Add fetch_comments_for_post to CdpCollector**

New method in `cdp_collector.py`:
```python
async def fetch_comments_for_post(self, url: str, platform: str) -> list[dict]:
    """Open a post detail page and extract comments. Best-effort."""
    comments: list[dict] = []
    try:
        if platform in ("weibo", "wb"):
            tab = await self._client.new_tab(url)
            try:
                await asyncio.sleep(2)
                # Extract post ID from URL
                post_id_match = re.search(r'/status/(\d+)', url)
                if post_id_match:
                    ext = WeiboExtractor()
                    raw = await self._client.eval_js(tab, ext.comment_js(post_id_match.group(1)))
                    data = json.loads(str(raw)) if isinstance(raw, str) else (raw or {})
                    for cc in data.get("comments") or []:
                        comments.append(_make_comment(
                            content=cc.get("content", ""),
                            author=cc.get("author", ""),
                            likes=cc.get("likes", 0),
                            platform="wb",
                            post_url=url,
                            post_note_id=post_id_match.group(1),
                            published_at=cc.get("created_at", ""),
                        ))
            finally:
                await self._client.close_tab(tab)
        
        elif platform in ("douyin", "dy"):
            ext = DouyinExtractor()
            tab = await self._client.new_tab(url)
            try:
                await asyncio.sleep(4)
                # Scroll to load comments
                await self._client.scroll(tab, "bottom")
                await asyncio.sleep(1)
                raw = await self._client.eval_js(tab, ext.COMMENTS_JS)
                cmt_list = _parse_json_result(raw)
                for cc in (cmt_list or []):
                    comments.append(_make_comment(
                        content=cc.get("content", ""),
                        author="",
                        likes=int(cc.get("likes", 0) or 0),
                        platform="douyin",
                        post_url=url,
                        post_note_id="",
                    ))
            finally:
                await self._client.close_tab(tab)
        
        elif platform in ("xiaohongshu", "xhs"):
            ext = XiaohongshuExtractor()
            tab = await self._client.new_tab(url)
            try:
                await asyncio.sleep(4)
                await self._client.scroll(tab, "bottom")
                await asyncio.sleep(3)
                raw = await self._client.eval_js(tab, ext.COMMENTS_JS)
                cmt_list = _parse_json_result(raw)
                for cc in (cmt_list or []):
                    comments.append(_make_comment(
                        content=cc.get("content", ""),
                        author=cc.get("author", ""),
                        likes=cc.get("likes", 0),
                        platform="xhs",
                        post_url=url,
                        published_at=cc.get("time_text", ""),
                    ))
            finally:
                await self._client.close_tab(tab)
    except Exception:
        pass  # best-effort
    
    return comments
```

Add `import re` at top if not present.

- [ ] **Step 2: Implement fetch_top_comments in scheduler**

Replace the no-op in `scheduler.py:543-547`:
```python
async def fetch_top_comments(self, vehicle_id: str) -> int:
    """Fetch comments for top-5 posts per platform via CDP."""
    from pipeline.analysis.batch_runner import select_top_posts_for_comments, _COMMENT_TOP_N
    
    top_posts = await select_top_posts_for_comments(self._session, vehicle_id)
    if not top_posts:
        return 0
    
    cdp = CdpCollector()
    if not await cdp.is_available():
        logger.warning("CDP proxy not available, skipping comment fetch")
        return 0
    
    # Per-platform cap: top-5
    platform_counts: dict[str, int] = {}
    total = 0
    
    for post in top_posts:
        plat = post.platform
        # Map short codes to full names
        plat_full = {"wb": "weibo", "dy": "douyin", "ks": "kuaishou", "xhs": "xiaohongshu"}.get(plat, plat)
        
        if plat_full == "kuaishou":
            continue  # Kuaishou detail pages 404, skip
        
        if platform_counts.get(plat_full, 0) >= 5:
            continue
        
        comments = await cdp.fetch_comments_for_post(post.url, plat_full)
        if comments:
            await self._store_comments(vehicle_id, comments)
            platform_counts[plat_full] = platform_counts.get(plat_full, 0) + 1
            total += len(comments)
    
    return total
```

- [ ] **Step 3: Update select_top_posts_for_comments constants for TOP5**

In `batch_runner.py`, update `_COMMENT_TOP_N` to 5 per platform:
```python
_COMMENT_TOP_N: dict[str, int] = {
    "xiaohongshu": 5,
    "weibo": 5,
    "douyin": 5,
    "kuaishou": 5,
}
```

- [ ] **Step 4: Update tests**

`tests/test_scheduler.py` — update any mock related to `fetch_top_comments` to reflect the new behavior.

- [ ] **Step 5: Run tests**

```bash
conda run -n base python -m pytest tests/test_scheduler.py tests/test_cdp_collector.py -v
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: implement fetch_top_comments via CDP for top-5 posts per platform"
```

---

### Task 5: Split event detection — social vs news

**Goal:** Run event detection twice — once for social posts, once for news. Store both in EventGroup with a `source` column to distinguish them. Remove _NEWS_EDGE_WEIGHT.

**Files:**
- Modify: `models/schemas.py` — add `source` column to `EventGroup`
- Modify: `models/database.py` — add migration
- Modify: `pipeline/analysis/event_tracker.py` — add `source` parameter, remove _NEWS_EDGE_WEIGHT
- Modify: `api/routes/analysis.py` — call event detection twice
- Modify: `api/routes/collection.py` — call event detection twice
- Modify: `api/routes/dashboard.py` — add `source` filter to event timeline endpoint

- [ ] **Step 1: Add source column to EventGroup**

In `models/schemas.py`, add after `post_count` (line 170):
```python
    # source: "social" = 社媒帖子事件 / "news" = 新闻媒体事件
    source = Column(String, default="social")
```

- [ ] **Step 2: Add migration**

```python
        def _migrate_event_source(sync_conn):
            sync_conn.execute(text(
                "ALTER TABLE event_groups ADD COLUMN source VARCHAR DEFAULT 'social'"
            ))
        try:
            await conn.run_sync(_migrate_event_source)
        except Exception:
            pass
```

- [ ] **Step 3: Modify event_tracker.py**

In `build_keyword_graph` (line 195): remove `_NEWS_EDGE_WEIGHT`, set all posts to weight 1:
```python
w = 1  # All posts equal weight (social and news are separate pipelines now)
```

Delete `_NEWS_EDGE_WEIGHT = 3` constant (line 47).

Modify `detect_events_for_vehicle` to accept `source` parameter:
```python
async def detect_events_for_vehicle(vehicle_id: str, session: AsyncSession, source: str = "social"):
```

Filter posts by source:
```python
# For social: exclude news platform
if source == "social":
    query = query.where(RawPost.platform != "news")
# For news: only news platform
elif source == "news":
    query = query.where(RawPost.platform == "news")
```

When creating EventGroup records, set `source=source`.

- [ ] **Step 4: Update pipeline callers**

In `api/routes/analysis.py`, replace single event detection call with two:
```python
# Social events
events_social = await detect_events_for_vehicle(vehicle_id, session, source="social")
# News events  
events_news = await detect_events_for_vehicle(vehicle_id, session, source="news")
pipeline_phases[vehicle_id]["events_social"] = len(events_social)
pipeline_phases[vehicle_id]["events_news"] = len(events_news)
```

Same in `api/routes/collection.py`.

- [ ] **Step 5: Update dashboard event endpoint**

Add optional `source` query parameter:
```python
@router.get("/vehicles/{vehicle_id}/events")
async def get_event_timeline(
    vehicle_id: str,
    start: str | None = Query(None),
    end: str | None = Query(None),
    source: str | None = Query(None),  # "social" or "news", None = both
    session: AsyncSession = Depends(get_session),
):
```

Filter by source if provided.

- [ ] **Step 6: Run tests**

```bash
conda run -n base python -m pytest tests/test_event_tracker.py -v
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: split event detection into social and news pipelines"
```

---

### Task 6: Frontend cleanup — remove anomaly, add event source filter

**Files:**
- Modify: `frontend/index.html` — remove anomaly section
- Modify: `frontend/static/js/app.js` — remove anomaly code, add source filter to events

- [ ] **Step 1: Remove anomaly HTML**

In `frontend/index.html`, find and remove the anomaly-timeline section div. Bump version query string.

- [ ] **Step 2: Remove anomaly JS**

In `frontend/static/js/app.js`, remove anomaly chart rendering, data fetching, and related state. Bump version query string.

- [ ] **Step 3: Add event source filter**

In the events panel, add a toggle or tabs for "社媒事件" / "新闻事件". The events API call should pass `source=social` or `source=news`.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: remove anomaly from frontend, add event source filter"
```

---

### Task 7: Integration verification

**Files:** No new code. Verify pipeline compiles, tests pass, service runs.

- [ ] **Step 1: Run full test suite**

```bash
conda run -n base python -m pytest tests/ -q --tb=no \
  --ignore=tests/test_anomaly_detector.py \
  --ignore=tests/test_anomaly_explainer.py
```

Expected: all pass (known asyncio + network issues excluded).

- [ ] **Step 2: Verify imports**

```bash
conda run -n base python -c "from api.main import app; from pipeline.analysis.analyzer import AnalysisPipeline; from pipeline.scheduler import CollectionScheduler; from pipeline.analysis.batch_runner import BatchAnalysisRunner; print('ALL OK')"
```

- [ ] **Step 3: Restart service**

```bash
# Kill old, start fresh
/c/Users/<you>/Anaconda3/python.exe -m uvicorn api.main:app --host 0.0.0.0 --port 8000 &
```

- [ ] **Step 4: Verify service responds**

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/
```
Expected: `200`

- [ ] **Step 5: Commit (if any final changes)**

---

## Self-Review

1. **Spec coverage:**
   - Task 1: Delete anomaly detection ✅
   - Task 2: Posts API-only ✅
   - Task 3: Comments local ABSA ✅
   - Task 4: fetch_top_comments implemented ✅
   - Task 5: Events split social/news ✅
   - Task 6: Frontend cleanup ✅
   - Task 7: Integration ✅

2. **Placeholder scan:** No TBD/TODO. All code blocks complete.

3. **Type consistency:** `source` column is VARCHAR default 'social'. EventGroup model, migration, event_tracker, and dashboard endpoint all use consistent naming.
