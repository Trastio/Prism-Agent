/** harness 登记收敛（2026-10-13）单测：真值信封收割 + 注册漂移检查 + 前缀对账。
 * 框架：node:test（Node 内置）。运行：node --test --import tsx tests/truth_envelope.test.ts */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { harvestTruth, collectRegistrationDrift } from '../src/shared/truth-envelope.ts';

// ---------------- harvestTruth ----------------

test('harvestTruth: compare_configs_valued 形态（cells 字符串数字/概念名/车系名）', () => {
  const data = {
    rows: [
      { id: 'A1', name: 'CLTC纯电续航', param: 'CLTC纯电续航里程(km)', cells: ['410', '405'], price: 0 },
      { id: 'F1', name: '座椅材质', cells: ['仿皮', '织物'] },
    ],
    cols: [
      { model_id: '6139', spec_id: '71048', series_name: '海豚', trim_name: '自由版', msrp: 99800 },
      { model_id: '6762', spec_id: '77748', series_name: '海鸥', trim_name: '活力版' },
    ],
  };
  const t = harvestTruth(data);
  assert.ok(t.numbers.includes('410') && t.numbers.includes('405'));
  assert.ok(t.numbers.includes('0') === false || true); // price 0 可在可不在，不作断言
  assert.ok(t.numbers.includes('99800'));
  assert.ok(t.names.includes('CLTC纯电续航') && t.names.includes('座椅材质'));
  assert.ok(t.names.includes('海豚') && t.names.includes('海鸥'));
  assert.ok(t.names.includes('自由版') && t.names.includes('活力版'));
});

test('harvestTruth: get_config_detail 同源形态 + "15.4英寸" 前导数值', () => {
  const data = {
    rows: [{ id: 'G1', name: '中控屏尺寸', cells: ['15.4英寸', '缺采'] }],
    cols: [{ series_name: '银河E5' }],
  };
  const t = harvestTruth(data);
  assert.ok(t.numbers.includes('15.4'));
  assert.ok(t.names.has === undefined); // 返回数组非 Set
  assert.ok(t.names.includes('中控屏尺寸') && t.names.includes('银河E5'));
  assert.ok(!t.numbers.includes('缺采'));
});

test('harvestTruth: get_trims 形态（trims[].name/price）', () => {
  const t = harvestTruth({ trims: [{ name: '海豚 2025款 智驾版 420km 自由版', price: '9.98万', spec_id: '71048' }] });
  assert.ok(t.names.some((n) => n.includes('自由版')));
  assert.ok(t.numbers.includes('9.98'));
});

test('harvestTruth: 空响应/残缺响应返回空集不崩', () => {
  assert.deepEqual(harvestTruth(null), { numbers: [], names: [] });
  assert.deepEqual(harvestTruth({}), { numbers: [], names: [] });
  assert.deepEqual(harvestTruth({ rows: 'oops' }).numbers, []);
});

// ---------------- collectRegistrationDrift ----------------

test('collectRegistrationDrift: 健康登记零漂移', () => {
  const drift = collectRegistrationDrift(['a', 'b', 'c'], ['a', 'b'], ['a', 'c'], 2);
  assert.deepEqual(drift, []);
});

test('collectRegistrationDrift: 截断表/白名单缺员与技能空各自上报', () => {
  const drift = collectRegistrationDrift(['a'], ['a', 'x'], ['a', 'y'], 0);
  assert.ok(drift.some((d) => d.includes('截断表缺注册:x')));
  assert.ok(drift.some((d) => d.includes('业务白名单缺注册:y')));
  assert.ok(drift.some((d) => d.includes('技能目录')));
});

// ---------------- 前缀对账（M2 前缀断裂教训防回归） ----------------

test('前缀对账：extension 与 ChatView 的保底通知前缀字面量一致', () => {
  const ext = readFileSync(new URL('../.pi/extensions/prism-guardrails/index.ts', import.meta.url), 'utf-8');
  const web = readFileSync(new URL('../prism-web/src/components/ChatView.tsx', import.meta.url), 'utf-8');
  const shared = readFileSync(new URL('../src/shared/verifier-prefix.ts', import.meta.url), 'utf-8');
  assert.ok(shared.includes("'[完成验证器'"), '单源常量文件须含前缀字面量');
  assert.ok(ext.includes("[完成验证器") || ext.includes('VERIFIER_NOTICE_PREFIX'), 'extension 引用前缀');
  assert.ok(web.includes("'[完成验证器'"), 'ChatView 过滤前缀须与 extension 同字面量');
  // 双侧都不得引入带闭括号的脆匹配（M2 事故形态）
  assert.ok(!web.includes("startsWith('[完成验证器·保底]'"));
});

// ---------------- Step8 隔离审查修复回归（P1-1/P1-2/P2-4） ----------------

test('harvestTruth: diff 段金额入真值集（P1-1：config_adv/flat_adv/逐项金额）', () => {
  const data = {
    rows: [{ id: 'A1', name: 'CLTC纯电续航', cells: ['410', '405'] }],
    cols: [{ series_name: '海豚' }],
    diff: {
      columns: [{ k: 1, amount: -4300 }],
      items: { A1: { verdict: '少', amount: -500 }, F10: { verdict: '同', amount: 0 } },
      config_adv: -4300,
      flat_adv: 5700,
    },
  };
  const t = harvestTruth(data);
  assert.ok(t.numbers.includes('-4300') && t.numbers.includes('5700'));
  assert.ok(t.numbers.includes('-500'));
  assert.ok(t.numbers.includes('410'));
});

test('harvestTruth: 区间价两端都收 + 千分位不断章（P1-2）', () => {
  const t = harvestTruth({
    cols: [{ series_name: 'X', msrp: '11.98-14.98万' }],
    rows: [{ id: 'G6', name: 'USB', cells: ['1,234'] }],
  });
  assert.ok(t.numbers.includes('11.98') && t.numbers.includes('14.98'), '区间两端都要在');
  assert.ok(t.numbers.includes('1234') && !t.numbers.includes('1,') , '千分位去逗号整体入账');
});

test('collectRegistrationDrift: 真值发射方不在业务白名单要报（P2-4）', () => {
  const drift = collectRegistrationDrift(
    ['a', 'b', 'ghost_tool'], ['a'], ['a', 'b'], 2, ['ghost_tool']);
  assert.ok(drift.some(d => d.includes('真值发射方不在业务白名单:ghost_tool')));
  const ok = collectRegistrationDrift(['a', 'b'], ['a'], ['a', 'b'], 2, ['a']);
  assert.equal(ok.length, 0);
});
