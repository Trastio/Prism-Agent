/**
 * T-2.3 验证层 · M3 综合冒烟
 * - T-2.3.2 完成验证器（CLAIM/VERIFY + 越界检查）
 * - T-2.3.3 口碑定性结论（claim 溯源 + 抽检）
 * - T-2.3.4 真值校验（多重集容差比对）
 */

import { verifyCompletion } from './completion.ts';
import { buildKoubeiClaim, sampleForAudit, formatAuditReport, type AuditRecord } from './koubei_claims.ts';
import { getSalesTruth, getReviewsTruth, compareMultiset, extractNumbersFromText } from './reference.ts';
import { readFileSync } from 'node:fs';
import { resolve as _resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

function assert(cond: boolean, label: string) {
  console.log(`  ${cond ? '✓' : '✗'} ${label}`);
  if (!cond) process.exitCode = 1;
}

// P0-#31 断言分组：环境敏感真值期望外置（eval/truth-expectations.json）；缺文件/缺键回退内联当前值
// 路径相对本文件解析（审查 P2#9：cwd 相对路径在非项目根运行时静默回退旧值）
const EXPECT_PATH = _resolve(fileURLToPath(import.meta.url), '../../eval/truth-expectations.json');
function loadExpect(): Record<string, any> {
  try {
    return JSON.parse(readFileSync(EXPECT_PATH, 'utf-8'));
  } catch {
    return {};
  }
}
const EXPECT = loadExpect();

async function main() {
  console.log('='.repeat(70));
  console.log('  T-2.3 验证层 · M3 综合冒烟');
  console.log('='.repeat(70));

  // 1. 完成验证器：合法 CLAIM 通过
  console.log('\n[1] 完成验证器 · 合法 CLAIM:');
  const r1 = verifyCompletion('s1', {
    conclusion_text: '舒适是 E5 口碑中 con 占比最高的维度',
    supported_by: ['review_tags:7650/舒适/con'],
    as_of: '2026-10-03',
    scope: '口碑内',
  });
  console.log('  pass:', r1.pass, 'failures:', r1.failures);
  assert(r1.pass, '合法 CLAIM 通过');

  // 2. 完成验证器：越界 fail（报告① v0.2 错误）
  console.log('\n[2] 完成验证器 · 越界（市场侧印证舒适性）:');
  const r2 = verifyCompletion('s2', {
    conclusion_text: '舒适性是结构性短板，销量下滑印证了这一结论',
    supported_by: ['review_tags:7650/舒适/con', 'sales_trim:银河E5/2026/8月末'],
    as_of: '2026-10-03',
    scope: '口碑内',
  });
  console.log('  pass:', r2.pass, 'failures:', r2.failures);
  assert(!r2.pass, '口碑越界到市场侧应 fail');
  assert(r2.can_continue, '首次失败允许 continuation');

  // 3. 完成验证器：无 supported_by fail
  console.log('\n[3] 完成验证器 · 无 supported_by（报告③ v0.2 错误）:');
  const r3 = verifyCompletion('s3', {
    conclusion_text: '铂智7X 在东北卖得好',
    supported_by: [],
    as_of: '2026-10-03',
    scope: '市场侧不归因',
  });
  console.log('  pass:', r3.pass, 'failures:', r3.failures);
  assert(!r3.pass, '无 supported_by 应 fail');

  // 4. 完成验证器：数据缺口未声明
  console.log('\n[4] 完成验证器 · 数据缺口未声明:');
  const r4 = verifyCompletion('s4', {
    conclusion_text: '铂智7X 配置档次中低端',
    supported_by: ['config_snapshots:7650/79311'],
    as_of: '2026-10-03',
    scope: '配置内',
  }, { owner_reviews: { hit: false }, series_summaries: { hit: false } });
  console.log('  pass:', r4.pass, 'failures:', r4.failures);
  assert(!r4.pass, '数据缺口未声明应 fail');

  // 5. 口碑定性结论
  console.log('\n[5] 口碑定性结论 · claim 溯源 + 抽检:');
  const claims = [
    buildKoubeiClaim('舒适 con 69.2%', ['review_tags:7650/舒适/con'],
      [{ review_id: 'k_5789427', source_text: '颠簸', tag_name: '舒适性差' }], 0.925),
    buildKoubeiClaim('智能化 con 47.4%', ['review_tags:7650/智能化/con'],
      [{ review_id: 'k_x', source_text: '车机卡', tag_name: '智能化差' }], 0.925),
  ];
  const sampled = sampleForAudit(claims, 0.5, 1);
  console.log('  抽样:', sampled.length, '条');
  const records: AuditRecord[] = sampled.map((c) => ({
    claim_conclusion: c.conclusion,
    review_id: c.sample_reviews[0].review_id,
    source_text: c.sample_reviews[0].source_text,
    result: 'pass' as const,
  }));
  const report = formatAuditReport(records);
  console.log('  报告生成:', report.split('\n').length, '行');
  assert(sampled.length > 0, '抽检抽样非空');

  // 6. 真值校验
  console.log('\n[6] 真值校验 · E5 2026 销量多重集比对:');
  const truth = getSalesTruth('银河E5', 2026);
  console.log('  真值:', truth);
  const first3: number[] = EXPECT.sales_e5_2026_first3 ?? [3028, 1823, 6508];
  const agentText = `2026年1月${first3[0]}台，2月${first3[1]}台，3月${first3[2]}台`;
  // 过滤掉年份（2020-2030）和过小数值
  const actual = extractNumbersFromText(agentText).filter((n) => n > 1000 && (n < 2020 || n > 2030));
  console.log('  agent 回复数值:', actual);
  const cmp = compareMultiset(truth.slice(0, 3), actual, 0.02);
  console.log('  pass:', cmp.pass, 'mismatches:', cmp.mismatches);
  assert(cmp.pass, '销量真值校验通过');

  console.log('\n[7] 真值校验 · E5 口碑维度真值:');
  const revTruth = getReviewsTruth(7650);
  const comfort = revTruth['舒适'];
  console.log('  舒适:', comfort);
  const expectCon: number = EXPECT.koubei_e5_comfort_con ?? 313;
  assert(comfort.con === expectCon, `舒适 con_count=${expectCon}（期望外置 truth-expectations.json；2026-10-08 新库口径 313，旧库 337）`);

  console.log('\n' + '='.repeat(70));
  console.log('  T-2.3 M3 冒烟通过 ✅');
  console.log('='.repeat(70));
}

main().catch((e) => {
  console.error('❌ 冒烟失败:', e);
  process.exit(1);
});
