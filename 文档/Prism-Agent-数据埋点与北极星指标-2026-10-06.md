# Prism-Agent · 数据埋点与北极星指标（含"在线时长"）· 2026-10-06

> 生成日期：2026-10-06
> 主题：① 北极星指标三层（商业/产品/输入）+ **商业北极星增列"在线时长"**；② 埋点数据的**采集手段**（三层来源）；③ 现状核查（做了没）；④ 数据在哪看（查看入口）；⑤ **badcase：用户对话 + agent 轨迹的采集设计**；⑥ 附：**40 并发承载能力**（埋点采集的前提）
> 性质：**设计/方案文档**（本文档为独立输出，不改动其他文档）
> 上游依据：[项目提纲 §9.8 北极星指标三层](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-项目提纲.md#L415-L459)、[八项工作设计稿 · 第0步北极星 #star](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-八项工作设计稿.html#L175-L194)、[八项工作设计稿 · ④数据埋点 #w4](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-八项工作设计稿.html#L714-L787)、[任务清单](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-任务清单.md)

---

## 1. 北极星指标三层（含 2026-10-06 增列"在线时长"）

### 1.1 三层总表

| 层 | 指标 | 用途 | 度量难度 |
|---|---|---|---|
| **商业北极星** | **日活量 DAU**（看板 DAU + 对话 DAU 分开算）+ **在线时长**（活跃时长，看板/对话分开算） | 项目存续判断 | 易（埋点可算） |
| **产品北极星** | **周成功交付结论数**（被采纳、未点踩的结论绝对量） | 日常驱动迭代 | 中（埋点可算） |
| **输入指标** | `Pass^1 × (1−幻觉率) ÷ 单次成本` · WAU · 人均结论数 · 采纳率 · 响应时延 | 工程师可操作 | 易 |

### 1.2 商业北极星口径

**DAU 口径**（2026-10-02 定）：

- 看板 DAU = 每天至少打开一个 BI 看板页的独立本地 ID 数（含只看图表、不对话的用户）
- 对话 DAU = 每天至少发起一次 agent 对话的独立本地 ID 数
- 总 DAU = 看板 DAU ∪ 对话 DAU（去重）
- 分开算的原因：看板 = "被动消费数据"，对话 = "主动要结论"，使用深度不同

**在线时长口径**（2026-10-06 增列）：

- 定义 = **活跃时长**：每个本地 ID 每天在前端"页面可见且活跃"状态下的**累计秒数**；看板页、对话页分开算
- **刻意不用"会话时长"**（一次 SSE 连接存活时长）作口径——长分析单轮实测可达 ~25min，会让"时长"虚高失真；活跃时长更贴近"真的在用"
- 与 DAU 同源（同一本地 ID）、看板/对话分开，作为 **DAU 的厚度维度**并列入商业北极星
- 理由：**DAU 只量"来没来"（广度），在线时长量"待多久/用多深"（厚度）**；单看 DAU 会把"打开即走"误判为健康，两者合看才是完整的存续信号

### 1.3 产品北极星与输入指标

- **产品北极星 = 周成功交付结论数**：一周内 agent/看板产出的、被用户**采纳（未点踩、未撤销）**的结论绝对量；看板 + agent 双模式都计入。绝对量非比率。起步可先用"周活 × 平均结论采纳率"过渡，跑通后升级绝对量。
- **输入指标**：`Pass^1 × (1−幻觉率) ÷ 单次成本` + WAU + 人均结论数 + 采纳率 + 响应时延。注意：`Pass^1×(1−幻觉率)÷成本` 是**输入指标不是北极星本体**（驱动 agent 质量迭代）。

### 1.4 推导链（第一性原理）

```
商业层：日活量 DAU（看板 DAU + 对话 DAU 分开）+ 在线时长（活跃时长，看板/对话分开）
  ↑ 内部工具价值=融入日常工作流，"每天在用"=存活的最直接信号
  ↑ "有效决策数"难测需定性退化，DAU 可日度量、可对比、可设阈值
  ↑ DAU 只看广度（来没来）不够——在线时长量厚度（待多久/用多深）
  ↑ DAU 拆看板/对话——看板=被动消费数据，对话=主动要结论，使用深度不同
  ↑ DAU 健康 = 人来（拉新+留存）② 人待得住（在线时长）③ 人用得深（产出结论）
  ↓
产品层：周成功交付结论数（被采纳未点踩的结论绝对量）
  ↑ "被采纳"=结论进入 PM 判断体系=使用价值兑现 → 兑现多 → DAU 留得住
  ↑ "未点踩"过滤编造结论；"绝对量非比率"——40人工具，规模是第一位
  ↓
输入层：Pass¹×(1−幻觉率)÷单次成本 + WAU + 人均结论数 + 采纳率 + 响应时延
  ↑ 驱动 agent 质量迭代；本层不是北极星本体
```

---

## 2. 埋点数据的采集手段（三层来源）

### 2.1 三层职责

| # | 层 | 采集什么 | 手段（现有基础） |
|---|---|---|---|
| ① | **前端（浏览器）** | 页面级事件：看板页打开、对话发起、点踩/采纳、**心跳（在线时长）** | 用现成 `getUserId()`（`localStorage.prism_user_id`，[chat.ts L8-L12](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/lib/chat.ts#L8-L12)）打标；`Page Visibility API` + 30s 心跳累加；`navigator.sendBeacon` 上报（关页/切后台不丢）→ POST 到 prism-api 事件接口 |
| ② | **服务端网关** | 请求级事件：会话建立、每轮消息、耗时、错误、SSE 连接起止 | prism-api（FastAPI）/ pi_gateway（Node）内写日志/事件表 = 零额外基建 |
| ③ | **pi 扩展 hook 层** | agent 轨迹级：`tool_call` / `tool_execution_end`（工具结果）/ `turn_start`·`turn_end` / `agent_settled` / `session_shutdown`，含结论产出、**evidence 行 ID**、`as_of` | pi 扩展 API 已提供这些 hook（[extensions.md](file:///c:/Users/<you>/Desktop/Prism-Agent/pi-windows-x64/docs/extensions.md)）→ 落 `trajectories.jsonl` |
| ④ | **复用 Langfuse**（旁路） | 已自动抓 pi turn / tool | 已有 `@langfuse/pi-observability-plugin`，但需加 Prism 领域属性才有用（当前只有 `Pi Turn`/`Conversational Turn`/`tags=pi`） |

### 2.2 事件清单（建议）

| 事件 | 来源层 | 关键字段 | 喂哪个指标 |
|---|---|---|---|
| `page_view`（看板页打开） | 前端 | `local_id, page, series_key, ts` | 看板 DAU |
| `chat_start`（发起对话） | 前端 | `local_id, session_id, ts` | 对话 DAU |
| `active_tick`（心跳，每 30s） | 前端 | `local_id, page, ts` | **在线时长** |
| `page_hide` / `page_unload` | 前端 | `local_id, page, duration` | **在线时长**（补尾） |
| `feedback`（点踩 / 采纳） | 前端 | `local_id, session_id, conclusion_id, value` | 产品北极星 |
| `session_created` | 网关 | `session_id, local_id` | 会话 |
| `chat_turn` | 网关 | `session_id, msg, latency_ms, ok` | 输入指标（时延/错误率） |
| `conclusion_emitted` | pi hook | `session_id, conclusion, evidence_ids, as_of` | 产品北极星 |
| `tool_call` / `tool_execution_end` | pi hook | `session_id, tool, input, output, status, latency_ms` | 输入指标 |
| `session_shutdown` | pi hook | `session_id, final_status` | 轨迹收尾 |

### 2.3 汇聚与存储

- **汇聚点 = 同一本地 ID**：三层用**同一本地 ID（=轨迹 `session_id`）**串起来 → 落**一张事件表（SQLite）** → 后期接 metabase / 自建看板查北极星。
- 如此才能把"**人（DAU/在线时长）→ 会话（轨迹）→ 结论（采纳）**"关联起来（也是"无登录 + 本地 ID"方案成立的前提，见 [任务清单 D0.2](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-任务清单.md#L34)）。
- 存储取舍（待拍板）：事件库与评估快照库**共用** vs **独立**。

### 2.4 脱敏（落盘前第一道防线）

- 落盘前过 regex_sanitizer（通用 14 类正则 + Luhn 校验）；**补汽车场景字段：VIN 车架号（17 位）、车牌号**（口碑原文常见）。
- 本地小模型 Level3 脱敏必抄核验：`value.lower() in text.lower()` 才接受（模型会编造文本里没有的 PII）。

---

## 3. 现状核查：做了没？

**结论：设计做了，落地基本为零。**

### 3.1 设计侧（做了，且完整）

- 北极星三层 + ④数据埋点方案在 [八项工作设计稿](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-八项工作设计稿.html) 有专章；2026-10-06 已把"在线时长"补入商业北极星。

### 3.2 落地侧（没做）

**任务清单相关项全为未勾选 `[ ]`**（[Prism-Agent-任务清单.md](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-任务清单.md)）：

| 编号 | 任务 | 状态 |
|---|---|---|
| D3.7 | badcase 轨迹埋点（`trajectories.jsonl`） | `[ ]` 未做 |
| D5.1 | 反馈通道实装 | `[ ]` 未做 |
| D5.2 | 点踩带 `session_id` 入库 | `[ ]` 未做 |
| D5.3 | 使用数据分析 | `[ ]` 未做 |
| D5.4 | 产品北极星度量 | `[ ]` 未做 |
| D5.5 | 脱敏引擎（含 VIN/车牌） | `[ ]` 未做 |
| D7.2 | 三层北极星验证 | `[ ]` 未做 |

**运行时代码实测证据**：

- 全仓无 `trajectories.jsonl`（该词仅出现在设计稿/学习笔记）
- 前端无点踩/采纳/反馈 UI；无心跳/在线时长上报
- 后端 [main.py](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py) 仅有 `/dashboard/{dtype}`、`/chat/stream`、`/session`(GET/POST)、`/sentiment-board/*`、`/health` —— **无 feedback / track / event / dau / metrics 任何端点**
- 无 DAU / 在线时长统计
- `pi_gateway.mjs` / `prism-api` 零埋点
- Langfuse 只有 pi 通用 trace（`Pi Turn` / `Conversational Turn` / `tags=pi`），无 Prism 领域事件
- **唯一半成品**：本地 ID —— `getUserId()`（`localStorage.prism_user_id`）已存在，但仅用于会话隔离/传 `user_id`，未接埋点

### 3.3 影响

- **商业北极星（DAU + 在线时长）目前算不出来**：无页面事件、无 heartbeat。
- **产品北极星（周成功交付结论数）目前算不出来**：无"结论产出事件"、无"点踩/采纳事件"、无轨迹落盘。
- 与主报告核心判断一致：**"设计完备度 ≫ 运行时落地度"**。

---

## 4. 我去哪里看这些数据？（查看入口）

### 4.1 现在能看的（2 个）

| 入口 | 能看什么 | 局限 |
|---|---|---|
| **Langfuse UI** `http://localhost:3000` | pi 每轮 turn + 工具调用（trace） | 只有 pi 通用字段（`Pi Turn` / `Conversational Turn` / `tags=pi`），**无 Prism 领域层**（无 series_key / 维度 / as_of / 采纳） |
| **磁盘 pi 会话原生日志** [`.pi/sessions/<user>/<ts>_<id>.jsonl`](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/sessions) | **当前唯一能看到"完整对话 + agent 轨迹"的地方**（已积 40+ 文件） | pi 原始格式；无脱敏 / 无 evidence / 无采纳标记 |

> 前端左栏"会话"列表也能列出会话，但行**不可点**、打不开。

### 4.2 想看却没地方看的（未落地）

- 埋点事件表 / DAU / 在线时长 / **北极星看板** → 无
- **metabase** → 仓库里没有（Glob `**/metabase*` 零结果），设计里写"后期接"
- **badcase 面板 / 轨迹回放工具** → 无

### 4.3 设计里规划的查看入口（未来）

- 近期：**自建北极星看板**（读事件表 SQLite）
- 中期：接 **metabase** 直查事件表 / 评估快照库
- 旁路：**Langfuse**（补 Prism 领域属性后可用；`Annotation Queues` 做人审金标，见[评估体系 §9 第 13 项](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-评估体系完整方案.md#L348-L353)）

---

## 5. badcase：怎么搜集"用户对话 + agent 轨迹"？（有设计）

### 5.1 结论：有设计，且相当完整

落在 3 处：[评估体系完整方案 §7–§8](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-评估体系完整方案.md#L273-L355)、[八项工作设计稿 #w4](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-八项工作设计稿.html#L714-L787)、任务清单 [D3.7](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-任务清单.md#L107)/[D5.2](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-任务清单.md#L136)/D5.5。

### 5.2 闭环机制

```
用户点踩 → session_id 入库 → 拉该 session 完整轨迹回放归因 → 定位失败维 → 自动转新评测题
```

- **三源**（§8.2）：① LLM 生成 + 人审 ② 点踩回流 ③ **生产轨迹挖掘**（离线扫全量 session → 找异常模式 → 转题）
- **归因**：badcase 五维归因（§7.2）+ 两层回归（§7.3：端到端 / **轨迹前缀截取**测决策边界）
- **门禁**：评测即 CI（§8.3，变更触发回归）

### 5.3 轨迹字段设计（#w4）

`trajectories.jsonl` 按 `session_id` 记：完整对话 + 每轮 `tool_call`/`tool_result` + **状态栏快照** + `final conclusion` + **evidence 行 ID** + `as_of`；并定期跑诊断 Agent 自动定位、生成回归用例。

### 5.4 关键发现：数据源已在被动产生

**"搜集对话 + 轨迹"不缺"采集"** —— pi 自己就会把**完整对话 + 每轮工具调用**写成 `.pi/sessions/*.jsonl`（已积 40+ 个）。缺的是 **Prism 侧加工层**：

| 缺的加工 | 内容 |
|---|---|
| 脱敏 | 补 VIN / 车牌正则（原有 14 类正则不足） |
| 结构化 | 补 evidence 行 ID / as_of / 状态栏快照 |
| 反馈标记 | 点踩带 `session_id` |
| 归因 | badcase 五维归因 |
| 转题 | 自动进评测集（动态评测集） |

### 5.5 现状

任务清单 D3.7 / D5.2 / D5.5 **全为 `[ ]`**；评估体系 §9 缺口表也自认：**动态评测集=无、两层回归=无、badcase 五维归因=现 3 维缺 1 维（权限边界）**。→ **设计有、实现无。**

---

## 6. 待拍板 / 下一步

**待拍板**：

1. 事件库与评估快照库**共用** vs **独立**（SQLite）。
2. 前端上报端点命名与鉴权（无登录下的本地 ID 防伪策略）。
3. 在线时长心跳间隔（建议 30s）与"活跃"判定阈值（如连续无交互 > N 分钟不计）。
4. Langfuse 与自建事件表：**双写** vs **仅以 `session_id` 关联**。

**下一步（收敛顺序）**：

1. 前端极简 SDK：`page_view` / `chat_start` / `active_tick` / `feedback` + `sendBeacon` 上报。
2. prism-api 加事件接收端点 + SQLite 事件表。
3. pi 扩展 hook 层落 `trajectories.jsonl`（含 `conclusion_emitted` + `as_of`）。
4. 落盘前接脱敏（补 VIN / 车牌正则）。
5. 跑通后即可算 DAU + 在线时长（商业北极星）；再定义"一条结论 / 被采纳"算产品北极星。

---

## 7. 附：40 并发承载能力（埋点采集的前提）

> 本条为**附带核查**。与"埋点/北极星"的关系：**埋点要采得到，前提是服务在高并发下不崩**——若 40 并发下进程 OOM 或请求被拒，`page_view` / `chat_start` / `feedback` 等事件本身就采不全，北极星也就无从统计。完整结论见主报告 [§5 第 10 条](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-PM推理能力与Harness成熟度评估-2026-10-05.md#L302) / [附录 H10](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-PM推理能力与Harness成熟度评估-2026-10-05.md#L348)。

### 7.1 裁决

| 场景 | 能否撑住 | 说明 |
|---|---|---|
| 40 人**日常使用**（不同时刻各自提问） | ✅ **理论可行** | DeepSeek 远程 API、I/O bound；网关有 30min 空闲回收，多数时刻在途远少于 40 |
| 40 人**同一时刻并发对话** | ❌ **不能保证** | 40 个常驻进程无上限、无排队、无背压；单用户连发被拒；长分析 300s 被切 |
| 生产可信赖交付 | ❌ **不能** | 未压测 + 无并发监控（D3.8 未做）+ 无告警 |

**一句话**：**"40 人日常用得动"成立；"40 人真并发"是设计口径，实现没兑现、也没验证过。**

### 7.2 实现层证据（[pi_gateway.mjs](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs)）

| # | 机制 | 代码 | 对并发的含义 |
|---|---|---|---|
| 1 | **每用户一 RPC 进程** | [L232-L266](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L232-L266)：`pool = new Map() // userId → RpcClient`，每用户 `spawn('pi.exe', …)` | 40 活跃用户 = **最多 40 个常驻 pi 进程**（非共享） |
| 2 | **无池上限** | `pool` 无 MAX / 无淘汰（除 disposed） | 人数 ↑ → 进程数**线性 ↑**，无保护 → OOM 风险 |
| 3 | 30 分钟空闲回收 | [L268-L278](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L268-L278)：`lastActive>30min → dispose` | ✅ 不活跃进程会释放；但活跃期仍同时驻留 |
| 4 | 同用户串行 = **直接拒绝** | [L317-L327](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L317-L327)：第二个请求返回 `"上一个请求仍在进行中"` | ❌ 多标签页/连发被**拒绝**，非排队 |
| 5 | 单轮 300s 超时 | [L179-L189](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L179-L189)：超时发 `abort`、丢弃迟到响应 | ❌ 长分析（实测曾 25min）被中途打断 |
| 6 | 仅 `/health` 暴露 `poolSize` | [L292-L296](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L294) | 有池大小可见；**无并发指标/告警/限流** |

**没有**：并发上限、排队、背压、限流、`429/503` 保护 —— 网关里一处都没有。

### 7.3 设计与实现的偏差（关键）

spec [项目提纲 §5.7](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-项目提纲.md#L200-L205) 与 [运行流程 html L250](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-运行流程.html#L250) 的原话是：

> **40 并发 = 1-2 个 pi 进程异步跑多个这样的循环**，DeepSeek 远程 API I/O bound，单机 4c16g 富余 3 倍。

**而实现是"每人 1 个 pi 进程"——40 人 = 40 个进程，不是 1-2 个。** 因此 spec"富余 3 倍"的资源估算**在实现层不成立**：真正吃资源的是 **40 个常驻 Node/pi 进程的内存**，不是算力。

### 7.4 验证现状：**从未压测**

spec 自己列过要验证：§5.4 spike 清单第 1 条"开多个并发会话（验证 40 峰值并发）"、[§9 待办第 3 条](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-项目提纲.md#L498)"40 并发验证"、任务清单 [D3.8](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-任务清单.md#L108)"40 并发下错误可观测"。**但仓库里没有任何 40 并发压测记录** → 等于未验证。

### 7.5 要撑住 40 真并发，最少要补

1. **池上限 + 排队**（信号量/LRU）：超出上限排队或返回 503，而非无限 spawn；
2. **同用户锁改排队**（或真并行 + 请求隔离），别直接拒绝；
3. **超时改分段/可配**（长分析别 300s 一刀切）；
4. **补 40 并发压测**（spec §5.4 早列，属欠债）；
5. **D3.8 轻量监控**：并发数/拒绝数/进程内存可观测告警。

---

## 附：本文与既有文档的关系

- 本文为**独立输出**，是对[项目提纲 §9.8](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-项目提纲.md#L415-L459) 与[八项工作设计稿 #star / #w4](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-八项工作设计稿.html#L714-L787) 的**汇总与增补**；"在线时长"与"三层采集手段"同步写入了上述两份上游文档与任务清单 D0.3，四者口径一致。
- 本文 §5（badcase 轨迹采集）是对[《评估体系完整方案》§7–§8](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-评估体系完整方案.md#L273-L355) 的**汇总**，不改变其口径。
- 如遇口径不一致，以**项目提纲 §9.8** 为唯一事实源。