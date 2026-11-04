/**
 * 归因材料包单测（归因工具包 change，2026-10-16）
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { buildPack, prelimSignals } from './gen_attribution_pack.mjs';

test('prelimSignals: 四类信号候选分类，不下结论措辞', () => {
  assert.ok(prelimSignals(['市场侧归因产品力（越界）'])[0].includes('候选A堆'));
  assert.ok(prelimSignals(['市场侧归因产品力（越界）'])[0].includes('先读回复原文'));
  assert.ok(prelimSignals(['truth 缺锚: 46.15%'])[0].includes('候选B堆'));
  const mix = prelimSignals(['rubric[ranking] 缺要素: 比亚迪 海豚']);
  assert.ok(mix[0].includes('A/B混合'));
  assert.ok(prelimSignals(['timeout'])[0].includes('基础设施'));
  assert.deepEqual(prelimSignals([]), []);
});

test('buildPack: 节内材料齐全（题面/规则/明细/回复/信号）+ 旧报告降级提示', () => {
  const tasks = [{ id: 'sales-07', set: 'frozen', dimension: '销量', question: '银河E5卖的最好的是哪一款？', judge_rubric: '核心数字2047/46.15%', truth: { anchors: ['2047', '46.15%'] } }];
  const rows = [{
    task: 'sales-07', score: 2, reasons: ['truth 缺锚: 46.15%'],
    truth: { checked: true, missing: ['46.15%'], forbidHits: [] },
    first_error_turn: 1, verdict: 'pass', tools: ['resolve_series', 'query_sales'],
    replyPreview: '最畅销是探索版2047辆', cost: { tokens: { totalTokens: 46810 } },
  }];
  const md = buildPack(rows, tasks);
  assert.match(md, /## sales-07（frozen｜销量）· 2 分/);
  assert.match(md, /银河E5卖的最好/);
  assert.match(md, /46\.15/);
  assert.match(md, /旧报告无全文/); // 无 reply_full → 降级提示
  assert.match(md, /候选B堆/);
  // 有 reply_full 时不降级
  const md2 = buildPack([{ ...rows[0], reply_full: '全文在这里' }], tasks);
  assert.ok(md2.includes('全文在这里') && !md2.includes('旧报告无全文'));
});
