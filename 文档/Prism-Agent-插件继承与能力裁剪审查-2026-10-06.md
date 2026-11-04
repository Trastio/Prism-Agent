# Prism-Agent · 插件继承与能力裁剪审查 · 2026-10-06

> 审查日期：2026-10-06
> 审查对象：Prism 与 pi 内核的关系、插件装载与工具能力裁剪机制
> 性质：**只读审查**（未改动任何代码 / 配置）
> 方法：逐行核对网关启动参数、两份 `settings.json`、`prism-guardrails` 扩展、pi 官方文档与项目自带研究文档；并对 `node_modules` 实装状态做实测

---

## 0. 结论摘要（一页）

**一句话**：prism 不是"另一个 agent"，它就是 **pi 内核本身**；但"具备 pi 的全部插件能力"**不成立**——插件在**依赖层全装**（12 个），而"能力"在**工具层被主动关掉**。

**定性**：**主体合理，但属"能用"而非"稳固"**。方向正确（复用内核 + 隔离配置 + 入口收窄），但踩了三个典型坑：黑名单兜底脆弱、装而不用、关键不变量靠注释维持。

| 级别 | 编号 | 风险 |
|---|---|---|
| 高 | R1 | 用 **denylist**（`--exclude-tools`）兜底，新增插件/改名会静默暴露 |
| 中 | R2 | 6 个工具型插件**装而不用**，白增攻击面与启动开销 |
| 中 | R3 | `--exclude-tools` 与 `setActiveTools` 的交互靠**注释约定**，无代码级不变量 |
| 低 | R4 | permission-system 在 **RPC 无 TTY** 下的"确认通路"未验证 |
| 低 | R5 | 插件版本未全 pin + **无启动自检** |
| 低 | R6 | 两处 `extensions` 声明路径疑似失效（**需实测**） |

---

## 1. 架构事实：同一内核 / 隔离配置 / 业务封装

### 1.1 内核：同一个 `pi.exe`

Prism **没有自己的 agent 内核**。网关 [pi_gateway.mjs L274](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L274) 直接 `spawn(PI_BIN, …)`：

```
'--mode rpc', '--model', 'deepseek-v4-flash', '--approve', '--session-dir', userDir,
'--exclude-tools', 'bash,powershell,edit,write,read,grep,find,ls,web_search,web_fetch,mcp__pi_memory,mcp__pi-subagents,mcp__pi-web-access,mcp__pi-memory-mem0,mcp__pi-mcp-adapter,mcp__pi-todo,mcp__pi-workspace-history',
'-e', <项目>/.pi/extensions/prism-guardrails/index.ts
```

其中 [`PI_BIN`](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L23) = `pi-windows-x64/pi.exe`。

### 1.2 配置：独立 agent 目录 `.pi/agent-minimal`

[L279](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L279) 设 `PI_CODING_AGENT_DIR=<项目>/.pi/agent-minimal` → 本次运行的"agent 目录"（原默认 `~/.pi/agent`）被替换为 `agent-minimal`。该目录含 `settings.json` / `npm/` / `sessions/` / `auth.json` / `langfuse.json` / `models-store.json`，是一套**完整且隔离**的配置。

### 1.3 封装：prism 额外加的三样

1. **业务扩展** `prism-guardrails`——注册业务工具（query_*/sentiment_*/Atuohome/resolve_series）+ 红线 hook（[index.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts)）；
2. **RPC 网关** `pi_gateway.mjs`——会话/进程管理、`mapEvent`、上下文前缀注入；
3. **FastAPI 语义层 + Web UI**——`/dashboard/*` 取数 + 前端看板/对话。

### 1.4 两份 settings 的叠加关系

| 文件 | 角色 | 声明包数 |
|---|---|---|
| [.pi/agent-minimal/settings.json](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/settings.json#L2-L15) | 本次"全局"（agent dir） | **12** |
| [.pi/settings.json](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/settings.json#L2-L6) | 项目级（`--approve` 后加载） | 3（前者的子集） |

依据 pi 官方 [settings.md L348-369](file:///c:/Users/<you>/Desktop/Prism-Agent/pi-windows-x64/docs/settings.md#L348-L369)（项目覆盖全局、嵌套对象合并）与 [packages.md L222-229](file:///c:/Users/<you>/Desktop/Prism-Agent/pi-windows-x64/docs/packages.md#L222-L229)（包按名去重、项目条目不新增）→ **合并后仍为 12 个**。

> 对照：本机默认 pi 的 `~/.pi/agent/settings.json` 只声明 **8 个**包。**prism 声明的插件比用户自己跑的 pi 还多**（多出 web-access / subagents / mcp-adapter / workspace-history）。

**实装确认**：`.pi/agent-minimal/npm/node_modules` 实测存在，含 **262 个包目录**（`@gotgenes`/`@langfuse`/`cc-safety-net`/`pi-subagents` 等均在）→ 插件**确实已安装**。

---

## 2. 插件清单与在 prism 对话路径下的实际状态

| 插件包 | 类型 | 在 prism 对话路径 |
|---|---|---|
| `@gotgenes/pi-permission-system` | hook（工具级批准） | **保留**（R4 待验证确认通路） |
| `cc-safety-net@2.4.15` | hook（安全网） | **保留** |
| `@langfuse/pi-observability-plugin` | hook（观测） | **保留**（有效） |
| `@narumitw/pi-usage` | hook（用量/状态） | 加载；对 PM 用户价值存疑 |
| `@juicesharp/rpiv-ask-user-question` | 交互（ask user） | 未在排除表；**待验证** |
| `pi-web-access` | 工具（web_search/web_fetch） | **已排除** |
| `pi-subagents` | 工具 | **已排除** |
| `pi-memory` | 工具 | **已排除**（`mcp__pi_memory`） |
| `@amaster.ai/pi-memory-mem0` | 工具 | **已排除**（`mcp__pi-memory-mem0`） |
| `@juicesharp/rpiv-todo` | 工具 | **已排除**（`mcp__pi-todo`） |
| `pi-mcp-adapter` | 工具 | **已排除**（`mcp__pi-mcp-adapter`） |
| `pi-workspace-history` | 工具 | **已排除**（`mcp__pi-workspace-history`） |

---

## 3. 两道能力闸

### 3.1 闸 1 · 网关 `--exclude-tools`（启动即排除）

pi 官方 [README L581-586](file:///c:/Users/<you>/Desktop/Prism-Agent/pi-windows-x64/README.md#L581-L586)：

> `--exclude-tools <list>` — **Disable specific tool names across built-in, extension, and custom tools**

→ 语义是**工具级过滤**，作用覆盖内置/扩展/自定义工具；**不停用插件本身**。因此：

- **工具型插件**（subagents/memory/mem0/web-access/todo/mcp-adapter）→ 工具被移除，**用户够不到**；
- **hook 型插件**（permission / cc-safety / langfuse）→ 插件照常加载，hook **仍然生效**。

此分工在扩展注释中被明确写出 —— [index.ts L648-652](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L648-L652)：

> permission-system（已运行）：工具级批准，弹确认框；guardrail（此处）：行为级拦截……；`--exclude-tools` 管 pi 内置危险工具排除。两者不重叠，叠加使用。

### 3.2 闸 2 · 扩展 `setActiveTools`（按 scope 二次收窄）

[index.ts L578-596](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L578-L596)：

| scope | 生效工具集 |
|---|---|
| `bi_reviews` | `['query_reviews', 'resolve_series']` |
| `bi_sales` | `['query_sales', 'resolve_series']` |
| `bi_config` | `['query_config', 'resolve_series']` |
| `agent` | **不动**（注释："全 23 工具"）→ 仅由闸 1 约束 |
| `series_key` 为空 | `setActiveTools([])` → **真 fail-closed**（红线#7） |

> 附带结论：此扩展已用 `setActiveTools([])` 实现"空 series 真阻断"（L592-595），**非提示词阻断**，符合红线#5。

### 3.3 两闸交互顺序分析

**当前无"排掉又被放回"的漏洞**：
- `bi_*` 模式 `setActiveTools` 给出的是**显式白名单**，本就不含被排除工具；
- `agent` 模式**不调用** `setActiveTools`，闸 2 不介入，闸 1 唯一生效。

**但这是隐式依赖**——靠"agent 模式千万别调 `setActiveTools(全量)`"这条注释维持。若将来有人在 `agent` 模式调用一次宽白名单，`--exclude-tools` 即被架空。→ 见 R3。

---

## 4. 风险清单

### R1【高】用 denylist 兜底，本质脆弱

`--exclude-tools` 是**排除清单**：将来任何新装插件只要注册了工具就**自动暴露**，除非有人记得手动加进 [那行长列表](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L272)。且该列表靠**工具名精确匹配**，插件改名/换前缀即**静默失效**（不报错、直接暴露）。

→ 与项目自身"**能力不发放，而非发放后拦截**"的原则（[pi改造研究 L105](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-pi改造研究.md#L105)）相悖：应是 **allowlist（只放业务工具）**，而非"排掉我不要的"。

### R2【中】装而不用，白增攻击面

12 个包全装，其中 6 个工具型在 prism 里**根本够不到**。
- 若确实不用 → 应从 `agent-minimal` 的 `packages` 里**直接删掉**（减攻击面 + 减启动开销 + 减配置漂移）；
- 若它们其实是给**后台批跑 / 评测 harness** 用的 → 就不该与面向用户的只读对话**共用一份 agent 配置**（现为"一份配置伺候所有场景"，语义混浊）。

### R3【中】关键不变量靠注释维持

`agent` 模式不重设工具集这一约束，**无代码强制**。建议把"可发放工具集"变为**单一来源常量**，`agent` 模式也显式取该常量，使闸 1 与闸 2 语义一致、可被自检。

### R4【低，但安全相关】permission-system 在 RPC 下的确认通路未验证

permission-system 是**交互式确认**插件，而 prism 是 RPC 无 TTY。若它弹确认而前端未接 `/ui-response`，会**卡住或静默放行**——两者都不可接受。项目存在 `/ui-response` 通路（[pi_gateway.mjs L409](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L409) 附近），但 permission 的批准是否**真被转发到前端**，本次未验证。→ 见附 B。

### R5【低】版本未全 pin + 无启动自检

仅 pin 了 `cc-safety-net@2.4.15`，其余浮动。pi 升级若改动 settings 合并 / 排除语义，prism 行为会漂移。且**无任何机制**在启动时断言"关键插件已加载 / 关键工具确实不可达"。

### R6【低】两处 `extensions` 声明路径疑似失效（需实测）

- [agent-minimal/settings.json L16-18](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/settings.json#L16-L18) 写 `.pi/extensions/prism-guardrails/index.ts`，但该路径相对 **agent-minimal** 解析 → `.pi/agent-minimal/.pi/extensions/…`（不存在）；
- [.pi/settings.json L7-9](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/settings.json#L7-L9) 写 `.pi/extensions/…`，相对 **`.pi`** 解析 → `.pi/.pi/extensions/…`（不存在）。

依据 [settings.md L279-281](file:///c:/Users/<you>/Desktop/Prism-Agent/pi-windows-x64/docs/settings.md#L279-L281)（路径相对各自 settings 文件解析）。→ 真实加载应靠网关 `-e <绝对路径>`；这两条声明疑似**死配置**，易误导读者。

---

## 5. 建议改法（对应 R1–R6）

| 编号 | 改法 |
|---|---|
| R1 | 改为**白名单语义**：显式列出可发放工具（业务工具 + 必要内置），或在扩展 `before_agent_start` 中统一 `setActiveTools` 到业务白名单，`--exclude-tools` 仅作兜底 |
| R2 | 从 `agent-minimal` 删除不用的工具型包；若后台场景需要，拆出**独立 agent 配置目录**（如 `.pi/agent-harness`） |
| R3 | 提取**单一工具白名单常量**（既供 `setActiveTools` 也供校验），`agent` 模式同样取该常量 |
| R4 | 实测 permission 在 RPC 下的行为：确认审批是否经 `/ui-response` 转发；否则考虑改为自动批准 + 事后审计，或禁用 |
| R5 | pin 关键包版本；加**启动自检**：关键插件未加载或关键工具意外可达时 **fail-closed** |
| R6 | 删除两处失效的 `extensions` 声明，或改正为正确相对路径，统一以 `-e` 为唯一加载源 |

---

## 6. 合理性判定

- **主体合理**：复用 pi 原生机制、独立 agent 配置、入口收窄、hook 型插件保留——这四点都对，是产品化 agent 的标准模式。
- **不够"稳固"**：踩了三个典型坑——**黑名单兜底（R1）**、**装而不用（R2）**、**关键不变量靠注释（R3）**；另有两条待验证（R4/R6）与一条可维护性缺口（R5）。
- **结论**：**方向合理、可用；收敛 R1/R2/R3、实测 R4/R6、补 R5 之后，可称"合理且稳妥"。**

---

## 附 A · 事实证据索引

| 事实 | 证据 |
|---|---|
| 同内核 spawn | [pi_gateway.mjs L271-283](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L271-L283) |
| `PI_CODING_AGENT_DIR` | [L279](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L279) |
| exclude-tools 语义 | [README L581-586](file:///c:/Users/<you>/Desktop/Prism-Agent/pi-windows-x64/README.md#L581-L586) |
| 12 包声明 | [agent-minimal/settings.json L2-15](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/settings.json#L2-L15) |
| 3 包声明 | [.pi/settings.json L2-6](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/settings.json#L2-L6) |
| 合并/去重规则 | [settings.md L348-369](file:///c:/Users/<you>/Desktop/Prism-Agent/pi-windows-x64/docs/settings.md#L348-L369)、[packages.md L222-229](file:///c:/Users/<you>/Desktop/Prism-Agent/pi-windows-x64/docs/packages.md#L222-L229) |
| 项目信任 | [settings.md L11-19](file:///c:/Users/<you>/Desktop/Prism-Agent/pi-windows-x64/docs/settings.md#L11-L19) |
| setActiveTools 分 scope | [index.ts L578-596](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L578-L596) |
| 职责划分注释 | [index.ts L648-652](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L648-L652) |
| 能力不发放原则 | [pi改造研究 L105](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-pi改造研究.md#L105) |
| 无需 fork 内核 | [pi改造研究 L9-13](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-pi改造研究.md#L9-L13) |
| node_modules 实装 | 实测 262 个目录 |

## 附 B · 待实测清单

1. **permission-system 在 RPC 下的批准通路**：发一条会触发工具批准的消息，观察是否被前端 `/ui-response` 承接，或是否阻塞/静默放行。
2. **`rpiv-ask-user-question` 的工具是否可达**：它不在 `--exclude-tools` 列表中，需确认其实际工具名与是否暴露给模型。
3. **`pi list` / 运行期工具快照**：确认实际加载的插件与最终暴露的工具清单（验证 R1 的"改名即暴露"）。
4. **两处 `extensions` 声明是否生效**：临时移除网关 `-e` 参数，看扩展是否仍加载（验证 R6）。
5. **`agent` 模式最终工具集**：抓一次 `agent` scope 的工具列表，确认闸 1 生效且未被闸 2 放大。