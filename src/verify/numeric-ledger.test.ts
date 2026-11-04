/** 数字台账单测（M1 T-G2/G3）——归一化/排除/双信任级/换算桥接 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  normalizeNumber, extractProseTokens, valueVariants, ledgerHasValue,
  extractLedgerValues, looksLikeErrorPayload, readNumericLedger,
} from './numeric-ledger.ts';

test('normalizeNumber：三态同值（3.5 Gap3）', () => {
  assert.equal(normalizeNumber('−14.1%'), '14.1');   // unicode 负号 + %
  assert.equal(normalizeNumber('4,436 辆'), '4436');  // 千分位 + 单位
  assert.equal(normalizeNumber('4436'), '4436');      // 裸值
  assert.equal(normalizeNumber('14.10'), '14.1');     // 尾零
  assert.equal(normalizeNumber('0.692'), '0.692');
  assert.equal(normalizeNumber('约四千'), '');         // 非数值
});

test('normalizeNumber：浮点精度对齐（tp_avg 全精度 ↔ 台账 10 位）', () => {
  assert.equal(normalizeNumber('106754.66666666672'), '106754.6667');
  assert.equal(normalizeNumber('107366'), '107366');  // 整数不动
  const truth = new Set(['106754.6667', '107366']);
  assert.ok(ledgerHasValue(truth, '106754.66666666672'));  // 模型抄全精度值可命中
  assert.ok(ledgerHasValue(truth, '107366'));
});

test('extractProseTokens：年份/月份不触发（单位口径）', () => {
  const tokens = extractProseTokens('2026年8月销量 4,436 辆（环比 −14.1%），con_ratio 69.2%');
  const vals = tokens.map(t => t.value + (t.percent ? '%' : '') + (t.wan ? '万' : ''));
  assert.deepEqual(vals.sort(), ['14.1%', '4436', '69.2%']);
  // 2026/8 不得出现
  assert.ok(!tokens.some(t => t.value === '2026' || t.value === '8'));
});

test('换算桥接：百分桥与万桥（确定性变换）', () => {
  assert.deepEqual(valueVariants('69.2', true, false).sort(), ['0.692', '69.2']);
  assert.deepEqual(valueVariants('0.44', false, true).sort(), ['0.44', '4400']);
  const truth = new Set(['0.692', '4436']);
  assert.ok(ledgerHasValue(truth, '69.2', true));    // prose % ↔ 工具小数
  assert.ok(ledgerHasValue(truth, '4436'));
  assert.ok(!ledgerHasValue(truth, '9999'));
});

test('extractLedgerValues：标识符 key 排除（v1.4 P-b）', () => {
  const json = JSON.stringify({
    series_id: 7650, spec_id: 79310, model_id: 7650, vehicle_id: 99, year: 2026, month: 8,
    rows: [
      { model_id: 7650, tag_category: '舒适', pro_count: 150, con_count: 337, con_ratio: 0.692, net_attitude: -187 },
      { retail_sum: 4436, tp_avg: 10.08 },
    ],
  });
  const vals = extractLedgerValues(json);
  assert.ok(vals.includes('4436'));
  assert.ok(vals.includes('0.692'));
  assert.ok(vals.includes('150') && vals.includes('337'));
  assert.ok(!vals.includes('7650'));   // series_id/model_id 排除
  assert.ok(!vals.includes('79310'));  // spec_id 排除
  assert.ok(!vals.includes('2026') && !vals.includes('8'));  // year/month 排除
});

test('looksLikeErrorPayload：错误载荷识别（v1.5）', () => {
  assert.ok(looksLikeErrorPayload('错误: HTTP 502'));
  assert.ok(looksLikeErrorPayload('Atuohome 接口错误: HTTP 404'));
  assert.ok(looksLikeErrorPayload(JSON.stringify({ status: 'unavailable', reason: 'HTTP 502' })));
  assert.ok(!looksLikeErrorPayload(JSON.stringify({ rows: [{ retail_sum: 4436 }], _meta: { as_of: '2026-10-04' } })));
});

test('readNumericLedger：双信任级 union（v1.4 P-a）', () => {
  const entries = [
    { customType: 'prism-numeric-truth', data: { values: ['4436', '0.692'], kind: 'truth' } },
    { customType: 'prism-numeric-truth', data: { values: ['4436', '14.1'], kind: 'declared-derived' } },
    { customType: 'prism-name-truth', data: { names: ['银河E5'] } },  // 干扰项
  ];
  const ledger = readNumericLedger(entries);
  assert.deepEqual([...ledger.truth].sort(), ['0.692', '4436']);
  assert.deepEqual([...ledger.declaredDerived].sort(), ['14.1', '4436']);
  // declared-derived 不入 truth（E9 防洗白链的读取侧）
  assert.ok(!ledger.truth.has('14.1'));
});
