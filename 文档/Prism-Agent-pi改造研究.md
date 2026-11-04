# Prism-Agent × pi-agent 改造研究

> 依据：pi 0.85.1 本地文档逐条核实（`pi-windows-x64\docs\`，2026-09-16 精读 extensions/sdk/compaction/security/skills/json/prompt-templates 全文或核心章节）+ BreachWeave 源码级先例（见《pi生态案例研究》§2.A.1）。
> 本文档：回答"Prism-Agent 具体怎么在 pi 上组装"——每个改造点给出 pi 原生机制 → 生态先例 → 我们的落法。
> 地位：**改造实施的工程规范**，介于提纲（产品层）和读书映射（方法论层）之间。任务挂接见 §6。

---

## 0. 一页结论

1. **插槽覆盖度超出预期：我们计划的每一个改造点，pi 都有原生机制支撑，全程无需 fork 内核。** BreachWeave 已验证这条路能走到竞赛冠军级。
2. **三个最重要的机制发现**（此前记忆中没有、本次精读确认）：
   - **`tool_call` 事件处理器抛错 = 拦截工具（fail-safe）**——pi 原生就是 fail-closed 设计，红线#5 的"护栏 fail-closed"不需要我们自己造；
   - **SDK 会话级工具白名单**：`tools` / `excludeTools` / `noTools` 三层控制 + 运行时 `setActiveTools()`——"agent 不写裸 SQL、不碰文件系统"可以用"根本不给工具"实现，比拦截更彻底；
   - **SDK 可全内存运行**：`SessionManager.inMemory()` + `InMemoryCredentialStore` + `SettingsManager.inMemory()`——每个网站用户一个隔离会话，不落 pi 全局目录，这是"产品化多租户"的干净底座。
3. **两个意外收获**：`createReadOnlyTools` 官方导出（BI 内嵌对话直接用）；会话树分支 API（`branch`/`fork`）原生支持"轨迹前缀回归"评测——书第 7 章的方法 pi 会话结构天然承载。
4. **两条风险**：BreachWeave 等先例基于 0.65（import 是旧 scope `@mariozechner/*`），我们的 0.85.1 用 `@earendil-works/*`，抄代码要对照迁移；pi-mcp-adapter 是否被 `tool_call` 护栏拦截仍未验证（P0 实验，见 §5）。

---

## 1. pi 插槽全景图（0.85.1 核实版）

| 层 | 机制 | 出处 | Prism 用法 |
|---|---|---|---|
| **会话** | `createAgentSession(options)`：model / thinkingLevel / scopedModels / tools / excludeTools / noTools / customTools / resourceLoader / sessionManager / settingsManager / cwd / agentDir | sdk.md | Agent 会话的唯一入口，按会话类型传不同工具白名单 |
| | `SessionManager`：`inMemory()` / `create()` / `continueRecent()` / `open()`；树结构 `branch` / `branchWithSummary` / `fork`；**可从 DB 条目恢复** | sdk.md | 网站用户会话=内存会话+我们自己的持久化；评测=内存会话即用即弃 |
| | `AgentSessionRuntime`：newSession / switchSession / fork / clone | sdk.md | 暂不用（每用户单会话够用） |
| | `SettingsManager.inMemory(settings)`：compaction / retry 等覆盖 | sdk.md | 评测批跑时关压缩、控重试 |
| **工具** | `defineTool` / `customTools`：typebox 参数、promptSnippet、promptGuidelines、execute 返回 content/details/usage/terminate、onUpdate 流式进度 | extensions.md | 口碑/销量/舆情语义工具全部走这里 |
| | 工具白名单：`tools`（允许清单）、`excludeTools`（排除）、`noTools:"all"/"builtin"`；运行时 `setActiveTools()` | sdk.md/extensions.md | Agent 模式不给 bash/read/write/edit；BI 内嵌对话用只读子集 |
| | 动态工具加载：先注册后激活，`setActiveTools` 增量启用 | extensions.md | 远期：工具多了再启用；DeepSeek 无原生延迟加载，慎用（破坏缓存前缀，§5） |
| | 覆盖内置工具：同名注册或 `--no-builtin-tools` | extensions.md | Agent 模式直接 `noTools` 内置，无需覆盖 |
| | 输出截断：**工具必须自截**，内建 50KB/2000 行上限，`truncateHead`/`truncateTail` | extensions.md | 口碑查询返回必须带 n 随行 + 截断 + 全量落盘路径 |
| | `createReadOnlyTools` 官方导出 | sdk.md | BI 内嵌对话的只读文件工具（如需读交付物） |
| **事件（护栏核心）** | `tool_call`：**可拦截** `{block, reason, terminate}`，**可就地改参数**；处理器抛错=拦截（fail-safe） | extensions.md | 口径校验、MCP 转发拦截、审计日志 |
| | `tool_result`：可改写结果，链式中间件 | extensions.md | 大结果降噪改写（BreachWeave large-tool-result 模式） |
| | `before_agent_start`：注入消息 + **改本 turn 系统提示词** | extensions.md | 会话层提示词：锁快照声明、注入当前筛选状态 |
| | `context`：每次 LLM 调用前改写消息（非破坏） | extensions.md | 备用：口径提醒常驻 |
| | `message_end`：可替换最终 assistant 消息 | extensions.md | 结论后处理挂点（如口径声明自动追加） |
| | `session_before_compact`：取消或**自定义摘要**（可换模型） | compaction.md | 远期自定义压缩：保留口径声明与关键结论 |
| | `input`：拦截/改写用户输入 | extensions.md | Agent 模式：输入预处理（敏感信息提示等） |
| **角色** | `systemPromptOverride`（ResourceLoader 级） | sdk.md | 全局层提示词（永不动的那层） |
| | prompt templates：`.pi/prompts/*.md`，`/名字` 展开，$1/$@ 参数 | prompt-templates.md | 分析模板：`/车系诊断 银河E5` |
| | Skills：`.pi/skills/`，渐进披露，`/skill:name` | skills.md | 棱镜方法论包（九维度框架、标签解读手册） |
| **模型** | `ModelRuntime`：auth 优先级、`setRuntimeApiKey`、自定义 authPath/modelsPath、`InMemoryCredentialStore` | sdk.md | DeepSeek 内置直用；评测用 runtime key 覆盖 |
| | `pi.registerProvider`：自定义 provider / 覆盖 baseUrl / OAuth / 自定义流式 | extensions.md | 评委模型（GLM/Kimi）接法；或评委走独立脚本（§2.7） |
| **产品通信** | SDK 进程内（推荐：同进程、类型安全、可拿 agent.state） | sdk.md | **网站后端直接嵌 SDK**（BreachWeave 模式） |
| | RPC 模式（`--mode rpc`）：JSON 行协议，跨语言子进程 | rpc.md | 不用（除非未来前端与 agent 分进程） |
| | JSON 模式（`--mode json`）：事件流到 stdout | json.md | 评测批跑的轻量通道（原定方案，保留） |
| | print 模式（`-p`） | — | 快速烟测 |
| **隔离** | 无内建沙箱；项目信任机制只管资源加载；官方指向容器化（Gondolin/Docker） | security.md | 印证红线#5：护栏必须在执行层；数据库权限靠 SQLite 只读打开+OS 文件权限 |

---

## 2. 逐模块改造方案

### 2.1 运行时拓扑：一个宿主进程，两类会话

**pi 机制**：SDK 进程内嵌入，`createAgentSession()` 每次调用产生独立会话；`session.subscribe()` 收事件流；`session.prompt()` 驱动。

**先例**：BreachWeave = Bun 宿主 + ui-web（Bun.serve REST + React）+ core 层 `resolvePromptSession` 把"角色配置"装配成 `CreateAgentSessionOptions`。它的"一次装配、处处复用"值得照搬。

**Prism 落法**：

```
prism-server（Bun 进程）
├── REST API 层（网站前后端通信）
├── 会话工厂 resolvePrismSession(kind, options)
│   ├── kind="agent"    → Agent 模式会话：语义工具全集 + 全局层提示词 + 会话层锁快照
│   └── kind="bi-chat"  → BI 内嵌会话：只读工具子集 + 筛选状态注入（服务端锁死）
└── 每个网站用户 = SessionManager.inMemory() + 我们自己的会话落盘（JSON）
```

要点：
- **BI 模式的图表不走 pi**——直连口径视图出图（原定设计不变）；pi 只承载"筛选锁定的内嵌对话"。内嵌会话的服务端工具只读当前筛选后的视图，工具参数里**没有**车系/时间维度可选（不靠提示词约束，靠工具接口本身没有那个参数）——这是"BI 内嵌对话锁筛选"的机制化，比之前设想的"提示词锁定"强一级。
- 会话持久化：内存会话 + `session.messages` 序列化到我们自己的存储；恢复用 `SessionManager.inMemory(cwd, {id}, entries)`（sdk.md 明确支持"Resume a session kept outside the filesystem, e.g. in a database"）。
- 一个用户一个 `AgentSession`，不并发复用；会话内工具并行是 pi 自己的事（默认并行工具模式）。

### 2.2 工具层：语义工具 = 唯一的手脚

**pi 机制**：`defineTool` + typebox；`promptSnippet`/`promptGuidelines` 控制工具在系统提示词里的露出；`execute` 返回 `content`（给 LLM）/`details`（给渲染与程序）/`usage`（嵌套调用记账）；`terminate: true` 可结束回合（结构化输出场景）。

**先例**：BreachWeave 的 `config/tools/` 全部 `defineTool`+typebox，用 `StringEnum`（Google 兼容）；成果只能通过 `submit_sub_agent_output` 提交。

**Prism 落法**（对应读书映射的工具描述模板与三重口径保障）：

| 设计点 | 落法 |
|---|---|
| 工具清单 | `query_koubei_aggregate`（车系×维度×极性聚合，必返 n+覆盖率+时间窗）、`query_koubei_reviews`（标签过滤+关键词检索——读书映射⑩，不建裸向量）、`query_sales`、`query_sentiment`、`list_series`、`get_snapshot_meta`、`submit_conclusion`（完成验证器，见 2.3） |
| 口径三重保障·第②重 | 每个查询工具参数里带 `expected_min_n`（模型自查声明）；服务端不足时返回明确"样本不足，结论不可靠"而不是静默给数 |
| 口径三重保障·第③重 | `execute` 内部只查口径视图（SQL 写死在工具里），返回的 n/覆盖率/截止日期是**服务端算的真值**，模型无法自报 |
| n 随行 | 返回 content 首行固定格式：`数据截止 {snapshot_date}，n={n}（覆盖率 {pct}%）`——机制上让"时效随行声明"无法被省略 |
| 截断 | 评论列表类用 `truncateHead`，超限全量写临时文件并告知路径（文档模式） |
| 工具描述 | 按 读书映射 工具描述模板写 description + promptGuidelines（guidelines 必须点名工具名，文档明确警告不能写"Use this tool when…"） |
| 禁裸 SQL | 机制化 = 工具白名单里**没有** bash/read/write/edit，也没有任何接受 SQL 字符串的工具——模型想写也没入口 |

### 2.3 护栏层：四道执行层闸门

**pi 机制**：`tool_call` 可拦可改可终止、抛错即拦（fail-safe）；`tool_result` 可改写；`before_agent_start` 改提示词；错误处理原则"extension errors logged, agent continues"。

**先例**：BreachWeave `scope-guard` 的 audit/enforce 双模式、共享文件所有权、Manager 直接行动限额（≤6 次）、命令黑名单。

**Prism 落法——四道闸门按数据流排序**：

1. **入口闸（会话装配）**：工具白名单按会话类型收窄（§2.1）。红线#2（不写裸 SQL）、#3（49 人只读）的主体在这道闸解决——**能力不发放，而非发放后拦截**。
2. **调用闸（`tool_call`）**：
   - MCP 转发调用拦截（P0 待验证，见 §5）：若 adapter 的调用走 `tool_call` 事件，则统一加：参数合法性、只读断言、审计日志；
   - 审计模式（audit）先行：全量记录工具调用与参数，跑两周看日志，再对违规模式切 enforce——照抄 BreachWeave 的灰度节奏；
   - 评测埋点：trap task 的"是否踩坑"判定从这道闸的日志取数。
3. **结果闸（`tool_result`）**：大结果降噪改写；响应补齐口径行（防御性：即使工具漏带也补上）。
4. **出口闸（完成验证器，红线#1 机制化）**：Agent 模式的最终交付走 `submit_conclusion` 工具（参数含：结论、依据的车系×维度、引用的 n/覆盖率、快照日期）；服务端校验"引用的数字与该会话实际查询返回的一致"（会话内查询台账比对——工具调用日志就是台账），不一致则 `block` 并要求修正。模型可以提出完成，不能批准自己的完成。BreachWeave 的 `terminate` + 提交工具模式是现成参照。

### 2.4 多 agent：三维度并行调查

**pi 机制**：无内建 subagent；官方 examples 有 `subagent/`（registerTool + exec 派生）；pi-subagents 包已装（未启用）。

**先例**：BreachWeave 自研 `subagent` 工具——每次派生独立 OS 进程跑全新 pi 会话（上下文彻底隔离），单/并行≤8/链式，JSON 结构化回传。

**Prism 落法**：棱镜三维度（配置/口碑/销量）各派一个子会话。**决策点：用 pi-subagents 包 vs 抄 BreachWeave 自研**。倾向：第①步先用 pi-subagents 验证产品价值（它封装了进程管理），bad case 显示需要更细控制（如每维度不同模型、独立护栏配置）再自研。判据已被 BreachWeave 旁证：三个维度是三个独立数据源，符合"是否引入新信息"。

### 2.5 角色层：两层提示词的机制化

**pi 机制**：`systemPromptOverride`（装配级）、`before_agent_start` 的 `event.systemPrompt`（每 turn 可改、链式）、AGENTS.md 上下文文件、prompt templates、skills。

**Prism 落法**（读书映射⑫的两层落地）：

| 层 | 机制 | 内容 | 变更纪律 |
|---|---|---|---|
| 全局层（永不动） | `systemPromptOverride`，写在代码里 | 棱镜角色定义、九维度框架、结论必须基于已打标样本、数据真实性纪律 | 改动=发版，走评估回归 |
| 会话层（每会话锁） | 会话创建时生成，经 `before_agent_start` 注入 | 当前快照声明（日期/n/覆盖率）、BI 模式的筛选状态、用户级赋分覆盖 | 随会话创建固化，会话内不漂移 |
| 方法论包 | Skills（渐进披露） | 标签体系手册、维度分析套路、结论写作模板——目录常驻，正文按需加载 | 内容可迭代，不碰提示词两层 |
| 操作模板 | prompt templates | `/车系诊断 <车系>`、`/竞品对比 <A> <B>`、`/口碑专题 <维度>` | 高频动作产品化 |

### 2.6 上下文工程

**pi 机制**：默认 compaction（阈值=contextWindow−16384，保留最近 20000 tokens；切点永不落在工具结果上）；`session_before_compact` 可整体替换摘要（`serializeConversation` 拿到序列化文本后可换模型）；`context` 事件每调用前改写消息。

**Prism 落法**：v4-flash 是 1M 上下文，**压缩几乎不会触发**——这是选择大上下文模型的隐性红利，长会话竞品分析不丢口径。仍要做两件事：①自定义压缩预案（真触发时，摘要必须原样保留各维度口径声明与已提交结论——写进 `session_before_compact` 的指令模板）；②工具结果永远自截（§2.2），不依赖压缩兜底。settings 用 `SettingsManager.inMemory` 显式管理，不碰全局 settings.json。

### 2.7 模型层：主 agent 与评委异源

**pi 机制**：DeepSeek 内置；`ModelRuntime` 管 auth；`registerProvider` 可加 provider；`scopedModels` 限定可选模型。

**Prism 落法**：主 agent = `deepseek-v4-flash`（已烟测）。评委（GLM/Kimi 双评委，读书映射④）**不进 pi 会话**——评委是离线批处理（拿轨迹 JSON 调 API 打分），独立 Python/TS 脚本更干净，也天然满足"judge 与 agent 异源+异构"。`registerProvider` 留作它用（如未来换代理端点，覆盖 baseUrl 即可，extensions.md 有现成例子）。`setRuntimeApiKey` 用于评测脚本注入 key，不落 auth.json（注意：auth.json 里已有 anthropic 条目，勿动）。

### 2.8 评测接线

**pi 机制**：`-p`/`--mode json` 事件流；SDK 全内存会话；会话树分支。

**Prism 落法**（提纲 §8 的机制对号）：

| 评测需求 | pi 机制 |
|---|---|
| 控参批跑 | SDK 进程内循环：`createAgentSession` + 固定 model/tools + `session.prompt(题目)` + `subscribe` 收全轨迹。比 `--mode json` 子进程更可控（同进程拿 `agent.state`）；`--mode json` 保留给跨语言场景 |
| 环境隔离 | `SessionManager.inMemory` + `SettingsManager.inMemory`（关压缩、控重试）——零文件污染 |
| 轨迹前缀回归（书 ch7） | 会话树 `branch`/`fork`：同一前缀分叉不同后续，天然支持"改了中间一步，重放后半段" |
| 幻觉否决（红线#1） | `submit_conclusion` 台账比对（§2.3 出口闸）+ 轨迹里 tool_call/tool_result 事件全量落盘供裁判复核 |
| Pass^k / trap tasks | 评测 harness 外层统计；trap 判定数据来自调用闸审计日志 |
| 评委 | 离线脚本读轨迹 JSON（§2.7） |

### 2.9 网站壳

**先例**：BreachWeave ui-web = Bun.serve + REST 路由对象 + React（Hash 路由 + shadcn 组件 + typed fetch 封装）。pi-web（⭐6.4k）是另一参照。

**Prism 落法**：前端自建（舆情 Board 栈），后端 Bun.serve 模式照 BreachWeave——路由对象化、按领域分组（/api/sessions、/api/chat、/api/bi/*）。BI 图表数据接口直连口径视图（不过 pi）。流式输出：`session.subscribe` 的 `message_update` → SSE/WebSocket 转发前端。文件交付物：工具在服务端生成 excel/word 落盘，返回路径+下载接口。会话列表 = 我们自己的持久化存储。

### 2.10 存量项目集成（Atuohome / 舆情 Board / RAG）

| 存量 | 去向 | pi 机制关联 |
|---|---|---|
| 22 个 Python MCP 工具·查询类 | 重写为 TS 语义工具（原定） | defineTool；MCP 桥只作过渡 |
| 22 个 MCP 工具·采集/打标类 | 留 Python，agent 外壳退役（原定） | 与 pi 无关，管线任务 |
| 舆情 Board 前端栈 | 拆出来做双模式网站前端 | 与 pi 无关 |
| 汽车知识库 RAG | 保留为 HTTP 服务，包一个 `search_knowledge` TS 工具 | defineTool 内 fetch；或经 MCP 桥（待护栏验证后定） |
| autohome.db → koubei.db | 拆库只读（原定三步计划） | SQLite 以只读连接打开（`mode=ro`）+ OS 文件权限，双保险 |

---

## 3. 红线 → 机制映射总表

| 红线 | 机制（优先级序） | 验证方法 |
|---|---|---|
| #1 数据真实性 | 出口闸 submit_conclusion 台账比对 + 工具端真值 n/覆盖率 + 评测幻觉否决 | golden case 全绿 + trap case 全红；人工抽检台账比对日志 |
| #2 不写裸 SQL | 工具白名单无任何 SQL/bash 入口；SQL 只存在于工具实现内 | 白名单快照测试（tools 列表断言）；红队提示词攻击用例 |
| #3 权限（49 人只读） | 会话工厂按用户角色发不同白名单；写接口只存在于管理端 REST，不过 agent | 双角色集成测试；API 层越权用例 |
| #4 舆情合规 | 采集留 Python 管线（学习研究用途）；agent 侧只有只读舆情查询工具 | 工具清单审查 |
| #5 护栏在执行层 | 全部闸门都是 hooks/白名单/工具实现，提示词层只做引导不做约束 | 移除系统提示词后重跑红队用例，闸门仍全部生效 |

---

## 4. 改造不做清单

1. **不 fork、不改 pi 源码**——全部走插槽；pi 升级=改依赖版本+回归。
2. **不用 InteractiveMode / 不做终端产品**——SDK 嵌入自建 Web。
3. **不用 RPC 模式**（除非前后端分进程需求出现）。
4. **Agent 会话不发内置文件工具**（read/write/edit/bash 全不给）——pi 是 coding agent 出身，默认工具是给写代码用的，我们的场景一个都不需要。
5. **不用动态工具加载**——工具总数少（<10），1M 上下文也不缺 token，动态加载反而破坏 DeepSeek 的提示词缓存前缀。
6. **评委模型不进 pi 会话**——离线脚本。
7. **不建裸向量索引**——读书映射⑩不变。
8. **BI 图表不过 agent**——直连口径视图。

---

## 5. 风险与待验证清单

| 优先级 | 事项 | 验证方案 | 影响 |
|---|---|---|---|
| **P0** | pi-mcp-adapter 转发的 MCP 调用是否触发 `tool_call` 事件 | 装一个带 tool_call 拦截日志的测试扩展 + adapter 接一个假 MCP server，观察拦截是否生效 | 若不触发：MCP 工具脱离护栏，§2.3 调用闸失效 → MCP 桥只能用于完全可信工具，或加速查询类 TS 重写 |
| **P0** | 0.65→0.85 API 漂移 | BreachWeave/官方例子的 import 与签名对照 0.85.1 本地 d.ts（`node_modules/@earendil-works/pi-coding-agent/dist/`） | 抄代码必对照；文档已确认 import scope 改名 |
| P1 | SDK 嵌入在 Windows 服务化的稳定性（长驻进程、编码、路径） | 最小宿主 demo 跑 24h | 部署形态 |
| P1 | 并发会话下的资源占用（每用户一个 session 的内存/句柄） | 10 并发内存会话压测 | 网站容量规划 |
| P1 | DeepSeek 在并行工具调用下的表现（文档提到并行模式） | 单会话多工具并行用例 | 工具执行模式选型 |
| P2 | 自定义压缩在 1M 上下文模型上的阈值行为 | 人造长会话观察 compaction 触发点 | §2.6 预案 |
| P2 | submit_conclusion 台账比对在多轮修正下的边界情况 | 评测 harness 单元测试 | 出口闸健壮性 |

---

## 6. 与执行序列的挂接

**第①步（Agent 组装落地）的组装清单**（本文档为其施工图）：

1. [ ] 拆库三步（原定：拆库/口径视图/补打标）——先于一切工具
2. [ ] 最小宿主 demo：Bun + createAgentSession + 一个 `query_koubei_aggregate` + 全局层提示词（P0 冒烟）
3. [ ] P0 实验×2（§5）：MCP 桥护栏拦截 + API 漂移对照
4. [ ] 工具层全集 + 口径三重保障 + n 随行
5. [ ] 护栏四道闸（audit 模式先行）
6. [ ] submit_conclusion 出口闸 + 会话查询台账
7. [ ] 三维度并行（pi-subagents 先行验证）
8. [ ] Skills 方法论包 + prompt templates 操作模板
9. [ ] 评测 harness（SDK 内存会话批跑 + 轨迹落盘）

**第②步（harness 补功课）**：本文档 §1 全景图即教材索引；pi-book（底座设计决策）+ BreachWeave pentest 分支（实战）配套精读。

**第⑦步（复盘）**：§3 映射总表 + §4 不做清单是"立项依据→技术决策"叙事的直接素材。

---

## 附：出处索引

- pi 0.85.1 本地文档：extensions.md（事件/API/自定义工具/动态加载）、sdk.md（createAgentSession/SessionManager/SettingsManager/run modes/exports）、compaction.md、security.md（无沙箱/项目信任）、skills.md、json.md、prompt-templates.md、custom-provider.md（目录已核）
- 生态先例：《Prism-Agent-pi生态案例研究.md》§2.A.1 BreachWeave 源码级拆解
- 方法论：《Prism-Agent-读书映射.md》（工具描述模板/口径三重保障/两层提示词/⑧⑩⑫等）
- 上游需求：《Prism-Agent-项目提纲.md》§0-8、《Prism-Agent-任务清单.md》
