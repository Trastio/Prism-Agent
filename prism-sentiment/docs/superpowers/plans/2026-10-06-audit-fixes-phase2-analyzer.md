# Phase 2: 分析层 Implementation Plan

> 父 plan: `2026-10-06-audit-fixes-complete.md`

**Goal:** 修复分析层 8 个问题（热度口径/时间/评论分母/事件切并/同名误并/NULL处理/dim-examples/缺陷TTL/缺陷情感过滤）。

**Files:**
- `pipeline/analysis/heat_calculator.py`（§9.1 口径 + §9.2 时间）
- `api/routes/dashboard.py`（§9.3 评论分母 + §9.4 dim-examples）
- `pipeline/analysis/event_tracker.py`（§9.4 切并/同名/NULL/env化）
- `api/routes/collection.py`（§9.5 DefectTheme window）
- `pipeline/analysis/defect_miner.py`（§9.5 rep_comments 情感过滤）
- `tests/test_analyzer_caliber.py`（新增/扩展）

## Task 2.1: 热度口径加 SELF+AUTH
- [ ] **Step 1: 写测试** — `test_heat_metrics_excludes_competitor_official`：competitor/官方帖不计入 discussion_volume
- [ ] **Step 2: 改 `heat_calculator.py:78,177`** — `where(RELEVANT_ONLY)` → `where(SELF_ONLY, AUTHENTIC_AUTHOR, RELEVANT_ONLY)`
- [ ] **Step 3: 验证 PASS**

## Task 2.2: 热度时间用 coalesce
- [ ] **Step 1: 写测试** — `test_heat_null_published_at_counted`：NULL published_at 用 collected_at 兜底计入
- [ ] **Step 2: 改 `heat_calculator.py:76-78,160,175-178`** — `RawPost.published_at >= start` → `func.coalesce(RawPost.published_at, RawPost.collected_at) >= start`
- [ ] **Step 3: 验证 PASS**

## Task 2.3: 评论情感分母排除未分析
- [ ] **Step 1: 写测试** — `test_comment_sentiment_excludes_unanalyzed`：NULL/`"{}"` dim_sentiment 不计入 neutral，计入 unanalyzed_count
- [ ] **Step 2: 改 `dashboard.py:462-466, 502-509`** — 跳过未分析评论或显式 `unanalyzed_count`
- [ ] **Step 3: 验证 PASS**

## Task 2.4: 事件切/并统一参数（决策：bug，统一）
- [ ] **Step 1: 写测试** — `test_event_split_merge_consistent`：切分阈值=合并阈值
- [ ] **Step 2: 改 `event_tracker.py:48,365`** — 合并阈值 ≤ 切分阈值（统一为 7 天）；参数 env 化（`env_int` 风格与 defect_miner 一致）
- [ ] **Step 3: 验证 PASS**

## Task 2.5: 事件同名误并加判据
- [ ] **Step 1: 写测试** — `test_event_same_name_different_time_not_merged`：同名但时间不重叠不合并
- [ ] **Step 2: 改 `event_tracker.py:383-410`** — 合并判据加时间重叠检查
- [ ] **Step 3: 验证 PASS**

## Task 2.6: 事件 NULL 处理 + /dim-examples 评论加口径
- [ ] **Step 1: 写测试** — `test_event_null_date_skipped` + `test_dim_examples_comment_caliber`
- [ ] **Step 2: 改 `event_tracker.py:280,350`** — NULL 日期跳过（不排 date.min）
- [ ] **Step 3: 改 `dashboard.py:1498-1500`** — `/dim-examples` 评论查询挂 SELF_ONLY+AUTHENTIC_AUTHOR+RELEVANT_ONLY
- [ ] **Step 4: 验证 PASS**

## Task 2.7: DefectTheme 写 window 字段 + TTL 统一（与 Phase 3 H1 合并修）
- [ ] **Step 1: 写测试** — `test_defect_theme_window_written` + `test_defect_ttl_consistent`
- [ ] **Step 2: 改 `collection.py:96`** — 落库时 `window_start=start, window_end=end`
- [ ] **Step 3: 改 `dashboard.py:1574,1590`** — TTL 注释 24h 改实际 6h，或实际改 24h（`21600 → 86400`）
- [ ] **Step 4: 验证 PASS**
- [ ] **注：H1 时区在 Phase 3 T3.1 修，本 task 只修 window 字段 + TTL，两者协同生效**

## Task 2.8: 缺陷 rep_comments 过滤情感
- [ ] **Step 1: 写测试** — `test_defect_rep_comments_filter_sentiment`：rep_comments 取 likes top3 时过滤 sentiment='negative'
- [ ] **Step 2: 改 `defect_miner.py:214`** — 加 `sentiment='negative'` 过滤
- [ ] **Step 3: 验证 PASS**

## Phase 2 验证
- [ ] 全量 pytest 绿
- [ ] Phase 2 commit

## Self-Review（3.5 自查）
- ✅ 8 task 覆盖 §9.1-9.5
- ⚠️ T2.1 与 Phase 3 口径收敛耦合——Phase 3 引入 scoped_posts 后 heat_calculator 也要改，T2.1 先手工加口径，Phase 3 统一重构
- ⚠️ T2.4 切/并统一后，现有事件检测行为变化，需重跑事件检测验证（可能影响 event_groups 数据）
- ⚠️ T2.7 TTL 改 24h 会延长缓存，但 H1 时区不修缓存仍不命中——必须与 Phase 3 T3.1 协同
- ⚠️ T2.5 同名误并判据：时间不重叠 + 帖子集合不重叠才算不同事件
