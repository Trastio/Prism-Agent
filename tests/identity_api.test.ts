/**
 * /identity/resolve 端点集成测试（红线#7 对象身份前置核验）
 * 框架：node:test（Node 内置，无依赖）
 * 运行：node --test --import tsx tests/identity_api.test.ts
 *
 * 注意：需要 prism-api 服务在 http://127.0.0.1:8002 运行。
 * 服务不可达时自动 skip（不算失败）。
 *
 * 4 case：
 * - 银河E5 命中（series_id=7650）
 * - 铂智7X needs_online_verify
 * - "7X" 歧义多候选
 * - 虚构车系 fail-closed
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { loginOnce, authHeaders } from './auth_smoke.ts';

const BASE = process.env.PRISM_FASTAPI || 'http://127.0.0.1:8002';
const RESOLVE = `${BASE}/identity/resolve`;

async function checkService(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/health`, { signal: AbortSignal.timeout(2000) });
    if (res.ok) await loginOnce(BASE); // 登录门禁适配（探活成功即登录，失败让请求401红掉）
    return res.ok;
  } catch {
    return false;
  }
}

async function resolve(seriesKey: string) {
  const res = await fetch(`${RESOLVE}?series_key=${encodeURIComponent(seriesKey)}`, { headers: authHeaders() });
  return { status: res.status, data: await res.json() as Record<string, unknown> };
}

describe('/identity/resolve · 对象身份核验', () => {
  it('银河E5 命中 → series_id=7650', async (t) => {
    if (!(await checkService())) return t.skip('prism-api 服务未运行');
    const { status, data } = await resolve('银河E5');
    assert.equal(status, 200);
    assert.equal(data.ambiguous, false);
    assert.equal(data.needs_online_verify, false);
    assert.equal(Number(data.series_id), 7650);
    assert.equal(typeof data.canonical_name, 'string');
    assert.ok((data.canonical_name as string).includes('银河E5'));
    assert.ok(typeof data.coverage === 'object' && data.coverage !== null);
  });

  it('铂智7X → needs_online_verify=true（库中无数据）', async (t) => {
    if (!(await checkService())) return t.skip('prism-api 服务未运行');
    const { status, data } = await resolve('铂智7X');
    assert.equal(status, 200);
    assert.equal(data.ambiguous, false);
    assert.equal(data.needs_online_verify, true);
    assert.equal(data.series_id, null);
    assert.ok(Array.isArray(data.warnings) && (data.warnings as string[]).length > 0);
  });

  it('"7X" → 降级模式 fail-closed（2026-10-07 alias 表缺失：简称不猜，宁拒不放）', async (t) => {
    if (!(await checkService())) return t.skip('prism-api 服务未运行');
    const { status, data } = await resolve('7X');
    assert.equal(status, 200);
    // 原 alias 歧义检测（7 候选）随上游库重建消失；降级判据=精确名才放行，简称 fail-closed
    assert.equal(data.ambiguous, false);
    assert.equal(data.series_id, null);
    assert.equal(data.needs_online_verify, true);
  });

  it('虚构车系 → fail-closed（series_id=null + needs_online_verify）', async (t) => {
    if (!(await checkService())) return t.skip('prism-api 服务未运行');
    const { status, data } = await resolve('不存在的虚构车系XYZ123');
    assert.equal(status, 200);
    assert.equal(data.series_id, null);
    assert.equal(data.ambiguous, false);
    assert.equal(data.needs_online_verify, true);
    assert.ok(Array.isArray(data.warnings));
    assert.ok((data.warnings as string[]).some(w => /未确认|未命中/.test(String(w))));
    assert.ok(Array.isArray(data.candidates) && (data.candidates as unknown[]).length === 0);
  });
});
