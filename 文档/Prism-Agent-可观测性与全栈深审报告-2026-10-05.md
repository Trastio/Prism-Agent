# Prism-Agent · 可观测性核验与全栈深审报告

> 审查日期：2026-10-05
> 审查根目录：`c:\Users\<you>\Desktop\Prism-Agent`
> 触发：① 核验 `http://localhost:3000`（Langfuse）"到底有没有 Prism 领域层"；② 深入审查前端 UI → 后台全栈
> 审查性质：**只读审查，未改动任何代码**
> 方法与证据强度：Langfuse **公开 API 实测**（一手）+ 运行进程实测（一手）+ 源码静态核对
>
> **文档关系**：本文为**子报告**，全部要点已并入主报告《[Prism-Agent-PM推理能力与Harness成熟度评估-2026-10-05.md](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-PM推理能力与Harness成熟度评估-2026-10-05.md)》§4；**优先级一律以主报告 §5 统一收敛清单为准**，本文 §7 已对齐。

---

## 0. 结论摘要（TL;DR）

| 议题 | 结论 |
|---|---|
| Langfuse 有没有 Prism 领域层？ | **没有**。Langfuse 里**有 trace**，也**能看到业务工具**（query_sales/sentiment_* 等），但**只因它们作为 pi 的 tool 被 pi 通用事件捕获**；trace 命名/结构/标签**全部是 pi 的**（`Pi Turn` / `Conversational Turn` / `LLM Call` / `Tool: X`，tags=`["pi"]`），**不存在 Prism 领域语义**（无 series_key/维度/as_of/覆盖率/CLAIM/scope 的 span 或结构化标签） |
| 与 pi 是否脱勾 | **没有脱勾**。观测层 100% 依赖 pi 插件；`prism-api` 与 `pi_gateway` **零埋点** |
| 最大隐性风险 | **磁盘代码 ≠ 运行代码**：网关进程 21:22 启动，代码 22:36 才修，**当前在跑的是旧代码**（无 `--exclude-tools`、无最新修复） |
| 旧报告时效 | 上一份《深入审查报告》中 **D9 / B-1 / B-2 / 4.5 / 无 SYSTEM.md** 等多项**已被修复**，本报告据**当前代码**更正 |

---

## 1. Langfuse 核验（实测证据）

### 1.1 服务与凭据现状（推翻旧结论）

| 项 | 实测结果 | 证据 |
|---|---|---|
| Langfuse 在跑 | ✅ `GET /api/public/health` → `{"status":"OK","version":"4.50.0"}` | 实测 |
| 项目 | ✅ `/api/public/projects` → 名称 `prism-dev`，组织 `Prism-Agent` | 实测 |
| 插件已安装 | ✅ `.pi/agent-minimal/npm/node_modules/@langfuse/pi-observability-plugin`（v0.1.2） | 文件存在 |
| **key 已配置** | ✅ `.pi/agent-minimal/langfuse.json` 内含 `publicKey/secretKey/baseUrl=http://localhost:3000/environment=prism-dev/release=phase2-m5` | [langfuse.json](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/langfuse.json) |
| 配置读取路径 | 插件读 `<agentDir>/langfuse.json`，即 `PI_CODING_AGENT_DIR/langfuse.json` ✅ 命中 | [index.ts L121-133](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/npm/node_modules/@langfuse/pi-observability-plugin/src/index.ts#L121-L133) |

> **更正**：上一份报告 D5「Langfuse key 未配 → 不产出任何 trace」**已过时**。实测 key 已配、插件已装、trace 已在产出。

### 1.2 trace 实测内容（决定性）

实测拉取 `GET /api/public/v2/observations?limit=100`（旧 `/api/public/traces` 端点在本部署为 v4 events_only 模式已下线）：

- 时间范围：`2026-10-05T13:41:45Z ~ 14:03:57Z`（UTC），**全部来自同一次事故会话**
- 按 name 统计：

| name | 数量 | 类型 |
|---|---|---|
| `LLM Call` | 38 | GENERATION |
| `Tool: bash` | **33** | TOOL |
| `Tool: query_sales` | 9 | TOOL |
| `Conversational Turn` | 7 | SPAN（根） |
| `test-span` | 3 | SPAN（人工测试） |
| `manual-test-span` | 2 | SPAN（人工测试） |
| `Tool: sentiment_overview` | 2 | TOOL |
| `Tool: sentiment_dimension` / `sentiment_trend` / `sentiment_events` | 各 1 | TOOL |
| `Tool: query_config` / `get_sales_detail` / `mcp` | 各 1 | TOOL |

- 根 span 均为 `Conversational Turn`，其 `sessionId` 与 `.pi/sessions/usr_g5r6h5ye/2026-10-05T13-39-59-978Z_01a10c4a-...jsonl` **完全一致** → 证明确为本次会话的 trace。
- 观测载荷字段：`environment=prism-dev`、`userId=""`（**空**，因 `langfuse.json` 未设 `userId`）、`sessionId=<pi session id>`。

### 1.3 判读：有没有"Prism 领域层"？

**没有 Prism 领域层。** 分层事实：

```
Trace 名  = "Pi Turn"                 ← 插件常量 TRACE_NAME
  根 span = "Conversational Turn"     ← 插件常量 ROOT_OBSERVATION_NAME
    ├─ "LLM Call"                     ← 模型调用（token/cost/时延）
    └─ "Tool: query_sales"            ← 业务工具，但仅"作为 pi tool"被通用捕获
tags = ["pi"] ; metadata.source = "pi"
```

- 证据：插件源码 `TRACE_NAME="Pi Turn"`、`ROOT_OBSERVATION_NAME="Conversational Turn"`、`BASE_TAGS=["pi"]`、`source:"pi"`（[index.ts L20-L28 / L612-L618](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/npm/node_modules/@langfuse/pi-observability-plugin/src/index.ts#L20-L28)）。
- **业务语义未被结构化**：`series_key`、维度、`as_of`、覆盖率、CLAIM、scope 都**不是** trace 的一等字段，只能"埋"在 tool span 的原始 `input`/`output` JSON 里（需人工翻找）。
- **Prism 自有层零可观测**：`prism-api/main.py`（FastAPI 网关）与 `prism-api/pi_gateway.mjs`（Node 编排）**没有任何埋点/日志/trace**；护栏的裸 SQL 拦截、grounding 改写、完成验证器否决**全部不可审计**。
- **旁证**：环境里另有 `test-span`(3) / `manual-test-span`(2) 的人工测试 trace，说明集成是"刚接上、还在自测"阶段。

**一句话**：Langfuse 现在看到的是"**pi 的对话轮次 + 被 pi 抓到的工具调用**"，不是"**Prism 的分析领域模型**"。要评 Prism 的分层/口径/护栏，还得另建埋点。

---

## 2. 关键隐性风险：磁盘代码 ≠ 运行代码（P0）

| 对象 | 时间 | 含义 |
|---|---|---|
| `prism-api/pi_gateway.mjs` 文件 mtime | **2026-10-05 22:36:36** | 最新修复（含 `--exclude-tools`）已落盘 |
| 运行中的 `pi_gateway.mjs` 进程（PID 79716） | **2026-10-05 21:22:13** 启动 | **在跑的是 21:22 的旧代码** |
| Langfuse 里的 `Tool: bash` ×33 | 2026-10-05 13:41–14:03 UTC | 旧代码下 bash **未**被排除；与"当前文件已排除 bash"矛盾 → 反证运行的是旧代码 |

**结论**：你当前对着 `localhost` 的实测，跑的是**未包含最新修复的旧网关**。任何"问题已修/未修"的判断，必须**先重启网关**再复测（`pi_gateway.mjs`、`prism-api`、pi 子进程池 `poolSize=4`）。此外还存在**大量残留 dev 进程**（10/4 起多个孤儿 `vite --port 5173`），属环境脏化。

---

## 3. 前端 UI（prism-web）深审

### 3.1 对话视图 ChatView（4 条确证缺陷）

| # | 问题 | 位置 | 严重度 |
|---|---|---|---|
| F1 | 工具入参永远显示 `undefined`：读的是 `e.data.arguments`，网关实际发 `args` | [ChatView.tsx L84](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/ChatView.tsx#L84) ↔ [pi_gateway.mjs L55](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L55) | 中 |
| F2 | 重复 `case 'tool_result'`（L89-104 与 L105-113），后者死代码 | [ChatView.tsx L89-L113](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/ChatView.tsx#L89-L113) | 低 |
| F3 | `session_info` 事件**从不产生**（网关/main.py 均无此事件）→ `setSessionId` 永不触发 → 每轮 `session_id` 恒为 `null` | [ChatView.tsx L60-L62](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/ChatView.tsx#L60-L62) | 中 |
| F4 | `as_of` 提取错位：从 `last.result._meta.as_of` 取，但 pi tool result 结构是 `{content:[...]}`，**取不到** → 状态栏 as_of 不更新 | [ChatView.tsx L96-L99](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/ChatView.tsx#L96-L99) | 低 |

### 3.2 ui_request 回填链路断裂（跨层）

- 前端收到 `ui_request` 会 `POST /ui-response`（[chat.ts L51-L59](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/lib/chat.ts#L51-L59)）。
- 网关**有** `/ui-response` 路由（[pi_gateway.mjs L409-L427](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L409-L427)），但：
  - `prism-api/main.py` **无** `/ui-response` 路由；
  - `vite.config.ts` **未代理** `/ui-response`（只代理了 `/chat/stream /dashboard /session /ws /sentiment-board /static /api/dashboard`）。
- 后果：回填请求打到 Vite 开发服务器（落 SPA fallback），**永远到不了网关**。若 `PRISM_AUTO_APPROVE_UI≠1`，pi 等待 UI 响应会**卡住整轮**；若 `=1` 则所有确认被静默自动通过（护栏形同虚设）。二者都不可接受。

### 3.3 看板视图：真实数据与"示例数据"混排（数据真实性风险）

对话/看板**硬编码单一对象"银河E5"**，对象选择器未接线：

- `App.tsx` L19 `useState('银河E5')`；`KanbanView` L32 `as_of 硬编码 2026-10-04`；Overview/Market/Config/Reviews 均 `fetch('/dashboard/...?series_key=银河E5')` 写死。

多处面板**明确标注"示例数据"却与真实数据并排展示**，汽车 PM 极易误读：

| 面板 | 内容 | 位置 |
|---|---|---|
| 销量·版型结构 | 硬编码 `530探索版 2047 / 530启航版 1854 / …` | [MarketBoard.tsx L43-L51](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/MarketBoard.tsx#L43-L51) |
| 销量·竞品对比 | 硬编码 理想L6/零跑D19/问界M7/岚图Free 行 | [MarketBoard.tsx L54-L66](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/MarketBoard.tsx#L54-L66) |
| 配置·赋分展示 | 硬编码 `55000元 / 2200元` | [ConfigBoard.tsx L69-L74](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ConfigBoard.tsx#L69-L74) |
| 口碑·原文样本 / 趋势 | 硬编码 review_id 与 `[28,35,30,…]` 序列 | [ReviewsBoard.tsx L71-L81](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ReviewsBoard.tsx#L71-L81) |
| 棱镜结论·结论文案 | `入门版缺少前排通风与隔音玻璃` 等**叙述硬编码**（仅数字部分计算） | [KanbanView.tsx L99-L131](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.tsx#L99-L131) |

> 这与全局红线#1「数据真实性硬底线」直接冲突：动态计算与硬编码示例**无视觉区分强制**，仅靠一个灰色 `示例数据` 小标签。

### 3.4 其他 UI 缺口

- **会话列表已渲染但不可切换**：`Sidebar.tsx` **已消费** `/session` 并渲染会话列表（`useQuery(['sessions',userId])` → `fetch('/session?user_id=…')`，[L17-L22](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L17-L22)；列表渲染 [L60-L69](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L60-L69)）；但 `sb-row` 无 `onClick` → 会话**点不开、无切换逻辑**，「新建会话」也只切视图未调 `POST /session` → 多会话管理仍不可用。
- **`VIEW` 切换即卸载**：`KanbanView` 与 `ChatView` 条件渲染，切换会丢失对话内存态。
- **`/chat/stream` 无心跳**：长分析（实测曾 ~25 分钟）在无数据期间易被中间层判超时。

---

## 4. 后台网关 prism-api（FastAPI）深审

| # | 问题 | 位置 | 严重度 |
|---|---|---|---|
| B1 | **无任何鉴权/权限分层**：全部路由裸奔；spec 承诺的"管理者可编辑 / ~49 人只读"**未实现** | [main.py 全文](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py) | 高 |
| B2 | `/chat/stream` **丢弃 `session_id`**：转发只带 `message/user_id/scope` | [main.py L158-L162](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L158-L162) | 中 |
| B3 | **无 `/ui-response` 路由**（前端却在调）→ 与 §3.2 联动断链 | [main.py](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py) | 中 |
| B4 | `open_prism_views()` **以读写模式**打开视图库（`src/tools/_shared.ts` 用 `readonly:true`，此处未设）→ 口径库存在被误写/锁争用风险 | [main.py L41-L44](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L41-L44) | 中 |
| B5 | **零可观测**：请求/时延/错误无日志无 trace | [main.py](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py) | 中 |
| B6 | 入参用裸 `dict`（非 Pydantic 模型），仅手工校验；`scope` 被转发但下游不用 | [main.py L147-L162](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L147-L162) | 低 |
| B7 | 目录内残留 0 字节 `prism-api/prism_views.db`（真实库在项目根）易误导 | `prism-api/` | 低 |

> **已修复项（更正旧报告）**：`/dashboard/sales` **已含** `group_by='spec'` 分支直读 `sales_trim`（[main.py L88-L102](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L88-L102)），旧报告 D9/B-1「三段断点」已补上取数段。

---

## 5. 编排层 pi_gateway.mjs 深审

| # | 问题 | 位置 | 严重度 |
|---|---|---|---|
| G1 | **无进程池上限 / 无排队 / 无限流**：`pool` 无 cap，进程数=在线用户数，可 OOM | [L232-L266](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L232-L266) | 高 |
| G2 | 同用户并发**直接报错**而非排队（`上一个请求仍在进行中`） | [L319-L325](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L319-L325) | 中 |
| G3 | 单轮超时 **300000ms**，与长分析不匹配 | [L188](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L188) | 中 |
| G4 | `scope` 被 `/chat` **彻底忽略**（只发 `prompt:{message}`）→ 模式分流从未生效 | [L333](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L333) | 高 |
| G5 | **零埋点**：进程生命周期/队列/超时/错误无 trace | 全文 | 中 |
| G6 | 硬编码 `MEM0_API_KEY` 默认值写在源码里 | [L258](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L258) | 中 |
| G7 | 30 分钟空闲回收 + 会话靠磁盘，进程内记忆态丢失 | [L269-L278](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L269-L278) | 低 |

> **已修复项（更正旧报告）**：磁盘版网关已加 `--exclude-tools bash,powershell,edit,write,read,grep,find,ls,web_search,web_fetch`（[L249-L251](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L249-L251)）—— 但**未生效**，因运行进程是旧代码（见 §2）。且 `mcp`（Langfuse 里 `Tool: mcp` 出现）**不在**排除名单，仍可用。

---

## 6. 扩展 / 工具 / 护栏现状（pi 扩展 prism-guardrails）

**典型"能力在 TS、但到不了 Agent"的三段断点已打通**（更正旧报告 B-1）：

| 环节 | 现状 |
|---|---|
| TS 实现 `group_by='spec'` | ✅ 有 |
| 扩展 schema 暴露 | ✅ 已暴露 `group_by` / `month`（[index.ts L61-L65](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L61-L65)） |
| 扩展 execute 透传 | ✅ 已透传（[index.ts L40-L41](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L40-L41)） |
| prism-api 取数分支 | ✅ 已有 `group_by='spec'`（[main.py L88-L102](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L88-L102)） |

其他**已修复**项：`get_sales_detail` 参数已改 `series`（[L215-L218](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L215-L218)）；验证器回灌改用 `appendCustomMessageEntry`（不再污染用户可见消息流，[L462-L469](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L462-L469)）；**`SYSTEM.md` 已落地**（仓库根，非仅模板）。

**仍存在的问题**：

| # | 问题 | 位置 | 严重度 |
|---|---|---|---|
| E1 | `before_agent_start` 的 SYSTEM.md 变量用**硬编码**占位（`{series_key}=银河E5`、`{series_id}=7650`、`{as_of}=今天`），**不是**按当前会话对象动态注入 | [index.ts L365-L375](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L365-L375) | 高 |
| E2 | **无角色分流**：普通用户与汽车 PM 走同一 System Prompt（AGENTS.md + SYSTEM.md） | 同上 | 高 |
| E3 | 护栏（裸 SQL 拦截 / grounding / 验证器）**无结构化审计事件**，Langfuse 看不到 | [index.ts L381-L470](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L381-L470) | 中 |
| E4 | `--exclude-tools` **未排除** `mcp`/记忆/子代理等非业务扩展，对话模式仍可能被工程能力干扰 | [pi_gateway L250](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L250) | 中 |
| E5 | `tool_call` 护栏仅正则匹配 `DROP|DELETE|...`，`bash` 直连数据库的判断在 bash 被排除后成空转；拦截面偏窄 | [index.ts L381-L395](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L381-L395) | 低 |

---

## 7. 缺陷汇总（已对齐主报告）

> 本节优先级**已与主报告《Prism-Agent-PM推理能力与Harness成熟度评估-2026-10-05.md》§5 统一收敛清单对齐**，两者不得冲突；如遇不一致，以主报告为准。

| 优先级 | 本报告相关项 | 对应主报告 §5 条目 |
|---|---|---|
| **P0** | 重启运行进程让磁盘代码生效（§2）；上下文注入 + 角色分流（G4/E2/E1，对应第 3 条）；打通 ui_request 回填并明确确认策略（§3.2/B3）；看板示例数据隔离（§3.3） | 第 3 / 5 / 6 / 7 条 |
| **P1** | 并发治理（G1/G2/G3）；模式分流贯通（G4）；建 Prism 自建可观测层 + 护栏审计（G5/B5/E3）；补鉴权/权限分层（B1） | 第 10 / 11 / 12 / 16 条 |
| **P2** | `/chat/stream` 透传 `session_id` + 补 `session_info`（B2/F3）；视图库只读 + 清理残留 db/孤儿进程（B4/B7）；前端修 `args`/重复 case/as_of（F1/F2/F4）；密钥移出源码（G6） | 第 21 / 22 / 23 / 24 条 |

---

## 8. 待确认

1. 生产部署形态（单机 / Nginx / 云）→ 决定池上限、限流与超时取值。
2. 普通用户是否需要正式开放"联网检索/闲聊"，还是受限陪聊。
3. 可观测性目标：Prism 自建 trace 与 Langfuse **双写还是关联**；企业数据是否允许出 cloud。
4. 权限分层是否需要分阶段实现（当前完全缺失）。

---

## 附录 A · 实测证据索引

| 编号 | 证据 | 来源 |
|---|---|---|
| L1 | Langfuse health `{"status":"OK","version":"4.50.0"}`；项目 `prism-dev` | `GET /api/public/health`、`/api/public/projects` |
| L2 | 100 条观测统计（`LLM Call`38 / `Tool: bash`33 / `Tool: query_sales`9 / `Conversational Turn`7 …）| `GET /api/public/v2/observations?limit=100` |
| L3 | 根 span `Conversational Turn`，`sessionId=01a10c4a-...`（与事故会话一致） | 同上 |
| L4 | 插件 trace 命名/标签常量（`Pi Turn`/`Conversational Turn`/tags=`pi`） | 插件 [src/index.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/npm/node_modules/@langfuse/pi-observability-plugin/src/index.ts) |
| L5 | key 已配，读取路径 `agentDir/langfuse.json` | [langfuse.json](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/langfuse.json)、插件 L87-L133 |
| R1 | 网关进程 PID 79716 启动 21:22:13；文件 mtime 22:36:36 | `Get-CimInstance Win32_Process`；`Get-Item` |
| R2 | 9100 健康 `poolSize=4`；8002 健康 `prism_views_tables=6` | 实测 HTTP |
| R3 | `--exclude-tools` 为 pi 合法 flag（denylist，覆盖内置+扩展工具） | `pi --help` 实测 |