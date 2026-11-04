/**
 * Prism-Agent · 数字台账（出口闸配套，M1）
 *
 * 三级信任（方案 v1.4/v1.5）：
 * - truth            工具返回的度量值（真值集）
 * - declared-derived submission pass 回写的派生值（弱信任：仅供复述放行，不得作 derived_from 源）
 * - 排除项           标识符 key（*_id/year/month/年款）与错误载荷（isError / status:'unavailable'）
 *
 * 归一化细则（3.5 Gap3 定死）：去负号、去 %、去千分位、去单位、去空白；
 * 小数去尾零；结果一律字符串。散文抽取沿用 NUMERIC_CLAIM_RE 单位口径（年/月不触发）。
 * 百分比/万 换算桥接：prose "69.2%" ↔ 工具 0.692、"0.44万辆" ↔ 4436（确定性变换非模糊匹配）。
 */

/** 标识符类 key：值不入台账（v1.4 P-b） */
function isIdKey(key: string): boolean {
  return /_id$/.test(key) || ['year', 'month', 'day', 'hour', '年款', 'rank', 'index'].includes(key);
}

/** 数值规整：消除浮点噪声（0.692*100 → 69.2 而非 69.19999...） */
function roundTrim(x: number): string {
  return String(Number(x.toPrecision(10)));
}

/** 归一化：'−14.1%' / '4,436 辆' / '4436' → '14.1' / '4436' / '4436'；非纯数值返回 '' */
export function normalizeNumber(raw: string): string {
  let s = raw.trim()
    .replace(/[−–—]/g, '-')
    .replace(/,/g, '')
    .replace(/(万辆|万台|公里|km|辆|台|%|分|元|条|位|个)/gi, '')
    .replace(/^-/, '')
    .trim();
  if (!/^\d+(\.\d+)?$/.test(s)) return '';
  if (s.includes('.')) {
    // 精度对齐（与台账 roundTrim 同源）：模型抄全精度浮点（106754.66666666672）
    // 与台账 10 位有效数字（106754.6667）统一表示，防误拒
    s = String(Number(Number(s).toPrecision(10)));
    if (s.includes('.')) s = s.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '');
  }
  return s;
}

export interface ProseToken { value: string; percent: boolean; wan: boolean; }

/** 散文数字抽取：单位口径同 NUMERIC_CLAIM_RE，但数字形态补齐千分位（"4,436 辆"）与
 * 单位前导小数（"0.44万辆"）；年份/月份因无度量单位天然不触发 */
const PROSE_NUM_RE = /(?<![\d.])(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(万辆|万台|辆|台|%|分|公里|km|元|条|位|个)/gi;

export function extractProseTokens(text: string): ProseToken[] {
  const out: ProseToken[] = [];
  let m: RegExpExecArray | null;
  const re = new RegExp(PROSE_NUM_RE.source, 'gi');
  while ((m = re.exec(text)) !== null) {
    const value = normalizeNumber(m[0]);
    if (!value) continue;
    const unit = (m[1] || '').toLowerCase();
    out.push({ value, percent: unit === '%', wan: unit.startsWith('万') });
  }
  return out;
}

/** 确定性换算变体：百分桥（÷100）与万桥（×10000） */
export function valueVariants(value: string, percent: boolean, wan: boolean): string[] {
  const vs = new Set<string>([value]);
  const n = parseFloat(value);
  if (Number.isFinite(n) && n !== 0) {
    if (percent) vs.add(roundTrim(n / 100));
    if (wan) vs.add(roundTrim(n * 10000));
  }
  return [...vs];
}

/** 台账命中判定（②保底与 submit 校验共用）——入口先归一化（精度对齐在 normalizeNumber 内） */
export function ledgerHasValue(set: Set<string>, value: string, percent = false, wan = false): boolean {
  const v = normalizeNumber(value);
  if (!v) return false;
  for (const variant of valueVariants(v, percent, value.includes('万') || wan)) {
    if (set.has(variant)) return true;
  }
  return false;
}

/** 从工具返回 JSON 文本抽取台账值（跳过标识符 key；调用方先跳过错误载荷） */
export function extractLedgerValues(jsonText: string): string[] {
  let data: unknown;
  try { data = JSON.parse(jsonText); } catch { return []; }
  const out = new Set<string>();
  (function walk(node: unknown, key: string | null) {
    if (node === null || node === undefined) return;
    if (Array.isArray(node)) { for (const x of node) walk(x, key); return; }
    if (typeof node === 'object') { for (const [k, v] of Object.entries(node as Record<string, unknown>)) walk(v, k); return; }
    if (typeof node === 'number' && Number.isFinite(node)) {
      if (key && isIdKey(key)) return;
      out.add(roundTrim(node));
      return;
    }
    // 字符串值不抽（as_of/名称/日期等均为字符串；散文形态数字由 prose 路径处理）
  })(data, null);
  return [...out];
}

/** 错误载荷识别（3.5 Gap 与 C3 对齐）：isError 文本 / unavailable 结构不抽台账 */
export function looksLikeErrorPayload(text: string): boolean {
  const t = text.trim();
  if (!t.startsWith('{') && !t.startsWith('[')) {
    // 现行错误返回为纯文本（"错误: HTTP 502" / "工具错误: ..." / "舆情接口错误: ..."）
    return /(^|\n)(错误|工具错误|接口错误|舆情接口错误|Atuohome 接口错误|身份解析错误|resolve_series 错误)/.test(t);
  }
  try {
    const obj = JSON.parse(t);
    return obj?.status === 'unavailable' || obj?.isError === true;
  } catch { return true; }
}

export interface NumericLedger { truth: Set<string>; declaredDerived: Set<string>; }

/** 读取会话台账：union 全部 prism-numeric-truth entries（kind 区分信任级） */
export function readNumericLedger(entries: unknown[]): NumericLedger {
  const truth = new Set<string>();
  const declaredDerived = new Set<string>();
  for (const e of entries as Array<Record<string, any>>) {
    if (e?.customType !== 'prism-numeric-truth') continue;
    const values: unknown = e?.data?.values;
    if (!Array.isArray(values)) continue;
    const target = e?.data?.kind === 'declared-derived' ? declaredDerived : truth;
    for (const v of values) {
      if (typeof v === 'string' && v) target.add(v);
    }
  }
  return { truth, declaredDerived };
}
