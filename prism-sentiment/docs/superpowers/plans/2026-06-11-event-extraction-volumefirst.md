# Event Extraction: Volume-first Redesign

> **STATUS: IN PROGRESS**
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Replace Post-first event detection (`is_event` + DBSCAN) with Volume-first approach (dimension volume → spike detection → event summarization). This fixes the fundamental architectural error: treating events as single-post attributes when they are temporal phenomena.

**Architecture:**
- **Before:** Post → LLM judges `is_event(Y/N)` → cluster `is_event=true` posts by tag via DBSCAN → EventGroup
- **After:** Post → LLM classifies `event_tags` + `opinion_tags` + `dim_sentiment` → aggregate daily volume per tag → detect volume spikes → EventGroup from spike periods

**Key insight from memory:** The building blocks already exist (`dim_sentiment`, `heat_calculator`, `anomaly_detector`). We need to adjust the flow order, not build new components.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, SQLite, sklearn DBSCAN (kept for time clustering within spikes)

---

## Root Problem Analysis

### Why Post-first fails

1. **`is_event` is architecturally wrong** — "事件是时间维度现象，不是单条帖子属性" (from memory). A recall event is not a property of post #42 — it's a pattern visible only when 50 posts about recalls cluster in time.

2. **17 tags conflate 3 categories:**
   - Real Events (temporal): 召回, 降价/促销, 新车发布, 交付延迟, 安全事故, OTA升级
   - Ongoing Topics: 质量问题, 续航争议, 充电问题, 售后服务, 4S店纠纷
   - User behaviors: 提车分享, 维权投诉, 政策法规, 行业动态

3. **LLM forced to guess** — judging `is_event` on a single post without temporal context. The 60-70% calibration mentioned in the prompt is a hack.

4. **DBSCAN doesn't help** — With `is_event` already noisy, clustering noisy data by time makes it worse. Memory notes: "EventGroup 全部集中在 2026-05-31（一天内聚类），DBSCAN eps=7天 没发挥作用"

### Why Volume-first works

- **Events emerge from patterns**, not individual posts. A recall event = a spike in `召回`-tagged post volume.
- **Already have the data**: `dim_sentiment` (15 dimensions from local model), `event_tags` (from API), `heat_calculator` (daily volumes).
- **Aligns with academic literature**: ACE2005 defines events as "a change of state" requiring temporal context. Standard NLP event detection = data → features → classification → visualization.

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `pipeline/analysis/analyzer.py` | Remove `is_event` from prompts and output handling |
| Rewrite | `pipeline/analysis/event_tracker.py` | Volume-first: aggregate per-tag daily volume → detect spikes → cluster posts within spike periods → EventGroup |
| Modify | `pipeline/analysis/anomaly_explainer.py` | Remove `is_event == True` query dependency |
| Modify | `pipeline/analysis/anomaly_detector.py` | Use per-tag volume for better reason generation |
| Modify | `models/schemas.py` | Mark `is_event` / `event_description` as deprecated (keep columns for backward compat) |
| Modify | `tests/test_analyzer.py` | Remove `is_event` assertions, update parse tests |
| Modify | `tests/test_event_tracker.py` | Rewrite for volume-first logic |
| Modify | `tests/test_anomaly_explainer.py` | Remove `is_event` dependency |
| Add | `tests/test_volume_tracker.py` | New tests for volume spike detection |

---

### Task 1: Simplify analyzer.py — remove `is_event` from LLM prompts

**Files:** `pipeline/analysis/analyzer.py`

**Why:** The LLM should not be asked to judge `is_event` on a single post. It should classify the post into event_tags and opinion_tags, and provide dim_sentiment. Whether something is "an event" will be determined downstream by volume analysis.

**What to do:**

1. Update `COMBINED_ANALYSIS_PROMPT` — remove `is_event` and `event_description` fields from the prompt and expected JSON output. Keep `event_tags`, `opinion_tags`, `sentiment`, `dim_sentiment`, `confidence`.

2. Update `EVENT_ONLY_PROMPT` — remove `is_event` and `event_description`. The dual-model event API should now return just `event_tags`, `opinion_tags`, `confidence`.

3. Update `_parse_response()` and `_parse_event_response()` — remove `is_event` and `event_description` parsing. Return `"is_event": False` as a hardcoded default (for backward compat with stored data).

4. Update `analyze_single()` — in the merged result, always set `"is_event": False` and `"event_description": ""`.

5. Update `_fallback_result()` and `_fallback_event_result()` — remove `is_event` field from fallbacks.

**Backward compatibility:**
- `AnalyzedPost.is_event` column stays in DB (SQLite can't drop columns)
- `AnalyzedPost.event_description` column stays in DB
- New data will always have `is_event=False`, `event_description=""`
- Old data with `is_event=True` remains valid — no migration needed

**Verification:** Existing `test_analyzer.py` tests should still pass after updating assertions.

- [ ] Update COMBINED_ANALYSIS_PROMPT — remove is_event/event_description
- [ ] Update EVENT_ONLY_PROMPT — remove is_event/event_description
- [ ] Update _parse_response — remove is_event parsing
- [ ] Update _parse_event_response — remove is_event parsing
- [ ] Update analyze_single — hardcode is_event=False
- [ ] Update fallbacks
- [ ] Run tests/test_analyzer.py — verify passing

---

### Task 2: Rewrite event_tracker.py — Volume-first architecture

**Files:** `pipeline/analysis/event_tracker.py`

**Why:** This is the core of the redesign. Instead of clustering `is_event=true` posts, we:
1. Aggregate daily volume per event_tag
2. Detect volume spikes per tag (using rolling average + threshold)
3. For each spike, cluster the contributing posts by time (DBSCAN still useful here)
4. Create EventGroup from each spike cluster

**What to do:**

```python
# New architecture:

async def detect_events_for_vehicle(vehicle_id: str, session: AsyncSession):
    """Volume-first event detection.
    
    1. Load all analyzed posts with event_tags
    2. Group posts by tag × date → daily volume per tag
    3. For each tag, detect spikes (volume > rolling_avg * spike_factor)
    4. For each spike period, cluster posts by time using DBSCAN
    5. Create EventGroup for each cluster
    """

# Key parameters:
SPIKE_FACTOR = 2.0        # volume must be 2x the rolling average
MIN_SPIKE_VOLUME = 3       # minimum posts on spike day
ROLLING_WINDOW_DAYS = 7    # baseline window
MIN_CLUSTER_SIZE = 2       # DBSCAN min_samples within spike
```

**Implementation steps:**

1. `_aggregate_tag_volumes(posts)` → `dict[tag, dict[date, int]]`
   - For each post, parse event_tags and count posts per tag per date
   - Also include posts WITHOUT event_tags in a "general" bucket

2. `_detect_spikes(tag_volumes, spike_factor, min_volume, window)` → `list[SpikeEvent]`
   - For each tag's time series, compute rolling average over `window` days
   - A spike day is when volume > max(rolling_avg * spike_factor, min_volume)
   - Merge adjacent spike days into spike periods
   - Return SpikeEvent(tag, start_date, end_date, spike_volume, baseline_volume)

3. `_collect_spike_posts(posts, spike)` → `list[dict]`
   - Gather all posts matching the spike's tag AND date range

4. `_cluster_posts_by_time(posts, eps_days=3)` → `list[list[dict]]`
   - Use DBSCAN on timestamps to sub-cluster within the spike period
   - eps=3 days (events may span a few days)

5. `_make_event_group(cluster, tag)` → `EventGroup`
   - Create EventGroup from the cluster
   - summary: LLM-generated from top posts (or use existing `representative_desc` from most-liked post)
   - sentiment_distribution: aggregate from cluster members

6. `detect_events_for_vehicle()` orchestrates the above

**Deprecation:**
- Old `cluster_events()` function kept with deprecation warning for backward compat
- Old `cluster_events_for_vehicle()` calls new `detect_events_for_vehicle()` internally

**Verification:** Write `tests/test_volume_tracker.py` with unit tests for each step.

- [ ] Implement `_aggregate_tag_volumes`
- [ ] Implement `_detect_spikes`
- [ ] Implement `_collect_spike_posts`
- [ ] Implement `_cluster_posts_by_time`
- [ ] Implement `_make_event_group`
- [ ] Implement `detect_events_for_vehicle`
- [ ] Deprecation wrappers for old API
- [ ] Write `tests/test_volume_tracker.py`

---

### Task 3: Update anomaly_explainer.py — remove is_event dependency

**Files:** `pipeline/analysis/anomaly_explainer.py`

**Why:** `_query_top_post_default()` queries `AnalyzedPost.is_event == True` which will always return None with new data.

**What to do:**

1. In `_query_top_post_default()`:
   - Remove `AnalyzedPost.is_event == True` filter
   - Instead, get the top post by engagement on that date (most impactful post regardless of is_event)
   - Use event_tags to enrich the description

2. Keep the function signature unchanged (backward compat for tests)

**Verification:** `tests/test_anomaly_explainer.py` should still pass.

- [ ] Update `_query_top_post_default` — remove is_event filter, use engagement ranking
- [ ] Verify `test_anomaly_explainer.py` passes

---

### Task 4: Update tests for new architecture

**Files:** `tests/test_analyzer.py`, `tests/test_event_tracker.py` (if exists), new `tests/test_volume_tracker.py`

**What to do:**

1. `tests/test_analyzer.py`:
   - Update `test_parse_full_json` — remove `is_event` assertion
   - Update `test_parse_non_event` — remove `is_event` assertion (now always False)
   - Update `test_event_post` / `test_non_event_post` — adjust assertions
   - Update fallback tests — `is_event` always False

2. `tests/test_volume_tracker.py` (NEW):
   - `test_aggregate_tag_volumes` — verify per-tag-per-date counting
   - `test_detect_spikes_basic` — verify spike detection with known data
   - `test_detect_spikes_no_spike` — flat volume returns no spikes
   - `test_merge_adjacent_spikes` — adjacent spike days merged
   - `test_cluster_posts_by_time` — DBSCAN sub-clustering within spike
   - `test_detect_events_for_vehicle_integration` — full pipeline with mock DB

**Verification:** All tests pass.

- [ ] Update test_analyzer.py
- [ ] Create test_volume_tracker.py
- [ ] Full test suite green

---

### Task 5: Update API routes if needed

**Files:** `api/routes/dashboard.py`, `api/routes/analysis.py`

**Why:** Some dashboard endpoints may reference `is_event` or old EventGroup fields.

**What to do:**
- Search for `is_event` usage in API routes
- Update any queries that filter by `is_event == True`
- Ensure EventGroup API responses still work (schema unchanged — EventGroup fields are tag-based, not is_event-based)

**Verification:** `tests/test_dashboard_api.py` passes.

- [ ] Search and update `is_event` references in API routes
- [ ] Verify dashboard API tests

---

## Dependency Graph

```
Task 1 (analyzer prompt) ──→ Task 4 (test updates)
Task 2 (event_tracker)  ──→ Task 4 (test updates)
Task 3 (anomaly_explainer) ──→ Task 4 (test updates)
Task 5 (API routes)      ──→ Task 4 (test updates)
```

**Parallelizable:** Tasks 1, 2, 3, 5 are independent code changes. Task 4 depends on all of them.

**Suggested subagent assignment:**
- **Agent A:** Task 1 (analyzer.py prompt changes)
- **Agent B:** Task 2 (event_tracker.py rewrite — largest task)
- **Agent C:** Task 3 + Task 5 (anomaly_explainer + API routes — smaller changes)
- **Agent D (after A/B/C):** Task 4 (test updates — needs all code changes done)

---

## Scope Exclusions

- **NOT in scope:** Data migration (old `is_event=True` data stays as-is)
- **NOT in scope:** Frontend changes (EventGroup API schema unchanged)
- **NOT in scope:** LLM event summarization within EventGroup (keep existing `representative_desc` approach)
- **NOT in scope:** New event_tag taxonomy (keep existing 17 tags, just reclassify usage)
