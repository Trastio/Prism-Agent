/**
 * 评估迭代基建包 · B2-1/B2-8 中间档判分纯函数（rubric_check.mjs）
 *
 * 三类中间档 + artifact 插槽，任务侧入口 task.rubric_params：
 * - ranking          排序题：金标 top3 ⊆ 回答前5 提及，或首选=硬锚（hard_first）
 * - gap              缺口题：方向词（假设/不可得，可题级覆盖）+ web URL +「不可复算」三要素
 * - sentiment_pattern 舆情范式：声量规模/情感方向/负面主题/来源/as_of 五要素正则齐全度
 * - artifact         导出题插槽（L1-5 题定后启用；本 change 只留插槽+假题单测）
 *
 * 返回 { kind, checked, pass, cap, present, missing, note? }：
 * - cap=null 不降档；cap=数字 → runner 取 min(score, cap)（中间档封顶）
 * - 缺参/未知 kind fail-closed（cap=2，不静默放行）
 * 正反例契约：eval/rubric_check.test.mjs（改本文件必须先改测试）。
 */

import { existsSync, readFileSync } from 'node:fs';

// 缺口题方向词缺省（假设清单范式信号；NEG_RE 是拒绝语义、此处要的是"承认缺口"方向）
const GAP_DIRECTION_RE = /假设|不可得|缺口|证据强度|无法确认|不能确认|数据缺失|暂无|未收录|无此数据|无对应字段/;

// 舆情范式五要素（sentiment-03 judge_rubric："五要素各1分"；此处只判有无，数值锚点归 truth）
const SENTIMENT_ELEMENTS = [
  { id: '声量规模', re: /\d[\d,]*(?:\.\d+)?\s*(?:条|篇|帖|声量|条内容)|(?:声量|帖子?量|提及量|讨论量)[^\n。]{0,12}\d/ },
  { id: '情感方向', re: /正面|负面|中性|积极|消极|情感|情绪|好评|差评|口碑/ },
  { id: '负面主题', re: /负面(?:主题|话题|反馈|评价|内容|声音)|吐槽|不满|抱怨|槽点|诟病|缺点|短板|质疑/ },
  { id: '来源', re: /抖音|douyin|微博|weibo|小红书|红书|xhs|快手|kuaishou|哔哩|bilibili|B站|来源|平台/ },
  { id: 'as_of', re: /as_of|数据时点|抓取时间|抓取日期|采集时间|20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}/ },
];

const GAP_ELEMENTS = [
  { id: 'direction', re: GAP_DIRECTION_RE },
  { id: 'url', re: /https?:\/\// },
  { id: '不可复算', re: /不可复算/ },
];

/** 中间档封顶映射：缺 1 要素→4、缺 2→3、缺 ≥3→2（齐全→null 不降档） */
function capByMissing(n) {
  if (n <= 0) return null;
  if (n === 1) return 4;
  if (n === 2) return 3;
  return 2;
}

// 名称归一（2026-11-01 修误报）：判据写"比亚迪 元UP"，agent 常写"元UP"，精确匹配会把命中的要素判成缺。
// 查找顺序：去空白/小写后的整串 → 候选名词段（跳过 纯电/插混 等通用后缀）。
// 位置一律在归一正文上取：原文索引与归一索引量级不同，混用会让排序错位（单测已锁）。
const compactName = (s) => String(s).replace(/\s+/g, '').toLowerCase();
const GENERIC_SEG = new Set(['纯电', '纯电动', '插混', '插电混动', '增程', '混动', '四驱', '两驱', '智驾', 'ev', 'dm', 'dm-i', 'max', 'pro', 'plus']);
function positionOf(reply, cand) {
  const cr = compactName(reply);
  const cc = compactName(cand);
  const whole = cr.indexOf(cc);
  if (whole >= 0) return whole;
  let best = -1;
  for (const seg of String(cand).split(/\s+/)) {
    const s = compactName(seg);
    if (s.length < 2 || GENERIC_SEG.has(s)) continue;
    const k = cr.indexOf(s);
    if (k >= 0 && (best < 0 || k < best)) best = k;
  }
  return best;
}

function checkRanking(params, reply) {
  const { gold_top3, candidates, hard_first } = params;
  if (!Array.isArray(gold_top3) || gold_top3.length === 0 || !Array.isArray(candidates) || candidates.length === 0) {
    return { kind: 'ranking', checked: true, pass: false, cap: 2, present: [], missing: [], note: 'rubric 缺参（gold_top3/candidates）fail-closed' };
  }
  // 候选按回复中首次提及位置排序（未提及的排∞）
  const mentioned = candidates
    .map((c) => ({ c, idx: positionOf(reply, c) }))
    .filter((x) => x.idx >= 0)
    .sort((a, b) => a.idx - b.idx)
    .map((x) => x.c);
  const first5 = mentioned.slice(0, 5);
  const inFirst5 = gold_top3.filter((g) => first5.includes(g));
  const hardHit = hard_first && mentioned[0] === hard_first;
  const pass = hardHit || (inFirst5.length === gold_top3.length);
  return {
    kind: 'ranking', checked: true, pass,
    cap: pass ? null : 2,
    present: inFirst5,
    missing: pass ? [] : gold_top3.filter((g) => !first5.includes(g)),
    note: hardHit ? '首选=硬锚' : `金标 top3 落前5: ${inFirst5.length}/${gold_top3.length}`,
  };
}

function checkByElements(kind, elements, reply) {
  const present = elements.filter((e) => (e.custom ?? e.re).test(reply)).map((e) => e.id);
  const missing = elements.map((e) => e.id).filter((id) => !present.includes(id));
  return { kind, checked: true, pass: missing.length === 0, cap: capByMissing(missing.length), present, missing };
}

// 通用要素判据（2026-10-26 补齐剩余观测集题）：题级 elements + 可选 required/min_present/forbid。
// causal_guard 与 elements 共用本实现，只是 kind 标签不同（便于报告归因）。
function checkElementRules(kind, params, reply) {
  const els = Array.isArray(params.elements) ? params.elements : [];
  if (!els.length) {
    return { kind, checked: true, pass: false, cap: 2, present: [], missing: [], missingRequired: [], forbidHits: [], note: 'rubric 缺参（elements）fail-closed' };
  }
  const present = els.filter((e) => new RegExp(e.re).test(reply)).map((e) => e.id);
  const missing = els.map((e) => e.id).filter((id) => !present.includes(id));
  const required = Array.isArray(params.required) ? params.required : [];
  const missingRequired = required.filter((id) => !present.includes(id));
  const minPresent = Number.isInteger(params.min_present) ? params.min_present : els.length;
  const forbidHits = (Array.isArray(params.forbid) ? params.forbid : []).filter((re) => new RegExp(re).test(reply));
  const enough = present.length >= minPresent && missingRequired.length === 0;
  const pass = enough && forbidHits.length === 0;
  const cap = forbidHits.length ? 2 : (pass ? null : capByMissing(missing.length));
  return {
    kind, checked: true, pass, cap, present, missing, missingRequired, forbidHits,
    note: forbidHits.length ? '命中禁项' : (pass ? '护栏全命中' : '要素不足'),
  };
}

function checkCausalGuard(params, reply) {
  return checkElementRules('causal_guard', params, reply);
}

function checkElements(params, reply) {
  return checkElementRules('elements', params, reply);
}

function checkArtifact(params, reply, opts = {}) {
  const a = params.artifact || {};
  const path = opts.artifactPath || '';
  if (!path || !existsSync(path)) {
    return { kind: 'artifact', checked: true, pass: false, cap: 2, present: [], missing: ['artifact'], note: 'artifact 未交付' };
  }
  const extOk = !a.ext || path.toLowerCase().endsWith('.' + String(a.ext).toLowerCase());
  if (!extOk) {
    return { kind: 'artifact', checked: true, pass: false, cap: 2, present: [], missing: ['ext'], note: `扩展名不符（期望 .${a.ext}）` };
  }
  // 插槽口径：文本类查 must_contain；xlsx 二进制只验存在+扩展名（内容检查随 L1-5 出题启用）
  if (Array.isArray(a.must_contain) && /\.(txt|md|json|csv)$/i.test(path)) {
    const text = readFileSync(path, 'utf-8');
    const missing = a.must_contain.filter((s) => !text.includes(s));
    if (missing.length) {
      return { kind: 'artifact', checked: true, pass: false, cap: 2, present: [], missing, note: 'must_contain 未全命中' };
    }
  }
  return { kind: 'artifact', checked: true, pass: true, cap: null, present: ['artifact'], missing: [], note: 'xlsx 内容检查随 L1-5 启用（当前仅存在性+扩展名）' };
}

/**
 * @param {{rubric_params?: object}} task
 * @param {string} reply agent 最终回复（多轮题=终轮全文）
 * @param {{artifactPath?: string}} opts artifact 题传入导出文件路径
 */
export function checkRubric(task, reply, opts = {}) {
  const params = task?.rubric_params;
  if (!params || !params.kind) return { kind: null, checked: false, pass: false, cap: null, present: [], missing: [] };
  const r = String(reply ?? '');
  switch (params.kind) {
    case 'ranking':
      return checkRanking(params, r);
    case 'gap': {
      // direction_words 题级覆盖（数组→任一命中）
      const els = GAP_ELEMENTS.map((e) =>
        e.id === 'direction' && Array.isArray(params.direction_words) && params.direction_words.length
          ? { id: e.id, custom: new RegExp(params.direction_words.join('|')) }
          : e,
      )
        // 库内缺口题（2026-11-01）：数据来自库、非联网补充，url/不可复算 不适用（web 题缺省仍要求）。
        .filter((e) => (params.requires_web_source === false ? !['url', '不可复算'].includes(e.id) : true));
      return checkByElements('gap', els, r);
    }
    case 'sentiment_pattern':
      return checkByElements('sentiment_pattern', SENTIMENT_ELEMENTS, r);
    case 'causal_guard':
      return checkCausalGuard(params, r);
    case 'elements':
      return checkElements(params, r);
    case 'artifact':
      return checkArtifact(params, r, opts);
    default:
      return { kind: params.kind, checked: true, pass: false, cap: 2, present: [], missing: [], note: '未知 rubric kind fail-closed' };
  }
}
