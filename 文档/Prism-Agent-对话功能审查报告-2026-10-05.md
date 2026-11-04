# Prism-Agent · 前端对话功能审查报告

> 审查日期：2026-10-05
> 审查范围：`prism-web`（:5173）「对话」视图，提问「银河E5最近几个月的销量怎么样？哪个版型卖得最好？」的应答异常
> 审查性质：**只读审查，未改动任何代码**
> 结论状态：根因已定位（静态链路 + 运行时日志双向印证）

---

## 0. 结论摘要（TL;DR）

1. **链路真实**：前端对话不是 mock 替答，而是真实打通到 pi Agent（前端 → `/chat/stream` → `prism-api:8002` → `pi_gateway:9100` → pi 子进程 + 工具）。
2. **"回答不对劲"的本质不是"编数"**：从运行日志看，最终数字**内部自洽**（版型明细逐月合计与 `query_sales` 月度总量 6 个月全部吻合），不存在凭空编造。
3. **真正的问题是形态与角色**：前端「对话」把**整套 pi 编码 Agent（含 bash / 文件 / MCP / 记忆 / 子代理）原样暴露给用户**，且未注入任何"面向用户的分析师"约束。于是一句卖车的问题，被当成工程任务处理——**读了 TS 源码、`netstat` 探端口、算 YoY/MoM、最后输出一篇含"工具层 bug 第 2 处"的工程复盘**。
4. **4 个可确证的缺陷**（1 个架构级 + 3 个链路级）见 §4，其中 `query_sales` 的版型能力（`group_by='spec'`）在 HTTP 链路上**三段全断**，正是"哪个版型卖得最好"逼得 Agent 绕路取数的直接原因。

---

## 1. 审查对象与方法

| 项 | 说明 |
|---|---|
| 触发 | 用户在前端提问，反馈"回答完全不对劲" |
| 方法 | ① 静态还原调用链与工具注册；② 运行时取证：从 `.pi/sessions/<user_id>/` 读取该轮真实会话日志（含工具调用轨迹与最终回答） |
| 证据强度 | 运行时日志为**一手证据**（pi 自身落盘），优于浏览器 Network 抓包 |
| 改动 | 无 |

---

## 2. 链路事实（静态）

```
prism-web (React, :5173)
  └─ ChatView.tsx  handleSend()  →  sendChat(text, cb, {sessionId})
       └─ src/lib/chat.ts  POST /chat/stream   body={message,scope,user_id,session_id}
            └─ Vite proxy → 127.0.0.1:8002
                 └─ prism-api/main.py  /chat/stream  转发 {message,user_id,scope}   ← session_id 被丢弃
                      └─ pi_gateway.mjs (Node :9100)  POST /chat
                           └─ spawn pi.exe --mode rpc --model deepseek-v4-flash
                                -e .pi/extensions/prism-guardrails/index.ts
                                PI_CODING_AGENT_DIR=.pi/agent-minimal
                                └─ Agent（业务工具 23 个 + 默认编码工具集）
```

- 工具注册：`prism-guardrails/index.ts` 注册 **23 个业务工具**（3 口径视图 + 6 舆情 + 14 Atuohome）。
- 模型：`deepseek-v4-flash`（前端 pill 显示 `Deepseek V4 Flash`，一致）。
- 前端用户身份：`getUserId()` → localStorage `prism_user_id`（形如 `usr_xxxxxxxx`），gateway **按 user_id 常驻一个 pi 子进程**。

---

## 3. 运行时证据（本次提问的真实轨迹）

**证据文件**：`.pi/sessions/usr_g5r6h5ye/2026-10-05T13-39-59-978Z_01a10c4a-ef6a-7209-8066-b653fe9a784e.jsonl`

该会话从 `你好，介绍一下你自己` 起，历经多轮，**同一条对话连续累积 25 分钟**（13:39→14:04 UTC），你的目标提问位于 **L78**，最终回答位于 **L111**：

| 轮 | 内容 | 日志行 |
|---|---|---|
| 1 | 你好，介绍一下你自己 | L4 |
| 2 | 银河E58月的销量是多少？ | L13 |
| 3 | 银河E5最近的舆情咋样？ | L30 |
| 4 | 你好，你是谁 → 验证器判"疑似编数"并注入系统话术 → 重跑 | L66 / L68 / L69 / L70 |
| 5 | **银河E5最近几个月的销量怎么样？哪个版型卖得最好？** | **L78 → L111** |

**第 5 轮该 Agent 的工具调用序列（约 30 次）**：

- `query_sales` ×2（月度量级，`year` 口径）
- `get_sales_detail` → **`Atuohome 接口错误: HTTP 400`**
- `query_config` ×1
- `bash` 大量：读取 `query_sales.ts`/`guardrails/index.ts`/`main.py` 源码、`netstat` 探 8000/8001/8002 端口、`curl` 舆情 43 条路由、计算 YoY/MoM、拼装 `trim-structure`
- `mcp`、`mem0_memory`、`memory_search` 等非业务工具
- 中间自述："**工具层又发现一处 bug——先取数，再报告。**"

**最终回答（L111）要点**：`银河E5 2026年1–8月累计 39,328 辆（YTD 同比 −42.9%）`；版型第一 = `26款 530Km 探索版`（8月 2,047 辆 / 46.1%）；并在文末列 **[必报缺口表]**，自曝"`get_sales_detail` 恒 400""`query_sales` 版型能力未暴露"。

> 关键判读：**数字没错，错的是"把一次业务问答做成了代码排障现场"**。这正是用户感知为"完全不对劲"的来源。

---

## 4. 根因分析

### 4.1 根因 A｜架构级：前端对话 = 未收窄的编码 Agent（置信度：高）

- `pi_gateway.mjs` spawn pi 时使用**默认全套工具**（bash / 文件读写 / 网络 / MCP / 记忆 / 子代理）。
- `.pi/agent-minimal/settings.json` 额外加载了 `pi-memory`、`@amaster.ai/pi-memory-mem0`、`pi-subagents`、`pi-web-access`、`rpiv-todo`、`pi-mcp-adapter`、`pi-workspace-history` 等**非业务**扩展。
- `prism-guardrails/index.ts` 的 `before_agent_start` **只注入 `AGENTS.md`**；注释所写的"注入 SYSTEM.md"并未实现——仓库中只有 `SYSTEM.md.template`（模板），**无 `SYSTEM.md`**。spec `prompt-context.md §2.1.1` 承诺的"当前对象身份 / 覆盖率 / as_of / 模式 / scope 看板 / 三维度完成度"**均未注入**。
- 后果：Agent 没有"你是面向用户的分析师、要简洁作答、不要动 bash"的任何约束；用户问业务，Agent 拿工程手段解决。

### 4.2 根因 B｜工具链断点，逼迫 Agent 绕路（置信度：高）

**B-1 `query_sales` 的版型能力（`group_by='spec'`）三段全断**——这是"哪个版型卖得最好"无法用语义工具回答的直接原因：

| 环节 | 现状 | 位置 |
|---|---|---|
| TS 实现 | ✅ 已实现 `group_by='spec'`（读 `sales_trim`） | `src/tools/query_sales.ts` L73–98 |
| 扩展工具 schema | ❌ 只暴露 `series_key` + `year` | `.pi/extensions/prism-guardrails/index.ts` L59–63 |
| 扩展 execute 透传 | ❌ 只透传 `series_key` / `tag_category` / `year` | 同上 L37–39 |
| prism-api 取数分支 | ❌ `/dashboard/sales` 无 `group_by` 分支，写死读 `mv_sales_monthly` | `prism-api/main.py` L85–98 |

→ 能力在 TS 层存在，但**到不了 Agent**；Agent 只得转投 Atuohome 原始端点取版型结构。

**B-2 `get_sales_detail` 恒 400**：扩展传 `model_id`，上游 `/dashboard/market/api/retail` **只认 `series`** → `{"error":"缺少 series 参数"}`。

**B-3 `sentiment_*` 全 404/422**：6 个舆情工具的路径与运行中的舆情服务（:8000）路由不匹配（如 `/api/dashboard/overview` 等前缀差异）。

### 4.3 根因 C｜会话连续性缺口（置信度：中）

- 前端 `chat.ts` 发送了 `session_id`，但 `prism-api/main.py` `/chat/stream` 转发时**只带 `message/user_id/scope`，丢弃 `session_id`**（L143–147）。
- 目前多轮上下文靠 gateway"按 user_id 常驻进程"顶着；一旦进程被回收（30 分钟无活动）或重启，会话上下文即断。

### 4.4 根因 D｜显示层小缺陷（置信度：低，但确证）

- `ChatView.tsx` L84 读取 `e.data.arguments`，而 gateway 实际发的是 `e.data.args`（`pi_gateway.mjs` L55）→ **工具活动面板里每个工具的入参永远显示 `undefined`**。
- `ChatView.tsx` 存在**重复的 `case 'tool_result'`**（L89–104 与 L105–113），后者为死代码。

### 4.5 附加观察｜护栏会把"系统话术"注入用户对话

- 完成验证器在 `agent_settled` 判定不通过时会 `sendUserMessage("[完成验证器] 验收未通过…")`（`index.ts` L450–452）。该消息以 **user 角色**进入会话，用户在前端会看到莫名冒出的"验收"话术（本会话 L69 真实出现过一次）。

---

## 5. 影响面

| 影响 | 说明 |
|---|---|
| 用户体验 | 简单业务问题被做成工程排障，耗时长（本例 ~25 分钟 / ~30 次工具），答案形态失控 |
| 数据可靠性 | 数字本身自洽，但**关键口径（版型）靠绕路取得**，非语义工具正规路径，稳健性差 |
| 可维护性 | 同一能力（`query_sales`）存在 TS 实现与 HTTP 实现**两套**，且以 HTTP 那套为准，易长期漂移 |
| 会话可靠性 | `session_id` 丢弃 + 常驻进程回收 → 多轮易断（根因 C） |
| 舆情维度 | 6 个 `sentiment_*` 工具全部不可用，第四组能力形同虚设 |

---

## 6. 修复建议（分层，供决策；本次未实施）

**P0（先做，直击"回答不对劲"）**
1. **收窄前端对话角色**：为对话会话注入独立 System Prompt（把 `SYSTEM.md.template` 真正渲染为 `SYSTEM.md` 并注入），明确"面向用户的分析师"定位、作答形态（先结论后简要依据）、**禁止在对话模式动用 bash/文件/源码探索**。
2. **按模式裁剪工具集**：对话（Agent）模式仅暴露业务语义工具；编码类工具（bash/文件/MCP/子代理/记忆）在对话模式下不可见或需显式提权。

**P1（打通关键口径）**
3. **贯通 `query_sales.group_by='spec'`**：扩展 schema 暴露 `group_by`/`month`/`metric`；execute 透传；`prism-api /dashboard/sales` 增加 `group_by='spec'` 分支直读 `sales_trim`。
4. **修 `get_sales_detail` 400**：在 `AUTOHOME_TOOL_MAP` 增补参数别名 `model_id → series`（或扩展侧改传参）。
5. **修 `sentiment_*` 404/422**：对齐工具路径与舆情服务实际路由。

**P2（稳健性与体验）**
6. **`/chat/stream` 透传 `session_id`**，恢复真实会话连续性。
7. **修显示层**：`ChatView` 入参字段改为 `e.data.args`；删除重复 `case 'tool_result'`。
8. **护栏话术用户可见性**：验证器回灌内容不应以"用户消息"形态出现在前端，建议走隐藏通道或折叠展示。

---

## 7. 结论与待确认

- **已确证**：链路真实；回答非编数；根因 A（角色未收窄）+ 根因 B（工具链三段断点）是"回答不对劲"的主因。
- **待用户确认**：所感知的"完全不对劲"偏向
  - **A. 形态**（太长、混入工程排障）→ 对应 P0 + P1；
  - **B. 内容**（认为最终数字/版型结论有误）→ 需对 `sales_trim` 做一次 ground-truth 复算以定位。

---

## 附录 A · 证据索引

| 编号 | 证据 | 位置 |
|---|---|---|
| E1 | 本次提问与回答的真实轨迹 | `.pi/sessions/usr_g5r6h5ye/2026-10-05T13-39-59-978Z_01a10c4a-ef6a-7209-8066-b653fe9a784e.jsonl`（L78 提问 / L111 回答 / L69 观察） |
| E2 | 工具注册（23 个）与 execute 透传 | `.pi/extensions/prism-guardrails/index.ts` L37–39 / L59–63 |
| E3 | `query_sales` 版型实现（TS） | `src/tools/query_sales.ts` L73–98 |
| E4 | `/dashboard/sales` 无 group_by | `prism-api/main.py` L85–98 |
| E5 | `/chat/stream` 丢弃 session_id | `prism-api/main.py` L143–147 |
| E6 | gateway 事件映射（args/arguments 不一致） | `prism-api/pi_gateway.mjs` L55 |
| E7 | 前端渲染与重复 case | `prism-web/src/components/ChatView.tsx` L84 / L89–113 |
| E8 | 非业务扩展清单 | `.pi/agent-minimal/settings.json` |
| E9 | System Prompt 模板未启用 | `SYSTEM.md.template`（无 `SYSTEM.md`） |