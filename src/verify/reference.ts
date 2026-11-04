/**
 * Prism-Agent · 真值校验（T-2.3.4）
 *
 * 纯 Python 多重集容差比对（教材 reference.py 模式）。
 * 构造 expected_multiset（从物化视图取真值），与 agent 回复提取的数值多重集比对。
 *
 * 容差：销量 ±2%（口径差异），配置 0 容差（精确）
 */

import { openAutohomeForTools } from '../tools/_shared.ts';

export interface ReferenceCheck {
  pass: boolean;
  expected: number[];
  actual: number[];
  mismatches: string[];
}

/** 从 sales_trim 取真值序列（实时；口径 = refresh.py 的 mv_sales_monthly：月末行按 series+year+month 汇总）
 *  retail_sum = SUM(retail)；ORDER BY 月号数字（等同物化视图的 month int 排序） */
export function getSalesTruth(series: string, year: number): number[] {
  const db = openAutohomeForTools();
  try {
    const rows = db
      .prepare(
        `SELECT SUM(retail) AS retail_sum
           FROM sales_trim
          WHERE series=? AND year=? AND month LIKE '%月末'
          GROUP BY month
          ORDER BY CAST(TRIM(REPLACE(month,'月末','')) AS INTEGER)`
      )
      .all(series, year) as { retail_sum: number }[];
    return rows.map((r) => r.retail_sum);
  } finally {
    db.close();
  }
}

/** 从 review_tags 取维度 pro/con 真值（实时；口径 = refresh.py 的 mv_reviews_dim：
 *  按 (model_id, tag_category) 统计 sentiment ∈ pro/con 的标签行数） */
export function getReviewsTruth(model_id: number): Record<string, { pro: number; con: number; total: number }> {
  const db = openAutohomeForTools();
  try {
    const rows = db
      .prepare(
        `SELECT tag_category,
                COUNT(CASE WHEN sentiment IN ('pro','1','正面') THEN 1 END) AS pro_count,
                COUNT(CASE WHEN sentiment IN ('con','-1','负面') THEN 1 END) AS con_count
           FROM review_tags
          WHERE CAST(model_id AS TEXT)=?
          GROUP BY tag_category`
      )
      .all(String(model_id)) as { tag_category: string; pro_count: number; con_count: number }[];
    const out: Record<string, { pro: number; con: number; total: number }> = {};
    for (const r of rows) {
      out[r.tag_category] = {
        pro: r.pro_count,
        con: r.con_count,
        total: r.pro_count + r.con_count,
      };
    }
    return out;
  } finally {
    db.close();
  }
}

/** 数值多重集容差比对 */
export function compareMultiset(
  expected: number[],
  actual: number[],
  tolerance = 0.02
): ReferenceCheck {
  const mismatches: string[] = [];
  const used = new Array(actual.length).fill(false);

  for (const exp of expected) {
    let found = false;
    for (let i = 0; i < actual.length; i++) {
      if (used[i]) continue;
      if (Math.abs(actual[i] - exp) / Math.max(exp, 1) <= tolerance) {
        used[i] = true;
        found = true;
        break;
      }
    }
    if (!found) {
      mismatches.push(`真值 ${exp} 在 agent 回复中未找到匹配`);
    }
  }

  // 反向：actual 里未被匹配的
  for (let i = 0; i < actual.length; i++) {
    if (!used[i]) {
      mismatches.push(`agent 回复 ${actual[i]} 无对应真值`);
    }
  }

  return {
    pass: mismatches.length === 0,
    expected,
    actual,
    mismatches,
  };
}

/** 从文本提取数值（复用 grounding 的 extractNumbers，但返回纯数值） */
export function extractNumbersFromText(text: string): number[] {
  // 简化版：匹配数字 + 可选万/亿
  const re = /(\d+(?:\.\d+)?)\s*(万|亿)?/g;
  const nums: number[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const n = parseFloat(m[1]);
    const scale = m[2] === '万' ? 10000 : m[2] === '亿' ? 100000000 : 1;
    nums.push(n * scale);
  }
  return nums;
}
