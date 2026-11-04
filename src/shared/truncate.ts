/**
 * 线B-工具截断：tool_result 统一截断纯函数
 *
 * 设计（change: openspec/changes/线B-工具截断/，D1-D5）：
 * - 一套算法覆盖全部 TRUNCATABLE 数据工具（组级只决定"截不截"，不决定"怎么截"）
 * - JSON 感知：递归裁长数组到总帽内，保头（服务端默认排序即业务排序，选样规则=原序，可复算）
 * - 保真名单靠结构自然满足：只删数组元素、不删对象键 → _meta/as_of/url/行ID 键永不丢
 * - _truncated 附加计数/分布摘要——摘要只做确定性 groupby（纯代码可复算，非 LLM 摘要）
 * - 顶层数组（舆情端点形态）→ 尾插 _truncated 标记元素；顶层对象 → spread 加 _truncated 键
 * - 非 JSON → head+tail 字符截断
 *
 * 顺序契约（self-check Gap1）：本函数只由截断 handler 调用，且该 handler 必须注册在
 * 台账/名称采集 handler 之后（pi tool_result 链式中间件，后者看到前者改写后的结果）。
 */

export interface TruncateOptions {
  /** 总帽（字符数），默认 20000 */
  maxChars?: number;
  /** 分布统计键（如 search_cars 的 'brand'）：对被裁数组元素做确定性 groupby；无有效键则省略 dist */
  groupKey?: string;
  /** 行为提示（写进 _truncated.hint） */
  hint?: string;
  /** 旁路文件路径（审查 P1-1 修：经 marker 注入而非调用方二次 parse——顶层数组形态下
   * 实例属性注入会被 JSON.stringify 丢弃；且计入 marker 长度=收敛预算内，消除注入后置越帽） */
  bypassPath?: string;
}

export interface TruncateResult {
  text: string;
  truncated: boolean;
  /** true = 原文已落旁路文件，截断载荷应附 full_output_path（由调用方写入后回填） */
  bypassNeeded: boolean;
}

const DEFAULT_MAX = 20000;
/** 非 JSON 路径：头 8000 + 尾 4000 */
const HEAD_CHARS = 8000;
const TAIL_CHARS = 4000;

interface ArrayTrim {
  path: string;
  total: number;
  kept: number;
}

/** 数组按预算保头裁剪：先用平均长度估 keep 数，再 stringify 验证收缩（≤几轮） */
function fitArrayHead(arr: unknown[], budget: number): unknown[] {
  if (arr.length === 0) return arr;
  const full = JSON.stringify(arr);
  if (full.length <= budget) return arr;
  const avg = full.length / arr.length || 1;
  let keep = Math.max(1, Math.floor(budget / avg));
  while (keep > 1 && JSON.stringify(arr.slice(0, keep)).length > budget) {
    keep = Math.max(1, Math.floor(keep * 0.9));
  }
  return arr.slice(0, keep);
}

/** 对被移除的元素做确定性分组计数（可选键；无有效键返回 undefined）。
 * 基数防护（单测抓到的缺陷）：键数 >20 时降级为 top-20 + __other__ 聚合 + __distinct__ 总键数
 * ——防高基数键（如每行唯一的车系名）把 dist 自身膨胀到超过预算。 */
const DIST_TOP_K = 20;
function groupRemoved(removed: unknown[], key: string | undefined): Record<string, number> | undefined {
  if (!key || removed.length === 0) return undefined;
  const dist = new Map<string, number>();
  for (const item of removed) {
    if (item && typeof item === 'object' && key in (item as Record<string, unknown>)) {
      const v = (item as Record<string, unknown>)[key];
      if (v !== null && v !== undefined) {
        const k = String(v);
        dist.set(k, (dist.get(k) || 0) + 1);
      }
    }
  }
  if (dist.size === 0) return undefined;
  if (dist.size <= DIST_TOP_K) return Object.fromEntries(dist);
  const sorted = [...dist.entries()].sort((a, b) => b[1] - a[1]);
  const top = sorted.slice(0, DIST_TOP_K);
  const otherCount = sorted.slice(DIST_TOP_K).reduce((s, [, n]) => s + n, 0);
  const out: Record<string, number> = Object.fromEntries(top);
  out.__other__ = otherCount;
  out.__distinct__ = dist.size;
  return out;
}

/** 递归裁剪：数组按剩余预算保头，**无论裁否都累计记账**（V4 实测缺陷修复：
 * specs 5.7K + provinces 15.7K 各自 ≤ 帽但总和 27.6K 逃过裁剪——预算必须总量控制）；
 * 保底 2000 防前面数组吃光致后面清零，代价由主流程收敛循环兜住。 */
function walk(
  node: unknown,
  budget: { left: number },
  trims: ArrayTrim[],
  path: string,
  groupKey: string | undefined,
  dists: Record<string, Record<string, number>>,
): unknown {
  if (Array.isArray(node)) {
    const arrBudget = Math.max(2000, budget.left);
    const keptArr = fitArrayHead(node, arrBudget);
    const keptLen = JSON.stringify(keptArr).length;
    if (keptArr.length < node.length) {
      const removed = node.slice(keptArr.length);
      trims.push({ path: path || '$', total: node.length, kept: keptArr.length });
      const dist = groupRemoved(removed, groupKey);
      if (dist) dists[path || '$'] = dist;
    }
    budget.left = Math.max(0, budget.left - keptLen);
    return keptArr.map((item, i) =>
      walk(item, budget, trims, `${path || '$'}[${i}]`, groupKey, dists),
    );
  }
  if (node && typeof node === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
      out[k] = walk(v, budget, trims, path ? `${path}.${k}` : k, groupKey, dists);
    }
    return out;
  }
  return node;
}

function headTail(text: string): string {
  return (
    text.slice(0, HEAD_CHARS) +
    `\n…[_TRUNCATED: 原文 ${text.length} 字符，头 ${HEAD_CHARS}+尾 ${TAIL_CHARS}；全文见旁路文件 full_output_path]\n` +
    text.slice(-TAIL_CHARS)
  );
}

export function truncateToolResult(text: string, opts: TruncateOptions = {}): TruncateResult {
  const max = opts.maxChars ?? DEFAULT_MAX;
  if (text.length <= max) return { text, truncated: false, bypassNeeded: false };

  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return { text: headTail(text), truncated: true, bypassNeeded: true };
  }
  // 标量（超长 JSON 字符串/数字）无处附加 _truncated，直接 head/tail
  if (data === null || typeof data !== 'object') {
    return { text: headTail(text), truncated: true, bypassNeeded: true };
  }

  // 收敛循环（V4 实测缺陷修复）：一轮裁完仍可能因"保底 2000/未裁键开销"略超帽——
  // 压掉超出量重裁（≤3 轮），任何形态收敛到 ≤1.05×帽且保持 JSON 结构（不走 headTail 丢结构）
  const build = (budgetMax: number): string => {
    const budget = { left: budgetMax };
    const trims: ArrayTrim[] = [];
    const dists: Record<string, Record<string, number>> = {};
    const walked = walk(data, budget, trims, '', opts.groupKey, dists);
    const marker: Record<string, unknown> = {
      total_chars_original: text.length,
      arrays: trims,
      hint: opts.hint || '结果已截断（长数组保头）。需要更多数据请带更窄参数重查（如 keyword/维度/limit）。',
    };
    if (Object.keys(dists).length > 0) marker.dist = dists;
    if (opts.bypassPath) marker.full_output_path = opts.bypassPath;
    if (Array.isArray(walked)) {
      return JSON.stringify([...(walked as unknown[]), { _truncated: marker }]);
    }
    return JSON.stringify({ ...(walked as Record<string, unknown>), _truncated: marker });
  };

  let outText = build(max);
  for (let round = 0; round < 3 && outText.length > max * 1.05; round++) {
    const over = outText.length - max;
    outText = build(Math.max(2000, max - over));
  }

  // 极端兜底：3 轮后仍超 1.1×帽（理论不应达）→ head/tail
  if (outText.length > max * 1.1) {
    return { text: headTail(outText), truncated: true, bypassNeeded: true };
  }
  return { text: outText, truncated: true, bypassNeeded: true };
}
