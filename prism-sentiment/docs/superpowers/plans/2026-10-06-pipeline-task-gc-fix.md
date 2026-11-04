# 采集 task GC + 内存 dict 掩盖 DB 状态 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development。Steps use checkbox (`- [ ]`) tracking.

**Goal:** 修复采集 task 被 GC 回收 + `get_pipeline_status` 优先信内存 dict 掩盖 DB 真相的问题。

**Architecture:** `trigger_collection` 持有 task 引用（`_running_tasks` dict + `add_done_callback`）+ `get_pipeline_status` 优先查 DB + 内存 dict 带 30min TTL + `_run_full_pipeline` 更新 `_updated_at`。

**Tech Stack:** Python, FastAPI, asyncio, SQLAlchemy 2.0 async, pytest

**Spec:** `openspec/changes/pipeline-task-gc-fix/`

---

## File Structure

| 文件 | 责任 | 改动类型 |
|---|---|---|
| `api/routes/collection.py` | task 持有引用 + get_pipeline_status DB 优先 + _run_full_pipeline 更新 _updated_at | Modify |
| `api/pipeline_state.py` | `_is_phase_stale` TTL helper | Modify |
| `tests/test_pipeline_task_lifecycle.py` | task 引用/DB 优先/TTL/zombie 清理 | Create |

---

## Task 1: task 持有引用防 GC + 清理

**Files:**
- Modify: `api/routes/collection.py`（`trigger_collection` + 模块级 `_running_tasks`）

- [ ] **Step 1: 写测试**

`tests/test_pipeline_task_lifecycle.py`：

```python
"""Tests: 采集 task 生命周期管理。"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from api.routes.collection import _running_tasks


@pytest.mark.asyncio
async def test_task_held_reference(monkeypatch):
    """触发 collect 后 _running_tasks 持有 task 引用，done 后清理。"""
    # mock _run_full_pipeline 立刻完成
    async def _fake_pipeline(vid):
        await asyncio.sleep(0.05)

    monkeypatch.setattr("api.routes.collection._run_full_pipeline", _fake_pipeline)
    # mock DB 查询返回无锁
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()

    from api.routes.collection import trigger_collection
    # 取一个不存在的 vid（mock 会返回 Vehicle）
    mock_vehicle = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_vehicle)

    await trigger_collection("v-test-hold", mock_session)
    # task 持有
    assert "v-test-hold" in _running_tasks, "task 引用应持有"
    # 等 done
    await asyncio.sleep(0.1)
    assert "v-test-hold" not in _running_tasks, "done 后应清理"


@pytest.mark.asyncio
async def test_zombie_task_cancelled_on_retrigger(monkeypatch):
    """重新触发同车 collect 时取消旧 zombie task。"""
    cancelled = []
    async def _slow_pipeline(vid):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.append(vid)
            raise

    monkeypatch.setattr("api.routes.collection._run_full_pipeline", _slow_pipeline)
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.add = MagicMock()
    mock_vehicle = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_vehicle)

    from api.routes.collection import trigger_collection
    await trigger_collection("v-zombie", mock_session)  # 启动旧 task
    assert "v-zombie" in _running_tasks
    await trigger_collection("v-zombie", mock_session)  # 重新触发应取消旧
    await asyncio.sleep(0.1)
    assert "v-zombie" in cancelled, "旧 task 应被取消"
```

- [ ] **Step 2: 运行验证 FAIL**

Run: `python -m pytest tests/test_pipeline_task_lifecycle.py::test_task_held_reference -v`
Expected: FAIL — `_running_tasks` 不存在（import 失败）。

- [ ] **Step 3: 加 `_running_tasks` + 改 `trigger_collection`**

`api/routes/collection.py` 顶部（router 定义后）加：

```python
# 全局 task 注册表：持有运行中 task 引用防 GC（asyncio 文档要求保存引用）
_running_tasks: dict[str, asyncio.Task] = {}
```

`trigger_collection`（line 134-168）改为：

```python
@router.post("/{vehicle_id}/collect")
async def trigger_collection(vehicle_id: str, session: AsyncSession = Depends(get_session)):
    vehicle = await session.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(404, detail="Vehicle not found")

    phase_info = pipeline_phases.get(vehicle_id, {})
    if phase_info.get("phase") in ("collecting", "analyzing", "calculating"):
        return {"vehicle_id": vehicle_id, "status": "already_running", "phase": phase_info["phase"]}

    # F-1：DB 级并发锁（line 144-165 原逻辑保留不变）
    cs = (await session.execute(
        select(CollectionStatus).where(
            CollectionStatus.vehicle_id == vehicle_id,
            CollectionStatus.source == "all",
        )
    )).scalar_one_or_none()
    if cs and cs.is_running:
        from datetime import datetime, timedelta
        stale = (not cs.last_collected_at or
                 datetime.now() - cs.last_collected_at > timedelta(minutes=30))
        if not stale:
            return {"vehicle_id": vehicle_id, "status": "already_running", "phase": "collecting(db_lock)"}
        logger.warning("检测到脏 DB 锁（is_running 超 30min），重置: vehicle=%s", vehicle_id)
    if cs:
        cs.is_running = True
        await session.commit()
    else:
        cs = CollectionStatus(vehicle_id=vehicle_id, source="all", mode="initial", is_running=True)
        session.add(cs)
        await session.commit()

    # 持有 task 引用防 GC + 取消同车 zombie
    old = _running_tasks.get(vehicle_id)
    if old and not old.done():
        old.cancel()
        logger.info("取消同车旧 task: vehicle=%s", vehicle_id)
    task = asyncio.create_task(_run_full_pipeline(vehicle_id))
    _running_tasks[vehicle_id] = task
    task.add_done_callback(lambda t: _running_tasks.pop(vehicle_id, None))
    return {"vehicle_id": vehicle_id, "status": "started", "phase": "collecting"}
```

- [ ] **Step 4: 运行验证 PASS**

Run: `python -m pytest tests/test_pipeline_task_lifecycle.py::test_task_held_reference tests/test_pipeline_task_lifecycle.py::test_zombie_task_cancelled_on_retrigger -v`
Expected: 2 PASS。

- [ ] **Step 5: 暂不提交，Task 2-3 一起 commit**

---

## Task 2: 内存 dict TTL + _run_full_pipeline 更新 _updated_at

**Files:**
- Modify: `api/pipeline_state.py`（加 `_is_phase_stale`）
- Modify: `api/routes/collection.py`（`_run_full_pipeline` 更新 `_updated_at`）

- [ ] **Step 1: 写测试**

`tests/test_pipeline_task_lifecycle.py` 追加：

```python
def test_phase_stale_ttl():
    """30min 旧 phase 视为 stale。"""
    from datetime import datetime, timedelta
    from api.pipeline_state import _is_phase_stale
    fresh = {"phase": "collecting", "_updated_at": datetime.now()}
    stale = {"phase": "collecting", "_updated_at": datetime.now() - timedelta(minutes=31)}
    no_ts = {"phase": "collecting"}  # 旧数据无时间戳
    assert not _is_phase_stale(fresh), "fresh 不应 stale"
    assert _is_phase_stale(stale), "31min 旧应 stale"
    assert _is_phase_stale(no_ts), "无时间戳应 stale（兼容）"
```

- [ ] **Step 2: 运行验证 FAIL**

Run: `python -m pytest tests/test_pipeline_task_lifecycle.py::test_phase_stale_ttl -v`
Expected: FAIL — `_is_phase_stale` 不存在。

- [ ] **Step 3: 加 `_is_phase_stale` 到 pipeline_state.py**

`api/pipeline_state.py` 末尾加：

```python
from datetime import datetime, timedelta

_PHASE_TTL = timedelta(minutes=30)  # 与 DB 锁 TTL 对齐


def _is_phase_stale(phase_info: dict) -> bool:
    """30 分钟无进展视为 zombie（与 DB 锁脏锁容错对齐）。"""
    updated = phase_info.get("_updated_at")
    if not updated:
        return True  # 无时间戳视为 stale（旧数据兼容）
    return datetime.now() - updated > _PHASE_TTL
```

- [ ] **Step 4: `_run_full_pipeline` 更新 `_updated_at`**

`api/routes/collection.py` `_run_full_pipeline` 每个 phase 转换处加 `_updated_at`。顶部 import：

```python
from datetime import datetime
```

修改 phase 转换（line 23, 32, 38, 46, 112, 117）：

```python
# line 23
pipeline_phases[vehicle_id] = {"phase": "collecting", "posts_collected": 0, "analyzed": 0, "error": None, "_updated_at": datetime.now()}
# line 32 (error)
pipeline_phases[vehicle_id] = {"phase": "error", "posts_collected": 0, "analyzed": 0, "error": ..., "_updated_at": datetime.now()}
# line 38 (analyzing)
pipeline_phases[vehicle_id] = {"phase": "analyzing", "posts_collected": posts_collected, "analyzed": 0, "error": None, "_updated_at": datetime.now()}
# line 46 (calculating)
pipeline_phases[vehicle_id] = {"phase": "calculating", "posts_collected": posts_collected, "analyzed": analyzed, "error": None, "_updated_at": datetime.now()}
# line 112 (completed)
pipeline_phases[vehicle_id] = {"phase": "completed", "posts_collected": posts_collected, "analyzed": analyzed, "error": None, "_updated_at": datetime.now()}
# line 117 (error except)
pipeline_phases[vehicle_id] = {"phase": "error", "posts_collected": 0, "analyzed": 0, "error": str(e), "_updated_at": datetime.now()}
```

注意：`pipeline_phases[vehicle_id]["comments_analyzed"] = cmt_analyzed`（line 63）和 `["defect_themes"]`（line 87）等增量更新不重设 `_updated_at`（避免掩盖卡住）。

- [ ] **Step 5: 运行验证 PASS**

Run: `python -m pytest tests/test_pipeline_task_lifecycle.py::test_phase_stale_ttl -v`
Expected: PASS。

- [ ] **Step 6: 暂不提交**

---

## Task 3: get_pipeline_status 优先查 DB

**Files:**
- Modify: `api/routes/collection.py`（`get_pipeline_status` 重写）

- [ ] **Step 1: 写测试**

`tests/test_pipeline_task_lifecycle.py` 追加：

```python
@pytest.mark.asyncio
async def test_get_status_db_priority(monkeypatch):
    """DB completed 时返回 completed，即使内存 dict 是 calculating（zombie）。"""
    from datetime import datetime
    from api.pipeline_state import pipeline_phases
    # 内存残留 calculating（zombie）
    pipeline_phases["v-db-test"] = {"phase": "calculating", "_updated_at": datetime.now()}

    # mock DB 返回 completed
    mock_session = MagicMock()
    mock_status = MagicMock()
    mock_status.status = "completed"
    mock_status.posts_collected = 100
    mock_status.error_message = None
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=mock_status)
    mock_analyzed_result = MagicMock()
    mock_analyzed_result.scalar = MagicMock(return_value=95)
    async def _execute(stmt, *a, **kw):
        if "CollectionStatus" in str(stmt):
            return mock_result
        return mock_analyzed_result
    mock_session.execute = AsyncMock(side_effect=_execute)

    from api.routes.collection import get_pipeline_status
    r = await get_pipeline_status("v-db-test", mock_session)
    assert r["phase"] == "completed", f"DB completed 应优先，实际 {r['phase']}"
    assert r["posts_collected"] == 100
    # 清理
    pipeline_phases.pop("v-db-test", None)
```

- [ ] **Step 2: 运行验证 FAIL**

Run: `python -m pytest tests/test_pipeline_task_lifecycle.py::test_get_status_db_priority -v`
Expected: FAIL — 现状优先信内存 dict 返回 calculating。

- [ ] **Step 3: 重写 `get_pipeline_status`**

`api/routes/collection.py` line 180-207 替换为：

```python
@router.get("/{vehicle_id}/pipeline-status")
async def get_pipeline_status(vehicle_id: str, session: AsyncSession = Depends(get_session)):
    """DB 优先（真相源）→ 内存 dict 热缓存（带 TTL）→ fallback idle。

    DB collection_status.status='completed' 直接返回，不查内存（防 zombie
    内存 dict 掩盖 DB 真相）。
    """
    # 1. 查 DB（真相源）
    status = (await session.execute(
        select(CollectionStatus).where(
            CollectionStatus.vehicle_id == vehicle_id,
            CollectionStatus.source == "all",
        )
    )).scalar_one_or_none()

    analyzed = (await session.execute(
        select(func.count(AnalyzedPost.id)).where(AnalyzedPost.vehicle_id == vehicle_id)
    )).scalar() or 0

    # 2. DB completed → 直接返回（即使内存有 zombie calculating）
    if status and status.status == "completed" and not status.is_running:
        return {
            "vehicle_id": vehicle_id,
            "phase": "completed",
            "posts_collected": status.posts_collected or 0,
            "analyzed": analyzed,
            "error": status.error_message,
        }

    # 3. DB 非 completed → 看内存 dict（热缓存，带 TTL）
    phase_info = pipeline_phases.get(vehicle_id)
    if phase_info and not _is_phase_stale(phase_info):
        return {"vehicle_id": vehicle_id, **phase_info}

    # 4. 内存无或 stale → fallback DB status
    if status:
        return {
            "vehicle_id": vehicle_id,
            "phase": status.status or "idle",
            "posts_collected": status.posts_collected or 0,
            "analyzed": analyzed,
            "error": status.error_message,
        }
    return {"vehicle_id": vehicle_id, "phase": "idle", "posts_collected": 0, "analyzed": 0, "error": None}
```

import 加：

```python
from api.pipeline_state import PipelineProgress, pipeline_progress, pipeline_phases, _is_phase_stale
```

- [ ] **Step 4: 运行验证 PASS**

Run: `python -m pytest tests/test_pipeline_task_lifecycle.py -v`
Expected: 全 PASS（4 测试）。

- [ ] **Step 5: 提交 Task 1-3**

```bash
git add api/routes/collection.py api/pipeline_state.py tests/test_pipeline_task_lifecycle.py
git commit -m "fix(pipeline): task 持有引用防 GC + get_pipeline_status DB 优先 + 内存 TTL

根因：asyncio.create_task 未持有引用被 GC（重启后第一次调用稳定复现，
风云A9L 三次触发 0 帖）；get_pipeline_status 优先信内存 dict 掩盖 DB 真相。

修复：
- _running_tasks dict 持有 task 引用 + add_done_callback 完成清理
- 重新触发同车 collect 时 cancel() 旧 zombie task
- _is_phase_stale: 30min TTL（与 DB 锁对齐），无进展视为 zombie
- _run_full_pipeline 每个 phase 转换更新 _updated_at
- get_pipeline_status 重写：DB completed 优先 → 内存非 stale → fallback DB
  （DB collection_status.status='completed' 且 is_running=False 时直接返回）

测试：4 个（task 持有/zombie 取消/TTL/DB 优先）"
```

---

## Task 4: 回归 + 实采验证 + 归档

**Files:** 无代码改动

- [ ] **Step 1: 全量测试**

Run: `python -m pytest tests/ -q`
Expected: 736 + 4 = 740 passed。

- [ ] **Step 2: 重启服务 + 触发风云A9L 采集验证 task 不被 GC**

```bash
# 重启服务
powershell -Command "Stop-Process ... ; Start-Process python start.py ..."
# 触发风云A9L
python -c "import urllib.request; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/api/vehicles/ec3edadf-52cf-4cb9-a224-2af4357c40ba/collect', method='POST'))"
# 监控 task 持有
python -c "
import urllib.request, json, time
vid='ec3edadf-52cf-4cb9-a224-2af4357c40ba'
for i in range(40):
    r=json.load(urllib.request.urlopen(f'http://127.0.0.1:8000/api/vehicles/{vid}/pipeline-status', timeout=5))
    print(f'[{i*15}s] phase={r[\"phase\"]} posts={r[\"posts_collected\"]}')
    if r['phase'] in ('completed','error'): break
    time.sleep(15)
"
```
Expected: task 正常推进（collecting → analyzing → calculating → completed），不再 0 帖卡死。

- [ ] **Step 3: 验证 get_pipeline_status 与 DB 一致**

```bash
python -c "
import sqlite3, json, urllib.request
vid='ec3edadf-52cf-4cb9-a224-2af4357c40ba'
con=sqlite3.connect('data/vehicle_sentiment.db'); cur=con.cursor()
db_status=cur.execute('SELECT status FROM collection_status WHERE vehicle_id=?', (vid,)).fetchone()
api_status=json.load(urllib.request.urlopen(f'http://127.0.0.1:8000/api/vehicles/{vid}/pipeline-status', timeout=5))
print(f'DB: {db_status[0]}, API: {api_status[\"phase\"]}')
assert db_status[0] == api_status['phase'], 'DB 与 API 不一致'
print('✅ 一致')
"
```

- [ ] **Step 4: /simplify 审查**
- [ ] **Step 5: /requesting + /receiving code-review**
- [ ] **Step 6: /opsx:archive 归档**

---

## Self-Review（3.5 自查收敛）

**1. Spec coverage:**
- ✅ task 持有引用 → Task 1
- ✅ DB 优先 → Task 3
- ✅ 内存 TTL → Task 2
- ✅ finally 释放锁 → 已有（line 121-131 保留）

**2. 跨 task 依赖:**
- Task 2 `_is_phase_stale` 被 Task 3 `get_pipeline_status` import → Task 3 Step 3 import 已标注 ✓
- Task 2 `_updated_at` 被 Task 3 依赖 → Task 2 Step 4 已加 ✓

**3. 风险点复查:**
- DB 优先返回旧 completed 风险：Task 3 加 `not status.is_running` 条件——新触发 collect 会先设 `is_running=True`，DB 查到 `is_running=True` 时不返回 completed，fallback 内存 dict ✓
- TTL 误清长 task：每 phase 转换更新 `_updated_at`，30min 是"无进展"非"总时长" ✓
- `add_done_callback` lambda 捕获 `vehicle_id`：闭包正确，pop 不会泄漏 ✓

**4. 测试 mock 真实性:**
- `trigger_collection` mock session.execute 返回 None（无 cs）→ 走 else 分支建新 cs ✓
- `get_pipeline_status` mock execute 区分 CollectionStatus vs AnalyzedPost 查询 ✓
- `_is_phase_stale` 不需 mock（纯函数）✓

**5. 自查发现的问题（v1→v2 收敛）:**
- ❌ v1 草稿 `get_pipeline_status` DB 优先没查 `is_running` → 新触发 collect 时 DB 仍是旧 completed（is_running 刚被设 True 但 status 字段还是 completed）会返回旧 completed。**修正 v2**：加 `not status.is_running` 条件，is_running=True 时 fallback 内存 dict（trigger_collection 已设 pipeline_phases=collecting）。
- ❌ v1 `add_done_callback(lambda t: _running_tasks.pop(vehicle_id, None))` 在 task 异常时 pop 但 `pipeline_phases[vid]` 残留 error 状态——这是对的（保留 error 供查询），但需确认 TTL 能清。✓ `_updated_at` 在 except 块设置，30min 后 stale。
