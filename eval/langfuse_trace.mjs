/**
 * Langfuse 真实轨迹读取器（失败归因的证据源）
 *
 * 背景（2026-11-01 实测）：
 * - 本地 trajectories.jsonl 的 toolCalls 只有 {"name":"query_sales"}、toolResults 只有 {name,is_error}，
 *   **没有入参、没有返回值** → 只能知道"调没调库"，不知道"查了什么、拿回来什么"，无法做步级归因。
 * - Langfuse（@langfuse/pi-observability-plugin）把每一步都落成了 span：
 *   `Tool: query_sales` 带完整入参 JSON 与返回值 JSON，`LLM Call` 带 tool_calls 决策，
 *   `Conversational Turn` 带题面与最终回复。这才是真实轨迹。
 *
 * 数据位置（v4 events_only 模式，2026-11-01 核实）：
 * - 真实数据在 ClickHouse `events_core`（不是 legacy 的 traces/observations——那两张表在 v4 下恒为 0，属正常）
 * - `/api/public/traces`、`/api/public/scores` 在 v4 已被封（返回 404 文案），
 *   `/api/public/v2/observations` 可读（UI 与它同源，均读 events_core）
 *
 * 用法：
 *   node eval/langfuse_trace.mjs --task config-07 [--repeat 1] [--report xxx.json] [--full]
 *   node eval/langfuse_trace.mjs --session <sessionId> [--full]
 *
 * 未指定 --report 时取 eval/reports 最新报告（含 results），按任务号+复跑号定位 sessionId。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

/** 读 Langfuse 凭据（与 eval/langfuse_writer.ts 同源文件；缺失则返回 null，调用方 fail-soft） */
export function loadLangfuseCreds() {
  try {
    const f = JSON.parse(readFileSync(join(ROOT, '.pi/agent-minimal/langfuse.json'), 'utf-8'));
    return {
      baseUrl: process.env.LANGFUSE_BASE_URL?.trim() || f.baseUrl,
      clickhouseUrl: process.env.LANGFUSE_CLICKHOUSE_URL?.trim() || f.clickhouseUrl,
      clickhouseAuth: process.env.LANGFUSE_CLICKHOUSE_AUTH?.trim() || f.clickhouseAuth,
      publicKey: f.publicKey,
      secretKey: f.secretKey,
    };
  } catch {
    return null;
  }
}

/** ClickHouse HTTP 查询（TSV 输出；失败返回空串，不抛——归因是旁路，不阻塞主链） */
async function chQuery(creds, sql) {
  if (!creds?.clickhouseUrl || !creds?.clickhouseAuth) return '';
  const auth = 'Basic ' + Buffer.from(creds.clickhouseAuth).toString('base64');
  try {
    const res = await fetch(`${creds.clickhouseUrl}/?query=${encodeURIComponent(sql)}&default_format=TSV`, {
      headers: { Authorization: auth },
      signal: AbortSignal.timeout(15000),
    });
    if (!res.ok) return '';
    return await res.text();
  } catch {
    return '';
  }
}

/** ClickHouse 字面量转义（sessionId 来自本系统生成，仍按单引号规则处理） */
const q = (s) => `'${String(s).replace(/\\/g, '\\\\').replace(/'/g, "''")}'`;

/**
 * 按 sessionId 取该题真实轨迹（跨多 trace 合并，按时间排序）。
 * 返回 { found, traces, steps }；未找到时 found=false（通常是跑批时 Langfuse 未启动/未连上，需复跑补采）。
 */
export async function fetchTrajectory(sessionId, creds = loadLangfuseCreds()) {
  if (!sessionId) return { found: false, traces: 0, steps: [] };
  const sql = `
    SELECT trace_id, type, name, start_time, end_time, left(input, 2000) AS inp, left(output, 2000) AS outp, level
    FROM events_core
    WHERE session_id = ${q(sessionId)}
    ORDER BY start_time ASC
    FORMAT TSV`;
  const raw = await chQuery(creds, sql);
  const rows = raw.trim().split('\n').filter(Boolean).map((line) => {
    const c = line.split('\t');
    return { traceId: c[0], type: c[1], name: c[2], startTime: c[3], endTime: c[4], input: c[5] ?? '', output: c[6] ?? '', level: c[7] ?? '' };
  });
  const traces = new Set(rows.map((r) => r.traceId)).size;
  return { found: rows.length > 0, traces, steps: rows };
}

/** 取工具步（type=TOOL）——归因最关心"查了什么、拿回来什么" */
export function toolSteps(steps) {
  return steps.filter((s) => s.type === 'TOOL');
}

/** 最新报告（含 results 的 eval-*.json；排除侧车） */
function latestReport() {
  const dir = resolve(ROOT, 'eval/reports');
  const files = readdirSync(dir)
    .filter((f) => /^eval-.*\.json$/.test(f) && !f.includes('.rescored') && !f.includes('.manifest'))
    .map((f) => ({ f, m: statSync(join(dir, f)).mtimeMs }))
    .sort((a, b) => b.m - a.m)
    .filter((x) => {
      try { return Array.isArray(JSON.parse(readFileSync(join(dir, x.f), 'utf-8')).results); } catch { return false; }
    });
  if (!files.length) throw new Error('eval/reports 下找不到含 results 的 eval-*.json');
  return join(dir, files[0].f);
}

/** 按 任务号+复跑号 在报告里定位 sessionId（复跑优先精确匹配，缺省取第一跑） */
export function sessionIdOf(report, task, repeat = 1) {
  const rows = Array.isArray(report.results) ? report.results : [];
  const hits = rows.filter((r) => r.task === task && (r.repeat ?? 1) === repeat);
  return hits.length ? hits[0].sessionId ?? null : null;
}

const clip = (s, n) => {
  const t = String(s ?? '').replace(/\n/g, ' ');
  return t.length > n ? t.slice(0, n) + '…' : t;
};

/** 渲染为可读文本（供 CLI 与 triage 复用） */
export function renderTrajectory(steps, { full = false, width = 200 } = {}) {
  if (!steps.length) return '（Langfuse 无此会话轨迹：跑批时观测栈可能未启动/未连通，需复跑补采）';
  const w = full ? 2000 : width;
  const lines = [];
  let n = 0;
  for (const s of steps) {
    if (s.type === 'GENERATION') {
      // LLM 决策步：只留"它决定调哪个工具"，正文太吵
      const calls = s.output.match(/"name":"([^"]+)"/g)?.map((x) => x.slice(8, -1)) ?? [];
      lines.push(`${s.startTime} · LLM 决策${calls.length ? ` → ${calls.join(', ')}` : '（无工具调用）'}`);
      continue;
    }
    n += 1;
    lines.push(`${s.startTime} · [${n}] ${s.name}`);
    lines.push(`    入参: ${clip(s.input, w)}`);
    lines.push(`    返回: ${clip(s.output, w)}`);
  }
  return lines.join('\n');
}

async function main() {
  const argv = process.argv.slice(2);
  const get = (k, d) => {
    const i = argv.indexOf(k);
    return i >= 0 && argv[i + 1] ? argv[i + 1] : d;
  };
  const full = argv.includes('--full');
  let sessionId = get('--session', null);
  const task = get('--task', null);

  if (!sessionId && task) {
    const reportPath = get('--report', null) ? resolve(get('--report')) : latestReport();
    const report = JSON.parse(readFileSync(reportPath, 'utf-8'));
    sessionId = sessionIdOf(report, task, Number(get('--repeat', '1')));
    if (!sessionId) throw new Error(`报告 ${reportPath} 里找不到任务 ${task}（repeat=${get('--repeat', '1')}）`);
    console.log(`任务 ${task} → session ${sessionId}\n报告 ${reportPath}\n`);
  }
  if (!sessionId) {
    console.error('用法：node eval/langfuse_trace.mjs --task <题号> [--repeat n] [--report 路径] [--full]');
    console.error('   或：node eval/langfuse_trace.mjs --session <sessionId> [--full]');
    process.exit(1);
  }

  const tr = await fetchTrajectory(sessionId);
  if (!tr.found) {
    console.log(renderTrajectory([], { full }));
    process.exit(2);
  }
  console.log(`会话 ${sessionId}｜trace ${tr.traces} 条｜步骤 ${tr.steps.length} 步（工具 ${toolSteps(tr.steps).length} 次）\n`);
  console.log(renderTrajectory(tr.steps, { full }));
}

// Windows 下 argv[1] 与 import.meta.url 的比较不可靠（曾误判不执行），统一走 pathToFileURL
const isMain = (() => {
  try {
    return pathToFileURL(resolve(process.argv[1] ?? '')).href === import.meta.url;
  } catch {
    return false;
  }
})();

if (isMain) main().catch((e) => { console.error(e.message); process.exit(1); });
