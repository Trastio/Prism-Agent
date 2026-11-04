/**
 * Prism-Agent · 六分制评分器（T-2.4.2）
 *
 * 只管销量/配置（数值容差）。口碑走 2.3.3 单独一套。
 * 0-5 分：
 *   5=完全正确 / 4=数值小误差 / 3=口径错 / 2=缺证据 / 1=越界 / 0=编造
 */

import { compareMultiset, getSalesTruth, extractNumbersFromText } from '../src/verify/reference.ts';
import { groundResult } from '../src/verify/grounding.ts';
import { verifyCompletion, type Claim } from '../src/verify/completion.ts';

export interface ScoreInput {
  taskId: string;
  dimension: '销量' | '配置' | '口碑' | '舆情' | '跨维度';
  modelReply: string;
  claim: Claim;
  expectedNumbers?: number[];   // 销量/配置数值
  identity_coverage?: unknown;
}

export interface ScoreResult {
  taskId: string;
  score: 0 | 1 | 2 | 3 | 4 | 5;
  reasons: string[];
}

/** 六分制评分 */
export function scoreTask(input: ScoreInput): ScoreResult {
  const reasons: string[] = [];
  let score: 0 | 1 | 2 | 3 | 4 | 5 = 5;

  // 1. 完成验证器（越界/无证据/数据缺口）
  const verify = verifyCompletion(`eval-${input.taskId}`, input.claim, input.identity_coverage);
  if (!verify.pass) {
    reasons.push(...verify.failures);
    // 越界=1，无证据=2，数据缺口=2
    if (verify.failures.some((f) => f.includes('越界'))) score = 1;
    else if (verify.failures.some((f) => f.includes('supported_by') || f.includes('缺口'))) score = 2;
    else score = 2;
  }

  // 2. 名称 + 数值 grounding
  const ground = groundResult(input.modelReply, input.expectedNumbers ?? [], []);
  if (!ground.name_check.pass) {
    reasons.push(...ground.name_check.mismatches);
    if (score > 0) score = 0;   // 名称编造 = 0
  }
  if (!ground.number_check.pass) {
    reasons.push(...ground.number_check.mismatches);
    if (score > 3) score = 3;   // 数值错 = 3（口径错）
    else if (score > 4) score = 4;
  }

  // 3. 数值容差（销量/配置）
  if (input.expectedNumbers && input.expectedNumbers.length > 0) {
    const actual = extractNumbersFromText(input.modelReply)
      .filter((n) => n > 100 && (n < 2020 || n > 2030));
    const cmp = compareMultiset(input.expectedNumbers, actual, 0.02);
    if (!cmp.pass && score === 5) {
      // 数值小误差 → 4
      reasons.push(...cmp.mismatches);
      score = 4;
    }
  }

  return { taskId: input.taskId, score, reasons };
}
