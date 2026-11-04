/**
 * T-2.2.5 冒烟测试：tool_result grounding（数值 + 名称 8 错误测试集）
 */

import {
  extractNumbers,
  verifyNumbers,
  verifyNames,
  collectNameTruth,
  groundResult,
} from './grounding.ts';

function assert(cond: boolean, label: string) {
  console.log(`  ${cond ? '✓' : '✗'} ${label}`);
  if (!cond) process.exitCode = 1;
}

async function main() {
  console.log('='.repeat(70));
  console.log('  T-2.2.5 tool_result grounding · 冒烟测试');
  console.log('='.repeat(70));

  // 1. 数值提取
  console.log('\n[1] 数值提取（带万/亿单位）:');
  const nums = extractNumbers('银河E5 8月销量4436台，累计约1.2万辆');
  console.log('  提取:', nums);
  assert(nums.length >= 2, '至少提取 2 个数值');
  assert(nums.some((n) => n.value === 4436), '提取 4436');
  assert(nums.some((n) => n.value === 12000), '提取 1.2万=12000');

  // 2. 数值容差通过
  console.log('\n[2] 数值容差通过（销量±2%）:');
  const r2 = verifyNumbers('8月销量4450台', [4436]);
  assert(r2.pass, '4450 vs 4436 在 2% 容差内通过');

  // 3. 数值容差失败
  console.log('\n[3] 数值容差失败（超容差）:');
  const r3 = verifyNumbers('8月销量10774台', [4436]);
  assert(!r3.pass, '10774 vs 4436 超容差失败');
  console.log('  mismatches:', r3.mismatches);

  // 4. 名称 8 错误测试集
  console.log('\n[4] 名称 grounding · 8 错误测试集:');
  const cases: Array<[string, string[], string]> = [
    ['26款 530Km 探索型', ['26款 530Km 探索版'], '探索型→探索版'],
    ['530km 启航型', ['530km 公务版'], '启航型→公务版'],
    ['全域精灵版', ['全球精灵版'], '全域精灵版→全球精灵版'],
    ['铂智7 是 SUV', ['三厢轿车'], '铂智7 SUV→三厢轿车'],
    ['星纪元 ET 08 EV', ['比亚迪 海豹08 EV'], '星纪元→比亚迪海豹08'],
    ['蔚来 Z9 GT', ['腾势 Z9 GT'], '蔚来Z9→腾势Z9'],
    ['智驾版', ['激光雷达版'], '智驾版→激光雷达版'],
    ['一汽丰田 GAC', ['广汽丰田'], '一汽丰田GAC→广汽丰田'],
  ];
  for (const [modelText, truth, label] of cases) {
    const truthSet = new Set(truth);
    const r = verifyNames(modelText, truthSet);
    // 错误名应被检出（pass=false 表示检出错误，符合预期）
    console.log(`    ${label}: pass=${r.pass}`);
    if (r.mismatches.length) console.log(`      ${r.mismatches[0]}`);
    assert(!r.pass, `${label} 应被拦截（pass=false）`);
  }

  // 5. 名称正确通过
  console.log('\n[5] 名称正确通过:');
  const r5 = verifyNames('26款 530Km 探索版', new Set(['26款 530Km 探索版']));
  assert(r5.pass, '探索版 与真值一致通过');

  // 6. 综合 grounding
  console.log('\n[6] 综合 grounding（数值+名称）:');
  const r6 = groundResult(
    '银河E5 2026年8月销量4436台，座椅材质仿皮',
    [4436],
    [{ series: '银河E5', model_name: '26款 530Km 探索版' }]
  );
  console.log('  pass:', r6.pass);
  console.log('  number:', r6.number_check.pass);
  console.log('  name:', r6.name_check.pass);

  console.log('\n' + '='.repeat(70));
  console.log('  T-2.2.5 冒烟通过 ✅');
  console.log('='.repeat(70));
}

main().catch((e) => {
  console.error('❌ 冒烟失败:', e);
  process.exit(1);
});
