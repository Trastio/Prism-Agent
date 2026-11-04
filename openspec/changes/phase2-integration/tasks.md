# Tasks · 前后端对齐与 pi 集成

> Step 2 propose · 任务拆分
> 日期：2026-10-04

---

## 依赖链

```
T1 pi_server.mjs → T2 FastAPI 转发 → T3 前端接入 → T4 舆情反代 → T5 清理
```

---

## T1 · pi_server.mjs（Node 常驻 HTTP）

| ID | 任务 | 状态 |
|---|---|---|
| T1.1 | HTTP 服务骨架（:9100）+ 路由 | ✅ |
| T1.2 | 会话管理（SessionManager + 每用户 sessionDir） | ✅ |
| T1.3 | /chat 流式（createAgentSession + prompt + subscribe → NDJSON） | ✅ |
| T1.4 | 工具注册（query_reviews/sales/config + scope 锁定） | ✅ |
| T1.5 | DeepSeek model 显式配置 + AGENTS.md 注入 | ✅ |
| T1.6 | 冒烟：node pi_server.mjs + curl /chat 验证事件流 | ✅ Python 测通过：session_info+text_delta+tool_call+tool_result 全出，E5 真实数据回流 |

**验收**：✅ curl /chat 收到 NDJSON 事件流，日志显示 model=deepseek-v4-flash。

---

## T2 · FastAPI 转发层

| ID | 任务 | 状态 |
|---|---|---|
| T2.1 | /chat/stream NDJSON 透传到 pi_server :9100 | ✅ |
| T2.2 | /session GET/POST 转发 | ✅（返回真实会话列表） |
| T2.3 | /sentiment-board/{path} 反代舆情 Board | ✅（200 text/html） |
| T2.4 | 装 httpx 依赖 | ✅ |

**验收**：✅ 全通。

---

## T3 · 前端接入

| ID | 任务 | 状态 |
|---|---|---|
| T3.1 | composer fetch stream 接 /chat/stream（ChatView） | ✅（lib/chat.ts + ChatView 流式渲染） |
| T3.2 | 流式文本渲染 + 工具活动面板 | ✅ |
| T3.3 | 状态栏联动 | ✅（status_update + 工具调用状态） |
| T3.4 | sidebar 会话列表接 /session + 浏览器本地 ID | ✅（useQuery 10s 刷新） |
| T3.5 | 舆情 iframe 改 /sentiment-board/ | ✅ |
| T3.6 | KanbanView composer → 切 ChatView 预填 | ✅ |

**验收**：✅ 浏览器内 fetch /chat/stream 收到 NDJSON 流（session_info+text_delta），链路通。

---

## T5 · 清理

| ID | 任务 | 状态 |
|---|---|---|
| T5.1 | 删 board-bar "示例数据" chip | ✅ |
| T5.2 | ConfigBoard table 横向滚动 | ✅ |
| T5.3 | 验证 DeepSeek（pi_server 日志） | ✅ |

---

## 3.5 自查收敛（Step 4）

propose 写完后自查：
- T1-T5 依赖完整无悬空
- pi_server 接口与 FastAPI 转发一一对应
- 前端 7 个 SSE 事件类型全有处理
- 不造轮子准则：session/agent-loop/事件流全用 pi，业务工具/验证器/反代是项目必需

---

## Step 6 simplify（已完成）

| 改动 | 说明 |
|---|---|
| mapEvent 去重 | message_update 只输出 text_delta，tool_call 统一走 tool_execution_start/end（之前重复） |
| message_end 过滤空 usage | 无 usage 不输出 |
| 工具参数统一 series_key | 去掉 spec_id/year 混乱，config/sales 都用 series_key + FastAPI 反查 series_id |
| FastAPI config 接受 series_key | 与 reviews 统一，反查 series_id（int 转换） |
| session 池 | pi_server 维护 Map<sessionId, session>，复用 session 实例 + 共享 resourceLoader |

---

## Step 7 code-review（进行中）

| 发现 | 处理 |
|---|---|
| session 上下文不持久（同 session_id 第二次对话 agent 说不记得） | 🟡 待查 pi SDK session 行为；可能是 inMemory + open 不恢复 transcript |
| tool_call 事件来自 tool_execution_start/end 两个事件 | 正常（start=调用开始，end=返回），非重复 |
| DeepSeek 偶尔不调工具（短 prompt 直接回答） | 提示词优化，非阻塞 |

---

## 关键路径

```
T1.1→T1.5→T1.6 → T2.1→T2.2 → T3.1→T3.4 → T5
                                ↘ T2.3→T3.5
```

**瓶颈**：T1 pi_server 是基础，全链路都依赖它。
