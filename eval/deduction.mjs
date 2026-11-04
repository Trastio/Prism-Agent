/**
 * Prism-Agent · 判分账本（deduction_trace）
 *
 * 目的：把"5 分是怎么被扣到 N 分的"逐条记成结构化步骤，而不是只留一串 reasons 文本。
 * 扣分语义与 eval/rescore.mjs 原 scoreFromReasons 完全一致（同一条规则表），
 * 因此同一份 reasons 在这里重算出的分数必须等于 runner 的官方分——报告里的
 * deduction_trace.consistent 就是这个不变式的自证位。
 *
 * 纯函数，无 I/O；只依赖判分器（trap_check/rubric_check），不反过来被它们依赖。
 * 2026-10-29：由 rescore.mjs 上移（避免 runner 与 rescore 两处各写一份规则）。
 */
import { checkOverreach } from './trap_check.mjs';
import { checkRubric } from './rubric_check.mjs';

/** 单条 reason → 扣分档位；返回 null 表示该 reason 不改变分数 */
function capFor(reason, task, reply) {
  // 数字错误 > 缺证据：多轮形态 "truth[t1] 缺锚/违禁" 与单轮前缀同档
  if (reason.startsWith('truth 缺锚') || reason.startsWith('truth forbid') || /^truth\[t\d+\] (缺锚|违禁)/.test(reason)) return 2;
  if (reason === '市场侧归因产品力（越界）') return checkOverreach(reply) ? 1 : null; // 免责形态不降分
  if (reason === '区域数据不可得却未走假设范式') return 2;
  if (reason.startsWith('社媒题缺')) return 2;
  if (reason === '缺 supported_by 证据行 ID' || reason === '缺 as_of 声明') return 2;
  if (reason.startsWith('轮间漂移')) return 2;
  if (reason.startsWith('rubric[') && (reason.includes('缺要素') || reason.includes('命中禁项'))) {
    const rub = checkRubric(task, reply);
    return rub.cap ?? null;
  }
  if (reason.startsWith('验证器否决')) return 1; // 非 trap 题；trap 题的否决由 trap 分支单独处理
  return null;
}

/**
 * 从 reasons 复算分数并产出扣分账本。
 * @returns {{base:number, score:number, steps:Array<{from:number,to:number,reason:string}>}}
 */
export function deductionFromReasons(reasons, task, reply) {
  let score = 5;
  const base = 5;
  const steps = [];
  for (const r of reasons || []) {
    const cap = capFor(r, task, reply);
    if (cap == null) continue;
    if (cap < score) {
      steps.push({ from: score, to: cap, reason: r });
      score = cap;
    }
  }
  return { base, score, steps };
}

/** 兼容旧调用点（rescore/单测）：只要分数时用这个 */
export function scoreFromReasons(reasons, task, reply) {
  return deductionFromReasons(reasons, task, reply).score;
}
