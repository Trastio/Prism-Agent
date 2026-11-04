# Design · 中止键与单一在途轮次

## 事件流（改后）

```
用户点[方块] → handleAbort
  ├─ POST /chat/abort {user_id}          (chat.ts abortChat)
  │    └─ main.py /chat/abort → gateway /abort
  │         └─ rpc.abort() ① eventQueue 推 {type:'aborted'} 唤醒 /chat 读循环
  │                      ② send('abort') → RPC 命令到 pi 本体（停 turn）
  │    └─ /chat 循环：mapEvent({aborted}) → 写 {type:'aborted'} → break → res.end
  │         └─ finally：清 inflightLocks + drain eventQueue
  └─ 2.5s 兜底：仍 streaming → activeController.abort() 本地断流
前端收 {type:'aborted'} → 状态"已中止生成" → finally setStreaming(false) → 按钮恢复箭头
```

## 层1 · 前端

**Icons.tsx**：sprite 加 `<symbol id="ico-stop" viewBox="0 0 24 24"><rect x="6.5" y="6.5" width="11" height="11" rx="1.5"/></symbol>`

**chat.ts**：
```ts
let activeController: AbortController | null = null;
let sawSettled = false;  // sendChat 内局部
// sendChat 变更：
//   activeController = new AbortController(); fetch(..., { signal: activeController.signal })
//   onEvent(evt): if (evt.type === 'settled') sawSettled = true;
//   正常 return / catch(AbortError 静默) / finally：
//     activeController === 本轮 controller 时置 null
//     if (!sawSettled) abortChat().catch(() => {})   // 断线即中止（兜底对齐）
//     用户主动中止路径设 userAborted 标记跳过（其实调 abortChat 幂等，重复无害，不特判）
export async function abortChat(): Promise<boolean> {
  return fetch('/chat/abort', { method:'POST', headers, body: JSON.stringify({ user_id: getUserId() }) })
    .then(r => r.ok).catch(() => false);
}
```
注：用户点中止也走 abortChat()——流会先收到 aborted 事件再 done，属正常结束；断线即中止的自动补调幂等不冲突。

**ChatView.tsx**：
- composer 按钮：`type="button"`，`onClick={() => (streaming ? handleAbort() : handleSend())}`（form onSubmit 保留 streaming 早退）；icon = streaming ? 'stop' : 'arrow-up'；不 disabled（点击即中止）。
- `handleAbort()`：`setStatus('正在中止…'); abortChat().then(ok => { if (!ok) setStatus('中止请求失败，请重试'); }); setTimeout(() => { if (streaming) { activeController 断流（经 chat.ts 暴露 cancelActiveStream()） } }, 2500)` —— streaming 是闭包快照，改用 ref（streamingRef）判断。
- 新 case 'aborted'：`setStatus('已中止生成'); track('chat_aborted', {})`。
- initialMessage 挂起：`useEffect(() => { if (initialMessage && !streaming) { const t = setTimeout(() => handleSend(initialMessage), 100); return () => clearTimeout(t); } }, [initialMessage, streaming])` —— 原实现只在 initialMessage 变化时触发一次，streaming 中会丢消息。

## 层2 · main.py

```python
@app.post('/chat/abort')
async def chat_abort(req: dict):
    user_id = validate_user_id(req.get('user_id', 'default'))
    async with httpx_client(15.0) as c:
        r = await c.post(f'{PI_SERVER}/abort', json={'user_id': user_id})
        return r.json()
```

## 层3 · pi_gateway.mjs

```js
if (url.pathname === '/abort' && req.method === 'POST') {
  const userId = validateUserId(body.user_id);
  if (!userId) { 400 }
  const rpc = pool.get(userId);
  const inflight = inflightLocks.has(userId);
  if (!rpc || !inflight) { res.end(JSON.stringify({ ok: true, aborted: false })); return; }  // D2 幂等
  try { await rpc.abort(); res.end(JSON.stringify({ ok: true, aborted: true })); }
  catch (e) { res.writeHead(500); res.end(JSON.stringify({ ok: false, error: e.message })); }
  return;
}
```
- mapEvent：`case 'aborted': return { type: 'aborted', data: {} };`（一等事件；前端/runner 各自忽略或处理）
- /chat finally 追加：`if (rpc) rpc.eventQueue.length = 0;`（D5；rpc 变量在 try 内声明——提升到 try 外或复用 getOrCreateRpc(userId)）
- 兜底 D6（条件实施）：E2E 发现回灌继续时，abort 路由内在 abort() 后 `setTimeout(() => writeSafe(abort 命令), 1000)` 复发

## 层4 · extension / pi

零改动（abort 原生；agent_settled 不触发→无 verdict→符合中止语义）。

## 测试（tests/abort_api.test.ts，活服务 skip 模式）

1. /health ok
2. 无在途 /chat/abort → `{ok:true,aborted:false}`（幂等）
3. 真流中止：POST /chat/stream（问题："银河E5的口碑怎么样？详细一点"，必多轮工具）后台读流；4s 后 POST /chat/abort → 断言 ≤10s 内流结束且含 `type:'aborted'` 事件
4. 锁已清+会话可续用：中止后 ≤2s 发"你好" → 收到非"上一个请求仍在进行中"的回复（text_delta 存在）
5. 再 abort 一次（流已结束）→ 幂等 ok

## 里程碑

M1 = gateway /abort + mapEvent + drain（后端通，可 curl 验收 E2E-3/4）
M2 = main.py 透传 + 前端三件（UI 双态 + aborted 分支 + 断线即中止）
M3 = 测试挂 smoke + 全量验收（含 UI 手测清单）
