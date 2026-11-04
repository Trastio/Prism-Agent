/** 验证器回灌通知前缀（单源常量）。
 * M2 教训：前缀字面量在 extension 与前端手抄两处，文案一改即静默断裂——
 * 本常量 + truth_envelope.test.ts 的双侧文件对账断言防回归。
 * 注意：不带闭括号 ']'——'·' 在 ']' 前，带上会让前缀匹配变脆（历史事故）。 */
export const VERIFIER_NOTICE_PREFIX = '[完成验证器';
