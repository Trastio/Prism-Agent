# Phase 4: 健康分一致性 Implementation Plan

> 父 plan: `2026-10-06-audit-fixes-complete.md`
> 决策：时间窗有意保留（车队 30 天 vs 单车用户窗），其余 3 处 bug 修

**Goal:** 修无数据语义/上界/门槛 3 处 bug，风险算法保留差异 + 文档说明。

**Files:**
- `api/routes/dashboard.py`（`/overview` + `/fleet-overview`）
- `frontend/static/js/app.js` + `index.html`（判空逻辑，与 Phase 6 T6.4 协同）
- `tests/test_health_score_consistency.py`（新增）

## Task 4.1: 无数据语义统一返 None
- [ ] **Step 1: 写测试** — `test_overview_no_data_returns_none`：`analyzed_total<=0` 时 `/overview` health_score=None（当前返 50）
- [ ] **Step 2: 改 `dashboard.py:88-90`** — `compute_health_score` 调用前加 `if analyzed_total <= 0: health_score = None`
- [ ] **Step 3: 改前端 `index.html:107`** — `{{ overview.health_score || '--' }}` → `{{ overview.health_score != null ? overview.health_score : '--' }}`（与 Phase 6 T6.4 协同）
- [ ] **Step 4: 验证 PASS**

## Task 4.2: 车队补上界
- [ ] **Step 1: 写测试** — `test_fleet_time_window_upper_bound`：未来 published_at 帖不计入车队
- [ ] **Step 2: 改 `dashboard.py:248`** — `>= thirty_ago_dt` → `>= thirty_ago_dt AND < end+1天`
- [ ] **Step 3: 验证 PASS**

## Task 4.3: 单车页加 `<20 insufficient` 门槛
- [ ] **Step 1: 写测试** — `test_overview_insufficient_sample`：`analyzed_total < 20` 显示 `insufficient`
- [ ] **Step 2: 改 `dashboard.py` `/overview`** — 加 `sample_insufficient = analyzed_total < 20`（与车队一致）
- [ ] **Step 3: 验证 PASS**

## Task 4.4: 风险算法保留差异 + 文档说明
- [ ] **Step 1: 改 `dashboard.py:222-224`** — 车队 risk_level 注释明确"简化单因子，与单车页多因子不同"
- [ ] **Step 2: 改 `docs/舆情看板-前端设计.md`** — 文档说明车队 vs 单车风险算法差异
- [ ] **Step 3: 验证**

## Phase 4 验证
- [ ] 全量 pytest 绿
- [ ] 实测：切 7/90 天窗对比单车页与车队同一车系健康分（验 §7.3）

## Self-Review（3.5 自查）
- ✅ 4 task 覆盖 7.3 决策（时间窗有意，其余 bug）
- ⚠️ T4.1 与 Phase 6 T6.4 判空逻辑耦合，必须协同
- ⚠️ T4.3 单车页加门槛后，样本不足的车系健康分不显示——需确认前端有 insufficient 提示
- ⚠️ `compute_health_score` 函数本身不动（保持单一真相源），只在调用方加判断
