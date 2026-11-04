/**
 * 评估迭代基建包 · B3 金标数字比对纯函数（truth:{anchors,forbid}）
 *
 * 语义：anchors = 主结论数字（全部必须命中，缺失→score 封顶 2，由 runner 执行）；
 *      forbid = 禁值（命中→封顶 2）。无 truth 的题不比对（checked:false）。
 * 归一化：全角数字→半角 / 去千分位 /「万/亿」换算到锚点同单位（开关在 scoring-rules.json）。
 * 容差：默认精确匹配；tolerance_overrides[taskId] 支持 {pp,abs,rel}（首跑后校准只改规则文件）。
 * 规则外置：eval/scoring-rules.json（单位假设/万换算开关/校准位），本文件只实现机制。
 * 正反例契约：eval/truth_check.test.mjs（改本文件必须先改测试）。
 */

// 全角→半角（数字/小数点/百分号/逗号）
const FULLWIDTH = { '０': '0', '１': '1', '２': '2', '３': '3', '４': '4', '５': '5', '６': '6', '７': '7', '８': '8', '９': '9', '．': '.', '％': '%', '，': ',' };

export const DEFAULT_RULES = {
  version: 1,
  normalize: { fullwidth_digits: true, strip_thousands_separators: true },
  wan_conversion: { enabled: true, factor: 10000 },
  percent_unit_required: true,
  default_tolerance: { abs: 0 },
  tolerance_overrides: {},
};

/** 文本归一化：全角数字/％/．转半角 + 去千分位（数字间的逗号） */
export function normalizeText(text, rules = DEFAULT_RULES) {
  let s = String(text ?? '');
  if (rules.normalize?.fullwidth_digits !== false) {
    s = s.replace(/[０-９．％，]/g, (ch) => FULLWIDTH[ch] ?? ch);
  }
  if (rules.normalize?.strip_thousands_separators !== false) {
    let prev;
    do {
      prev = s;
      s = s.replace(/(\d),(\d)/g, '$1$2'); // 循环处理 1,234,567 链式千分位
    } while (s !== prev);
  }
  return s;
}

/**
 * 从归一化文本提取数字 token（带单位上下文）。
 * "4,436台"→{value:4436}；"0.63%"→{value:0.63,percent}；"19.98万"→{value:19.98,wan}。
 */
export function extractNumberTokens(normalized) {
  const tokens = [];
  const re = /(\d+(?:\.\d+)?)\s*(%|万|亿)?/g;
  let m;
  while ((m = re.exec(normalized)) !== null) {
    const value = parseFloat(m[1]);
    if (Number.isNaN(value)) continue;
    if (m[2] === '%') tokens.push({ value, percent: true });
    else if (m[2] === '万') tokens.push({ value, wan: true });
    else if (m[2] === '亿') tokens.push({ value, yi: true });
    else tokens.push({ value });
  }
  return tokens;
}

/** 锚点/禁值字符串 → {value, percent, wan, yi}；不合法（非纯数字+可选单位）返回 null */
export function parseAnchor(anchor) {
  const m = String(anchor ?? '').trim().match(/^([\d,]+(?:\.\d+)?)\s*(%|万|亿)?$/);
  if (!m) return null;
  return { raw: String(anchor), value: parseFloat(m[1].replace(/,/g, '')), percent: m[2] === '%', wan: m[2] === '万', yi: m[2] === '亿' };
}

/** token 换算到与锚点可比的量级（万/亿按规则开关折算；关闭开关则只认同单位字面值） */
function canonValue(a, rules) {
  const wanOn = rules.wan_conversion?.enabled !== false;
  const factor = rules.wan_conversion?.factor ?? 10000;
  return a.value * (a.wan && wanOn ? factor : 1) * (a.yi ? 10000 * factor : 1);
}

/** 单锚点 vs token 列表是否命中（含容差；forbid 一律精确无容差） */
function anchorHits(anchor, tokens, rules, tolerance) {
  const a = parseAnchor(anchor);
  if (!a) return false;
  const aCanon = canonValue(a, rules);
  for (const t of tokens) {
    if (rules.percent_unit_required !== false && a.percent !== !!t.percent) continue;
    const diff = Math.abs(aCanon - canonValue(t, rules));
    if (diff < 1e-9) return true; // 精确命中
    if (!tolerance) continue;
    if (a.percent && tolerance.pp != null && t.percent && diff <= tolerance.pp) return true;
    if (!a.percent && tolerance.abs != null && diff <= tolerance.abs) return true;
    if (tolerance.rel != null && diff <= Math.abs(tolerance.rel) * Math.abs(aCanon)) return true;
  }
  return false;
}

/**
 * @param {{id?: string, truth?: {anchors?: string[], forbid?: string[],
 *          text_anchors?: string[], text_forbid?: string[], expect_gap?: string[]}}} task
 *        多轮评估批 change 新增三语义字段（Gap1）：text_anchors=语义词全子串必中；
 *        text_forbid=语义禁词子串禁中；expect_gap=每条"/"分隔备选至少一选命中（缺口声明）。
 *        既有 anchors/forbid 仅数字锚——语义锚走新字段，既有题零字段零影响。
 * @param {string} reply agent 最终回复
 * @param {object} rules scoring-rules.json 内容
 * @returns {{checked: boolean, anchorsCount: number, missing: string[], forbidHits: string[]}}
 *          checked=false = 本题无 truth，不比对不降档
 */
export function checkTruth(task, reply, rules = DEFAULT_RULES) {
  const truth = task?.truth;
  const hasNum = Array.isArray(truth?.anchors) || Array.isArray(truth?.forbid);
  // 合法零锚形态（审查 P2-9 注明）：anchors=[] 保留结构 = checked:true/anchorsCount:0/missing:[]
  // ——摘锚题（sentiment-06）判分权重移交 rubric 要素；reasons 落"truth 锚点全中(0)"字样属预期读感。
  const hasText = Array.isArray(truth?.text_anchors) || Array.isArray(truth?.text_forbid) || Array.isArray(truth?.expect_gap);
  if (!truth || (!hasNum && !hasText)) {
    return { checked: false, anchorsCount: 0, missing: [], forbidHits: [] };
  }
  const normalized = normalizeText(reply, rules);
  const tokens = extractNumberTokens(normalized);
  const tolerance = rules.tolerance_overrides?.[task.id] ?? null;
  const anchors = Array.isArray(truth.anchors) ? truth.anchors : [];
  const forbid = Array.isArray(truth.forbid) ? truth.forbid : [];
  const missing = anchors.filter((a) => !anchorHits(a, tokens, rules, tolerance));
  const forbidHits = forbid.filter((f) => anchorHits(f, tokens, rules, null)); // 禁值无容差

  // ── 多轮语义字段（多轮评估批 change；子串匹配在归一化文本上做）─────────
  const textAnchors = Array.isArray(truth.text_anchors) ? truth.text_anchors : [];
  const textForbid = Array.isArray(truth.text_forbid) ? truth.text_forbid : [];
  const gapList = Array.isArray(truth.expect_gap) ? truth.expect_gap : [];
  for (const a of textAnchors) {
    if (!normalized.includes(normalizeText(a, rules))) missing.push(a);
  }
  // 语义禁词：否定语境豁免（"不能改成续航"/"不是虚标" 属正确表述，不应判违禁）
  const NEG_BEFORE_RE = /(不|非|没有|并非|不是|不能|不应|无需|谈不上|未|别)[^。\n]{0,8}$/;
  for (const f of textForbid) {
    const needle = normalizeText(f, rules);
    let idx = normalized.indexOf(needle);
    let hit = false;
    while (idx >= 0) {
      const before = normalized.slice(Math.max(0, idx - 14), idx);
      if (!NEG_BEFORE_RE.test(before)) { hit = true; break; }
      idx = normalized.indexOf(needle, idx + needle.length);
    }
    if (hit) forbidHits.push(f);
  }
  for (const g of gapList) {
    // 每条 = "/" 分隔备选，任一子串命中即满足（缺口声明词形多变，全列不现实）
    const alts = String(g).split('/').map((s) => s.trim()).filter(Boolean);
    if (!alts.some((s) => normalized.includes(normalizeText(s, rules)))) missing.push(`缺口声明(${g})`);
  }
  return { checked: true, anchorsCount: anchors.length, missing, forbidHits };
}
