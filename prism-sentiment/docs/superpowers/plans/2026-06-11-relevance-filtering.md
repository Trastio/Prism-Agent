# Data Relevance Filtering: Hybrid Rule Engine + LLM

> **STATUS: IN PROGRESS**
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Filter irrelevant posts (wrong-topic, wrong-time, wrong-domain) from collected data using a two-stage pipeline: fast rule-based pre-filter → LLM semantic verification for gray-zone posts.

**Problem:** Keyword search for "海豚" returns animal content, Dolphin emulator, PPT docs. "银河E5" returns car config pages. ~15-28% of collected posts are irrelevant noise that pollutes sentiment analysis and dashboard.

**Architecture:**
```
Collected Posts → Rule Engine (0ms, free) → Pass/Limbo/Reject
                       ↓ Pass                    ↓ Limbo (~200ms, ¥0.0001/条)
                  Store directly          → LLM Relevance Check → Pass/Reject
                                                                    ↓
                                                            Store with relevance_score
```

**Tech Stack:** Python 3.13, GLM-4-Flash API, regex

**Academic backing:**
- CN110633373A: keyword matching → knowledge graph → deep learning (standard automotive sentiment pipeline)
- Springer 2023: data quality must be addressed at collection stage
- PMC 2025: multi-stage filtering (language + ads + irrelevant) is standard practice

---

## Design Decisions

### 1. Where in the pipeline?

**Decision: Post-collection, pre-analysis.** After `collect_vehicle()` stores posts, before `analyze_vehicle()` processes them.

Why:
- Collection should be fast and permissive (don't lose data at collection time)
- Filtering is a data quality concern, best done between collection and analysis
- Already have `analysis_status` field — add `"irrelevant"` status

### 2. New status values

| analysis_status | Meaning |
|-----------------|---------|
| `"pending"` | Not yet filtered or analyzed |
| `"irrelevant"` | Filtered out by relevance checker (skip analysis) |
| `"analyzed"` | Already analyzed |

### 3. Schema change

Add `relevance_score` column to `RawPost`:
- `NULL` — not yet checked
- `1.0` — rule engine passed (high confidence)
- `0.0-0.99` — LLM relevance score
- `0.0` — rejected

### 4. LLM prompt design

Minimize token cost. Use a simple binary classification prompt:

```
判断以下帖子是否与"{vehicle_name}"({brand}品牌{vehicle_type}车型)相关。

相关定义：讨论该车型的性能、质量、购买、使用、售后、市场表现等
不相关：讨论其他同名事物、纯广告、配置参数页、图片集等

标题：{title}
内容摘要：{content[:200]}

回复 JSON: {"relevant": true/false, "confidence": 0.0-1.0}
```

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `pipeline/analysis/relevance_filter.py` | Rule engine + LLM relevance checker |
| Modify | `models/schemas.py` | Add `relevance_score` column |
| Modify | `pipeline/analysis/batch_runner.py` | Skip `irrelevant` posts in analysis |
| Modify | `api/routes/dashboard.py` | Exclude `irrelevant` posts from dashboard queries |
| Modify | `api/routes/analysis.py` | Add relevance check endpoint or auto-run before analysis |
| Create | `tests/test_relevance_filter.py` | Unit tests for both stages |

---

### Task 1: Create relevance_filter.py — Rule Engine + LLM Checker

**Files:** `pipeline/analysis/relevance_filter.py` (NEW)

**Components:**

1. **`VehicleProfile` dataclass:**
   ```python
   @dataclass
   class VehicleProfile:
       name: str           # e.g. "比亚迪海豚"
       brand: str          # e.g. "比亚迪"
       launch_date: str     # e.g. "2021-08-01"
       vehicle_type: str    # e.g. "纯电两厢车"
       aliases: list[str]   # e.g. ["海豚EV", "Dolphin", "BYD Dolphin"]
   ```

2. **`RuleBasedFilter` class:**
   - `check(post, profile) -> RelevantStatus`
     - Rule 1: published_at before launch_date → REJECT
     - Rule 2: URL matches blacklist patterns (config/picture/image pages) → REJECT
     - Rule 3: title+content matches exclude regex (模拟器, 动物海豚, etc.) → REJECT
     - Rule 4: title+content contains car context keyword → PASS
     - Rule 5: none of the above → LIMBO (needs LLM check)
   - Returns enum: `PASS`, `LIMBO`, `REJECT`

3. **`LLMRelevanceChecker` class:**
   - Uses existing `AnalysisPipeline._call_api()` pattern
   - `check_relevance(post, profile) -> tuple[bool, float]`
   - Batch mode: `check_batch(posts, profile) -> list[tuple[bool, float]]`
   - Uses GLM-4-Flash (cheapest model, sufficient for binary classification)

4. **`RelevanceFilter` orchestrator:**
   - `filter_posts(posts, vehicle, session=None) -> list[dict]`
     - Step 1: Rule engine on all posts → split into pass/limbo/reject
     - Step 2: LLM check on limbo posts
     - Returns posts with `relevance_score` and `analysis_status` set
   - `filter_vehicle(vehicle_id, session) -> dict`
     - Load pending posts from DB, run filter, update DB

**Verification:** Unit tests with synthetic posts covering each rule + LLM mock.

- [ ] Implement VehicleProfile
- [ ] Implement RuleBasedFilter with 5 rules
- [ ] Implement LLMRelevanceChecker
- [ ] Implement RelevanceFilter orchestrator
- [ ] Write test_relevance_filter.py

---

### Task 2: Add relevance_score column to RawPost

**Files:** `models/schemas.py`

**What to do:**
```python
# In RawPost class, add:
relevance_score = Column(Float, nullable=True)
```

SQLite migration: column will be NULL for existing rows (backward compatible).

**Verification:** Existing tests should still pass (nullable column).

- [ ] Add relevance_score column
- [ ] Run existing tests to verify no breakage

---

### Task 3: Update batch_runner to skip irrelevant posts

**Files:** `pipeline/analysis/batch_runner.py`

**What to do:**
In the query that selects posts for analysis, add:
```python
# Current:
RawPost.analysis_status == "pending"

# New:
RawPost.analysis_status == "pending",
RawPost.relevance_score == None,  # not yet filtered OR
```

Actually, simpler approach: the relevance filter will set `analysis_status = "irrelevant"` for rejected posts. The existing `analysis_status == "pending"` filter already excludes them. No change needed in batch_runner if we set the status correctly.

Wait — we need to make sure relevance filtering runs BEFORE analysis. Two options:
1. Auto-run in `batch_runner` before analysis starts
2. Separate endpoint that runs first

**Decision:** Auto-run in `batch_runner.run_for_vehicle()` before the analysis loop.

- [ ] Add relevance filter call at start of `run_for_vehicle()`
- [ ] Ensure `analysis_status == "irrelevant"` posts are skipped

---

### Task 4: Update dashboard queries to exclude irrelevant posts

**Files:** `api/routes/dashboard.py`

**What to do:**
Search for queries that select from `RawPost` and add exclusion:
```python
# Where we query raw_posts for display, exclude irrelevant
RawPost.analysis_status != "irrelevant"
```

Key endpoints to check:
- `/dashboard/overview/{id}` — total posts count
- `/dashboard/top-posts/{id}` — hot posts list
- `/dashboard/posts/{id}` — posts list
- `/dashboard/word-cloud/{id}` — word cloud
- `/dashboard/platform-distribution/{id}` — platform stats

**Verification:** Dashboard API tests should still pass.

- [ ] Add `!= "irrelevant"` filter to dashboard queries
- [ ] Verify dashboard API tests pass

---

### Task 5: Wire relevance filter into the full pipeline

**Files:** `api/routes/analysis.py`

**What to do:**
In the analysis trigger flow, ensure relevance filtering runs before analysis:
```python
async def _run_analysis_pipeline(vehicle_id, ...):
    # Step 1 (NEW): Filter irrelevant posts
    await filter_vehicle_posts(vehicle_id, session)
    # Step 2 (existing): Run analysis
    result = await runner.run_for_vehicle(vehicle_id)
    # Step 3 (existing): Heat + anomaly + events
    ...
```

- [ ] Add filter step to analysis pipeline
- [ ] End-to-end test

---

## Dependency Graph

```
Task 2 (schema) ──→ Task 1 (relevance_filter.py) ──→ Task 3 (batch_runner)
                                              ──→ Task 4 (dashboard)
                                              ──→ Task 5 (pipeline wiring)
```

**Parallelizable:** Tasks 3, 4, 5 are independent once Task 1 is done.

---

## Scope Exclusions

- **NOT in scope:** Re-filtering existing analyzed posts (only filter pending posts going forward)
- **NOT in scope:** Retroactive cleaning of existing data (separate one-time script)
- **NOT in scope:** Changing collection keywords (separate optimization)
