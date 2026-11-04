/**
 * C2（2026-10-14 评估迭代基建包）· mapEvent 单测
 * 此前 mapEvent 内联在 pi_gateway.mjs（import 即 listen）不可单测——
 * auto_retry 事件落 default 丢弃。抽到 prism-api/map_event.mjs 后补测。
 * 运行：node --test tests/map_event.test.mjs（已挂 smoke:verify）
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { mapEvent } from '../prism-api/map_event.mjs';

describe('mapEvent · C2 auto_retry（provider 流错误自动重试可见）', () => {
  it('auto_retry_start → 一等 auto_retry 事件（phase=start）', () => {
    const r = mapEvent({ type: 'auto_retry_start' });
    assert.deepEqual(r, { type: 'auto_retry', data: { phase: 'start', ts: r.data.ts } });
    assert.equal(r.data.phase, 'start');
    assert.ok(r.data.ts > 0);
  });

  it('auto_retry_end → 一等 auto_retry 事件（phase=end）', () => {
    const r = mapEvent({ type: 'auto_retry_end' });
    assert.equal(r.type, 'auto_retry');
    assert.equal(r.data.phase, 'end');
  });

  it('auto_retry 事件可 JSON 序列化（NDJSON 下发前端前提）', () => {
    const r = mapEvent({ type: 'auto_retry_start' });
    const j = JSON.parse(JSON.stringify(r));
    assert.equal(j.type, 'auto_retry');
    assert.equal(j.data.phase, 'start');
  });
});

describe('mapEvent · 抽出回归锚（防搬运走样）', () => {
  it('tool_execution_start/end → tool_call/tool_result', () => {
    assert.deepEqual(
      mapEvent({ type: 'tool_execution_start', toolName: 'query_sales', input: { a: 1 } }),
      { type: 'tool_call', data: { name: 'query_sales', args: { a: 1 } } }
    );
    assert.equal(
      mapEvent({ type: 'tool_execution_end', toolName: 'query_sales', result: 'ok', isError: false }).type,
      'tool_result'
    );
  });

  it('message_update text_delta 透传、message_start 显式丢弃', () => {
    assert.deepEqual(
      mapEvent({ type: 'message_update', assistantMessageEvent: { type: 'text_delta', delta: '你好' } }),
      { type: 'text_delta', data: { text: '你好' } }
    );
    assert.equal(mapEvent({ type: 'message_start' }), null);
  });

  it('未知类型 → null（default 分支）', () => {
    assert.equal(mapEvent({ type: 'totally_unknown' }), null);
  });
});
