/**
 * /verify/claim 舆情源分支集成测试（出口闸舆情源登记，2026-10-11）
 * 框架：node:test（Node 内置，无依赖）
 * 运行：node --test --import tsx tests/verify_claim_api.test.ts
 *
 * 注意：需要 prism-api 服务在 http://127.0.0.1:8002 运行。
 * 服务不可达时自动 skip（不算失败，与 identity_api.test.ts 同模式）。
 *
 * 4 case：
 * - sentiment_overview:风云T7（真车系）→ 无 failure
 * - sentiment_overview:不存在的车系XYZW → failure（fail-closed 有效）
 * - sentiment_posts:{真帖ID}（从舆情库现取）→ 无 failure
 * - sentiment_posts:00000000-0000-0000-0000-000000000000 → failure
 * - 三维度回归：sales_trim:银河E5/2026 → 无 failure（改动不伤旧分支）
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { loginOnce, authHeaders } from './auth_smoke.ts';
import Database from 'better-sqlite3';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const BASE = process.env.PRISM_FASTAPI || 'http://127.0.0.1:8002';
const VERIFY = `${BASE}/verify/claim`;
const ROOT = join(dirname(dirname(fileURLToPath(import.meta.url))));
const SENT_DB = process.env.PRISM_SENTIMENT_DB || join(ROOT, 'prism-sentiment', 'data', 'vehicle_sentiment.db');

async function serviceUp(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/health`, { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}

async function verifyClaim(refs: string[]): Promise<string[]> {
  const res = await fetch(VERIFY, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ supported_by: refs }),
    signal: AbortSignal.timeout(5000),
  });
  assert.equal(res.status, 200);
  const data = await res.json() as { failures?: string[] };
  return data.failures || [];
}

/** 舆情库现取一个真帖 ID（库缺失时抛错→本轮 case 标记失败，符合 fail-closed 语义） */
function realPostId(): string {
  const db = new Database(SENT_DB, { readonly: true, fileMustExist: true });
  try {
    const row = db.prepare('SELECT id FROM raw_posts LIMIT 1').get() as { id: string } | undefined;
    if (!row) throw new Error('舆情库 raw_posts 为空');
    return row.id;
  } finally {
    db.close();
  }
}

describe('/verify/claim · sentiment_* 舆情源分支（出口闸舆情源登记）', async () => {
  const up = await serviceUp();
  if (up) await loginOnce(BASE); // 登录门禁适配
  it(up ? '服务在线，跑 5 case' : 'prism-api 服务不可达 → skip', { skip: !up }, async () => {
    // 1. 真车系（overview：车存在即过）
    assert.deepEqual(await verifyClaim(['sentiment_overview:风云T7']), []);
    // 2. 假车系 → fail-closed
    assert.ok((await verifyClaim(['sentiment_overview:不存在的车系XYZW'])).length > 0);
    // 3. 真帖 ID（posts：raw_posts.id 精确）
    const pid = realPostId();
    assert.deepEqual(await verifyClaim([`sentiment_posts:${pid}`]), []);
    // 4. 假 uuid → 拒
    assert.ok((await verifyClaim(['sentiment_posts:00000000-0000-0000-0000-000000000000'])).length > 0);
    // 5. 三维度回归不受影响
    assert.deepEqual(await verifyClaim(['sales_trim:银河E5/2026']), []);
    // 6. sentiment_defects（2026-10-20 舆情工具层跟进）：真车系过 / 假车系拒
    assert.deepEqual(await verifyClaim(['sentiment_defects:风云T7']), []);
    assert.ok((await verifyClaim(['sentiment_defects:不存在的车系XYZW'])).length > 0);
    // 7. paused 车引用也过（出口闸查全量 vehicles 不筛 status——与工具层两级解析对齐）
    assert.deepEqual(await verifyClaim(['sentiment_defects:银河E5']), []);
  });
});
