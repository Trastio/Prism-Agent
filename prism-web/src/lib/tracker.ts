/**
 * T-7.1/T-7.2 前端埋点 SDK
 * 事件：page_view / chat_start / active_tick(30s) / feedback / chat_settled
 * 上报：sendBeacon（关页不丢）+ fetch 兜底
 * 脱敏：VIN/车牌（T-7.5，后端也做一道）
 */

import { getUserId } from './chat';

const ENDPOINT = '/events';
const HEARTBEAT_MS = 30000;
const IDLE_TIMEOUT_MS = 5 * 60 * 1000;  // 待拍板项4：无交互>5min 不计

const queue: any[] = [];
let lastActive = Date.now();
let currentSessionId: string | null = null;
let currentSeriesKey: string | null = null;
let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
// D10：兜底 flush 周期（普通事件攒 5 条才发，最坏要等心跳凑满 ~2.5min；60s 定时兜底压到 1 分钟内）
const FLUSH_INTERVAL_MS = 60000;
let flushTimer: ReturnType<typeof setInterval> | null = null;

// 块0.5：改用共享脱敏模块（消除双实现）
import { sanitize } from '../../../src/shared/redaction';

function flush() {
  if (queue.length === 0) return;
  const batch = { events: queue.splice(0) };
  const blob = new Blob([JSON.stringify(batch)], { type: 'application/json' });
  // sendBeacon 优先（关页不丢）
  if (navigator.sendBeacon) {
    navigator.sendBeacon(ENDPOINT, blob);
  } else {
    fetch(ENDPOINT, { method: 'POST', body: JSON.stringify(batch), headers: { 'Content-Type': 'application/json' }, keepalive: true }).catch(() => {});
  }
}

export function track(eventType: string, data: Record<string, any> = {}) {
  // P1-1 修复：...data 在前，脱敏 value/series_key 在后覆盖（防明文入库）
  const evt: Record<string, any> = {
    ...data,
    event_type: eventType,
    local_id: getUserId(),
    session_id: currentSessionId,
    page: window.location.pathname,
    series_key: currentSeriesKey ? sanitize(currentSeriesKey) : undefined,
    value: data.value ? sanitize(String(data.value)) : undefined,
    ts: new Date().toISOString(),
  };
  // 清 undefined
  for (const k of Object.keys(evt)) if (evt[k] === undefined) delete evt[k];
  queue.push(evt);
  // 攒够 5 条或立即 flush（feedback/settled 立即发）
  if (queue.length >= 5 || eventType === 'feedback' || eventType === 'chat_settled') {
    flush();
  }
  lastActive = Date.now();
}

export function setSessionContext(sessionId: string | null, seriesKey: string | null = null) {
  currentSessionId = sessionId;
  currentSeriesKey = seriesKey;
}

/** T-7.1 启动心跳 + 页面可见性监听；返回清理函数（清两个 interval） */
export function initTracker(): () => void {
  // 首次 page_view
  track('page_view');

  // 心跳（仅页面可见 + 未空闲 >5min）
  heartbeatTimer = setInterval(() => {
    if (document.hidden) return;
    if (Date.now() - lastActive > IDLE_TIMEOUT_MS) return;  // 空闲超时不计
    track('active_tick');
  }, HEARTBEAT_MS);

  // D10 兜底 flush：队列不满 5 条也每 60s 强制发一次（覆盖"心跳被空闲判定暂停"的积压场景）
  flushTimer = setInterval(flush, FLUSH_INTERVAL_MS);

  // 可见性变化：隐藏时 flush + 记录，可见时 page_view
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      flush();
    } else {
      track('page_view');
      lastActive = Date.now();
    }
  });

  // 关页 flush
  window.addEventListener('beforeunload', flush);
  window.addEventListener('pagehide', flush);

  // 用户交互重置 lastActive
  ['click', 'keydown', 'touchstart'].forEach(ev =>
    document.addEventListener(ev, () => { lastActive = Date.now(); }, { passive: true })
  );

  return () => {
    if (heartbeatTimer) clearInterval(heartbeatTimer);
    if (flushTimer) clearInterval(flushTimer);
  };
}
