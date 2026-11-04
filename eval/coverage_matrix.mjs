/**
 * L1-1.5 工具×题目覆盖矩阵（2026-10-31 建，方案 §10.0.1 L1-1.5）
 *
 * 目的：找出"一次都没被题目触发过"的工具——它们坏了评估也发现不了。
 * 数据源：
 *   - 工具全集：从 guardrails 白名单文本解析（不 import，避免执行注册副作用）
 *   - 题目侧：零基线报告的 results[].tools（runner 逐题记录的工具清单）
 *   - 全局侧：eval/trajectories/eval-trajectories.jsonl 的实际调用（含无报告覆盖的历史批跑）
 * 输出：eval/reports/coverage-matrix.json + 控制台表
 *
 * 用法：node eval/coverage_matrix.mjs [report.json]
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const GUARD = resolve(ROOT, '.pi/extensions/prism-guardrails');

/** 从 Set 定义块里抓工具名（只抓单引号小写标识符，忽略 ...展开） */
function pickup(block) {
  return (String(block || '').match(/'[a-z0-9_]+'/g) || []).map((s) => s.slice(1, -1));
}

/** 应注册的工具全集（按分类） */
export function expectedTools() {
  let idx = '', tikhub = '';
  try { idx = readFileSync(resolve(GUARD, 'index.ts'), 'utf-8'); } catch {}
  try { tikhub = readFileSync(resolve(GUARD, 'tikhub.ts'), 'utf-8'); } catch {}
  const grab = (src, re) => pickup((src.match(re) || [])[1] || '');
  const business = grab(idx, /KNOWN_BUSINESS_TOOLS = new Set\(\[([\s\S]*?)\]\)/);
  const web = grab(idx, /web: new Set\(\[([\s\S]*?)\]\)/);
  const utility = grab(idx, /utility: new Set\(\[([\s\S]*?)\]\)/);
  const tik = grab(tikhub, /TIKHUB_TOOLS = new Set\(\[([\s\S]*?)\]\)/);
  return {
    business, web: [...web, ...tik], utility,
    all: [...new Set([...business, ...web, ...tik, ...utility])],
  };
}

/** 零基线报告默认路径（--set=all 的有效跑次） */
function defaultReport() {
  const dir = resolve(ROOT, 'eval/reports');
  const names = ['eval-2026-10-28T15-39-08-403Z-r3.rescored.json'];
  for (const n of names) if (existsSync(resolve(dir, n))) return resolve(dir, n);
  return null;
}

/**
 * 覆盖统计（纯函数）：返回工具 → 触发它的题集合。
 * @param rows 报告 results 行（含 task/tools）
 * @param trajLines 轨迹行（含 toolCalls）
 */
export function buildMatrix(rows, trajLines) {
  const byTool = new Map();   // tool -> Set<task>
  const byTask = new Map();   // task -> Set<tool>
  for (const r of rows || []) {
    const tools = Array.isArray(r.tools) ? r.tools : [];
    const set = new Set(tools);
    byTask.set(r.task, set);
    for (const t of set) {
      if (!byTool.has(t)) byTool.set(t, new Set());
      byTool.get(t).add(r.task);
    }
  }
  const trajCalls = new Map(); // tool -> 调用次数（轨迹侧）
  for (const t of trajLines || []) {
    for (const c of (t.toolCalls || [])) {
      const n = String(c?.name || '');
      if (n) trajCalls.set(n, (trajCalls.get(n) || 0) + 1);
    }
  }
  return { byTool, byTask, trajCalls };
}

function main() {
  const reportPath = process.argv[2] ? resolve(ROOT, process.argv[2]) : defaultReport();
  const exp = expectedTools();
  let rows = [];
  if (reportPath && existsSync(reportPath)) {
    const rep = JSON.parse(readFileSync(reportPath, 'utf-8'));
    rows = (rep.results || []).filter((r) => r.valid !== false);
  }
  const trajPath = resolve(ROOT, 'eval/trajectories/eval-trajectories.jsonl');
  const traj = existsSync(trajPath)
    ? readFileSync(trajPath, 'utf-8').trim().split('\n').filter(Boolean).map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean)
    : [];

  const m = buildMatrix(rows, traj);
  const used = new Set([...m.byTool.keys(), ...m.trajCalls.keys()]);
  const uncovered = exp.all.filter((t) => !used.has(t));

  // 逐工具明细：题数（报告侧）/ 调用次数（轨迹侧）
  const detail = exp.all.map((t) => ({
    tool: t,
    tasks: m.byTool.has(t) ? m.byTool.get(t).size : 0,
    calls: m.trajCalls.get(t) || 0,
    covered: used.has(t),
  }));

  const out = {
    generated_at: new Date().toISOString(),
    report: reportPath ? dirname(reportPath) + '/' : null,
    rows: rows.length,
    traj_rows: traj.length,
    expected_total: exp.all.length,
    covered_total: exp.all.length - uncovered.length,
    uncovered,
    detail,
    // 只调了"非业务工具"的题（无 resolve/query/get，可能是纯闲聊或回应失败）
    tasks_without_business: rows.filter((r) => !(r.tools || []).some((t) => exp.business.includes(t) || exp.web.includes(t))).map((r) => ({ task: r.task, tools: r.tools || [] })),
  };
  const outPath = resolve(ROOT, 'eval/reports/coverage-matrix.json');
  writeFileSync(outPath, JSON.stringify(out, null, 2), 'utf-8');

  console.log(`工具覆盖矩阵：应有 ${exp.all.length} / 已触发 ${out.covered_total} / 零覆盖 ${uncovered.length}`);
  console.log(`  报告 ${rows.length} 行，轨迹 ${traj.length} 行`);
  if (uncovered.length) {
    console.log('  ── 零覆盖（坏了也发现不了）──');
    for (const t of uncovered) console.log(`    ${t}`);
  }
  const low = detail.filter((d) => d.covered && d.tasks <= 1);
  if (low.length) {
    console.log('  ── 覆盖不足（仅 1 题触发）──');
    for (const d of low) console.log(`    ${d.tool}\ttasks=${d.tasks}\tcalls=${d.calls}`);
  }
  if (out.tasks_without_business.length) {
    console.log(`  ── 未调用任何业务/联网工具的题 ${out.tasks_without_business.length} 行 ──`);
    for (const t of out.tasks_without_business.slice(0, 10)) console.log(`    ${t.task}\t${JSON.stringify(t.tools)}`);
  }
  console.log(`→ ${outPath}`);
}

const IS_MAIN = (() => {
  try {
    return Boolean(process.argv[1]) && import.meta.url.toLowerCase() === pathToFileURL(process.argv[1]).href.toLowerCase();
  } catch { return false; }
})();
if (IS_MAIN) main();
