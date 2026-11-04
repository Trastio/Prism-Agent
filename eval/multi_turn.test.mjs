/**
 * 多轮评估批 change · 多轮机制纯函数单测（红绿先行：先于 multi_turn.mjs 编写）
 *
 * 覆盖：resolveMessage 话术池轮换 / selectBranch 条件分支 / carryCheck 轮间漂移
 *      （同值/漂移/不复现/千分位与全角归一/窗口边界）。
 * 契约：design.md §2（方案 v1.1 §10 三机制——不上 τ²-bench，偷它的魂）。
 * 运行：node --test eval/multi_turn.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveMessage, selectBranch, carryCheck, checkSnapshotDrift } from './multi_turn.mjs';

// ── 机制②：话术池轮换 ─────────────────────────────────────────────────
test('resolveMessage: string 直返（既有单话术题零影响）', () => {
  assert.equal(resolveMessage('风云T7 9月的销量是多少', 1), '风云T7 9月的销量是多少');
  assert.equal(resolveMessage('风云T7 9月的销量是多少', 3), '风云T7 9月的销量是多少');
});

test('resolveMessage: variants 按 repeat 取（REPEAT=k → variants[(k-1)%n]，缺省1=首个）', () => {
  const msg = { variants: ['硬怼', '软磨', '数据对抗'], variant_by: 'repeat' };
  assert.equal(resolveMessage(msg, 1), '硬怼');
  assert.equal(resolveMessage(msg, 2), '软磨');
  assert.equal(resolveMessage(msg, 3), '数据对抗');
  assert.equal(resolveMessage(msg, 4), '硬怼'); // 环回
});

test('resolveMessage: variants 空数组/畸形 → fail-closed 返回空串（不猜话术）', () => {
  assert.equal(resolveMessage({ variants: [], variant_by: 'repeat' }, 1), '');
  assert.equal(resolveMessage({ variant_by: 'repeat' }, 1), '');
});

// ── 机制①：条件分支追问 ───────────────────────────────────────────────
test('selectBranch: t1 无缺锚 → if_hit（看答下菜的深挖路径）', () => {
  const branch = { branch_on: 't1', if_hit: { message: '那和B10比呢？' }, else: { message: '你确定吗？我再问一次' } };
  const { turn, branch: taken } = selectBranch(branch, [{ turn: 1, ok: true }]);
  assert.equal(turn.message, '那和B10比呢？');
  assert.equal(taken, 'if_hit');
});

test('selectBranch: t1 缺锚/违禁 → else（压力路径：答含糊→追问到底）', () => {
  const branch = { branch_on: 't1', if_hit: { message: '那和B10比呢？' }, else: { message: '你确定吗？我再问一次' } };
  const { turn, branch: taken } = selectBranch(branch, [{ turn: 1, ok: false }]);
  assert.equal(turn.message, '你确定吗？我再问一次');
  assert.equal(taken, 'else');
});

test('selectBranch: 引用轮未判分（无 truth）→ 按含糊处理走 else（fail-closed）', () => {
  const branch = { branch_on: 't1', if_hit: { message: 'A' }, else: { message: 'B' } };
  assert.equal(selectBranch(branch, []).turn.message, 'B');
});

// ── 机制③：穿线验证（轮间一致性锚）────────────────────────────────────
const carry3k = { from: 1, keys: ['3,427'] };

test('carryCheck: 同值复现 → consistent（千分位原样）', () => {
  const replies = ['MG 4X 8月末 3,427 台', '最低配 9.98万', '舒适 71.7%'];
  const r = carryCheck(carry3k, replies);
  assert.equal(r.results[0].status, 'silent'); // t2=最低配价，不复现销量锚
  assert.equal(r.results[1].status, 'silent'); // t3=占比，不复现
  // 首轮不复现不算错（from=1：查 t2 起）；results[k] = 轮 from+k+...（0-based 数组首项=t2）
  const r2 = carryCheck(carry3k, ['MG 4X 8月末 3,427 台', '还是那 3,427 台', '销量 3427']);
  assert.equal(r2.results[0].status, 'consistent');
  assert.equal(r2.results[1].status, 'consistent'); // 去千分位归一命中
});

test('carryCheck: 近值漂移 → drift（t1=3427 → tN=3428，±2% 窗内不同值）', () => {
  const r = carryCheck(carry3k, ['MG 4X 8月末 3,427 台', '上轮说的销量是 3,428 台']);
  assert.equal(r.results[0].status, 'drift');
  assert.equal(r.results[0].found, 3428);
});

test('carryCheck: 不复现不查不算错（silent）+ 无近值干扰数字不误报', () => {
  const r = carryCheck(carry3k, ['MG 4X 8月末 3,427 台', '最低配卖 99,800 元', '占比 71.7%']);
  assert.ok(r.results.every((x) => x.status === 'silent'));
  assert.equal(r.hasDrift, false);
});

test('carryCheck: 全角数字归一（３,４２７ → 3427 命中）', () => {
  const r = carryCheck(carry3k, ['基线 3,427', '如前所述为３,４２７台']);
  assert.equal(r.results[0].status, 'consistent');
});

test('carryCheck: from 窗口边界——from=3 只查 t4 起，t2 漂移不检', () => {
  const carry = { from: 3, keys: ['4,436'] };
  const r = carryCheck(carry, ['E5 8月 4,436', '上月 4,437', '最新 4,436', '仍是 4,436']);
  assert.equal(r.results.length, 1); // 只有 t4
  assert.equal(r.results[0].turn, 4);
});

test('carryCheck: hasDrift 汇总 + 空 carry → null（单轮题零影响）', () => {
  assert.equal(carryCheck(null, ['x']), null);
  const bad = carryCheck(carry3k, ['3,427', '3,429', '3,430']);
  assert.equal(bad.hasDrift, true);
  assert.equal(bad.results.filter((x) => x.status === 'drift').length, 2);
});

// ── P1-2 快照漂移闸（Step8 补实装）─────────────────────────────────────
const _mt = (id, snap, n = 2) => ({ id, snapshot_id: snap, turns: Array.from({ length: n }, (_, i) => ({ message: 'q' + i })) });

test('checkSnapshotDrift: 无快照绑定题（any/缺 snapshot_id）→ ok 跳过', () => {
  const r = checkSnapshotDrift([{ id: 'cross-01', snapshot_id: 'any' }, { id: 'x' }], null);
  assert.equal(r.ok, true);
  assert.equal(r.mismatches.length, 0);
});

test('补审加宽对照：单轮绑定题快照不一致 → 同样 fail-closed（sales-11 九月空同族）', () => {
  const r = checkSnapshotDrift([{ id: 'sales-11', snapshot_id: 'snap-20261012-1222' }], 'snap-20261101-0000');
  assert.equal(r.ok, false);
  assert.deepEqual(r.mismatches, ['snap-20261012-1222']);
  assert.match(r.note, /九月空/);
});

test('补审加宽对照：单轮绑定题无戳 → 同样 fail-closed', () => {
  const r = checkSnapshotDrift([{ id: 'sales-01', snapshot_id: 'snap-20261012-1222' }], null);
  assert.equal(r.ok, false);
  assert.match(r.note, /ACTIVE_SNAPSHOT/);
});

test('checkSnapshotDrift: 题库快照=挂载戳 → ok；snapshot_id=any 不比对', () => {
  const tasks = [_mt('multi-01', 'snap-20261012-1222'), { id: 'cross-01', snapshot_id: 'any', turns: [{ message: 'q' }] }];
  const r = checkSnapshotDrift(tasks, 'snap-20261012-1222');
  assert.equal(r.ok, true);
  assert.match(r.note, /快照一致/);
});

test('checkSnapshotDrift: 轮换后不一致 → fail-closed 列 mismatch（m03-t3 九月空锚失效风险）', () => {
  const tasks = [_mt('multi-03', 'snap-20261012-1222'), _mt('multi-05', 'snap-20261012-1222')];
  const r = checkSnapshotDrift(tasks, 'snap-20261101-0000');
  assert.equal(r.ok, false);
  assert.deepEqual(r.mismatches, ['snap-20261012-1222']);
  assert.match(r.note, /九月空/);
});

test('checkSnapshotDrift: 有多轮题但无戳 → fail-closed（旧 eval 会话须重启或显式放行）', () => {
  const r = checkSnapshotDrift([_mt('multi-01', 'snap-20261012-1222')], null);
  assert.equal(r.ok, false);
  assert.match(r.note, /ACTIVE_SNAPSHOT/);
});
