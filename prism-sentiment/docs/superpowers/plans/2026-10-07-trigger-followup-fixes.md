# 触发链路收尾修复 Implementation Plan

> **For agentic workers:** 本 change 极小（2 行代码），显式决策 **inline 执行**（主会话直接改，标注 inline，不派子代理——开销不成比例）。

**Goal:** 消除 refresh already_running 面板卡死 + EventGroup.keywords 顺序确定性。

**Architecture:** 两处独立小修：前端 1 行（already_running 分支复位 phase），后端 1 行（set → sorted）。

**Tech Stack:** Vue3 JS / Python / pytest

**OpenSpec:** `openspec/changes/trigger-followup-fixes/`

---

## Task 1: refresh already_running 面板卡死修复

**Files:**
- Modify: `frontend/static/js/app.js:1301`（triggerRefreshEngagement already_running 分支首行）

- [ ] **Step 1: 复位 pipelinePhase**

现状（app.js:1300-1311）：
```javascript
            if (data.status === "already_running") {
                this.pipelinePhase = data.phase;
                // D3：查 /status 区分单车/全车（单一真相源，P2-2）
                const st = await this.apiFetch("/api/fleet/status", { silent: true });
```
改为：
```javascript
            if (data.status === "already_running") {
                // 复位预置的 "refreshing"（不覆盖成真实 phase——本分支提前 return 无轮询，
                // 真实 phase 会命中 showCollectPanel 致面板+状态点卡死）
                this.pipelinePhase = "";
                // D3：查 /status 区分单车/全车（单一真相源，P2-2）
                const st = await this.apiFetch("/api/fleet/status", { silent: true });
```

- [ ] **Step 2: Commit**

```bash
git add frontend/static/js/app.js
git commit -m "fix(frontend): refresh already_running 复位 pipelinePhase 消除面板卡死

already_running 分支提前 return（原语义保留）但覆盖了 pipelinePhase，
真实 phase 命中 showCollectPanel 且无轮询复位 → 面板+状态点卡死。
复位为 ''（与 collect 侧不同法：refresh 终态 handler 文案语义 + 守卫缺口
不允许保持轮询，见 openspec trigger-followup-fixes design D1）。

OpenSpec: trigger-followup-fixes (P1)"
```

## Task 2: event keywords 确定性

**Files:**
- Modify: `pipeline/analysis/event_tracker.py:353`（assemble_events）

- [ ] **Step 1: set → sorted**

现状（event_tracker.py:343,353）：
```python
            event_keywords = set()
            for p in group:
                for kw in p.get("topic_keywords", []):
                    event_keywords.add(kw)
```
和：
```python
                "keywords": list(event_keywords),
```
改：
```python
                "keywords": sorted(event_keywords),
```

- [ ] **Step 2: 跑 event_tracker 测试**

```bash
PYTHONPATH=. python -m pytest tests/test_volume_tracker.py tests/test_defect_miner.py -q
```
Expected: PASS（keywords 断言均为内容断言非顺序断言——T2 前先 grep 确认无顺序依赖断言）。

- [ ] **Step 3: Commit**

```bash
git add pipeline/analysis/event_tracker.py
git commit -m "fix(events): EventGroup.keywords 顺序确定性（set 迭代序→sorted）

assemble_events 的 keywords 收集用 set，list(set) 迭代序随进程哈希摆动，
落库 payload 顺序不稳定。sorted 给稳定序（内容不变）。

OpenSpec: trigger-followup-fixes (P2)"
```

## Task 3: 验证与归档

- [ ] T3.1 全量 pytest（inline 跑）
- [ ] T3.2 code review 子代理（覆盖 2 commit）
- [ ] T3.3 verification
- [ ] T3.4 archive + memory

---

## Self-Review（3.5 自查）

1. **Spec coverage**: refresh-phase-reset 1 条 → Task 1；event-keywords-determinism 1 条 → Task 2 ✅
2. **Placeholder scan**: 无 ✅
3. **顺序依赖断言核查**（T2 风险点）: 实施时先 grep test_volume_tracker/test_defect_miner 的 keywords 断言——若存在顺序断言（如 `keywords[0] ==`）需评估。已知 test_volume_tracker.py L147 `tags = {e["event_tag"] for e in events}` 是 set 比较（顺序无关）；test_detects_events_from_posts L133 断言 event_tag 非空（无关顺序）✅
4. **collect 侧对照**: triggerCollection already_running 分支已修（保持轮询），本 Task 1 只动 refresh 侧，两侧行为差异已定调（design D1）✅
5. **pipelinePhase="" 副作用核查**: showCollectPanel 不命中（面板隐藏）✅；index.html:50 `v-if="pipelinePhase === 'refreshing'"` 状态点隐藏 ✅；_pollPipeline 不受影响（无轮询在跑）✅
