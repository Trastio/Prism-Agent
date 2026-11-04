/**
 * 判分账本（eval/deduction.mjs）单测
 *
 * 锁三件事：
 *   ① scoreFromReasons 语义与迁移前逐条一致（rescore 忠实度闸依赖它）
 *   ② deductionFromReasons 的 steps 只记"真正改变分数"的步骤（from→to 递减）
 *   ③ 越界走 checkOverreach 复核实判（免责形态不降分），与 runner:385 同源
 * 运行：node --test eval/deduction.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { deductionFromReasons, scoreFromReasons } from './deduction.mjs';

const TASK = { id: 'cross-02', dimension: '销量' };

test('deduction：无扣分项 → 5 分且 steps 为空', () => {
  const d = deductionFromReasons([], TASK, '');
  assert.deepEqual(d, { base: 5, score: 5, steps: [] });
});

test('deduction：truth 缺锚 → 封顶 2，一条 from5→to2 记录', () => {
  const d = deductionFromReasons(['truth 缺锚: 46.15%'], TASK, '');
  assert.equal(d.score, 2);
  assert.deepEqual(d.steps, [{ from: 5, to: 2, reason: 'truth 缺锚: 46.15%' }]);
});

test('deduction：多轮形态 truth[t2] 缺锚同样封顶 2（2026-10-28 忠实度实录形态）', () => {
  const d = deductionFromReasons(['truth[t2] 缺锚/违禁: 25'], TASK, '');
  assert.equal(d.score, 2);
  assert.equal(d.steps.length, 1);
});

test('deduction：同档多条只记一次（已是 2 分再命中 cap2 不重复记）', () => {
  const d = deductionFromReasons(['truth 缺锚: x', '缺 as_of 声明'], TASK, '');
  assert.equal(d.score, 2);
  assert.deepEqual(d.steps.map((s) => s.to), [2]); // 第二条无分数变化，不入账
});

test('deduction：越界真命中 → 1 分，且 steps 从当前分一路降到 1', () => {
  const reply = '销量结构印证了这一判断，说明产品力确实更强。';
  const d = deductionFromReasons(['市场侧归因产品力（越界）'], TASK, reply);
  assert.equal(d.score, 1);
  assert.deepEqual(d.steps, [{ from: 5, to: 1, reason: '市场侧归因产品力（越界）' }]);
});

test('deduction：越界免责形态 → 不降分（checkOverreach 复核实判，不纯信 reason 字符串）', () => {
  const reply = '不能把销量当作产品力的印证，两者口径不同。';
  const d = deductionFromReasons(['市场侧归因产品力（越界）'], TASK, reply);
  assert.equal(d.score, 5);
  assert.equal(d.steps.length, 0);
});

test('deduction：验证器否决 → 1 分（非 trap 题）', () => {
  const d = deductionFromReasons(['验证器否决: 证据不足'], TASK, '');
  assert.equal(d.score, 1);
});

test('scoreFromReasons 与 deductionFromReasons.score 恒等（rescore 调用路径不受迁移影响）', () => {
  const cases = [
    [[], ''],
    [['truth 缺锚: 1'], ''],
    [['缺 supported_by 证据行 ID', '缺 as_of 声明'], ''],
    [['社媒题缺 URL 溯源'], ''],
    [['轮间漂移: t1=4436→t2=4437'], ''],
    [['验证器否决: x'], ''],
  ];
  for (const [reasons, reply] of cases) {
    assert.equal(scoreFromReasons(reasons, TASK, reply), deductionFromReasons(reasons, TASK, reply).score);
  }
});
