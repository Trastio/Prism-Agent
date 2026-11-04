# 刷新/采集/全车采集互斥 Implementation Plan

> REQUIRED SUB-SKILL: subagent-driven-development
> 方案：`docs/刷新采集互斥方案-2026-10-07.md`（v2）

**Goal:** D1 按钮完整互斥 + D2 /api/fleet/status 跨会话恢复 + D3 already_running 区分

## Task 1: 后端 GET /api/fleet/status

**Files:** api/routes/fleet.py + tests/test_fleet_status.py

- [ ] **Step 1: 写测试** `tests/test_fleet_status.py`
  - test_fleet_status_无运行：全 is_running=False → is_running=false
  - test_fleet_status_有运行：1 车 is_running=True lock_acquired_at=now → in_progress_count=1
  - test_fleet_status_脏锁不计入：is_running=True 但 lock_acquired_at 超 30min → 不计入
- [ ] **Step 2: 验证 FAIL**
- [ ] **Step 3: fleet.py 新增 GET /status**（方案 v2 D2 代码，补导入 and_/CollectionStatus/pipeline_phases/datetime/timedelta + 脏锁容错 30min）
- [ ] **Step 4: 验证 PASS + commit**

## Task 2: 前端按钮互斥（D1）

**Files:** frontend/index.html

- [ ] **Step 1: 采集按钮 disabled 加 fleetCollecting**
- [ ] **Step 2: 刷新按钮 disabled 加 fleetCollecting**
- [ ] **Step 3: 全车按钮 disabled 加 loading || refreshing（反向，P2-1）**
- [ ] **Step 4: commit**

## Task 3: 前端 _restoreFleetState（D2）

**Files:** frontend/static/js/app.js

- [ ] **Step 1: 新增 _restoreFleetState 方法**（方案 v2 D2 代码：silent 调 /status + 设 fleetCollecting + fleetStartTime=Date.now() + _startFleetPolling）
- [ ] **Step 2: mounted 末尾调 _restoreFleetState**
- [ ] **Step 3: commit**

## Task 4: 前端 already_running 区分（D3）

**Files:** frontend/static/js/app.js

- [ ] **Step 1: triggerRefreshEngagement already_running 分支**（方案 v2 D3 代码：查 /status + in_progress_count>=2 判 fleet + 区分提示）
- [ ] **Step 2: commit**

## Task 5: 验证与归档

- [ ] **Step 1: 全量 pytest 绿**
- [ ] **Step 2: 实测全车采集时刷新按钮禁用**
- [ ] **Step 3: 实测刷新页面后 fleetCollecting 恢复**
- [ ] **Step 4: /simplify**
- [ ] **Step 5: /code-review**
- [ ] **Step 6: /opsx:archive**

## Self-Review（3.5 自查）

- ✅ 方案 v2 审查修正收敛，5 P1 全修
- ✅ P1-2 脏锁容错对齐 collection.py:169-173
- ✅ P1-3 fleetStartTime 必须设（否则 _pollFleet 首轮判超时）
- ✅ P2-1 反向禁用（全车按钮单车活动时也禁用）
- ✅ P2-2 单一真相源（D3 复用 /status，collection.py 无改动）
- ✅ P2-3 阈值 >= 2 台判 fleet
- ✅ P2-5 删 ETA（无数据源）
- ⚠️ T1 fleet.py 需补导入（P1-1）
- 收敛判断：v2 方案已收敛，plan 可进执行
