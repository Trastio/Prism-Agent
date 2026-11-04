# 刷新互动数「上次采集」不更新 — 方案（v2）

> 日期：2026-10-07
> 状态：**v1 审查未收敛；本版为审查修正版，收敛，待用户 review**
> 根因排查：见上一轮对话（风云T7 触发刷新互动数后"上次采集"时间仍显示 9-28）

## 审查结论（v1 → v2）

v1 的根因定位正确（`_run_refresh_pipeline` 不更新展示时间），但**方案选型有致命缺陷**：v1 未识别 `last_collected_at` 同时是**增量采集水位线**，方案 A 会前移水位线、造成漏采。

| 编号 | v1 问题 | 严重度 | 本版处置 |
|---|---|---|---|
| P0-1 | 方案 A 写 `last_collected_at=now` 破坏增量水位线 → 漏采 | **P0** | **废弃方案 A，并回退已落地实现**（见下） |
| P0-2 | 方案 A 已经落地在代码里（`collection.py:275` + 测试），文档仍写"待 review" | P0 | 文档状态同步 + 回退步纳入方案 |
| P1-1 | 方案 B 称"零后端改动"，但 `/collection-status` 不返回 `updated_at` | P1 | 方案 B 标注需改端点，整体不推荐 |
| P1-2 | 方案 B 的 `updated_at` 用 `func.now()`（SQLite=UTC）、`last_collected_at` 用本地时间 → 混用差 8 小时 | P1 | 不作为推荐方案 |
| P1-3 | 两方案都漏了：刷新完成后前端**未重载** `collection-status` | P1 | 纳入方案 C 改动清单 |
| P2-1 | 未覆盖"首采"边界：车从未真实采集时，写入会让下次采集被误判为 incremental | P2 | 方案 C 从根上规避（不写 `last_collected_at`） |
| P2-2 | 新增测试形同虚设：只断言"存在 UPDATE"，未断言字段 | P2 | 方案 C 测试改为强断言 |

**结论：v1 未收敛；按本版方案 C 收敛。**

---

## 问题

用户点「刷新互动数」完成后，前端"上次采集"时间不更新——仍显示上一次**采集**的时间，而非本次刷新的时间。

## 根因

`_run_refresh_pipeline`（刷新互动数管线）成功时写 `CollectionStatus.status="completed"`，但**不更新任何用于"上次采集"展示的字段**。

| 字段 | 采集（`scheduler._update_status`）写 | 刷新（`_run_refresh_pipeline`）写 |
|---|---|---|
| `last_collected_at` | ✅ now（**同时是增量水位线**） | ⚠️ 见下方 P0-1（v1 方案 A 曾写，须回退） |
| `posts_collected` | ✅ 入库数 | ❌ 不写 |
| `status` | ✅ completed | ✅ completed |
| `is_running` | trigger 写 True + finally 写 False | 同 |
| `lock_acquired_at` | trigger 写 now | 同 |

**现象后果**：刷新互动数完成后，前端"上次采集"仍显示上一次采集时间 → 用户误以为没刷新。

---

## 关键结论：`last_collected_at` 是水位线，不是展示字段（P0-1）

`last_collected_at` 被增量采集当作**起始时间水位线**消费：

- `scheduler._determine_mode`（[scheduler.py:859-866](file:///C:/Users/<you>/Desktop/Agent项目/Vehicle%20Sentiment%20Analysis%20Board/pipeline/scheduler.py#L859-L866)）：`if existing.last_collected_at: return "incremental", existing.last_collected_at`
- `scheduler._get_date_ranges`（[scheduler.py:850-857](file:///C:/Users/<you>/Desktop/Agent项目/Vehicle%20Sentiment%20Analysis%20Board/pipeline/scheduler.py#L850-L857)）：增量起点 = `last_collected_at - 2天`

因此，**方案 A 把刷新时间写进 `last_collected_at` 会把下次增量采集的窗口起点前移到"刷新时刻 − 2 天"**，导致 `[上次真实采集, 刷新时刻 − 2天)` 区间内发布的帖子被**永久跳过**（漏采）。文档 v1 自举的风云T7 例子（9-28 → 10-07）就有约 7 天数据处于风险区间。

**结论：方案 A 不可取，必须废弃并回退当前已落地的实现。**

> 备注（文档与代码状态不一致，需核对）：当前代码 [collection.py:270-275](file:///C:/Users/<you>/Desktop/Agent项目/Vehicle%20Sentiment%20Analysis%20Board/api/routes/collection.py#L270-L275) 已含 `last_collected_at=datetime.now()`（注释"方案 A"），且 [test_refresh_engagement.py:97-132](file:///C:/Users/<you>/Desktop/Agent项目/Vehicle%20Sentiment%20Analysis%20Board/tests/test_refresh_engagement.py#L97-L132) 已有对应测试——即 **P0-1 缺陷已在代码中**。而 v1 文档"DB 实证"称风云T7 仍为 9-28，与"方案 A 已生效"矛盾，需核对方案 A 是否已在当前运行环境生效。

## DB 实证（v1 原文，待复核）

fleet 触发的 7 车（采集）：`last_collected_at` 都更新到 10-07（`_update_status` 生效）。
风云T7（刷新互动数）：`last_collected_at` 仍是 9-28（与"方案 A 已落地"矛盾，见上方备注）。

---

## 收敛方案：方案 C（新增专用展示字段）

**设计原则**：`last_collected_at` 保持纯粹的水位线语义、不改动；另加一个专用展示字段承载"上次刷新时间"。

### 步骤

1. **模型**（`models/schemas.py`，CollectionStatus）加一列：

   ```python
   last_refreshed_at = Column(DateTime)  # 上次"刷新互动数"完成时刻（展示用，不参与增量水位线）
   ```

2. **迁移**（`models/database.py` 的 migrations 列表，幂等版本号顺延）：

   ```python
   {"sql": "ALTER TABLE collection_status ADD COLUMN last_refreshed_at DATETIME", ...}
   ```

   （沿用现有 `PRAGMA table_info` 幂等检查机制，与 `lock_acquired_at` 同款。）

3. **后端写**（`api/routes/collection.py`）：`_run_refresh_pipeline` 成功分支
   - **回退 P0-1**：移除 `last_collected_at=datetime.now()`（当前已落地，须删）
   - 改为写 `last_refreshed_at=datetime.now()`

   ```python
   # _run_refresh_pipeline 成功分支（替换现有 方案A 的 update）
   await session.execute(
       update(CollectionStatus).where(
           CollectionStatus.vehicle_id == vehicle_id,
           CollectionStatus.source == "all",
       ).values(
           status="completed",
           error_message=None,
           last_refreshed_at=datetime.now(),   # 专用展示字段；不动 last_collected_at（水位线）
       )
   )
   ```

4. **端点**（`/collection-status`，`collection.py:362-375`）返回新字段：

   ```python
   "last_refreshed_at": s.last_refreshed_at.isoformat() if s.last_refreshed_at else None,
   ```

5. **前端**（`frontend/static/js/app.js`）：
   - `loadCollectionStatus`（L746-753）：显示 `max(last_collected_at, last_refreshed_at)`（两者均本地时间，字符串可直接比较；前端取较大者）
   - **`_reloadAfterRefresh`（L1300-1312）补 `this.loadCollectionStatus()`**（P1-3：当前只在 `onVehicleChange` 调，刷新完成后 header 不更新）

6. **可选文案**：若认为"上次采集"应更贴切，可把 header 文案（`index.html:78`）改为"上次更新"。此项由用户拍板，不做也可收敛。

### 为什么不用方案 B（不推荐）

- `/collection-status` 未返回 `updated_at` → 并非"零后端改动"（P1-1）。
- `updated_at` 用 `func.now()`（SQLite `CURRENT_TIMESTAMP` = **UTC**），而 `last_collected_at` 用 `datetime.now()`（本地 UTC+8）→ 混用会显示差 8 小时（P1-2）。
- `updated_at` 还会被 finally 释放 `is_running=False` 等任意 update 触发，语义含糊。

### 建议

**方案 C**。语义最准确（水位线与展示字段分离），且消除漏采风险。

---

## 改动文件

| 文件 | 改动 |
|---|---|
| `models/schemas.py` | `CollectionStatus` 新增 `last_refreshed_at` 列 |
| `models/database.py` | migrations 新增 `ALTER TABLE collection_status ADD COLUMN last_refreshed_at DATETIME` |
| `api/routes/collection.py` | `_run_refresh_pipeline` 成功分支：**移除** `last_collected_at=now`（回退 P0-1）、**改为** `last_refreshed_at=now`；`/collection-status` 返回 `last_refreshed_at` |
| `frontend/static/js/app.js` | `loadCollectionStatus` 取 `max(last_collected_at, last_refreshed_at)`；`_reloadAfterRefresh` 补 `loadCollectionStatus()` |
| `frontend/index.html` | （可选）header 文案改"上次更新" |

## 测试

- `tests/test_refresh_engagement.py`：把现有 `test_run_refresh_pipeline_成功写_last_collected_at` 改为**强断言**——
  - 成功分支的 UPDATE 必须含 `last_refreshed_at`，且**不得含** `last_collected_at`（防 P0-1 回归）；
  - 新增失败分支不写 `last_refreshed_at` 的断言。
- `tests/test_migrations.py`：新增 `last_refreshed_at` 迁移幂等用例。
- `tests/test_collection_api.py`（或就近）：`/collection-status` 返回 `last_refreshed_at` 字段。
- 回归：确认 `_determine_mode` 在刷新后仍返回原 `last_collected_at`（水位线未被刷新污染）。

## 流程

superpowers 简化版（1 列 + 迁移 + 少量改动 + 测试）。