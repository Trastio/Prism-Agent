# Tasks · 集成重写（用 pi 官方能力）

> Step 2 propose · 任务拆分
> 方案 B：RPC 模式 + Extension hook

---

## 依赖链

```
T1 P0 user_id 校验（独立先修）
  ↓
T2 RPC 子进程管理（rpc_client.mjs + 进程池）
  ↓
T3 prism-guardrails extension（5 个 hook）
  ↓
T4 FastAPI /chat/stream + /session 改用 RPC
  ↓
T5 前端 try/catch + finally + 状态栏
  ↓
T6 .pi/settings.json + AGENTS.md + 清理旧文件
```

---

## T1 · P0 user_id 校验

| ID | 任务 | 状态 |
|---|---|---|
| T1.1 | validate_user_id 白名单 `/^[A-Za-z0-9_-]+$/` | ✅ |
| T1.2 | pi_gateway 所有接口接 user_id 的都校验 | ✅ |

**验收**：✅ `user_id=../../foo` → 400；合法 → 200

---

## T2 · RPC 子进程管理

| ID | 任务 | 状态 |
|---|---|---|
| T2.1 | `pi_gateway.mjs`：spawn `pi --mode rpc --approve` + 手写 JSONL reader（indexOf 切分） | ✅ |
| T2.2 | RpcClient 类：send(type,params) / nextEvent / abort / dispose | ✅ |
| T2.3 | 进程池 Map<userId, RpcClient> + 超时清理（30min → dispose） | ✅ |
| T2.4 | DeepSeek model 显式（--model deepseek-v4-flash） | ✅ |
| T2.5 | extension_ui_request 自动回填（开发期自动批准 select/confirm/input） | ✅ |
| T2.6 | 冒烟：RPC 事件流通（agent_start/turn_start/message_update(thinking_delta+toolcall)/agent_settled） | ✅ DeepSeek thinking+tool_call+AGENTS.md 注入全通 |

**验收**：✅ RPC 链路通。待修：业务工具未注册（agent 用 search 找 query_reviews）→ T3 extension 注册

---

## T3 · prism-guardrails extension

| ID | 任务 | 状态 |
|---|---|---|
| T3.1 | `.pi/extensions/prism-guardrails/index.ts` 骨架 | ✅ |
| T3.2 | before_agent_start → 注入 AGENTS.md + 红线 | ✅（thinking 引用 AGENTS.md 验证） |
| T3.3 | tool_call → block 裸 SQL / 写操作（红线#2） | ✅ |
| T3.4 | tool_result → grounding 改写（红线#1，开发期简化版） | ✅ |
| T3.5 | agent_settled → 完成验证器（sendUserMessage retry + 防递归） | ✅ |
| T3.6 | session_before_compact → 观测 | ✅ |
| T3.7 | 业务工具注册（query_reviews/sales/config via pi.registerTool） | ✅ agent 调 query_reviews 成功 + 真实数据回流 |
| T3.8 | 加载方式：-e 显式加载（settings.json extensions 字段不生效，待查） | 🟡 |

**验收**：✅ query_reviews 注册成功 + agent 调用 + 真实数据（E5 9 维度）。AGENTS.md 注入生效（thinking 引用红线）。

---

## T4 · FastAPI 改用 RPC

| ID | 任务 | 状态 |
|---|---|---|
| T4.1 | /chat/stream 转发 pi_gateway:9100（NDJSON 透传） | ✅ |
| T4.2 | /session 转发 pi_gateway | ✅ |
| T4.3 | user_id 校验（P0） | ✅ |
| T4.4 | FastAPI 转发 try/except + error 事件 | ✅ |
| T4.5 | /sentiment-board 反代保留 | ✅ |
| T4.6 | CORS 限本机 | ✅ |

**验收**：✅ 端到端 FastAPI→pi_gateway→RPC→DeepSeek→query_reviews→真实数据全通

---

## T5 · 前端

| ID | 任务 | 状态 |
|---|---|---|
| T5.1 | chat.ts sendChat try/catch | ✅ |
| T5.2 | ChatView handleSend finally setStreaming(false) | ✅ |

---

## T6 · 配置 + 清理

| ID | 任务 | 状态 |
|---|---|---|
| T6.1 | .pi/settings.json 配 keepRecentTokens:30000 + extensions 字段 | ✅ |
| T6.2 | AGENTS.md 保留（before_agent_start 注入） | ✅ |
| T6.3 | 删 pi_server.mjs + pi_bridge.mjs + session_bridge.mjs | ✅ |
| T6.4 | package.json 重建（gateway/dev:all scripts） | ✅ |

---

## 3.5 自查（Step 4）

- T2 RPC readline 坑（手写 indexOf）
- T3 agent_settled 递归防护（appendEntry 标记）
- T3 tool_call 与 cc-safety-net 共存（链式串行）
- T4 FastAPI↔Node 桥方式（Python subprocess 调 rpc_client.mjs？还是 Node 常驻？）
- T2 进程池超时清理 + 崩溃恢复
- P0-P2 全覆盖

---

## 关键路径

```
T1 → T2 → T3 → T4 → T5 → T6
```

**瓶颈**：T2 RPC 子进程管理（核心架构）+ T3 extension（红线核心）
