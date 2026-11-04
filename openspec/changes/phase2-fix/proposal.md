# Proposal · 集成重写（用 pi 官方能力）

> Step 2 propose · 2026-10-04
> 范围：用 pi-agent 官方 RPC 模式 + Extension hook 替代手写 pi_server.mjs，修 code-review 18 问题
> 上游：explore.md（pi 全模块能力地图）+ phase2-integration code-review（18 findings）

---

## 一、为什么做（WHY）

phase2-integration 用 pi_server.mjs 手写了 HTTP 服务 + sessionPool + 事件映射 + 独立护栏/grounding/验证器。经 6 个子 agent 深读 pi 全文档，确认**这些全是 pi 自带能力**：

- pi 有 RPC 模式（`pi --mode rpc`，JSONL over stdin/stdout）
- pi 有 SessionManager 全套（create/open/list/continueRecent，文件持久化）
- pi 有 Extension hook（tool_call block / tool_result modify / agent_settled / before_agent_start / session_before_compact）
- pi 有 AgentSession API（subscribe→unsubscribe / abort / dispose）

**准则"pi 满足不造轮子"** → pi_server.mjs + sessionPool + 独立 guardrail/grounding/completion 都是造轮子，必须用 pi 官方能力替代。

同时修 code-review 发现的 18 个问题（1 P0 + 7 P1 + 10 P2）。

---

## 二、做什么（WHAT）

### 删的（造轮子）
| 模块 | 替代 |
|---|---|
| `pi_server.mjs` 手写 HTTP + sessionPool + mapEvent | `pi --mode rpc` 子进程 + Node RpcClient |
| `src/tools/guardrail.ts` 独立护栏 | `pi.on('tool_call')` extension |
| `src/verify/grounding.ts` 独立调用 | `pi.on('tool_result')` extension |
| `src/verify/completion.ts` 独立验证 | `pi.on('agent_settled')` extension |

### 新增的（pi extension）
`.pi/extensions/prism-guardrails/index.ts`：
- `before_agent_start` → 注入 SYSTEM.md + 车系上下文 + 红线
- `tool_call` → block 裸 SQL / 写操作（红线#2）
- `tool_result` → grounding 改写（红线#1，名称+数值）
- `agent_settled` → 完成验证器（sendUserMessage retry，max 1 次，防递归）
- `session_before_compact` → 自定义压缩（保留数据真实性关键事实）

### 改的（修 bug + 用对 API）
| 项 | 旧 | 新 |
|---|---|---|
| 集成方式 | pi_server.mjs 手写 HTTP | `pi --mode rpc` 子进程 + Node RpcClient |
| session 持久化 | inMemory() | SessionManager.create(cwd, sessionDir) 文件模式 |
| session 恢复 | open(session_id) 错 | open(sessionFile) 对 |
| session 复用 | sessionPool Map | 每用户一 RPC 子进程（进程级隔离） |
| user_id 路径穿越 (P0) | 直接拼路径 | 白名单 `/^[A-Za-z0-9_-]+$/` |
| 订阅泄漏 (P1#4) | 不取消 | RPC 子进程用完即弃 + readline 手写切分 |
| 客户端中断 (P1#5) | 不感知 | RpcClient abort + req.on('close') |
| message 挂死 (P1#7) | try 外 | 校验 + try |
| 前端卡死 (P1#8) | 无 try/catch | try/catch + finally |
| 压缩 | 没配 | keepRecentTokens:30000 |
| SYSTEM.md 注入 | 没接 | before_agent_start hook |
| CORS 全开 (P2#16) | `*` | 限本机 |

### 保留的（业务必需，pi 没有）
- `src/tools/query_sales/reviews/config.ts`（defineTool 定义，execute 调 FastAPI）
- `src/identity/resolve.ts`（对象身份映射）
- `src/registry/datasource.ts` + `src/views/refresh.py`（数据源 + 口径视图）
- `prism-api/main.py`（FastAPI 网关 + 舆情反代）
- `prism-web/`（前端）
- `eval/`（评估集 + 统计栈）
- grounding/completion 的**校验逻辑**（接 hook，但数值容差/名称匹配/CLAIM 验证逻辑自建）

---

## 三、关键决策（已拍板）

| # | 决策 | 依据 |
|---|---|---|
| 1 | RPC 模式 B（每用户一 pi 子进程） | 用户拍板；进程级崩溃隔离；匹配 10-20 实例部署 |
| 2 | 用 pi extension hook 替代独立 TS 层 | pi 满足不造轮子；hook 在执行层（红线#5） |
| 3 | SessionManager 文件持久化 | pi 自带，不用 Redis |
| 4 | agent_settled 用 sendUserMessage 实现 retry | pi 无原生 retry 返回（ext-reader 发现） |
| 5 | 保留 grounding/completion 校验逻辑 | pi hook 是接入点，校验算法是业务逻辑 |

---

## 四、影响范围

**新建**：
- `.pi/extensions/prism-guardrails/index.ts`（pi extension，5 个 hook）
- `prism-api/rpc_client.mjs`（Node RpcClient，封装 RPC 协议）
- `.pi/settings.json` 配 keepRecentTokens:30000

**重写**：
- `prism-api/main.py`（/chat/stream 改用 RPC 子进程 + RpcClient；/session 改用 SessionManager.list）
- `prism-web/src/lib/chat.ts`（try/catch + finally）
- `prism-web/src/components/ChatView.tsx`（finally + 状态栏联动）

**删的**：
- `prism-api/pi_server.mjs`（被 RPC 替代）
- `prism-api/pi_bridge.mjs`（被 RPC 替代）
- `prism-api/session_bridge.mjs`（被 RPC 替代）

**不动**：
- `src/tools/query_*.ts`（业务工具，注册方式从 customTools 改为 pi.registerTool 或仍用 customTools）
- `src/identity/resolve.ts` / `src/registry/datasource.ts` / `src/views/refresh.py`
- `src/verify/grounding.ts` / `completion.ts`（校验逻辑保留，调用方式改为从 extension 调）
- `prism-web/src/components/dashboards/*`（看板组件）
- `eval/*`

---

## 五、验收

1. **P0 安全**：`user_id=../../foo` → 400
2. **session 上下文持久**：同 session 连续两轮对话，第二轮记得第一轮
3. **进程隔离**：一个用户 RPC 子进程崩溃，其他用户不受影响
4. **护栏在执行层**：tool_call hook 拦截裸 SQL；tool_result hook 改写编造数据
5. **完成验证器**：agent_settled 触发 CLAIM/VERIFY，失败用 sendUserMessage 重来一轮
6. **压缩**：keepRecentTokens:30000 生效
7. **客户端中断**：关连接后 RPC 子进程 abort
8. **前端不卡死**：fetch 失败 UI 恢复
9. **DeepSeek**：RPC 子进程 model=deepseek-v4-flash
10. **18 个 code-review 问题全修**

---

## 六、不做（边界）

- 不做 Redis（pi 文件持久化够）
- 不做 Docker 部署（留上线期）
- 不做 GLM/Kimi 双评委（留评估期）
- 不做 langfuse 接入（评估期改自定义 loader 保留 langfuse）
- 不做 supported_by 溯源 chip（留下一轮）
- 不做 scope 锁定前端切换（先固定 agent 模式）
