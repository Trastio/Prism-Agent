# 前端刷新按钮 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development
> 设计文档：`docs/刷新按钮设计-2026-10-06.md`（v7，五轮审查收敛，含完整代码片段）

**Goal:** 前端刷新按钮（增量采集 + 全车刷新 + 互动刷新 + 前端全组件更新）

**Architecture:** pipeline/frequency.py 抽离 + fleet.py 新建 + collection.py refresh 端点 + 前端按钮/重载/复位钩子

## Task 1: pipeline/frequency.py 抽离 + daily_update 改导入

- [ ] **Step 1: 写测试** `tests/test_frequency.py` — test_tier_of（100/30 + `>`）/ test_select_by_frequency（偶数日 + 周一）/ test_recent_post_counts
- [ ] **Step 2: 验证 FAIL**
- [ ] **Step 3: 新建 pipeline/frequency.py**（照搬 daily_update.py:46-47,54-100 常量+逻辑，设计 v7 §1 代码片段）
- [ ] **Step 4: daily_update.py 改导入**（P1-1 不取别名 + nit-1 删冗余导入）
- [ ] **Step 5: 验证 PASS + commit**

## Task 2: collection.py 基础设施（_PIPELINE_SEM + REFRESHING_PHASES + finally）

- [ ] **Step 1: 加 _PIPELINE_SEM + REFRESHING_PHASES**
- [ ] **Step 2: _run_full_pipeline 改造**（P1-3 保留 finally + P2-4 SEM 包整个 try/finally，设计 v7 §3 代码片段）
- [ ] **Step 3: trigger_collection 判定集加 stale 逃逸**（`phase in REFRESHING_PHASES and not _is_phase_stale`）
- [ ] **Step 4: 验证现有测试不回归 + commit**

## Task 3: fleet.py + main.py 注册

- [ ] **Step 1: 写测试** `tests/test_fleet_collect.py` — test_fleet_collect_frequency（频率分层）/ test_fleet_collect_independent_session
- [ ] **Step 2: 新建 api/routes/fleet.py**（设计 v7 §2 代码片段，每车独立 session）
- [ ] **Step 3: main.py 注册** `from api.routes.fleet import router as fleet_router`（P2-3 对齐既有风格）
- [ ] **Step 4: 验证 PASS + commit**

## Task 4: refresh-engagement 端点

- [ ] **Step 1: 写测试** `tests/test_refresh_engagement.py` — test_refresh_writes_collection_status / test_refresh_success_writes_completed / test_refresh_failure_writes_error / test_refresh_finally_releases_lock
- [ ] **Step 2: 新增 trigger_refresh_engagement**（设计 v7 §3 代码片段，写 CollectionStatus.is_running + lock_acquired_at）
- [ ] **Step 3: 新增 _run_refresh_pipeline**（P1-2 成功/失败写 cs.status + P1-3 finally 复位，设计 v7 §3 代码片段）
- [ ] **Step 4: 验证 PASS + commit**

## Task 5: 前端按钮 + 分级重载

- [ ] **Step 1: index.html** Chrome 栏「刷新互动数」按钮 + refreshing dot + ⋮ 全车采集（设计 v7 §按钮 代码片段）
- [ ] **Step 2: app.js data** 新增 fleetPollTimer/fleetStartedVids/fleetStartTime/refreshing/fleetCollecting（P2-1 只放 data）
- [ ] **Step 3: triggerRefreshEngagement + _reloadAfterRefresh**（分级重载跳过 defect，设计 v7 §前端方法）
- [ ] **Step 4: _pollPipeline 区分 completed/error**（P2-2 error 不走 _onRefreshCompleted）
- [ ] **Step 5: triggerFleetCollect + _startFleetPolling + _pollFleet**（P1-4 容错 + 120min 超时）
- [ ] **Step 6: 验证 + commit**

## Task 6: 口径回归白名单 + 全量测试

- [ ] **Step 1: test_caliber_regression.py 加白名单** /api/fleet/collect + /refresh-engagement
- [ ] **Step 2: 全量 pytest 绿**
- [ ] **Step 3: commit**

## Task 7: 验证与归档

- [ ] **Step 1: 实测单车刷新** → 前端组件更新
- [ ] **Step 2: 实测全车采集** → 复位钩子工作
- [ ] **Step 3: 实测 refresh 失败** → 前端弹失败（非成功）
- [ ] **Step 4: /simplify**
- [ ] **Step 5: /code-review**
- [ ] **Step 6: /opsx:archive**

## Self-Review（3.5 自查）

- ✅ 设计 v7 经五轮审查收敛，无结构性缺口
- ✅ 跨 task 依赖标注（T1→T2→T4，T2→T3）
- ✅ 关键契约对齐：P1-2 DB-first / P1-3 finally / P1-4 null 容错 / P1-C stale 逃逸
- ⚠️ T2 改造 _run_full_pipeline 需回归验证不破坏现有采集（保留 finally + SEM 包全程）
- ⚠️ T4 _run_refresh_pipeline 的 except 块写 cs.status="error" 需独立 session（不能复用已关的 session）
- 收敛判断：v7 设计已收敛，plan 可进执行
