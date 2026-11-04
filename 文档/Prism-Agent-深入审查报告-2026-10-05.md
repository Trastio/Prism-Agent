# Prism-Agent · 深入审查报告（并发 / 双类用户 / 与 pi 的耦合）

> 审查日期：2026-10-05
> 审查根目录：`c:\Users\<you>\Desktop\Prism-Agent`
> 审查议题：① 多人并发对话能力；② 同服务汽车 PM 与普通用户（聊天/查资料）；③ Prism-Agent 是否与 pi-agent 脱勾（Langfuse 只见 pi trace）
> 审查性质：**只读审查，未改动任何代码**

---

## 0. 结论摘要（TL;DR）

| 议题 | 结论 | 一句话 |
|---|---|---|
| ① 多人并发 | **部分满足，有硬伤** | 不同用户各占一个常驻 pi 子进程、可并行；但**无进程池上限、无排队、同一用户串行**，进程数随在线人数线性增长 |
| ② 双类用户 | **未分治** | 没有角色/模式分流：`scope→工具白名单` 机制是**死代码**，System Prompt 只有面向 PM 的 `AGENTS.md`，普通用户被硬塞进 PM 的 SOP |
| ③ 与 pi 脱勾 | **没有脱勾，反而是薄封装** | 业务逻辑全在 pi 扩展里、会话/循环/观测都来自 pi；**Prism 自身领域层零可观测**，且 Langfuse 当前 key 未配、评估场景又被 `--no-extensions` 关掉 |

---

## 1. 架构事实（分层）

```
[前端] prism-web (React, :5173)
   │  POST /chat/stream  {message, scope, user_id, session_id}
   ▼
[网关] prism-api (FastAPI, :8002)  main.py
   │  /chat/stream  转发 {message, user_id, scope}      ← session_id 被丢弃
   │  /session      → 转发（注释称 Redis，实为文件系统）
   ▼
[编排] pi_gateway.mjs (Node, :9100)
   │  pool: userId → RpcClient（每用户一个常驻 pi.exe）
   │  inflightLocks: userId → 串行锁
   ▼
[底盘] pi.exe --mode rpc --model deepseek-v4-flash
   │  -e .pi/extensions/prism-guardrails/index.ts   （23 个业务工具）
   │  PI_CODING_AGENT_DIR=.pi/agent-minimal        （通用插件：web-access/memory/subagents/mcp/todo…）
   ▼
[业务服务] 舆情 Board(:8000) · Atuohome(:8001)  ← 由业务工具经 prism-api 反代调用
```

**关键判读**：Prism 的"自有代码"只有三块——`prism-api`（网关）、`prism-guardrails` 扩展（业务工具+护栏）、以及外部业务服务；**Agent 主循环、会话管理、观测全部来自 pi**。

---

## 2. 议题一：多人并发对话

### 2.1 现状机制（`prism-api/pi_gateway.mjs`）

| 机制 | 实现 | 位置 |
|---|---|---|
| 进程模型 | `pool: userId → RpcClient`，**每用户一个常驻 pi.exe** | L233–265 |
| 复用/创建 | `getOrCreateRpc()` spawn `pi --mode rpc ...` | L235–265 |
| 同用户并发 | `inflightLocks` 串行锁：前一个请求未结束 → 直接回 `上一个请求仍在进行中`（**非排队**） | L36–37 / L316–325 |
| 单次超时 | RPC `send()` **300000ms** 超时后 `abort` | L170–189 |
| 空闲回收 | 每 60s 扫描，**30 分钟无活动** `dispose()` | L267–277 |
| 池上限 | **无**（无 maxPool / 无队列 / 无限流） | 全文无 |

### 2.2 会话与持久化

- 会话落盘：`.pi/sessions/<user_id>/*.jsonl`（网关 `/session` 直接扫目录，L359–380）。
- `prism-api/main.py` 的 `/session` 只是转发（L161–175）。**全仓未实装 Redis**（grep 仅命中 lockfile 传递依赖与学习笔记）：`main.py`/`pi_bridge.py` 注释里的"Redis-backed SessionManager"**从未落地**。
- `/chat/stream` **丢弃 `session_id`**（main.py L143–147）。

### 2.3 瓶颈与失败模式

1. **进程数 = 在线用户数**，且每个 pi.exe 叠加 memory/subagents/mcp 等插件 → 内存随在线人数线性增长，**可能 OOM**；无上限、无背压。
2. **同一用户无法并行**：同一浏览器 `user_id` 来自 localStorage（`chat.ts` L8–15），多标签页共享同一身份 → 第二个请求被锁**直接报错**。
3. **单轮 300s 上限**：长分析（实测曾 ~25 分钟）会超时 abort。
4. **30 分钟回收**会结束进程；会话可从磁盘恢复，但进程内 in-memory 态丢失。
5. **数据层**：`prism_views.db` 为 SQLite 单写（项目文档 `设计图总览/Prism-Agent-项目提纲.md` L231 已指出高并发下单写锁风险）。

### 2.4 结论

**"多人并发"在"不同用户"这一维度成立**（进程级隔离，且模型侧 DeepSeek 配额宽裕）；但**缺少并发治理**（无池上限、无排队、无每用户限流），且**同用户串行**、**单轮超时偏短**。面向 40 人量级可跑，但缺少过载保护，属于"能用但脆"。

---

## 3. 议题二：双类用户（汽车 PM / 普通用户）

### 3.1 工具供给

- **业务工具 23 个**（PM 向）：`prism-guardrails/index.ts` L53–221（3 口径 + 6 舆情 + 14 Atuohome）。
- **通用能力**（普通用户向）：`.pi/agent-minimal/settings.json` L2–18 载入 `pi-web-access`（联网检索）、`pi-memory`/mem0（记忆）、`pi-subagents`、`rpiv-todo`、`pi-mcp-adapter`、`pi-workspace-history` → **基础"聊天/查资料"能力其实是具备的**。

### 3.2 角色/模式机制：**端到端失效**（关键发现）

| 环节 | 应有职责 | 实际 |
|---|---|---|
| `scope → 工具白名单` | 按 `mode`/`board` 收窄工具集 | 定义在 `prism-api/pi_bridge.py` L19–44，但该模块 `create_session()` **直接 `raise NotImplementedError`**（L80），且**全仓无任何 import**（grep 仅命中自身定义 + main.py 注释）→ **死代码** |
| 前端 | 传 `scope` | `chat.ts` L16–28 传 `{mode:'agent'}` |
| 网关转发 | 消费 `scope` | `main.py` L146 把 scope 转发给 gateway |
| 编排消费 | 按 scope 设工具集 | `pi_gateway.mjs` 的 `/chat` **只发 `{message}`**（L332）→ **scope 被彻底忽略** |

→ 结论：**"BI/看板锁工具白名单""Agent 全量"这类模式分流从未生效**；所有会话一律拿到全量工具。

### 3.3 System Prompt：只有 PM 的 SOP

- `prism-guardrails` 的 `before_agent_start` **只注入 `AGENTS.md`**（L357–367）。
- 仓库里只有 `SYSTEM.md.template`（模板），**无 `SYSTEM.md`**；spec 承诺的"当前车系/覆盖率/as_of/模式/scope"上下文**从未注入**。
- `AGENTS.md` 是长而强的 PM 纪律（棱镜三维度 + 报告纪律六条 + 强制 `resolve_series` + CLAIM 结构）——**对"普通用户闲聊"是负担与误导**。

### 3.4 结论

两类用户**当前被同一套提示词 + 同一份全量工具硬塞在一起**：普通用户能聊天/查资料（通用工具在），但会被 PM SOP 推着输出"三维度+CLAIM"式重回答；而"看板单轮问答"等模式锁又没生效。**需要补齐"角色/模式"分流（提示词 + 工具白名单 + scope 贯通）**。

---

## 4. 议题三：与 pi-agent 的耦合 / 脱勾 & 可观测性

### 4.1 归属划分

| 能力 | 归属 | 证据 |
|---|---|---|
| Agent 主循环 / RPC | **pi** | `pi_gateway.mjs` L250 spawn `pi.exe` |
| 会话管理 | **pi** | `--session-dir`，`.pi/sessions/**` |
| 业务工具（23 个） | **Prism**（寄居 pi） | `.pi/extensions/prism-guardrails/index.ts` |
| 护栏（block/grounding/验证器） | **Prism**（寄居 pi） | 同上 L371–453 |
| LLM 调用 / 通用 tool span 观测 | **pi**（Langfuse 插件） | `.pi/agent-minimal/settings.json` L5 |
| 业务数据服务 | **Prism**（外部进程） | 舆情 :8000 / Atuohome :8001 / prism-api :8002 |

→ **Prism-Agent = pi 底盘 + Prism 扩展 + Prism 外部服务**，是**薄封装**而非独立服务。**没有脱勾**。

### 4.2 Langfuse 到底能看到什么

- 集成方式：`@langfuse/pi-observability-plugin`（**pi 的插件**），hook 的是 pi 的 `tool_execution_start/end`——`eval/langfuse_writer.ts` L4–5 明确记录"**自建工具全覆盖**"。
- 含义：业务工具（`query_sales` 等）**能出现在 trace 里，但只是因为它们作为 pi tool 被 pi 通用事件捕获**，并非 Prism 做了埋点。
- **现状双重失效**：
  1. `openspec/changes/phase2-ui-plugins/tasks.md` L11：`B2 langfuse cloud key 配置 | ⬜ 待用户配 key` → **key 未配**；
  2. `文档/Prism-Agent-设计稿问题清单.md` L197：评估批跑带 `--no-extensions` → **连 langfuse 一起被禁**，"分数写回 trace"链路在评估场景是断的。
  3. 仓库内**未找到该插件实体**（`node_modules/@langfuse/**` 与 `.pi/agent-minimal/npm/node_modules/@langfuse/**` 均无）。
- 写回实现是**桩**：`writeEvalTrace()` 仅 `console.log`（`langfuse_writer.ts` L36–44）。

### 4.3 Prism 侧的观测盲区（Langfuse 看不到的）

| 盲区 | 说明 |
|---|---|
| 网关层 | `prism-api/main.py` 无任何 logging/trace/埋点；`/chat/stream`、`/session` 请求无 span |
| 治理决策 | 护栏的 **裸 SQL 拦截、grounding 改写、完成验证器否决策**全部无 trace → **无法审计 fail-closed 次数与原因** |
| 业务语义 | 无 Prism 领域 trace：没有 `series_key / 维度 / as_of / 覆盖率 / CLAIM 结论 / scope` 的 span 层级与标签 |
| 外部服务 | 舆情 :8000、Atuohome :8001 的调用时延/错误率无 trace（仅工具返回体里有 HTTP 码） |
| 会话生命周期 | Prism 层无"会话开始/结束/回收/超时"事件 |
| 成本归因 | 无 per-user / per-dimension 的 token·成本归因（`langfuse_writer` 仅定义字段，未接） |

### 4.4 结论

用户的判断**基本成立**：**Langfuse 看到的是"pi 的 trace"**（LLM 调用 + 通用 tool 事件），而 **Prism 的领域层与治理层是观测盲区**。根因是 **Prism 没有自己的可观测层，完全依赖 pi 的通用插件**；叠加 key 未配 + 评估禁用，**当前 Langfuse 实际不产出任何可用 trace**。

---

## 5. 关键缺陷汇总

| # | 缺陷 | 严重度 | 证据 |
|---|---|---|---|
| D1 | `scope→工具白名单` 是死代码，模式分流从未生效 | 高 | `prism-api/pi_bridge.py` L19–44 / L80；`pi_gateway.mjs` L332 忽略 scope |
| D2 | 无 System Prompt / 无角色分流，普通用户被 PM SOP 裹挟 | 高 | `prism-guardrails/index.ts` L357–367；无 `SYSTEM.md` |
| D3 | 无进程池上限 / 无排队 / 无限流；同用户串行 | 高 | `pi_gateway.mjs` L233–277 / L316–325 |
| D4 | Prism 领域层零可观测；Langfuse 只覆盖 pi 通用事件 | 高 | `eval/langfuse_writer.ts` L4–5；`main.py` 无埋点 |
| D5 | Langfuse key 未配 + 评估 `--no-extensions` 禁用 | 中 | `phase2-ui-plugins/tasks.md` L11；`设计稿问题清单.md` L197 |
| D6 | 无 Redis，会话持久化=文件系统；注释误导 | 中 | `main.py` L161–175；`pi_bridge.py` L69 |
| D7 | `/chat/stream` 丢弃 `session_id` | 中 | `main.py` L143–147 |
| D8 | 单轮 300s 超时 vs 长分析（实测 ~25min）不匹配 | 中 | `pi_gateway.mjs` L188 |
| D9 | `query_sales` 版型能力三段断点（见上一份报告 §4.2） | 中 | 上一份审查报告 |

---

## 6. 建议路线（分层，供决策；本次未实施）

**P0 · 分治与角色（回应议题②）**
1. **真正落地模式分流**：让 `pi_gateway` 消费 `scope`，用 `setActiveTools` 按 `mode/board` 设白名单（可复用 `pi_bridge.py` 的映射表，但要在 pi 编排层实现）。
2. **渲染并注入 `SYSTEM.md`**：把模板实例化为会话上下文（对象身份/覆盖率/as_of/模式），并**区分角色**——PM 走棱镜 SOP，普通用户走轻量助手提示词。

**P0 · 并发治理（回应议题①）**
3. **加并发控制**：进程池上限 + 排队/背压 + 每用户限流；同用户并发改"排队"而非直接报错。
4. **单轮超时可配**，与长分析匹配。

**P1 · 可观测自建层（回应议题③）**
5. **建 Prism 自己的 trace 层**：在 `prism-api` 加请求级 span（OpenTelemetry 或轻量日志），把 `series_key/维度/as_of/scope/工具/外部服务时延/护栏裁决`写进 trace，并与 pi 的 Langfuse trace 以 `session_id/trace_id` **关联**（而不是替代）。
6. **修 Langfuse 现状**：配 key；评估批跑**保留 langfuse**（自定义 loader 只禁 permission-system）；`writeEvalTrace` 从桩接真 SDK。
7. **护栏决策可审计**：`tool_call` 拦截、grounding 改写、验证器否决均产出结构化事件。

**P2 · 稳健性**
8. `/chat/stream` 透传 `session_id`；确需 Redis 则实装，否则**删除误导性注释**。
9. 数据层读写分离（`prism_views.db` 只读 + 运行时库独立写），对齐项目既有设计。

---

## 7. 待确认

1. 议题①的"多人并发"目标量级与部署形态（单机 / Nginx / 云），决定池上限与限流取值。
2. 议题②普通用户是否需要"联网检索/闲聊"正式开放，还是仅作受限陪聊。
3. 议题③是否要求 Prism 自建 trace 与 Langfuse **双写还是关联**（合规上，企业数据是否允许出 cloud 见 `设计稿问题清单.md` 问题 11）。

---

## 附录 A · 证据索引

| 编号 | 证据 | 位置 |
|---|---|---|
| E1 | 进程池 / 串行锁 / 超时 / 回收 | `prism-api/pi_gateway.mjs` L36–37、L170–189、L233–277、L316–325 |
| E2 | `/chat` 忽略 scope、只发 message | `prism-api/pi_gateway.mjs` L332 |
| E3 | scope→白名单（死代码） | `prism-api/pi_bridge.py` L19–44、L80 |
| E4 | `/chat/stream` 丢 session_id；`/session` 转发 | `prism-api/main.py` L132–175 |
| E5 | 只注入 AGENTS.md；无 SYSTEM.md | `.pi/extensions/prism-guardrails/index.ts` L357–367；`SYSTEM.md.template` |
| E6 | Langfuse 插件声明（仅 pi 侧） | `.pi/agent-minimal/settings.json` L5 |
| E7 | Langfuse hook 范围（"自建工具全覆盖"）+ 写回是桩 | `eval/langfuse_writer.ts` L4–5、L36–44 |
| E8 | Langfuse key 未配 | `openspec/changes/phase2-ui-plugins/tasks.md` L11 |
| E9 | 评估 `--no-extensions` 禁 langfuse | `文档/Prism-Agent-设计稿问题清单.md` L191–197 |
| E10 | SQLite 单写风险 / 读写分离必要性 | `设计图总览/Prism-Agent-项目提纲.md` L220–231 |
| E11 | 前端身份/scope 默认值 | `prism-web/src/lib/chat.ts` L8–28 |