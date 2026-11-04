# Spec · 2.5b pi-agent 集成（前端↔FastAPI↔pi SDK 全链路）

> 阶段2 · 集成层
> 依赖：2.2 工具接口（TS 语义工具 + 护栏 + grounding）+ 2.3 验证层
> 关系：本 spec 覆盖 frontend.md 2.5.10-2.5.11，是前端 UI 与 pi-agent 的"磨合"层
> 核心：SSE 流式对话 + 工具活动推送 + 状态栏联动 + 会话管理 + scope 锁定

---

## 一、集成拓扑

```
浏览器 (React)
  │
  ├─ REST: GET /dashboard/{type}      → FastAPI 读 mv_* 返回看板数据
  ├─ SSE:  POST /chat/stream          → FastAPI → pi SDK createAgentSession → 流式响应
  ├─ WS:   /ws/status                 → FastAPI 推送状态栏（三维度完成度/token/as_of）
  └─ REST: POST /session / GET /session → 会话列表（Redis 持久化）
        │
        ▼
  FastAPI (prism-api/)
  ├─ routes/chat.py     (SSE 流式)
  ├─ routes/dashboard.py (看板数据)
  ├─ routes/session.py   (会话 CRUD)
  ├─ routes/auth.py      (浏览器本地 ID)
  ├─ pi_bridge.py        (pi SDK 封装)
  └─ ws.py               (WebSocket 状态推送)
        │
        ▼
  pi-agent SDK (createAgentSession)
  ├─ 注册 2.2.3 的 3 工具 + discover_tools
  ├─ 2.2.4 tool_call 护栏 (cc-safety-net + 自建红线)
  ├─ 2.2.5 tool_result grounding (数值+名称)
  ├─ 2.3.2 完成验证器 (agent_settled, CLAIM/VERIFY)
  ├─ 2.1.1 AGENTS.md/SYSTEM.md 提示词注入 (before_agent_start)
  ├─ 2.1.2 状态栏 hook → WebSocket 推前端
  └─ langfuse 埋点 (评估闭环)
        │
        ▼
  Atuohome SQLite (immutable=1 只读) + 舆情 Board REST + Redis (会话)
```

---

## 二、SSE 流式对话链路（核心）

### 2.1 前端 → 后端
```typescript
// 前端 EventSource
const es = new EventSource(`/chat/stream?session_id=${sid}&model=deepseek-v4-flash`);
es.onmessage = (e) => {
  const evt = JSON.parse(e.data);
  switch(evt.type) {
    case 'text_delta':      // 流式文本片段 → assistant-ui append
    case 'tool_call':       // 工具调用开始 → 工具活动面板
    case 'tool_result':     // 工具返回 → 工具活动面板 + 看板高亮
    case 'status_update':   // 状态栏更新 → 状态栏
    case 'claim_check':     // 完成验证器 → 显示 CLAIM/VERIFY 状态
    case 'settled':         // agent 完成 → 报告预览
    case 'error':           // fail-closed → 错误提示
  }
};
// 提交消息
fetch('/chat/stream', { method:'POST', body: JSON.stringify({session_id, message, scope}) })
```

### 2.2 后端 → pi SDK
```python
# pi_bridge.py
from pi import createAgentSession, SessionManager

async def stream_chat(session_id, message, scope, model="deepseek-v4-flash"):
    # 1. 恢复或创建会话（Redis-backed SessionManager）
    sm = SessionManager.inMemory()  # 或自定义 Redis-backed
    session = await sm.get_or_create(session_id, cwd=PROJECT_ROOT)

    # 2. scope 锁定：根据 scope.board 设置工具白名单
    tools = resolve_scope_tools(scope)  # BI 口碑看板 → [query_reviews] only
    session.setActiveTools(tools)

    # 3. 注入 SYSTEM.md（before_agent_start hook，含车系/覆盖率/as_of）
    # 4. 流式发送
    async for event in session.send(message):
        yield map_pi_event_to_sse(event)  # 转 SSE 格式
```

### 2.3 pi 事件 → SSE 映射
| pi 事件 | SSE event.type | 前端动作 |
|---|---|---|
| `message_update` (text delta) | `text_delta` | assistant-ui 流式 append |
| `tool_execution_start` (args/input) | `tool_call` | 工具活动面板加行 |
| `tool_execution_end` (result/output/is_error/usage) | `tool_result` | 工具活动面板更新 + 看板高亮 |
| `before_agent_start` | `status_update` | 状态栏（车系/覆盖率/as_of 注入完成） |
| `agent_settled` (验证器结果) | `claim_check` / `settled` | 显示 CLAIM/VERIFY，通过则报告预览 |
| `tool_call` block (护栏拦截) | `error` | fail-closed 错误提示 |

---

## 三、scope 锁定（BI 模式核心）

### 3.1 scope 协议
```typescript
type Scope = {
  mode: 'bi' | 'agent';
  board?: 'reviews' | 'sales' | 'config' | 'sentiment';
  filters: {
    series_key?: string;       // 银河E5
    series_id?: string;        // 7650
    year?: number;
    month?: string;
    tag_category?: string;
    // ...当前看板筛选条件
  };
};
```

### 3.2 工具白名单映射
| scope.board | 允许的工具 |
|---|---|
| reviews | query_reviews + query_config（限配置项查证） |
| sales | query_sales |
| config | query_config |
| sentiment | sentiment_overview/trend/dimension/posts/competitive/events（6 舆情工具） |
| agent 模式 | 全部（3 核心 + discover_tools + 6 舆情） |

### 3.3 实现
- 前端 composer 提交时附带 `scope`
- 后端 `pi_bridge` 调 `session.setActiveTools(resolve_scope_tools(scope))`
- 切换看板 tab → 前端更新 scope → 下次提问生效

---

## 四、会话管理（Redis 持久化）

### 4.1 设计（2026-09-30 拍板：Redis 共享 + 浏览器本地 ID）
```
浏览器 localStorage: usr_xxx (随机 ID, 无登录)
       ↓
POST /session { user_id: usr_xxx, title: "银河E5 分析" }
       ↓
Redis: session:{sid} = { user_id, title, created_at, scope, messages_summary }
       ↓
pi SessionManager.inMemory() 从 Redis 条目恢复
```

### 4.2 多实例支持
- 50-100 并发 → pi 实例 10-20 + SLB（2026-09-30 拍板）
- 用户第二次请求可能落到不同实例 → 会话状态必须 Redis 共享
- SessionManager 自定义 Redis-backed 实现（pi 文档支持 inMemory，Redis 需自实现 wrapper）

### 4.3 接口
| 接口 | 作用 |
|---|---|
| `POST /session` | 创建会话（user_id + title） |
| `GET /session?user_id=usr_xxx` | 列出用户会话 |
| `GET /session/{sid}` | 获取会话详情（含 scope） |
| `DELETE /session/{sid}` | 删除会话 |

---

## 五、状态栏 WebSocket（2.1.2 联动）

### 5.1 推送字段
```typescript
type StatusUpdate = {
  data_sources: { atuohome: 'ready'|'down', sentiment: 'ready'|'down' };
  model: string;                    // deepseek-v4-flash
  token_usage: { input, output, cache_hit, cost };  // @narumitw/pi-usage
  dimensions_done: { config: bool, reviews: bool, sales: bool };  // 三维度完成度
  as_of: string;                    // 当前数据时点
  tool_call_count: number;          // 同维度 ≥3 告警
};
```

### 5.2 推送时机
- `before_agent_start`：注入完成，推初始状态
- `tool_execution_start/end`：更新 dimensions_done + tool_call_count
- `message_update`：更新 token_usage
- 每 5 秒心跳推 data_sources 健康状态

---

## 六、看板数据接口（REST，非 SSE）

### 6.1 接口
| 接口 | 数据源 |
|---|---|
| `GET /dashboard/reviews?series_key=银河E5` | mv_reviews_dim |
| `GET /dashboard/sales?series_key=银河E5&year=2026` | mv_sales_monthly |
| `GET /dashboard/config?series_id=7650` | mv_config_spec |
| `GET /dashboard/sentiment?vehicle_id=...` | 舆情 Board REST 代理 |

### 6.2 返回格式
```json
{
  "rows": [...],
  "_meta": {
    "as_of": "2026-10-03",
    "source": "mv_reviews_dim",
    "coverage": { "review_count": 1274, "tag_count": 3235, "coverage_rate": 0.925 },
    "口径": "sentiment=pro/con, tag_category 聚合"
  }
}
```
_meta 必带（报告纪律：口径逐维声明 as_of）。

---

## 七、agent_settled 验证器联动

### 7.1 前端显示
agent 完成时：
- 验证器通过 → `settled` 事件 → 报告预览面板显示 md/excel/word
- 验证器失败（1 次）→ `claim_check` 事件（status=fail, reason）→ 前端显示"补证据中"→ continuation
- 验证器失败（2 次）→ `error` 事件 → 前端显示"验证未通过：[reason]"

### 7.2 supported_by 渲染
agent 回复里的 `<external_content source="review_tags:7650/舒适/con">` 标签 → 前端渲染为可点击溯源 chip → 点击跳转到对应看板高亮该数据。

---

## 八、langfuse 评估闭环

### 8.1 埋点（已核实，pi-observability-plugin@0.1.2）
- `tool_execution_start/end`：自建工具全覆盖
- `session_start/before_agent_start/before_provider_request/message_update/message_end/session_compact/agent_settled/session_shutdown`

### 8.2 写回 trace（评估批跑时）
- 验证器分数 / 失败维度 / 成本4维度 / trap 是否被否决 / 名称拦截是否触发
- trace 打 `eval_run_id` 标签

### 8.3 开发期 vs 评估期
- 开发期：langfuse cloud 免费额度
- 评估批跑：`pi -p --mode json`，**不禁 extensions**（决策⑥），langfuse 保持开启
- 上线期：self-host 或继续 cloud

---

## 九、待办清单（与 frontend.md 2.5.10-2.5.11 对齐 + 新增集成项）

| ID | 待办 | 优先级 | 依赖 |
|---|---|---|---|
| 2.5b.1 | FastAPI 骨架 + Redis 会话 store | P0 | — |
| 2.5b.2 | pi_bridge.py：createAgentSession 封装 + 工具注册 + hook 注入 | P0 | 2.2.3, 2.2.4, 2.3.2 |
| 2.5b.3 | SSE /chat/stream 流式（pi 事件 → SSE 映射） | P0 | 2.5b.2 |
| 2.5b.4 | scope 锁定（setActiveTools 白名单切换） | P0 | 2.5b.2 |
| 2.5b.5 | WebSocket /ws/status 状态推送 | P1 | 2.5b.2 |
| 2.5b.6 | /dashboard/{type} 看板数据 REST | P0 | 2.2.2 |
| 2.5b.7 | /session 会话 CRUD + 浏览器本地 ID | P1 | 2.5b.1 |
| 2.5b.8 | supported_by 溯源 chip 渲染 | P2 | 2.5b.3 |
| 2.5b.9 | agent_settled 验证器结果前端显示 | P1 | 2.5b.3 |
| 2.5b.10 | langfuse 埋点 + trace 写回 | P1 | 2.5b.2 |
| 2.5b.11 | Redis-backed SessionManager wrapper（多实例共享） | P1 | 2.5b.1 |

---

## 十、验收

1. `POST /chat/stream` 流式返回文本 + 工具活动 + 状态栏更新
2. 在口碑看板提问 → agent 只调 query_reviews（scope 锁定生效）
3. 切换实例（模拟 SLB）→ 会话从 Redis 恢复，上下文不丢
4. agent_settled 验证器结果前端可见（通过/失败/continuation）
5. supported_by chip 可点击溯源到看板
6. langfuse trace 含工具 args/result/usage/耗时 + 评估字段写回

---

## 十一、风险与边界

1. **Redis-backed SessionManager 需自实现**：pi 文档只支持 inMemory，Redis wrapper 要自己写（序列化会话状态 + 恢复）。开发期可先用 inMemory 单实例，上线前补 Redis。
2. **SSE 长连接 + 50-100 并发**：FastAPI + uvicorn 异步可支撑，但需调 worker 数 + 连接超时。SLB 需支持 SSE（不缓冲）。
3. **scope 锁定可被 prompt injection 绕过？**：scope 只控制工具白名单（执行层），不靠 prompt 劝说。模型想调别的工具 → setActiveTools 不在白名单 → 调用失败 fail-closed。
4. **舆情 Board 嵌套 iframe 跨域**：开发期同源代理（FastAPI 反代 8000），避免 iframe 跨域。
