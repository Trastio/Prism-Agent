# Frontend Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix incremental collection buffer window, merge duplicate buttons, and fix platform naming inconsistencies in the frontend.

**Architecture:** Four independent fixes across 3 files (1 backend, 2 frontend). Backend change is TDD with existing test suite. Frontend changes are HTML/JS edits verified by existing backend tests staying green.

**Tech Stack:** Python 3 + pytest (backend), Vue 3 CDN + ECharts (frontend)

---

## Task 1: Add 2-day buffer window to incremental collection

**Files:**
- Modify: `tests/test_scheduler.py:48-55`
- Modify: `pipeline/scheduler.py:347`

**Context:** `_get_date_ranges("incremental", last_collected)` currently sets `start = last_collected`. This misses posts published before the collection timestamp but not yet ingested. We add a 2-day buffer: `start = last_collected - 2 days`.

- [ ] **Step 1: Update the existing test to expect the buffered start date**

In `tests/test_scheduler.py`, change `TestDateRanges.test_incremental_single_range` (line 48-55):

```python
def test_incremental_single_range(self):
    from pipeline.scheduler import CollectionScheduler
    s = CollectionScheduler.__new__(CollectionScheduler)
    last = datetime(2026, 5, 15)
    ranges = s._get_date_ranges("incremental", last)
    assert len(ranges) == 1
    assert ranges[0][0] == "2026-05-13"
    assert ranges[0][1] == date.today().strftime("%Y-%m-%d")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "C:\Users\<you>\Desktop\Agent项目\Vehicle Sentiment Analysis Board" && python -m pytest tests/test_scheduler.py::TestDateRanges::test_incremental_single_range -v`
Expected: FAIL — asserts `"2026-05-13"` but gets `"2026-05-15"`

- [ ] **Step 3: Implement the 2-day buffer in scheduler**

In `pipeline/scheduler.py`, change line 347 from:

```python
        start = last_collected.strftime("%Y-%m-%d") if last_collected else today.strftime("%Y-%m-%d")
```

to:

```python
        buffered = last_collected - timedelta(days=2) if last_collected else today
        start = buffered.strftime("%Y-%m-%d")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "C:\Users\<you>\Desktop\Agent项目\Vehicle Sentiment Analysis Board" && python -m pytest tests/test_scheduler.py::TestDateRanges -v`
Expected: 2 passed

- [ ] **Step 5: Run full scheduler test suite**

Run: `cd "C:\Users\<you>\Desktop\Agent项目\Vehicle Sentiment Analysis Board" && python -m pytest tests/test_scheduler.py -v`
Expected: all passed (16 tests)

- [ ] **Step 6: Commit**

```bash
cd "C:\Users\<you>\Desktop\Agent项目\Vehicle Sentiment Analysis Board"
git add tests/test_scheduler.py pipeline/scheduler.py
git commit -m "fix: add 2-day buffer window to incremental collection start date"
```

---

## Task 2: Remove 「分析」button, keep only 「采集」

**Files:**
- Modify: `frontend/index.html:59`
- Modify: `frontend/static/js/app.js:61-62` (status line), `app.js:698-707` (method)

- [ ] **Step 1: Remove the 「分析」button from HTML**

In `frontend/index.html`, delete line 59 entirely:

```html
            <button @click="triggerAnalysis" :disabled="!currentVehicleId || loading" class="btn">分析</button>
```

- [ ] **Step 2: Remove the "analyzing" status span from HTML**

In `frontend/index.html`, delete line 62:

```html
            <span v-if="pipelinePhase === 'analyzing'" class="pipeline-status">分析中 ({{ pipelineInfo.analyzed || 0 }})...</span>
```

This status is no longer reachable from the frontend since `triggerAnalysis()` is being removed. The backend pipeline still sets this phase internally during execution, but the frontend polling in `_pollPipeline()` maps it to the generic status display via `pipelinePhase = data.phase`. Keep the status span removal — the pipeline progresses through phases fast enough that "analyzing" is transient and the user sees "采集中..." → "计算热度..." → "完成" which is sufficient.

- [ ] **Step 3: Remove `triggerAnalysis()` method from JS**

In `frontend/static/js/app.js`, delete lines 698-707:

```javascript
        async triggerAnalysis() {
            this.loading = true;
            this.pipelinePhase = "analyzing";
            const resp = await fetch(`/api/analysis/trigger/${this.currentVehicleId}`, { method: "POST" });
            const data = await resp.json();
            if (data.status === "already_running") {
                this.pipelinePhase = data.phase;
            }
            this._startPolling();
        },
```

- [ ] **Step 4: Commit**

```bash
cd "C:\Users\<you>\Desktop\Agent项目\Vehicle Sentiment Analysis Board"
git add frontend/index.html frontend/static/js/app.js
git commit -m "ui: remove 分析 button — single 采集 button triggers full pipeline"
```

---

## Task 3: Fix platform abbreviations in all-posts filter

**Files:**
- Modify: `frontend/index.html:357-363`

- [ ] **Step 1: Replace old abbreviations with full platform names**

In `frontend/index.html`, replace the platform `<select>` (lines 357-363) from:

```html
            <select v-model="postsFilter.platform" @change="loadPosts(1)">
                <option value="">全部平台</option>
                <option value="news">新闻</option>
                <option value="xhs">小红书</option>
                <option value="wb">微博</option>
                <option value="dy">抖音</option>
            </select>
```

to:

```html
            <select v-model="postsFilter.platform" @change="loadPosts(1)">
                <option value="">全部平台</option>
                <option value="news">新闻</option>
                <option value="xiaohongshu">小红书</option>
                <option value="weibo">微博</option>
                <option value="douyin">抖音</option>
                <option value="kuaishou">快手</option>
            </select>
```

**Why:** The backend `posts` API endpoint filters by `platform` column which stores full names (`xiaohongshu`, `weibo`, `douyin`, `kuaishou`). The old abbreviations (`xhs`, `wb`, `dy`) only exist in legacy data and are handled via OR queries in the top-posts endpoint — but the generic posts endpoint does not have this OR logic, so the filter returned empty results for new data.

- [ ] **Step 2: Commit**

```bash
cd "C:\Users\<you>\Desktop\Agent项目\Vehicle Sentiment Analysis Board"
git add frontend/index.html
git commit -m "fix: all-posts platform filter uses full names, add kuaishou"
```

---

## Task 4: Add kuaishou tab to hot posts

**Files:**
- Modify: `frontend/index.html:320-325`

- [ ] **Step 1: Add kuaishou button to the tab row**

In `frontend/index.html`, after line 324, add one line. Change from:

```html
        <div class="top-posts-tabs">
            <button class="top-posts-tab" :class="{active: topPostsTab === ''}" @click="switchTopPostsTab('')">全部</button>
            <button class="top-posts-tab" :class="{active: topPostsTab === 'xiaohongshu'}" @click="switchTopPostsTab('xiaohongshu')">小红书</button>
            <button class="top-posts-tab" :class="{active: topPostsTab === 'weibo'}" @click="switchTopPostsTab('weibo')">微博</button>
            <button class="top-posts-tab" :class="{active: topPostsTab === 'douyin'}" @click="switchTopPostsTab('douyin')">抖音</button>
        </div>
```

to:

```html
        <div class="top-posts-tabs">
            <button class="top-posts-tab" :class="{active: topPostsTab === ''}" @click="switchTopPostsTab('')">全部</button>
            <button class="top-posts-tab" :class="{active: topPostsTab === 'xiaohongshu'}" @click="switchTopPostsTab('xiaohongshu')">小红书</button>
            <button class="top-posts-tab" :class="{active: topPostsTab === 'weibo'}" @click="switchTopPostsTab('weibo')">微博</button>
            <button class="top-posts-tab" :class="{active: topPostsTab === 'douyin'}" @click="switchTopPostsTab('douyin')">抖音</button>
            <button class="top-posts-tab" :class="{active: topPostsTab === 'kuaishou'}" @click="switchTopPostsTab('kuaishou')">快手</button>
        </div>
```

No JS changes needed — `switchTopPostsTab()` already passes the value to `loadTopPosts()` which sends it as the `platform` query param. The backend top-posts endpoint handles kuaishou via OR query (matches both `kuaishou` and `ks`). `platformLabel('kuaishou')` already maps to `"快手"` in the existing `platformLabel` function (app.js:744).

- [ ] **Step 2: Commit**

```bash
cd "C:\Users\<you>\Desktop\Agent项目\Vehicle Sentiment Analysis Board"
git add frontend/index.html
git commit -m "ui: add kuaishou tab to hot posts section"
```

---

## Task 5: Run full test suite for final verification

- [ ] **Step 1: Run all tests**

Run: `cd "C:\Users\<you>\Desktop\Agent项目\Vehicle Sentiment Analysis Board" && python -m pytest tests/ -v --tb=short`
Expected: 404+ passed, 0 failed (the 1 known pytest-asyncio env error is acceptable)

- [ ] **Step 2: Squash or keep commits as-is per team preference**

If squashing is desired:
```bash
git rebase -i HEAD~4
```
Otherwise, the 4 individual commits are fine — each is atomic and self-contained.
