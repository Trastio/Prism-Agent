# Collection Redesign + Dashboard V5: Fix & Complete

> **STATUS: IN PROGRESS** — 62 files uncommitted, 336 tests GREEN / 11 failing.
> Architecture refactored (platform_strategy, PipelineProgress, layered collection) but tests not updated.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement tasks in parallel. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 11 failing tests, verify collection redesign completeness, and ensure the full pipeline works end-to-end with the new layered architecture.

**Architecture:** The scheduler was refactored from a monolithic `_run_collectors()` to separate `_collect_news()` + `_collect_mc_platform()` methods. `MediaCrawlerWrapper` gained `search_with_comments()` and `search_lightweight()`. `platform_strategy.py` defines per-platform risk profiles. `PipelineProgress` tracks per-platform collection state.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, SQLite, pytest, pytest-asyncio

**Specs:** Based on `collection-redesign` memory + current uncommitted code state.

---

## Root Cause Analysis: 11 Failures

All failures trace to **two root causes** introduced by the scheduler/MC refactoring:

| Root Cause | Symptom | Tests Affected |
|------------|---------|----------------|
| **RC-1: `_run_collectors` removed** | `AttributeError: does not have the attribute '_run_collectors'` | 7 tests: `test_scheduler` (3), `test_collection_api` (3), `test_e2e` (1) |
| **RC-2: `_no_init` missing `_want_comments`** | `AttributeError: 'MediaCrawlerWrapper' object has no attribute '_want_comments'` + wrong subprocess mock target | 4 tests: `test_media_crawler` (4) |

### RC-1 Detail: Scheduler API Change

**Old API** (tests mock this):
```python
# Single method, 3-tuple return
scheduler._run_collectors(keyword, start, end, vehicle_id) → (posts, comments, index_data)
```

**New API** (actual code):
```python
# Separate methods, each with its own scope
scheduler._collect_news(vehicle_id, keywords, start_date, end_date, progress) → posts
scheduler._collect_mc_platform(vehicle_id, platform, keywords, progress) → (posts, comments)
scheduler._import_historical() → (posts, comments)
```

The `collect_vehicle()` main flow is now: `_expand_keywords_if_needed` → `_import_historical` (if initial) → `_collect_news` → `_collect_mc_platform` (for each MC platform) → `_crawl_full_texts` → `_resolve_urls` → `_run_dedup` → `_store_posts` → `_store_comments` → `_store_index_data` → `_update_status`.

### RC-2 Detail: MediaCrawler Test Fixture Issue

1. Tests use `_no_init` to bypass `__init__`, but `_no_init` only sets `_consecutive_failures`, missing `_want_comments`
2. `_run_crawler()` references `self._want_comments` at line 118
3. One test (`test_calls_subprocess_and_reads_results`) patches `asyncio.create_subprocess_exec` but actual code uses `subprocess.run` via `loop.run_in_executor`
4. Tests for `search()` were written for the old subprocess invocation pattern

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `tests/test_scheduler.py` | Update mocks from `_run_collectors` to `_collect_news` + `_collect_mc_platform` |
| Modify | `tests/test_collection_api.py` | Same mock updates for pipeline logic tests |
| Modify | `tests/test_e2e.py` | Same mock updates for end-to-end test |
| Modify | `tests/test_media_crawler.py` | Fix `_no_init`, update subprocess mock targets |

---

### Task 1: Fix `_no_init` fixture in test_media_crawler

**Files:** `tests/test_media_crawler.py`

**Why:** The `_no_init` helper bypasses `__init__` but omits `_want_comments`, `_last_failure_time`, and `_crawler_dir`. Any test that calls `search()` or `_run_crawler()` crashes with `AttributeError`.

**What to do:**
```python
def _no_init(self):
    self._consecutive_failures = {}
    self._last_failure_time = {}          # NEW
    self._want_comments = True            # NEW — _run_crawler reads this
    self._crawler_dir = Path("/tmp")      # NEW — is_available reads this
```

**Verification:** `test_calls_subprocess_and_reads_results` and `test_subprocess_receives_get_comment_true` should no longer crash with `_want_comments` error.

- [ ] Update `_no_init` with `_want_comments`, `_last_failure_time`
- [ ] Verify `TestSearch.test_calls_subprocess_and_reads_results` — also needs subprocess mock fix (see Task 2)
- [ ] Verify `TestSearch.test_subprocess_receives_get_comment_true` — should work once `_want_comments` is present

---

### Task 2: Fix subprocess mock target in test_media_crawler

**Files:** `tests/test_media_crawler.py`

**Why:** `test_calls_subprocess_and_reads_results` patches `asyncio.create_subprocess_exec` but `_run_crawler()` uses `subprocess.run` via `loop.run_in_executor`. The mock doesn't intercept the call, so the test gets an empty result.

**What to do:**
Change the mock from `asyncio.create_subprocess_exec` to `subprocess.run` (matching what `test_subprocess_receives_get_comment_true` already does correctly):

```python
# BEFORE (broken)
with patch("pipeline.collectors.media_crawler.asyncio.create_subprocess_exec", return_value=mock_proc):

# AFTER (correct)
mock_result = MagicMock()
mock_result.returncode = 0
mock_result.stdout = b""
mock_result.stderr = b""
with patch("pipeline.collectors.media_crawler.subprocess.run", return_value=mock_result):
```

Also remove the `AsyncMock()` for `mock_proc.communicate` — that's the old `create_subprocess_exec` pattern.

**Verification:** `test_calls_subprocess_and_reads_results` should return 1 result, not 0.

- [ ] Fix mock in `test_calls_subprocess_and_reads_results`
- [ ] Run `TestSearch` class — all 5 tests should pass

---

### Task 3: Update scheduler mocks in test_scheduler.py

**Files:** `tests/test_scheduler.py`

**Why:** 3 tests in `TestCollectVehicle` mock `_run_collectors` which no longer exists. Need to mock the new individual methods.

**What to do:**

The new `collect_vehicle()` calls these methods in order:
1. `_expand_keywords_if_needed(vehicle)` → `list[str]`
2. `_import_historical()` → `(posts, comments)` — only if `is_available()` and `initial` mode
3. `_collect_news(vehicle_id, keywords, start, end, progress)` → `posts`
4. `_collect_mc_platform(vehicle_id, platform, keywords, progress)` → `(posts, comments)` — for each MC platform
5. `_crawl_full_texts(posts)` → `posts`
6. `_resolve_urls(posts)` → `posts`
7. `_run_dedup(posts)` → `posts`

**For `test_stores_posts`:**
```python
# OLD: single mock
patch.object(s, "_run_collectors", new_callable=AsyncMock, return_value=(mock_posts, [], [])),

# NEW: mock _collect_news + _collect_mc_platform
patch.object(s, "_collect_news", new_callable=AsyncMock, return_value=mock_posts),
patch.object(s, "_collect_mc_platform", new_callable=AsyncMock, return_value=([], [])),
```

**For `test_creates_status_records`:**
```python
# OLD
patch.object(s, "_run_collectors", new_callable=AsyncMock, return_value=([], [], [])),

# NEW
patch.object(s, "_collect_news", new_callable=AsyncMock, return_value=[]),
patch.object(s, "_collect_mc_platform", new_callable=AsyncMock, return_value=([], [])),
```

**For `test_dedup_by_url`:**
```python
# OLD
patch.object(s, "_run_collectors", new_callable=AsyncMock, return_value=(posts, [], [])),

# NEW
patch.object(s, "_collect_news", new_callable=AsyncMock, return_value=posts),
patch.object(s, "_collect_mc_platform", new_callable=AsyncMock, return_value=([], [])),
```

Note: All three tests already mock `_import_historical` and `_expand_keywords_if_needed`. Those stay as-is.

Note: The `_collect_news` and `_collect_mc_platform` mocks must also handle the `progress` parameter. Since `collect_vehicle` creates a `PipelineProgress` and passes `progress.platforms["news"]` / `progress.platforms[platform]` to these methods, the mocks just need to accept and ignore the extra arg.

**Verification:** `pytest tests/test_scheduler.py` — all 17 tests pass (14 existing + 3 fixed).

- [ ] Update `test_stores_posts` mocks
- [ ] Update `test_creates_status_records` mocks
- [ ] Update `test_dedup_by_url` mocks
- [ ] Run full `test_scheduler.py` — verify 17 passed

---

### Task 4: Update scheduler mocks in test_collection_api.py

**Files:** `tests/test_collection_api.py`

**Why:** 3 pipeline logic tests mock `CollectionScheduler._run_collectors`. Same fix as Task 3.

**What to do:**

For `test_pipeline_collects_and_completes`:
```python
# OLD
patch("pipeline.scheduler.CollectionScheduler._run_collectors", new_callable=AsyncMock, return_value=(
    [{"title": "测试", ...}], [], []
)),

# NEW
patch("pipeline.scheduler.CollectionScheduler._collect_news", new_callable=AsyncMock, return_value=[
    {"title": "测试", "content": "内容", "url": "https://ex.com/1",
     "source": "news", "platform": "news", "published_at": "2026-05-20"},
]),
patch("pipeline.scheduler.CollectionScheduler._collect_mc_platform", new_callable=AsyncMock, return_value=([], [])),
```

For `test_pipeline_handles_collection_error`:
```python
# OLD
patch("pipeline.scheduler.CollectionScheduler._run_collectors", new_callable=AsyncMock, side_effect=Exception("timeout")),

# NEW — make _collect_news throw, _collect_mc_platform not reached
patch("pipeline.scheduler.CollectionScheduler._collect_news", new_callable=AsyncMock, side_effect=Exception("timeout")),
```

For `test_pipeline_deduplicates_posts`:
```python
# OLD
patch("pipeline.scheduler.CollectionScheduler._run_collectors", new_callable=AsyncMock, return_value=(posts, [], [])),

# NEW
patch("pipeline.scheduler.CollectionScheduler._collect_news", new_callable=AsyncMock, return_value=posts),
patch("pipeline.scheduler.CollectionScheduler._collect_mc_platform", new_callable=AsyncMock, return_value=([], [])),
```

**Verification:** `pytest tests/test_collection_api.py` — all 8 tests pass.

- [ ] Update `test_pipeline_collects_and_completes` mocks
- [ ] Update `test_pipeline_handles_collection_error` mocks
- [ ] Update `test_pipeline_deduplicates_posts` mocks
- [ ] Run full `test_collection_api.py`

---

### Task 5: Update scheduler mocks in test_e2e.py

**Files:** `tests/test_e2e.py`

**Why:** The single e2e test mocks `_run_collectors` with a 5-post dataset.

**What to do:**
```python
# OLD
patch("pipeline.scheduler.CollectionScheduler._run_collectors", new_callable=AsyncMock, return_value=(mock_posts, [], [])),

# NEW
patch("pipeline.scheduler.CollectionScheduler._collect_news", new_callable=AsyncMock, return_value=mock_posts),
patch("pipeline.scheduler.CollectionScheduler._collect_mc_platform", new_callable=AsyncMock, return_value=([], [])),
```

Note: This test already mocks `_import_historical`, `_crawl_full_texts`, `_resolve_urls`, `_run_dedup`, `_expand_keywords_if_needed`, and the batch runner. Those all stay as-is.

**Verification:** `pytest tests/test_e2e.py` — 1 test passes.

- [ ] Update `test_full_e2e_pipeline` mocks
- [ ] Run full `test_e2e.py`

---

### Task 6: Full test suite verification

**Files:** None (verification only)

**What to do:**
Run the complete test suite and confirm all 351 tests pass (or 350+ with known acceptable exclusions).

```bash
python -m pytest tests/ -v --tb=short
```

**Acceptance criteria:**
- 0 failures
- The `OSError: could not get source code` errors in fixtures are pytest-asyncio teardown warnings, not test logic failures — these are acceptable
- All `passed` counts match or exceed 351

- [ ] Run `pytest tests/ -v` — confirm 0 failures
- [ ] Document final test count

---

## Dependency Graph

```
Task 1 (fix _no_init)
  └─→ Task 2 (fix subprocess mock) — depends on Task 1's _want_comments fix

Task 3 (fix test_scheduler) — independent of Tasks 1-2
Task 4 (fix test_collection_api) — independent of Tasks 1-2
Task 5 (fix test_e2e) — independent of Tasks 1-2

Task 6 (full verification) — depends on ALL above
```

**Parallelizable:** Tasks 1+2 can run together. Tasks 3, 4, 5 are fully independent and can run in parallel. Task 6 is the final gate.

**Suggested subagent assignment:**
- **Agent A:** Task 1 + Task 2 (media_crawler tests — same file)
- **Agent B:** Task 3 (test_scheduler)
- **Agent C:** Task 4 + Task 5 (test_collection_api + test_e2e — same pattern)
- **Agent D (after A/B/C):** Task 6 (full verification)

---

## Scope Exclusions

- **NOT in scope:** Event extraction Volume-first redesign (separate future phase)
- **NOT in scope:** Collector Extensions (Anspire, toutiao/google index — DEFERRED)
- **NOT in scope:** New feature development — only fixing existing refactored code
- **NOT in scope:** Frontend changes — already committed in working tree
