# pi-agent 二次开发参考笔记

> 一手来源：pi.dev 官方文档 + 本地 pi-windows-x64/docs/（0.85.1）+ GitHub earendil-works/pi
> 视频补充：B站 BV139bD6gEa8《Pi 大道至简，超越Codex和Claude Code的极简Agent》UP主：技术爬爬虾
> 用途：Prism-Agent 基于 pi SDK 二次开发的接口参考

---

## 一 pi 设计哲学（大道至简）

- **"Pi is a minimal agent harness. Adapt Pi to your workflows, not the other way around."**
- **Primitives, not features**：别的agent内置的功能（sub-agents/plan mode/permission gates/sandboxing），pi让你自己建或装包
- 视频简介确认：**四个默认工具**（读文件/写文件/改文件/运行命令），**系统提示词仅1000 token**，多项基准测试代码质量/速度/成本超过Codex和Claude Code
- 四种模式：interactive(TUI) / print(JSON) / RPC(stdin/stdout JSONL) / **SDK**（Prism走这条）

### 1.1 基准测试数据（Composio，中位耗时，视频30s处）
| Agent | 耗时 |
|---|---|
| **Pi Agent** | **161.7s（最快）** |
| Hermes Agent | 179.5s |
| Codex | 236.2s |
| OpenCode | 271.1s |
| Kimi Code | 297.1s |
| Claude Code | 347.6s（最慢） |

Pi 比 Codex 快 31%，比 Claude Code 快 53%。"Pi's lead fits its minimal design."

### 1.2 "No X" 设计表（视频1080s，每项砍掉的功能都给扩展方案）
| 默认没有 | 替代/扩展方式 |
|---|---|
| No MCP | 写 extension 添加 MCP 支持，或装一个包 |
| No sub-agents | 用 Skills 构建 CLI 工具，或自行扩展 |
| No permission popups | 容器内运行，或自建确认流程 |
| No plan mode | 写计划到文件，或扩展 |
| No built-in to-dos | 用 TODO.md 文件，或扩展 |
| No background bash | 用 tmux，完全可观测、直接交互 |

→ 极简不是能力不足，而是有意设计。Prism 落点：不裸SQL护栏用 tool_call hook 自建、sub-agent 用 pi-subagents 包、permission 用容器+hook。

### 1.3 四工具确认（视频1050s）
1. **Read**（读文件）
2. **Write**（写文件）
3. **Edit**（改文件）
4. **Bash**（运行命令）
原话："默认只有四个基础工具，其实这四个工具已经足够强大。"

### 1.4 Pi 能自己给自己写插件（视频2420s）
"DIY 插件，打造专属 Agent——不止支持插件，还能自己给自己写插件。"Prism 落点：可以让 Pi 自己生成 extension 代码，/reload 热加载。

---

## 二 包结构（二次开发全景）

| 包 | 作用 | Prism用 |
|---|---|---|
| `@earendil-works/pi-coding-agent` | 交互CLI + **SDK入口** | ✅ SDK嵌入 |
| `@earendil-works/pi-agent-core` | Agent runtime+工具调用+状态管理 | 底层 |
| `@earendil-works/pi-ai` | 统一多provider LLM API（15+） | ✅ DeepSeek |
| `@earendil-works/pi-durable` | 持久化会话/任务/文档runtime | 可选 |
| `@earendil-works/pi-tui` | 终端UI库 | 不用(自建web) |
| `@earendil-works/chord` | 应用组合runtime | 可选 |
| `@earendil-works/pi-telemetry` | 遥测契约 | ✅ 埋点 |

---

## 三 Agent loop 核心机制

- 会话是**树结构**（tree），每条路径是branch，当前entry标识active branch
- 一轮：提交消息→Pi构建请求(system prompt+active branch+tools+skills)→provider流式响应→执行tool_calls→记录结果→若需继续则下一轮
- **steering消息**在当前assistant turn后插入；**follow-up**等agent完成pending工作后
- Compaction插入summary entry替换旧消息（原始entry保留在树里）

---

## 四 Extensions 二次开发（Prism核心接口）

### 4.1 基础
- Extension是TypeScript模块，导出default factory，接收`ExtensionAPI`
- 放 `~/.pi/agent/extensions/`（全局）或 `.pi/extensions/`（项目），`pi -e ./path.ts` 临时加载
- jiti即时编译无需build；三种组织：单文件/目录(index.ts)/package(带package.json)
- **生命周期纪律**：factory里别启动process/socket/watcher；从`session_start`启动长资源，`session_shutdown`清理

### 4.2 核心 API（Prism要用的）
```typescript
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  // 加模型可调用工具（Prism语义工具）
  pi.registerTool({
    name: "query_sales",
    description: "查汽车销量...",
    parameters: Type.Object({ car_model: Type.String(), ... }),
    async execute(toolCallId, params, signal, onUpdate, ctx) { ... }
  });

  // 观察生命周期（Prism红线护栏）
  pi.on("tool_call", async (event, ctx) => { ... });      // 可block
  pi.on("tool_result", async (event, ctx) => { ... });    // 可改写结果
  pi.on("before_agent_start", (event, ctx) => { ... });   // 注入棱镜SOP

  // 加 / 命令
  pi.registerCommand("hello", { handler: async (name, ctx) => { ... } });

  // 加模型provider
  pi.registerProvider("local", { baseUrl, apiKey, models: [...] });

  // 持久化非上下文数据
  pi.appendEntry({ ... });
}
```

### 4.3 关键事件（Prism落点）

| 事件 | 能做什么 | Prism落点 |
|---|---|---|
| `before_agent_start` | 改prompt sections/tools/guidelines；`forceSystemPrompt`替换整个prompt | **注入棱镜SOP+状态栏** |
| `tool_call` | **mutate input** 或 `{block:true, reason, terminate}` 拦截 | **红线#1/#3护栏**（拦截裸SQL/越权） |
| `tool_result` | 改写content/details/isError，handlers链式组合 | **grounding数字溯源**（改写编造数字） |
| `agent_before_settle` | 最终actionable边界，append entries+请求continuation | **完成验证器**（核对后才settle） |
| `context` | 转换对话消息（不含prompt/tool system） | 上下文压缩定制 |
| `session_start/shutdown` | 启动/清理长资源 | DB连接/事件触发器 |

### 4.4 tool_call 拦截代码模式（红线护栏直接抄）
```typescript
pi.on("tool_call", async (event, ctx) => {
  if (isToolCallEventType("bash", event)) {
    event.input.command = `source ~/.profile\n${event.input.command}`; // mutate
    if (event.input.command.includes("rm -rf")) {
      return { block: true, reason: "Dangerous command", terminate: true };
    }
  }
  // 自定义工具类型
  if (isToolCallEventType<"my_tool", MyToolInput>("my_tool", event)) {
    event.input.action;  // typed
  }
});
```
- `event.input` 可变，mutation影响实际执行，后续handler看到前一个的修改，**不再re-validation**
- 并行模式下sibling tool_calls不保证看到彼此结果

### 4.5 tool_result 改写代码模式（grounding用）
```typescript
pi.on("tool_result", async (event, ctx) => {
  // event.content, event.details, event.isError, event.usage
  // 可返回partial patch: {content?, details?, isError?, usage?}
  if (isBashToolResult(event)) {
    // event.details typed as BashToolDetails
  }
});
```
- handlers链式（middleware），每个看到前一个的修改

---

## 五 SDK 嵌入（Prism接入方式）

```typescript
import { createAgentSession, SessionManager } from "@earendil-works/pi-coding-agent";

const { session } = await createAgentSession({
  sessionManager: SessionManager.inMemory(),  // 内存会话（多租户隔离）
  cwd: "/workspace/prism",
});

session.subscribe(event => {
  if (event.type === "message_update" && event.assistantMessageEvent.type === "text_delta") {
    process.stdout.write(event.assistantMessageEvent.delta);
  }
});

try {
  await session.prompt("分析比亚迪汉销量");
  console.log(session.getLastAssistantText());
} finally {
  session.dispose();
}
```
- `prompt()` 完成时resolve；steering vs follow-up必须显式指定（不指定会reject）
- `SessionManager.inMemory()` 不落盘（多用户隔离底座）
- `AgentSessionRuntime`：newSession/switchSession/fork/importFromJsonl
- `session.systemPrompt` 只读（含未发送的变更）；`session.getActiveToolNames()`

---

## 六 Compaction 机制（长会话关键）

- 触发：`contextTokens > contextWindow - reserveTokens`（默认reserve 16384）
- `keepRecentTokens` 默认 20k（保留最近的token数）
- 流程：找cut point→提取messages→LLM生成summary→append CompactionEntry→rebuild context
- CompactionEntry 含 summary + firstKeptEntryId，原始entry保留在树里
- provider context-overflow错误可触发一次 compact-and-retry
- 手动 `/compact [instructions]`
- **summarization请求禁用prompt-cache writes**（一次性prompt unlikely复用）

---

## 七 Skills（按需加载指令）

- SKILL.md + frontmatter（name/description）+ 可选scripts/references/assets
- 启动时只加name+description到system prompt，**full instructions按需加载**（progressive disclosure，不破prompt cache）
- description决定何时加载，要写清"做什么+何时用"（别写"Helps with PDFs"）
- `/skill:name args` 强制加载；`disable-model-invocation:true` 只允许显式调用
- Agent Skills规范兼容 `~/.agents/skills/` 和 `.agents/skills/`
- Prism落点：棱镜三维度各一个skill（review_skill/sales_skill/config_skill）

---

## 八 容器化部署（工作⑤直接参考）

四种模式：
| 模式 | 隔离什么 | 适用 |
|---|---|---|
| **Gondolin扩展** | 内置工具+!命令进micro-VM | host认证+VM工具隔离 |
| **Plain Docker** | 整个pi进程 | 简单本地隔离 |
| OpenShell | 整个pi进策略沙箱 | 本地/远程托管沙箱 |
| Docker Sandboxes | 整个pi进托管沙箱 | provider key留host |

### Plain Docker（最简单，Prism起步用）
```dockerfile
FROM node:24-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends bash ca-certificates git ripgrep && rm -rf /var/lib/apt/lists/*
RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent
WORKDIR /workspace
ENTRYPOINT ["pi"]
```
```bash
docker build -t pi-sandbox -f Dockerfile.pi .
docker run --rm -it -e DEEPSEEK_API_KEY -v "$PWD:/workspace" -v pi-agent-home:/root/.pi/agent pi-sandbox
```

---

## 九 安全（红线#3呼应）

- pi无内建权限系统，用启动进程的权限
- **project trust**控制是否加载项目资源（.pi/settings.json/extensions/skills等），但不是安全边界
- 三种运行方式：直接(用户权限) / 容器内(最强) / host+工具路由进隔离环境
- "Treat model-generated commands and code as untrusted"——prompt injection防护
- **Prism落点**：红线#3靠容器化+tool_call hook拦截，不靠prompt

---

## 十 生态包（已装+待考虑）

### 已装（nicopreme维护三大件）
- `pi-mcp-adapter` (1.1M/月) —— MCP桥
- `pi-subagents` (459K/月) —— subagent委托
- `pi-web-access` (430K/月) —— 联网搜索/URL抓取/PDF/YouTube

### 待考虑（高相关）
- `@aliou/pi-guardrails` —— 护栏扩展（红线#1/#3）
- `@chankov/agent-fleet` —— subagent编排+verification contract（三维度并行备选）
- `billion-context` —— 上下文压缩5x（长会话）
- `opencode-agent-skill` —— evidence-gated completion（和完成验证器同源！）
- `@juicesharp/rpiv-ask-user-question` —— 结构化问卷（需求澄清阶段）
- `@vigolium/piolium` —— 多阶段安全审计，专家子Agent+隔离上下文窗口（视频提到）
- 内置Skills：`mcp-scripting` / `playwright-cli` / `workflow-authoring` / `workflow-patterns`

---

## 十一 Prism 二次开发落点速查

| Prism需求 | pi接口 | 文件:行号 |
|---|---|---|
| 嵌入pi到Prism后端 | `createAgentSession` SDK | sdk.md |
| 多用户会话隔离 | `SessionManager.inMemory()` | sdk.md |
| 棱镜SOP注入 | `before_agent_start` event | extensions.md:530 |
| 红线#1不裸SQL护栏 | `tool_call` {block:true} | extensions.md:778 |
| grounding数字溯源 | `tool_result` 改写 | extensions.md:842 |
| 完成验证器 | `agent_before_settle` | extensions.md |
| 语义工具注册 | `pi.registerTool()` + TypeBox | extensions.md |
| 三维度skill | SKILL.md + frontmatter | skills.md |
| 长会话压缩 | compaction (reserveTokens/keepRecentTokens) | compaction.md |
| 容器化部署 | Plain Docker / Gondolin | containerization.md |
| DeepSeek provider | `pi.registerProvider()` 或 auth.json | custom-provider.md |

---

*笔记基于 pi.dev 官方文档 + 本地 0.85.1 docs + GitHub。视频文字稿待补充（bilibili元数据加载受限，等网络工具恢复后补基准测试数据）。*
