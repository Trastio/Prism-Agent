/**
 * langfuse 深度绑定单测（T4，2026-10-19）
 *
 * 全 mock 零触网（Gap7）：monkeypatch globalThis.fetch 返回假响应——不对活 langfuse
 * 栈做任何真实调用（活栈冒烟由主会话独立脚本承担）。凭证安全：LANGFUSE_* env 假值
 * 优先于文件（loadBindingCreds env 优先口径），测试不读真凭证、不打印任何密钥。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  diffDatasetItems,
  buildDatasetItemBody,
  syncDatasetItems,
  linkRun,
  bindEvalRun,
} from './langfuse_binding.ts';
import { humanizeScoreName } from './annotate.mjs';

// 假凭证（env 优先）：测试独立性 + 不触真密钥
process.env.LANGFUSE_PUBLIC_KEY = 'test-pk';
process.env.LANGFUSE_SECRET_KEY = 'test-sk';
process.env.LANGFUSE_BASE_URL = 'http://langfuse.test';

const origFetch = globalThis.fetch;

/** 装 mock fetch：按 URL 正则(+可选 method)路由；记录全部调用供断言。 */
function withMock(routes, fn) {
  return async () => {
    const calls = [];
    globalThis.fetch = async (url, init = {}) => {
      const method = init.method || 'GET';
      calls.push({ url: String(url), method, body: init.body ? JSON.parse(init.body) : null });
      const hit = routes.find((r) => (!r.method || r.method === method) && r.url.test(String(url)));
      if (!hit) throw new Error(`mock 无路由: ${method} ${url}`);
      if (hit.throw) throw hit.throw;
      return { ok: true, status: hit.status ?? 200, json: async () => hit.json };
    };
    try {
      await fn(calls);
    } finally {
      globalThis.fetch = origFetch;
    }
  };
}

const fiveTasks = ['t1', 't2', 't3', 't4', 't5'].map((id) => ({
  id, set: 'dev', dimension: '配置', question: `Q-${id}`,
  judge_rubric: '金标要点', expected_evidence: 'config_snapshots', as_of: '2026-10-04',
}));

// ── 1. diffDatasetItems（纯函数）─────────────────────────────────
test('diffDatasetItems: 已有 taskId 的不进新建列表；无 metadata 的存量 item 不匹配任何题', () => {
  const existing = [
    { id: 'item-1', metadata: { taskId: 't1' } },
    { id: 'item-2', metadata: null },
    { id: 'item-3' }, // 无 metadata
    { id: 'item-4', metadata: {} }, // 有 metadata 无 taskId
    { id: 'item-5', metadata: { taskId: 123 } }, // taskId 非字符串
  ];
  const missing = diffDatasetItems(existing, fiveTasks);
  assert.deepEqual(missing.map((t) => t.id), ['t2', 't3', 't4', 't5']); // 仅 t1 被匹配
});

test('buildDatasetItemBody: golden_digest 截断 500 / 及格线缺省省略有则透传 / 简短字段透传', () => {
  const body = buildDatasetItemBody('prism-eval-60', {
    ...fiveTasks[0], id: 'trap-01', set: 'frozen', judge_rubric: 'x'.repeat(600), trap_type: 'name_grounding',
  });
  assert.equal(body.datasetName, 'prism-eval-60');
  assert.equal(body.expectedOutput.golden_digest.length, 500);
  assert.equal(body.expectedOutput.pass, undefined); // 题集无及格线字段 → 省略
  assert.equal(body.input.question, 'Q-t1');
  assert.equal(body.input.trap_type, 'name_grounding');
  assert.equal(body.metadata.taskId, 'trap-01');
  assert.equal(body.metadata.group, 'frozen');
  // Step8 P2-1：pass_line 存在的正向分支
  const withPass = buildDatasetItemBody('prism-eval-60', { ...fiveTasks[1], pass_line: 4 });
  assert.equal(withPass.expectedOutput.pass, 4);
});

// ── 2. syncDatasetItems（先查后建，只补缺）───────────────────────
test('syncDatasetItems: GET 返回 2 个已有 item + 5 题 → 只 POST 3 次', withMock([
  { url: /\/api\/public\/datasets/, json: { data: [{ id: 'ds-1', name: 'prism-eval-60' }] } },
  { url: /\/api\/public\/dataset-items\?/, json: { data: [
    { id: 'i-1', metadata: { taskId: 't1' } },
    { id: 'i-2', metadata: { taskId: 't2' } },
  ], meta: { totalPages: 1 } } },
  { method: 'POST', url: /\/api\/public\/dataset-items$/, json: { id: 'new-item' } },
], async (calls) => {
  const sum = await syncDatasetItems(fiveTasks);
  const posts = calls.filter((c) => c.method === 'POST' && /dataset-items$/.test(c.url));
  assert.equal(posts.length, 3);
  assert.equal(sum.created, 3);
  assert.equal(sum.skipped, 2);
  assert.deepEqual(sum.failed, []);
  // payload 形态断言（验收 1）
  assert.equal(posts[0].body.datasetName, 'prism-eval-60');
  assert.equal(posts[0].body.input.question, 'Q-t3');
  assert.equal(posts[0].body.expectedOutput.golden_digest, '金标要点');
  assert.equal(posts[0].body.metadata.taskId, 't3');
  assert.equal(posts[0].body.metadata.group, 'dev');
  // dataset 已存在 → 不 POST /datasets
  assert.equal(calls.filter((c) => c.method === 'POST' && /\/datasets$/.test(c.url)).length, 0);
}));

test('syncDatasetItems: dataset 不存在 → 先 POST 创建再建 item；单题失败继续其余', withMock([
  { url: /\/api\/public\/datasets\?/, json: { data: [] } },
  { method: 'POST', url: /\/api\/public\/datasets$/, json: { id: 'ds-new', name: 'prism-eval-60' } },
  { url: /\/api\/public\/dataset-items\?/, json: { data: [], meta: { totalPages: 1 } } },
  { method: 'POST', url: /\/api\/public\/dataset-items$/, json: null, status: 500 }, // 全部 500
], async (calls) => {
  const sum = await syncDatasetItems(fiveTasks);
  assert.equal(calls.filter((c) => c.method === 'POST' && /\/datasets$/.test(c.url)).length, 1);
  assert.equal(sum.created, 0);
  assert.equal(sum.failed.length, 5); // 单题失败记入 failed 继续
  assert.ok(sum.failed[0].startsWith('t1: langfuse POST /api/public/dataset-items HTTP 500'));
}));

// ── 3. linkRun（run-item + score 各 2 次，payload 含 datasetRunId）──
test('linkRun: 2 条 results → 2 次 dataset-run-items POST + 2 次 scores POST；noTrace 跳过计数', withMock([
  { url: /\/api\/public\/dataset-items\?/, json: { data: [
    { id: 'i-1', metadata: { taskId: 't1' } },
    { id: 'i-2', metadata: { taskId: 't2' } },
    { id: 'i-3', metadata: { taskId: 't3' } },
  ], meta: { totalPages: 1 } } },
  { method: 'POST', url: /\/api\/public\/dataset-run-items$/, json: { id: 'ri-1', datasetRunId: 'run-42' } },
  { method: 'POST', url: /\/api\/public\/scores$/, json: { id: 'score-1' } },
], async (calls) => {
  const sum = await linkRun('r-2026', [
    { taskId: 't1', traceId: 'tr-1', pass: true },
    { taskId: 't2', traceId: 'tr-2', pass: false },
    { taskId: 't3', traceId: null, pass: true }, // 无 traceId → 跳过
  ]);
  assert.equal(sum.linked, 2);
  assert.equal(sum.skippedNoTrace, 1);
  assert.deepEqual(sum.failed, []);
  const runItems = calls.filter((c) => /\/api\/public\/dataset-run-items$/.test(c.url));
  const scores = calls.filter((c) => /\/api\/public\/scores$/.test(c.url));
  assert.equal(runItems.length, 2);
  assert.equal(scores.length, 2);
  // run-item payload
  assert.equal(runItems[0].body.runName, 'r-2026');
  assert.equal(runItems[0].body.datasetItemId, 'i-1');
  assert.equal(runItems[0].body.traceId, 'tr-1');
  // score payload：关联字段实测名 = datasetRunItemId（值=run-item id；datasetRunId 会被 400 拒）
  assert.equal(scores[0].body.datasetRunItemId, 'ri-1');
  assert.equal(scores[0].body.name, 'task-pass');
  assert.equal(scores[0].body.value, 1);
  assert.equal(scores[1].body.value, 0);
  assert.equal(scores[0].body.dataType, 'NUMERIC');
  assert.equal(scores[0].body.comment, 'auto: prism eval run');
}));

// ── 4. bindEvalRun fail-soft（拍板④）─────────────────────────────
test('bindEvalRun fail-soft: fetch 抛错 → console.warn 一条后返回 null，不抛', withMock([
  { url: /.*/, throw: new Error('ECONNREFUSED (mock)') },
], async () => {
  const warns = [];
  const origWarn = console.warn;
  console.warn = (m) => warns.push(String(m));
  try {
    const r = await bindEvalRun(fiveTasks, 'r-x', [{ taskId: 't1', traceId: 'tr', pass: true }]);
    assert.equal(r, null); // 绝不让调用方（runner）崩
    assert.equal(warns.length, 1); // Step8 P2-2：fail-soft 必须恰好一条警告
    assert.ok(warns[0].includes('绑定降级'));
  } finally {
    console.warn = origWarn;
  }
}));

// Step8 P1 回归：200 但响应结构异常 → 必须 fail-loud 抛（经 bindEvalRun 兜底成 null），
// 绝不静默当"空库"全量 POST（dataset-items 不幂等，翻倍不可恢复）
test('bindEvalRun: 200 但 dataset-items 响应缺 data/meta → 走 fail-soft 而非全量 POST', withMock([
  { url: /\/api\/public\/datasets\?/, json: { data: [{ id: 'ds-1', name: 'prism-eval-60' }] } },
  { url: /\/api\/public\/dataset-items\?/, json: { data: '坏形状' } }, // data 非数组
], async (calls) => {
  const r = await bindEvalRun(fiveTasks, 'r-bad', []);
  assert.equal(r, null);
  assert.equal(calls.filter((c) => c.method === 'POST').length, 0); // 一个 POST 都不许发
}));

// Step8 P2-2：翻页覆盖——totalPages=2 → dataset-items GET 恰好 2 次且聚合两页
test('syncDatasetItems: totalPages=2 → 翻页两轮 GET，跨页聚合', withMock([
  { url: /\/api\/public\/datasets\?/, json: { data: [{ id: 'ds-1', name: 'prism-eval-60' }] } },
  { url: /page=1&limit=50/, json: { data: [{ id: 'i-1', metadata: { taskId: 't1' } }], meta: { totalPages: 2 } } },
  { url: /page=2&limit=50/, json: { data: [{ id: 'i-2', metadata: { taskId: 't2' } }], meta: { totalPages: 2 } } },
  { method: 'POST', url: /\/api\/public\/dataset-items$/, json: { id: 'new' } },
], async (calls) => {
  const sum = await syncDatasetItems(fiveTasks);
  const gets = calls.filter((c) => c.method === 'GET' && /dataset-items\?/.test(c.url));
  assert.equal(gets.length, 2); // 恰好两页，不死循环
  assert.equal(sum.skipped, 2); // 两页各命中 1 题
  assert.equal(sum.created, 3);
}));

// ── 5. annotate 的 human- 前缀逻辑（可导入函数直测）─────────────
test('humanizeScoreName: 无前缀补 human-，有则不重复，空白 trim', () => {
  assert.equal(humanizeScoreName('tone'), 'human-tone');
  assert.equal(humanizeScoreName('human-tone'), 'human-tone');
  assert.equal(humanizeScoreName('  spacing  '), 'human-spacing');
  assert.equal(humanizeScoreName(''), 'human-');
  assert.equal(humanizeScoreName(undefined), 'human-');
});
