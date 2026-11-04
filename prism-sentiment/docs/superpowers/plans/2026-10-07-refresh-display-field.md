# 刷新互动数展示字段分离 Implementation Plan

> REQUIRED SUB-SKILL: subagent-driven-development（或 inline）
> 方案：`docs/刷新互动数last_collected_at缺失-方案-2026-10-07.md`（v2 方案 C）

**Goal:** 新增 last_refreshed_at 展示字段，与 last_collected_at 水位线分离

## Task 1: 模型 + 迁移
- [ ] **Step 1: schemas.py CollectionStatus 加 `last_refreshed_at = Column(DateTime)`**
- [ ] **Step 2: database.py migrations 加 `ALTER TABLE collection_status ADD COLUMN last_refreshed_at DATETIME`（幂等）**
- [ ] **Step 3: test_migrations 加幂等用例**
- [ ] **Step 4: 验证 PASS + commit**

## Task 2: 后端
- [ ] **Step 1: 写测试** test_refresh_engagement 加强断言（成功写 last_refreshed_at + 不写 last_collected_at）
- [ ] **Step 2: _run_refresh_pipeline 成功分支写 `last_refreshed_at=datetime.now()`**（当前已回退方案 A，确认无 last_collected_at）
- [ ] **Step 3: /collection-status 端点返回 last_refreshed_at**
- [ ] **Step 4: 验证 PASS + commit**

## Task 3: 前端
- [ ] **Step 1: loadCollectionStatus 显示 `max(last_collected_at, last_refreshed_at)`**（NULL 兼容）
- [ ] **Step 2: _reloadAfterRefresh 补 `this.loadCollectionStatus()`**
- [ ] **Step 3: commit**

## Task 4: 验证与归档
- [ ] **Step 1: 全量 pytest 绿**
- [ ] **Step 2: 实测刷新后"上次采集"更新**
- [ ] **Step 3: /simplify**
- [ ] **Step 4: /code-review**
- [ ] **Step 5: /opsx:archive**

## Self-Review（3.5 自查）
- ✅ last_collected_at 水位线不动（防 P0-1 漏采）
- ✅ last_refreshed_at 专用展示字段
- ✅ 前端 max 兼容 NULL
- ✅ _reloadAfterRefresh 补 loadCollectionStatus（P1-3）
- ⚠️ 迁移幂等（PRAGMA table_info 检查，与 lock_acquired_at 同款）
- 收敛判断：方案 v2 审查收敛，plan 可进执行
