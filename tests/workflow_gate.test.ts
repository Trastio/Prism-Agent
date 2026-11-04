/** 工作流状态门单测（登记收敛归档追加 2026-10-14）：两阶段协议执行层强制。 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decideWorkflowGate, TEMPLATE_B_MARKER } from '../src/shared/workflow-gate.ts';

const SCAN = 'scanning' as const;
const NAMED = 'named' as const;

test('scanning 态锁深挖工具：social_user_profile 被拦且带自纠指引', () => {
  const g = decideWorkflowGate(SCAN, 'social_user_profile', '{"platform":"douyin","user_id":"某人"}');
  assert.equal(g.block, true);
  assert.ok(g.reason.includes('候选人名单'));
});

test('scanning 态锁 social_user_posts', () => {
  const g = decideWorkflowGate(SCAN, 'social_user_posts', '{"platform":"douyin","user_id":"某人"}');
  assert.equal(g.block, true);
});

test('scanning 态不锁 social_search（扫描是本阶段本职）', () => {
  const g = decideWorkflowGate(SCAN, 'social_search', '{"platform":"douyin","keyword":"风云T7"}');
  assert.equal(g.block, false);
});

test('scanning 态锁模板 B 导出（含用户对照总览标记）', () => {
  const input = JSON.stringify({ filename: 'x.xlsx', sheets: [{ name: '用户对照总览', rows: [] }] });
  const g = decideWorkflowGate(SCAN, 'export_document', input);
  assert.equal(g.block, true);
  assert.ok(g.reason.includes('模板 B'));
});

test('scanning 态放行模板 A 导出（无对照总览标记）', () => {
  const input = JSON.stringify({ filename: 'x.xlsx', sheets: [{ name: '好评维度', rows: [] }] });
  const g = decideWorkflowGate(SCAN, 'export_document', input);
  assert.equal(g.block, false);
});

test('named 态解锁深挖工具与模板 B 导出', () => {
  assert.equal(decideWorkflowGate(NAMED, 'social_user_profile', '{}').block, false);
  const input = JSON.stringify({ sheets: [{ name: TEMPLATE_B_MARKER, rows: [] }] });
  assert.equal(decideWorkflowGate(NAMED, 'export_document', input).block, false);
});

test('idle 态全放行（未加载技能=门不介入）', () => {
  assert.equal(decideWorkflowGate('idle', 'social_user_profile', '{}').block, false);
  assert.equal(decideWorkflowGate('idle', 'export_document', '{"sheets":[{"name":"用户对照总览"}]}').block, false);
});
