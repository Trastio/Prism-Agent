# Phase 1: 采集层容错 Implementation Plan

> 父 plan: `2026-10-06-audit-fixes-complete.md`

**Goal:** 修复采集层 4 个容错问题（小红书重试风暴 / 扩词固化 / 指数连带 / 锁释放）。

**Files:**
- `pipeline/collectors/tikhub_collector.py`（§8.1 移除 xhs 豁免）
- `pipeline/collectors/keyword_expander.py` + `pipeline/scheduler.py` + `models/schemas.py`（§8.2 扩词失败不固化 + expansion_status 字段 + 迁移）
- `pipeline/scheduler.py`（§8.3 指数拆 try + 全词失败标 error）
- `api/routes/collection.py`（§8.4 is_running 释放移到 finally）
- `tests/test_collector_resilience.py`（新增）

## Task 1.1: 小红书永久 400 停止重试

- [ ] **Step 1: 写测试** — `tests/test_collector_resilience.py` 加 `test_xhs_permanent_400_no_retry`：mock xhs search_notes 返回 400 `code=-1`，验证不重试（_max_attempts=1）
- [ ] **Step 2: 验证 FAIL**
- [ ] **Step 3: 改 `tikhub_collector.py:291`** — 移除 `not endpoint.startswith("xiaohongshu.")` 豁免，所有平台永久 4xx 都不重试
- [ ] **Step 4: 验证 PASS**
- [ ] **Step 5: 提交**

## Task 1.2: 关键词扩展失败不固化 7 天

- [ ] **Step 1: 加 `expansion_status` 字段** — `models/schemas.py` Vehicle 加 `expansion_status: str`（success/failed/未跑）；`models/database.py` 迁移加列
- [ ] **Step 2: 写测试** — `test_keyword_expansion_failure_not_persisted`：LLM 失败时验证不置 `keywords_expanded_at`，`expansion_status='failed'`
- [ ] **Step 3: 改 `keyword_expander.py:82-84`** — 失败时 raise 或返回标记，不返回 `base_keywords` 当成功
- [ ] **Step 4: 改 `scheduler.py:176-181`** — 失败时不置 `keywords_expanded_at=now`，置 `expansion_status='failed'`
- [ ] **Step 5: 改 `scheduler.py:156-160`** — 缓存判据加 `expansion_status='success'` 条件
- [ ] **Step 6: 验证 PASS + 提交**

## Task 1.3: 指数采集拆 try + 全词失败标 error

- [ ] **Step 1: 写测试** — `test_index_collection_isolated_try`：douyin 指数失败时 xhs 指数仍执行；`test_all_keywords_failed_marks_error`：全词失败标 phase=error
- [ ] **Step 2: 改 `scheduler.py:1033-1042`** — 拆为两个独立 try
- [ ] **Step 3: 改 `scheduler.py:958`** — 全词失败（`fetch_failures` 数==总词数）时标 `phase="error"` 而非 `done`
- [ ] **Step 4: 验证 PASS + 提交**

## Task 1.4: is_running 释放移到 finally

- [ ] **Step 1: 写测试** — `test_is_running_released_on_cancel`：task 被 cancel 时 DB 锁释放
- [ ] **Step 2: 改 `collection.py:124-134`** — 释放锁代码移到 `finally` 块（当前在 `async with` 之外）
- [ ] **Step 3: 验证 PASS + 提交**

## Phase 1 验证

- [ ] 全量 pytest 绿
- [ ] Phase 1 commit 链完整

## Self-Review（3.5 自查）

- ✅ 4 task 覆盖 §8.1-8.4
- ⚠️ T1.2 加字段需迁移，备份 DB
- ⚠️ T1.3 全词失败判据：`len(fetch_failures)==len(selected_kw)` 才算全失败
- ⚠️ T1.4 移到 finally 后，正常 completed 路径也要确保释放（不能只异常路径）
