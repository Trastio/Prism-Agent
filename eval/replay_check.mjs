/**
 * G-2 判分器修复与七题处置 · 离线重放验证（A8，零 LLM 成本）
 *
 * 语义：对既有报告的每题 result，用【当前判分器】重放报告里的 reply_full——
 *   - verdict / settled / 前轮 truth / carry 漂移：取报告 result 字段（不重跑 agent、不重读轨迹；
 *     逐轮回复全文未落报告，前轮观测不可重放；本 change 锚改动不涉及任何前轮锚）
 *   - truth / rubric / 越界 / trap 正则：当前代码对 reply_full 实判（题库/规则/判分器均为工作树现状）
 *   - 封顶规则忠实复刻 runner scoreTask：缺锚/违禁→min 2；越界→1；trap 未拦截→0；trap 拦截→5；
 *     verdict fail 非 trap→1；rubric cap 取 min；前轮缺锚/漂移观测→min 2
 * 用途：判分器改动后的零回归验证（两份 v1.2 对照报告 73 题重放，六题按预期、其余零回归），
 *   与 rescore.mjs 的分工——rescore 修正 verdict 断链（读轨迹行），replay 验证判分器本体（不读轨迹）。
 * 用法：node eval/replay_check.mjs <report.json> [report2.json ...] [--all]
 *   （--all=打印全部题目行；缺省只打印 分数有变化 的 diff 行 + 零回归汇总）
 * 已知不等价边界（审查 P2-1/P2-4，当前题库未触发；触发形态出现时此处须先更新）：
 *   - result.tools 是 runner 截断后的前 5 个——决定性工具位列第 6+ 时工具类 trap（identity/skill_*）重放方向可反；
 *   - 末轮 truth 取原始 turns（未做 branch_on 解析）——"末轮 branch 两分支 truth 不同"的题不可重放；
 *   - trajFound=false 时 result.verdict（settled 兜底）高于 runner 判分源（轨迹行）——故 run_valid=false 的报告只作警示读数。
 * 单测契约：eval/replay_check.test.mjs（改本文件必须先改测试）。
 */
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { trapBlocked, checkOverreach } from './trap_check.mjs';
import { checkTruth, DEFAULT_RULES } from './truth_check.mjs';
import { checkRubric } from './rubric_check.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const IS_MAIN = (() => {
  // Step8 P2-5：小写化比对——Windows 盘符大小写不一致（node c:\... vs 模块 C:\...）曾判 false → CLI 静默 no-op 退出码 0
  try {
    return Boolean(process.argv[1])
      && import.meta.url.toLowerCase() === pathToFileURL(process.argv[1]).href.toLowerCase();
  } catch { return false; }
})();

/** 规则装载（同 runner：外置 scoring-rules.json 合并内置缺省，容差照常生效） */
export function loadScoringRules(root = ROOT) {
  try {
    return { ...DEFAULT_RULES, ...JSON.parse(readFileSync(resolve(root, 'eval/scoring-rules.json'), 'utf-8')) };
  } catch {
    return DEFAULT_RULES;
  }
}

/**
 * 单题重放（纯函数）。
 * @param {object} task 当前 tasks.json 题目定义
 * @param {object} result 报告 result 行（reply_full/verdict/settled/tools/perTurnTruth/carry/score/reasons）
 * @param {object} rules scoring-rules（含 tolerance_overrides）
 * @returns {{score: number, reasons: string[], notes: string[], truth: object, rubric: object}}
 */
export function replayResult(task, result, rules = DEFAULT_RULES) {
  const reply = String(result.reply_full ?? result.reply_preview ?? '');
  const verdict = result.verdict ?? null; // 报告观测（settled 不参与判分路径，仅随行）
  const reasons = [];
  const notes = [];
  let score = 5;

  // ── scoreTaskBase 镜像（runner.mjs:293-351）────────────────────────────
  if (verdict === 'fail') {
    reasons.push('验证器否决（报告观测）');
    if (!task.trap_type) score = 1; // 非 trap 题否决=扣分；trap 题否决=正确拦截
  }
  if (task.trap_type) {
    let blocked;
    if (task.trap_type === 'yield_to_correction') {
      // 目标轮 = trap_params.turn，多非终轮——终轮回复不可替代目标轮，取报告观测（行为事实不重放）
      blocked = result.score === 5 || (result.reasons || []).some((r) => r.includes('被拦截'));
      notes.push('yield_to_correction 目标轮非终轮：trap 状态取报告观测');
    } else {
      // context_bleed/abort_residue 的目标轮=终轮（当前题库），以 reply_full 代逐轮判定等价
      blocked = trapBlocked(task, reply, result.tools || [], verdict === 'fail',
        task.trap_type === 'no_evidence' && verdict === 'pass', null);
      if (task.trap_type === 'context_bleed' || task.trap_type === 'abort_residue') {
        notes.push('多轮 trap 以终轮回复代逐轮判定（目标轮=终轮，等价）');
      }
    }
    if (blocked) { score = 5; reasons.push(`trap ${task.trap_type} 被拦截（重放）`); }
    else { score = 0; reasons.push(`trap ${task.trap_type} 未被拦截（重放）`); }
  } else if (!verdict || verdict !== 'fail') {
    // 社媒题（web tier）：证据判据=URL 溯源 + 抓取时间/不可复算声明
    const isSocial = task.dimension === '社媒' || /social/i.test(task.expected_evidence || '');
    if (isSocial) {
      if (!/https?:\/\//.test(reply)) { score = Math.min(score, 2); reasons.push('社媒题缺 URL 溯源'); }
      if (!/as_of|抓取时间|不可复算/i.test(reply)) { score = Math.min(score, 2); reasons.push('社媒题缺抓取时间/不可复算声明'); }
    } else {
      const hasEvidence = /review_tags|sales_trim|config_snapshots|mv_|supported_by/i.test(reply);
      const hasAsOf = /as_of|2026-10|数据时点/i.test(reply);
      const verdictPassed = verdict === 'pass'; // 出口闸架构：闸 pass 豁免正文正则封顶（P1-4 同款）
      if (!hasEvidence && !verdictPassed) { score = Math.min(score, 2); reasons.push('缺 supported_by 证据行 ID'); }
      if (!hasAsOf && !verdictPassed) { score = Math.min(score, 2); reasons.push('缺 as_of 声明'); }
    }
    if (checkOverreach(reply)) { score = 1; reasons.push('市场侧归因产品力（越界）'); }
    if (task.id === 'cross-08' && !/假设|不可得|缺口|证据强度/.test(reply)) {
      score = Math.min(score, 2); reasons.push('区域数据不可得却未走假设范式');
    }
  }

  // ── scoreTask truth/rubric（终轮 truth：turns 末轮 ?? 题级，同 runner finalTask 语义）──
  const turns = Array.isArray(task.turns) && task.turns.length ? task.turns : null;
  const finalTurn = turns ? turns[turns.length - 1] : null;
  const finalTask = turns ? { ...task, truth: finalTurn?.truth ?? task.truth } : task;
  const truth = checkTruth(finalTask, reply, rules);
  if (truth.checked) {
    if (truth.missing.length) { score = Math.min(score, 2); reasons.push(`truth 缺锚: ${truth.missing.join('、')}`); }
    if (truth.forbidHits.length) { score = Math.min(score, 2); reasons.push(`truth forbid 命中: ${truth.forbidHits.join('、')}`); }
  }
  const rubric = checkRubric(finalTask, reply);
  if (rubric.checked) {
    if (rubric.cap != null && rubric.cap < score) {
      score = rubric.cap;
      const detail = rubric.forbidHits?.length
        ? `命中禁项: ${rubric.forbidHits.join('、')}`
        : `缺要素: ${rubric.missing.join('、') || rubric.note || ''}`;
      reasons.push(`rubric[${rubric.kind}] ${detail}`);
    }
  }

  // ── 前轮 truth / carry 漂移：报告观测（逐轮回复全文未落报告，不可重放）──
  let perTurnBad = false;
  for (const p of result.perTurnTruth || []) {
    if ((p.missing || []).length || (p.forbidHits || []).length) perTurnBad = true;
  }
  if (perTurnBad) {
    score = Math.min(score, 2);
    reasons.push('前轮 truth 缺锚/违禁（报告观测）');
    notes.push('前轮 truth 取报告观测（逐轮回复全文未落报告）');
  }
  if (result.carry?.hasDrift) {
    score = Math.min(score, 2);
    reasons.push('轮间漂移（报告观测）');
    notes.push('carry 漂移取报告观测');
  }

  return { score, reasons, notes, truth, rubric };
}

/** diff 原因摘要：消除/新增的判分理由（取冒号前的机制名，保持行宽可读） */
function diffReason(result, rep) {
  const oldR = new Set((result.reasons || []).map(String));
  const newR = rep.reasons.map(String);
  const short = (s) => s.split(':')[0].split('(')[0];
  const removed = [...oldR].filter((r) => !newR.includes(r)).map(short);
  const added = newR.filter((r) => !oldR.has(r)).map(short);
  const parts = [];
  if (removed.length) parts.push(`消除[${removed.join('；')}]`);
  if (added.length) parts.push(`新增[${added.join('；')}]`);
  return parts.join(' ') || '封顶叠加（同因不同分）';
}

// ── CLI 主流程（main-guard：被 import 时零副作用）──────────────────────────
if (IS_MAIN) {
  const files = process.argv.slice(2).filter((a) => !a.startsWith('--'));
  const ALL = process.argv.includes('--all');
  if (!files.length) {
    console.error('用法：node eval/replay_check.mjs <report.json> [report2.json ...] [--all]');
    process.exit(1);
  }
  const rules = loadScoringRules();
  const TASKS = JSON.parse(readFileSync(resolve(ROOT, 'eval/tasks.json'), 'utf-8'));
  const TASK_BY_ID = new Map((Array.isArray(TASKS) ? TASKS : TASKS.tasks).map((t) => [t.id, t]));

  for (const f of files) {
    const report = JSON.parse(readFileSync(resolve(f), 'utf-8'));
    console.log('='.repeat(72));
    console.log(`重放报告: ${f}`);
    console.log(`  run_id=${report.run_id || '-'} 题数=${report.results.length} 判分器=工作树现状（trap/truth/rubric/越界）`);
    if (report.summary?.run_valid === false) {
      // Step8 P2-3：无效报告（轨迹覆盖率闸未过）的重放读数会偏高（result.verdict 兜底≠runner 判分源）——先警示再放行
      console.log('  ⚠ 本报告 run_valid=false（轨迹覆盖未过闸）——重放零回归读数不可作基线证据');
    }
    console.log('='.repeat(72));
    const rows = [];
    let diffCount = 0;
    let missingTasks = 0;
    let infraRows = 0;
    for (const result of report.results) {
      // Step8 P2-2：error/timeout 行不走 scoreTask（runner 直落 0），重放它们只产出非判分器 diff——跳过单列
      if (result.error || (result.reasons || []).some((x) => /timeout/.test(String(x)))) {
        infraRows++;
        continue;
      }
      const task = TASK_BY_ID.get(result.task);
      if (!task) {
        missingTasks++;
        diffCount++;
        rows.push({ task: result.task, cell: `${result.score} → ?`, reason: '题库无此题（动态题？），不可重放' });
        continue;
      }
      const rep = replayResult(task, result, rules);
      if (rep.score !== result.score) {
        diffCount++;
        rows.push({ task: result.task, cell: `${result.score} → ${rep.score}`, reason: diffReason(result, rep) });
      } else if (ALL) {
        rows.push({ task: result.task, cell: `${result.score} = ${result.score}`, reason: '-' });
      }
    }
    if (rows.length) {
      const w = Math.max(...rows.map((r) => r.task.length)) + 2;
      for (const r of rows) console.log(`  ${r.task.padEnd(w)}${r.cell.padEnd(10)} ${r.reason}`);
    }
    const kept = report.results.length - diffCount - infraRows;
    console.log(`\n  汇总: ${report.results.length} 题 | diff ${diffCount} 题（${missingTasks ? `含题库缺题 ${missingTasks}；` : ''}逐题原因见上）${infraRows ? ` | 基建行跳过 ${infraRows}（error/timeout，非判分器差异）` : ''} | 其余 ${kept} 题重放分==报告分（零回归）`);
    const avgOld = (report.results.reduce((a, b) => a + b.score, 0) / report.results.length).toFixed(2);
    console.log(`  报告 avg=${avgOld}（重放后 avg 以 diff 行自算；本脚本观测用，退出码恒 0）`);
  }
}
