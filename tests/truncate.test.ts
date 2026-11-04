/**
 * 线B-工具截断单测（change: 线B-工具截断 T5）
 * 样本来自真实端点形态：series-list {ok,series:[{series,latest_retail,...}]}、
 * 舆情顶层数组、koubei data 嵌套对象。
 * 顺序契约（self-check Gap1）：截断 handler 必须注册在台账/名称采集 handler 之后——
 * 台账从全量抽取、模型上下文只进截断后载荷，本单测只验纯函数，顺序由 extension 注册位置保证。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { truncateToolResult } from '../src/shared/truncate.ts';

/** 造一个 ~N KB 的 series-list 形态样本（1149 行真实形态的模拟扩展；brand 供 dist 测试） */
function bigSeriesList(rows: number): string {
  const series = Array.from({ length: rows }, (_, i) => ({
    series: `测试车系${i}号`,
    brand: `品牌${i % 4}`,
    latest_retail: 3000 + i,
    has_retail: i % 3 !== 0,
    has_weighted: true,
  }));
  return JSON.stringify({ ok: true, series });
}

test('不超阈值原样返回（bypassNeeded=false）', () => {
  const small = JSON.stringify({ ok: true, series: [{ series: '银河E5', latest_retail: 1214 }] });
  const r = truncateToolResult(small);
  assert.equal(r.truncated, false);
  assert.equal(r.bypassNeeded, false);
  assert.equal(r.text, small);
});

test('series-list 大载荷：裁数组、保顶层键、附 _truncated', () => {
  const src = bigSeriesList(3000); // ~240KB
  const r = truncateToolResult(src, { maxChars: 20000, groupKey: 'brand' });
  assert.equal(r.truncated, true);
  assert.ok(r.text.length <= 22000, `输出应 ≤1.1×总帽，实际 ${r.text.length}`);
  const out = JSON.parse(r.text);
  // 顶层键保真：ok / series 均在
  assert.equal(out.ok, true);
  assert.ok(Array.isArray(out.series) && out.series.length > 0);
  assert.ok(out.series.length < 3000, '数组应被裁');
  // 裁掉的元素不进数组（标记在 _truncated，数组元素本身是纯数据）
  // _truncated 结构
  const t = out._truncated;
  assert.ok(t && t.total_chars_original === src.length);
  assert.ok(Array.isArray(t.arrays) && t.arrays.length >= 1);
  assert.ok(t.arrays[0].total === 3000);
  assert.ok(typeof t.hint === 'string' && t.hint.includes('截断'));
});

test('顶层数组形态（舆情端点）：尾插 _truncated 标记元素', () => {
  const arr = Array.from({ length: 5000 }, (_, i) => ({ id: `p${i}`, url: `https://x.com/${i}`, text: 'x'.repeat(60) }));
  const src = JSON.stringify(arr);
  // 审查 P1-1 回归：旁路路径必须经 marker 注入——顶层数组下二次 parse 注入会被
  // JSON.stringify(Array) 丢弃实例属性（隔离审查实证复现）
  const r = truncateToolResult(src, { maxChars: 20000, bypassPath: 'C:/tmp/bypass-test.json' });
  assert.equal(r.truncated, true);
  const out = JSON.parse(r.text);
  assert.ok(Array.isArray(out));
  const last = out[out.length - 1];
  assert.ok(last && typeof last === 'object' && '_truncated' in last);
  assert.equal(last._truncated.full_output_path, 'C:/tmp/bypass-test.json');
  // 保留元素的 url 键完整（保真名单：不删对象键）
  assert.ok(typeof out[0].url === 'string');
});

test('保真名单：_meta / as_of 顶层键不丢', () => {
  const rows = Array.from({ length: 2000 }, (_, i) => ({ row_id: i, v: `${i}月值`.repeat(8) }));
  const src = JSON.stringify({ rows, _meta: { as_of: '2026-10-12', source: 'prism' }, as_of: '2026-10-12' });
  const r = truncateToolResult(src, { maxChars: 20000 });
  const out = JSON.parse(r.text);
  assert.deepEqual(out._meta, { as_of: '2026-10-12', source: 'prism' });
  assert.equal(out.as_of, '2026-10-12');
});

test('groupKey 分布统计：被裁元素确定性 groupby', () => {
  const series = Array.from({ length: 1000 }, (_, i) => ({
    series: `车系${i}`,
    brand: `品牌${i % 4}`,
  }));
  const r = truncateToolResult(JSON.stringify({ series }), { maxChars: 10000, groupKey: 'brand' });
  const out = JSON.parse(r.text);
  const dist = out._truncated.dist;
  assert.ok(dist, '应有 dist');
  const flat = Object.values(Object.values(dist)[0] as Record<string, number>);
  assert.ok(flat.length >= 4, '四个品牌都应被统计到');
});

test('groupKey 无效（元素无该键）→ 省略 dist 不硬造', () => {
  const series = Array.from({ length: 1000 }, (_, i) => ({ series: `车系${i}` }));
  const r = truncateToolResult(JSON.stringify({ series }), { maxChars: 5000, groupKey: 'brand' });
  const out = JSON.parse(r.text);
  assert.equal(out._truncated.dist, undefined);
});

test('非 JSON 文本：head+tail 截断并带标记', () => {
  const src = 'a'.repeat(100000);
  const r = truncateToolResult(src, { maxChars: 20000 });
  assert.equal(r.truncated, true);
  assert.ok(r.text.includes('_TRUNCATED'));
  assert.ok(r.text.length < 20000);
  assert.ok(r.text.startsWith('a') && r.text.endsWith('a'));
});

test('嵌套数组（rows[].comments[]）递归裁剪', () => {
  const rows = Array.from({ length: 200 }, (_, i) => ({
    row_id: i,
    comments: Array.from({ length: 300 }, (_, j) => ({ c: `${i}-${j}`, t: 'x'.repeat(40) })),
  }));
  const src = JSON.stringify({ rows });
  const r = truncateToolResult(src, { maxChars: 20000 });
  assert.ok(r.text.length <= 22000, `嵌套裁后应达标，实际 ${r.text.length}`);
  const out = JSON.parse(r.text);
  assert.ok(out._truncated.arrays.length >= 1, '至少记录一个被裁数组');
});

test('dist 基数防护：高基数键（每行唯一）降级 top-20 + __other__/__distinct__', () => {
  // 回归：groupKey 配了每行唯一的键时，dist 曾膨胀到 55KB 炸穿预算（走 headTail 兜底）
  const series = Array.from({ length: 2000 }, (_, i) => ({ series: `唯一车系名${i}`, v: i }));
  const src = JSON.stringify({ series });
  const r = truncateToolResult(src, { maxChars: 20000, groupKey: 'series' });
  assert.ok(r.text.length <= 22000, `dist 降级后应达标，实际 ${r.text.length}`);
  const out = JSON.parse(r.text); // 必须仍是合法 JSON（未落 headTail）
  const dist = out._truncated.dist['series'];
  assert.ok(dist, 'dist 应存在');
  // 语义：dist 只统计被移除元素（kept 部分模型可见无需统计）
  const kept = out.series.length;
  assert.equal(dist.__distinct__, 2000 - kept);
  assert.ok(dist.__other__ >= 2000 - kept - 20, '__other__ = distinct - top20');
  const visibleKeys = Object.keys(dist).filter(k => !k.startsWith('__'));
  assert.ok(visibleKeys.length <= 20, `可见键应 ≤20，实际 ${visibleKeys.length}`);
});

test('回归（V4 实测缺陷）：多数组各自小于帽但总和超帽 → 必须裁且保持 JSON', () => {
  // 真实形态复刻：koubei data = specs 5.7K + provinces 15.7K + 小键 → 总 37.9K
  // 旧缺陷：逐数组独立判定 ≤20K 全放行 → 总量 27.6K 逃过裁剪 → headTail 丢结构
  const src = JSON.stringify({
    ok: true, model_id: '7650', series_name: '银河E5',
    specs: Array.from({ length: 11 }, (_, i) => ({ id: i, blob: 'x'.repeat(500) })),
    provinces: Array.from({ length: 30 }, (_, i) => ({ prov: `省${i}`, detail: 'y'.repeat(500) })),
    facts: { n: 123 }, tag_dist: { 舒适: { pro: 10, con: 20 } },
    stream: { rows: Array.from({ length: 12 }, (_, i) => ({ r: i, t: 'z'.repeat(400) })) },
  });
  const r = truncateToolResult(src, { maxChars: 20000 });
  assert.ok(r.text.length <= 21000, `多数组总量应收敛 ≤1.05×帽，实际 ${r.text.length}`);
  const out = JSON.parse(r.text); // 必须仍是合法 JSON（未落 headTail）
  assert.equal(out.ok, true);
  assert.equal(out.model_id, '7650');
  assert.ok(out._truncated.arrays.length >= 1, '至少一个数组被裁');
});

test('收敛循环：保底叠加导致的超帽由二轮收紧兜住', () => {
  // 构造多个数组把预算吃光后仍各自拿 2000 保底 → 一轮超帽 → 收敛循环压回
  const mk = (n: number, size: number) => Array.from({ length: n }, (_, i) => ({ i, b: 'q'.repeat(size) }));
  const src = JSON.stringify({ a: mk(30, 400), b: mk(30, 400), c: mk(30, 400), d: mk(30, 400) });
  const r = truncateToolResult(src, { maxChars: 20000 });
  assert.ok(r.text.length <= 21000, `实际 ${r.text.length}`);
  JSON.parse(r.text);
});
