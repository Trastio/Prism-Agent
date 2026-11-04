/**
 * 评估基建小包 · 报告派生/留痕单测（report_lib + scoring-rules 完整性）
 *
 * 覆盖：首错轮判定 / 逐轮衰减聚合 / 恢复分类 / acceptance_boundary /
 *       SHA-256 manifest / 四 sheet 组装与 md 渲染 / calibration_log 回填合法
 * 运行：node --test eval/report_lib.test.mjs
 * 纪律：本文件只测派生层——既有 60 题判分器（trap/truth/rubric_check）行为零改动零断言变更
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import {
  firstErrorTurn, deriveBoundary, aggregateDecay, classifyRecovery, recoverySubset,
  crossCheckRows, sha256File, buildManifest, buildSheets, renderMd,
  isAnchored, splitByAnchored, pickTrajectory, computeCoverage, compareRuns,
  matchTrajectoryRowByPrefix, passAtK,
} from './report_lib.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

// ── 首错轮 ──
test('firstErrorTurn: 多轮题 perTurnTruth t2 缺锚 → 首错轮=2', () => {
  const row = {
    score: 2, turnVerdicts: ['pass', 'pass'],
    perTurnTruth: [{ turn: 1, missing: [], forbidHits: [] }, { turn: 2, missing: ['4436'], forbidHits: [] }],
  };
  assert.equal(firstErrorTurn(row), 2);
});

test('firstErrorTurn: 多轮题 t1 违禁优先于 t2 缺锚（取最早）', () => {
  const row = {
    score: 1, turnVerdicts: ['pass', 'pass', 'pass'],
    perTurnTruth: [{ turn: 1, missing: [], forbidHits: ['x'] }, { turn: 2, missing: ['y'], forbidHits: [] }],
  };
  assert.equal(firstErrorTurn(row), 1);
});

test('firstErrorTurn: 单轮题终轮判分失败 → 首错轮=1（v1.1 低分形态）', () => {
  assert.equal(firstErrorTurn({ score: 2, turnVerdicts: ['pass'], perTurnTruth: [], reasons: ['truth 缺锚: 46.15%'] }), 1);
  assert.equal(firstErrorTurn({ score: 1, turnVerdicts: ['pass'], perTurnTruth: [], reasons: ['市场侧归因产品力（越界）'] }), 1);
});

test('firstErrorTurn: 通过题 → null；timeout → null（基础设施错误不派生）', () => {
  assert.equal(firstErrorTurn({ score: 5, turnVerdicts: ['pass'], perTurnTruth: [], reasons: [] }), null);
  assert.equal(firstErrorTurn({ score: 0, turnVerdicts: [], perTurnTruth: [], reasons: ['timeout'] }), null);
});

// ── 逐轮衰减 ──
test('aggregateDecay: 单轮批聚合——命中/越界/总数对得上', () => {
  const rows = [
    { score: 5, turnVerdicts: ['pass'], perTurnTruth: [], truth: { checked: true, missing: [], forbidHits: [] }, reasons: [] },
    { score: 2, turnVerdicts: ['pass'], perTurnTruth: [], truth: { checked: true, missing: ['46.15%'], forbidHits: [] }, reasons: ['truth 缺锚: 46.15%'] },
    { score: 1, turnVerdicts: ['pass'], perTurnTruth: [], reasons: ['市场侧归因产品力（越界）'] },
  ];
  const d = aggregateDecay(rows);
  assert.equal(d.length, 1);
  assert.equal(d[0].turn, 1);
  assert.equal(d[0].total, 3);
  assert.equal(d[0].truthChecked, 2); // 第三行无 truth.checked 且无"truth 缺锚"前缀 → 不计查锚
  assert.equal(d[0].truthHit, 1);
  assert.equal(d[0].truth_hit_rate, '50%');
  assert.equal(d[0].overreach, 1);
});

// ── 恢复分类 ──
test('classifyRecovery: 三档 + 附和兜底', () => {
  assert.equal(classifyRecovery({ score: 5, reasons: [] }), '顶住');
  assert.equal(classifyRecovery({ score: 0, reasons: ['从命：附和 14.6 寸'] }), '附和');
  assert.equal(classifyRecovery({ score: 2, reasons: ['部分要素缺失'] }), '部分恢复');
});

test('recoverySubset: 只取纠正/取消中止原型题；v1.1 题（无 prototype）→ 空', () => {
  const tasks = [
    { id: 'multi-05', prototype: '纠正' },
    { id: 'sales-03' },
  ];
  const rows = [
    { task: 'multi-05', score: 5, reasons: [] },
    { task: 'sales-03', score: 5, reasons: [] },
  ];
  const got = recoverySubset(rows, tasks);
  assert.equal(got.length, 1);
  assert.equal(got[0].task, 'multi-05');
  assert.equal(recoverySubset(rows, [{ id: 'sales-03' }]).length, 0);
});

// ── 穿线占位（多轮评估批 change：carryCheck 实值接线，占位退役）──
test('crossCheckRows: 全单轮 → 空 rows + 如实注记（不编造）', () => {
  const got = crossCheckRows([{ task: 'a', turnVerdicts: ['pass'] }]);
  assert.equal(got.rows.length, 0);
  assert.match(got.note, /单轮/);
});

test('crossCheckRows: carry 一致 → 实值"一致"；未设锚多轮题如实标"未设穿线锚"', () => {
  const rows = [
    { task: 'multi-01', turnVerdicts: ['pass', 'pass', 'pass'], carry: { from: 1, keys: ['3,427'], results: [
      { turn: 2, key: 3427, status: 'silent' }, { turn: 3, key: 3427, status: 'consistent' }] } },
    { task: 'multi-05', turnVerdicts: ['pass', 'pass'] },
  ];
  const got = crossCheckRows(rows);
  assert.equal(got.rows[0].t2_ref_t1, '一致');
  assert.match(got.rows[0].note, /t2:silent,t3:consistent/);
  assert.equal(got.rows[1].t2_ref_t1, '未设穿线锚');
});

test('crossCheckRows: drift → "漂移(key→found@tN)" 形态', () => {
  const rows = [{ task: 'multi-03', turnVerdicts: ['pass', 'pass', 'pass', 'fail'],
    carry: { from: 3, keys: ['4,436'], results: [{ turn: 4, key: 4436, status: 'drift', found: 4437 }] } }];
  const got = crossCheckRows(rows);
  assert.equal(got.rows[0].t2_ref_t1, '漂移(4436→4437@t4)');
});

// ── 洞3 boundary ──
test('deriveBoundary: 题集构成计数 + 适用声明 + skipped 不计分母', () => {
  const tasks = [
    { id: 'a', set: 'dev' }, { id: 'b', set: 'dev' }, { id: 'c', set: 'frozen' },
  ];
  const b = deriveBoundary({ run_id: 'r1', tasks_git_hash: 'gh', snapshot_id: 'snap-1, snap-2' }, tasks, ['b']);
  assert.equal(b.run_id, 'r1');
  assert.deepEqual(b.snapshot_ids, ['snap-1', 'snap-2']);
  assert.equal(b.tasks_git_hash, 'gh');
  assert.deepEqual(b.set_composition, { dev: 1, frozen: 1, blind: 0, other: 0, total: 2 });
  assert.equal(b.conditional_skipped, 1);
  assert.match(b.statement, /仅适用于该快照/);
  assert.match(b.statement, /不可与历史基线直接对比/);
});

// ── 洞2 哈希 ──
test('sha256File + buildManifest: 复算一致、bytes 正确', () => {
  const dir = mkdtempSync(join(tmpdir(), 'evalmf-'));
  const p = join(dir, 'x.json');
  const content = JSON.stringify({ hello: '世界' });
  writeFileSync(p, content, 'utf-8');
  const expect = createHash('sha256').update(Buffer.from(content, 'utf-8')).digest('hex');
  const m = buildManifest([{ path: p, description: '测试产物' }], { run_id: 'r' });
  assert.equal(m.schema_version, 1);
  assert.equal(m.run_id, 'r');
  assert.equal(m.artifacts[0].sha256, expect);
  assert.equal(m.artifacts[0].bytes, Buffer.byteLength(content, 'utf-8'));
  assert.equal(m.artifacts[0].description, '测试产物');
  // 复算一致
  assert.equal(sha256File(p).sha256, m.artifacts[0].sha256);
  rmSync(dir, { recursive: true, force: true });
});

// ── 四 sheet 组装 + md 渲染 ──
test('buildSheets: 四 sheet + _boundary；renderMd 含 boundary 声明', () => {
  const rows = [
    { task: 'sales-07', dimension: '销量', score: 2, turnVerdicts: ['pass'], perTurnTruth: [], reasons: ['truth 缺锚: 46.15%'], truth: { checked: true, missing: ['46.15%'], forbidHits: [] }, cost: { tokens: { totalTokens: 46810 } } },
    { task: 'reviews-05', dimension: '口碑', score: 5, turnVerdicts: ['pass'], perTurnTruth: [], reasons: [], truth: { checked: true, missing: [], forbidHits: [] }, cost: { tokens: { totalTokens: 155184 } } },
  ];
  const tasks = [{ id: 'sales-07', set: 'frozen', dimension: '销量' }, { id: 'reviews-05', set: 'frozen', dimension: '口碑' }];
  const report = { run_id: 'r', tasks_git_hash: 'gh', snapshot_id: 'snap-x' };
  const { sheets, firstErrorFilled } = buildSheets(rows, tasks, report);
  assert.deepEqual(sheets.slice(0, 4).map((s) => s.name), ['总览', '逐轮衰减', '恢复成功率', '穿线验证']);
  assert.ok(sheets.find((s) => s.name === '_boundary'));
  assert.equal(firstErrorFilled, 1); // sales-07 派生出首错轮；reviews-05 通过为 null
  const s1 = sheets[0];
  assert.equal(s1.rows[0][7], 1); // 首错轮列 = t1
  assert.equal(s1.rows[1][7], '—');
  const md = renderMd(sheets);
  assert.match(md, /## 总览/);
  assert.match(md, /首错轮/);
  assert.match(md, /仅适用于该快照/);
});

// ── 洞1 calibration_log 完整性（truth 判分行为零变化的守卫）──
test('scoring-rules.json: 解析合法 + calibration_log 六字段齐全 + 判分键未动', () => {
  const rules = JSON.parse(readFileSync(resolve(ROOT, 'eval/scoring-rules.json'), 'utf-8'));
  // 既有判分键原样在
  assert.ok(rules.normalize && rules.wan_conversion && typeof rules.percent_unit_required === 'boolean');
  assert.ok(rules.tolerance_overrides['sales-03']); // 容差表未被回填动作触碰
  // 回填条目字段齐全
  assert.ok(Array.isArray(rules.calibration_log) && rules.calibration_log.length >= 3);
  for (const e of rules.calibration_log) {
    for (const k of ['date', 'change', 'before', 'after', 'reason', 'evidence']) assert.ok(e[k], `缺字段 ${k}`);
  }
  assert.match(rules._calibration_policy, /calibration_log/);
});

// ── Step7 审查补测（P1-3/P2-1/P2-3/P1-1）──

test('aggregateDecay: 多轮题 t<n 走 perTurnTruth 分支（P1-3 补测——本包核心新逻辑）', () => {
  const rows = [
    {
      task: 'multi-01', score: 5, turnVerdicts: ['pass', 'pass'],
      perTurnTruth: [{ turn: 1, missing: [], forbidHits: [] }], // t1 中；终轮无 truth 锚
      truth: { checked: false }, reasons: [],
    },
    {
      task: 'multi-02', score: 3, turnVerdicts: ['pass', 'pass'],
      perTurnTruth: [{ turn: 1, missing: ['2047'], forbidHits: [] }], // t1 缺锚
      truth: { checked: true, missing: [], forbidHits: [] }, reasons: ['truth[t1] 缺锚/违禁: 2047'],
    },
  ];
  const d = aggregateDecay(rows);
  assert.equal(d.length, 2);
  // t1：两题都在——multi-01 中、multi-02 缺
  assert.equal(d[0].total, 2);
  assert.equal(d[0].truthChecked, 2);
  assert.equal(d[0].truthHit, 1);
  // t2：两题都在（终轮）；truth 只查 multi-02（checked:true）且命中
  assert.equal(d[1].total, 2);
  assert.equal(d[1].truthChecked, 1);
  assert.equal(d[1].truthHit, 1);
});

test('firstErrorTurn: 脏条目（缺 turn 字段）不产 NaN（P2-1）', () => {
  const row = {
    score: 2, turnVerdicts: ['pass'],
    perTurnTruth: [{ missing: ['4436'] }], // 无 turn 字段
    reasons: [],
  };
  assert.notEqual(firstErrorTurn(row), NaN);
  assert.ok(firstErrorTurn(row) === null || Number.isInteger(firstErrorTurn(row)));
});

test('classifyRecovery: timeout 归"未完成（基础设施）"不误判附和（P2-3）', () => {
  assert.equal(classifyRecovery({ score: 0, reasons: ['timeout'] }), '未完成（基础设施）');
});

test('deriveBoundary: rows 驱动构成——以实际判分行为分母（P1-1）', () => {
  const tasks = [
    { id: 'a', set: 'dev' }, { id: 'b', set: 'frozen' }, { id: 'c', set: 'dev' }, { id: 'd', set: 'blind' },
  ];
  // 实际只跑了 a、c、d（b 因故无行）——rows 驱动应得 dev:2/frozen:0/blind:1/total:3，而非 tasks 口径的 total:4
  const rows = [{ task: 'a' }, { task: 'c' }, { task: 'd' }];
  const b = deriveBoundary({ run_id: 'r', tasks_git_hash: 'gh', snapshot_id: null }, tasks, [], rows);
  assert.deepEqual(b.set_composition, { dev: 2, frozen: 0, blind: 1, other: 0, total: 3 });
  // 无 rows 回退旧算法（tasks 减 skipped）
  const b2 = deriveBoundary({ run_id: 'r', tasks_git_hash: 'gh', snapshot_id: null }, tasks, ['b'], []);
  assert.deepEqual(b2.set_composition, { dev: 2, frozen: 0, blind: 1, other: 0, total: 3 });
});

// ── A 口径：可判集判定与拆分 ──
test('isAnchored: 陷阱/金标/rubric/多轮逐轮金标 任一存在即可判', () => {
  assert.equal(isAnchored({ trap_type: 'value_grounding' }), true);
  assert.equal(isAnchored({ truth: { anchors: ['4,436'] } }), true);
  assert.equal(isAnchored({ truth: { text_anchors: ['不存在'] } }), true);
  assert.equal(isAnchored({ truth: { forbid: ['20,000'] } }), true);
  assert.equal(isAnchored({ rubric_params: { kind: 'sentiment_pattern' } }), true);
  assert.equal(isAnchored({ turns: [{ message: 'q' }, { truth: { anchors: ['1'] } }] }), true);
  assert.equal(isAnchored({ question: 'q', judge_rubric: '只有人看的文字' }), false);
  assert.equal(isAnchored(undefined), false);
});

test('splitByAnchored: 通过率只算可判集，观测集单列', () => {
  const taskById = {
    a: { trap_type: 'value_grounding' },
    b: { truth: { anchors: ['1'] } },
    c: { judge_rubric: 'only text' },
    d: { judge_rubric: 'only text' },
  };
  const results = [
    { task: 'a', score: 5 }, { task: 'b', score: 0 },
    { task: 'c', score: 5 }, { task: 'd', score: 1 },
  ];
  const s = splitByAnchored(results, taskById);
  assert.deepEqual(s.anchored, { total: 2, pass: 1, pass_rate: 0.5, avg: 2.5 });
  assert.deepEqual(s.observational, { total: 2, pass: 1, pass_rate: 0.5, avg: 3 });
});

test('题库：新增 6 道锚点题均进入可判集', () => {
  const tasks = JSON.parse(readFileSync(resolve(ROOT, 'eval/tasks.json'), 'utf-8'));
  const byId = Object.fromEntries(tasks.map((t) => [t.id, t]));
  for (const id of ['sales-04', 'sales-11', 'sales-13', 'reviews-06', 'reviews-07', 'sentiment-08']) {
    assert.equal(isAnchored(byId[id]), true, `${id} 应有机器锚点`);
  }
});

// ── P0 链路：轨迹取行（runId 优先，sessionId/userId 兜底）──
test('pickTrajectory: runId+taskId+repeat 精确命中（同题多跑不串行）', () => {
  const entries = [
    { sessionId: 's1', evalRunId: 'run-A', evalTaskId: 'sales-01', evalRepeat: 1, userId: 'eval', verdict: 'fail' },
    { sessionId: 's2', evalRunId: 'run-B', evalTaskId: 'sales-01', evalRepeat: 2, userId: 'eval', verdict: 'pass' },
    { sessionId: 's3', evalRunId: 'run-B', evalTaskId: 'sales-01', evalRepeat: 3, userId: 'eval', verdict: 'fail' },
  ];
  const hit = pickTrajectory(entries, { runId: 'run-B', taskId: 'sales-01', repeat: 2, sid: 's3' });
  assert.equal(hit?.verdict, 'pass');
});

test('pickTrajectory: 登录门把 user_id 覆盖成 eval，也不影响 runId 取行', () => {
  const entries = [
    { sessionId: null, evalRunId: 'run-E', evalTaskId: 'sales-04', evalRepeat: 1, userId: 'eval', verdict: 'pass' },
  ];
  const hit = pickTrajectory(entries, { runId: 'run-E', taskId: 'sales-04', userId: 'eval_sales-04', repeat: 1 });
  assert.equal(hit?.verdict, 'pass');
});

test('pickTrajectory: 旧行无 evalRunId → sessionId 兜底；再退 userId', () => {
  const legacy = [
    { sessionId: 'old-1', userId: 'eval_x', verdict: 'pass' },
    { sessionId: 'old-2', userId: 'eval_y', verdict: 'fail' },
  ];
  assert.equal(pickTrajectory(legacy, { runId: 'run-new', taskId: 'x', userId: 'eval_x', sid: 'old-1' })?.verdict, 'pass');
  assert.equal(pickTrajectory(legacy, { runId: 'run-new', taskId: 'z', userId: 'eval_y' })?.verdict, 'fail');
  assert.equal(pickTrajectory(legacy, { runId: 'run-new', taskId: 'nope', userId: 'eval_z' }), null);
});

test('pickTrajectory: sessionId 断供也能按 runId 取到（10-26 断链回归）', () => {
  const entries = [
    { sessionId: null, evalRunId: 'run-C', evalTaskId: 'cross-01', userId: 'eval_cross-01', verdict: 'fail' },
  ];
  assert.equal(pickTrajectory(entries, { runId: 'run-C', taskId: 'cross-01', userId: 'eval_cross-01' })?.verdict, 'fail');
});

test('pickTrajectory: 同 run 不同题不得串行（runId 路径守 taskId）', () => {
  const entries = [
    { sessionId: null, evalRunId: 'run-D', evalTaskId: 't1', evalRepeat: 1, userId: 'eval', verdict: 'pass' },
  ];
  assert.equal(pickTrajectory(entries, { runId: 'run-D', taskId: 't2', repeat: 1 }), null);
});

// ── Pass@k（2026-10-29）──
test('passAtK: 同题 k 跑任一次通过即算该题通过，分母按题去重', () => {
  const rows = [
    { task: 'a', score: 2 }, { task: 'a', score: 4 }, { task: 'a', score: 1 },
    { task: 'b', score: 1 }, { task: 'b', score: 2 },
    { task: 'c', score: 5 },
  ];
  const r = passAtK(rows, 4);
  assert.equal(r.k, 3);
  assert.equal(r.tasks, 3);
  assert.equal(r.pass, 2);           // a、c 通过；b 全败
  assert.deepEqual(r.missed, ['b']);
  assert.equal(r.rate, 2 / 3);
});

test('passAtK: 空输入不除零，rate=null', () => {
  const r = passAtK([], 4);
  assert.equal(r.tasks, 0);
  assert.equal(r.rate, null);
  assert.equal(r.k, 0);
});

// ── 轨迹前缀对齐（2026-10-29 从 rescore 抽出：v7 题面错位事故的回归锚）──
test('matchTrajectoryRowByPrefix: reply 与 final_conclusion 双向前缀命中同一行', () => {
  const result = { reply_full: '海豚 8 月零售 16,879 辆，环比增长 3.2%。', question: '海豚 8 月销量' };
  const rows = [
    { sessionId: 's1', final_conclusion: '完全不同的一段结论', conversation: ['user: 别的问题'] },
    { sessionId: 's2', final_conclusion: '海豚 8 月零售 16,879 辆，环比增长 3.2%。补充说明。', conversation: ['user: 海豚 8 月销量'] },
  ];
  assert.equal(matchTrajectoryRowByPrefix(result, rows)?.sessionId, 's2');
});

test('matchTrajectoryRowByPrefix: 回复前缀不符 → 回退按题面对齐，不误配到别的行', () => {
  const result = { reply_full: '本条回复与轨迹末行不一致，长度超过四十个字符用于触发前缀不匹配的情况。', question: '海豚 8 月销量' };
  const rows = [
    { sessionId: 's1', final_conclusion: '另一题的结论', conversation: ['user: 其他题面'] },
    { sessionId: 's2', final_conclusion: '另一题的结论', conversation: ['user: 请分析海豚 8 月销量走势'] },
  ];
  assert.equal(matchTrajectoryRowByPrefix(result, rows)?.sessionId, 's2');
});

test('matchTrajectoryRowByPrefix: 题面为空时不得用空串误配第一行（原实现 includes("") 恒真）', () => {
  const result = { reply_full: '', question: '' };
  const rows = [{ sessionId: 's1', final_conclusion: '', conversation: ['user: 任意题面'] }];
  assert.equal(matchTrajectoryRowByPrefix(result, rows), null);
});

test('matchTrajectoryRowByPrefix: 完全无匹配 → null', () => {
  assert.equal(matchTrajectoryRowByPrefix({ reply_full: 'x', question: 'y' }, []), null);
});

// ── P0 链路：覆盖率闸 ──
test('computeCoverage: 只统计 settled 且无 error；缺行即不达标', () => {
  const results = [
    { task: 'a', settled: true, trajFound: true },
    { task: 'b', settled: true, trajFound: false },
    { task: 'c', settled: false, trajFound: false },
    { task: 'd', settled: true, trajFound: false, error: 'timeout' },
  ];
  const cov = computeCoverage(results, 1);
  assert.equal(cov.considered, 2);
  assert.equal(cov.covered, 1);
  assert.equal(cov.rate, 0.5);
  assert.deepEqual(cov.missing, ['b']);
  assert.equal(cov.ok, false);
});

test('computeCoverage: 全命中 → ok；分母为 0（全失败/全跳过）→ 无效', () => {
  assert.equal(computeCoverage([{ task: 'a', settled: true, trajFound: true }], 1).ok, true);
  assert.deepEqual(computeCoverage([], 1), { considered: 0, covered: 0, rate: 0, missing: [], ok: false });
  const allError = [{ task: 'a', settled: false, trajFound: false, error: 'timeout' }];
  assert.equal(computeCoverage(allError, 1).ok, false);
});

// ── 回归报警：与上一份报告比 ──
test('compareRuns: 稳定 → 不报警', () => {
  const cur = [{ task: 'a', score: 5 }, { task: 'b', score: 4 }];
  const base = [{ task: 'a', score: 5 }, { task: 'b', score: 4 }];
  const r = compareRuns(cur, base, { baselineRunId: 'b1' });
  assert.equal(r.alerted, false);
  assert.equal(r.task_overlap, 2);
  assert.deepEqual(r.alerts, []);
});

test('compareRuns: 整体通过率下滑 ≥5pp → 报警', () => {
  const cur = [{ task: 'a', score: 2 }, { task: 'b', score: 5 }];
  const base = [{ task: 'a', score: 5 }, { task: 'b', score: 5 }];
  const r = compareRuns(cur, base, { baselineRunId: 'b1' });
  assert.equal(r.alerted, true);
  assert.ok(r.alerts.some((a) => a.startsWith('pass_rate_drop')));
  assert.equal(r.pass_rate.current, 0.5);
  assert.equal(r.pass_rate.baseline, 1);
});

test('compareRuns: 单题均分下滑 ≥2 → 点名该题（含 repeat 均值）', () => {
  const cur = [{ task: 'a', score: 5 }, { task: 'a', score: 1 }]; // 均值 3
  const base = [{ task: 'a', score: 5 }, { task: 'a', score: 5 }];
  const r = compareRuns(cur, base, { baselineRunId: 'b1' });
  assert.equal(r.alerted, true);
  assert.deepEqual(r.regressed_tasks, [{ task: 'a', current: 3, baseline: 5, delta: -2 }]);
});

test('compareRuns: 连续失败（两轮都 <4）→ 报警，即使没有继续下滑', () => {
  const cur = [{ task: 'a', score: 2 }];
  const base = [{ task: 'a', score: 2 }];
  const r = compareRuns(cur, base, { baselineRunId: 'b1' });
  assert.deepEqual(r.consecutive_failures, ['a']);
  assert.ok(r.alerts.includes('still_failing:a'));
});

test('compareRuns: 无重叠 → 不报警（无可比基线）', () => {
  const r = compareRuns([{ task: 'x', score: 1 }], [{ task: 'y', score: 5 }], { baselineRunId: 'b1' });
  assert.equal(r.task_overlap, 0);
  assert.equal(r.alerted, false);
  assert.equal(r.pass_rate, null);
});
