/**
 * Prism-Agent · 题号 → Langfuse 轨迹直达链接 索引表（2026-11-01）
 *
 * 背景：插件生成的 trace 名统一为 "Pi Turn"，题号只存在 score 的 metadata 里，
 * Langfuse 列表页不显示 → 人在 UI 里无法按题定位，只能翻列表（实测反馈）。
 * 本脚本读报告 + 查 ClickHouse scores，产出「题号 | 分数 | 扣分原因 | 轨迹链接」索引表，
 * 一次点击直达该题轨迹。
 *
 * 用法：
 *   node eval/trace_index.mjs                       # 取 eval/reports 下最新的 eval-*.json
 *   node eval/trace_index.mjs --report=<path>       # 指定报告
 *   node eval/trace_index.mjs --task=cross-02       # 只出单题
 *
 * 说明：fail-soft —— 查不到 trace（如该题跑在 dual 写模式之前）时链接列留 "—"，不阻塞。
 */

import { readFileSync, writeFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, dirname, basename, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PROJECT_ID = 'prism-dev'; // Langfuse 项目 id（UI 侧同一值）

function arg(name, def) {
  const hit = process.argv.slice(2).find((a) => a.startsWith(`--${name}=`));
  return hit ? hit.slice(name.length + 3) : def;
}

/** 选报告：显式 --report 优先；缺省取 reports 下最新且真含 results 的 eval-*.json（排除侧车） */
function pickReport() {
  const explicit = arg('report');
  if (explicit) return explicit;
  const dir = resolve(ROOT, 'eval/reports');
  const files = readdirSync(dir)
    .filter((f) => /^eval-.*\.json$/.test(f) && !f.includes('.rescored') && !f.includes('.manifest'))
    .map((f) => ({ f, m: statSync(join(dir, f)).mtimeMs }))
    .sort((a, b) => b.m - a.m);
  for (const x of files) {
    try {
      if (Array.isArray(JSON.parse(readFileSync(join(dir, x.f), 'utf-8')).results)) return join(dir, x.f);
    } catch { /* 跳过坏文件 */ }
  }
  throw new Error('eval/reports 下找不到含 results 的 eval-*.json（可用 --report 指定）');
}

function creds() {
  try {
    const f = JSON.parse(readFileSync(resolve(ROOT, '.pi/agent-minimal/langfuse.json'), 'utf-8'));
    return { base: process.env.LANGFUSE_BASE_URL || f.baseUrl, ch: f.clickhouseUrl, auth: f.clickhouseAuth };
  } catch {
    return null;
  }
}

/** 查本轮所有 eval-score 的 (task_id, trace_id)：metadata 是 Map 列，须 toString 才能 LIKE */
async function taskTraceMap(runId, c) {
  if (!c?.ch || !c?.auth) return new Map();
  const sql = `SELECT trace_id, toString(metadata) FROM scores
    WHERE name = 'eval-score' AND toString(metadata) LIKE '%${runId.replace(/'/g, "''")}%'
    FORMAT TSV`;
  const res = await fetch(`${c.ch}/?query=${encodeURIComponent(sql)}`, {
    headers: { Authorization: 'Basic ' + Buffer.from(c.auth).toString('base64') },
    signal: AbortSignal.timeout(15000),
  });
  if (!res.ok) return new Map();
  const out = new Map();
  for (const line of (await res.text()).split('\n')) {
    if (!line.trim()) continue;
    const [traceId, meta] = line.split('\t');
    // ClickHouse toString(Map) 会把引号转义成 \' —— 先还原再取 task_id
    const m = /'task_id':'([^']+)'/.exec((meta ?? '').replace(/\\'/g, "'"));
    if (m) out.set(m[1], traceId);
  }
  return out;
}

const esc = (s) => String(s ?? '').replace(/\|/g, '／').replace(/\n/g, ' ');

async function main() {
  const reportPath = pickReport();
  const report = JSON.parse(readFileSync(reportPath, 'utf-8'));
  const runId = report.run_id || report.runId || basename(reportPath).replace(/^eval-/, '').replace(/\.json$/, '');
  const only = arg('task');

  const c = creds();
  const map = await taskTraceMap(runId, c);

  const rows = (report.results || []).filter((r) => (only ? r.task === only : true) && r.valid !== false);
  const lines = [
    `# 轨迹索引 · ${runId}`,
    '',
    `> 报告：\`${reportPath}\``,
    `> 快照：${report.runtime_snapshot || '未记录'}｜共 ${rows.length} 题｜已定位轨迹 ${[...rows].filter((r) => map.get(r.task)).length}`,
    '> Langfuse：<http://localhost:3300> · 项目 prism-dev',
    '',
    '| 题号 | 维度 | 分 | 扣分原因 | 轨迹 |',
    '|---|---|---|---|---|',
  ];
  for (const r of rows) {
    const tid = map.get(r.task);
    const link = tid ? `[打开](http://localhost:3300/project/${PROJECT_ID}/traces/${tid})` : '— 未找到轨迹';
    lines.push(`| ${r.task} | ${esc(r.dimension)} | ${r.score} | ${esc((r.reasons || []).join('; ')).slice(0, 120)} | ${link} |`);
  }
  lines.push('');

  const out = resolve(ROOT, `eval/reports/index-${runId}.md`);
  writeFileSync(out, lines.join('\n'), 'utf-8');
  console.log(`[trace_index] run=${runId} 题=${rows.length} 命中轨迹=${[...rows].filter((r) => map.get(r.task)).length}`);
  console.log(`[trace_index] 已写入 ${out}`);
  if (!map.size) console.warn('[trace_index] 该批次无 score→trace 映射（可能早于 dual 写模式，或 ClickHouse 不可达）');
}

main().catch((e) => {
  console.error('[trace_index] 失败:', e?.message ?? e);
  process.exit(1);
});
