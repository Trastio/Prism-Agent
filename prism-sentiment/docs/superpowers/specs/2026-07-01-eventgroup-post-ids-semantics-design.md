# EventGroup.post_ids 语义统一 — 设计文档

> 日期：2026-07-01
> 遗留项（出自 2026-06-29 全栈治根 minor-cleanup 拆出）：EventGroup.post_ids 存的是 AnalyzedPost.id，与全项目其它 post_ids 语义不一致，统一为 RawPost.id

## 1. 背景与根因

`EventGroup.post_ids`（`models/schemas.py:178`）存事件聚合的帖子 id 列表。代码追踪确认：

- `pipeline/analysis/event_tracker.py:479` 构建 post 字典时 `"id": ap.id`（AnalyzedPost 主键）、`"post_id": ap.post_id`（RawPost 外键）两个键都有
- `event_tracker.py:328` `"post_ids": json.dumps([p["id"] for p in group])` → **存的是 AnalyzedPost.id**

而全项目其它所有 `post_ids` 都指 **RawPost.id**（经 `AnalyzedPost.post_id` 外键），例如 `api/routes/dashboard.py`、`analysis.py` 大量 `AnalyzedPost.post_id.in_(post_ids)`。唯独 `EventGroup.post_ids` 指 AnalyzedPost.id——**命名相同、语义不同**。

**隐患**：未来任何人（或 LLM）看到 `EventGroup.post_ids`，第一反应都会当 RawPost.id 去用（如 `RawPost.id.in_(event.post_ids)`），一旦如此就会查错表/查不到。这是隐性约定，无注释说明。

## 2. 目标

1. `EventGroup.post_ids` 改存 **RawPost.id**（= `AnalyzedPost.post_id`），全项目 post_ids 语义统一。
2. 消费端（event_tracker 内部 representative_posts 构建）同步对齐，保持构建即消费的自洽。
3. 补注释/docstring，消除语义歧义。
4. 治根判据：测试断言 `EventGroup.post_ids` 里的值 = RawPost.id 而非 AnalyzedPost.id。

## 3. 设计

置信度：高（改动极小、无外部消费者、NULL 安全已核实）。

### 3.1 改动点（4 处）

| # | 位置 | 改动 |
|---|------|------|
| 1 | `event_tracker.py:328` | `[p["id"] for p in group]` → `[p["post_id"] for p in group]` |
| 2 | `event_tracker.py:522` | `post_by_id = {p["id"]: p for p in post_dicts}` → `{p["post_id"]: p for p in post_dicts}` |
| 3 | `event_tracker.py:288` | assemble_events docstring 注明 post_ids = RawPost.id（JSON 数组） |
| 4 | `models/schemas.py:178` | EventGroup.post_ids 列加注释：JSON 数组，存 RawPost.id，全项目语义统一 |

改动 1（写入）与改动 2（消费）必须成对：写入改 post_id、消费键也改 post_id，`post_by_id[pid]`（`event_tracker.py:526`）才仍能匹配。

### 3.2 安全性论证（均已代码核实）

- **无 NULL 风险**：`AnalyzedPost.post_id = Column(String, nullable=False)`（`schemas.py:64`），改存 `ap.post_id` 不会有 None 进列表。
- **零外部消费者**：全项目扫描，`EventGroup.post_ids` 唯一消费点是 `event_tracker.py:524-528`（构建 representative_posts，构建即消费，不跨调用）。`api/routes/dialog.py` 的 event 分支用 EventGroup 但只读 `start_date/end_date/post_count/summary/sentiment_distribution`（dialog.py:108-122），**不读 post_ids**；前端/API 无路由返回 EventGroup.post_ids。→ 改语义不影响任何消费端。
- **现有数据自动修复**：`detect_events_for_vehicle`（`event_tracker.py:541-548`）每次按 `(vehicle_id, source)` 删除现有 EventGroup 再重写，旧数据下次跑事件检测自动正确。

### 3.3 数据处置

采用方案 A（用户确认）：**不主动迁移/全量重跑**。现有 EventGroup 数据 post_ids 仍为 AnalyzedPost.id 语义，但期间无任何消费者读取，零影响；下次事件检测（手动或定时）自动重建为正确语义。verify 阶段仅对单个车型重跑一次以证明新语义生效。

## 4. 改造范围

| 文件 | 改动 |
|------|------|
| `pipeline/analysis/event_tracker.py` | `:328` 写入改 post_id；`:522` 消费键改 post_id；`:288` docstring |
| `models/schemas.py` | `:178` EventGroup.post_ids 加注释 |
| `tests/test_event_tracker.py` | 升级 `:225` 断言为 RawPost.id；新增 AnalyzedPost.id ≠ post_id 区分测试 |

## 5. 验证

pytest（`tests/test_event_tracker.py`）：
1. **升级现有断言**（`:225`）：从 `"post_ids" in event` 升级为断言 post_ids 里的值 = RawPost.id。
2. **新增区分测试**：构造 `AnalyzedPost(id="ap-1", post_id="raw-1")` + 对应 RawPost(id="raw-1")，跑 detect_events，断言 `EventGroup.post_ids == '["raw-1"]'`（不是 `["ap-1"]`）。AnalyzedPost.id 与 post_id 必须取不同值，才能抓住"存错 id"的回归。
3. **回归**：检查 `test_event_tracker.py:245` 的 `'["p1","p2"]'` fixture 是否依赖 AnalyzedPost.id 语义，按需调整。

集成验证：
- 单车型重跑 `detect_events_for_vehicle`，DB 查 `EventGroup.post_ids` 确认值与 `RawPost.id` 集合一致（可用 `AnalyzedPost.post_id` 反查校验）。

## 6. 涉及文件

- `pipeline/analysis/event_tracker.py`、`models/schemas.py`
- `tests/test_event_tracker.py`

## 7. 非目标（YAGNI）

- 不改字段名（`analyzed_post_ids` 重命名涉及 SQLite 迁移 + 序列化层，收益不抵成本）。
- 不写数据迁移脚本（detect_events 自动重建，期间无消费者）。
- 不全量重跑现有数据（方案 A）。
- 不动 dialog.py / 前端（它们不读 EventGroup.post_ids）。
