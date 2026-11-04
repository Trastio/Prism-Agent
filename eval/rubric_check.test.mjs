/**
 * 评估迭代基建包 · B2-1/B2-8 中间档判分正反例单测（rubric_check.mjs）
 *
 * 三类中间档（排序/缺口/舆情范式）+ artifact 插槽（L1-5 导出题定后启用）。
 * 纪律同 trap/truth：改判分规则必须先改本测试。
 * 运行：node --test eval/rubric_check.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { checkRubric } from './rubric_check.mjs';
import { writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

// ── 排序题：金标 top3 ⊆ 回答前5 或 首选=硬锚 ───────────────────────────────

const rankTask = {
  rubric_params: {
    kind: 'ranking',
    gold_top3: ['QQ3 EV', '熊猫mini', '凌宝BOX'],
    candidates: ['QQ3 EV', '熊猫mini', '凌宝BOX', '长安Lumin', '五菱缤果', '吉利几何E'],
  },
};

test('排序题：金标 top3 全部落在回答前5 → pass 不降档', () => {
  const reply = '销量排序：1. QQ3 EV（12,129），2. 熊猫mini，3. 凌宝BOX，4. 长安Lumin，5. 五菱缤果。';
  const r = checkRubric(rankTask, reply);
  assert.deepEqual([r.pass, r.cap, r.missing], [true, null, []]);
});

test('排序题：首选=硬锚直接 pass（即使后续散）', () => {
  const t2 = { ...rankTask, rubric_params: { ...rankTask.rubric_params, hard_first: 'QQ3 EV' } };
  const reply = '第一是 QQ3 EV。后面凌宝BOX、长安Lumin、五菱缤果、吉利几何E、熊猫mini。';
  const r = checkRubric(t2, reply);
  assert.equal(r.pass, true);
});

test('排序题：金标成员排到第6位之后 → fail 封顶2', () => {
  const reply = '排序：1. 长安Lumin 2. 五菱缤果 3. 吉利几何E 4. 熊猫mini 5. 凌宝BOX 6. QQ3 EV。';
  const r = checkRubric(rankTask, reply);
  assert.deepEqual([r.pass, r.cap], [false, 2]);
  assert.ok(r.missing.join().includes('QQ3 EV'));
});

test('排序题：金标成员完全未提及 → fail 封顶2', () => {
  const r = checkRubric(rankTask, '卖得最好的是长安Lumin，其次五菱缤果。');
  assert.equal(r.cap, 2);
});

test('排序题：缺 candidates/gold_top3 → fail-closed 封顶2（不静默放行）', () => {
  const r = checkRubric({ rubric_params: { kind: 'ranking', gold_top3: ['A'] } }, '回答');
  assert.deepEqual([r.pass, r.cap], [false, 2]);
});

test('排序题：候选名带品牌前缀、回复只写车型名 → 仍算命中（2026-11-01 修误报）', () => {
  const t = {
    rubric_params: {
      kind: 'ranking',
      gold_top3: ['比亚迪 元UP', '比亚迪 海豚', '启源Q05 纯电'],
      candidates: ['比亚迪 元UP', '比亚迪 海豚', '启源Q05 纯电', '零跑B01'],
      hard_first: '比亚迪 元UP',
    },
  };
  const reply = '首选：元UP 2025款 智驾版（11.98万）；其次海豚、启源Q05 纯电 也在这个价位。';
  const r = checkRubric(t, reply);
  assert.deepEqual([r.pass, r.cap, r.missing], [true, null, []]);
});

test('排序题：品牌前缀省略但名次靠后 → 仍按位置判 fail（不因归一而放宽）', () => {
  const t = {
    rubric_params: {
      kind: 'ranking',
      gold_top3: ['比亚迪 元UP'],
      candidates: ['零跑B01', '五菱缤果', '吉利几何E', '长安Lumin', '熊猫mini', '比亚迪 元UP'],
    },
  };
  const reply = '1 零跑B01 2 五菱缤果 3 吉利几何E 4 长安Lumin 5 熊猫mini 6 元UP。';
  const r = checkRubric(t, reply);
  assert.deepEqual([r.pass, r.cap], [false, 2]);
});

// ── 缺口题：方向词（假设/不可得）+ web URL +「不可复算」三要素 ───────────────

const gapTask = { rubric_params: { kind: 'gap' } };

test('缺口题：三要素齐全 → pass', () => {
  const reply =
    '库内无 800V 平台字段，此为数据缺口。假设（证据强度：弱）：参考懂车帝实测 https://www.dongchedi.com/auto/xyz 佐证，web 数据不可复算。';
  const r = checkRubric(gapTask, reply);
  assert.deepEqual([r.pass, r.cap, r.missing], [true, null, []]);
});

test('缺口题：缺 URL 与不可复算标记 → 封顶3，missing 列出', () => {
  const reply = '该字段库内不可得，走假设清单（证据强度：弱）。';
  const r = checkRubric(gapTask, reply);
  assert.equal(r.pass, false);
  assert.equal(r.cap, 3);
  assert.deepEqual(r.missing.sort(), ['url', '不可复算'].sort());
});

test('缺口题：三要素全缺 → 封顶2', () => {
  const r = checkRubric(gapTask, '这车有 800V 平台，充电很快。');
  assert.deepEqual([r.pass, r.cap], [false, 2]);
});

test('缺口题：direction_words 题级覆盖生效', () => {
  const t = { rubric_params: { kind: 'gap', direction_words: ['无PTC字段'] } };
  const ok = checkRubric(t, '库内无PTC字段；web 佐证 https://a.b/c（不可复算）。');
  assert.equal(ok.pass, true);
  const bad = checkRubric(t, '假设字段缺失；见 https://a.b/c（不可复算）。');
  assert.ok(bad.missing.includes('direction'));
});

test('缺口题：requires_web_source=false（库内缺口）→ 不要求 url/不可复算', () => {
  const t = { rubric_params: { kind: 'gap', requires_web_source: false } };
  const r = checkRubric(t, '库里没有这款车的配置采集数据，属于数据缺失，无法确认座椅/智驾明细。');
  assert.deepEqual([r.pass, r.cap, r.missing], [true, null, []]);
  // 未声明缺口 → 仍判缺 direction
  const bad = checkRubric(t, '这车座椅很舒服，智驾也不错。');
  assert.deepEqual([bad.pass, bad.missing], [false, ['direction']]);
});

// ── 舆情范式：五要素正则齐全度（声量规模/情感方向/负面主题/来源/as_of）──────

const senTask = { rubric_params: { kind: 'sentiment_pattern' } };
const senFull =
  '近30天风云T7 相关声量约 1,200 条；情感方向偏正面（正面 58%/负面 27%/中性 15%）。' +
  '负面主题集中在「续航虚标」吐槽（来源：抖音+微博为主）。数据时点 as_of 2026-10-11。';

test('舆情范式：五要素齐全 → pass', () => {
  const r = checkRubric(senTask, senFull);
  assert.deepEqual([r.pass, r.cap, r.missing], [true, null, []]);
});

test('舆情范式：缺负面主题与 as_of → 封顶3 并点名缺失', () => {
  const reply = '声量 1,200 条，情感方向偏正面（来源：抖音）。';
  const r = checkRubric(senTask, reply);
  assert.equal(r.cap, 3);
  assert.deepEqual(r.missing.sort(), ['负面主题', 'as_of'].sort());
});

test('舆情范式：仅命中来源 → 封顶2', () => {
  const r = checkRubric(senTask, '数据来源：抖音。');
  assert.deepEqual([r.pass, r.cap], [false, 2]);
  assert.equal(r.missing.length, 4);
});

// ── artifact 插槽（B2-8：L1-5 导出题定后启用，本 change 只留插槽+假题单测）────

test('artifact 插槽：假题（txt must_contain 命中）→ pass', () => {
  const dir = mkdtempSync(join(tmpdir(), 'prism-rubric-'));
  const p = join(dir, 'fake-export.txt');
  writeFileSync(p, '银河E5 口碑报告：舒适 con 占比最高（review_tags:7650/舒适/con）', 'utf-8');
  const t = { rubric_params: { kind: 'artifact', artifact: { kind: 'file', ext: 'txt', must_contain: ['银河E5', 'review_tags'] } } };
  const r = checkRubric(t, '已导出报告。', { artifactPath: p });
  assert.equal(r.pass, true);
  rmSync(dir, { recursive: true, force: true });
});

test('artifact 插槽：未交付/扩展名不符 → fail 封顶2', () => {
  const t = { rubric_params: { kind: 'artifact', artifact: { kind: 'file', ext: 'xlsx' } } };
  assert.deepEqual([checkRubric(t, '已导出。', {}).pass, checkRubric(t, '已导出。', {}).cap], [false, 2]);
  const dir = mkdtempSync(join(tmpdir(), 'prism-rubric-'));
  const p = join(dir, 'fake.txt');
  writeFileSync(p, 'x', 'utf-8');
  assert.equal(checkRubric(t, '已导出。', { artifactPath: p }).pass, false);
  rmSync(dir, { recursive: true, force: true });
});

// ── 边界 ─────────────────────────────────────────────────────────────────

test('无 rubric_params → checked:false 不比对；未知 kind → fail-closed 封顶2', () => {
  assert.equal(checkRubric({ id: 'x' }, '回答').checked, false);
  const r = checkRubric({ rubric_params: { kind: 'nonexistent' } }, '回答');
  assert.deepEqual([r.pass, r.cap], [false, 2]);
});

// ── 因果护栏（cross-05/06/07/08/10；红线：相关≠因果，不归因产品力）──────────
const causalTask = {
  rubric_params: {
    kind: 'causal_guard',
    elements: [
      { id: 'causal_disclaimer', re: '不能归因|不足以[^。\\n]{0,8}解释' },
      { id: 'alternative', re: '竞品|分流|价格' },
    ],
    forbid: ['(因为|由于)[^。\\n]{0,12}(产品力|配置)[^。\\n]{0,10}(导致|造成)[^。\\n]{0,10}销量'],
  },
};

test('因果护栏：要素齐全且无禁项 → pass 不降档', () => {
  const r = checkRubric(causalTask, '口碑短板不足以单独解释降幅，主因更可能是竞品分流与价格。');
  assert.deepEqual([r.pass, r.cap, r.missing], [true, null, []]);
});

test('因果护栏：缺 1 要素 → 封顶 4', () => {
  const r = checkRubric(causalTask, '口碑短板不足以单独解释降幅。');
  assert.deepEqual([r.pass, r.cap, r.missing], [false, 4, ['alternative']]);
});

test('因果护栏：命中因果禁项 → 一票封顶 2（即使要素齐全）', () => {
  const r = checkRubric(causalTask, '当然不能归因于竞品，因为产品力不足导致销量下滑。');
  assert.deepEqual([r.pass, r.cap], [false, 2]);
  assert.equal(r.forbidHits.length, 1);
});

test('因果护栏：缺参 fail-closed 封顶 2', () => {
  const r = checkRubric({ rubric_params: { kind: 'causal_guard' } }, '不能归因于竞品分流。');
  assert.deepEqual([r.pass, r.cap], [false, 2]);
});

// ── 通用要素判据（elements）：required 必中 + min_present 门槛 ─────────────
const elemTask = {
  rubric_params: {
    kind: 'elements',
    elements: [
      { id: 'a', re: '甲' },
      { id: 'b', re: '乙' },
      { id: 'c', re: '丙' },
      { id: 'd', re: '丁' },
    ],
    required: ['d'],
    min_present: 3,
  },
};

test('要素判据：required 命中且达到 min_present → pass', () => {
  const r = checkRubric(elemTask, '回答覆盖甲、乙、丁。');
  assert.deepEqual([r.pass, r.cap, r.missingRequired], [true, null, []]);
});

test('要素判据：缺 required → fail 封顶档位', () => {
  const r = checkRubric(elemTask, '回答覆盖甲、乙、丙。');
  assert.equal(r.pass, false);
  assert.deepEqual(r.missingRequired, ['d']);
});

test('要素判据：命中数不足 min_present → fail', () => {
  const r = checkRubric(elemTask, '只提甲、丁。');
  assert.equal(r.pass, false);
  assert.ok(r.missing.length >= 2);
});
