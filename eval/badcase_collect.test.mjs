/**
 * badcase 采集回归测试（2026-10-31）
 *
 * 锁三条不变式：
 *   ① 系统注入的续跑消息（"[完成验证器] …"）不得被当成用户题面（实测 L4 误收）
 *   ② verdict=fail 必收；pass 但用户重问/纠正也要收（B 类是规则层漏掉的坏例的唯一来源）
 *   ③ 重问的 ref_line 指向被否定的上一轮，保证根因可回溯
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { collectBadcases, similarity } from './dynamic-tasks.ts';

function writeTraj(rows) {
  const dir = mkdtempSync(join(tmpdir(), 'badcase-'));
  const p = join(dir, 'traj.jsonl');
  writeFileSync(p, rows.map((r) => JSON.stringify(r)).join('\n'), 'utf-8');
  return { p, cleanup: () => rmSync(dir, { recursive: true, force: true }) };
}

const base = (over = {}) => ({
  sessionId: 's1', timestamp: '2026-10-30T00:00:00Z',
  conversation: ['user: 你好', 'assistant: 好'],
  toolCalls: [], final_conclusion: '', evidence_ids: [],
  verdict: 'pass', verdict_reason: '出口闸通过',
  ...over,
});

test('similarity：同串=1，异串=0，近似过阈值', () => {
  assert.equal(similarity('银河E5舆情怎么样', '银河E5舆情怎么样'), 1);
  assert.equal(similarity('银河E5舆情怎么样', '哈弗H6销量多少'), 0);
  assert.ok(similarity('银河E5舆情怎么样', '银河E5的舆情怎么样？') >= 0.6);
  assert.equal(similarity('', '任何'), 0);
});

test('verdict=fail 必收，四件套齐全', () => {
  const { p, cleanup } = writeTraj([base({
    conversation: ['user: 宋Pro新能源口碑怎么样', 'assistant: 口碑不错'],
    toolCalls: [{ name: 'query_reviews', input: {} }, { name: 'query_sales', input: {} }],
    verdict: 'fail', verdict_reason: '缺少 supported_by 行 ID',
  })]);
  try {
    const c = collectBadcases(p);
    assert.equal(c.length, 1);
    assert.equal(c[0].signal, 'verdict_fail');
    assert.equal(c[0].question, '宋Pro新能源口碑怎么样');
    assert.deepEqual(c[0].tools, ['query_reviews', 'query_sales']);
    assert.equal(c[0].verdict_reason, '缺少 supported_by 行 ID');
    assert.equal(c[0].source_line, 1);
  } finally { cleanup(); }
});

test('系统注入消息不得成为题面（真实问题回溯）', () => {
  const { p, cleanup } = writeTraj([base({
    conversation: [
      'user: 宋Pro新能源口碑怎么样',
      'assistant: 草稿',
      'user: [完成验证器] mixed tier 验收未通过：缺少 supported_by',
      'assistant: 修订稿',
    ],
    verdict: 'fail', verdict_reason: '漏提交',
  })]);
  try {
    const c = collectBadcases(p);
    assert.equal(c.length, 1);
    assert.equal(c[0].question, '宋Pro新能源口碑怎么样', '题面必须是人类问题，不是验证器文案');
    assert.equal(c[0].has_sys_inject, true, '自纠轮要留标记，便于区分"首答错"与"改后仍错"');
  } finally { cleanup(); }
});

test('pass 但用户重问 → 收为 B 类，ref_line 指向上轮', () => {
  const { p, cleanup } = writeTraj([
    base({ conversation: ['user: 银河E5舆情怎么样', 'assistant: 答得含糊'], verdict: 'pass' }),
    base({ conversation: ['user: 银河E5舆情怎么样', 'user: 银河E5的舆情怎么样？', 'assistant: 再说一遍'], verdict: 'pass' }),
  ]);
  try {
    const c = collectBadcases(p);
    assert.equal(c.length, 1, '只有第二行触发重问，首行无信号不收');
    assert.equal(c[0].signal, 'user_rephrase');
    assert.equal(c[0].ref_line, 1);
    assert.equal(c[0].source_line, 2);
  } finally { cleanup(); }
});

test('用户显式纠正 → 收为 user_correct', () => {
  const { p, cleanup } = writeTraj([base({
    conversation: ['user: 帮我看看理想L6', 'assistant: 好的', 'user: 不对，我说的是配置对比'],
    verdict: 'pass',
  })]);
  try {
    const c = collectBadcases(p);
    assert.equal(c.length, 1);
    assert.equal(c[0].signal, 'user_correct');
  } finally { cleanup(); }
});

test('干净 pass 且无行为信号 → 不收', () => {
  const { p, cleanup } = writeTraj([base({ conversation: ['user: 你好', 'assistant: 好'] })]);
  try {
    assert.equal(collectBadcases(p).length, 0);
  } finally { cleanup(); }
});

test('文件缺失 → 返回空数组（不抛）', () => {
  assert.deepEqual(collectBadcases('no-such-file.jsonl'), []);
});
