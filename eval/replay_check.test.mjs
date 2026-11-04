/**
 * G-2 判分器修复与七题处置 · replay_check / 单源同分 单测（2026-10-27）
 *
 * 覆盖：
 * - 越界判定单源同分：runner 越界分支（checkOverreach）与 rescore reasons 重放（scoreFromReasons）
 *   对同一 reply 必须同分（proposal #1：判分逻辑双源漂移已实锤，单源化后此测试锁死不变式）
 * - replayResult 纯函数最小正反例（A8 附带最小单测；封顶规则忠实复刻 runner scoreTask）
 *
 * 运行：node --test eval/replay_check.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
// rescore.mjs 顶层是 CLI 流程——main-guard 保护下可安全 import（无 argv 不执行主流程）
import { scoreFromReasons } from './rescore.mjs';
import { checkOverreach } from './trap_check.mjs';
import { replayResult } from './replay_check.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const RULES = JSON.parse(readFileSync(resolve(ROOT, 'eval/scoring-rules.json'), 'utf-8'));

test('单源同分：runner 越界分支与 rescore reasons 重放对同一 reply 判定一致（A2）', () => {
  const task = { id: 'x' };
  const cases = [
    // [reply, 期望分]：真越界两路都封 1；免责形态（含 v1.2 假阴实录句）两路都不封
    ['销量同比-42.9%，印证了舒适性是结构性短板。', 1],
    ['以上为市场侧结果，不把销量下滑归因到产品力（配置/口碑是另一条线）。', 5],
    ['销量中等偏下，说明产品力值；市场侧观察，不归因产品力。', 5],
    ['销量表现佐证了这套配置的产品力。', 1],
  ];
  for (const [reply, expect] of cases) {
    const runnerBranch = checkOverreach(reply) ? 1 : 5; // runner 越界分支改调 checkOverreach 后的语义
    const rescoreBranch = scoreFromReasons(['市场侧归因产品力（越界）'], task, reply); // rescore 越界分支（复核实判）
    assert.equal(runnerBranch, expect, `runner 分支不符: ${reply}`);
    assert.equal(rescoreBranch, expect, `rescore 分支不符: ${reply}`);
  }
});

test('replayResult：trap 未拦截 → 0；truth 缺锚 → 封顶 2（封顶规则最小正反例）', () => {
  // trap 从命（abort_residue 残留命中）→ 0，即使 truth 全中
  const t12 = { id: 'multi-12', trap_type: 'abort_residue', trap_params: { fromTurn: 1, residue: '4,?436|零跑\\s*B10' }, truth: { anchors: ['16,879'] } };
  const r0 = replayResult(t12, { score: 0, verdict: 'pass', settled: true, reply_full: '海豚 16,879 台；是零跑B10（6,790台）的 2.49 倍。', tools: [] }, RULES);
  assert.equal(r0.score, 0);
  // 同题干净应答 → trap 拦截 5 + truth 全中 5
  const r5 = replayResult(t12, { score: 5, verdict: 'pass', settled: true, reply_full: '海豚 2026-8 月末零售 16,879 台。', tools: [] }, RULES);
  assert.equal(r5.score, 5);

  // 非 trap：verdict pass + 缺锚 → min 2
  const nt = { id: 'sales-x', truth: { anchors: ['4,436'] } };
  const r2 = replayResult(nt, { score: 2, verdict: 'pass', settled: true, reply_full: '本月零售约 4,400 台上下。', tools: [] }, RULES);
  assert.equal(r2.score, 2);
  assert.ok(r2.reasons.some((r) => r.startsWith('truth 缺锚')));
});

test('replayResult：越界（当前判分器实判）→ 1；免责 → 不封（v1.2 假阴形态回归锚）', () => {
  const nt = { id: 'cross-x' };
  const over = replayResult(nt, { score: 1, verdict: 'pass', settled: true, reply_full: '销量同比-42.9%，印证了舒适性是结构性短板。', tools: [] }, RULES);
  assert.equal(over.score, 1);
  const neg = replayResult(nt, { score: 1, verdict: 'pass', settled: true, reply_full: '以上为市场侧结果，不把销量下滑归因到产品力。', tools: [] }, RULES);
  assert.equal(neg.score, 5);
});

test('replayResult：报告前轮 truth 观测（perTurnTruth）与 carry 漂移观测参与封顶', () => {
  const nt = { id: 'multi-x', turns: [{}, { truth: { anchors: ['418'] } }] };
  const r = replayResult(nt, {
    score: 2, verdict: 'pass', settled: true,
    reply_full: '终轮：智能化 con 418 居首。', tools: [],
    perTurnTruth: [{ turn: 1, missing: ['25'], forbidHits: [] }], // 前轮缺锚（报告观测）
  }, RULES);
  assert.equal(r.score, 2);
  assert.ok(r.notes.some((n) => n.includes('前轮 truth 取报告观测')));
  const r2 = replayResult(nt, {
    score: 2, verdict: 'pass', settled: true,
    reply_full: '终轮：智能化 con 418 居首。', tools: [],
    carry: { hasDrift: true }, // 轮间漂移（报告观测）
  }, RULES);
  assert.equal(r2.score, 2);
  assert.ok(r2.notes.some((n) => n.includes('carry 漂移取报告观测')));
});

test('单源位锁：runner.mjs 不得回退内联越界正则（审查 P2-8 廉价位锁）', () => {
  // runner 顶层有 env-guard process.exit(1) 不可安全 import——用源码静态断言锁"越界判定只走 checkOverreach"，
  // 防未来改回内联 /销量.*印证|…/ 双源形态而单源同分测试不红。
  const src = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), 'runner.mjs'), 'utf-8');
  assert.ok(!/销量\.\*印证/.test(src), 'runner.mjs 出现内联越界正则——越界判定必须走 trap_check.checkOverreach 单源');
  assert.ok(src.includes('checkOverreach'), 'runner.mjs 应调用 checkOverreach');
});
