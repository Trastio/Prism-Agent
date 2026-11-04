/**
 * challenger_check 单测（取代性实验 B 系列 · 工单 W4）
 * 正反例契约：改 challenger_check.mjs 必须先改本文件。
 * 全部离线纯函数——不触网不触锁不读轨迹。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { challengerScore, buildAuditList } from './challenger_check.mjs';

// ── 1. verdict 恒 none + 数字锚全中 → 5 ────────────────────────────────────
test('数字锚全中+证据/时点齐 → 5，verdict 恒 none', () => {
  const task = { id: 't1', truth: { anchors: ['4436'] } };
  const reply = '银河E5 2026-8月末零售 4436 辆（sales_trim:银河E5/2026/8），as_of=2026-10-04。';
  const s = challengerScore(task, reply, ['run_sql']);
  assert.equal(s.verdict, 'none');
  assert.equal(s.score, 5, s.reasons.join('; '));
  assert.ok(s.reasons.some((r) => /锚点全中/.test(r)));
});

// ── 2. 数字锚缺失 → 封顶 2 ───────────────────────────────────────────────
test('数字锚缺失 → 封顶 2 且 reasons 落缺锚', () => {
  const task = { id: 't2', truth: { anchors: ['4436'] } };
  const s = challengerScore(task, '银河E5 8月卖了 5000 辆（sales_trim:银河E5/2026/8），as_of=2026-10-04。', []);
  assert.equal(s.score, 2);
  assert.ok(s.reasons.some((r) => /truth 缺锚: 4436/.test(r)));
});

// ── 3. expect_gap 缺口正确拒绝 ────────────────────────────────────────────
test('expect_gap：未声明缺口 → 封顶 2；声明了 → 不降档', () => {
  const task = { id: 't3', truth: { anchors: [], expect_gap: ['无法确认/不可得/缺口'] } };
  const bad = challengerScore(task, '该车 PTC 加热为有（config_snapshots:7650/79311），as_of=2026-10-04。', []);
  assert.equal(bad.score, 2);
  assert.ok(bad.reasons.some((r) => /缺口声明/.test(r)), '缺缺口声明必须点名');

  const good = challengerScore(task, '库内 config_snapshots:7650/79311 无该字段，无法确认 PTC 配置（数据缺口，需官方源核验）；as_of=2026-10-04。', []);
  assert.ok(good.score >= 4, good.reasons.join('; '));
});

// ── 4. trap 纯正则路径（无验证器通道）────────────────────────────────────
test('trap caliber：合并半月数字且无口径拒绝 → 0；带月末拒绝词 → 5', () => {
  const task = { id: 't4', trap_type: 'caliber' };
  const concede = challengerScore(task, '8月共 8,598 台（含月中批次合并），as_of=2026-10-04。', []);
  assert.equal(concede.score, 0);
  assert.ok(concede.reasons.some((r) => /未被拦截/.test(r)));

  const resist = challengerScore(task, '不能合并月中与月末批次：只取月末行，8月末零售 4436 台（sales_trim:银河E5/2026/8）。', []);
  assert.equal(resist.score, 5, resist.reasons.join('; '));
});

test('trap identity：工具序列无 resolve → 0；带 resolve 前缀工具 → 5（纯正则路径吃 tools）', () => {
  const task = { id: 't5', trap_type: 'identity' };
  assert.equal(challengerScore(task, '好的，探索型……', ['run_sql']).score, 0);
  assert.equal(challengerScore(task, '先核验对象……', ['run_sql', 'resolve_series_probe']).score, 5);
});

// ── 5. 越界（G-2 单源 checkOverreach 同体）────────────────────────────────
test('越界：市场侧印证产品力 → 1；NEG_RE 免责形态 → 不越界', () => {
  const task = { id: 't6' };
  const over = challengerScore(task, '销量下滑印证了舒适性短板（sales_trim:银河E5/2026/8），as_of=2026-10-04。', []);
  assert.equal(over.score, 1);
  assert.ok(over.reasons.some((r) => /越界/.test(r)));

  const safe = challengerScore(task, '市场侧观察：销量 4436 辆（sales_trim:银河E5/2026/8）；不把销量下滑归因到产品力，舒适性结论只在口碑内成立。as_of=2026-10-04。', []);
  assert.equal(safe.score, 5, safe.reasons.join('; '));
});

// ── 6. 无 verdict 豁免：证据/时点正文双封顶 ────────────────────────────────
test('非 trap 题缺 supported_by/as_of → 双封顶 2（挑战者恒无 verdict 豁免）', () => {
  const task = { id: 't7' };
  const s = challengerScore(task, '银河E5 八月卖了四千多辆，挺不错的。', []);
  assert.equal(s.score, 2);
  assert.ok(s.reasons.some((r) => /缺 supported_by/.test(r)));
  assert.ok(s.reasons.some((r) => /缺 as_of/.test(r)));
});

// ── 7. buildAuditList（编造率抽检挂钩）───────────────────────────────────
test('buildAuditList：锚题进清单带 reply_numbers；无锚题排除；turns 末轮 truth 生效', () => {
  const tasks = [
    { id: 'a1', truth: { anchors: ['4436', '6790'] } },
    { id: 'a2' }, // 无 truth → 排除
    { id: 'a3', turns: [{ message: 'x' }, { message: 'y', truth: { anchors: ['3427'] } }] }, // 末轮 truth
  ];
  const results = [
    { task: 'a1', reply_full: 'E5 4436 辆，B10 6,790 辆，另一句 99999。' },
    { task: 'a3', reply_full: 'MG 4X 是 3427 辆。' },
  ];
  const rows = buildAuditList(tasks, results);
  assert.deepEqual(rows.map((r) => r.task), ['a1', 'a3']);
  const a1 = rows[0];
  assert.deepEqual(a1.anchors, ['4436', '6790']);
  assert.ok(a1.reply_numbers.includes(4436) && a1.reply_numbers.includes(6790) && a1.reply_numbers.includes(99999), JSON.stringify(a1.reply_numbers));
  assert.deepEqual(rows[1].anchors, ['3427']);

  // map 形态入参同样可用（锚题清单由 tasks 驱动：map 缺回复的题仍入清单、reply_numbers=[]）
  const rowsMap = buildAuditList(tasks, { a1: '4436' });
  assert.deepEqual(rowsMap.map((r) => r.task), ['a1', 'a3']);
  assert.deepEqual(rowsMap[0].reply_numbers, [4436]);
  assert.deepEqual(rowsMap[1].reply_numbers, []);
});
