/**
 * Prism-Agent · 口碑定性结论单独一套（T-2.3.3）
 *
 * 六分制对口碑失效（定性结论非数值），单独一套：
 * - claim 溯源：每个口碑结论附 supported_by 行 ID + 原文样本
 * - 人工抽检：抽样 10% 口碑结论人工核对
 *
 * 教材 human-benchmark 模式
 */

export interface KoubeiClaim {
  conclusion: string;
  supported_by: string[];      // review_tags: model_id/tag/sentiment
  sample_reviews: Array<{
    review_id: string;
    source_text: string;
    tag_name: string;
  }>;
  coverage_note: string;       // 打标覆盖率说明
}

/** 构造口碑 claim（要求附原文样本） */
export function buildKoubeiClaim(
  conclusion: string,
  supported_by: string[],
  sample_reviews: KoubeiClaim['sample_reviews'],
  coverage_rate: number
): KoubeiClaim {
  return {
    conclusion,
    supported_by,
    sample_reviews,
    coverage_note: `打标覆盖率 ${(coverage_rate * 100).toFixed(1)}%`,
  };
}

/** 人工抽检：从口碑 claim 列表抽样 N 条 */
export function sampleForAudit(claims: KoubeiClaim[], rate = 0.1, min = 5): KoubeiClaim[] {
  const n = Math.max(min, Math.ceil(claims.length * rate));
  if (claims.length <= n) return claims;
  // 均匀抽样
  const step = Math.floor(claims.length / n);
  const sampled: KoubeiClaim[] = [];
  for (let i = 0; i < n; i++) {
    sampled.push(claims[i * step]);
  }
  return sampled;
}

/** 抽检结果记录（写 koubei_claims_audit.md） */
export interface AuditRecord {
  claim_conclusion: string;
  review_id: string;
  source_text: string;
  result: 'pass' | 'fail' | '边界';
  note?: string;
}

export function formatAuditReport(records: AuditRecord[]): string {
  const lines = ['# 口碑定性结论 · 人工抽检记录', ''];
  for (const r of records) {
    lines.push(`## ${r.review_id}`);
    lines.push(`- 结论: ${r.claim_conclusion}`);
    lines.push(`- 原文: ${r.source_text}`);
    lines.push(`- 结果: ${r.result}${r.note ? `（${r.note}）` : ''}`);
    lines.push('');
  }
  const pass = records.filter((r) => r.result === 'pass').length;
  const fail = records.filter((r) => r.result === 'fail').length;
  const edge = records.filter((r) => r.result === '边界').length;
  lines.push(`---`);
  lines.push(`汇总: ${records.length} 条 · pass ${pass} / fail ${fail} / 边界 ${edge}`);
  return lines.join('\n');
}
