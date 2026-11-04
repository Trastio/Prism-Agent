#!/usr/bin/env node
/**
 * 评估基建小包 · 批跑报告 → 四 sheet 分析表格（md + xlsx 同构）
 *
 * 用法：
 *   node eval/render_report.mjs <report.json> [--out <前缀>] [--with-manifest]
 *   - md 与 xlsx 落 <前缀>-四sheet.md / .xlsx（缺省前缀=报告同目录同主干）
 *   - --with-manifest：给报告本体补 SHA-256 sidecar manifest（可回填旧报告，洞2）
 *   - 报告缺 acceptance_boundary / first_error_turn 时自动派生（洞3，旧报告兼容）
 * 退出码：0 成功；2 参数错误；1 渲染失败
 */
import { readFileSync, writeFileSync, unlinkSync } from 'node:fs';
import { resolve, dirname, basename, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { buildSheets, renderMd, buildManifest, firstErrorTurn } from './report_lib.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const reportArg = args.find((a) => !a.startsWith('--'));
const outIdx = args.indexOf('--out');
const outPrefix = outIdx >= 0 ? resolve(process.cwd(), args[outIdx + 1]) : null;
const withManifest = args.includes('--with-manifest');

if (!reportArg) {
  console.error('用法: node render_report.mjs <report.json> [--out <前缀>] [--with-manifest]');
  process.exit(2);
}

const reportPath = resolve(process.cwd(), reportArg);
const report = JSON.parse(readFileSync(reportPath, 'utf-8'));
const rows = report.results || [];
let tasks = [];
try { tasks = JSON.parse(readFileSync(resolve(ROOT, 'eval/tasks.json'), 'utf-8')); } catch (e) {
  // P1-2 修复（Step7 审查）：tasks 加载失败必须出声——set/原型列缺省、恢复表消失不能是静默降级
  console.error(`[warn] eval/tasks.json 加载失败（${e.message}）：set/原型列将缺省，恢复表无法生成`);
}

// 旧报告兼容：acceptance_boundary / first_error_turn 缺失时由 buildSheets 内部派生（不回写原文件）
const { sheets, firstErrorFilled } = buildSheets(rows, tasks, report);

// 输出前缀
const defaultPrefix = join(dirname(reportPath), basename(reportPath).replace(/\.json$/, ''));
const prefix = outPrefix || defaultPrefix;

// 1) md
const mdPath = `${prefix}-四sheet.md`;
writeFileSync(mdPath, renderMd(sheets), 'utf-8');

// 2) xlsx（openpyxl 助手；失败降级为仅 md 不阻塞）
const xlsxPath = `${prefix}-四sheet.xlsx`;
const tmpSheets = resolve(dirname(mdPath), `.${basename(prefix)}.sheets.tmp.json`);
writeFileSync(tmpSheets, JSON.stringify({ sheets }), 'utf-8');
let xlsxOk = false;
try {
  const py = spawnSync('python', [resolve(ROOT, 'eval/render_xlsx.py'), xlsxPath, tmpSheets], { encoding: 'utf-8' });
  if (py.status === 0) xlsxOk = true;
  else console.error(`[warn] xlsx 渲染失败（仅出 md）：${(py.stderr || '').trim().slice(0, 300)}`);
} catch (e) {
  console.error(`[warn] xlsx 渲染异常（仅出 md）：${e.message}`);
} finally {
  try { unlinkSync(tmpSheets); } catch {}
}

// 3) 可选：报告本体哈希 sidecar（旧报告回填）
let manifestPath = null;
if (withManifest) {
  const m = buildManifest([{ path: reportPath, rel: relative(process.cwd(), reportPath), description: '批跑报告（离线回填哈希）' }], { run_id: report.run_id ?? null });
  manifestPath = `${reportPath.replace(/\.json$/, '')}.manifest.json`;
  writeFileSync(manifestPath, JSON.stringify(m, null, 2), 'utf-8');
}

// 对账摘要
const scores = rows.map((r) => r.score ?? 0);
const full = scores.filter((s) => s === 5).length;
const low = rows.filter((r) => (r.score ?? 5) < 4);
console.log('─'.repeat(60));
console.log(`报告: ${basename(reportPath)}（${rows.length} 题）`);
console.log(`四 sheet: ${sheets.filter((s) => s.name !== '_boundary').map((s) => s.name).join(' / ')}`);
console.log(`对账: 满分=${full} 低分=${low.length}（${low.map((r) => `${r.task}:${r.score}`).join(' ')}）`);
console.log(`首错轮有值: ${firstErrorFilled}/${rows.length}${low.length ? `；低分题首错轮=${low.map((r) => r.first_error_turn ?? firstErrorTurn(r)).join(',')}` : ''}`);
console.log(`产物:\n  ${mdPath}\n  ${xlsxOk ? xlsxPath : '(xlsx 未生成，见 warn)'}${manifestPath ? `\n  ${manifestPath}` : ''}`);
