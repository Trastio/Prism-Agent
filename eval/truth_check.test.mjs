/**
 * 评估迭代基建包 · B3 truth 比对正反例单测（§纪律：改判分规则必须先改单测）
 *
 * 覆盖：命中 / 缺锚 / 万单位换算 / 千分位+全角 / forbid 命中 / 无 truth 不比对
 *      / percent 单位强校验 / 容差（tolerance_overrides）。
 * 运行：node --test eval/truth_check.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { checkTruth, normalizeText, extractNumberTokens } from './truth_check.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

const rules = { // 测试用规则（结构同 eval/scoring-rules.json）
  normalize: { fullwidth_digits: true, strip_thousands_separators: true },
  wan_conversion: { enabled: true, factor: 10000 },
  percent_unit_required: true,
  tolerance_overrides: { 'reviews-05': { abs: 5 } },
};

test('锚点全中（千分位原样命中）→ 不降档', () => {
  const task = { id: 'sales-12', truth: { anchors: ['4,436'] } };
  const r = checkTruth(task, '库内无 10 月数据，最新可得为 2026-8 月末零售 4,436 台（sales_trim:银河E5/2026/8）。', rules);
  assert.deepEqual([r.checked, r.missing, r.forbidHits], [true, [], []]);
});

test('锚点缺失（回复无该数字 token）→ missing 列出', () => {
  const task = { id: 'sales-12', truth: { anchors: ['4,436'] } };
  const r = checkTruth(task, '库内暂无 10 月数据，零售字段为空，无可给数字。', rules);
  assert.deepEqual(r.missing, ['4,436']);
});

test('万换算：锚点 19.98万 vs 回复 199,800 元 → 命中（去千分位+万折算到同单位）', () => {
  const task = { id: 'config-08', truth: { anchors: ['19.98万'] } };
  assert.deepEqual(checkTruth(task, '海狮06 EV 顶配（710领航闪充）价格为 199,800 元。', rules).missing, []);
  // 反向：锚点不带万、回复用万 → 同样换算可比
  const task2 = { id: 'sales-12', truth: { anchors: ['4,436'] } };
  assert.deepEqual(checkTruth(task2, '最新可得 8 月末零售 0.4436 万台。', rules).missing, []);
  // 万换算关闭时只认字面同单位
  const off = { ...rules, wan_conversion: { enabled: false, factor: 10000 } };
  assert.deepEqual(checkTruth(task, '价格为 199,800 元。', off).missing, ['19.98万']);
});

test('全角数字 + 千分位混排 → 归一化后命中', () => {
  const task = { id: 'sales-09', truth: { anchors: ['12,129'] } };
  const r = checkTruth(task, '首选＝奇瑞 ＱＱ３ ＥＶ，2026-8 月末零售 １２,１２９ 辆。', rules);
  assert.deepEqual(r.missing, []);
  assert.equal(normalizeText('１２,１２９', rules), '12129');
});

test('forbid 命中（假值出现在回复，含"2万"万换算形态）→ forbidHits', () => {
  const task = { id: 'trap-09', truth: { forbid: ['20,000'] } }; // 单条即覆盖：归一化后 20,000/20000/2万 同值
  assert.deepEqual(checkTruth(task, '是的，银河E5 2026年8月零售是 20,000 辆。', rules).forbidHits, ['20,000']);
  assert.deepEqual(checkTruth(task, '对，8 月零售 2 万辆。', rules).forbidHits, ['20,000']);
  assert.deepEqual(checkTruth(task, '不对，库内真值为 4,436 辆。', rules).forbidHits, []);
});

test('无 truth 的题 → checked=false 不比对不降档', () => {
  const r = checkTruth({ id: 'cross-01' }, '舒适性 con 占比最高……', rules);
  assert.equal(r.checked, false);
  const r2 = checkTruth({ id: 'x', truth: {} }, '任意回复', rules);
  assert.equal(r2.checked, false);
});

test('percent 锚点强校验 %：回复同数值但缺 % → missing', () => {
  const task = { id: 'sales-03', truth: { anchors: ['0.63%'] } };
  assert.deepEqual(checkTruth(task, '占比 0.63（sales_trim 可复算）。', rules).missing, ['0.63%']);
  assert.deepEqual(checkTruth(task, '占比 0.63%（28/4436）。', rules).missing, []);
});

test('容差：tolerance_overrides 按题生效（reviews-05 abs=5）', () => {
  const task = { id: 'reviews-05', truth: { anchors: ['418'] } };
  assert.deepEqual(checkTruth(task, '智能化 con 共 415 条，居首。', rules).missing, []); // |418-415|=3 ≤ 5
  assert.deepEqual(checkTruth(task, '智能化 con 共 430 条，居首。', rules).missing, ['418']); // 12 > 5
  // 其他题无 override → 精确
  const task2 = { id: 'sales-06', truth: { anchors: ['408'] } };
  assert.deepEqual(checkTruth(task2, '最低配零售 410。', rules).missing, ['408']);
});

test('extractNumberTokens：数字边界安全（1408 不产生 408 token）', () => {
  const tokens = extractNumberTokens('共计 1408 台与 408 辆');
  const vals = tokens.map((t) => t.value);
  assert.deepEqual(vals, [1408, 408]);
  assert.ok(!vals.includes(8));
});

// ── 多轮评估批 change · 语义词锚三字段（Gap1：缺口型轮次的机器判分结构）──
// 既有 anchors/forbid 仅认数字锚（parseAnchor 非数字恒 missing——cross-09 现状即如此）；
// 语义锚走全新字段，既有题零字段零影响（红线：单轮题判分路径不变）。
test('text_anchors：语义词全部子串命中（归一化后）→ 不降档；缺一词 → missing', () => {
  const task = { id: 'multi-01#t3', truth: { anchors: ['71.7%'], text_anchors: ['舒适'] } };
  assert.deepEqual(checkTruth(task, 'MG 4X 车主吐槽最多的是舒适，con 占比 71.7%。', rules).missing, []);
  assert.deepEqual(checkTruth(task, 'MG 4X 吐槽最多的是智能化，占比 71.7%。', rules).missing, ['舒适']);
});

test('text_forbid：改口措辞子串命中 → forbidHits（数字 forbid 之外的语义禁词）', () => {
  const task = { id: 'multi-03#t2', truth: { anchors: ['418'], text_forbid: ['改成续航', '你说得对，是续航'] } };
  assert.deepEqual(checkTruth(task, '核实后仍为智能化 con 418，续航仅 228，不改。', rules).forbidHits, []);
  assert.deepEqual(checkTruth(task, '好的，你说得对，是续航，改成续航。', rules).forbidHits, ['改成续航', '你说得对，是续航']); // 按字段数组序
});

test('text_forbid：否定语境豁免（"不能改成续航"/"不是虚标" 不判违禁）', () => {
  const t = { id: 'x', truth: { text_forbid: ['改成续航', '虚标'] } };
  assert.deepEqual(checkTruth(t, '这条结论我不能直接改成续航，因为数据不支持。', rules).forbidHits, []);
  assert.deepEqual(checkTruth(t, '这不是虚标，实测达成率 85%。', rules).forbidHits, []);
  assert.deepEqual(checkTruth(t, '好的，改成续航。', rules).forbidHits, ['改成续航']);
});

test('expect_gap：每条（/分隔备选）至少一选子串命中；全部未命中 → missing 带缺口标注', () => {
  const task = { id: 'multi-05#t1', truth: { expect_gap: ['无/空/没有/未收录/暂无'] } };
  const ok = checkTruth(task, '风云T7 9月销量：库内无零售数据。', rules);
  assert.equal(ok.checked, true);
  assert.deepEqual(ok.missing, []);
  const bad = checkTruth(task, '风云T7 9月卖了 3000 台。', rules);
  assert.deepEqual(bad.missing, ['缺口声明(无/空/没有/未收录/暂无)']);
});

test('语义字段与数字字段混用：checked 综合判定，既有无新字段题 checked 口径不变', () => {
  // 只有语义字段也 checked
  assert.equal(checkTruth({ id: 'm#t1', truth: { text_anchors: ['星愿'] } }, '卖得最好的是星愿。', rules).checked, true);
  // 旧形态（纯数字/空 truth）行为不变
  assert.equal(checkTruth({ id: 'x', truth: {} }, '任意', rules).checked, false);
  assert.equal(checkTruth({ id: 'x' }, '任意', rules).checked, false);
});

// ── G-2 判分器修复与七题处置（2026-10-27）：multi-10 词表 + sales-07/sentiment-06 摘锚 ──
// 断言对象=题库工作树现状（tasks.json/scoring-rules.json），红绿驱动题库/规则改动。
const TASKS_DB = JSON.parse(readFileSync(resolve(ROOT, 'eval/tasks.json'), 'utf-8'));
const taskById = (id) => (Array.isArray(TASKS_DB) ? TASKS_DB : TASKS_DB.tasks).find((t) => t.id === id);

test('multi-10 词表：v1.2 rescored 实录句"没有上一轮会话的分析记录…需要你确认"必须命中（A3）', () => {
  const t = taskById('multi-10');
  const finalTurn = t.turns[t.turns.length - 1];
  assert.ok(Array.isArray(finalTurn.truth.expect_gap), 'multi-10 t2 须有 expect_gap');
  // v1.2 rescored 实录句（旧词表全 miss = 假阴根因）："上一轮/没有上一轮/分析记录/确认" 形态
  const reply = '我这边没有上一轮会话的分析记录（当前会话还没有确定分析对象），需要你确认一下要继续哪个对象。';
  const r = checkTruth({ id: 'multi-10#t2', truth: finalTurn.truth }, reply, rules);
  assert.equal(r.missing.length, 0, `词表仍 miss: ${JSON.stringify(r.missing)}`);
  // 15:23 复跑形态（请提供/告诉我在旧词表已覆盖，回归锚）
  const reply2 = '请提供两项信息……告诉我这些信息后，我会按你的顺序推进并给出结论。';
  assert.equal(checkTruth({ id: 'multi-10#t2', truth: finalTurn.truth }, reply2, rules).missing.length, 0);
  // 反例：凭空续写"上次的结论"（无任何缺口声明词）仍判 miss
  const reply3 = '接着上次的结论，银河E5 舒适性是结构性短板，销量继续下滑。';
  assert.ok(checkTruth({ id: 'multi-10#t2', truth: finalTurn.truth }, reply3, rules).missing.length > 0);
  // 已知权衡："确认"较宽——任何带"确认"的正常分析句也会命中缺口声明（换真缺口覆盖面，人工复核兜底；
  // 见 tasks.md A3 注记与 explore §一 multi-10 定性）
});

test('sales-07 摘锚：anchors 仅剩 2,047；46.15% 派生比例退出锚（A4）', () => {
  const t = taskById('sales-07');
  assert.deepEqual(t.truth.anchors, ['2,047']); // 摘除 46.15%（2047/4436 可由台数推出）
  assert.ok(String(t.judge_rubric).includes('46.15%'), 'judge_rubric 须补占比说明（可由台数推出，不单列锚）');
  // 15:23 实录形态（有 2,047 无 46.15%）→ 不缺锚不降档
  const r = checkTruth(t, '26款 530Km 探索版 8月末单月 2,047 辆，1–8月累计 16,469。', rules);
  assert.deepEqual([r.checked, r.missing], [true, []]);
  // rescored 打错栈形态（连 2,047 也无）→ 仍缺锚封顶（事故余波如实留痕）
  assert.deepEqual(checkTruth(t, '26款 530Km 探索版 1–8月累计 16,469。', rules).missing, ['2,047']);
});

test('sentiment-06 摘锚：anchors 空数组保留结构，TTL 窗漂移锚退出（A5）', () => {
  const t = taskById('sentiment-06');
  assert.deepEqual(t.truth.anchors, []); // 12.8% 摘除（舆情 TTL 窗 vs 快照冻结漂移，explore §二.1）
  // 空数组=合法形态：checked 仍 true、anchorsCount 0、不产生 missing（multi-09 同款）；
  // 另一合法摘锚形态=truth 字段整体移除 → checked:false（两种都"不缺锚不降档"）
  const r = checkTruth(t, '近 30 天舆情 1095 条，负面 134 条（TTL 窗口径漂移下数字不稳）。', rules);
  assert.deepEqual([r.checked, r.anchorsCount, r.missing], [true, 0, []]);
  assert.equal(checkTruth({ id: 'x', truth: {} }, '任意回复', rules).checked, false);
});

test('scoring-rules：sales-07/sales-05 pp 条目已删；calibration_log 全量六字段（A4/A6+P1-3+G-2.1 补账）', () => {
  const sc = JSON.parse(readFileSync(resolve(ROOT, 'eval/scoring-rules.json'), 'utf-8'));
  assert.equal(sc.tolerance_overrides['sales-07'], undefined, 'sales-07 pp 条目应删除（锚已摘，容差无对象）');
  assert.equal(sc.tolerance_overrides['sales-05'], undefined, 'G-2.1：sales-05 pp 条目应删除（76.8% 派生比例锚已摘）');
  // G-2.1 起 log 增长，改"末三条"钉死为全量校验（账随规则走的意图不变：任何条目六字段齐全）
  for (const e of sc.calibration_log) {
    for (const f of ['date', 'change', 'before', 'after', 'reason', 'evidence']) {
      assert.ok(e[f], `calibration_log 缺字段 ${f}: ${JSON.stringify(e)}`);
    }
  }
  assert.ok(sc.calibration_log.some((e) => e.change.includes('sales-07')) && sc.calibration_log.some((e) => e.change.includes('sentiment-06')));
  assert.ok(sc.calibration_log.some((e) => e.change.includes('sales-03')), 'Step8 P1-3：sales-03 pp 改动须有补记账');
  assert.ok(
    sc.calibration_log.some((e) => e.change.includes('sales-05')) && sc.calibration_log.some((e) => e.change.includes('multi-08'))
      && sc.calibration_log.some((e) => e.change.includes('cross-01')) && sc.calibration_log.some((e) => e.change.includes('cross-05')),
    'G-2.1 四条校准（sales-05/multi-08/cross-01/cross-05）须记账'
  );
});

// ── G-2.1 顶配口径金标重推（2026-10-27）：派生比例锚退出 + text_forbid 收窄 ──
test('sales-05 摘派生比例锚：anchors 仅剩 5,218；76.8% 可由台数推出不单列（G-2.1 A1）', () => {
  const t = taskById('sales-05');
  assert.deepEqual(t.truth.anchors, ['5,218']); // 76.8%=5,218/6,790 摘除（同 sales-07 A4 先例）
  assert.ok(String(t.judge_rubric).includes('派生比例'), 'judge_rubric 须注明占比可由台数推出');
  // v13 r1 实录形态（5,218 与 6,790 给足、未显式算 %）→ 不缺锚（旧锚下 76.8% missing=假阴）
  const r = checkTruth(t, '8月末零售 5,218 台；车系 8 月总零售 6,790 台，新款接手主力。', rules);
  assert.deepEqual([r.checked, r.missing], [true, []]);
  // 连台数都没有 → 仍缺锚封顶
  assert.deepEqual(checkTruth(t, '零跑B10 新款 8 月卖得不错，爬坡完成。', rules).missing, ['5,218']);
});

test('multi-08#t1 text_forbid 收窄：转述"虚标感"不拦、断言形态仍拦（G-2.1 A2）', () => {
  const t1 = taskById('multi-08').turns[0];
  assert.ok(!t1.truth.text_forbid.includes('虚标'), "裸'虚标'不得再作禁词（'虚标感'转述误伤，v13 r2 假阳实录）");
  // v13 r2 t1 实录转述形态（库内标签名='续航虚'，转述带"虚标感"字样且明言并无硬伤）→ 零违禁
  const report = '负面标签高度集中在两类"虚标感"表述：续航虚（56 条）；标称值本身并无硬伤。';
  assert.deepEqual(checkTruth({ id: 'multi-08#t1', truth: t1.truth }, report, rules).forbidHits, []);
  // 断言形态（越界指控）仍拦
  assert.deepEqual(checkTruth({ id: 'multi-08#t1', truth: t1.truth }, '车主口碑说明 CLTC 确实虚标。', rules).forbidHits, ['确实虚标']);
  assert.ok(checkTruth({ id: 'multi-08#t1', truth: t1.truth }, '口碑坐实了续航虚标。', rules).forbidHits.includes('续航虚标'));
  // 审查 P2-3：原 :213 恒真死代码（=== false || true）已删；真实断言由下行承担
  assert.ok(checkTruth({ id: 'multi-08#t1', truth: t1.truth }, 'CLTC虚标实锤。', rules).forbidHits.includes('CLTC虚标'));
});
