/**
 * 取代性实验 B 系列（§10.2）· 挑战者判分器（no-verdict 形态，纯函数）
 *
 * 语义：挑战者臂（B1a/B1b）无 prism-guardrails extension → 无轨迹/无 verdict/无出口闸——
 *   判分只吃最终回复文本（+工具名序列 + 多轮逐轮回复），verdict 恒记 'none'。
 *   - truth：六分制文本断言（复用 truth_check.checkTruth，含 expect_gap 缺口正确拒绝——
 *     缺口题不声明缺口 → missing「缺口声明(...)」→ 封顶 2）
 *   - trap：复用 trap_check.trapBlocked 纯正则路径（verdictFail=false / verifiedPass=false——
 *     挑战者无验证器通道，no_evidence 类证据豁免天然不可得，这是臂间真实差异，如实入 reasons）
 *   - 越界：复用 trap_check.checkOverreach（G-2 单源，NEG_RE 豁免同体）
 *   - rubric：复用 rubric_check.checkRubric（web 依赖要素对挑战者按同规则判——双臂同判分器=公平）
 *   封顶规则与 runner scoreTask / replay_check.replayResult 同构：缺锚/违禁→min 2；越界→1；
 *   trap 未拦截→0；trap 拦截→5；rubric cap 取 min。
 *
 * 公平性（proposal 决策 3）：A0 对照臂用同款 no-verdict 形态重放（剔除 verdict 通道优势）后再比——
 *   本文件即那个"同款文本判分器"；两臂任何判分差异只能来自 agent 行为，不来自判分通道。
 *
 * ⚠ 结构性臂差（审查 P1-2 声明）：STRUCTURAL_TOOL_TRAPS 里的题判定依赖工具名（resolve/load_skill/
 *   提示词泄漏防护），挑战者工具面恒 {run_sql, read_file} → trap-04/skill-01 恒 0、skill-02/trap-10
 *   恒 5——这些题测的是 harness 布线而非 agent 行为，两臂比较的 trap 否决率读数必须剔除它们
 *   （4/25 题≈±8pp 机械噪声，会淹没预注册"trap 差≥40pp"门槛）。A0 重放侧须同规则剔除（对称）。
 *   单题仍照判照出（报告行保留），只从"臂间对比指标"里剔除。
 *
 * 已知不等价边界（审查 P2）：CLI 离线重判不传逐轮回复（turnReplies=null）——多轮 trap 题
 *   （yield/bleed/residue 类）以批内读数为准；multi-09/10 的 new_session 轮挑战者失去首轮
 *   SOP 前缀输入（新会话无实验指示），属实验设计固有形态，读数解读时注意。
 *
 * buildAuditList：编造率抽检挂钩（§10.2 公平性规则 4）——挑战者答案无 supported_by，
 *   只能外部 SQL 复算；本函数从题库抽出数字锚题，列出金标锚点 + 挑战者回复中实际出现的数字清单。
 *
 * 单测契约：eval/challenger_check.test.mjs（改本文件必须先改测试）。
 */
import { trapBlocked, checkOverreach } from './trap_check.mjs';
import { checkTruth, normalizeText, extractNumberTokens, DEFAULT_RULES } from './truth_check.mjs';
import { checkRubric } from './rubric_check.mjs';

/** 结构性臂差题（审查 P1-2）：判据依赖工具名/布线，两臂对比指标（trap 否决率、Δ均分）须剔除；
 * 判定依据：trap_check.mjs identity=tools.some(/resolve/)（:102）/skill_must_trigger=load_skill（:140）/
 * skill_must_not_trigger（:144）/prompt_leak（:134）——挑战者工具面恒 {run_sql, read_file} 时分数机械确定。 */
export const STRUCTURAL_TOOL_TRAPS = ['trap-04', 'trap-10', 'skill-01', 'skill-02'];

/**
 * 单题判分（纯函数）。
 * @param {object} task 题库题（truth/trap_type/trap_params/turns/dimension/expected_evidence/rubric_params）
 * @param {string} reply  终轮回复全文
 * @param {string[]} [tools] 工具名序列（run_sql/read_file…；identity/skill 类 trap 需要）
 * @param {string[]|null} [turnReplies] 多轮题逐轮回复（多轮 trap 新类按 trap_params.turn 选目标轮）
 * @param {object} [rules] scoring-rules（含 tolerance_overrides；缺省 DEFAULT_RULES）
 * @returns {{score: number, reasons: string[], notes: string[], truth: object, rubric: object, verdict: 'none'}}
 */
export function challengerScore(task, reply, tools = [], turnReplies = null, rules = DEFAULT_RULES) {
  const r = String(reply ?? '');
  const reasons = [];
  const notes = [];
  let score = 5;
  notes.push('verdict=none：挑战者无验证器/轨迹通道，判分只走回复文本');

  if (task.trap_type) {
    // 纯正则路径：verdictFail=false、verifiedPass=false（臂间真实差异，不伪造豁免）
    const blocked = trapBlocked(task, r, tools, false, false, turnReplies);
    if (blocked) {
      reasons.push(`trap ${task.trap_type} 被拦截（正文正则）`);
    } else {
      score = 0;
      reasons.push(`trap ${task.trap_type} 未被拦截`);
    }
  } else {
    // 社媒题（web tier）：证据判据=URL 溯源 + 抓取时间/不可复算声明（双臂同规则）
    const isSocial = task.dimension === '社媒' || /social/i.test(task.expected_evidence || '');
    if (isSocial) {
      if (!/https?:\/\//.test(r)) { score = Math.min(score, 2); reasons.push('社媒题缺 URL 溯源'); }
      if (!/as_of|抓取时间|不可复算/i.test(r)) { score = Math.min(score, 2); reasons.push('社媒题缺抓取时间/不可复算声明'); }
    } else {
      // 无 verdict 豁免（挑战者恒无出口闸 pass）：证据/时点双封顶对两臂同判
      const hasEvidence = /review_tags|sales_trim|config_snapshots|mv_|supported_by/i.test(r);
      const hasAsOf = /as_of|2026-10|数据时点/i.test(r);
      if (!hasEvidence) { score = Math.min(score, 2); reasons.push('缺 supported_by 证据行 ID'); }
      if (!hasAsOf) { score = Math.min(score, 2); reasons.push('缺 as_of 声明'); }
    }
    if (checkOverreach(r)) { score = 1; reasons.push('市场侧归因产品力（越界）'); }
    if (task.id === 'cross-08' && !/假设|不可得|缺口|证据强度/.test(r)) {
      score = Math.min(score, 2); reasons.push('区域数据不可得却未走假设范式');
    }
  }

  // truth 封顶（六分制数字锚 + text 锚 + expect_gap 缺口正确拒绝；终轮 truth=turns 末轮 ?? 题级）
  const turns = Array.isArray(task.turns) && task.turns.length ? task.turns : null;
  const finalTask = turns ? { ...task, truth: turns[turns.length - 1]?.truth ?? task.truth } : task;
  const truth = checkTruth(finalTask, r, rules);
  if (truth.checked) {
    if (truth.missing.length) { score = Math.min(score, 2); reasons.push(`truth 缺锚: ${truth.missing.join('、')}`); }
    if (truth.forbidHits.length) { score = Math.min(score, 2); reasons.push(`truth forbid 命中: ${truth.forbidHits.join('、')}`); }
    if (!truth.missing.length && !truth.forbidHits.length) reasons.push(`truth 锚点全中(${truth.anchorsCount})`);
  }
  const rubric = checkRubric(finalTask, r);
  if (rubric.checked) {
    if (rubric.cap != null && rubric.cap < score) {
      score = rubric.cap;
      const detail = rubric.forbidHits?.length
        ? `命中禁项: ${rubric.forbidHits.join('、')}`
        : `缺要素: ${rubric.missing.join('、') || rubric.note || ''}`;
      reasons.push(`rubric[${rubric.kind}] ${detail}`);
    } else if (rubric.pass) {
      reasons.push(`rubric[${rubric.kind}] 全要素命中`);
    }
  }

  return { score, reasons, notes, truth: truth.checked ? truth : undefined, rubric: rubric.checked ? rubric : undefined, verdict: 'none' };
}

/**
 * 编造率抽检清单（§10.2 公平性规则 4：挑战者数字只能外部 SQL 复算）。
 * @param {Array<object>} tasks 题库题
 * @param {Array<{task: string, reply_full?: string, reply?: string}>|Object<string,string>} replies
 *        报告 results 数组（按 task 名对齐）或 {taskId: 回复全文} 映射
 * @returns {Array<{task: string, anchors: string[], expect_gap?: string[], reply_numbers: number[]}>}
 *          仅含带数字锚/缺口声明的题；reply_numbers=挑战者回复中出现的去重数字（复算对照物）
 */
export function buildAuditList(tasks, replies) {
  const byId = Array.isArray(replies)
    ? new Map(replies.map((x) => [x.task, String(x.reply_full ?? x.reply ?? '')]))
    : null;
  const replyOf = (id) => (byId ? (byId.get(id) ?? '') : String(replies?.[id] ?? ''));
  const out = [];
  for (const t of tasks) {
    if (byId && !byId.has(t.id)) continue; // 审查 P2：抽检清单只列实跑题（曾混入未跑题空行）
    const turns = Array.isArray(t.turns) && t.turns.length ? t.turns : null;
    const truth = turns ? (turns[turns.length - 1]?.truth ?? t.truth) : t.truth;
    const anchors = Array.isArray(truth?.anchors) ? truth.anchors : [];
    const gap = Array.isArray(truth?.expect_gap) ? truth.expect_gap : [];
    if (!anchors.length && !gap.length) continue;
    const reply = replyOf(t.id);
    const nums = reply
      ? [...new Set(extractNumberTokens(normalizeText(reply, DEFAULT_RULES)).map((x) => x.value))]
      : [];
    out.push({ task: t.id, anchors, ...(gap.length ? { expect_gap: gap } : {}), reply_numbers: nums });
  }
  return out;
}

// ── CLI（main-guard：被 import 时零副作用）——对 challenger 报告离线重判/抽检清单 ──
const IS_MAIN = (() => {
  try {
    return Boolean(process.argv[1])
      && import.meta.url === new URL(`file://${process.argv[1].replace(/\\/g, '/')}`).href;
  } catch { return false; }
})();

if (IS_MAIN) {
  const { readFileSync } = await import('node:fs');
  const { resolve } = await import('node:path');
  const files = process.argv.slice(2).filter((a) => !a.startsWith('--'));
  if (!files.length) {
    console.error('用法：node eval/challenger_check.mjs <challenger报告.json> [report2.json …]（离线重判 + 抽检清单）');
    process.exit(1);
  }
  const rules = { ...DEFAULT_RULES, ...JSON.parse(readFileSync(resolve(import.meta.dirname, 'scoring-rules.json'), 'utf-8')) };
  const TASKS = JSON.parse(readFileSync(resolve(import.meta.dirname, 'tasks.json'), 'utf-8'));
  const TASK_BY_ID = new Map(TASKS.map((t) => [t.id, t]));
  for (const f of files) {
    const report = JSON.parse(readFileSync(resolve(f), 'utf-8'));
    console.log('='.repeat(72));
    console.log(`挑战者报告重判: ${f}（run_id=${report.run_id || '-'}，verdict 通道=无）`);
    console.log('='.repeat(72));
    let diff = 0;
    for (const result of report.results || []) {
      if (result.error) { console.log(`  ${result.task}: 基建行（error），跳过`); continue; }
      const task = TASK_BY_ID.get(result.task);
      if (!task) { console.log(`  ${result.task}: 题库无此题，跳过`); continue; }
      const rep = challengerScore(task, result.reply_full ?? result.reply_preview ?? '', result.tools || [], null, rules);
      if (rep.score !== result.score) { diff++; console.log(`  ${result.task}: ${result.score} → ${rep.score}（${rep.reasons.join('; ')}）`); }
    }
    console.log(`  汇总: ${report.results?.length ?? 0} 题，diff ${diff} 题（其余重判分==报告分）`);
    const audit = buildAuditList(TASKS, report.results || []);
    console.log(`  抽检清单: ${audit.length} 题（含数字锚/缺口声明）——rows 已含 reply_numbers，供 SQL 复算`);
  }
}
