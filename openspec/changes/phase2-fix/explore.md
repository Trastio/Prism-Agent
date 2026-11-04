# 阶段2·集成修复（用 pi 官方能力重写）· Step 1 explore

> Prism-Agent 开发流程 · Step 1 explore
> 日期：2026-10-04
> 范围：用 pi-agent 官方能力重写集成层，替代手造轮子 pi_server.mjs + 修 code-review 18 问题
> 上游：phase2-integration（code-review 18 findings）+ 6 个 pi-agent 深读子 agent 报告

---

## 一、重大发现：pi_server.mjs 是造轮子

经 6 个子 agent 深读 pi-agent 全部文档（sdk.md/extensions.md/sessions.md/session-format.md/security.md/compaction.md/containerization.md/rpc.md/models.md），确认：

**pi-agent 自带的官方能力覆盖了我们在 pi_server.mjs 里手写的全部功能**：

| 我们手写的 | pi 官方提供 | 判定 |
|---|---|---|
| pi_server.mjs HTTP 服务 | AgentSession in-process（rpc.md 第 5 行明说 Node 直接 import） | 造轮子 |
| sessionPool Map 缓存 | SessionManager.create/open/list（文件持久化） | 造轮子 |
| mapEvent 事件映射 | session.subscribe（18 种事件，官方映射） | 造轮子 |
| guardrail.ts 护栏 | pi.on('tool_call') → {block:true, reason, terminate} | 没用 pi 能力 |
| grounding.ts 独立调用 | pi.on('tool_result') → {content, isError} patch | 没用 pi 能力 |
| completion.ts 独立验证 | agent_settled 事件（注意：无 retry 返回，用 sendUserMessage） | 没用 pi 能力 |
| 没配压缩 | session_before_compact hook + keepRecentTokens:30000 | 没用 pi 能力 |
| 没注入 SYSTEM.md | before_agent_start → {systemPrompt, message} | 没用 pi 能力 |

**准则对照**："pi-agent 满足的不造轮子" → pi_server.mjs + sessionPool + guardrail.ts + grounding.ts + completion.ts 的"独立运行"部分都是造轮子，应该用 pi 的 extension/hook 机制替代。

---

## 二、之前用错的 API

| 错误 | 正确 | 根因 | 影响 |
|---|---|---|---|
| `SessionManager.inMemory()` | `SessionManager.create(cwd, sessionDir)` | inMemory 不持久化 | session 上下文丢失 |
| `SessionManager.open(session_id)` | `SessionManager.open(sessionFile)` | open 第一参数是文件 path | open 失败→新建→上下文丢 |
| sessionPool 复用 session 实例 | 每请求 createAgentSession（或 AgentSessionRuntime） | 复用导致竞态 | 并发串台+订阅泄漏+OOM |
| noExtensions 禁所有扩展 | 精准禁 permission-system（保留 langfuse） | 一刀切 | langfuse 被禁 |
| 护栏在 TS 层独立 | pi.on('tool_call') hook | 没用执行层 | 绕过 pi 生命周期 |
| 完成验证器独立 | agent_settled 事件 | 没接生命周期 | 验证时机不对 |

---

## 三、pi-agent 官方能力清单（对照 Prism 需求）

### session 管理（pi core 内置，不需插件）
- `SessionManager.create(cwd, sessionDir?)` 新建持久化（JSONL 文件）
- `SessionManager.open(sessionFile)` 恢复 transcript（已验证 CONTEXT_RESTORED=YES）
- `SessionManager.continueRecent(cwd)` 续最近
- `SessionManager.list(cwd)` 列会话
- 每用户独立 sessionDir：`SessionManager.create(cwd, '.pi/sessions/<userId>/')`
- **不用 Redis**（文件持久化够，pi 官方无 Redis SessionManager）

### AgentSession 关键 API
- `subscribe(listener) → unsubscribe`（修订阅泄漏）
- `abort()`（修客户端中断）
- `dispose()`（修资源清理）
- `sessionFile` / `sessionId`（直接拿，不用 list 查）
- `isStreaming`（判断流式中）
- `compact()` / `abortCompaction()`（手动压缩）
- `setActiveToolsByName()`（scope 锁定）

### Extension API（hook 机制）
- `pi.on('tool_call')` → `{block:true, reason, terminate}` 拦截（红线#2）
- `pi.on('tool_result')` → `{content, isError}` patch 改写（红线#1 grounding）
- `pi.on('before_agent_start')` → `{systemPrompt, message}` 注入（SYSTEM.md + 车系上下文）
- `pi.on('agent_settled')` → 完成验证器（注意：无 retry 返回，用 sendUserMessage）
- `pi.on('session_before_compact')` → 自定义压缩（Prism 上下文层）
- `pi.on('session_start')` → 初始化 in-memory 状态
- `pi.on('session_shutdown')` → 清理资源
- `pi.registerTool()` / `defineTool` + `customTools`（业务工具）
- `pi.appendEntry()` / `pi.sendMessage()`（评估元数据 + 注入）

### 模型管理
- `getModel('deepseek', 'deepseek-v4-flash')` from `@earendil-works/pi-ai/compat`
- `ModelRuntime.create()` 进程级单例，共享
- GLM/Kimi 双评委：models.json custom provider（Kimi 必带 `deferredToolsMode: "kimi"`）

### 压缩
- `.pi/settings.json`: `{"compaction":{"enabled":true,"reserveTokens":16384,"keepRecentTokens":30000}}`
- `session_before_compact` hook 自定义摘要

### 部署
- Plain Docker per-instance + SLB（50-100 并发，10-20 容器）
- 凭证走环境变量
- session-dir 指独立路径（每容器/每用户独立 volume）

---

## 四、phase2-fix 新方向：用 pi extension 替代手写层

### 要删的（造轮子）
- `pi_server.mjs` 的 sessionPool / mapEvent / getOrCreateSession → 用 SessionManager + createAgentSession
- `src/tools/guardrail.ts` 独立运行 → 用 pi.on('tool_call') extension
- `src/verify/grounding.ts` 独立调用 → 用 pi.on('tool_result') extension
- `src/verify/completion.ts` 独立验证 → 用 pi.on('agent_settled') extension

### 要保留的（业务必需，pi 没有）
- `src/tools/query_sales/reviews/config.ts` 业务工具（defineTool 定义，但 execute 逻辑保留）
- `src/identity/resolve.ts` 对象身份映射
- `src/registry/datasource.ts` 数据源注册表
- `src/views/refresh.py` 口径视图
- `prism-api/main.py` FastAPI 网关（HTTP 接口层，pi 不做 HTTP server）
- `prism-web/` 前端
- `eval/` 评估集 + 统计栈

### 新增的（pi extension）
- `.pi/extensions/prism-guardrails/index.ts`：tool_call 拦截 + tool_result grounding + agent_settled 验证 + before_agent_start 注入 + session_before_compact 自定义压缩

---

## 五、架构变化

### 之前（phase2-integration）
```
前端 → FastAPI → pi_server.mjs(手写 HTTP + sessionPool + mapEvent) → pi SDK
                     ↕ 独立运行 guardrail.ts / grounding.ts / completion.ts
```

### 之后（phase2-fix）
```
前端 → FastAPI → Node 常驻(AgentSession in-process)
                   ├─ SessionManager.create/open（文件持久化，每用户独立 dir）
                   ├─ customTools: query_sales/reviews/config（defineTool）
                   ├─ extension: prism-guardrails（pi.on hook）
                   │   ├─ before_agent_start → 注入 SYSTEM.md + 车系上下文
                   │   ├─ tool_call → block 裸 SQL / 写操作（红线#2）
                   │   ├─ tool_result → grounding 改写（红线#1）
                   │   ├─ agent_settled → 完成验证器（sendUserMessage retry）
                   │   └─ session_before_compact → 自定义压缩
                   ├─ subscribe → unsubscribe（修泄漏）
                   ├─ abort()（修中断）
                   └─ dispose()（修清理）
```

---

## 六、agent_settled 关键坑（ext-reader 发现）

**agent_settled 无原生 retry 返回机制**——完成验证器失败后只能用 `pi.sendUserMessage()` 强制再来一轮：
- 不是原生 retry，消耗一次用户轮次
- 要防递归（用 appendEntry 存"已验收"标记）
- max 1 次 continuation 用 sendUserMessage 实现

---

## 七、code-review 18 问题对照新方案

| # | 问题 | 新方案怎么修 |
|---|---|---|
| 1 P0 | user_id 路径穿越 | 白名单校验（不变） |
| 2 P1 | SessionManager.open 误用 | 用 sessionFile（pi session.sessionFile 属性） |
| 3 P1 | 并发竞态 | 每请求 createAgentSession（删 sessionPool） |
| 4 P1 | 订阅泄漏 | subscribe 返回 unsubscribe，req.on close 调 |
| 5 P1 | 客户端中断 | session.abort() + req.on('close') |
| 6 P1 | OOM | 删 sessionPool，session 用完 dispose() |
| 7 P1 | message 挂死 | try 包裹 + 类型校验 |
| 8 P1 | 前端卡死 | try/catch + finally |
| 9-18 P2 | 各种健壮性 | 随重写一起修 |

---

## 八、explore 结论

phase2-fix 从"修 bug"升级为"用 pi 官方能力重写集成层"：
1. 删 pi_server.mjs 手写部分，用 AgentSession in-process
2. 删独立 guardrail/grounding/completion，用 pi extension hook
3. 修 SessionManager 用法（create/open 文件模式）
4. 修 18 个 code-review 问题
5. 接 pi 全生命周期（before_agent_start/agent_settled/compaction）

**下一步 Step 2 propose**：重写 proposal + design + tasks。
