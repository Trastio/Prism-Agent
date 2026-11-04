# Phase 3: 收敛层口径统一（大改）Implementation Plan

> 父 plan: `2026-10-06-audit-fixes-complete.md`
> 本 Phase 是大改，风险最高，口径回归测试兜底。

**Goal:** H1 时区 + 统一查询构造器 + 12 端点口径补齐 + 时间窗 helper + 口径回归测试。

**Files:**
- `api/query_scopes.py`（新增）
- `api/routes/dashboard.py`（H1 + 12 端点）
- `api/routes/analysis.py`（`/sentiment-summary` / `/top-events`）
- `pipeline/analysis/heat_calculator.py`（与 Phase 2 T2.1 协同）
- `tests/test_caliber_regression.py`（新增，口径回归）

## Task 3.1: H1 缺陷簇缓存时区
- [ ] **Step 1: 写测试** — `test_defect_cache_hit_after_tz_fix`：computed_at UTC 与 datetime.utcnow() 比较命中缓存
- [ ] **Step 2: 改 `dashboard.py:1589`** — `datetime.now()` → `datetime.utcnow()`
- [ ] **Step 3: 全库排查** — grep `func.now()` 列与 `datetime.now()` 混用比较的位置
- [ ] **Step 4: 验证 PASS + 与 T2.7 window 字段协同**

## Task 3.2: 新增 scoped_posts 构造器
- [ ] **Step 1: 写测试** — `test_scoped_posts_default_caliber` / `test_scoped_posts_with_time_window`
- [ ] **Step 2: 新建 `api/query_scopes.py`**：
```python
from models.schemas import RawPost, LISTING_CALIBER
from sqlalchemy import select, func
from datetime import datetime, timedelta

def scoped_posts(vehicle_id: str, caliber: tuple = LISTING_CALIBER, *,
                 start: str | None = None, end: str | None = None) -> select:
    stmt = select(RawPost).where(RawPost.vehicle_id == vehicle_id, *caliber)
    if start:
        stmt = stmt.where(func.coalesce(RawPost.published_at, RawPost.collected_at) >= datetime.fromisoformat(start))
    if end:
        stmt = stmt.where(func.coalesce(RawPost.published_at, RawPost.collected_at) < datetime.fromisoformat(end) + timedelta(days=1))
    return stmt
```
- [ ] **Step 3: 验证 PASS**

## Task 3.3: 12 端点改用构造器
- [ ] **Step 1: 改 `/overview` 舆情总量** — 改 `analyzed_total` 或显式标注"相关声量"（v3 实测星愿差 23%）
- [ ] **Step 2: 改 `/comment-sentiment-diff`** — `dashboard.py:994` 硬编码改 `AUTHENTIC_AUTHOR`
- [ ] **Step 3: 改 `/platform-distribution`、`/event-distribution`** — 补 SELF/AUTH
- [ ] **Step 4: 改 `/sentiment-summary`、`/top-events`** — `analysis.py:112,137` 补 LISTING_CALIBER
- [ ] **Step 5: 改 `/overview` 峰值日** — `dashboard.py:157` 加 SELF_ONLY
- [ ] **Step 6: 改 `heat_calculator`** — 用 scoped_posts（与 Phase 2 T2.1 协同）
- [ ] **Step 7: 验证各端点测试 PASS**

## Task 3.4: 时间窗 helper
- [ ] **Step 1: 写测试** — `test_time_window_filter_coalesce`
- [ ] **Step 2: `api/query_scopes.py` 加 `time_window_filter(start, end)`** — 返回 coalesce 条件列表
- [ ] **Step 3: 7 端点裸比较替换** — `/platform-distribution`、`/sentiment-trend`、`/dim-sentiment`、`/dim-examples`、`reports.py`、`/negative-radar`
- [ ] **Step 4: 验证 PASS**

## Task 3.5: 口径回归测试
- [ ] **Step 1: 写 `tests/test_caliber_regression.py`** — 对 25 端点断言 SQL 已挂 LISTING_CALIBER（或显式豁免）
- [ ] **Step 2: 跑测试，修复漏挂**
- [ ] **Step 3: 验证全 PASS**

## Phase 3 验证
- [ ] 全量 pytest 绿
- [ ] 实测：连续两次请求 `/defect-themes` 第二次命中缓存（验 H1）
- [ ] 实测：`/overview` 总量与环图合计对得上（验 H3）

## Self-Review（3.5 自查）
- ✅ 5 task 覆盖 H1 + 6.3 + M3 + L1/L2
- ⚠️ T3.1 与 T2.7 必须协同生效（时区+window 字段）
- ⚠️ T3.3 改 12 端点，每端点行为可能变化，需逐个验证
- ⚠️ T3.5 回归测试是兜底，必须覆盖所有 25 端点
- ⚠️ `/overview` 舆情总量改 `analyzed_total` 是语义变更，需前端同步（与 Phase 4 T4.1 无数据语义耦合）
- 收敛判断：v3 自查无新增问题，可进执行
