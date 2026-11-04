# pi-Agent 全模块能力地图（对照 Prism-Agent 需求）

> 2026-10-04 · 基于 6 个子 agent 深读 pi 0.85.1 全部文档（sdk/extensions/sessions/session-format/security/compaction/containerization/rpc/models）
> 准则：pi-agent 满足的不造轮子，业务工具/验证器/反代是项目必需

---

## 一、核心发现：pi 自带完整 agent-loop，不需手写

pi-agent 的官方能力覆盖了 agent 全生命周期：session 管理 / 事件流 / 工具注册 / 护栏 / grounding / 完成验证 / 压缩 / 模型管理 / 部署。

**Prism 之前手写的 pi_server.mjs + sessionPool + guardrail.ts + grounding.ts + completion.ts 的"独立运行"部分都是造轮子**，应该用 pi 的 extension/hook 机制替代。

---

## 二、SessionManager（pi core 内置，不是插件）

### 静态方法
| 方法 | 签名 | 用途 |
|---|---|---|
| `SessionManager.create(cwd, sessionDir?)` | 新建持久化 session（写 JSONL 文件） | Prism 每用户建会话 |
| `SessionManager.open(sessionFile)` | 打开指定 .jsonl 文件恢复 transcript | Prism 续接历史会话 |
| `SessionManager.continueRecent(cwd)` | 续最近会话 | 用户重开页面 |
| `SessionManager.list(cwd)` | 列当前项目 session | sidebar 会话列表 |
| `SessionManager.inMemory(cwd?, start?, entries?)` | 内存 session（不持久化） | Redis 恢复用（暂不需要） |
| `SessionManager.forkFrom(sourcePath, targetCwd)` | 跨项目分叉 | 评估批跑 |

### 关键事实
- **每用户独立 sessionDir**：`SessionManager.create(cwd, '.pi/sessions/<userId>/')`
- **open 第一参数是文件 path 不是 session_id**：用 `session.sessionFile` 属性拿
- **inMemory 不持久化** → Prism 用 create（文件模式）
- **已验证**：open(sessionFile) 恢复 transcript 进 LLM 上下文（CONTEXT_RESTORED=YES）
- **不用 Redis**（pi 无官方 Redis SessionManager，文件持久化够）
- **pi-session-manager 插件全是第三方 TUI 浏览器，无官方，不支持多用户隔离**

---

## 三、AgentSession 关键 API

| API | 用途 | Prism 用法 |
|---|---|---|
| `prompt(text, {streamingBehavior})` | 发 prompt | steer/followUp 排队 |
| `subscribe(listener) → unsubscribe` | 事件流 | NDJSON 转 SSE 给前端 |
| `abort()` | 中断当前操作 | 客户端断开时调 |
| `dispose()` | 清理资源 | session 超时清理 |
| `sessionFile` / `sessionId` | 文件路径 / ID | 续接用 |
| `isStreaming` | 是否流式中 | 前端状态 |
| `setActiveToolsByName(names)` | 工具白名单 | scope 锁定 |
| `compact(customInstructions?)` | 手动压缩 | 长对话 |
| `agent.state.messages` | 对话历史 | 验证器读取 |

### 事件类型（18 种）
- 流式：`message_start/update/end`（update 含 text_delta/thinking_delta）
- 工具：`tool_execution_start/update/end`
- 生命周期：`agent_start/end`、`turn_start/end`、`agent_settled`
- 压缩：`compaction_start/end`
- 重试：`auto_retry_start/end`
- 队列：`queue_update`

### 关键坑
- session 替换后 subscribe 失效，需重订阅
- streaming 期间 prompt 不带 streamingBehavior 抛错
- **agent_settled ≠ agent_end**：agent_end 可能继续 retry/compact/follow-up；agent_settled 才是真完成

---

## 四、Extension API（hook 机制，红线核心）

### 注册方法
`pi.on(event, handler)` / `pi.registerTool` / `pi.registerCommand` / `pi.registerProvider` / `pi.registerShortcut` / `pi.registerFlag` / `pi.sendMessage` / `pi.sendUserMessage` / `pi.appendEntry` / `pi.setActiveTools` / `pi.setModel` / `pi.events`（跨扩展通信）

### 关键 hook（can-block / can-modify）
| 事件 | can-block | can-modify | Prism 用途 |
|---|---|---|---|
| `before_agent_start` | 否 | 是（systemPrompt + message 注入） | 注入 SYSTEM.md + 车系上下文 + 红线 |
| `tool_call` | **是**（block+terminate） | 是（mutate input） | 红线#2 裸 SQL 拦截 |
| `tool_result` | 否 | **是**（content/isError/usage patch） | 红线#1 grounding 改写 |
| `agent_settled` | 否 | 否 | 完成验证器（注意：无 retry 返回） |
| `session_before_compact` | 是（cancel） | 是（自定义 summary） | Prism 上下文层自定义压缩 |
| `context` | 否 | 是（messages deep copy） | 上下文裁剪/注入 |
| `session_start` | 否 | 否 | 初始化 in-memory 状态 |
| `session_shutdown` | 否 | 否 | 清理 session-scoped 资源 |

### tool_call block 机制
```typescript
pi.on("tool_call", (event, ctx) => {
  // event.input 可变，原地 mutate 改参数
  return { block: true, reason: "...", terminate: true };  // 拦截
});
// terminate 需整批 terminating 才停 agent
// handler 抛错 = block（fail-safe）
```

### tool_result modify 机制
```typescript
pi.on("tool_result", (event, ctx) => {
  // 链式 middleware，看到前一个 handler 改后的 result
  return { content: [...], isError: true };  // 部分 patch
});
```

### agent_settled 关键坑
- **无原生 retry 返回机制**
- 完成验证器失败后只能用 `pi.sendUserMessage()` 强制再来一轮
- 消耗一次用户轮次，要防递归（appendEntry 存"已验收"标记）

### before_agent_start 注入
```typescript
pi.on("before_agent_start", (event, ctx) => {
  return {
    systemPrompt: event.systemPrompt + "\n## Prism 红线...",
    message: { customType: "prism-redline", content: "...", display: false }
  };
});
```

---

## 五、ModelRuntime + 模型管理

### DeepSeek（主 model）
- 内置 provider，auth.json 配 apiKey 即可
- `getModel('deepseek', 'deepseek-v4-flash')` from `@earendil-works/pi-ai/compat`
- `ModelRuntime.create()` 进程级单例，4 小时刷新节流
- v4-flash：1M ctx / 384K max-out，thinking + tool calls
- thinkingFormat: "deepseek"（开 reasoning 时）

### GLM/Kimi 双评委
- 必须 custom provider 注册（models.json）
- GLM：走智谱 OpenAI-compatible 端点
- Kimi：必带 `deferredToolsMode: "kimi"`（工具调用顺序关键）
- 三家 thinkingFormat 不一致是评分对齐隐患

### 成本记录
- AssistantMessage 逐条落 provider/model/usage/cost
- Usage: {input, output, cacheRead, cacheWrite, totalTokens, cost:{...}}

---

## 六、Compaction（压缩）

### 配置
```json
// .pi/settings.json
{ "compaction": { "enabled": true, "reserveTokens": 16384, "keepRecentTokens": 30000 } }
```

### 机制
- 触发：contextTokens > contextWindow - reserveTokens
- 切点从末尾往前累积 token 到 keepRecentTokens
- 切点只落在 user/assistant/bash/custom，绝不切 tool result
- overflow 模式成功后自动重试被中断的 turn
- 摘要结构化模板（Goal/Constraints/Progress/Key Decisions/Next Steps）

### hook
- `session_before_compact`：可 cancel 或自定义 summary
- `session_compact_failed`：langfuse 上报

---

## 七、RPC 模式（Prism 选定：方案 B）

### 能力
- `pi --mode rpc`：JSONL over stdin/stdout，一进程一长连接
- 完整命令：prompt/steer/follow_up/abort/new_session/set_model/compact/get_state/get_messages/get_session_stats/get_entries/fork/clone/switch_session/export_html
- 事件流：agent_start/end/settled + turn_* + message_update + tool_execution_* + compaction_* + auto_retry_*
- `agent_settled` = 真正跑完信号
- `get_session_stats` 直接给 contextUsage.tokens/percent + cost
- 扩展 UI 子协议：permission-system 弹 select/confirm，client 回填

### Prism 用法（方案 B）
- 每用户一个 `pi --mode rpc` 子进程
- Node 网关持有 RpcClient，SLB 后每 ECS 跑 N 个 pi 子进程
- 进程级崩溃隔离（一个用户挂了不影响别人）
- 匹配 10-20 pi 实例部署设想

### 关键坑
- **readline 不能读 RPC 输出**（U+2028/U+2029 拆行破坏 JSON）→ 手写 indexOf("\n") 切分
- RPC 单客户端，不支持多客户端复用一个进程 → 一用户一进程
- 流式期间 prompt 必须带 streamingBehavior
- agent_end ≠ 跑完，监听 agent_settled

---

## 八、Containerization（部署）

### 四种模式
| 模式 | 隔离 | 凭证 | 适合 |
|---|---|---|---|
| Gondolin micro-VM | 仅工具进 VM | 留宿主 | 本地单机（Windows 不支持） |
| Plain Docker | 整个 pi 进程 | env 注入 | 简单隔离 |
| OpenShell | pi + 策控沙箱 | 留宿主 | 远程受管沙箱 |
| Docker Sandboxes | 整个 pi | sentinel 占位符 | 本地隔离+凭证不落容器 |

### Prism 部署建议
- Plain Docker per-pi-instance + SLB（50-100 并发，10-20 容器）
- 凭证走环境变量
- session-dir 指独立路径（每容器/每用户独立 volume）
- 生产可选 Docker Sandboxes（更安全但更重）

---

## 九、Session JSONL 格式

### 文件位置
`~/.pi/agent/sessions/--<path>--/<timestamp>_<uuid>.jsonl`

### 结构
- 第 1 行 SessionHeader：{type, version:3, id, timestamp, cwd, parentSession?}
- 后续每行一个 entry：{type, id(8位hex), parentId|null, timestamp}
- 树结构靠 id/parentId 串联

### Entry 类型
| type | 进 LLM 上下文? | Prism 用途 |
|---|---|---|
| message | 是 | 对话 |
| compaction | 是（summary + retainedTail） | 压缩检查点 |
| branch_summary | 是 | 分支摘要 |
| custom | 否 | 评估元数据（样本id/评委/评分） |
| custom_message | 是 | 注入 rubric/system prompt |
| label | 否 | 书签 |
| session_info | 否 | 显示名 |

### Redis 恢复路径（未来）
- `SessionManager.inMemory(cwd, {id}, entries)` + 逐条 append
- 或 Redis → 临时 JSONL → `SessionManager.open()`
- 缺 bulk load API

---

## 十、Extension 加载机制

### 加载位置
| 位置 | 范围 |
|---|---|
| `~/.pi/agent/extensions/*.ts` | 全局 |
| `.pi/extensions/*.ts` | 项目级（信任后加载） |
| settings.json packages 字段 | npm/git 分发 |
| `pi -e ./path.ts` | 临时测试 |

- jiti 加载 TypeScript 无需编译
- factory 可 async，pi await 后才继续启动
- **noExtensions**：DefaultResourceLoader 选项（extensions.md 未描述，sdk.md 提及但未详述）
- 多 extension 串行（按加载顺序），handler 链式

### 与已装插件共存
- cc-safety-net：tool_call handler（与 Prism 的 tool_call 串行）
- langfuse：只读观测事件（不冲突）
- pi-permission-system：UI confirm/select（RPC 下走 extension_ui 协议）
- 用 `prism-` 前缀避免撞名

---

## 十一、Prism 必须自建的（pi 没有）

- **业务工具**：query_reviews/sales/config（defineTool 定义，execute 调 FastAPI）
- **对象身份映射**：resolve_series（车系名 → series_key + series_id + 覆盖率）
- **口径视图**：mv_sales_monthly/reviews_dim/config_spec（Prism 侧消费者口径资产）
- **FastAPI 网关**：HTTP 接口层 + 舆情反代（pi 不做 HTTP server）
- **前端**：React 看板 + 对话
- **评估集 + 统计栈**：业务特定
- **grounding 逻辑**：数值容差 + 名称匹配（接 tool_result hook，但校验逻辑自建）
- **完成验证器逻辑**：CLAIM/VERIFY（接 agent_settled，但验证逻辑自建）

---

## 十二、之前用错的 API（phase2-integration）

| 错误 | 正确 | 影响 |
|---|---|---|
| SessionManager.inMemory() | SessionManager.create(cwd, sessionDir) | 不持久化 |
| SessionManager.open(session_id) | SessionManager.open(sessionFile) | open 失败→上下文丢 |
| sessionPool 复用 | 每请求新建（RPC 模式每用户一进程） | 竞态+泄漏+OOM |
| noExtensions 禁所有 | 精准禁 permission-system | langfuse 被禁 |
| 护栏在 TS 层独立 | pi.on('tool_call') hook | 没用执行层 |
| 完成验证独立 | agent_settled 事件 | 时机不对 |
| 没配压缩 | keepRecentTokens:30000 | 上下文爆炸 |

---

## 文档来源

| 文档 | 行数 | 路径 |
|---|---|---|
| sdk.md | 1224 | pi-windows-x64/docs/sdk.md |
| extensions.md | 3023 | pi-windows-x64/docs/extensions.md |
| sessions.md | 145 | pi-windows-x64/docs/sessions.md |
| session-format.md | 438 | pi-windows-x64/docs/session-format.md |
| security.md | 59 | pi-windows-x64/docs/security.md |
| compaction.md | 418 | pi-windows-x64/docs/compaction.md |
| containerization.md | 156 | pi-windows-x64/docs/containerization.md |
| rpc.md | 1618 | pi-windows-x64/docs/rpc.md |
| models.md | 574 | pi-windows-x64/docs/models.md |
