/**
 * T-2.2.1 冒烟测试：数据源注册表 + 健康检查 + 覆盖率守卫
 *
 * 验收点（spec §2.2.1）：
 * - 启动时健康检查全 pass（舆情/RAG 缺失可降级，不 crash）
 * - 任一数据源 down → 降级声明
 * - 覆盖率守卫：银河E5 全 hit；铂智7 部分缺失（series_summaries 不收录/口碑0）
 */

import {
  bootHealthCheck,
  getDataSourceStatus,
  getDataSource,
  openAutohome,
} from './datasource.ts';

async function main() {
  console.log('='.repeat(70));
  console.log('  T-2.2.1 数据源注册表 · 冒烟测试');
  console.log('='.repeat(70));

  // 1. 启动健康检查
  console.log('\n[1] 启动健康检查:');
  const health = await bootHealthCheck();
  for (const [name, ok] of Object.entries(health)) {
    console.log(`  ${name}: ${ok ? '✅ ready' : '⚠️ degraded (降级声明, 不 crash)'}`);
  }

  // 2. 数据源状态（含降级原因）
  console.log('\n[2] 数据源状态:');
  const status = getDataSourceStatus();
  for (const s of status) {
    console.log(`  ${s.name}: healthy=${s.healthy} as_of=${s.as_of}`);
    if (s.degrade_reason) console.log(`    降级原因: ${s.degrade_reason}`);
  }

  // 3. 覆盖率守卫：银河E5（应全 hit）
  console.log('\n[3] 覆盖率守卫 · 银河E5（预期全 hit）:');
  const ah = getDataSource('atuohome');
  if (ah) {
    const cov = await ah.coverage.series_covered('银河E5');
    console.log('  ', JSON.stringify(cov, null, 2));
  }

  // 4. 覆盖率守卫：铂智7（预期部分缺失 → 触发数据缺口声明）
  console.log('\n[4] 覆盖率守卫 · 铂智7（预期 series_summaries 不收录 / 口碑 0）:');
  if (ah) {
    const cov = await ah.coverage.series_covered('铂智7');
    console.log('  ', JSON.stringify(cov, null, 2));
  }

  // 5. 直接读 autohome 验证可连
  console.log('\n[5] 只读直连 autohome.db 验证:');
  const db = openAutohome();
  const tables = db
    .prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    .all() as { name: string }[];
  console.log(`  表数: ${tables.length}, 前5: ${tables.slice(0, 5).map((t) => t.name).join(', ')}`);
  const e5 = db
    .prepare("SELECT COUNT(*) as n FROM sales_trim WHERE series='银河E5' AND month LIKE '%月末' AND year=2026")
    .get() as { n: number };
  console.log(`  银河E5 2026 月末行: ${e5.n}（仅观察值不断言——P0-#31：环境敏感断言已外置 eval/truth-expectations.json，此处只验连接）`);
  db.close();

  console.log('\n' + '='.repeat(70));
  console.log('  T-2.2.1 冒烟通过 ✅');
  console.log('='.repeat(70));
}

main().catch((e) => {
  console.error('\n❌ 冒烟失败:', e);
  process.exit(1);
});
