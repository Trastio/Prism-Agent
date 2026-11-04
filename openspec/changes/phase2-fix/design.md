# Design · 集成重写（用 pi 官方能力）

> Step 2 propose · 技术方案
> 方案 B：RPC 模式 + Extension hook

---

## 0. 架构

```
浏览器 (React)
  │ fetch stream
  ▼
FastAPI (prism-api/main.py, :8002)
  │ subprocess + stdin/stdout JSONL
  ▼
pi --mode rpc 子进程（每用户一个）
  ├─ SessionManager.create/open（文件持久化，.pi/sessions/<userId>/）
  ├─ customTools: query_reviews/sales/config（defineTool）
  ├─ extension: prism-guardrails（.pi/extensions/）
  │   ├─ before_agent_start → 注入 SYSTEM.md + 车系上下文
  │   ├─ tool_call → block 裸 SQL / 写操作（红线#2）
  │   ├─ tool_result → grounding 改写（红线#1）
  │   ├─ agent_settled → 完成验证器（sendUserMessage retry）
  │   └─ session_before_compact → 自定义压缩
  ├─ model: deepseek-v4-flash
  ├─ keepRecentTokens: 30000
  └─ 事件流 JSONL → FastAPI 透传 → 前端
```

---

## 1. RPC 子进程管理（rpc_client.mjs）

### 1.1 启动
```js
const { spawn } = require('child_process');
function startPiRpc(userId, sessionId) {
  const args = ['--mode', 'rpc', '--model', 'deepseek-v4-flash'];
  if (sessionId) args.push('--session', sessionId);
  const proc = spawn('pi', args, {
    cwd: PROJECT_ROOT,
    stdio: ['pipe', 'pipe', 'pipe'],
    env: { ...process.env, PI_SESSION_DIR: `.pi/sessions/${userId}/` },
  });
  // 手写 JSONL reader（不能用 readline，U+2028/U+2029 拆行）
  return new RpcClient(proc);
}
```

### 1.2 RpcClient
```js
class RpcClient {
  constructor(proc) {
    this.proc = proc;
    this.buffer = '';
    this.pending = new Map();  // requestId → {resolve, reject}
    this.listeners = [];       // 事件监听
    this.proc.stdout.on('data', (chunk) => this._onData(chunk));
    this.proc.stderr.on('data', (d) => console.error('[pi]', d.toString()));
    this.proc.on('exit', (code) => this._onExit(code));
  }
  _onData(chunk) {
    this.buffer += chunk.toString('utf-8');
    let idx;
    while ((idx = this.buffer.indexOf('\n')) >= 0) {
      const line = this.buffer.slice(0, idx);
      this.buffer = this.buffer.slice(idx + 1);
      if (line.trim()) this._handleLine(JSON.parse(line));
    }
  }
  _handleLine(msg) {
    if (msg.type === 'response') {
      const p = this.pending.get(msg.id);
      if (p) { this.pending.delete(msg.id); p.resolve(msg); }
    } else {
      // 事件：agent_start/settled/message_update/tool_*/...
      this.listeners.forEach(fn => fn(msg));
    }
  }
  async send(command, args = {}) {
    const id = crypto.randomUUID();
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.proc.stdin.write(JSON.stringify({ id, command, ...args }) + '\n');
    });
  }
  onEvent(fn) { this.listeners.push(fn); }
  async abort() { return this.send('abort'); }
  async dispose() { this.proc.kill(); }
}
```

### 1.3 子进程池
```js
// 每用户一 RPC 子进程（进程级隔离）
const procPool = new Map();  // userId → RpcClient
function getRpc(userId) {
  if (!procPool.has(userId)) {
    procPool.set(userId, startPiRpc(userId));
  }
  return procPool.get(userId);
}
// 超时清理：lastActive > 30min → dispose + delete
```

---

## 2. FastAPI /chat/stream 改用 RPC

```python
@app.post('/chat/stream')
async def chat_stream(req: dict):
    user_id = validate_user_id(req.get('user_id', 'default'))
    message = req.get('message', '')
    if not message or not isinstance(message, str):
        raise HTTPException(400, 'message required')

    async def stream():
        try:
            # 获取/启动 RPC 子进程
            rpc = await get_rpc(user_id)
            # 发 prompt 命令
            await rpc.send('prompt', {'text': message})
            # 读事件流直到 agent_settled
            async for event in rpc.events():
                yield json.dumps(event) + '\n'
                if event.get('type') == 'agent_settled':
                    break
        except Exception as e:
            yield json.dumps({'type': 'error', 'data': {'message': str(e)}}) + '\n'

    return StreamingResponse(stream(), media_type='application/x-ndjson')
```

### 客户端中断
```python
@app.post('/chat/stream')
async def chat_stream(req: Request):
    ...
    async def stream():
        try:
            rpc = await get_rpc(user_id)
            # 监听客户端断开
            disconnect_task = asyncio.create_task(wait_disconnect(req))
            event_task = asyncio.create_task(rpc.events().__anext__())
            while True:
                done, pending = await asyncio.wait(
                    [disconnect_task, event_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                if disconnect_task in done:
                    await rpc.abort()  # 中断 pi
                    break
                if event_task in done:
                    event = event_task.result()
                    yield json.dumps(event) + '\n'
                    if event.get('type') in ('agent_settled', 'error'):
                        break
                    event_task = asyncio.create_task(rpc.events().__anext__())
        except Exception as e:
            yield json.dumps({'type': 'error', 'data': {'message': str(e)}}) + '\n'
```

---

## 3. prism-guardrails extension（.pi/extensions/prism-guardrails/index.ts）

```typescript
export default function pi(ctx) {
  // before_agent_start：注入 SYSTEM.md + 红线
  ctx.on('before_agent_start', async (event) => {
    return {
      systemPrompt: event.systemPrompt + readFileSync('AGENTS.md', 'utf-8'),
      message: { customType: 'prism-redline', content: '红线已启用', display: false }
    };
  });

  // tool_call：拦截裸 SQL / 写操作（红线#2）
  ctx.on('tool_call', async (event) => {
    if (looksLikeRawSql(event.input)) {
      return { block: true, reason: '红线#2: 禁止裸 SQL', terminate: true };
    }
  });

  // tool_result：grounding 改写（红线#1）
  ctx.on('tool_result', async (event) => {
    if (event.toolName.startsWith('query_')) {
      const result = verifyGrounding(event.content, event.details);
      if (!result.pass) {
        return { content: [{ type: 'text', text: result.reason }], isError: true };
      }
    }
  });

  // agent_settled：完成验证器
  ctx.on('agent_settled', async (_event, ctx) => {
    const verified = ctx.sessionManager.getEntry(ctx.sessionManager.getLeafId());
    // 检查是否已验证（防递归）
    const entries = ctx.sessionManager.getEntries();
    const lastCustom = [...entries].reverse().find(e => e.customType === 'prism-verified');
    if (lastCustom) return;  // 已验证过，不重入

    const verdict = await runCompletionVerifier(verified);
    if (!verdict.pass) {
      ctx.appendEntry('prism-verified', { pass: false, reasons: verdict.reasons });
      ctx.sendUserMessage(`[验证器] 验收未通过：${verdict.reasons.join('; ')}。请修正。`);
    } else {
      ctx.appendEntry('prism-verified', { pass: true });
    }
  });

  // session_before_compact：保留数据真实性关键事实
  ctx.on('session_before_compact', async (event) => {
    // 用默认压缩 + 追加 Prism 关键事实
    return;  // 不 cancel，让 pi 默认压缩，仅观测
  });
}
```

---

## 4. .pi/settings.json

```json
{
  "compaction": {
    "enabled": true,
    "reserveTokens": 16384,
    "keepRecentTokens": 30000
  },
  "packages": [
    "npm:pi-web-access",
    "npm:cc-safety-net@2.4.15",
    "npm:@langfuse/pi-observability-plugin@0.1.2",
    "npm:@narumitw/pi-usage"
  ]
}
```
注：开发期不装 pi-permission-system（避免 RPC 模式 UI 确认问题）；langfuse 保留（评估期用）。

---

## 5. 前端改动

### chat.ts try/catch + finally
```ts
async function sendChat(message, onEvent, opts) {
  try {
    const res = await fetch('/chat/stream', { method: 'POST', body: ... });
    // stream read
  } catch (e) {
    onEvent({ type: 'error', data: { message: e.message } });
  }
}
// ChatView.handleSend:
try { await sendChat(...); } finally { setStreaming(false); }
```

---

## 6. P0 user_id 校验

```python
import re
def validate_user_id(uid):
    if not re.match(r'^[A-Za-z0-9_-]+$', uid):
        raise HTTPException(400, 'invalid user_id')
    return uid
```

---

## 7. 风险

1. **RPC readline 坑**：手写 indexOf("\n") 切分，不用 readline
2. **RPC 子进程崩溃**：RpcClient 检测 exit → 清理 + 通知前端 error
3. **extension 加载**：.pi/extensions/ 项目级，需 project_trust；或用 -e 临时加载
4. **agent_settled 递归**：appendEntry 存"已验证"标记，重入检查
5. **tool_call 与 cc-safety-net 共存**：链式串行，用 prism- 前缀
6. **RPC 单客户端**：每用户一进程，进程池管理
