# Design · 前后端对齐与 pi 集成

> Step 2 propose · 技术方案
> 日期：2026-10-04

---

## 0. 架构

```
浏览器 (React)
  │
  ├─ EventSource /chat/stream     → FastAPI → Node pi_server (常驻) → pi SDK
  ├─ REST /session                → FastAPI → Node pi_server → SessionManager
  ├─ REST /dashboard/{type}       → FastAPI → prism_views.db
  └─ iframe /sentiment-board/*    → FastAPI 反代 → 127.0.0.1:8000
        │
        ▼
  Node pi_server.mjs (常驻 HTTP :9100)
  ├─ POST /chat    → createAgentSession + prompt + 事件流 NDJSON
  ├─ GET  /session → SessionManager.list
  ├─ POST /session → SessionManager.create
  └─ GET  /session/recent → SessionManager.continueRecent
        │
        ▼
  pi-agent SDK
  ├─ model: getModel('deepseek','deepseek-v4-flash')
  ├─ customTools: query_reviews/sales/config
  ├─ sessionManager: SessionManager.create(cwd, sessionDir+userId)
  ├─ resourceLoader: DefaultResourceLoader({noExtensions, systemPrompt:AGENTS.md})
  └─ session.subscribe → 事件流
```

---

## 1. pi_server.mjs（Node 常驻 HTTP）

### 1.1 接口
| 方法 | 路径 | 作用 |
|---|---|---|
| POST | /chat | 流式对话，body={message, scope, user_id, session_id?}，响应 NDJSON 流 |
| GET | /session?user_id= | 列会话 |
| POST | /session | 建会话，body={user_id, title} |
| GET | /session/recent?user_id= | 续最近会话 |

### 1.2 会话管理
```js
// 每用户独立 sessionDir（思路 2）
function sessionDirFor(userId) {
  const base = resolve(PROJECT_ROOT, '.pi/sessions');
  return `${base}/${userId}`;
}
// SessionManager.create(cwd, sessionDirFor(userId))
```

### 1.3 工具注册
- 注册 query_reviews/sales/config（customTools）
- scope 锁定：`session.setActiveToolsByName(resolveScopeTools(scope))`
- 工具 execute 调 FastAPI /dashboard/* 取数（回环调 Python，避免 Node 重实现 SQL）

### 1.4 事件流（NDJSON，前端用 fetch stream 读）
```
session.subscribe(event => {
  const out = mapEvent(event);  // pi 事件 → {type, data}
  res.write(JSON.stringify(out) + '\n');  // NDJSON，每行一个 JSON
});
await session.prompt(message, {streamingBehavior:'followUp'});
```
注：不用 SSE `data:` 前缀格式（因为前端用 POST + fetch ReadableStream 读，不是 EventSource GET）。FastAPI 透传 NDJSON 原样。

### 1.5 model
```js
import { getModel } from '@earendil-works/pi-ai/compat';
const model = getModel('deepseek', 'deepseek-v4-flash');
createAgentSession({ model, ... });
```

---

## 2. FastAPI 转发层

### 2.1 /chat/stream（SSE 透传）
```python
@app.post('/chat/stream')
async def chat_stream(req: dict):
    async def stream():
        async with httpx.AsyncClient() as client:
            async with client.stream('POST', 'http://127.0.0.1:9100/chat', json=req) as r:
                async for line in r.aiter_lines():
                    yield f'{line}\n'  # 透传 NDJSON，前端 EventSource 解析
    return StreamingResponse(stream(), media_type='text/event-stream')
```

### 2.2 /session（转发 pi_server）
```python
@app.get('/session')
async def list_sessions(user_id: str):
    async with httpx.AsyncClient() as c:
        r = await c.get('http://127.0.0.1:9100/session', params={'user_id': user_id})
        return r.json()
```

### 2.3 /sentiment-board/{path}（反代舆情 Board）
```python
@app.get('/sentiment-board/{path:path}')
async def sentiment_proxy(path: str):
    async with httpx.AsyncClient() as c:
        r = await c.get(f'http://127.0.0.1:8000/{path}')
        return Response(r.content, status_code=r.status_code, 
                       headers={'Content-Type': r.headers.get('content-type','text/html')})
```

---

## 3. 前端接入

### 3.1 composer 发送（fetch stream 读 NDJSON）
```tsx
async function sendChat(message: string) {
  // 本轮固定 agent 模式（不锁白名单）；BI scope 锁定留下一轮
  const scope = { mode: 'agent' };
  const res = await fetch('/chat/stream', {
    method: 'POST',
    body: JSON.stringify({ message, scope, user_id: getUserId() }),
  });
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop() || '';
    for (const line of lines) {
      if (!line.trim()) continue;
      const evt = JSON.parse(line);
      // 按 evt.type 分发：
      // text_delta → append 流式文本
      // tool_call → 工具活动面板加行
      // tool_result → 工具活动面板更新
      // status_update → 状态栏更新
      // claim_check/settled → 验证器状态
    }
  }
}
```

### 3.2 sidebar /session
```tsx
const { data } = useQuery({
  queryKey: ['sessions', userId],
  queryFn: () => fetch('/session?user_id=' + userId).then(r => r.json()),
});
// 渲染 data.sessions
```

### 3.3 舆情 iframe
```tsx
<iframe src="/sentiment-board/" />  // 同源，无跨域
```

---

## 4. 清理

- 删 board-bar 的"示例数据"chip
- ConfigBoard table 包 `overflow-x: auto`
- pi_server 日志输出 model=deepseek-v4-flash 验证

---

## 5. 风险与缓解

1. **SSE 透传缓冲**：FastAPI + httpx 默认可能缓冲，要 `stream=True` + 逐行 yield
2. **pi_server 进程管理**：开发期 `npm run pi-server` 手动启；异常退出要重启
3. **每用户 sessionDir 隔离**：要确认 pi 接受非默认 sessionDir 路径（已查 SDK 支持）
4. **DeepSeek API 限流**：单账号 2500 并发，开发期无压力
5. **noExtensions 禁 langfuse**：开发期可接受，评估期改自定义 loader
