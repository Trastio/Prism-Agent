/**
 * prism-guardrails · 验证层新判据 smoke（M2 改道后重写）
 *
 * 历史回归语义保留：2026-10-04 原始误报用例（问候语含维度词 → 被旧粗筛判分析 → 回灌）
 * 与 2026-10-07"复述真数字被误拦"用例，映射到新判据——数字台账（有出处放行/无出处拦截）。
 *
 * 运行：npm run smoke:guard
 * 本文件不是扩展入口，pi 只自动发现 index.ts，不会被加载。
 */

import extensionFactory, {
  isVerifierRetryTurn,
  lastUserMessageText,
  KNOWN_BUSINESS_TOOLS,
  TOOL_CATEGORIES,
  decideTier,
  NUMERIC_CLAIM_RE,
  PI_WEB_ACCESS_TOOLS,
  evalToday,
  type BranchEntry,
} from './index.ts';
import { extractProseTokens, ledgerHasValue, readNumericLedger } from '../../../src/verify/numeric-ledger.ts';

// 扩展入口契约：pi 只认默认导出的 factory 函数
if (typeof extensionFactory !== 'function') {
  console.error('  ✗ index.ts 默认导出不是 factory 函数，pi 将无法加载扩展');
  process.exit(1);
}

let pass = 0;
let fail = 0;

function check(name: string, actual: unknown, expected: unknown): void {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    pass++;
    console.log(`  ✓ ${name}`);
  } else {
    fail++;
    console.log(`  ✗ ${name}\n      期望 ${JSON.stringify(expected)}\n      实得 ${JSON.stringify(actual)}`);
  }
}

// ---------------------------------------------------------------------------
// 1. 数字形态门（NUMERIC_CLAIM_RE）——问候语含维度词不算数字结论（2026-10-04 原始误报）
// ---------------------------------------------------------------------------
console.log('\n[1] 数字形态门');

const GREETING =
  'Hi! 我是 Prism-Agent。我可以做：车系三维度分析——配置 → 口碑 → 销量；' +
  '口碑走 owner_reviews + 标签表；舆情是外挂第四组。完整参考答案见文档。';
check('问候语含维度词、无度量数字 → 不触发（2026-10-04 误报用例）', NUMERIC_CLAIM_RE.test(GREETING), false);

const RESTATE =
  '你好！我是 Prism-Agent。刚才这个会话里我已经做过：查了银河E5 2026年8月销量 = 4,436 辆（环比 −14.1%）。';
check('复述真数字（原 2026-10-07 事故文本）→ 触发数字形态（进保底②台账判定）', NUMERIC_CLAIM_RE.test(RESTATE), true);

check('年份/月份不触发（"2026年8月"非度量结论）', NUMERIC_CLAIM_RE.test('银河E5于2026年8月上市，价格适中'), false);

// ---------------------------------------------------------------------------
// 2. 保底②台账判定（新判据核心：有出处放行 / 无出处拦截）
// ---------------------------------------------------------------------------
console.log('\n[2] 保底②台账判定');

const LEDGER = {
  truth: new Set(['4436', '5162', '106754.6667', '0.692']),
  declaredDerived: new Set(['14.1', '58.8']),
};
const RESTATED_TOKENS = extractProseTokens(RESTATE);
check(
  '复述：全部 token 在②判定集（truth∪derived）→ 放行',
  RESTATED_TOKENS.every(t => ledgerHasValue(new Set([...LEDGER.truth, ...LEDGER.declaredDerived]), t.value, t.percent, t.wan)),
  true,
);
const FABRIC_TOKENS = extractProseTokens('银河E5 2026年8月销量 12,345 辆，环比增长 300%');
check(
  '编造：存在 token 不在②判定集 → 拦截',
  FABRIC_TOKENS.some(t => !ledgerHasValue(new Set([...LEDGER.truth, ...LEDGER.declaredDerived]), t.value, t.percent, t.wan)),
  true,
);
check('百分比桥：prose 69.2% 命中工具 0.692', ledgerHasValue(LEDGER.truth, '69.2', true), true);
check('洗白链：declared-derived 不入 truth（读取侧）', readNumericLedger([
  { customType: 'prism-numeric-truth', data: { values: ['14.1'], kind: 'declared-derived' } },
]).truth.has('14.1'), false);

// ---------------------------------------------------------------------------
// 3. 回灌识别与链起点（乒乓修复的判据基础）
// ---------------------------------------------------------------------------
console.log('\n[3] 回灌识别');

check('验证器回灌消息 → 识别为 retry 轮', isVerifierRetryTurn('[完成验证器·保底] 本轮含库数据数字结论…'), true);
check('真实用户消息 → 非 retry 轮', isVerifierRetryTurn('银河E5 8月销量多少？'), false);

const BRANCH: BranchEntry[] = [
  { type: 'message', message: { role: 'user', content: '银河E5 8月销量多少？' } },
  { type: 'message', message: { role: 'assistant', content: [{ type: 'text', text: '4,436 台' }] } },
  { type: 'message', message: { role: 'user', content: '[完成验证器·保底] 请提交 CLAIM' } },
  { type: 'message', message: { role: 'assistant', content: [{ type: 'toolCall', name: 'submit_conclusion' }] } },
];
check('取最后一条 user 消息文本（retry 链识别）', lastUserMessageText(BRANCH), '[完成验证器·保底] 请提交 CLAIM');

// ---------------------------------------------------------------------------
// 4. 出口闸注册与 tier 归属
// ---------------------------------------------------------------------------
console.log('\n[4] 出口闸注册与 tier');

check('submit_conclusion 在业务白名单', KNOWN_BUSINESS_TOOLS.has('submit_conclusion'), true);
check('submit_conclusion 在 business 分类（ALLOWED 派生源）', TOOL_CATEGORIES.business.has('submit_conclusion'), true);
check('只调 submit（未调 query_*）→ tier=library（v1.2 §3.1）', decideTier(['submit_conclusion']), 'library');
check('web 工具混 query_* → tier=mixed', decideTier(['query_sales', 'web_search']), 'mixed');
check('无工具 → tier=none', decideTier([]), 'none');

// ---------------------------------------------------------------------------
// 5. B2-2/B2-6 web 受控（评估迭代基建包 wave2）
// ---------------------------------------------------------------------------
console.log('\n[5] web 受控三态 + 假今日');

import { TIKHUB_TOOLS } from './tikhub.ts';
check('PI_WEB_ACCESS_TOOLS = pi-web-access 插件 4 真名（web_fetch 不存在）',
  [...PI_WEB_ACCESS_TOOLS].sort().join(','), 'fetch_content,get_search_content,source_check,web_search');
check('G1：web4 与 social_*（TikHub）不相交（剔除 web4 不波及社媒题）',
  [...PI_WEB_ACCESS_TOOLS].filter((t) => TIKHUB_TOOLS.has(t)).length, 0);
check('web4 ⊆ web 分类（tier 判定一致）',
  [...PI_WEB_ACCESS_TOOLS].every((t) => TOOL_CATEGORIES.web.has(t)), true);
const prevFake = process.env.PRISM_FAKE_TODAY;
const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; // 本地日期（trend fmt 同源）
process.env.PRISM_FAKE_TODAY = '2026-10-07';
check('B2-6 PRISM_FAKE_TODAY 注入 → evalToday 返回假今日', ymd(evalToday()), '2026-10-07');
process.env.PRISM_FAKE_TODAY = 'not-a-date';
const fallback = ymd(evalToday()) === ymd(new Date());
check('B2-6 PRISM_FAKE_TODAY 非法值 → 回退系统时间', fallback, true);
if (prevFake === undefined) delete process.env.PRISM_FAKE_TODAY;
else process.env.PRISM_FAKE_TODAY = prevFake;
check('B2-6 缺省（无 env）→ 系统时间（行为不变）', ymd(evalToday()) === ymd(new Date()), true);

console.log(`\n结果: ${pass} passed, ${fail} failed`);
process.exit(fail > 0 ? 1 : 0);
