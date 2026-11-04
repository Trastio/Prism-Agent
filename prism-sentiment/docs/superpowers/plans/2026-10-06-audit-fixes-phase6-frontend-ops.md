# Phase 6: 前端 + 运维 Implementation Plan

> 父 plan: `2026-10-06-audit-fixes-complete.md`

**Goal:** 8 task — ECharts 白图 / 竞态 / 历史报告 / openFleet / 判空 / 词云 / WAL / DB 锁 / 去重约束 / 安全。

**Files:**
- `frontend/static/js/app.js`（ECharts/竞态/历史报告/openFleet/词云）
- `frontend/static/index.html`（判空/scheme/字段契约）
- `models/database.py`（WAL）
- `models/schemas.py` + `models/database.py`（lock_acquired_at 字段 + 评论唯一约束，迁移）
- `api/routes/collection.py`（DB 锁判据）
- `tests/test_frontend_lifecycle.py` + `tests/test_ops_resilience.py`（新增）

## Task 6.1: ECharts 空↔有数据切换白图修复（8 处）
- [ ] **Step 1: 写测试** — `test_echarts_clear_not_destroy_canvas`：空数据分支不抹掉 canvas
- [ ] **Step 2: 改 `app.js:578-585` 等 8 处** — 空数据分支用 `chart.clear()` 不抹 canvas 子节点，或重渲染前 `chart.dispose()` 旧实例
- [ ] **Step 3: 浏览器实测** — 切零数据车（元UP）→ 切有数据车（星愿），图表正常渲染
- [ ] **Step 4: 验证 PASS**

## Task 6.2: 异步竞态守卫
- [ ] **Step 1: 写测试** — `test_on_vehicle_change_request_id_guard`：旧请求晚回不覆盖新车数据
- [ ] **Step 2: 改 `app.js:522-558`** — `onVehicleChange` 加 requestId，回调比对 requestId 不匹配则丢弃
- [ ] **Step 3: 验证 PASS**

## Task 6.3: 历史报告加载 + openFleet 刷新
- [ ] **Step 1: 改 `app.js` `onVehicleChange`** — 加 `loadReports()` 调用
- [ ] **Step 2: 改 `app.js:1267` `openFleet`** — 去掉 `if (this.fleetOverview.length) return` 或加刷新机制
- [ ] **Step 3: 验证**

## Task 6.4: 判空逻辑 + 词云 resize + 字段契约 + postDetail.url scheme
- [ ] **Step 1: 改 `index.html:107,113`** — `||` → `!= null`（与 Phase 4 T4.1 协同）
- [ ] **Step 2: 改 `app.js:341-345`** — 修复 `wordCloudChart` 赋值
- [ ] **Step 3: 清理死分支字段** — 前端读后端不返回的 `positive_pct` 等，或后端补返回
- [ ] **Step 4: 改 `index.html:577`** — `postDetail.url` 过滤 `javascript:` 伪协议
- [ ] **Step 5: 验证**

## Task 6.5: SQLite 启用 WAL
- [ ] **Step 1: 写测试** — `test_wal_enabled`：DB journal_mode=WAL
- [ ] **Step 2: 改 `models/database.py:8`** — 加 `PRAGMA journal_mode=WAL`（aiosqlite connect 钩子或事件监听）
- [ ] **Step 3: 验证 PASS**

## Task 6.6: DB 锁脏锁判据修复（task GC 延伸）
- [ ] **Step 1: 加 `lock_acquired_at` 字段** — `models/schemas.py` CollectionStatus + 迁移
- [ ] **Step 2: 写测试** — `test_lock_expired_by_acquired_time`：加锁时刻超 30min 视为过期
- [ ] **Step 3: 改 `collection.py:152-158`** — 判据从 `last_collected_at` 改 `lock_acquired_at`
- [ ] **Step 4: 改 `trigger_collection`** — 设 `lock_acquired_at=now`（加锁时）
- [ ] **Step 5: 验证 PASS**

## Task 6.7: 评论去重 DB 唯一约束
- [ ] **Step 1: 迁移加 `UNIQUE(post_id, cid)`** — `models/database.py` 迁移
- [ ] **Step 2: 加指纹兜底唯一索引** — `UNIQUE(post_id, author, substr(content,1,200))`
- [ ] **Step 3: 验证现有数据无冲突** — 查重后加约束
- [ ] **Step 4: 验证**

## Task 6.8: 安全（条件性）
- [ ] **Step 1: 文档说明 `HOST=0.0.0.0` 风险** — `docs/舆情项目-架构.md`
- [ ] **Step 2: 若开放外网，加鉴权** — 至少对写副作用端点（/collect / /analysis/trigger / reports）
- [ ] **Step 3: 验证**

## Phase 6 验证
- [ ] 全量 pytest 绿
- [ ] 浏览器实测：切车系不白图（验 §11.1）
- [ ] DB 实测：WAL 启用 + 锁判据正确

## Self-Review（3.5 自查）
- ✅ 8 task 覆盖 §11.1-11.3 + L4-L7 + §3.9
- ⚠️ T6.1 ECharts 8 处机械修复，需浏览器实测（Playwright）
- ⚠️ T6.4 判空逻辑与 Phase 4 T4.1 耦合，必须协同
- ⚠️ T6.6/T6.7 DB 迁移需备份
- ⚠️ T6.5 WAL 启用后，DB 文件会有 -wal/-shm，备份策略要调整
- ⚠️ T6.8 安全是条件性，取决于是否开放外网
