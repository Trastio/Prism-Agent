/**
 * /chat/abort 中止链路集成测试（中止键与单一在途轮次，2026-10-12）
 * 框架：node:test；服务不可达自动 skip（identity_api 同模式）。
 *
 * 三组：
 * - unit（常跑，无服务依赖）：Block B（判分器修复与七题处置）中止残留注记纯函数——
 *   /abort 后下一轮 prompt 附注记（multi-12 残留根治），历史回显剥离
 * - fast（常跑，进 smoke:all）：健康 + 幂等×2 + 非法 user_id
 * - e2e（PRISM_E2E_ABORT=1 才跑，DeepSeek 真轮 30-60s）：真流中止 + 锁清后续用
 *   —— 2026-10-12 已人工实测通过（abort_race2：abort 0.5s 返回、100ms 后新问完整获答），
 *      此处留可重复执行的门控入口；Block B 追加：中止后下一轮注记注入生效
 *      （原始会话文件含注记 + /session/messages 回显剥离）双断言。
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { loginOnce, authHeaders } from './auth_smoke.ts';
import { ABORT_NOTE, ABORT_NOTE_MARK, withAbortNote, stripAbortNoteFromMessages } from '../prism-api/abort_note.mjs';

const API = process.env.PRISM_FASTAPI || 'http://127.0.0.1:8002';
const GW = process.env.PRISM_GATEWAY || 'http://127.0.0.1:9200';
const E2E = process.env.PRISM_E2E_ABORT === '1';

async function serviceUp(base: string): Promise<boolean> {
  try {
    const res = await fetch(`${base}/health`, { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}

async function postJson(url: string, body: unknown, timeoutMs = 10000): Promise<{ status: number; json: any }> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
  let json: any = null;
  try { json = await res.json(); } catch { /* 非 JSON */ }
  return { status: res.status, json };
}

/** 读整条 NDJSON 流（测流事件用，非渲染场景无需增量） */
async function drainStream(body: unknown, timeoutMs: number): Promise<string[]> {
  const res = await fetch(`${API}/chat/stream`, {
    method: 'POST',
    // Step8 P1-4：登录门下无 cookie 的 /chat/stream 全 401（曾漏带——流式 helper 与 postJson 双标）
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
  const text = await res.text();
  const types: string[] = [];
  for (const line of text.split('\n')) {
    if (!line.trim()) continue;
    try { types.push(JSON.parse(line).type); } catch { /* ignore */ }
  }
  return types;
}

/** drainStream + 捕获 session_info 会话 id（Block B e2e：注记断言需定位会话文件） */
async function drainStreamFull(body: unknown, timeoutMs: number): Promise<{ types: string[]; sid: string | null }> {
  const res = await fetch(`${API}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() }, // Step8 P1-4：同 drainStream
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(timeoutMs),
  });
  const text = await res.text();
  const types: string[] = [];
  let sid: string | null = null;
  for (const line of text.split('\n')) {
    if (!line.trim()) continue;
    try {
      const e = JSON.parse(line);
      types.push(e.type);
      if (e.type === 'session_info' && e.data?.session_id) sid = e.data.session_id;
    } catch { /* ignore */ }
  }
  return { types, sid };
}

describe('abort_note · 中止残留注记纯函数（Block B，无服务依赖）', () => {
  it('withAbortNote：同会话标记才追加注记；异会话/无标记原样返回', () => {
    const base = '比亚迪海豚8月卖了多少？';
    const out = withAbortNote(base, 'sess-1', 'sess-1');
    assert.ok(out.startsWith(base), '用户消息应保留在前');
    assert.ok(out.includes(ABORT_NOTE_MARK), '同会话应附中止注记');
    assert.ok(out.length > base.length);
    assert.equal(withAbortNote(base, 'sess-1', 'sess-2'), base, '跨会话不注记（中止残留只影响原会话）');
    assert.equal(withAbortNote(base, null, 'sess-1'), base, '无标记不注记');
  });

  it('注记文案不含 multi-12 残留词面（trap_params.residue 同源正则，防误伤判分）', () => {
    assert.doesNotMatch(ABORT_NOTE, /4,?436|6,?790|3,?427|银河E5|零跑\s*B10|MG\s*4X/);
    assert.doesNotMatch(ABORT_NOTE_MARK, /4,?436|6,?790|3,?427|银河E5|零跑\s*B10|MG\s*4X/);
  });

  it('stripAbortNoteFromMessages：字符串与 blocks 两种 content 形态都剥离；其他角色/干净消息不动', () => {
    const raw = withAbortNote('问题A', 's', 's');
    const stripped = stripAbortNoteFromMessages([
      { role: 'user', content: raw },
      { role: 'user', content: [{ type: 'text', text: raw }] },
      { role: 'user', content: '普通消息' },
      { role: 'assistant', content: [{ type: 'text', text: raw }] },
    ]);
    assert.equal(stripped[0].content, '问题A', '字符串 content 尾部注记应剥离');
    assert.equal(stripped[1].content[0].text, '问题A', 'blocks content 末块注记应剥离');
    assert.equal(stripped[2].content, '普通消息', '干净消息不动');
    assert.equal(stripped[3].content[0].text, raw, 'assistant 回复不剥（只处理 user 消息）');
  });

  it('round-trip：附注记→剥离=原文；非数组入参原样返回', () => {
    const m = '任意消息';
    const round = stripAbortNoteFromMessages([{ role: 'user', content: withAbortNote(m, 's', 's') }]);
    assert.equal(round[0].content, m);
    const arr = [{ role: 'user', content: 'x' }];
    assert.deepEqual(stripAbortNoteFromMessages(arr), arr, '干净数组内容不变');
    assert.equal(stripAbortNoteFromMessages(undefined), undefined, '非数组原样返回');
    assert.equal(stripAbortNoteFromMessages(null), null);
  });
});

describe('/chat/abort · fast（健康+幂等）', async () => {
  const up = (await serviceUp(API)) && (await serviceUp(GW));
  if (up) await loginOnce(API); // 登录门禁适配：不带 token 全 401
  it(up ? '服务在线，跑 fast case' : 'api/gateway 不可达 → skip', { skip: !up }, async () => {
    // 1. api 透传幂等（无在途）
    const r1 = await postJson(`${API}/chat/abort`, { user_id: 'aborttest_fast' });
    assert.equal(r1.status, 200);
    assert.deepEqual(r1.json, { ok: true, aborted: false });
    // 2. gateway 直连幂等
    const r2 = await postJson(`${GW}/abort`, { user_id: 'aborttest_fast' });
    assert.equal(r2.status, 200);
    assert.deepEqual(r2.json, { ok: true, aborted: false });
    // 3. 非法 user_id → 400
    const r3 = await postJson(`${GW}/abort`, { user_id: '../evil' });
    assert.equal(r3.status, 400);
  });
});

describe('/chat/abort · e2e 真流中止（PRISM_E2E_ABORT=1）', async () => {
  const up = await serviceUp(API);
  if (up) await loginOnce(API);
  it(up && E2E ? '真流中止 + 锁清后续用' : '未设 PRISM_E2E_ABORT=1 → skip', { skip: !up || !E2E }, async () => {
    const uid = `abort_t_${Date.now()}`;
    // 后台开一条长问题流
    const streamDone = drainStream(
      { user_id: uid, message: '银河E5的口碑怎么样？请详细分析各维度' }, 180000);
    await new Promise(r => setTimeout(r, 6000));
    const t0 = Date.now();
    const ab = await postJson(`${API}/chat/abort`, { user_id: uid }, 15000);
    assert.equal(ab.json.aborted, true);
    const events = await streamDone;
    assert.ok(events.includes('aborted'), `流应含 aborted 事件，尾部: ${events.slice(-5)}`);
    assert.ok(Date.now() - t0 < 15000, '中止应在 15s 内结束流');
    // 锁清 + 会话可续用：中止后立发新问，应有正文且不被"进行中"拒绝
    const ev2 = await drainStreamFull({ user_id: uid, message: '你好' }, 120000);
    assert.ok(ev2.types.includes('text_delta'), `中止后新问应有正文，实际: ${ev2.types.slice(0, 6)}`);
    assert.ok(ev2.types[ev2.types.length - 1] === 'settled', `新问应正常收尾，尾部: ${ev2.types.slice(-3)}`);

    // Block B：中止注记生效断言（同会话下一轮）——
    // a) 注入侧：pi 原始会话文件含注记（/chat prompt 确实携带=multi-12 残留根治路径通）
    // b) 剥离侧：网关 /session/messages 历史回显不含注记（前端零泄漏，D4 契约同向）
    assert.ok(ev2.sid, '应捕获到 session_info 的会话 id');
    // Step8 P1-4：登录门 resolve_user_id 把 body user_id 覆盖成 cookie 用户名（smoke_test）
    // ——pi 会话文件与网关会话池都按覆盖后身份键控，用 body uid 定位必 ENOENT/404
    const OWNER = 'smoke_test';
    const rawFile = resolve(import.meta.dirname, '..', '.pi', 'sessions', OWNER, `${ev2.sid}.jsonl`);
    const raw = readFileSync(rawFile, 'utf8');
    assert.ok(raw.includes(ABORT_NOTE_MARK), 'pi 会话文件应含中止注记（prompt 已携带）');
    const histRes = await fetch(`${GW}/session/messages?user_id=${OWNER}&session_id=${encodeURIComponent(ev2.sid)}`, {
      headers: authHeaders(), signal: AbortSignal.timeout(15000),
    });
    assert.equal(histRes.status, 200, '历史回显端点应可达');
    const hist = await histRes.json() as { messages?: any[] };
    const userTexts = (hist.messages || [])
      .filter((m: any) => m?.role === 'user')
      .map((m: any) => typeof m.content === 'string' ? m.content
        : Array.isArray(m.content) ? m.content.map((b: any) => b?.text ?? '').join('') : '');
    assert.ok(!userTexts.some((t: string) => t.includes(ABORT_NOTE_MARK)), `历史回显不应含中止注记，实际: ${JSON.stringify(userTexts)}`);
    assert.ok(userTexts.some((t: string) => t.trim() === '你好'), '历史回显应保留原始用户消息');
  });
});
