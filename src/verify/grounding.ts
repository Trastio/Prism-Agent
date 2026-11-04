/**
 * Prism-Agent · tool_result grounding（T-2.2.5）
 *
 * 数值维度 + 名称维度（spec §2.2.5）：
 * - 数值：QUANTITY_FLOOR=1000，_SCALES 加"万/亿"，容差比对
 * - 名称：series/brand/model_name/tag_category/manufacturer 精确匹配
 *
 * 阶段1 复审 8 个名称错误做测试集（修报告①②③）：
 * 1. 探索型→探索版  2. 启航型→公务版  3. 全域精灵版→全球精灵版
 * 4. 铂智7 SUV→三厢轿车  5. 星纪元ET08→比亚迪海豹08
 * 6. 蔚来Z9→腾势Z9  7. 智驾版→激光雷达版  8. 一汽丰田GAC→广汽丰田
 *
 * 教材 §3.1 chapter1/grounding.py 照抄 + 名称扩展
 * 红线#1：数据真实性
 */

// ---------------------------------------------------------------------------
// 数值 grounding
// ---------------------------------------------------------------------------

export const QUANTITY_FLOOR = 1000;

/** 数值比例匹配表（教材 _SCALES，加"万/亿"） */
const SCALES: Record<string, number> = {
  '万': 10000,
  '亿': 100000000,
  'k': 1000,
  'K': 1000,
  'M': 1000000,
};

interface ExtractedNumber {
  value: number;
  raw: string;
}

/** 从文本提取数值（带"万/亿"单位） */
export function extractNumbers(text: string): ExtractedNumber[] {
  const results: ExtractedNumber[] = [];
  // 匹配 数字 + 可选单位
  const re = /(\d+(?:\.\d+)?)\s*(万|亿|k|K|M)?/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const num = parseFloat(m[1]);
    const scale = m[2] ? SCALES[m[2]] ?? 1 : 1;
    if (num * scale >= QUANTITY_FLOOR) {
      results.push({ value: num * scale, raw: m[0] });
    }
  }
  return results;
}

/** 数值容差比对：模型回复的数值 vs 工具返回的数值 */
export function verifyNumbers(
  modelText: string,
  toolNumbers: number[],
  tolerance = 0.02   // 销量±2%，配置 0 容差
): { pass: boolean; mismatches: string[] } {
  const extracted = extractNumbers(modelText);
  const mismatches: string[] = [];

  for (const tNum of toolNumbers) {
    // 在模型回复里找匹配的数值（容差内）
    const matched = extracted.some((e) => Math.abs(e.value - tNum) / tNum <= tolerance);
    if (!matched) {
      mismatches.push(`工具返回 ${tNum}，模型回复未在容差内出现`);
    }
  }

  // 反向：模型回复里的大数值，工具没返回
  for (const e of extracted) {
    const matched = toolNumbers.some((t) => Math.abs(e.value - t) / t <= tolerance);
    if (!matched) {
      mismatches.push(`模型回复 ${e.raw}（${e.value}），工具未返回该数值`);
    }
  }

  return { pass: mismatches.length === 0, mismatches };
}

// ---------------------------------------------------------------------------
// 名称 grounding（新增，修阶段1 复审 8 错误）
// ---------------------------------------------------------------------------

/** 从工具返回收集名称真值集 */
export function collectNameTruth(toolResults: Array<Record<string, unknown>>): Set<string> {
  const truth = new Set<string>();
  // 2026-10-11 出口闸舆情源登记（G1）：追加 canonical_name（resolve_series 权威名）/
  // dim（舆情维度）/ event_tag（舆情事件）/ platform（平台名，防"抖音/快手"误报）——
  // 舆情轮次不调 query_* 时真值集也需要锚点，否则品牌/维度/平台词全进 findClosest 误报
  const NAME_FIELDS = ['series', 'brand', 'model_name', 'tag_category', 'manufacturer', 'series_name', '车型名称',
    'canonical_name', 'dim', 'event_tag', 'platform'];
  for (const r of toolResults) {
    for (const f of NAME_FIELDS) {
      const v = r[f];
      if (typeof v === 'string' && v.length > 0) truth.add(v);
    }
  }
  return truth;
}

/**
 * C1 通用域白名单（2026-10-14 评估迭代基建包）：维度/业务通用词不承载车系/品牌/
 * 版型身份，白名单词不构成名称冲突。R1-deep 实案（出口闸舆情源登记 review-response）：
 * conclusion_text 里"销量、口碑、配置"式罗列的 2 字普通词对任意 2 字维度真值
 * （如"电耗"）findClosest 恒 d≤2 → 误报"疑似人工转写"致出口闸同轮自纠 1~3 次。
 * 改阈值会破 8 case 张冠李戴检测（蔚来Z9/一汽丰田GAC），故走分类层：白名单外
 * 仍走既有阈值，8 case 检测不动。
 */
const GENERIC_DOMAIN_WORDS = new Set([
  '销量', '口碑', '配置', '舆情', '市场', '对比', '分析', '智能',
  '空间', '续航', '外观', '内饰', '价格', '性价比', '驾驶', '安全',
  '舒适', '质量', '售后', '服务',
]);

/** 白名单词按长度降序的拼接正则（供 isGenericPhrase 剥离用） */
const GENERIC_DOMAIN_RE = new RegExp(
  `(?:${[...GENERIC_DOMAIN_WORDS].sort((a, b) => b.length - a.length).join('|')})`,
  'g'
);

/**
 * 泛域短语判定：token 剥掉全部通用域词后残部 ≤1 字（如"外观和内饰对比分析"
 * → 残部"和"）→ 该 token 不承载身份，不构成名称冲突、也不作为张冠李戴证据。
 * 残部 >1 字（如"蔚来"）仍按身份词处理。
 */
function isGenericPhrase(token: string): boolean {
  if (GENERIC_DOMAIN_WORDS.has(token)) return true;
  const residue = token.replace(GENERIC_DOMAIN_RE, '');
  return residue.length <= 1;
}

/**
 * 名称精确匹配：模型回复里的名称 vs 工具返回的名称真值集
 * 不一致 → fail-closed
 *
 * 阶段1 测试集（8 条）：
 * - "探索型" vs "探索版" → fail
 * - "启航型" vs "公务版" → fail
 * - "全域精灵版" vs "全球精灵版" → fail
 * - "铂智7 SUV" vs "三厢轿车" → fail
 * - "星纪元ET08" vs "比亚迪海豹08" → fail
 * - "蔚来Z9" vs "腾势Z9" → fail
 * - "智驾版" vs "激光雷达版" → fail
 * - "一汽丰田GAC" vs "广汽丰田" → fail
 */
export function verifyNames(
  modelText: string,
  truthSet: Set<string>
): { pass: boolean; mismatches: string[]; softs: string[] } {
  const mismatches: string[] = [];
  // R1-deep 分层（2026-10-16 尾巴包）：findClosest d<3 对 ≤3 字纯 CJK token 零区分度
  // （任意 2 字词对任意 2 字真值恒命中）——散文普通词（维度/概念词变体）据此误报，
  // 自纠 1-3 次耗 token 用户无感。分层：此类命中降 soft（告警不拒，不进出口闸 failures）；
  // 含字母数字/长名（车系版型特征）/版型转置/张冠李戴兜底 全保 hard（拒）。
  const softs: string[] = [];

  const modelTokens = extractNameTokens(modelText);

  for (const token of modelTokens) {
    if (isNameInTruth(token, truthSet)) continue;

    // C1 通用域白名单：销量/口碑/对比等业务通用词不是名称 → 不构成名称冲突
    if (GENERIC_DOMAIN_WORDS.has(token)) continue;

    // R1 最小修（2026-10-11 风云T7 实案）：纯 CJK token 是某真值名的前缀且余部
    // 非 CJK（风云→风云T7、银河→银河E5）→ 合法简称放行。原 findClosest d<3 阈值下
    // 2 字 token 对任意 2 字真值（如"空间"）恒命中，把品牌/车系简称误报成人工转写错误
    if (/^[一-龥]{2,}$/.test(token)) {
      let prefixOk = false;
      for (const t of truthSet) {
        const rest = t.slice(token.length);
        if (t.startsWith(token) && rest.length > 0 && !/^[一-龥]/.test(rest)) {
          prefixOk = true;
          break;
        }
      }
      if (prefixOk) continue;
    }

    const tokLast = token.slice(-1);
    const isSuffixToken = tokLast === '版' || tokLast === '型';

    if (isSuffixToken) {
      // 版型名 token：检查 truth 里是否有"去掉后缀后子串匹配"的真值
      const stem = token.slice(0, -1);
      let foundTranspose = false;
      let truthMatch = '';
      let hasAnySuffixTruth = false;
      for (const t of truthSet) {
        const tLast = t.slice(-1);
        if (tLast === '版' || tLast === '型') {
          hasAnySuffixTruth = true;
          if (tLast !== tokLast && t.includes(stem)) {
            foundTranspose = true;
            truthMatch = t;
            break;
          }
        }
      }
      if (foundTranspose) {
        mismatches.push(`模型输出"${token}"，库源真值"${truthMatch}"（版/型后缀转写错误）`);
        continue;
      }
      // 用 findClosest（R1-deep 分流：≤3 字纯 CJK 命中零区分度 → soft 告警不拒）
      const closest = findClosest(token, truthSet);
      if (closest) {
        if (/^[一-龥]{1,3}$/.test(token)) {
          softs.push(`疑似普通词"${token}"近真值"${closest}"（低置信，告警不拒）`);
        } else {
          mismatches.push(`模型输出"${token}"，库源真值"${closest}"（疑似人工转写错误）`);
        }
        continue;
      }
      // truth 里有版/型后缀真值，但模型 token 既无转写匹配也无 close 匹配
      // → 模型输出了 truth 里不存在的版型名 → fail
      if (hasAnySuffixTruth) {
        mismatches.push(`模型输出"${token}"，库源无对应版型名（疑似编造或张冠李戴）`);
      }
    } else {
      // 非版型 token（品牌/车系名）：用 findClosest（R1-deep 分流同上）
      const closest = findClosest(token, truthSet);
      if (closest) {
        if (/^[一-龥]{1,3}$/.test(token)) {
          softs.push(`疑似普通词"${token}"近真值"${closest}"（低置信，告警不拒）`);
        } else {
          mismatches.push(`模型输出"${token}"，库源真值"${closest}"（疑似人工转写错误）`);
        }
      }
    }
  }

  // 全局兜底：模型输出的中文 token 里，至少有一个要在 truth 子串里
  // 否则说明模型输出了完全不在 truth 的实体（品牌张冠李戴/形态错）
  // C1：泛域短语（"外观和内饰对比分析"式纯业务词句）不承载身份 → 不作张冠李戴证据；
  // 残部 >1 字的身份词（"蔚来"）仍触发兜底
  const cnTokens = modelTokens.filter(
    (t) => !t.endsWith('版') && !t.endsWith('型') && !isGenericPhrase(t)
  );
  if (cnTokens.length > 0 && truthSet.size > 0) {
    const anyMatch = cnTokens.some((t) => {
      for (const tv of truthSet) {
        if (tv.includes(t) || t.includes(tv)) return true;
      }
      return false;
    });
    if (!anyMatch) {
      const closest = findClosest(cnTokens[0], truthSet);
      mismatches.push(
        `模型输出"${cnTokens[0]}"等中文实体，库源无任何匹配（疑似品牌/车系张冠李戴）${closest ? `，最接近"${closest}"` : ''}`
      );
    }
  }

  return { pass: mismatches.length === 0, mismatches, softs };
}

/**
 * 从文本提取需要校验的名称 token。
 *
 * 策略（修阶段1 8 错误）：
 * - 只校验承载身份的 token：末字"版/型"（版型名）、品牌/厂商名、车系名
 * - 不校验时间词（"26款"）、规格（"530Km"）、纯数字
 * - 末字"版/型"的 token 是版型名，必须精确匹配（防"探索型"→"探索版"转写）
 */
function extractNameTokens(text: string): string[] {
  const tokens = new Set<string>();

  // 1. 末字"版/型"的 token（版型名，最敏感）
  // 匹配"探索版""探索型""智充启航版""激光雷达版"等
  const verRe = /[一-龥A-Za-z0-9]+(?:版|型)/g;
  let m: RegExpExecArray | null;
  while ((m = verRe.exec(text)) !== null) {
    if (m[0].length >= 2) tokens.add(m[0]);
  }

  // 2. 车系/品牌/厂商名：从真值集反向匹配（在 verifyNames 里处理）
  //    这里只提取候选中文短语，留给 findClosest 判断
  const cnRe = /[一-龥]{2,}/g;
  while ((m = cnRe.exec(text)) !== null) {
    if (m[0].length >= 2) tokens.add(m[0]);
  }

  return Array.from(tokens);
}

/** 名称是否在真值集（精确或子串，但末字"版/型"必须一致） */
function isNameInTruth(token: string, truth: Set<string>): boolean {
  if (truth.has(token)) return true;

  const tokLast = token.slice(-1);
  const isSuffixToken = tokLast === '版' || tokLast === '型';

  for (const t of truth) {
    if (isSuffixToken) {
      // 版型名 token：必须找真值里有相同末字的，且 token 是其子串
      const tLast = t.slice(-1);
      if (tLast === '版' || tLast === '型') {
        if (tokLast !== tLast) continue;          // 版≠型
        if (t.includes(token)) return true;        // 探索版 in 26款 530Km 探索版
      } else {
        continue;  // 真值不是版/型后缀，跳过
      }
    } else {
      // 非版型 token（品牌/车系名）：子串匹配即可
      if (t.includes(token) || token.includes(t)) return true;
    }
  }
  return false;
}

/** 找最接近的真值（编辑距离 ≤ 2） */
function findClosest(token: string, truth: Set<string>): string | null {
  let best: string | null = null;
  let bestDist = 3;
  for (const t of truth) {
    const d = editDistance(token, t);
    if (d < bestDist) {
      bestDist = d;
      best = t;
    }
  }
  return best;
}

function editDistance(a: string, b: string): number {
  const m = a.length, n = b.length;
  const dp = Array.from({ length: m + 1 }, () => new Array<number>(n + 1).fill(0));
  for (let i = 0; i <= m; i++) dp[i][0] = i;
  for (let j = 0; j <= n; j++) dp[0][j] = j;
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      dp[i][j] = a[i - 1] === b[j - 1] ? dp[i - 1][j - 1] : 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
    }
  }
  return dp[m][n];
}

// ---------------------------------------------------------------------------
// 综合 grounding（数值 + 名称）
// ---------------------------------------------------------------------------

export interface GroundingResult {
  pass: boolean;
  number_check: { pass: boolean; mismatches: string[] };
  name_check: { pass: boolean; mismatches: string[] };
}

export function groundResult(
  modelText: string,
  toolNumbers: number[],
  toolResults: Array<Record<string, unknown>>
): GroundingResult {
  const number_check = verifyNumbers(modelText, toolNumbers);
  const truthSet = collectNameTruth(toolResults);
  const name_check = verifyNames(modelText, truthSet);
  return {
    pass: number_check.pass && name_check.pass,
    number_check,
    name_check,
  };
}
