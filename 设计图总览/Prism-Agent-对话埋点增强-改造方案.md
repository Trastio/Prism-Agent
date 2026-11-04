# Prism-Agent · 对话埋点增强方案

> 2026-10-07
> 起因：用户"能不能看到用户实际上有多少轮对话，我想统计，做数据埋点"
> 性质：**改造方案**（待审阅，审阅通过后施工）
> **依赖**：《对话 Agent 架构重构方案》§三 层 0（会话隔离）——**session_id 真实化**是本方案的前提
> 审查方法：读前端 tracker / ChatView / Sidebar / App + 后端 `/events` + extension `trajectories.jsonl`

---

## 一、目标

回答四个问题：

1. **用户有多少轮？**（按用户聚合）
2. **每个会话多少轮？**（按会话聚合）
3. **轮次分布？**（人均/会话均/长尾）
4. **轮次质量？**（tier / 耗时 / 工具调用数 / 验证通过率）

---

## 二、现状：已有链路（可复用，不重建）

| 层 | 位置 | 现状 |
|---|---|---|
| 前端 SDK | `prism-web/src/lib/tracker.ts` | 事件 `page_view` / `chat_start` / `active_tick`(30s 心跳) / `feedback` / `chat_settled` / `session_switch` / `session_rename`；sendBeacon 上报 + VIN/车牌脱敏 |
| 触发点 | `ChatView.tsx` L91 / L154 | `chat_start` = **每发一条用户消息一次**（value=问题前 80 字）；`chat_settled` = **每轮回答结束一次**（value=verdict） |
| 后端接收 | `prism-api/main.py` L103-142 | `POST /events` → SQLite `prism_events.db`，表 `events(event_type, local_id, session_id, page, series_key, value, ts)`，已建 `type_ts / session / local` 索引 |
| 后端统计 | `prism-api/main.py` L145-175 | `GET /events/stats` 已算 DAU / chat_dau / 周结论数 / 反馈计数 |
| 服务端 per-turn | `prism-guardrails/index.ts` L574-603 | 每轮写 `.pi/sessions/trajectories.jsonl`：`sessionId / timestamp / conversation / toolCalls / toolResults / final_conclusion / evidence_ids / as_of / scope / verdict`——**本身就是 per-turn 埋点** |
| 其他 | — | per-session `verdict.json`；pi_bridge 的 langfuse |

**结论**：链路已通，缺的只是**轮次维度**与**会话真实性**。

---

## 三、口径定义（先定口径，再埋点）

| 口径 | 定义 | 数据源 |
|---|---|---|
| **用户** | `local_id`（前端 localStorage `prism_user_id`，假名） | events 表 |
| **会话** | 一条 `.jsonl` 会话文件（**层 0 后的真实 session_id**） | events 表 / 会话文件 |
| **轮（turn）** | 一条用户消息 = 一次 `chat_start` = 一次 `chat_settled` | events 表 |
| **轮次质量** | tier / 耗时 / 工具数 / verdict | `trajectories.jsonl` |

> **暂定**：一轮 = 一次用户提交（含追问），不把"点击建议问题"另算；若需区分，后续加 `source` 字段。

---

## 四、缺口（必须解决的问题）

### 缺口 1（致命）：`session_id` 是假的

前端 `setSessionContext(e.data.session_id)`（ChatView L98），而网关 `session_info` 返回的是 **`userId`**（见重构方案 §二 问题 6）→ **所有会话都归到同一个 id**，按会话分组统计全部失真。

**解决**：
- **首选**：先做重构方案层 0（会话隔离），`session_info` 返回真实会话 id（`get_state.sessionId`）。
- **过渡（默认）**：若层 0 未就绪，本期统计只做**按用户**维度，会话维度标记为"不可用"，不产出错误数字（红线：不编造）。

### 缺口 2：`chat_start` 的 `value` 存了问题内容

`ChatView.tsx` L91 `track('chat_start', { value: text.slice(0, 80) })`——属**内容留存**，纯统计不需要，且有隐私面。

**解决（定案）**：`chat_start` **去掉 `value`**，只保留结构化字段。若确需留存问题文本，另立"内容留存"授权项，不混在埋点里。

### 缺口 3：缺轮次与质量维度

`events` 表没有 `turn_index`（会话内第几轮）/ `latency` / `tier` / `tool_count`。

**解决**：
- **轮次序 + 耗时**：前端补（见层 2）。
- **tier / 工具数**：**不双写**，直接取服务端 `trajectories.jsonl`（已含 `toolCalls` 与 `verdict`，只需补 `tier` 字段）。
- `events` 表加列需迁移（见层 2）。

---

## 五、改造方案

### 层 1：会话 id 真实化（依赖重构方案层 0）

- 网关 `session_info` 返回**真实会话 id**（`get_state.sessionId`），与 `/session` 列表 id 同源。
- 前端 `setSessionContext(真实 session_id, ...)`。
- **这是本方案的前置**；未就绪前只出"按用户"统计。

### 层 2：字段补齐（最小改动）

**前端 `tracker.ts` / `ChatView.tsx`**：
- 维护会话内轮次计数器 `turnIndex`：**新建会话归零**；**切换到已有会话时 = 该会话已有 user 消息数**（由层 0 的 `/session/messages` 历史推导，与层 0 一致，**不是无脑归零**）。
- `chat_start` 增 `turn_index`；**去掉 `value`**（缺口 2）。
- `chat_settled` 增 `turn_index` / `latency_ms`（发送 → settled 的耗时）。
- `track()` 的 payload 支持 `turn_index` / `latency_ms` 透传。

**后端 `main.py`**：
- `_init_events_db()` 迁移：为 `events` 表补列 `turn_index INTEGER`、`latency_ms INTEGER`（`ALTER TABLE ... ADD COLUMN`，幂等判断 `PRAGMA table_info`）。
- `post_events` 写入这两个新字段。

**服务端 `index.ts`**：
- `appendTrajectory` 行对象补 `tier` 字段（`tool_count` 由 `toolCalls.length` 得出，不另存）。

### 层 3：统计口径与端点

扩展 `GET /events/stats`（或新增 `/events/turns`）：

```sql
-- 每个用户总轮数
SELECT local_id, COUNT(*) n FROM events WHERE event_type='chat_start' GROUP BY local_id;
-- 每个会话轮数（依赖层 1 的真实 session_id）
SELECT session_id, COUNT(*) n FROM events WHERE event_type='chat_start' GROUP BY session_id;
-- 轮次分布
SELECT n, COUNT(*) users FROM (SELECT local_id, COUNT(*) n FROM events WHERE event_type='chat_start' GROUP BY local_id) GROUP BY n;
```

新增返回：`avg_turns_per_user` / `avg_turns_per_session` / `turn_distribution`。
质量维度（tier / 工具数 / verdict 通过率）从 `trajectories.jsonl` 聚合，按 `sessionId` 与 events 关联。

### 层 4：会话列表直接显示轮数（不依赖埋点）

`GET /session` 用 RPC `get_state.messageCount` 返回轮数，前端会话列表显示"N 轮"——**层 0 顺带实现即可**。

---

## 六、改造清单

| # | 文件 | 改动 | 层 |
|---|---|---|---|
| 1 | pi_gateway.mjs | `session_info` 返回真实 session_id（依赖重构方案层 0） | 会话 |
| 2 | ChatView.tsx | 维护 `turnIndex`（新建归零 / 切已有会话续接）；`chat_start` 增 `turn_index`、**删 `value`**；`chat_settled` 增 `turn_index` / `latency_ms` | 埋点 |
| 3 | tracker.ts | `track()` payload 支持 `turn_index` / `latency_ms` 透传 | 埋点 |
| 4 | main.py `_init_events_db` | 迁移补列 `turn_index` / `latency_ms`（幂等） | 埋点 |
| 5 | main.py `post_events` | 写入 `turn_index` / `latency_ms` | 埋点 |
| 6 | main.py `events_stats` | 增 `avg_turns_per_user` / `avg_turns_per_session` / `turn_distribution` | 统计 |
| 7 | index.ts `appendTrajectory` | 行对象补 `tier` 字段 | 埋点 |
| 8 | pi_gateway.mjs `GET /session` | 返回 `messageCount`（`get_state`） | 会话 |

---

## 七、改后行为

| 场景 | 结果 |
|---|---|
| 用户发第 3 条消息 | `chat_start{turn_index:3}` 入库（无 `value`） |
| 第 3 轮结束 | `chat_settled{turn_index:3, latency_ms:…, value:verdict}` 入库 |
| 查某用户轮数 | `SELECT COUNT(*) FROM events WHERE event_type='chat_start' AND local_id=?` |
| 查某会话轮数 | 同上按真实 `session_id` 分组（依赖层 1） |
| 会话列表 | 显示"N 轮"（层 0 顺带） |
| 质量统计 | 从 `trajectories.jsonl` 聚合 tier / 工具数 / verdict 通过率 |

---

## 八、验收

1. `chat_start` 不再含问题明文字段（无 `value` 或 `value=''`）
2. `chat_start` / `chat_settled` 均带连续 `turn_index`；新建会话从 1 起，切到已有会话从"该会话已有轮数 + 1"续接
3. `chat_settled` 带合理 `latency_ms`（>0）
4. `events` 表存在 `turn_index` / `latency_ms` 列且写入正确（迁移幂等，重跑不报错）
5. `/events/stats` 返回 `avg_turns_per_user` / `avg_turns_per_session` / `turn_distribution`
6. 用户维度轮数统计正确（可抽 1 个 local_id 人工核对）
7. **会话维度**：层 1 完成后 session_id 非 userId，分组结果与 `.jsonl` 会话文件数一致；**层 1 未完成时该维度不产出数字**
8. `trajectories.jsonl` 每行含 `tier`
9. 会话列表显示"N 轮"（层 0 顺带）
10. 脱敏仍生效（VIN / 车牌不落库）

---

## 九、不做

- 内容全量留存（问题/结论原文）——除已授权项外不采集
- 第三方埋点外发（不外传用户数据）
- 实时看板 UI（本期只出数据与端点）
- 去重口径之外的复杂行为漏斗（如点击热区）

---

## 十、施工顺序与依赖

1. **前置**：重构方案层 0（会话隔离）——解决缺口 1、并提供层 4 轮数。
2. **本方案层 2**（字段补齐 + 迁移 + 去 value）——可先做，只影响字段。
3. **本方案层 3**（统计端点）。
4. **本方案层 4**（会话列表轮数，随层 0 落地）。

> **风险**：缺口 1 未解前，任何"按会话"的数字都不可信；本期必须遵守"不产出错误数字"的红线（缺口 1 过渡策略）。

---

## 十一、对 Harness / 整体架构的影响

**结论：本方案是"旁路观测"——不改 Harness 决策逻辑、不新增运行时组件、对整体架构无结构性影响。**

| 维度 | 是否受影响 | 说明 |
|---|---|---|
| 提示词 / 上下文（Harness 注入） | **否** | 埋点不进入 prompt，不影响层 1 分层注入 |
| 验证层（Harness 护栏） | **否** | 不改 verifyWeb / verifyScope / tier 路由逻辑 |
| 工具层 / 会话层 | **否** | 不增删工具、不改会话机制（只消费其 session_id） |
| 留痕扩展（index.ts） | **轻度** | 仅给 `appendTrajectory` 行对象**加 `tier` 字段**（纯附加，不动判定） |
| 运行时组件 | **否** | 不新增进程 / 服务；复用既有 `/events` + SQLite + `trajectories.jsonl` |
| 数据面 | **新增一路消费** | 见下"双真值源"风险 |

**唯一结构性风险——双真值源**：
- 现状已有两套记录：**前端**写 `events` 表（轮次），**服务端**写 `trajectories.jsonl`（质量）。
- 若边界不清，将来会出现"events 说 10 轮、trajectories 说 9 轮"对不上。
- 本方案的分工（**须固化**）：**轮次 / 用户 / 会话维度 → events 表**；**质量维度（tier / 工具数 / verdict）→ trajectories.jsonl**；以 `session_id` 关联。**禁止两边都记轮次。**

**与《对话 Agent 架构重构方案》的交叉点**：
- **强依赖**：层 0（会话隔离 / `session_info` 返真实 id）→ 同时解决本方案缺口 1 与层 4。
- **同根因**：重构方案 §八"事件契约语义错（`session_info` 返 userId）"与本方案缺口 1 是同一处。
- **施工交叉风险**：重构方案清单 15"删除 memory.json 写入（L605-627）"与本文件 `appendTrajectory`（L574-603）**在同一函数 `agent_settled` 内相邻**——删 memory 时**严禁连带删掉 `appendTrajectory`**（否则本方案的埋点数据源直接消失）。

---

## 十二、待决策与待核实

**待决策（2 项，均已给默认值，可据此施工）**：
1. **缺口 1 过渡策略**：→ **默认只做"按用户"维度**，会话维度不产出数字。
2. **`chat_start` 的 `value`**：→ **默认全删**（不留问题文本）。

**待核实（1 项，不阻塞）**：
1. 前端 `agent_settled` 事件是否携带 `tier`；若未携带，`tier` 一律由服务端 `trajectories.jsonl` 提供（本方案已按此设计）。

---

## 十三、收敛状态（2026-10-07 审计）

**结论：已收敛**（口径唯一、边界明确、待决策均已给默认值）。

- 编号连续：缺口 1-3 / 层 1-4 / 清单 1-8 / 验收 1-10。
- 口径唯一：轮 = `chat_start`；质量维度只认 `trajectories.jsonl`。
- 依赖明确：前置 = 重构方案层 0；本方案不反向影响架构。
- **已修正**：`turn_index` 在"切到已有会话"时**续接该会话轮数**（非归零），与层 0 历史加载一致。
- 待决策 2 项均已给默认值；待核实 1 项不阻塞。