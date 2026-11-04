# 采集触发链路加固 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复风云T9L 点采集报 500（UnboundLocalError），清理 api/ 函数内 import 反模式，补齐 trigger 三链路的互斥/提示一致性，加防回潮 CI 检查。

**Architecture:** 两批次独立提交。批次一 P0 热修（删 collection.py 两处函数内 import，恢复线上采集）。批次二含 C-1 冗余清理、F-1/F-2/F-3 前端互斥与提示对齐、G-1 防回潮（AST 脚本扫 api/ 全口径 + CI step）、回归测试。所有改动保留原逻辑，仅消除遮蔽/补防御。

**Tech Stack:** Python 3.13 / FastAPI / SQLAlchemy async / pytest-asyncio / Vue3+JS 前端 / GitHub Actions CI

**OpenSpec:** `openspec/changes/collection-trigger-hardening/`（proposal/design/specs/tasks）
**方案文档:** `docs/采集刷新增量全面审查方案-2026-10-07.md`（v2 收敛版）

---

## File Structure

| 文件 | 改动 | 责任 |
|---|---|---|
| `api/routes/collection.py` | 改 L166/L179 | 删 trigger_collection 函数内 import（P0） |
| `api/routes/dashboard.py` | 改 L688/892/896/991/994 | 删冗余函数内 import（C-1） |
| `api/routes/analysis.py` | 改 L79 | 删冗余函数内 import（C-1） |
| `api/routes/fleet.py` | 改 L46-52 | 循环内 import 提到循环外（F-2） |
| `frontend/static/js/app.js` | 改 L1230-1239/L1333-1335 | triggerCollection 加 fleetCollecting 检查+already_running 提示（F-1）；triggerFleetCollect 加 loading/refreshing 检查（F-3） |
| `scripts/check_no_inline_imports.py` | 新建 | AST 扫 api/ 函数体内 import（G-1） |
| `.github/workflows/test.yml` | 改 | 加 G-1 step |
| `tests/test_collection_api.py` | 改 | 新增 idle cs → 200 回归用例 |

---

## Task 1: P0 热修 — 删 trigger_collection 函数内 import

**批次一，独立先行。** 仅删 2 行，恢复线上采集。

**Files:**
- Modify: `api/routes/collection.py:166`
- Modify: `api/routes/collection.py:179`

- [ ] **Step 1: 删 L166 的函数内 import**

`api/routes/collection.py:165-173` 现状：
```python
    if cs and cs.is_running:
        from datetime import datetime, timedelta
        # §3.8 L5：脏锁判据用 lock_acquired_at（加锁时刻），而非 last_collected_at
        # （last_collected_at 只在采集完成时更新，无法区分"本次运行已 30min"与"上次完成已 30min 前"）
        lock_time = cs.lock_acquired_at or cs.last_collected_at  # 兼容旧数据
        stale = (not lock_time or datetime.now() - lock_time > timedelta(minutes=30))
        if not stale:
            return {"vehicle_id": vehicle_id, "status": "already_running", "phase": "collecting(db_lock)"}
        logger.warning("检测到脏 DB 锁（is_running 超 30min），重置: vehicle=%s", vehicle_id)
```

删除第 166 行 `from datetime import datetime, timedelta`（顶部 L5 已导入）。

- [ ] **Step 2: 删 L179 的函数内 import**

`api/routes/collection.py:178-183` 现状：
```python
    else:
        from datetime import datetime
        cs = CollectionStatus(vehicle_id=vehicle_id, source="all", mode="initial",
                              is_running=True, lock_acquired_at=datetime.now())
        session.add(cs)
        await session.commit()
```

删除第 179 行 `from datetime import datetime`。

- [ ] **Step 3: 验证顶部导入覆盖所有使用点**

确认 L5 `from datetime import date, datetime, timedelta` 后，函数内 L170 (`datetime.now() - lock_time`、`timedelta(minutes=30)`)、L176 (`datetime.now()`)、L181 (`datetime.now()`) 全部走顶部导入。运行：
```bash
PYTHONPATH=. python -c "import ast; ast.parse(open('api/routes/collection.py',encoding='utf-8').read())"
```
Expected: 无异常（语法正确）。

- [ ] **Step 4: 端到端验证（需服务运行，可选延后到 T7）**

对风云T9L（`collection_status` 行 `is_running=0`）点采集 → 期望 HTTP 200 `{"status":"started"}`。若服务未起，至少跑 Step 5 单测兜底。

- [ ] **Step 5: Commit P0 热修**

```bash
git add api/routes/collection.py
git commit -m "fix(collection): 删 trigger_collection 函数内 import 致 UnboundLocalError 500（P0 热修）

顶部 L5 已导入 datetime/timedelta；L166/L179 函数内 import 遮蔽顶部，
is_running=False 路径走 L176 datetime.now() 未绑定 → UnboundLocalError。
删除两行，逻辑不变（脏锁容错/分支行为不变）。

OpenSpec: collection-trigger-hardening (P0)"
```

---

## Task 2: C-1 清理 dashboard.py 冗余函数内 import

**Files:**
- Modify: `api/routes/dashboard.py:688`
- Modify: `api/routes/dashboard.py:892`
- Modify: `api/routes/dashboard.py:896`
- Modify: `api/routes/dashboard.py:991`
- Modify: `api/routes/dashboard.py:994`

- [ ] **Step 1: 删 L688**

`dashboard.py:687-690` 现状：
```python
    start_d = date.fromisoformat(start)
    end_d = date.fromisoformat(end)

    from datetime import datetime
    start_dt = datetime.combine(start_d, datetime.min.time())
    end_dt = datetime.combine(end_d + timedelta(days=1), datetime.min.time())
```
删第 688 行 `from datetime import datetime`（顶部 L3 已导入 datetime）。

- [ ] **Step 2: 删 L892**

`dashboard.py:891-894` 现状：
```python
    if start:
        from datetime import datetime as dt
        start_dt = dt.fromisoformat(start)
        query = query.where(RawPost.published_at >= start_dt)
```
删第 892 行，把第 893 行 `dt.fromisoformat` 改为 `datetime.fromisoformat`：
```python
    if start:
        start_dt = datetime.fromisoformat(start)
        query = query.where(RawPost.published_at >= start_dt)
```

- [ ] **Step 3: 删 L896**

`dashboard.py:895-898` 现状：
```python
    if end:
        from datetime import datetime as dt
        end_dt = dt.fromisoformat(end) + timedelta(days=1)
        query = query.where(RawPost.published_at < end_dt)
```
删第 896 行，把 `dt.fromisoformat` 改为 `datetime.fromisoformat`：
```python
    if end:
        end_dt = datetime.fromisoformat(end) + timedelta(days=1)
        query = query.where(RawPost.published_at < end_dt)
```

- [ ] **Step 4: 删 L991**

`dashboard.py:990-992` 现状：
```python
    if start:
        from datetime import datetime as dt
        batch_q = batch_q.where(func.coalesce(RawPost.published_at, RawPost.collected_at) >= dt.fromisoformat(start))
```
删第 991 行，改 `dt.fromisoformat` → `datetime.fromisoformat`：
```python
    if start:
        batch_q = batch_q.where(func.coalesce(RawPost.published_at, RawPost.collected_at) >= datetime.fromisoformat(start))
```

- [ ] **Step 5: 删 L994**

`dashboard.py:993-995` 现状：
```python
    if end:
        from datetime import datetime as dt
        batch_q = batch_q.where(func.coalesce(RawPost.published_at, RawPost.collected_at) < dt.fromisoformat(end) + timedelta(days=1))
```
删第 994 行，改 `dt.fromisoformat` → `datetime.fromisoformat`：
```python
    if end:
        batch_q = batch_q.where(func.coalesce(RawPost.published_at, RawPost.collected_at) < datetime.fromisoformat(end) + timedelta(days=1))
```

- [ ] **Step 6: 跑 dashboard 相关测试**

```bash
PYTHONPATH=. python -m pytest tests/test_dashboard*.py -q
```
Expected: PASS（行为不变，仅别名改回原名）。

---

## Task 3: C-1 清理 analysis.py 冗余函数内 import

**Files:**
- Modify: `api/routes/analysis.py:79`

- [ ] **Step 1: 删 L79**

`analysis.py:70-81` 现状（在 `try:` 块内）：
```python
            try:
                from pipeline.analysis.defect_miner import mine_defect_themes
                from models.schemas import DefectTheme
                import uuid as _uuid
                dstats = await mine_defect_themes(vehicle_id, session)
                pipeline_phases[vehicle_id]["defect_themes"] = len(dstats)
                await session.execute(
                    __import__("sqlalchemy").delete(DefectTheme).where(DefectTheme.vehicle_id == vehicle_id)
                )
                from datetime import date as _d
                end_d = _d.today()
                start_d = end_d - timedelta(days=30)
```
顶部 L4 已 `from datetime import date, datetime, timedelta`。删第 79 行 `from datetime import date as _d`，把第 80 行 `_d.today()` 改为 `date.today()`：
```python
                end_d = date.today()
                start_d = end_d - timedelta(days=30)
```

**注意：** L71-72 的 `from pipeline.analysis.defect_miner import ...` 和 `from models.schemas import DefectTheme` 也是函数内 import，但**不在本 change 口径内**（G-1 只扫 `api/` 函数体 import 的全口径会在 G-1 脚本里命中这些——见 Task 6 决策）。本 Task 只删 datetime 这一处（C-1 范围）。

> ⚠️ **G-1 口径冲突预警：** analysis.py 函数体内还有 L71 `from pipeline...`、L72 `from models...`、L73 `import uuid as _uuid`、L77 `__import__("sqlalchemy")` 等函数内 import。若 G-1 全口径扫 `api/`，这些会全部命中 → 脚本报错。**必须在 Task 6 决策：要么 analysis.py 这些非 datetime 的函数内 import 也一并清理（扩大 C-1），要么 G-1 脚本对 analysis.py 这类"延迟加载重型模块"做白名单豁免。** 见 Task 6 Step 1 的决策。

- [ ] **Step 2: 跑 analysis 测试**

```bash
PYTHONPATH=. python -m pytest tests/ -k "analysis or defect or pipeline" -q
```
Expected: PASS。

---

## Task 4: F-2 fleet.py 循环内 import 提到循环外

**Files:**
- Modify: `api/routes/fleet.py:46-52`

- [ ] **Step 1: 把 import 提到循环外**

`fleet.py:46-56` 现状：
```python
    # P0-A：每车独立 session（不共用 request session）
    started = []
    for v in targets:
        try:
            async with async_session() as s:
                from api.routes.collection import trigger_collection as _tc
                await _tc(v["id"], s)
            started.append(v["id"])
        except Exception as e:
            logger.warning("fleet collect %s failed: %s", v["name"], e)
```
改为：
```python
    # P0-A：每车独立 session（不共用 request session）
    # F-2：import 提到循环外（import 有缓存无害，纯风格；G-1 全口径禁函数体 import）
    from api.routes.collection import trigger_collection as _tc
    started = []
    for v in targets:
        try:
            async with async_session() as s:
                await _tc(v["id"], s)
            started.append(v["id"])
        except Exception as e:
            logger.warning("fleet collect %s failed: %s", v["name"], e)
```

**注意：** `from api.routes.collection import trigger_collection as _tc` 提到函数体顶部（仍在 `trigger_fleet_collect` 函数内）。G-1 全口径会命中此行 → 这是**模块级延迟导入**（避免循环 import 的合理用法）。Task 6 决策白名单。

> ⚠️ **循环依赖核查：** fleet.py 顶部若 `from api.routes.collection import trigger_collection` 会否致循环 import？现状是函数内导入即为此规避。提到函数体顶部（非模块顶部）仍保持延迟，**不会引入循环**。验证方式：Step 2 跑测试若 import 失败会立即报错。

- [ ] **Step 2: 跑 fleet 测试**

```bash
PYTHONPATH=. python -m pytest tests/ -k "fleet" -q
```
Expected: PASS（若无 fleet 测试，跑全量 `python -m pytest -q` 确认无 import 错误）。

---

## Task 5: F-1 + F-3 前端 triggerCollection / triggerFleetCollect 加固

**Files:**
- Modify: `frontend/static/js/app.js:1230-1239`（triggerCollection）
- Modify: `frontend/static/js/app.js:1333-1335`（triggerFleetCollect）

- [ ] **Step 1: triggerCollection 首部加 fleetCollecting 检查**

`app.js:1230-1239` 现状：
```javascript
        async triggerCollection() {
            this.loading = true;
            this.pipelinePhase = "collecting";
            const data = await this.apiFetch(`/api/vehicles/${this.currentVehicleId}/collect`, { method: "POST" });
            if (!data) { this.loading = false; this.pipelinePhase = ""; return; }
            if (data.status === "already_running") {
                this.pipelinePhase = data.phase;
            }
            this._startPolling();
        },
```
改为（首部加检查对齐 refresh app.js:1284）：
```javascript
        async triggerCollection() {
            if (this.fleetCollecting) { this.showToast("全车采集进行中，请等待完成后再点采集", "info"); return; }
            this.loading = true;
            this.pipelinePhase = "collecting";
            const data = await this.apiFetch(`/api/vehicles/${this.currentVehicleId}/collect`, { method: "POST" });
            if (!data) { this.loading = false; this.pipelinePhase = ""; return; }
            if (data.status === "already_running") {
                this.pipelinePhase = data.phase;
                // F-1：复用 refresh 的 D3 模式，查 /status 区分单车/全车 + toast（对齐 app.js:1289-1301）
                const st = await this.apiFetch("/api/fleet/status", { silent: true });
                if (st && st.in_progress_count >= 2) {
                    this.showToast(`全车采集进行中（${st.in_progress_count} 台），请等待完成`, "info");
                } else {
                    const label = {collecting:"采集中", analyzing:"分析中", calculating:"计算中", refreshing:"刷新中", "collecting(db_lock)":"采集中"}[data.phase] || data.phase;
                    this.showToast(`该车正在${label}，请等待完成`, "info");
                }
                this.loading = false;
                return;
            }
            this._startPolling();
        },
```

**关键决策（与 design D2 一致）：** already_running 分支这里**加 `return` 并显式 `this.loading = false`**——这与 v1 证伪的"保持现状"是否冲突？

不冲突。design D2 说"保持现状"指**不加 D3 提示时**保持轮询。现在 F-1 主动加提示：用户已知"是别人在跑"，无需再轮询别人的进度 → 加 return + 复位 loading 是 F-1 引入的新行为，与 v1 证伪的 P1-1/P2-1（无提示时强制 return 致永久 disabled）不同。**前提：return 前必须 `loading=false`**（否则回到 v1 P1-1 的坑）。refresh 的 already_running 分支（app.js:1299-1300）正是此模式 `this.refreshing = false; return;`——这里对齐 `this.loading = false; return;`。

**toast 映射表补 `collecting(db_lock)`**（collection.py:171-172 返回值），映射到"采集中"（与 `collecting` 同义，db_lock 只是来源标记）。

- [ ] **Step 2: triggerFleetCollect 首部加 loading/refreshing 检查**

`app.js:1333-1335` 现状：
```javascript
        async triggerFleetCollect() {
            this.showOverflow = false;  // P0-1：方法内关菜单
            if (this.fleetCollecting) return;
```
改为：
```javascript
        async triggerFleetCollect() {
            this.showOverflow = false;  // P0-1：方法内关菜单
            if (this.loading || this.refreshing) { this.showToast("单车任务进行中，请等待完成后再全车采集", "info"); return; }
            if (this.fleetCollecting) return;
```

- [ ] **Step 3: 前端无单测，跑全量后端测试确认无回归**

```bash
PYTHONPATH=. python -m pytest -q
```
Expected: PASS（前端改动不影响后端测试，仅确认未误改文件）。

- [ ] **Step 4: 手动验证前端（可选，延后到 T7）**

启动看板 → 全车采集进行中时点单车采集 → 期望 toast"全车采集进行中（N 台）"且不进轮询。

---

## Task 6: G-1 防回潮 — AST 脚本扫 api/ 全口径

**Files:**
- Create: `scripts/check_no_inline_imports.py`
- Modify: `.github/workflows/test.yml`

- [ ] **Step 1: 决策 analysis.py / fleet.py 的非 datetime 函数内 import 处置**

G-1 全口径扫 `api/` 会命中：
- `analysis.py:71` `from pipeline.analysis.defect_miner import mine_defect_themes`
- `analysis.py:72` `from models.schemas import DefectTheme`
- `analysis.py:73` `import uuid as _uuid`
- `analysis.py:77` `__import__("sqlalchemy")`（AST 视角是 Call 不是 Import，**不命中**）
- `fleet.py:51`（Task 4 后）`from api.routes.collection import trigger_collection as _tc`

这些都是**合理的延迟导入**（避免循环 import / 重型模块启动开销），非反模式。

**决策：白名单豁免，而非强清理。** 理由：
1. analysis.py 的延迟导入是 `_run_full_pipeline` 内部按需加载（defect_miner 只在管线末端用），提到模块顶部会拖慢启动 + 可能循环依赖。
2. fleet.py 的 `trigger_collection` 导入若提到模块顶部会循环 import（fleet ↔ collection 互相引用）。
3. G-1 的本意是防"**跨分支使用致 UnboundLocalError**"的反模式，即 `datetime` 这种顶部已导入、函数内再 import 同名遮蔽的 case。延迟加载不同模块是另一回事。

**白名单实现：** 脚本扫函数体内 `from X import Y` / `import X`，命中即报错；但允许通过 `# noqa: inline-import` 行注释豁免（在 import 行尾加注释）。analysis.py L71-73、fleet.py L51 加该注释。

> **替代方案（更严格）：** 若用户后续要彻底禁，改白名单为"禁止 import 顶部已导入的名字"——即只挡 `from datetime import`（顶部已有）这类遮蔽，不挡延迟加载新模块。本次按用户拍板的"api/ 全口径 + noqa 豁免"实现。

- [ ] **Step 2: 给 analysis.py / fleet.py 的延迟 import 加 noqa 注释**

`analysis.py:71-73`：
```python
                from pipeline.analysis.defect_miner import mine_defect_themes  # noqa: inline-import
                from models.schemas import DefectTheme  # noqa: inline-import
                import uuid as _uuid  # noqa: inline-import
```

`fleet.py:51`（Task 4 改后）：
```python
    from api.routes.collection import trigger_collection as _tc  # noqa: inline-import
```

- [ ] **Step 3: 写 scripts/check_no_inline_imports.py**

```python
#!/usr/bin/env python3
"""G-1 防回潮：扫描 api/ 下函数体内 import，期望 0 命中（# noqa: inline-import 可豁免）。

口径：api/ 全口径（禁止函数内 import 跨分支使用致 UnboundLocalError 的反模式）。
范围：仅 api/；tests/ 排除；pipeline/scripts/utils/models/ 不在口径内。
豁免：import 行尾加 `# noqa: inline-import` 注释则跳过（用于合理的延迟加载）。
退出码：0 命中=通过，>0=失败。
"""
import ast
import sys
from pathlib import Path

NOQA_TAG = "noqa: inline-import"
TARGET_DIR = Path(__file__).resolve().parent.parent / "api"


def _is_noqa(node: ast.stmt, source_lines: list[str]) -> bool:
    """判断 import 节点所在行是否含 noqa: inline-import 注释。"""
    if not hasattr(node, "lineno"):
        return False
    line = source_lines[node.lineno - 1] if node.lineno - 1 < len(source_lines) else ""
    return NOQA_TAG in line


def _walk_functions(tree: ast.Module):
    """遍历所有函数定义（含嵌套），产出 (func_node) 。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _function_imports(func: ast.FunctionDef, source_lines: list[str]):
    """函数体内的 import 语句（排除嵌套函数的——ast.walk 会单独走到，避免重复计）。"""
    for child in ast.walk(func):
        if child is func:
            continue
        # 嵌套函数的 import 由嵌套函数自己负责报，这里不重复
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            if _is_noqa(child, source_lines):
                continue
            yield child


def check_file(path: Path) -> list[str]:
    """返回该文件的所有违规（函数内 import 且无 noqa）。"""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        return [f"{path}: 语法错误 {e}"]
    lines = source.splitlines()
    violations = []
    for func in _walk_functions(tree):
        for imp in _function_imports(func, lines):
            kind = "from" if isinstance(imp, ast.ImportFrom) else "import"
            names = ", ".join(a.name for a in imp.names) if isinstance(imp, ast.Import) else ", ".join(imp.names)
            violations.append(f"{path}:{imp.lineno}: 函数 `{func.name}` 内 {kind} {names}（加 `# noqa: inline-import` 豁免）")
    return violations


def main() -> int:
    if not TARGET_DIR.exists():
        print(f"目标目录不存在: {TARGET_DIR}", file=sys.stderr)
        return 2
    py_files = sorted(TARGET_DIR.rglob("*.py"))
    all_violations = []
    for f in py_files:
        all_violations.extend(check_file(f))
    if all_violations:
        print(f"❌ G-1 检查失败：发现 {len(all_violations)} 处函数内 import（api/ 全口径禁止）：", file=sys.stderr)
        for v in all_violations:
            print(f"  {v}", file=sys.stderr)
        return 1
    print(f"✅ G-1 通过：api/ 下 0 处函数内 import（扫描 {len(py_files)} 文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 本地运行脚本，期望 0 命中**

```bash
PYTHONPATH=. python scripts/check_no_inline_imports.py
```
Expected: `✅ G-1 通过：api/ 下 0 处函数内 import（扫描 N 文件）`

若命中：按违规清单加 `# noqa: inline-import` 或清理。注意 `__import__("sqlalchemy")` 是 Call 不是 Import，AST 不会命中（已确认）。

- [ ] **Step 5: test.yml 加 G-1 step**

`.github/workflows/test.yml` 现状：
```yaml
      - run: pip install -r requirements.txt
      - run: PYTHONPATH=. python -m pytest -q
```
改为：
```yaml
      - run: pip install -r requirements.txt
      - run: PYTHONPATH=. python scripts/check_no_inline_imports.py
      - run: PYTHONPATH=. python -m pytest -q
```

- [ ] **Step 6: 再次本地运行确认 + 跑全量测试**

```bash
PYTHONPATH=. python scripts/check_no_inline_imports.py && PYTHONPATH=. python -m pytest -q
```
Expected: G-1 通过 + 全量 PASS。

---

## Task 7: 回归测试 — idle cs 触发采集返回 started

**Files:**
- Modify: `tests/test_collection_api.py`

**设计：** 直接调用 `trigger_collection(vehicle_id, session)` 函数（不走 HTTP）。`Depends(get_session)` 作为默认值，直接调用时传 session 参数即被忽略（Depends 是 FastAPI 框架解析的 marker，普通调用不触发）。这样精准测 P0 路径——函数内 `datetime` 未绑定会抛 `UnboundLocalError`，pytest 直接捕获异常 FAIL，无需 HTTP 层。用 `db` fixture（test_collection_api.py L43-54）。

- [ ] **Step 1: 写测试**

在 `tests/test_collection_api.py` 末尾追加：

```python
async def test_trigger_collection_idle_cs_returns_started(db):
    """P0 回归：已有 cs 行且 is_running=False → started（非 UnboundLocalError）。

    复现风云T9L 故障路径：collection_status 存在 source='all' 行、is_running=False、
    pipeline_phases 无活跃 phase（非 already_running）。
    修复前 trigger_collection 在此路径抛 UnboundLocalError(datetime)。
    """
    from api.routes.collection import trigger_collection
    async with db() as session:
        session.add(Vehicle(id="vidle", name="风云T9L", brand="奇瑞",
                            search_keywords='["风云T9L"]'))
        session.add(CollectionStatus(vehicle_id="vidle", source="all", mode="initial",
                                     is_running=False, status="completed"))
        await session.commit()
        pipeline_phases.pop("vidle", None)  # 确保不进 already_running 分支
        with patch("api.routes.collection._run_full_pipeline", new_callable=AsyncMock):
            result = await trigger_collection("vidle", session)
    assert result["status"] == "started"
```

- [ ] **Step 2: 跑测试验证 PASS**

```bash
PYTHONPATH=. python -m pytest tests/test_collection_api.py::test_trigger_collection_idle_cs_returns_started -v
```
Expected: PASS（修复后）。若 FAIL 报 `UnboundLocalError: local variable 'datetime'` → 说明 P0 修复未生效，回 Task 1 检查。

- [ ] **Step 3: 跑全量测试**

```bash
PYTHONPATH=. python -m pytest -q
```
Expected: 全 PASS（基线 812 + 本新增 1 = 813，允许已有 flaky）。

---

## Task 8: Commit 批次二 + 归档

- [ ] **Step 1: Commit 批次二**

```bash
git add api/routes/dashboard.py api/routes/analysis.py api/routes/fleet.py frontend/static/js/app.js scripts/check_no_inline_imports.py .github/workflows/test.yml tests/test_collection_api.py
git commit -m "feat(collection): trigger 链路加固 + 防回潮（C-1/F-1/F-2/F-3/G-1/回归测试）

- C-1: 删 dashboard.py/analysis.py 6 处冗余函数内 import（纯删除）
- F-1: triggerCollection 加 fleetCollecting 检查 + already_running D3 提示（覆盖 collecting(db_lock)）
- F-2: fleet.py 循环内 import 提到循环外
- F-3: triggerFleetCollect 加 loading/refreshing 检查
- G-1: scripts/check_no_inline_imports.py（AST 扫 api/ 全口径）+ CI step
- 回归测试: idle cs → 200（防 P0 回潮）

OpenSpec: collection-trigger-hardening (批次二)"
```

- [ ] **Step 2: /simplify 自审**

- [ ] **Step 3: /requesting-code-review**

- [ ] **Step 4: /receiving-code-review（逐条验证）**

- [ ] **Step 5: /verification-before-completion**
- 全量 pytest 通过
- G-1 脚本 0 命中
- 端到端：风云T9L 点采集 200（若服务可起）

- [ ] **Step 6: /opsx:archive**

---

## Self-Review（plan 自查）

**1. Spec coverage:**
- `collection-trigger` spec 7 条 Requirement → Task 1(P0)/Task 5(F-1,F-3)/Task 4(F-2)/Task 2+3(C-1)/Task 7(回归测试) ✅ 全覆盖
- `inline-import-guard` spec 4 条 → Task 6 全覆盖 ✅
- design D1-D5 决策 → Task 1(D1)/Task 5 Step1(D2/D3)/Task 6(D4)/Task 1+8(D5 拆批) ✅

**2. Placeholder scan:** 无 TBD/TODO/"add appropriate"。"手动验证可选延后"是真实可延后项（服务启动需用户操作），非占位。

**3. Type/signature consistency:**
- `datetime.fromisoformat` 替换 `dt.fromisoformat`（Task 2）—— 顶部 L3 已导入 datetime ✅
- `date.today()` 替换 `_d.today()`（Task 3）—— 顶部 L4 已导入 date ✅
- toast 映射表 `collecting(db_lock)` 键名与 collection.py:172 返回值一致 ✅
- Task 7 直接调 `trigger_collection("vidle", session)` —— Depends 默认值直接调用被忽略，`db` fixture 提供 session ✅（已修正：原方案走 HTTP + `client.app.dependency_overrides` 取 session 是 async generator 不能 `async with`，改直接调函数更精准测 P0 路径）

**4. 交叉契约检查：**
- Task 5 改 triggerCollection already_running 加 return + loading=false → 与 design D2"保持现状"看似冲突，已在 Step 1 决策段说明不冲突（F-1 引入新提示行为，对齐 refresh app.js:1299-1300 模式）✅
- Task 6 G-1 全口径会命中 analysis.py/fleet.py 的延迟 import → Step 1 决策 noqa 豁免 + Step 2 加注释 ✅
- Task 4 fleet.py import 提到函数体顶部 → G-1 命中需 noqa（Task 6 Step 2 处理）✅

**5. 流程合规（[[dev-workflow-openspec-superpower]]）：**
- Step 3.5 自查收敛：本 plan 已自查，无增量问题 ✅
- 子代理执行留痕：Task 均可由子代理执行，commit message 含 OpenSpec change 名 ✅
