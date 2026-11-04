# Phase 5: 静默降级显式化 Implementation Plan

> 父 plan: `2026-10-06-audit-fixes-complete.md`

**Goal:** 7 task — 降级状态字段 / ABSA A 方案 / 观点归并 degraded / 最小计数 / confidence / 管线收敛 / 同义归并带后缀。

**Files:**
- `api/routes/dashboard.py` + `analysis.py` + `collection.py`（降级字段）
- `pipeline/analysis/batch_runner.py` + `local_absa.py`（ABSA A 方案）
- `frontend/static/js/app.js` + `index.html`（降级角标）
- `tests/test_degradation_visibility.py`（新增）

## Task 5.1: 端点降级状态字段 + 前端角标
- [ ] **Step 1: 写测试** — `test_defect_judge_failure_returns_degraded`：缺陷簇 LLM 失败返回 `degraded: ["defect_judge"]`
- [ ] **Step 2: 5 处降级点加 `degraded` 字段** — defect_miner.py:257-267 / analysis.py:235-236 / analysis.py:66-67 / batch_runner.py:206-208 / relevance_filter.py:350-355
- [ ] **Step 3: 端点响应结构加 `degraded: []`**
- [ ] **Step 4: 前端加降级角标** — app.js 渲染时检查 `degraded` 数组非空则显示角标
- [ ] **Step 5: 验证 PASS**

## Task 5.2: ABSA A 方案（决策：A 前端提示）
- [ ] **Step 1: 写测试** — `test_overview_comment_model_available`：模型未加载时返回 `comment_model_available: false`
- [ ] **Step 2: 改 `batch_runner.py:336-345`** — 模型未加载时返回标记而非静默 `return 0`
- [ ] **Step 3: 改 `dashboard.py` `/overview`** — 加 `comment_model_available` 字段
- [ ] **Step 4: 前端显示"评论维度数据缺失"占位**
- [ ] **Step 5: 验证 PASS**

## Task 5.3: 观点标签归并失败 degraded
- [ ] **Step 1: 写测试** — `test_opinion_merge_failure_degraded`：归并失败返回 `degraded: true`
- [ ] **Step 2: 改 `analysis.py:235-236`** — 失败时返回 `degraded: true`（当前静默返回未归并 TOP10）
- [ ] **Step 3: 验证 PASS**

## Task 5.4: 观点标签最小计数门槛
- [ ] **Step 1: 写测试** — `test_opinion_min_count`：计数 < 2 不进 TOP 榜
- [ ] **Step 2: 改 `analysis.py:227-234`** — 加 `min_count=2` 过滤
- [ ] **Step 3: 验证 PASS**

## Task 5.5: confidence 阈值过滤（既定设计债）
- [ ] **Step 1: 写测试** — `test_confidence_threshold_filter`：`confidence < 0.3` 不入聚合；`confidence == 0.0` fallback 标记
- [ ] **Step 2: 聚合层加 `confidence >= 0.3` 过滤** — dashboard.py 情感计数/健康分/维度均分
- [ ] **Step 3: `confidence == 0.0` 标记 `fallback: true`**
- [ ] **Step 4: 验证 PASS**
- [ ] **关联 [[review-rounds-complete-2026-10-01]]**

## Task 5.6: /analysis/trigger 管线收敛
- [ ] **Step 1: 写测试** — `test_analysis_trigger_produces_defects_events`：`/analysis/trigger` 后 defect_themes/event_groups 有数据
- [ ] **Step 2: 改 `analysis.py:24-71`** — 加 `detect_events_for_vehicle` + `mine_defect_themes` 调用
- [ ] **Step 3: 验证 PASS**

## Task 5.7: 观点标签同义归并覆盖带后缀（v3 §13.4）
- [ ] **Step 1: 写测试** — `test_opinion_merge_covers_suffix_variants`：`续航长（正面）`→`续航长`
- [ ] **Step 2: 改 `analysis.py` `_merge_opinion_tags` prompt** — 加带后缀形态归并规则
- [ ] **Step 3: 验证 PASS**

## Phase 5 验证
- [ ] 全量 pytest 绿
- [ ] 实测：`/top-opinions` 端点归并效果（验 §13.4）

## Self-Review（3.5 自查）
- ✅ 7 task 覆盖 M4/H2/M1/M6/M5/M2/§13.4
- ⚠️ T5.1 5 处降级点改动分散，需逐个验证不破坏现有行为
- ⚠️ T5.2 ABSA A 方案与 T5.1 降级字段耦合（comment_model_available 也算降级）
- ⚠️ T5.5 confidence 阈值会改变情感分布结果，需对比前后数据
- ⚠️ T5.6 管线收敛后 `/analysis/trigger` 会变慢（多了缺陷/事件计算）
