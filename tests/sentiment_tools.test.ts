/**
 * sentiment 工具层单测（舆情工具层跟进，2026-10-20）
 * 框架：node:test（Node 内置，无依赖）
 * 运行：node --test --import tsx tests/sentiment_tools.test.ts
 *
 * 覆盖 resolveVehicleId 两级解析（红线#1：paused 车不误报"未收录"）：
 * - 风云T7（active）→ fleet-overview 一级命中
 * - 银河E5（paused）→ fleet-overview miss → fallback /api/vehicles 命中 → 照查（冻结语义）
 * - 'model y'（大小写/空格变体）→ fallback 归一匹配命中 Model Y（active）
 * - 不存在的车 → null
 *
 * 集成测试：需 prism-api(8002) 与舆情(8000) 双服务在跑（resolveVehicleId 走
 * /sentiment-board 反代）。8002 不可达时 skip（与 verify_claim_api.test.ts 同模式）。
 * defect-themes 端点真调不进自动门禁（TTL 过期会触发 LLM 自愈重算，烧钱+慢）——Step9 手工验。
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const BASE = process.env.PRISM_FASTAPI || 'http://127.0.0.1:8002';
const ROOT = join(dirname(dirname(fileURLToPath(import.meta.url))));

// 生产链路里 extension 跑在 pi 子进程内，网关注入 PRISM_SERVICE_TOKEN 过登录门（10-18 热修）；
// 测试进程没有该 env → 反代 401。此处贴近生产路径注入 .pi/service_token。
// P2-6（Step7 审查）：不做"token 缺失降级直连 8000"——fallback 固定走 FASTAPI 的
// /sentiment/vehicles-all，降级模式下 case2 必挂是死路径；token 读不到 = 栈不完整，
// fail-loud 红掉暴露问题（与 auth_smoke 同哲学）。必须先设 env 再动态 import（模块级读 env）。
process.env.PRISM_SERVICE_TOKEN = readFileSync(join(ROOT, '.pi', 'service_token'), 'utf8').trim();
const { resolveVehicleId } = await import('../.pi/extensions/prism-guardrails/index.ts');

async function serviceUp(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/health`, { signal: AbortSignal.timeout(2000) });
    return res.ok;
  } catch {
    return false;
  }
}

describe('sentiment 工具层 · resolveVehicleId 两级解析', async () => {
  const up = await serviceUp();
  it(up ? '服务在线，跑 4 case' : 'prism-api 服务不可达 → skip', { skip: !up }, async () => {
    // 1. active 车一级命中（fleet-overview）
    const t7 = await resolveVehicleId('风云T7');
    assert.ok(t7, '风云T7 应可解析');
    assert.equal(t7.status, 'active');
    assert.match(t7.id, /^[0-9a-f-]{36}$/);
    // 2. paused 车二级命中（fallback /api/vehicles）——红线#1：不再 null（误报"未收录"）
    const e5 = await resolveVehicleId('银河E5');
    assert.ok(e5, '银河E5（paused）应经 fallback 解析到，而非 null');
    assert.equal(e5.status, 'paused');
    assert.match(e5.id, /^[0-9a-f-]{36}$/);
    // 3. 大小写/空格变体归一匹配（Model Y）
    const my = await resolveVehicleId('model y');
    assert.ok(my, "'model y' 应归一命中 Model Y");
    assert.equal(my.status, 'active');
    // 4. 未收录车 → null（真缺口语义不变）
    assert.equal(await resolveVehicleId('不存在的车系XYZW'), null);
  });
});
