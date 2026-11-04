/** 前端 chat 客户端：fetch stream 读 NDJSON */
import { getAuthUser } from './auth';

export interface ChatEvent {
  type: 'session_info' | 'text_delta' | 'thinking_delta' | 'tool_call' | 'tool_result' | 'status_update' | 'message_end' | 'settled' | 'done' | 'error' | 'ui_request' | 'aborted' | 'auto_retry';
  data: any;
}

export function getUserId(): string {
  // 登录门禁 T4：身份以登录态用户名为准（后端 resolve_user_id 同样以 token 覆盖自报值，
  // 此处对齐保证前端展示与后端归因一致）；legacy 兜底仅在未登录窗口期（理论上无请求发出）
  const u = getAuthUser();
  if (u?.username) return u.username;
  let id = localStorage.getItem('prism_user_id');
  if (!id) {
    id = 'usr_' + Math.random().toString(36).slice(2, 10);
    localStorage.setItem('prism_user_id', id);
  }
  return id;
}

// 中止键与单一在途轮次（2026-10-12）：单活跃流控制器 + 用户主权中止 + 断线即中止
let activeController: AbortController | null = null;

/** 本地断流兜底（abort 端点不可达/后端异常时防卡死） */
export function cancelActiveStream(): void {
  try { activeController?.abort(); } catch { /* 已断 */ }
}

/** 请求后端中止在途轮（幂等：无在途返回 aborted:false） */
export async function abortChat(): Promise<boolean> {
  const userId = getUserId();
  try {
    const res = await fetch('/chat/abort', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId }),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export async function sendChat(
  message: string,
  onEvent: (e: ChatEvent) => void,
  opts?: { scope?: string; sessionId?: string }
): Promise<void> {
  const userId = getUserId();
  const scope = opts?.scope ?? 'agent';
  const controller = new AbortController();
  activeController = controller;
  let sawSettled = false;
  let sawAborted = false;
  let sawStreamError = false;   // 流内 error 事件（如"上一个请求仍在进行中"被拒）——非断线，不补 abort
  // S8 P0-2：断线即中止判据收紧——仅当流异常终止且未收到任何终止事件（settled/aborted/
  // 流内 error）才补 abort。原 !sawSettled 单判据会：(a) 把被拒轮的 finally 变成对同 user
  // 在途合法轮的误杀（双标签页共享 user_id）；(b) 用户主动中止后再冗余 abort，可能命中刚
  // 拿到锁的新轮。网络异常走 catch 路径发 error 事件但不置 sawStreamError（标志只在流内
  // 行解析处置位）→ 仍会补 abort（这是断线即中止的本意场景）。
  try {
    const res = await fetch('/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message, scope, user_id: userId,
        session_id: opts?.sessionId ?? null,
      }),
      signal: controller.signal,
    });

    if (!res.ok || !res.body) {
      onEvent({ type: 'error', data: { message: `HTTP ${res.status}` } });
      return;
    }

    const reader = res.body.getReader();
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
        try {
          const evt = JSON.parse(line) as ChatEvent;
          onEvent(evt);
          if (evt.type === 'settled') sawSettled = true;
          else if (evt.type === 'aborted') sawAborted = true;
          else if (evt.type === 'error') sawStreamError = true;
          // B3：ui_request 需要前端回填（自动批准，生产期改弹框）
          if (evt.type === 'ui_request') {
            const { id, method, options } = evt.data;
            const value = method === 'select' ? (options?.[0]) : method === 'confirm' ? true : '';
            respondUi(id, value);
          }
        } catch {
          // 忽略解析失败的行
        }
      }
    }
  } catch (e) {
    // 本地断流（用户中止兜底）发合成 aborted 事件，不产错误气泡（G8）
    if ((e as Error).name === 'AbortError') {
      onEvent({ type: 'aborted', data: {} });
    } else {
      onEvent({ type: 'error', data: { message: (e as Error).message } });
    }
  } finally {
    if (activeController === controller) activeController = null;
    // 断线即中止（脱钩根治，G9；S8 P0-2 收紧判据）：无任何终止事件的异常结束才补 abort
    if (!sawSettled && !sawAborted && !sawStreamError) abortChat().catch(() => {});
  }
}

// B3：前端回填 UI 响应（供 ChatView 弹框后调用）
export async function respondUi(id: string, value: any, cancelled = false): Promise<void> {
  const userId = getUserId();
  await fetch('/ui-response', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, value, cancelled, user_id: userId }),
  });
}
