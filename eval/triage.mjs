/**
 * 坏例分诊（triage）：把报告里的失败行摊成一张人可确认的清单
 *
 * 目的：机器只做"摆证据"，不做"下结论"——
 *   证据 = 扣分链（哪条判据封顶）+ 工具轨迹（查没查库/查了什么）+ 回复片段
 *   结论 = 初判（待人工确认页），人只需确认或推翻，不用自己翻报告
 *
 * 用法：node eval/triage.mjs [report.json]   （缺省取 eval/reports 最新 eval-*.json）
 * 产出：eval/reports/triage-<run_id>.md + 控制台摘要
 */
import { readFileSync, writeFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { fetchTrajectory, toolSteps, renderTrajectory } from './langfuse_trace.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

/** 取最新报告（按 mtime；排除 .rescored / .manifest（无 results 的侧车）与 triage 产物） */
function latestReport() {
  const dir = resolve(ROOT, 'eval/reports');
  const files = readdirSync(dir)
    .filter((f) => /^eval-.*\.json$/.test(f) && !f.includes('.rescored') && !f.includes('.manifest'))
    .map((f) => ({ f, m: statSync(join(dir, f)).mtimeMs }))
    .sort((a, b) => b.m - a.m)
    // 逐个确认真的含 results（首次试跑曾误选 manifest 侧车，静默出 0 行）
    .filter((x) => {
      try { return Array.isArray(JSON.parse(readFileSync(join(dir, x.f), 'utf-8')).results); } catch { return false; }
    });
  if (!files.length) throw new Error('eval/reports 下找不到含 results 的 eval-*.json');
  return join(dir, files[0].f);
}

// 查询类工具前缀（用于判"有没有查库"）
const isQueryTool = (t) => /^(query_|resolve_series|score_models|get_similar_models|search_reviews)/.test(t);

/**
 * 初判（候选原因，非结论）——只做机器能从证据里读出来的那一层
 * 返回 { cause, action }：action 是处置候选，最终由人拍板
 */
function triageRow(r) {
  const reasons = r.reasons || [];
  const tools = Array.isArray(r.tools) ? r.tools : [];
  const reply = String(r.reply_full || r.replyPreview || '');
  const usedQuery = tools.some(isQueryTool);

  if (r.valid === false || r.error) {
    return { cause: `跑坏（${r.invalid_reason || r.error}）`, action: '重试，不计分' };
  }
  if (reasons.includes('timeout')) {
    return { cause: '基础设施超时', action: '重试' };
  }
  // trap 未拦截：0 分且理由含"未被拦截"
  if (r.score === 0 && reasons.some((x) => x.includes('未被拦截'))) {
    const hasNum = /\d+(\.\d+)?\s*(万|km|元|kWh)/.test(reply);
    return {
      cause: hasNum ? '疑似编造（回复含具体数值）' : '疑似未拒绝（未明确说数据不可得）',
      action: '改 agent（拒绝话术/验证器）',
    };
  }
  if (reasons.some((x) => x.startsWith('truth 缺锚') || /^truth\[t\d+\]/.test(x))) {
    if (!usedQuery) return { cause: '疑似未查库（缺锚且无查询类工具调用）', action: '改 agent（工具使用）' };
    if (/未收录|无数据|为空|没有.*数据|查不到/.test(reply)) return { cause: '疑似数据缺口（已查库但报无数据）', action: '改题（判据要求了库里没有的数据）' };
    return { cause: '疑似表述未覆盖锚点（查了库但文未引用）', action: '待确认：改 agent 或改判据正则' };
  }
  if (reasons.some((x) => x.startsWith('rubric['))) {
    return { cause: 'rubric 要素未覆盖', action: '待确认：改 agent 或改判据要素' };
  }
  if (reasons.some((x) => x.includes('越界'))) {
    return { cause: '市场侧归因产品力（越界）', action: '改 agent（口径声明）' };
  }
  if (reasons.some((x) => x.includes('轮间漂移'))) {
    return { cause: '多轮上下文漂移', action: '改 agent（跨轮复用口径）' };
  }
  return { cause: '待人工判断', action: '待确认' };
}

function chainOf(r) {
  const steps = r.deduction_trace?.steps;
  if (Array.isArray(steps) && steps.length) {
    return steps.map((s) => `${s.from}→${s.to}：${s.reason}`).join('；');
  }
  return (r.reasons || []).join('；') || '（无扣分理由）';
}

/**
 * 并发拉取坏例的真实轨迹（Langfuse → ClickHouse events_core，按 sessionId）。
 * fail-soft：无凭据/服务不可达 → found=false（清单里标"轨迹缺失"），不影响分诊产出。
 */
async function attachTrajectories(rows) {
  const map = new Map();
  const ids = [...new Set(rows.map((r) => r.sessionId).filter(Boolean))];
  await Promise.all(ids.map(async (sid) => {
    try { map.set(sid, await fetchTrajectory(sid)); } catch { map.set(sid, { found: false, traces: 0, steps: [] }); }
  }));
  return map;
}

async function main() {
  const reportPath = process.argv[2] ? resolve(process.argv[2]) : latestReport();
  const report = JSON.parse(readFileSync(reportPath, 'utf-8'));
  const rows = Array.isArray(report.results) ? report.results : [];

  // 失败行：invalid + score<4（trap 未拦截的 0 分自然在内）
  const bad = rows.filter((r) => r.valid === false || r.error || (r.score ?? 5) < 4);
  const runId = report.run_id || reportPath;

  // 真实轨迹（Langfuse）：本地 trajectories 只有工具名，看不到入参/返回；
  // 这里按 sessionId 拉步级明细，缺轨迹的行明确标注（多为跑批时观测栈未启动，需复跑补采）。
  const trajMap = await attachTrajectories(bad);
  const traced = bad.filter((r) => trajMap.get(r.sessionId)?.found).length;

  const lines = [];
  lines.push(`# 坏例分诊清单 · ${runId}`);
  lines.push('');
  lines.push(`> 报告：\`${reportPath}\``);
  lines.push(`> 总行 ${rows.length}｜坏例 ${bad.length}｜invalid ${rows.filter((r) => r.valid === false).length}`);
  lines.push(`> 真实轨迹（Langfuse）：${traced}/${bad.length} 个坏例可取到步级明细；缺的标"轨迹缺失"，需复跑补采。`);
  lines.push('> 初判是**候选原因**，处置由人确认后写入 eval/badcases.md。');
  lines.push('');
  lines.push('## 一览');
  lines.push('');
  lines.push('| 题号 | 维度 | 分 | 复跑 | 工具数 | 初判 | 建议处置 |');
  lines.push('|---|---|---|---|---|---|---|');
  for (const r of bad) {
    const t = triageRow(r);
    lines.push(`| ${r.task} | ${r.dimension || ''} | ${r.score ?? '—'} | ${r.repeat ?? 1} | ${(r.tools || []).length} | ${t.cause} | ${t.action} |`);
  }
  lines.push('');
  lines.push('## 逐题证据');
  lines.push('');
  for (const r of bad) {
    const t = triageRow(r);
    const tools = Array.isArray(r.tools) ? r.tools : [];
    const uniq = [...new Set(tools)];
    const reply = String(r.reply_full || r.replyPreview || '');
    lines.push(`### ${r.task}（${r.dimension || '—'}）· ${r.score ?? '—'} 分 · 第 ${r.repeat ?? 1} 跑`);
    lines.push('');
    lines.push(`- **扣分链**：${chainOf(r)}`);
    lines.push(`- **工具**：${tools.length} 次调用${uniq.length ? `，${uniq.join(' / ')}` : ''}${tools.some(isQueryTool) ? '（含查询类）' : '（**无查询类**）'}`);
    lines.push(`- **回复长度**：${r.replyLength ?? reply.length} 字符｜settled=${r.settled ?? '—'}｜verdict=${r.verdict ?? '—'}`);
    if (r.first_error_turn != null) lines.push(`- **首错轮**：t${r.first_error_turn}`);
    lines.push(`- **初判**：${t.cause}`);
    lines.push(`- **建议处置**：${t.action}`);
    lines.push('');

    // 真实轨迹：工具步带入参/返回，归因看"查了什么、拿回来什么、哪一步走偏"
    const tr = trajMap.get(r.sessionId);
    const steps = tr?.found ? toolSteps(tr.steps) : [];
    lines.push(`<details><summary>真实轨迹（Langfuse）：${steps.length} 次工具调用${tr?.found ? `｜${tr.traces} 条 trace` : '｜**轨迹缺失**'}</summary>`);
    lines.push('');
    lines.push('```');
    lines.push(steps.length ? renderTrajectory(steps, { width: 260 }) : '（该会话在 Langfuse 无数据：跑批时观测栈未启动/未连通，需复跑补采）');
    lines.push('```');
    lines.push('');
    lines.push('</details>');
    lines.push('');
    lines.push('<details><summary>回复片段（前 300 字）</summary>');
    lines.push('');
    lines.push('```');
    lines.push(reply.slice(0, 300) || '（空）');
    lines.push('```');
    lines.push('');
    lines.push('</details>');
    lines.push('');
  }

  const outPath = join(ROOT, 'eval/reports', `triage-${String(runId).replace(/[:.]/g, '-')}.md`);
  writeFileSync(outPath, lines.join('\n'), 'utf-8');

  // 控制台摘要：按初判聚合
  const byCause = new Map();
  for (const r of bad) {
    const c = triageRow(r).cause;
    byCause.set(c, (byCause.get(c) || 0) + 1);
  }
  console.log(`报告: ${reportPath}`);
  console.log(`总行 ${rows.length}｜坏例 ${bad.length}`);
  for (const [c, n] of [...byCause.entries()].sort((a, b) => b[1] - a[1])) console.log(`  ${n} × ${c}`);
  console.log(`清单: ${outPath}`);
}

main().catch((e) => { console.error(e.message); process.exit(1); });
