/**
 * RPC 原始事件 → 前端友好格式映射（原 pi_gateway.mjs 内联函数抽出，
 * 2026-10-14 评估迭代基建包 C2：pi_gateway 在 import 时即 listen，内联函数
 * 不可单测——抽为纯模块，网关与 tests/map_event.test.mjs 共用）
 * 块5 B1：事件契约补全——pi RPC 事件全集对齐，显式标注透传/丢弃+原因
 */
import { resolve } from 'node:path';
import { readFileSync, existsSync } from 'node:fs';

export function mapEvent(event, userId = '', realSessionId = '') {
  const t = event.type;
  switch (t) {
    case 'message_update': {
      const ame = event.assistantMessageEvent || {};
      const sub = ame.type;
      if (sub === 'text_delta' && ame.delta) {
        return { type: 'text_delta', data: { text: ame.delta } };
      }
      if (sub === 'thinking_delta' && ame.delta) {
        return { type: 'thinking_delta', data: { text: ame.delta } };
      }
      return null;  // text_start/end, toolcall_start/end 等子类型不单独输出（message_update 聚合）
    }
    case 'tool_execution_start':
      // D4（2026-11-03）：pi 事件字段名是 args（pi docs/json.md L49），此前读 event.input
      // 恒为 undefined —— 前端工具活动无参数，且车系联动 extractSeriesKey 永远取不到 series_key。
      // 保留 event.input 兜底（兼容旧事件形态），主路径改用 args。
      return { type: 'tool_call', data: { name: event.toolName, args: event.input ?? event.args } };
    case 'tool_execution_end':
      return { type: 'tool_result', data: { name: event.toolName, result: event.result, is_error: event.isError } };
    case 'agent_start':
      return { type: 'status_update', data: { phase: 'agent_start' } };
    case 'agent_settled': {
      let verdictData = null;
      try {
        // M3 T-S3：优先 realSessionId（extension 写 .pi/sessions/<pi sessionId>/verdict.json，
        // agent_settled 事件本身无 sessionId 字段——json.md:45；原 fallback 全局 last-verdict.json
        // 会跨会话串读，雷 1）
        const sid = realSessionId || event.sessionId || userId || 'default';
        const sessionDir = resolve(process.cwd(), `.pi/sessions/${sid}`);
        const verdictPath = resolve(sessionDir, 'verdict.json');
        const lastPath = resolve(process.cwd(), '.pi/sessions/last-verdict.json');
        const p = existsSync(verdictPath) ? verdictPath : (existsSync(lastPath) ? lastPath : null);
        if (p) verdictData = JSON.parse(readFileSync(p, 'utf-8'));
      } catch {}
      return { type: 'settled', data: {}, verdict: verdictData };
    }
    case 'extension_error':
      return { type: 'error', data: { message: event.error || 'extension error' } };
    case 'aborted':
      // 中止键与单一在途轮次（2026-10-12）：一等事件非 error——中止是用户主权操作
      return { type: 'aborted', data: {} };
    case 'ui_request':
      return event;
    // 块5 B1 补全：turn_start/end → 前端"生成中/完成"状态 + 耗时
    case 'turn_start':
      return { type: 'status_update', data: { phase: 'turn_start', ts: Date.now() } };
    case 'turn_end':
      return { type: 'status_update', data: { phase: 'turn_end', ts: Date.now() } };
    // 块5 B1 补全：session_info（兑现 L102 注释意图）
    case 'session_info':
      return { type: 'session_info', data: event.data || {} };
    // C2（2026-10-14 评估迭代基建包）：pi provider 流错误自动重试（官方事件
    // auto_retry_start/end，pi-Agent-能力地图"重试"节）——此前落 default 刷
    // "未知事件类型"日志并丢弃，用户只见停顿不知在重试。映射为一等 auto_retry
    // 事件，前端渲染"自动重试中"标签（重试轮可见）
    case 'auto_retry_start':
      return { type: 'auto_retry', data: { phase: 'start', ts: Date.now() } };
    case 'auto_retry_end':
      return { type: 'auto_retry', data: { phase: 'end', ts: Date.now() } };
    // 显式丢弃（前端不需要，但标注原因防"被丢且无记录"）
    case 'agent_end': return null;      // pi 可能继续 retry/compact，agent_settled 才是真完成
    case 'message_start': return null;  // message_update 已覆盖文本流
    case 'message_end': return null;    // 同上
    case 'tool_execution_update': return null;  // 中途进度，前端不需要
    case 'session_start': return null;  // 内部生命周期，前端用 session_info
    case 'session_shutdown': return null;
    case 'session_before_compact': return null;
    // P2-1 补全：extension appendEntry 发的事件（pi docs json.md 明确存在，此前落 default 刷日志）
    case 'entry_appended': return null;
    // P2-1 补全：其余已知生命周期/状态事件，显式丢弃（防"未知事件类型"刷屏）
    case 'session_info_changed': return null;
    case 'queue_update': return null;
    case 'thinking_level_changed': return null;
    // provider 流错误（json.md:89：fields reason/error）——显式转告，不再静默丢弃；
    // event.data?.message 兜底 exit/abort 路径推入的伪事件（{type:'error',data:{message}}）
    case 'error': {
      // S8 P2-2：reason/error 可能是 Error 实例——JSON.stringify 后变 {}（truthy 兜底不触发）
      const raw = event.reason || event.error || event.data?.message;
      const msg = raw instanceof Error ? raw.message : (typeof raw === 'string' && raw ? raw : 'provider stream error');
      return { type: 'error', data: { message: msg } };
    }
    default:
      console.error(`[pi_gateway] 未知事件类型: ${t}（丢弃，请补 mapEvent）`);
      return null;
  }
}
