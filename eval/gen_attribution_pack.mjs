#!/usr/bin/env node
/**
 * 归因材料包生成器（归因工具包 change，2026-10-16）
 *
 * 用途：低分题的"单文件归因工作台"——每题一节，把分散在报告/tasks/判分明细里的材料
 * 聚齐（题目全文/判分规则/逐要素命中/工具调用/回复全文/首错轮），并给"初步信号"标注。
 * **纪律：信号只是候选分类，不下结论**——归因结论由人（PM）读材料后自己下（用户拍板：
 * 归因修复自己看；本工具只供材料，不替人判断）。
 *
 * 用法：node eval/gen_attribution_pack.mjs [report.json] [--threshold 4] [--out <path>]
 *   缺省报告 = eval/eval-report.json；阈值 = 分 < threshold 的题入选（缺省 4）
 *   旧报告无 reply_full 时降级为 replyPreview + 提示（全文看 langfuse/重跑）
 * 退出码：0 成功（含"无低分题"空包）；2 参数错
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { firstErrorTurn } from './report_lib.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

/** 初步信号（候选分类，不下结论——归因是人的活） */
export function prelimSignals(reasons = []) {
  const sigs = [];
  const has = (kw) => reasons.some((r) => r.includes(kw));
  if (has('越界')) sigs.push('**候选A堆·越界措辞（提示词层）**——先读回复原文确认措辞真越界（"销量印证产品力"式），排除正则误伤');
  if (reasons.some((r) => r.startsWith('truth 缺锚'))) sigs.push('**候选B堆·锚形态（判分校准）**——对照回复找数字是否已给只是形态不同（如 46.15% vs 46.2%）');
  if (has('rubric') && has('缺要素')) sigs.push('**候选A/B混合·rubric缺要素**——读回复：要素在但名字写法不同→判分名字归一问题（B堆）；要素真没提→agent 真漏（A堆）');
  if (reasons.includes('timeout')) sigs.push('**基础设施（timeout）**——不计 agent 能力，查服务/网络后再跑');
  if (!sigs.length && reasons.length) sigs.push('**信号未覆盖**——按 reasons 逐条人肉判读');
  return sigs;
}

export function buildPack(rows, tasks) {
  const tmap = new Map(tasks.map((t) => [t.id, t]));
  const out = [];
  for (const r of rows) {
    const t = tmap.get(r.task) || {};
    const fet = r.first_error_turn ?? firstErrorTurn(r);
    out.push(`## ${r.task}（${t.set ?? r.set ?? '-'}｜${r.dimension ?? t.dimension ?? '-'}）· ${r.score} 分${r.repeat > 1 ? ` · r${r.repeat}` : ''}

**题目**：${t.question ?? r.question ?? '（tasks.json 无此题——题库已变更？）'}

**判分规则**：${t.judge_rubric ?? '（无 rubric 文本）'}
${t.truth ? `\n**truth 锚点**：${JSON.stringify(t.truth.anchors ?? [])}${t.truth.forbid?.length ? ` ｜ 违禁：${JSON.stringify(t.truth.forbid)}` : ''}` : ''}

**判分结果 reasons**：
${(r.reasons ?? []).map((x) => `- ${x}`).join('\n') || '- （无）'}
${r.truth?.checked ? `\n**truth 命中明细**：missing=${JSON.stringify(r.truth.missing ?? [])} forbidHits=${JSON.stringify(r.truth.forbidHits ?? [])}` : ''}${r.rubric?.checked ? `\n**rubric 明细**：kind=${r.rubric.kind} pass=${r.rubric.pass} missing=${JSON.stringify(r.rubric.missing ?? [])}` : ''}

**首错轮**：${fet ?? '—'}｜**verdict**：${r.verdict ?? '—'}｜**成本**：${r.cost?.tokens?.totalTokens ?? r.cost?.duration_s + 's' ?? '—'} tokens

**工具调用（前5）**：${(r.tools ?? []).join(' → ') || '（无记录）'}

### 回复原文
${r.reply_full ? '```\n' + r.reply_full + '\n```' : '```\n[旧报告无全文，仅预览] ' + (r.replyPreview ?? '') + '\n```\n> 全文看 langfuse(3000) environment=eval 搜本题，或下轮批跑（报告已新增 reply_full 字段）'}

### 初步信号（候选，不下结论）
${prelimSignals(r.reasons).map((s) => '- ' + s).join('\n')}

---`);
  }
  return out.join('\n\n');
}

// ── CLI ──
const isDirectRun = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isDirectRun) {
  const args = process.argv.slice(2);
  const reportArg = args.find((a) => !a.startsWith('--'));
  const thIdx = args.indexOf('--threshold');
  const threshold = thIdx >= 0 ? Number(args[thIdx + 1]) : 4;
  const outIdx = args.indexOf('--out');
  if (!reportArg) { console.error('用法: gen_attribution_pack.mjs <report.json> [--threshold 4] [--out <path>]'); process.exit(2); }
  const report = JSON.parse(readFileSync(resolve(process.cwd(), reportArg), 'utf-8'));
  const tasks = JSON.parse(readFileSync(resolve(ROOT, 'eval/tasks.json'), 'utf-8'));
  const low = (report.results ?? []).filter((r) => (r.score ?? 5) < threshold);
  const header = `# 归因材料包 · ${report.run_id ?? reportArg}

> 生成时间 ${new Date().toISOString()} ｜ 阈值 <${threshold} ｜ 低分题 ${low.length} 道 ｜ 快照 ${report.snapshot_id ?? '-'} ｜ 提示词指纹 ${report.prompt_files_hash ?? '（旧报告未记）'}
> **纪律**：初步信号只是候选分类；归因结论由人读材料后自下（A堆=agent真错→提示词修；B堆=判分错→校准）。归因后修复走 prompt-gate 流程。

`;
  const outPath = outIdx >= 0 ? resolve(process.cwd(), args[outIdx + 1]) : resolve(ROOT, 'eval/reports', `归因材料包-${(report.run_id ?? 'report').slice(0, 24)}.md`);
  const body = low.length ? buildPack(low, tasks) : '（本批无低分题——空包）';
  writeFileSync(outPath, header + body, 'utf-8');
  console.log(`归因材料包: ${outPath}（${low.length} 题：${low.map((r) => r.task).join(' ')}）`);
}
