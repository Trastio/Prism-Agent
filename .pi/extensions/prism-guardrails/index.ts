/**
 * Prism-Agent · prism-guardrails extension（红线执行层）
 *
 * 注册 23 个业务工具 + 4 个社媒工具（social_*，web 类）+ 7 个 hook：
 * - pi.registerTool: query_* 3（mv 口径链）+ sentiment_* 7（prism-sentiment:8000）
 *   + dashboards 10（prism-dashboards:8010）+ resolve_series + submit_conclusion（出口闸）
 *   + social_* 4（TikHub 直连，社媒深挖能力包：搜索/评论/用户画像/作品列表，每轮 20 次成本护栏）
 * - before_agent_start: ctx.json 解析（series_key/scope）→ setActiveTools 白名单 + 身份核验 + 提示词分层注入
 * - tool_call: 行为级拦截（裸SQL/敏感文件/数据库直连）+ fail-closed 未知业务工具（红线#2/#3）
 * - tool_result: 数字台账采集（truth/declared-derived 双信任级）+ 名称真值集 + _meta 口径校验（红线#1/#6）
 * - agent_settled: 出口闸改道（保底③身份 → 通过提交 pass → 保底①漏提交/②凭空编造 → 默认放行；
 *   回灌链级硬顶，prism-verified entry 跨重启持久）
 * - session_before_compact / session_start / session_shutdown: 观测与生命周期
 *
 * 行ID查库走 FastAPI POST /verify/claim（服务端真值）——pi.exe(Bun) 内禁 better-sqlite3 原生模块（NAPI panic）
 */

import { readFileSync, writeFileSync, mkdirSync, existsSync as _existsSync, unlinkSync as _unlinkSync, readdirSync, statSync, appendFileSync, renameSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
const existsSyncSafe = _existsSync;
const unlinkSyncSafe = _unlinkSync;
import { verifyClaimShape, type Claim } from '../../../src/verify/completion.ts';
import { collectNameTruth, verifyNames } from '../../../src/verify/grounding.ts';
import { normalizeNumber, extractProseTokens, extractLedgerValues, looksLikeErrorPayload, readNumericLedger, ledgerHasValue } from '../../../src/verify/numeric-ledger.ts';
import { harvestTruth, collectRegistrationDrift } from '../../../src/shared/truth-envelope.ts';
import { VERIFIER_NOTICE_PREFIX } from '../../../src/shared/verifier-prefix.ts';
import { TIKHUB_TOOLS, TIKHUB_LIMIT_MSG, TIKHUB_LIMIT, tikhubCounter, executeAction, truncateOutput } from './tikhub.ts';

// v1.2 重跑护栏（2026-10-26 归因）：启动横幅——轨迹落点一眼可验。曾发生批跑打错栈、轨迹
// 静默写入生产回退文件 .pi/sessions/trajectories.jsonl（污染北极星）而无人察觉。
console.error('[prism-guardrails] traj sink =', process.env.PRISM_TRAJECTORY_FILE
  ? resolve(process.env.PRISM_TRAJECTORY_FILE)
  : resolve(process.cwd(), '.pi/sessions/trajectories.jsonl') + '  ← FALLBACK（PRISM_TRAJECTORY_FILE 未注入！）');
// 线B-工具截断：统一截断层（第二个 tool_result handler 调用，见文件尾部）
import { truncateToolResult } from '../../../src/shared/truncate.ts';
import { decideWorkflowGate, shouldAdvancePhase, WORKFLOW_SKILL } from '../../../src/shared/workflow-gate.ts';
import { readSkillFile } from './skills.ts';
import { listSkills } from './skills.ts';

const FASTAPI = process.env.PRISM_FASTAPI || 'http://127.0.0.1:8002';
// 服务令牌（2026-10-18）：登录门禁拦本机 8002 内部调用，网关注入 PRISM_SERVICE_TOKEN，
// 以 X-Prism-Service 头通过 FastAPI 鉴权（main.py auth middleware）。仅对本机 FASTAPI 生效。
const SERVICE_TOKEN = process.env.PRISM_SERVICE_TOKEN || '';
// 评估 run 标识（P0 链路焊死，2026-10-26）：网关按请求写 ctx.json，extension 逐轮读取后落到每行轨迹。
// runner 按 evalRunId+userId 取 verdict，不再依赖 sessionId 对齐（sessionId 断供曾致整批判分失真）。
let evalRunId = '';
let evalTaskId = '';
let evalRepeat: number | null = null;
let ctxUserId = '';
const _nativeFetch = globalThis.fetch;
globalThis.fetch = (async (input: any, init?: any) => {
  const url = typeof input === 'string' ? input : String(input?.url ?? '');
  if (SERVICE_TOKEN && url.startsWith(FASTAPI)) {
    init = { ...(init || {}), headers: { 'X-Prism-Service': SERVICE_TOKEN, ...(init?.headers || {}) } };
  }
  return _nativeFetch(input, init);
}) as typeof fetch;

// 已注册业务工具白名单（3 query + 7 sentiment + 11 dashboards + resolve_series + submit_conclusion）
// fail-closed 用：业务前缀工具不在白名单 → block（防 agent 幻觉工具）
export const KNOWN_BUSINESS_TOOLS = new Set([
  'query_reviews', 'query_sales', 'query_config',
  'sentiment_overview', 'sentiment_trend', 'sentiment_dimension',
  'sentiment_posts', 'sentiment_competitive', 'sentiment_events',
  'sentiment_defects',
  'search_cars', 'get_model_detail', 'get_similar_models',
  'get_trims', 'get_config_detail', 'compare_configs_valued', 'get_review_analysis', 'search_reviews',
  'get_dimension_reviews', 'get_sales_detail', 'score_models',
  'resolve_series',
  'submit_conclusion',
]);
export const BUSINESS_PREFIXES = ['query_', 'sentiment_', 'search_', 'get_', 'score_', 'resolve_'];

// 块3：TOOL_CATEGORIES 一源（business/web/utility），ALLOWED_TOOLS 派生
export const TOOL_CATEGORIES = {
  business: KNOWN_BUSINESS_TOOLS,
  // 社媒深挖能力包 M1：social_* 归 web 类（不可复算外部源 → tier 路由/URL 真值集/白名单三处自动派生）
  web: new Set(['web_search', 'fetch_content', 'source_check', 'get_search_content', ...TIKHUB_TOOLS]),
  // 社媒深挖能力包 M2/M3：load_skill（技能加载）/ export_document（xlsx 交付）归 utility
  utility: new Set(['ask_user_question', 'load_skill', 'export_document']),
};
export const EXTRA_TOOLS = new Set([...TOOL_CATEGORIES.web, ...TOOL_CATEGORIES.utility]);
export const ALLOWED_TOOLS = new Set([...KNOWN_BUSINESS_TOOLS, ...EXTRA_TOOLS]);

// ── B2-2 web 受控三态（PRISM_EVAL_WEB=off|live|fixture，eval 网关 env）──
// pi-web-access 插件 4 工具真名（插件 DEFAULT_TOOL_NAMES 实证：web_search/source_check/
// fetch_content/get_search_content——派单稿写的 web_fetch 不存在）。G1：social_*（TikHub）
// 独立类不波及——剔除/录制/回放只针对 web4。
// 生产网关不注入 PRISM_EVAL_WEB；eval 上下文判据 = PRISM_TRAJECTORY_FILE 已注入
// （prism.py eval start 独有）→ 缺省 off（库内题零外呼）。null = 生产/交互：web4 照常。
export const PI_WEB_ACCESS_TOOLS = new Set(['web_search', 'fetch_content', 'source_check', 'get_search_content']);
const EVAL_WEB_MODE = (() => {
  const v = (process.env.PRISM_EVAL_WEB || '').toLowerCase();
  if (v === 'live' || v === 'fixture') return v;
  if (v && v !== 'off') console.error(`[prism-guardrails] PRISM_EVAL_WEB 未知值 ${v}，按 off 处理`);
  return process.env.PRISM_TRAJECTORY_FILE ? 'off' : null;
})();
const WEB_FIXTURE_DIR = resolve(
  process.cwd(),
  process.env.PRISM_WEB_FIXTURE_DIR || 'eval/fixtures/web',
);

// B2-2 录制/回放（tool 层实现——非 HTTP 层）：
// 实测（web-debug 探针，2026-10-14）：extension 沙箱与插件工具主 realm 的 globalThis.fetch
// 不共享，extension 内补丁拦不到 pi-web-access 工具的外呼。故改在 hook 层：
// - 录制（live+PRISM_WEB_FIXTURE_DIR）：tool_result hook 把 web4 工具的最终结果（模型实际
//   看到的内容）按题落盘 <dir>/<taskId>/tools.jsonl（照 tikhub-fixtures 结构，_meta 口径同源）
// - 回放（fixture）：tool_call hook 拦截 web4 调用 → block + reason=录制件原文（零外呼；
//   录制件按 input 相似度优先匹配，其次同工具顺序消费；未录制→语义化缺口提示）
let currentEvalTaskId = '_unknown';
let webReplayRecords: any[] | null = null;
const webReplayConsumed = new Set<number>();

function loadWebReplayRecords(): any[] {
  if (webReplayRecords) return webReplayRecords;
  const all: any[] = [];
  try {
    // P2-3（Step7）：当前任务有专属录制件时只装它的目录——防 repeat/多题顺序消费吃错录制
    const ownFixture = resolve(WEB_FIXTURE_DIR, currentEvalTaskId, 'tools.jsonl');
    const ownOnly = existsSyncSafe(ownFixture);
    for (const taskDir of readdirSync(WEB_FIXTURE_DIR)) {
      if (ownOnly && taskDir !== currentEvalTaskId) continue;
      const dirPath = resolve(WEB_FIXTURE_DIR, taskDir);
      let isDir = false;
      try { isDir = statSync(dirPath).isDirectory(); } catch {}
      if (!isDir) continue;
      const f = resolve(dirPath, 'tools.jsonl');
      if (!existsSyncSafe(f)) continue;
      for (const line of readFileSync(f, 'utf-8').split('\n')) {
        if (!line.trim()) continue;
        try {
          const rec = JSON.parse(line);
          if (rec?.tool) all.push(rec);
        } catch {}
      }
    }
  } catch {}
  console.error(`[prism-guardrails][web-fixture] 回放装载: ${all.length} 条（${WEB_FIXTURE_DIR}）`);
  webReplayRecords = all;
  return all;
}

function webInputOverlap(a: unknown, b: unknown): boolean {
  const sa = JSON.stringify(a ?? {}), sb = JSON.stringify(b ?? {});
  if (!sa || !sb) return false;
  // 简版最长公共子串 >10 字符视为同查询（query/url 关键词重合）
  const m = sa.length, n = sb.length;
  let best = 0;
  const prev = new Array(n + 1).fill(0);
  for (let i = 1; i <= m; i++) {
    let diag = 0;
    for (let j = 1; j <= n; j++) {
      const cur = sa.charCodeAt(i - 1) === sb.charCodeAt(j - 1) ? diag + 1 : 0;
      prev[j - 1] = diag;
      diag = cur;
      if (cur > best) best = cur;
    }
    prev[n] = diag;
  }
  return best > 10;
}

/** fixture 回放：返回 block reason（含录制件）或未录制提示；供 tool_call hook 调用 */
function webFixtureReplay(toolName: string, input: unknown): { block: true; reason: string; terminate: false } | null {
  const records = loadWebReplayRecords();
  let idx = records.findIndex((r, i) => !webReplayConsumed.has(i) && r.tool === toolName && webInputOverlap(r.input, input));
  if (idx < 0) idx = records.findIndex((r, i) => !webReplayConsumed.has(i) && r.tool === toolName);
  if (idx < 0) {
    return {
      block: true, terminate: false,
      reason: `[web-fixture] PRISM_EVAL_WEB=fixture：${toolName} 无未消费的录制件（零外呼）。请基于已回放的 web 证据作答，或如实声明该 web 证据不可得（红线#4）。`,
    };
  }
  webReplayConsumed.add(idx);
  const rec = records[idx];
  console.error(`[prism-guardrails][web-fixture] 回放: ${toolName} #${idx}（原录制 ${rec.ts}）`);
  return {
    block: true, terminate: false,
    reason: `[web-fixture 回放·零外呼] 以下为 live 模式录制的 ${toolName} 结果（原样数据，含 URL/as_of；引用按 web 证据标注「不可复算」）：\n${String(rec.content || '').slice(0, 60 * 1024)}`,
  };
}

// 线B-工具截断：纳入统一截断的数据工具（组级只决定"截不截"，算法一套见 src/shared/truncate.ts）。
// 流程/交互工具不截（resolve_series/submit_conclusion 出口闸协议、load_skill/export_document/ask_user 天然小）；
// pi-web-access 4 个插件工具不截（URL 真值集风险，观察一版）——self-check Gap4。
const TRUNCATABLE_TOOLS = new Set([
  'query_reviews', 'query_sales', 'query_config',
  'sentiment_overview', 'sentiment_trend', 'sentiment_dimension',
  'sentiment_posts', 'sentiment_competitive', 'sentiment_events',
  'sentiment_defects',
  'search_cars', 'get_model_detail', 'get_similar_models', 'get_trims',
  'get_config_detail', 'compare_configs_valued', 'get_review_analysis', 'search_reviews',
  'get_dimension_reviews', 'get_sales_detail', 'score_models',
  ...TIKHUB_TOOLS,
]);
// 分布统计键（确定性 groupby，白名单配置非按工具定制策略）。
// 注：search_cars 专用实现已自带 cap 50 + 行内 _truncated，不再需要 hook 层 dist（simplify 清理）
const TRUNCATE_DIST_KEYS: Record<string, string> = {};
const TRUNCATE_MAX_CHARS = 20000;
// 旁路文件目录（prism.py 日志同惯例；写盘 best-effort，失败不阻断工具结果）
const TOOL_OUTPUT_DIR = resolve(process.cwd(), 'logs', 'tool-outputs');

// 块2：TrustTier 一等概念（基于工具调用判定）
export type TrustTier = 'library' | 'web' | 'mixed' | 'none';
export function decideTier(calledTools: string[]): TrustTier {
  // v1.2 §3.1：submit_conclusion 计入 library 判据（仅追加不移除）
  const hasLib = calledTools.some(t => t.startsWith('query_') || t === 'submit_conclusion');
  const hasWeb = calledTools.some(t => TOOL_CATEGORIES.web.has(t));
  if (hasLib && hasWeb) return 'mixed';
  if (hasLib) return 'library';
  if (hasWeb) return 'web';
  return 'none';
}

/**
 * tool_call 行为级拦截判定（纯函数，供单测）
 *
 * 红线#2/#3 + fail-closed 未知业务工具：
 * - 裸 SQL 写操作（DROP/DELETE/INSERT/UPDATE/ALTER）→ block + terminate
 * - bash 直连数据库（psql/mysql/sqlite3）→ block
 * - 敏感文件（.env/auth.json/.ssh/id_rsa/credentials/secret）→ block
 * - 业务前缀工具不在白名单 → block（防 agent 幻觉工具）
 * - pi 内置工具（read/glob/grep/bash 等）不在校验范围，归 --exclude-tools 管
 */
export function decideToolCall(
  toolName: string,
  input: unknown
): { block: boolean; reason?: string; terminate?: boolean } {
  const inputStr = typeof input === 'string' ? input : JSON.stringify(input || {});
  // 红线#2：拦截裸 SQL 写操作
  if (/\b(DROP|DELETE|INSERT|UPDATE|ALTER)\s+/i.test(inputStr)) {
    return { block: true, reason: '红线#2: 禁止裸 SQL 写操作', terminate: true };
  }
  // 红线#2：拦截数据库直连
  if (toolName === 'bash' && /\b(psql|mysql|sqlite3)\b/i.test(inputStr)) {
    return { block: true, reason: '红线#2: 禁止命令行直连数据库', terminate: false };
  }
  // 红线#3：拦截敏感文件读取
  if (/\.env|auth\.json|\.ssh|id_rsa|credentials|secret/i.test(inputStr)) {
    return { block: true, reason: '红线#3: 禁止读写敏感文件', terminate: false };
  }
  // fail-closed：未知业务工具（业务前缀但不在白名单 → block，防 agent 幻觉工具）
  const tn = toolName || '';
  if (BUSINESS_PREFIXES.some(p => tn.startsWith(p)) && !ALLOWED_TOOLS.has(tn)) {
    return { block: true, reason: `fail-closed: 未知业务工具 ${tn}`, terminate: false };
  }
  return { block: false };
}

// ---------------------------------------------------------------------------
// 业务工具注册（工厂模式，三个工具 execute 逻辑一致）
// ---------------------------------------------------------------------------
function makeQueryTool(name, label, description, extraParams = {}) {
  return {
    name,
    label,
    description,
    parameters: {
      type: 'object',
      properties: {
        series_key: { type: 'string', description: '车系名，如 银河E5' },
        ...extraParams,
      },
      required: ['series_key'],
    },
    async execute(toolCallId, params) {
      const qs = new URLSearchParams({ series_key: params.series_key });
      if (params.tag_category) qs.set('tag_category', params.tag_category);
      if (params.year) qs.set('year', String(params.year));
      if (params.group_by) qs.set('group_by', params.group_by);
      if (params.month !== undefined) qs.set('month', String(params.month)); // Step7审查P2-4：falsy检查会吞month=0（静默返全量）——改显式undefined判断，0交后端400 fail-loud
      const dtype = name.replace('query_', '');  // query_reviews → reviews
      try {
        const res = await fetch(`${FASTAPI}/dashboard/${dtype}?${qs}`);
        // C3：失败语义化——结构化 unavailable（非裸 HTTP 码），让模型能走红线#4"如实报缺"话术而非绕路
        if (!res.ok) return { content: [{ type: 'text', text: JSON.stringify({ status: 'unavailable', tool: name, reason: `HTTP ${res.status}`, fallback: 'none' }) }] };
        const data = await res.json();
        return { content: [{ type: 'text', text: JSON.stringify(data) }], details: { count: data.rows?.length } };
      } catch (e) {
        return { content: [{ type: 'text', text: JSON.stringify({ status: 'unavailable', tool: name, reason: (e as Error).message, fallback: 'none' }) }] };
      }
    },
  };
}

function registerPrismTools(pi) {
  pi.registerTool(makeQueryTool(
    'query_reviews', 'Query Reviews',
    '查询车系口碑维度聚合（pro/con/净态度）+ 原文样本。expected: sentiment=pro/con; 维度=tag_category; 返回带 as_of+覆盖率。定位=库内快问快答；如用户要全网社媒深挖/典型用户画像/调研报告交付，改用 load_skill("car-reputation-research")，或答完后主动提示可升级深挖。',
    { tag_category: { type: 'string', description: '维度，如 舒适' } }
  ));
  pi.registerTool(makeQueryTool(
    'query_sales', 'Query Sales',
    '查询车系月度销量（月末行 retail）+ 终端价 tp_avg。支持 group_by=spec 查版型明细。expected: 按 year+month 分组; 月末行非月中; 返回带 as_of。',
    // B1-6 month 债已清（query-sales-month过滤 change，2026-10-15）：后端 /dashboard/sales 实装
    // month 过滤（月度聚合 SQL 条件 + spec 分支行内前导数字匹配），月末口径限定不受影响；
    // schema 恢复 month 参数，execute 内 :246 发送分支本就正确。
    { year: { type: 'number', description: '年份，如 2026' }, month: { type: 'number', description: '月份 1-12，可选；只筛该月（月末行口径不变）' }, group_by: { type: 'string', description: '分组方式：month（月度汇总）或 spec（版型明细）' } }
  ));
  pi.registerTool(makeQueryTool(
    'query_config', 'Query Config',
    '查询车型配置（展平嵌套 dict + 年款标注）。expected: 含 2024/2026/2027 三年款; 版型名末字版非型; 返回带 as_of。'
  ));

  // T-2.5：resolve_series 工具（红线#7 身份核验，供 agent 查询详情）
  // before_agent_start 已强制前置核验，此工具供 agent 主动复查
  pi.registerTool({
    name: 'resolve_series',
    label: 'Resolve Series',
    description: '核验车系对象身份 + 覆盖率守卫（红线#7）。分析前必须确认 series_key 对应真实车系。返回 series_id/coverage/warnings/needs_online_verify/ambiguous/candidates。',
    parameters: {
      type: 'object',
      properties: {
        series_key: { type: 'string', description: '车系名，如 银河E5' },
      },
      required: ['series_key'],
    },
    async execute(_toolCallId, params) {
      try {
        const url = `${FASTAPI}/identity/resolve?series_key=${encodeURIComponent(params.series_key)}`;
        const res = await fetch(url);
        if (!res.ok) return { content: [{ type: 'text', text: JSON.stringify({ status: 'unavailable', tool: 'resolve_series', reason: `HTTP ${res.status}`, fallback: 'none' }) }] };
        const data = await res.json();
        // D3 保底③喂源修正（登记收敛）：agent 实际核验成功即写 session 台账——
        // 原喂源只有前端 ctx 选择，纯对话时台账恒空 → 追问轮误触发身份保底（2026-10-13 用户会话实证）。
        // 只在命中真实车系（有 series_id 且非歧义）时写，歧义/虚构不记账（判据读"最新非空"）。
        // P2-2（隔离审查）：series_key 空串不入账（空身份键会破坏台账口径）
        const skResolved = String(params.series_key || '').trim();
        if (skResolved && data && data.series_id && !data.ambiguous) {
          try { pi.appendEntry('prism-session-series-key', { series_key: skResolved }); } catch {}
        }
        return { content: [{ type: 'text', text: JSON.stringify(data) }] };
      } catch (e) {
        return { content: [{ type: 'text', text: JSON.stringify({ status: 'unavailable', tool: 'resolve_series', reason: (e as Error).message, fallback: 'none' }) }] };
      }
    },
  });
}

// ---------------------------------------------------------------------------
// 舆情 Board 工具（7 组，调 FastAPI /sentiment-board/ 反代 → 舆情 :8000）
// ---------------------------------------------------------------------------
const SENTIMENT_BASE = process.env.PRISM_SENTIMENT_BASE || `${FASTAPI}/sentiment-board`;

// 舆情 Board API 前缀是 /api/dashboard，vehicle_id 是 UUID
// 工具接收 vehicle_name（车系名），先搜 fleet-overview 拿 UUID 再调。
// 2026-10-20 舆情工具层跟进：两级解析——fleet-overview 只返回 active 车（dashboard.py:294），
// 16 台 paused 车（含银河E5/零跑D19 常用车，R42 冻结存量保留）会 miss → fallback 全量名单
// /api/vehicles（含 status）。paused 照查（数据端点 _get_vehicle_or_404 不筛 status），
// 红线#1：如实声明"停更冻结"，不误报"未收录"。export 供 tests/sentiment_tools.test.ts。
export async function resolveVehicleId(vehicleName: string): Promise<{ id: string; status: string } | null> {
  // P1-1（Step7 审查）：空串守卫——includes('') 恒真会静默命中 fleet 第一台（实测返 Model Y），
  // 模型传空串即错车交付。fail-closed：空/纯空白名一律 null（真缺口语义）。
  if (!vehicleName || !vehicleName.trim()) return null;
  try {
    const res = await fetch(`${SENTIMENT_BASE}/api/dashboard/fleet-overview`);
    if (res.ok) {
      const fleet = await res.json();
      if (Array.isArray(fleet)) {
        // 精确匹配优先，模糊匹配兜底
        const exact = fleet.find(v => v.name === vehicleName);
        if (exact) return { id: exact.id, status: 'active' };
        const fuzzy = fleet.find(v => v.name && v.name.includes(vehicleName));
        if (fuzzy) return { id: fuzzy.id, status: 'active' };
      }
    }
  } catch { /* fallthrough 到全量名单（paused 车解析的主路径） */ }
  // fallback 不走舆情 /api/vehicles（同样只返回 active）——走 Prism 侧只读全量端点
  // /sentiment/vehicles-all（main.py 直查舆情库含 status，2026-10-20 T1）
  try {
    const res = await fetch(`${FASTAPI}/sentiment/vehicles-all`);
    if (res.ok) {
      const all = await res.json();
      if (Array.isArray(all)) {
        // 去空格 + 大小写不敏感（英文车名如 Model Y 常见大小写变体）
        const nm = vehicleName.replace(/\s+/g, '').toLowerCase();
        const norm = (s: unknown) => (typeof s === 'string' ? s.replace(/\s+/g, '').toLowerCase() : '');
        const exact = all.find(v => norm(v.name) === nm);
        if (exact) return { id: exact.id, status: exact.status || 'unknown' };
        const fuzzy = all.find(v => v.name && norm(v.name).includes(nm));
        if (fuzzy) return { id: fuzzy.id, status: fuzzy.status || 'unknown' };
      }
    }
  } catch (e) {
    // P2-4（Step7 审查）：网络失败静默归并为"未收录"是文案失真——日志留痕，
    // unavailable 文案由调用方升级为不撒谎的合并措辞（服务不可达时模型应建议稍后重试）
    console.error('[prism-guardrails] vehicles-all fallback 不可达:', (e as Error).message);
    return null;
  }
  return null;
}

// B2-6（B9 舆情保质期预留）：PRISM_FAKE_TODAY=YYYY-MM-DD 供 sentiment_trend 时间窗换算
// 假"今日"；缺省系统时间（行为不变）。拍板后 eval 网关注入即启用，不改代码。
export function evalToday(): Date {
  const s = process.env.PRISM_FAKE_TODAY;
  if (s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s.trim());
    if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    console.error('[prism-guardrails] PRISM_FAKE_TODAY 格式非法（须 YYYY-MM-DD），回退系统时间:', s);
  }
  return new Date();
}

function makeSentimentTool(name, path, description, extraParams = {}) {
  return {
    name,
    label: name,
    // 红线#7 引导：先 resolve_series 再查舆情，避免轮末身份保底回灌多绕一轮（2026-10-11 E2E 实证）
    description: description + ' 使用前先调 resolve_series 核验车系身份（红线#7）。',
    parameters: {
      type: 'object',
      properties: {
        vehicle_name: { type: 'string', description: '车系名，如 银河E5' },
        ...extraParams,
      },
      required: ['vehicle_name'],
    },
    async execute(toolCallId, params) {
      const resolved = await resolveVehicleId(params.vehicle_name);
      // C3：未收录车系也是 unavailable 语义（模型如实报告缺口，不绕路）。
      // 2026-10-20：区分三态——未收录（真无）/ inactive（已停用库内无数据）/ active|paused（照查）
      if (!resolved) return { content: [{ type: 'text', text: JSON.stringify({ status: 'unavailable', tool: name, reason: `车系 ${params.vehicle_name} 不在舆情系统收录范围（或舆情服务暂时不可达，可稍后重试）`, fallback: 'none' }) }] };
      if (resolved.status === 'inactive') return { content: [{ type: 'text', text: JSON.stringify({ status: 'unavailable', tool: name, reason: `车系 ${params.vehicle_name} 在舆情系统已停用（库内无舆情数据）`, fallback: 'none' }) }] };
      const qs = new URLSearchParams();
      // 线B bug 修：trend 端点必填 start/end（YYYY-MM-DD，2026-10-12 实测 422）——
      // 工具侧把可选 days 换算成日期区间（缺省 30 天），PM 仍只需说"最近 N 天"
      if (path.includes('/trend/')) {
        const d = Math.max(1, Math.min(365, Number(params.days) || 30));
        const end = evalToday(); // B2-6：PRISM_FAKE_TODAY 假今日（缺省系统时间，行为不变）
        const start = new Date(end.getTime() - d * 86400000);
        const fmt = (x: Date) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
        qs.set('start', fmt(start));
        qs.set('end', fmt(end));
      }
      for (const [k, v] of Object.entries(params)) {
        if (k !== 'vehicle_name' && k !== 'days' && v !== undefined) qs.set(k, String(v));
      }
      const url = `${SENTIMENT_BASE}/api/dashboard${path.replace('{vehicle_id}', resolved.id)}${qs.toString() ? '?' + qs : ''}`;
      try {
        const res = await fetch(url);
        if (!res.ok) return { content: [{ type: 'text', text: JSON.stringify({ status: 'unavailable', tool: name, reason: `HTTP ${res.status}`, fallback: 'none' }) }] };
        const data = await res.json();
        // 2026-10-20 paused 冻结声明（红线#1）：对象响应顶层注入——不包装整个响应
        // （collectNameTruth 按顶层字段收真值，grounding.ts:86 实证，包装会藏掉名称锚点）；
        // 数组响应跳过（top-posts 每条自带日期，数据自明）。
        if (resolved.status === 'paused' && data && typeof data === 'object' && !Array.isArray(data)) {
          data._prism_frozen_note = `该车舆情已停更（paused），以下为停更前冻结数据，不反映近期动态`;
        }
        return { content: [{ type: 'text', text: JSON.stringify(data) }] };
      } catch (e) {
        return { content: [{ type: 'text', text: JSON.stringify({ status: 'unavailable', tool: name, reason: (e as Error).message, fallback: 'none' }) }] };
      }
    },
  };
}

function registerSentimentTools(pi) {
  pi.registerTool(makeSentimentTool(
    'sentiment_overview', '/overview/{vehicle_id}',
    '查询舆情声量总览（声量/情绪/热度指标）。数据源：舆情 Board。引用格式（supported_by 行 ID）：sentiment_overview:{车系名}，如 sentiment_overview:风云T7。定位=库内舆情快查；全网社媒深挖/画像/调研报告类需求用 load_skill("car-reputation-research")。'
  ));
  pi.registerTool(makeSentimentTool(
    'sentiment_trend', '/trend/{vehicle_id}',
    '查询舆情声量趋势（时间序列）。可选 days 参数（7/14/30）。注意：舆情数据保留线约 30 天，days>30 只返回保留线内数据。引用格式：sentiment_trend:{车系名}。',
    { days: { type: 'number', description: '天数（7/14/30）' } }
  ));
  pi.registerTool(makeSentimentTool(
    'sentiment_dimension', '/dim-sentiment/{vehicle_id}',
    '查询舆情维度分析（按维度拆分情绪 + 示例帖子）。引用格式：sentiment_dimension:{车系名}/{维度}，如 sentiment_dimension:风云T7/续航里程。'
  ));
  pi.registerTool(makeSentimentTool(
    'sentiment_posts', '/top-posts/{vehicle_id}',
    '查询舆情热门帖子（含原文 + 评论）。可选 limit。引用格式：sentiment_posts:{帖ID}（结果里的 id 字段）或 sentiment_posts:{车系名}。',
    { limit: { type: 'number', description: '返回条数' } }
  ));
  pi.registerTool(makeSentimentTool(
    'sentiment_competitive', '/competitor-comparison/{vehicle_id}',
    '查询竞品声量对比（跨车系舆情对比）。引用格式：sentiment_competitive:{车系名}。'
  ));
  pi.registerTool(makeSentimentTool(
    // C1 修正：真实路由为 /vehicles/{vehicle_id}/events（dashboard.py:1399）；
    // 注意填 router 相对路径——execute 已拼 /api/dashboard 前缀，填完整路径会双前缀
    'sentiment_events', '/vehicles/{vehicle_id}/events',
    '查询舆情事件预警（负面事件 + 风险雷达）。引用格式：sentiment_events:{事件ID} 或 sentiment_events:{车系名}。'
  ));
  // 2026-10-20 舆情工具层跟进 T2：缺陷话题簇（第 7 个舆情工具）。端点 10-20 闭环改造后
  // 统一 30 天权威窗（今天−29~今天）+ 24h TTL（夜间 Phase8 批产），start/end 参数保留签名
  // 但已退役（代码不读）——工具走通用路径零特例；LLM 失败保旧载荷。
  pi.registerTool(makeSentimentTool(
    'sentiment_defects', '/defect-themes/{vehicle_id}',
    '查询缺陷话题簇（中低互动帖聚类 + LLM 簇判定，捞热度榜漏掉的早期缺陷讨论，非热度榜）。口径=近 30 天权威窗（夜间批产 + 24h 缓存，LLM 判定失败时保留旧载荷）。引用格式：sentiment_defects:{车系名}，如 sentiment_defects:风云T7。'
  ));
}

// ---------------------------------------------------------------------------
// Atuohome 工具（14 个，调 FastAPI /mcp/ 反代 → Atuohome :8001）
// ---------------------------------------------------------------------------
const AUTOHOME_BASE = process.env.PRISM_AUTOHOME_BASE || `${FASTAPI}/autohome`;
// 真值发射方登记（登记收敛 P2-4）：_truth 收割发生过的工具名——自检校验 ⊆ 业务白名单，
// 防"发射了真值却不在 business 集 → 两闸对其数据全盲"的静默漂移
const truthEmitters = new Set<string>();
// 工作流状态门（登记收敛归档追加）：car-reputation-research 两阶段协议的执行层强制。
// idle → (load_skill 成功) scanning → (新用户轮) named；深挖工具/模板B导出仅在 named 放行。
// 进程内存态（每用户一进程=天然隔离）；重启归 idle 属可接受降级（语义见 workflow-gate.ts 头注）。
let skillPhase: 'idle' | 'scanning' | 'named' = 'idle';

function makeAutohomeTool(name, description, params) {
  return {
    name,
    label: name,
    description,
    parameters: params,
    async execute(toolCallId, p) {
      try {
        // 配置差价工具 sel 容错（skill v2 配套）：模型偶发传逗号字符串 "a:1,b:2"
        // 而非数组（typebox 直接拒，曾致真实对话 39 次工具试错）——归一后放行。
        const args: Record<string, unknown> = { ...p };
        if (name === 'compare_configs_valued' && typeof args.sel === 'string') {
          const arr = (args.sel as string).split(/[,，、\s]+/).filter(Boolean);
          if (arr.length) args.sel = arr;
        }
        const qs = new URLSearchParams();
        for (const [k, v] of Object.entries(args)) {
          if (v === undefined || v === null) continue;
          // 数组参数（如 compare-horizontal 的 sel）须重复键展开，不能 String(list)
          if (Array.isArray(v)) { for (const item of v) qs.append(k, String(item)); }
          else qs.set(k, String(v));
        }
        const res = await fetch(`${AUTOHOME_BASE}/${name}?${qs}`);
        if (!res.ok) return { content: [{ type: 'text', text: JSON.stringify({ status: 'unavailable', tool: name, reason: `HTTP ${res.status}`, fallback: 'none' }) }] };
        const data = await res.json();
        // D2 真值信封（登记收敛）：收割数字/名称真值随响应下发，
        // 采集 handler（tool_result 第一道）入账后剥离——模型上下文零增量。
        try { (data as any)._truth = harvestTruth(data); truthEmitters.add(name); } catch {}
        return { content: [{ type: 'text', text: JSON.stringify(data) }] };
      } catch (e) {
        return { content: [{ type: 'text', text: JSON.stringify({ status: 'unavailable', tool: name, reason: (e as Error).message, fallback: 'none' }) }] };
      }
    },
  };
}

function registerAutohomeTools(pi) {
  // 2026-10-08 迁移适配：数据源切 prism-dashboards(:8010)，仅注册 JSON API 有等价的工具；
  // 退役 4 个（8010 无等价）：get_model_generations / get_energy_analysis / search_news / get_dealer_price
  // 线B B2：search_cars 专用实现——原通用透传把 keyword/brand/价格参数传给无参端点 series-list，
  // 过滤形同虚设且全量 ~100KB 入上下文；且旧描述（series_id/名称/级别）与真实字段不符（explore §8）。
  // 修法：客户端过滤（keyword 车系名包含，去空格）+ 裁列到真实字段 + cap 50 + 命中数。
  // 只选行不改数，红线#1 无涉。brand/price 参数删除（端点无此字段，防模型传无效参）。
  // 人工题集转金标 Block 0：参数扩展（energy/level/price/wheelbase 全可选）+ 双路径——
  // 任一筛选参数 → series_filter 端点服务端过滤（含无零售车系，属性取车系自身最新月）；
  // 仅 keyword/无参 → 原 series-list 客户端过滤路径不动（既有 agent 行为零回归）。
  pi.registerTool({
    name: 'search_cars',
    label: 'search_cars',
    description: '跨车系搜索/筛选市场车系：keyword 车系名过滤，或按能耗（BEV/PHEV/NEV/ICE）/级别/价格区间/轴距区间筛选，按最新零售量降序（无零售排后），最多 50 条。跨车系比较类问题（如"12万左右的纯电车"）用本工具；找具体车系的 series_id/model_id 请用 resolve_series。数据源：prism-dashboards 市场口径。',
    parameters: {
      type: 'object',
      properties: {
        keyword: { type: 'string', description: '车系名关键词（包含匹配，如 银河/海豚）' },
        brand: { type: 'string', description: '品牌筛选，如 奇瑞/吉利/比亚迪' },
        energy: { type: 'string', enum: ['BEV', 'PHEV', 'NEV', 'ICE'], description: '能耗类型：BEV=纯电；PHEV=插混含增程；NEV=新能源；ICE=燃油（传统能源+油电混合）' },
        level: { type: 'string', description: '级别精确匹配（A/A0/A00/B/C/D 等；A 不含 A0）' },
        price_min: { type: 'number', description: '价格区间下限（元，闭区间）' },
        price_max: { type: 'number', description: '价格区间上限（元，闭区间）' },
        wheelbase_min: { type: 'number', description: '轴距区间下限（mm，闭区间）' },
        wheelbase_max: { type: 'number', description: '轴距区间上限（mm，闭区间）' },
      },
    },
    async execute(toolCallId, p) {
      try {
        // Block 0 双路径：任一筛选参数 → 服务端过滤；仅 keyword/无参 → 原路径（不动）
        const filterKeys = ['brand', 'energy', 'level', 'price_min', 'price_max', 'wheelbase_min', 'wheelbase_max'];
        const present = (v: unknown) => v !== undefined && v !== null && v !== '';
        if (filterKeys.some((k) => present((p as Record<string, unknown>)[k]))) {
          const q = new URLSearchParams();
          for (const k of filterKeys) {
            const v = (p as Record<string, unknown>)[k];
            if (present(v)) q.set(k, String(v));
          }
          if (typeof p.keyword === 'string' && p.keyword.trim()) q.set('kw', p.keyword);
          const fres = await fetch(`${AUTOHOME_BASE}/series_filter?${q.toString()}`);
          if (!fres.ok) {
            const detail = await fres.text().catch(() => '');
            return { content: [{ type: 'text', text: JSON.stringify({ status: 'unavailable', tool: 'search_cars', reason: `HTTP ${fres.status} ${detail.slice(0, 200)}`, fallback: 'none' }) }] };
          }
          return { content: [{ type: 'text', text: JSON.stringify(await fres.json()) }] };
        }
        const res = await fetch(`${AUTOHOME_BASE}/search_cars`);
        if (!res.ok) return { content: [{ type: 'text', text: JSON.stringify({ status: 'unavailable', tool: 'search_cars', reason: `HTTP ${res.status}`, fallback: 'none' }) }] };
        const data = await res.json() as { series?: Array<Record<string, unknown>> };
        let rows = data.series || [];
        const total_library = rows.length;
        const kw = typeof p.keyword === 'string' ? p.keyword.replace(/\s+/g, '') : '';
        if (kw) rows = rows.filter((r) => String(r.series || '').replace(/\s+/g, '').includes(kw));
        const total_matched = rows.length;
        const kept = rows.slice(0, 50).map((r) => ({
          series: r.series, latest_retail: r.latest_retail, has_retail: r.has_retail, has_weighted: r.has_weighted,
        }));
        const payload: Record<string, unknown> = {
          rows: kept, total_matched,
          total_library,
          _meta: { source: 'prism-dashboards/market/series-list', note: 'has_weighted=false 表示该系无加权口径数据' },
        };
        if (total_matched > kept.length) {
          payload._truncated = { kept_rows: kept.length, total_matched, hint: '命中超 50 条仅保留前 50；带更具体 keyword 重查可缩小范围' };
        }
        return { content: [{ type: 'text', text: JSON.stringify(payload) }] };
      } catch (e) {
        return { content: [{ type: 'text', text: JSON.stringify({ status: 'unavailable', tool: 'search_cars', reason: (e as Error).message, fallback: 'none' }) }] };
      }
    },
  });
  pi.registerTool(makeAutohomeTool('get_model_detail',
    '获取车系口碑下钻 JSON：facts（样本/续航事实）+ tag_dist（维度标签分布）+ stream（原文流）。数据源：prism-dashboards。',
    { type: 'object', properties: { model_id: { type: 'string', description: '数字 model_id（如 7650），可从 search_cars 或 resolve_series 获取' } }, required: ['model_id'] }
  ));
  pi.registerTool(makeAutohomeTool('get_similar_models',
    '双车口碑对比 v2（样本守卫+可比性体检+分类层对比）。数据源：prism-dashboards。入参 a_mid/b_mid=双方数字 model_id。',
    { type: 'object', properties: { a_mid: { type: 'string', description: '本车数字 model_id' }, a_spec: { type: 'string' }, b_mid: { type: 'string', description: '对比车数字 model_id（必填）' }, b_spec: { type: 'string' } }, required: ['a_mid', 'b_mid'] }
  ));
  pi.registerTool(makeAutohomeTool('get_trims',
    '获取版型列表（含指导价/配置差异）。数据源：prism-dashboards。',
    { type: 'object', properties: { series_id: { type: 'string' } }, required: ['series_id'] }
  ));
  pi.registerTool(makeAutohomeTool('get_config_detail',
    '版型横向对比表（之家式）：座椅/轮胎/智驾/车机等逐项对比。数据源：prism-dashboards。入参 sel=series_id:spec_id（2-6 个）。',
    { type: 'object', properties: { sel: { type: 'array', items: { type: 'string' }, description: '版型选择，格式 series_id:spec_id，如 7650:79311，传 2-6 个' } }, required: ['sel'] }
  ));
  // 配置赋值口径改造 M3：差价引擎出口（61 项口径，diff_pricing 真值表；细节结论纪律见 config-compare skill）
  // skill v2（2026-10-13）：范围扩为差异/差价两用——纯差异问法只讲判定不报金额；sel 必须数组（容错归一在 execute）
  pi.registerTool(makeAutohomeTool('compare_configs_valued',
    '两个/多个版型的配置对比（61 项口径）：逐项多/少/同判定；需要差价时给金额+配置优势+拉平指导价优势，纯差异问题可只看判定。用户问"配置差异/配置区别"（不带金额意图）时本工具同样适用。入参 sel 必须是数组 ["series_id:spec_id",...]（2-6 个，第 1 个为基准版型）；车系级问题先用 get_trims 选定具体版型。数据源：prism-dashboards。',
    { type: 'object', properties: { sel: { type: 'array', items: { type: 'string' }, description: '版型数组，格式 series_id:spec_id，如 ["7650:79311","7650:79310"]，传 2-6 个，第 1 个为基准' } }, required: ['sel'] }
  ));
  pi.registerTool(makeAutohomeTool('get_review_analysis',
    '获取口碑维度标签聚合（tag_dist：各维度 pro/con 分布）。数据源：prism-dashboards。',
    { type: 'object', properties: { model_id: { type: 'string' } }, required: ['model_id'] }
  ));
  pi.registerTool(makeAutohomeTool('search_reviews',
    '全文检索口碑原文（kw=关键词，返回 stream 原文流）。数据源：prism-dashboards。',
    { type: 'object', properties: { model_id: { type: 'string' }, kw: { type: 'string', description: '检索关键词' } }, required: ['model_id', 'kw'] }
  ));
  pi.registerTool(makeAutohomeTool('get_dimension_reviews',
    '获取指定维度的口碑原文（tag=维度名如 舒适/续航，返回 stream 原文流）。数据源：prism-dashboards。',
    { type: 'object', properties: { model_id: { type: 'string' }, tag: { type: 'string', description: '维度名，如 舒适、续航、智能化' } }, required: ['model_id'] }
  ));
  pi.registerTool(makeAutohomeTool('get_sales_detail',
    // C2：参数语义强化（实测模型误传 model_id → HTTP 400）
    '获取销量明细（按月/版型，比 query_sales 更细）。数据源：prism-dashboards。入参 series=车系名（如 银河E5）——不是 model_id、不是数字 ID，传数字 ID 会返回 400。',
    { type: 'object', properties: { series: { type: 'string', description: '车系名，如 银河E5（非 model_id/数字 ID）' }, months: { type: 'number' } }, required: ['series'] }
  ));
  pi.registerTool(makeAutohomeTool('score_models',
    '多车系概念配置对比（评分维度与权重）。数据源：prism-dashboards。',
    { type: 'object', properties: { model_ids: { type: 'array', items: { type: 'string' } }, weights: { type: 'object' } }, required: ['model_ids'] }
  ));
}

// ---------------------------------------------------------------------------
// M1 出口闸：submit_conclusion 工具（方案 §3.1；红线#1 执行层执法）
// 验证失败以 tool_result 返回 → 模型同轮内修正重提（§3.3，不注入 user 消息）
// ---------------------------------------------------------------------------

/** 从 session entries 取最新 identity coverage（agent_settled 同款，最近优先） */
function findIdentityCoverage(entries: any[]): unknown {
  for (let i = entries.length - 1; i >= 0; i--) {
    if (entries[i]?.customType === 'prism-identity-coverage' && entries[i]?.data?.coverage) {
      return entries[i].data.coverage;
    }
  }
  return undefined;
}

function registerGateTool(pi) {
  pi.registerTool({
    name: 'submit_conclusion',
    label: 'Submit Conclusion',
    description: '提交分析结论供出口闸验证（红线#1）。凡基于库数据给出数字结论，必须先调本工具提交 CLAIM，通过后才算交付。拒绝原因会以工具结果返回，请按原因修正后重新提交。supported_by 行 ID 格式（照抄，勿改字段含义）：`sales_trim:银河E5/2026/8`（车系名，不是 series_id 数字）、`review_tags:7650/舒适/con`（model_id/维度/极性）、`config_snapshots:7650/79311`（series_id/spec_id）、`config_diff:midA/specA/midB/specB`（配置差价配对）、舆情结论用 `sentiment_overview:风云T7`（车系名）、`sentiment_dimension:风云T7/续航里程`、`sentiment_posts:帖ID`、`sentiment_events:事件ID`、`sentiment_defects:风云T7`（缺陷簇）。numbers 填写两条硬规则：①value 必须纯数值（去单位去千分位：12.8 而非 "12.8英寸"，65000 而非 "6.5万"）；②自己计算的差价/合计/比值一律 source="derived" 并在 derived_from 列出参与计算的工具源数字（禁止把心算值标 source="tool"）.',
    parameters: {
      type: 'object',
      properties: {
        conclusion_text: { type: 'string', description: '结论一句话（先结论后依据）' },
        supported_by: { type: 'array', items: { type: 'string' }, description: '行 ID，如 review_tags:7650/舒适/con' },
        as_of: { type: 'string', description: '数据时点，如 2026-10-04' },
        scope: { type: 'string', enum: ['口碑内', '配置内', '市场侧不归因', '跨维度'] },
        data_gaps_declared: { type: 'array', items: { type: 'string' } },
        numbers: {
          type: 'array',
          description: '本结论引用的数字清单',
          items: {
            type: 'object',
            properties: {
              value: { type: 'string', description: '归一化裸数值（去千分位/去单位）' },
              source: { type: 'string', enum: ['tool', 'derived'] },
              derived_from: { type: 'array', items: { type: 'string' }, description: 'source=derived 时必填：引用的工具源数字（declared-derived 不可作源）' },
            },
            required: ['value', 'source'],
          },
        },
      },
      required: ['conclusion_text', 'supported_by', 'as_of', 'scope'],
    },
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      // T-G0 已验证（3.5 Gap2）：ExtensionContext.sessionManager 注入 execute ctx（types.d.ts:223）
      const sm = (ctx as any)?.sessionManager;
      const entries: any[] = sm?.getEntries?.() ?? [];
      const ledger = readNumericLedger(entries);

      const claim: Claim = {
        conclusion_text: String(params.conclusion_text || ''),
        supported_by: Array.isArray(params.supported_by) ? params.supported_by.map(String) : [],
        as_of: String(params.as_of || ''),
        scope: (['口碑内', '配置内', '市场侧不归因', '跨维度'].includes(params.scope as string) ? params.scope : '跨维度') as Claim['scope'],
        data_gaps_declared: Array.isArray(params.data_gaps_declared) ? params.data_gaps_declared.map(String) : [],
      };
      // M1 运行时约束（2026-10-07 实测）：pi.exe(Bun) 内 better-sqlite3 触发 NAPI panic
      // → 四件套拆两层：形状校验本地纯函数；行ID查库走 FastAPI /verify/claim（服务端真值）
      const shape = verifyClaimShape(claim, findIdentityCoverage(entries));
      const failures = [...shape.failures];
      if (claim.supported_by.length > 0) {
        try {
          const res = await fetch(`${FASTAPI}/verify/claim`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ supported_by: claim.supported_by }),
          });
          if (res.ok) {
            const data = await res.json() as { failures?: string[] };
            failures.push(...(data.failures || []));
          } else {
            failures.push(`行ID校验服务不可用（HTTP ${res.status}）——暂不能通过，请稍后重试`);  // fail-closed
          }
        } catch {
          failures.push('行ID校验服务不可达——暂不能通过，请稍后重试');  // fail-closed
        }
      }

      // 数字台账比对（v1.4 分信任级）：tool ∈ truth；derived_from 每个 ∈ truth（declared-derived 不算）
      const nums: Array<Record<string, any>> = Array.isArray(params.numbers) ? params.numbers : [];
      for (const n of nums) {
        const raw = String(n?.value ?? '');
        const v = normalizeNumber(raw);
        if (!v) { failures.push(`numbers[].value 无法解析为数值: ${raw.slice(0, 30)}`); continue; }
        const percent = raw.includes('%');
        if (n?.source === 'derived') {
          for (const d of (Array.isArray(n.derived_from) ? n.derived_from : []).map(String)) {
            const dv = normalizeNumber(d);
            if (!dv || !ledgerHasValue(ledger.truth, dv, d.includes('%'))) {
              failures.push(`derived 源 ${d} 不在工具真值集（declared-derived 不可作源）`);
            }
          }
        } else {
          if (!ledgerHasValue(ledger.truth, v, percent)) {
            failures.push(`数字 ${v} 不在工具真值集（source=tool 须为工具返回值）`);
          }
        }
      }

      // 名称校验（与 agent_settled 同款真值集）
      const nameTruth = collectNameTruthFromEntries(entries);
      if (nameTruth.size > 0) {
        const nameResult = verifyNames(claim.conclusion_text, nameTruth);
        if (!nameResult.pass) {
          failures.push(...nameResult.mismatches.map((m: string) => `名称真值不匹配: ${m}`));
        }
        // R1-deep 分层（2026-10-16）：soft 普通词近真值命中只告警不拒——散文词自纠 1-3 次的耗 token 消除
        if (nameResult.softs?.length) console.warn('[verifyNames][soft]', nameResult.softs.join('；'));
      }

      if (failures.length === 0) {
        // 3.5 Gap7 顺序：先回写台账、后写 verified（回写失败不写 verified → fail-closed）
        try {
          const derivedVals = nums.filter(n => n?.source === 'derived').map(n => normalizeNumber(String(n.value ?? ''))).filter(Boolean);
          const toolVals = nums.filter(n => n?.source !== 'derived').map(n => normalizeNumber(String(n.value ?? ''))).filter(Boolean);
          if (derivedVals.length) pi.appendEntry('prism-numeric-truth', { values: derivedVals, kind: 'declared-derived', source: 'submit_conclusion' });
          if (toolVals.length) pi.appendEntry('prism-numeric-truth', { values: toolVals, kind: 'truth', source: 'submit_conclusion' });
        } catch (e) {
          return { content: [{ type: 'text', text: `[出口闸] 拒绝：台账回写失败（${(e as Error).message}），请重试提交` }] };
        }
        try { pi.appendEntry('prism-conclusion-verified', { numbers: nums, ts: new Date().toISOString() }); } catch {}
        return { content: [{ type: 'text', text: '[出口闸] 通过：结论已验证并登记，可据此向用户交付。' }] };
      }
      const rejectText = '[出口闸] 拒绝：\n' + failures.map(f => '- ' + f).join('\n')
        + '\n请修正后重新提交。格式提示：supported_by 用 `sales_trim:银河E5/2026/8` 形态（series=车系名非数字ID，年/月为数字）；舆情引用用 `sentiment_overview:风云T7` / `sentiment_dimension:风云T7/续航里程` / `sentiment_posts:帖ID` / `sentiment_defects:风云T7`；derived_from 只接受工具返回的源数字。';
      return { content: [{ type: 'text', text: rejectText.slice(0, 2000) }] };
    },
  });
}

// ---------------------------------------------------------------------------
// 验证层常量（M2 改道后仅保留在用件）
// 历史：decideVerification 粗筛（数字+维度词→reject）已于 M2 退役——判据从"像不像分析"
// 换成"数字有没有出处"（保底②台账判定），旧函数及 CONCLUSION/EVIDENCE/AS_OF_RE 死代码已清
// ---------------------------------------------------------------------------

/** 数据性数字：带口径单位或 ≥2 位计数才算"数字结论"（年份/日期不算）——保底①②共用形态门 */
export const NUMERIC_CLAIM_RE = /(?<![\d.])\d{2,}(?:\.\d+)?\s*(?:万辆|万台|辆|台|%|分|公里|km|元|条|位|个)/i;

/** 验证器自身回灌的消息前缀（用于阻断自回灌循环 + 链起点识别） */
export const VERIFIER_PREFIX = '[完成验证器]';

/** 验证器自身回灌的那一轮：不再回灌，避免自触发死循环。
 * 注意前缀匹配不带 ']'——M2 文案改 '[完成验证器·保底]' 后曾断裂（']' 在 '·' 前），
 * 导致 retry 轮识别失效（smoke:guard 重写时抓到）：保底③让路失效、链起点误断 */
export function isVerifierRetryTurn(userText: string | undefined): boolean {
  return typeof userText === 'string' && userText.startsWith(VERIFIER_NOTICE_PREFIX);
}

// ---------------------------------------------------------------------------
// P0-2b/c：验证器回灌上限（显式化）+ 同因截断（防同因死循环）
// - VERIFIER_MAX_RETRY：单轮回灌次数上限（写入 verdict 便于观测）
// - lastFailureSigMap：按 session 记录上次回灌的 failure 签名；连续两次同因则停止重试
//   注意：新用户轮（非验证器回灌轮）开始时会清空该 session 的签名，保证新问题可正常重试
// ---------------------------------------------------------------------------
export const VERIFIER_MAX_RETRY = 2; // B1（2026-11-02）：库数据失败允许回灌 2 次（原 1 次）
const lastFailureSigMap = new Map<string, string>();

// ---------------------------------------------------------------------------
// 块2：web 验证辅助函数（verifyWeb + collectWebUrlsThisTurn + verifyNamesWithWebExempt）
// ---------------------------------------------------------------------------

/** N1 URL 真值集：从本轮 branch 收集 web 工具返回的 URL（M3 按最后 user 消息起） */
export function collectWebUrlsThisTurn(branch: BranchEntry[]): Set<string> {
  const urls = new Set<string>();
  let start = 0;
  for (let i = branch.length - 1; i >= 0; i--) {
    if (branch[i]?.type === 'message' && branch[i]?.message?.role === 'user') {
      start = i + 1; break;
    }
  }
  // P0-5：检查两种 toolResult 结构（顶层 role='toolResult' + assistant.content 子条目）
  for (let i = start; i < branch.length; i++) {
    const m = branch[i]?.message;
    // 方式1：顶层 toolResult
    if (m?.role === 'toolResult' && m.toolName && TOOL_CATEGORIES.web.has(m.toolName)) {
      const c = Array.isArray(m.content) ? m.content.map((x: any) => x?.text ?? '').join('') : (typeof m.content === 'string' ? m.content : '');
      const urlMatches = c.match(/https?:\/\/[^\s"'<>)\]，。；！？,;]+/g);
      if (urlMatches) for (const u of urlMatches) urls.add(u.replace(/[，。；！？.,;]+$/, ''));
    }
    // 方式2：assistant.content 里的 toolResult 子条目
    if (m?.role === 'assistant' && Array.isArray(m.content)) {
      for (const x of m.content) {
        if (x?.type === 'toolResult' && x.toolName && TOOL_CATEGORIES.web.has(x.toolName)) {
          const c = typeof x.result === 'string' ? x.result : (x.text || '');
          const urlMatches = c.match(/https?:\/\/[^\s"'<>)\]，。；！？,;]+/g);
          if (urlMatches) for (const u of urlMatches) urls.add(u.replace(/[，。；！？.,;]+$/, ''));
        }
      }
    }
  }
  return urls;
}

/** verifyWeb：web tier 验证（URL 真值集保留 + 业务数字降级） */
const BUSINESS_NUM_RE = /(\d{2,})\s*(台|辆|%|万|公里|km|元|条|分|位)/;
const BUSINESS_KW_RE = /(销量|口碑|配置|零售|同比|环比|市占率|续航|舒适|动力|操控|外观|空间|内饰|安全|价格|智能|辅助驾驶|售后|油耗|电耗|充电)/;

function verifyWeb(text: string, webUrls: Set<string>): { pass: boolean; reason?: string } {
  // 提取回复中的 URL
  const replyUrls = (text.match(/https?:\/\/[^\s"'<>)\]，。；！？,;]+/g) || []).map(u => u.replace(/[，。；！？.,;]+$/, ''));
  if (replyUrls.length === 0) return { pass: false, reason: 'web tier 但回复无 URL 来源标注' };

  // 第一道门：URL 真值集（保留——防编造 URL，红线#1）
  for (const u of replyUrls) {
    if (!webUrls.has(u)) {
      return { pass: false, reason: `URL 不在本轮 web 真值集: ${u.slice(0, 40)}` };
    }
  }
  // host 白名单降为标记（不阻断，通用来源放行）
  // 仅业务数字降级时标注 host 是否可信

  // 业务数字降级告警（不阻断，verdict.json 标注）
  if (BUSINESS_NUM_RE.test(text) && BUSINESS_KW_RE.test(text)) {
    return { pass: true, reason: 'web 来源通过，但含业务数字建议用 query_* 核验' };
  }

  return { pass: true, reason: 'web 来源验证通过' };
}

/** M9 verifyNames 修正：保留编造检测，只放宽"库外名在本轮 web 真值集内" */
function verifyNamesWithWebExempt(text: string, truthNames: Set<string>, webUrls: Set<string>): { pass: boolean; mismatches: string[] } {
  // 从 web 返回内容提取的名称可能在 URL 关联文本里——简化：web 真值集非空时放宽库外名
  const hasWeb = webUrls.size > 0;
  if (!hasWeb) return verifyNames(text, truthNames);

  // 有 web 来源时：只拦 truthNames 内名称被写错，不拦库外名
  //（verifyNames 内部的编造检测对库外名仍生效，但我们在 web tier 下接受 web 来源的库外名）
  // 简化实现：web tier 下跳过 verifyNames（库外名来自 web，truthNames 只含库内名）
  return { pass: true, mismatches: [] };
}

// ---------------------------------------------------------------------------
// CLAIM 提取（T-1.3 移植 completion.ts 配套）
// 从 agent 回复文本提取 Claim 结构，供 verifyCompletion 做完整验证（行ID查库等）
// ---------------------------------------------------------------------------

/** 从回复文本提取 supported_by 行 ID（如 review_tags:7650/舒适/con） */
const REF_RE = /((?:review_tags|sales_trim|config_snapshots|mv_\w+):[^\s，。、）)]+)/g;

function extractClaim(text: string): Claim {
  const supported_by: string[] = [];
  let m: RegExpExecArray | null;
  const re = new RegExp(REF_RE);
  while ((m = re.exec(text)) !== null) {
    supported_by.push(m[1]);
  }

  const asOfMatch = text.match(/as_of[:\s]*(20\d\d[-/年]\d{1,2}(?:[-/月]\d{1,2})?)/i)
    || text.match(/(20\d\d[-/年]\d{1,2}(?:[-/月]\d{1,2})?)/);
  const as_of = asOfMatch ? asOfMatch[1] : '';

  let scope: Claim['scope'] = '跨维度';
  if (/口碑/.test(text) && !/销量|市场|配置/.test(text)) scope = '口碑内';
  else if (/配置/.test(text) && !/销量|市场|口碑/.test(text)) scope = '配置内';
  else if (/销量|市场|同比|环比/.test(text) && !/口碑|配置/.test(text)) scope = '市场侧不归因';

  const data_gaps_declared: string[] = [];
  if (/未接入|数据缺口|缺失|不可得|未覆盖/.test(text)) {
    data_gaps_declared.push('已声明数据缺口');
  }

  return { conclusion_text: text, supported_by, as_of, scope, data_gaps_declared };
}

/** 修正包 F-B（v1.2 归因）：从本链提取「通过」的 CLAIM 证据——最后一次被 prism-conclusion-verified
 *  确认的 submit_conclusion 调用参数（supported_by/as_of）。终稿散文按输出分层政策不含行 ID
 *  （SYSTEM.md §9：溯源由结构化引用承担、不进正文），故 extractClaim(text) 的 REF_RE 在合法回复上
 *  恒空——verdict 行 evidence_ids 必须从提交通道搬运（曾致 89/89 pass 行 evidence_ids 全空）。 */
function extractPassClaimEvidence(branch: unknown[]): { supported_by: string[]; as_of: string } | null {
  let lastSubmit: any = null;
  let passInput: any = null;
  for (const be of branch as any[]) {
    const m = be?.message;
    if (m?.role === 'assistant' && Array.isArray(m.content)) {
      for (const x of m.content) {
        if (x?.type === 'toolCall' && x.name === 'submit_conclusion' && x.input) lastSubmit = x.input;
      }
    }
    if (be?.customType === 'prism-conclusion-verified' && lastSubmit) passInput = lastSubmit;
  }
  if (!passInput) return null;
  return {
    supported_by: Array.isArray(passInput.supported_by) ? passInput.supported_by.map(String) : [],
    as_of: passInput.as_of ? String(passInput.as_of) : '',
  };
}

/** T-4.2：从 session entries 收集 prism-name-truth 真值集（供 verifyNames 比对） */
function collectNameTruthFromEntries(entries: any[]): Set<string> {
  const truth = new Set<string>();
  for (const e of entries) {
    if (e?.customType === 'prism-name-truth' && Array.isArray(e?.data?.names)) {
      for (const n of e.data.names) {
        if (typeof n === 'string' && n.length > 0) truth.add(n);
      }
    }
  }
  return truth;
}

/** T-6.4 Gap 2：写 verdict.json 供 pi_gateway mapEvent 读取
 * P2-1 注：appendEntry 实际会发 entry_appended 事件（pi docs json.md），原"不出事件流"注释有误；
 *   verdict.json 是 mapEvent 读 verdict 的既有契约，保留不变
 * P1-7 修复：按 sessionId 分目录，防多用户并发互相覆盖 */
function writeVerdictFile(sessionId: string, verdict: { pass: boolean; failures?: string[]; reason?: string; retry_limit?: number; retry_count?: number }, claim: Claim, scope: string) {
  try {
    // P1-7：按 sessionId 分目录（同时写 last-verdict.json 兼容旧读取）
    const dir = resolve(process.cwd(), `.pi/sessions/${sessionId}`);
    mkdirSync(dir, { recursive: true });
    const verdictObj = {
      sessionId, verdict: verdict.pass ? 'pass' : 'fail',
      reason: verdict.reason || verdict.failures?.join('; ') || '',
      evidence_ids: claim.supported_by,
      scope, as_of: claim.as_of,
      // P0-2c：回灌上限显式化，便于观测（undefined 时序列化会略去）
      retry_limit: verdict.retry_limit,
      retry_count: verdict.retry_count,
      // M4 修复：can_continue 缺失 → 网关 "!vd.can_continue" 恒真 → fail 一律断流，
      // 回灌重试轮对客户端不可见（E5 实测暴露；P1-6 修复此前从未真正生效）
      can_continue: verdict.pass ? undefined
        : (verdict.retry_count ?? 0) < (verdict.retry_limit ?? 1),
      timestamp: new Date().toISOString(),
    };
    writeFileSync(resolve(dir, 'verdict.json'), JSON.stringify(verdictObj, null, 2));
    // 兼容：同时写 last-verdict.json（开发期单用户兜底，mapEvent 优先读 sessionId 目录）
    writeFileSync(resolve(process.cwd(), '.pi/sessions/last-verdict.json'), JSON.stringify(verdictObj, null, 2));
  } catch { /* 静默 */ }
}

/** T-8.1 落 trajectories.jsonl（badcase 回放用，每 agent_settled 追加一行） */
function appendTrajectory(sessionId: string, branch: BranchEntry[], finalText: string, claim: Claim, verdict: { pass: boolean; failures?: string[]; reason?: string }) {
  try {
    // A5 轨迹分离：eval 网关（prism.py eval start）注入独立轨迹文件，防批跑混入生产北极星统计
    const trajPath = process.env.PRISM_TRAJECTORY_FILE
      ? resolve(process.env.PRISM_TRAJECTORY_FILE)
      : resolve(process.cwd(), '.pi/sessions/trajectories.jsonl');
    mkdirSync(dirname(trajPath), { recursive: true });
    // 提取本轮 tool_call 序列 + tool_result
    const toolCalls: any[] = [];
    const toolResults: any[] = [];
    const conversation: string[] = [];
    // M4：submission 统计（供 runner 断言 E2/E3/E9）
    // 形态兼容：toolResult 既可能是顶层 role='toolResult' 条目，也可能是 assistant.content 内嵌块
    let submitCount = 0, submitPass = false, lastReject = '';
    const noteSubmitResult = (result: unknown) => {
      submitCount++;
      const rt = typeof result === 'string' ? result
        : (Array.isArray((result as any)?.content) ? (result as any).content.map((cc: any) => cc?.text ?? '').join('') : JSON.stringify(result ?? ''));
      if (rt.includes('[出口闸] 通过')) submitPass = true;
      if (rt.includes('[出口闸] 拒绝')) lastReject = rt.slice(0, 200);
    };
    for (const e of branch) {
      if (e?.type === 'message' && e?.message) {
        const m = e.message;
        const c = Array.isArray(m.content) ? m.content.map((x: any) => x?.text ?? '').join('') : (typeof m.content === 'string' ? m.content : '');
        if (c) conversation.push(`${m.role}: ${c.slice(0, 500)}`);
        // 顶层 toolResult 条目
        if (m.role === 'toolResult' && m.toolName) {
          toolResults.push({ name: m.toolName, is_error: (m as any).isError });
          if (m.toolName === 'submit_conclusion') noteSubmitResult((m as any).result ?? (m as any).content);
        }
        if (m.role === 'assistant' && Array.isArray(m.content)) {
          for (const x of m.content) {
            if (x?.type === 'toolCall' && x.name) toolCalls.push({ name: x.name, input: x.input });
            if (x?.type === 'toolResult' && x.toolName) {
              toolResults.push({ name: x.toolName, is_error: x.isError });
              if (x.toolName === 'submit_conclusion') noteSubmitResult(x.result);
            }
          }
        }
      }
    }
    const line = JSON.stringify({
      sessionId, timestamp: new Date().toISOString(),
      // P0 链路焊死：run 标识随行落库（runner 按 evalRunId+userId 精确取，sessionId 仅作兜底）
      ...(evalRunId ? { evalRunId } : {}),
      ...(evalTaskId ? { evalTaskId } : {}),
      ...(evalRepeat != null ? { evalRepeat } : {}),
      ...(ctxUserId ? { userId: ctxUserId } : {}),
      conversation, toolCalls, toolResults,
      final_conclusion: finalText.slice(0, 2000),
      evidence_ids: claim.supported_by, as_of: claim.as_of, scope: claim.scope,
      verdict: verdict.pass ? 'pass' : 'fail',
      verdict_reason: verdict.reason || verdict.failures?.join('; ') || '',
      submission: submitCount > 0 ? { count: submitCount, pass: submitPass, lastReject } : undefined,
    });
    // 轨迹轮转（2026-10-16 尾巴包）：>100MB 轮转 .1（覆盖旧档）——本地持续增长无上限的疣
    try {
      if (statSync(trajPath).size > 100 * 1024 * 1024) {
        renameSync(trajPath, trajPath + '.1');
      }
    } catch { /* 首写/占用忽略——轮转失败不阻塞落盘 */ }
    appendFileSync(trajPath, line + '\n');

    // memory.json 已删除（层1 v4：同会话延续由 pi session branch 承担）
  } catch { /* 静默 */ }
}

export interface BranchEntry {
  type?: string;
  message?: {
    role?: string;
    toolName?: string;
    content?: Array<{ type?: string; name?: string; text?: string }>;
  };
}

/** 取本轮 user 消息文本（用于识别验证器回灌） */
export function lastUserMessageText(branch: BranchEntry[]): string | undefined {
  for (let i = branch.length - 1; i >= 0; i--) {
    const m = branch[i]?.message;
    if (branch[i]?.type === 'message' && m?.role === 'user') {
      const c = m.content;
      if (typeof c === 'string') return c;
      if (Array.isArray(c)) return c.map(x => x?.text ?? '').join('');
      return undefined;
    }
  }
  return undefined;
}

/** 取本轮真实用户消息（跳过验证器回灌伪轮）——回灌轮也要能拿到原题面做对象覆盖核对 */
export function lastRealUserMessageText(branch: BranchEntry[]): string | undefined {
  for (let i = branch.length - 1; i >= 0; i--) {
    const m = branch[i]?.message;
    if (branch[i]?.type === 'message' && m?.role === 'user') {
      const c = m.content;
      const txt = typeof c === 'string' ? c : Array.isArray(c) ? c.map(x => x?.text ?? '').join('') : '';
      if (!isVerifierRetryTurn(txt)) return txt;
    }
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// 对象覆盖守卫（v1.5，2026-11-01）
// 归因：multi-07 题面点名三个对象，agent 只答一个就收尾；红线#5 要求护栏在执行层，
// 不能只靠 SYSTEM.md L23 的"题面点名几条就交付几条"提示词自觉。
// - 清单来源：eval/tasks.json 题集声明 cover_objects（可复算）；线上不做实时抽取，只记录不拦
// - 处置：缺对象 → 回灌 1 次要求补齐；重试轮仍缺 → 记录 prism-object-coverage 后放行（防乒乓）
// - 声明位「未覆盖：X」自然消解：声明的对象名出现在正文即视为已覆盖（不需要额外解析）
// ---------------------------------------------------------------------------
let evalTasksCache: any[] | null = null;

/** 读 eval 题集（进程内缓存；读失败退化为空数组=不拦截，避免守卫自身崩掉落）
 *  合并 dynamic-tasks.json（runner 会把 badcase 自动转的 dyn-* 题并入批跑，守卫对它们同样生效） */
function loadEvalTasksCached(): any[] {
  if (evalTasksCache) return evalTasksCache;
  const merged: any[] = [];
  for (const f of ['eval/tasks.json', 'eval/dynamic-tasks.json']) {
    try {
      const raw = JSON.parse(readFileSync(resolve(process.cwd(), f), 'utf-8'));
      if (Array.isArray(raw)) merged.push(...raw);
    } catch { /* 单个文件缺失不影响另一份 */ }
  }
  evalTasksCache = merged;
  return evalTasksCache;
}

/** 取题面声明的必答对象（多轮题按本轮 message 精确对齐对应 turns 项） */
export function declaredCoverObjects(taskId: string, userText: string | undefined): string[] {
  if (!taskId) return [];
  const task = loadEvalTasksCached().find((t: any) => t?.id === taskId);
  if (!task) return [];
  let raw: any = task.cover_objects;
  if (Array.isArray(task.turns) && userText) {
    const norm = (s: any) => String(s ?? '').replace(/\s+/g, '');
    const hit = task.turns.find((t: any) => norm(t?.message) === norm(userText));
    raw = hit?.cover_objects;
  }
  return Array.isArray(raw)
    ? raw.map((x: any) => typeof x === 'string' ? x : x?.name).filter(Boolean).map(String)
    : [];
}

/** 对象名匹配键：全名 + 含数字的型号尾串（银河E5→e5、零跑B10→b10、风云T7→t7） */
export function coverKeys(name: string): string[] {
  const keys = [String(name).replace(/\s+/g, '').toLowerCase()];
  const runs = String(name).match(/[A-Za-z0-9\-]+/g) || [];
  const model = runs.find(r => /\d/.test(r) && /[A-Za-z]/.test(r));
  if (model && model.length >= 2) keys.push(model.toLowerCase());
  return keys;
}

/** 回答正文中未出现的对象清单（空数组=全覆盖） */
export function findUncoveredObjects(replyText: string, objects: string[]): string[] {
  const hay = String(replyText || '').replace(/\s+/g, '').toLowerCase();
  return objects.filter(name => !coverKeys(name).some(k => hay.includes(k)));
}

// ---------------------------------------------------------------------------
// 横评先筛池守卫（2026-11-02 显著性实验 B 臂）
// 归因：config-07 三跑均未做价格带筛选，直接自选几款比配置 → 金标 top3 未覆盖（2/2/2）。
// 语义：价格带横评问法 + 已进入车型级比较 + 未做价格带/能源筛选 → 触发回灌一次。
// 纯函数（无 IO），正反例契约见 tool_call.test.ts。
// ---------------------------------------------------------------------------

/** 实验臂：唯一真源 eval/.arm（A=守卫关/B=守卫开），缺失按 A（不会伪造改善） */
export function currentArm(): 'A' | 'B' {
  try {
    const v = readFileSync(resolve(process.cwd(), 'eval/.arm'), 'utf-8').trim().toUpperCase();
    return v === 'B' ? 'B' : 'A';
  } catch { return 'A'; }
}

/** 筛选参数（search_cars 服务端过滤路径的入参；任一在场即视为已筛池） */
const POOL_FILTER_KEYS = ['price_min', 'price_max', 'energy', 'level', 'wheelbase_min', 'wheelbase_max', 'brand'];

export function checkPoolGuard(
  question: string,
  toolCalls: Array<{ name?: string; input?: Record<string, any> }>,
): { trigger: boolean; reason: string } {
  const q = String(question || '');
  // 价格带：万 + ≤6 字内出现方位词（"12万元左右"/"15万以下"）
  const band = /万[^。\n]{0,6}(左右|以内|以下|上下|级)/.test(q);
  // 横评意图：配置最好/哪个/哪款/推荐/值得买/横评
  const ask = /配置[^。\n]{0,8}(最好|最高|最强|最全)|哪个|哪款|推荐|值得买|横评/.test(q);
  if (!band || !ask) return { trigger: false, reason: '非价格带横评问法' };
  const names = toolCalls.map(t => String(t?.name || ''));
  const compared = names.includes('compare_configs_valued') || names.includes('get_trims');
  if (!compared) return { trigger: false, reason: '未进入车型级配置比较' };
  const screened = toolCalls.some(t => t?.name === 'search_cars' && t?.input
    && POOL_FILTER_KEYS.some(k => t.input![k] !== undefined && t.input![k] !== null && t.input![k] !== ''));
  if (screened) return { trigger: false, reason: '已做价格带/能源筛选' };
  return { trigger: true, reason: '横评未先按价格带筛池' };
}

// ---------------------------------------------------------------------------
// TikHub 社媒工具（社媒深挖能力包 M1：调 api.tikhub.dev，web 类 = 不可复算外部源）
// ---------------------------------------------------------------------------

function makeSocialTool(name: string, description: string, params: Record<string, any>, required: string[], action: 'search' | 'comments' | 'profile' | 'posts') {
  return {
    name,
    label: name,
    description: description + ' ' +
      '引用规范：结果属外部付费 API 即时快照（不可复算），引用须标注 来源平台+URL+抓取时间（结果 _meta.as_of），' +
      '且回复正文中逐条附 URL（不能只写进导出文件）。' +
      `成本护栏：TikHub 工具每轮最多 ${TIKHUB_LIMIT} 次调用。`,
    parameters: { type: 'object', properties: params, required },
    async execute(toolCallId: string, p: Record<string, any>) {
      return executeAction(name, action, p);
    },
  };
}

function registerTikhubTools(pi: any) {
  const PLATFORM_ALL = {
    type: 'string', enum: ['douyin', 'xiaohongshu', 'weibo', 'kuaishou', 'bilibili'],
    description: '平台：抖音/小红书/微博/快手/哔哩哔哩',
  };
  const PLATFORM_USER = {
    type: 'string', enum: ['douyin', 'xiaohongshu'],
    description: '平台（用户画像/作品列表当前仅支持抖音/小红书）',
  };
  pi.registerTool(makeSocialTool(
    'social_search',
    '社媒平台搜索帖子/视频/笔记（免登录，抖音/小红书/微博/快手/哔哩哔哩）。用于车型口碑扫描、舆情补充、找真实车主发帖。',
    {
      platform: PLATFORM_ALL,
      keyword: { type: 'string', description: '搜索词，如 "风云T7 提车" / "银河E5 续航"' },
      time_window: { type: 'string', enum: ['day', 'week', 'month', 'halfyear'], description: '时间窗（可选；平台不支持的档位自动忽略）' },
      page: { type: 'number', description: '页码（默认 1）' },
    },
    ['platform', 'keyword'],
    'search',
  ));
  pi.registerTool(makeSocialTool(
    'social_post_comments',
    '拉取社媒帖子的评论（评论区是购车细节金矿：车主常在评论区自述落地价/配置/有无现车）。post_url_or_id 接受帖子链接或裸 ID。',
    {
      platform: PLATFORM_ALL,
      post_url_or_id: { type: 'string', description: '帖子 URL（douyin.com/video/{id}、xiaohongshu.com/explore/{id} 或 xhslink 短链、m.weibo.cn/status/{id}、bilibili.com/video/{bv_id}）或裸 ID' },
      max: { type: 'number', description: '最多返回条数（默认 20，上限 50）' },
    },
    ['platform', 'post_url_or_id'],
    'comments',
  ));
  pi.registerTool(makeSocialTool(
    'social_user_profile',
    '查询社媒用户主页画像（昵称/简介/粉丝数/获赞/作品数/IP属地/性别，抖音含年龄线索）。用于典型车主/发帖人深挖的画像采集。',
    {
      platform: PLATFORM_USER,
      user_id: { type: 'string', description: '四种均可：①搜索结果作者字段里的昵称（直接可用，如"开奇瑞的杨仔"）②sec_uid（MS4wLjAB…）③纯数字抖音号 ④主页/分享链接。搜索结果的 author 字段自带昵称与 sec_uid——不要以"拿不到 ID"为由跳过深挖' },
    },
    ['platform', 'user_id'],
    'profile',
  ));
  pi.registerTool(makeSocialTool(
    'social_user_posts',
    '查询社媒用户的公开作品/笔记列表（含标题/发布时间/互动数）。用于典型车主深挖：还原其发帖轨迹与决策链时间线。',
    {
      platform: PLATFORM_USER,
      user_id: { type: 'string', description: '四种均可：①搜索结果作者昵称 ②sec_uid ③数字抖音号 ④主页/分享链接（同 social_user_profile；不要以"没有原生 ID"为由跳过）' },
      cursor: { type: 'string', description: '翻页游标（可选，取上页返回值）' },
      count: { type: 'number', description: '每页条数（默认 20，上限 30）' },
    },
    ['platform', 'user_id'],
    'posts',
  ));
}

// ---------------------------------------------------------------------------
// load_skill 工具（社媒深挖能力包 M2：技能渐进披露，替代被排除的 read）
// ---------------------------------------------------------------------------

function registerSkillTool(pi: any) {
  // D5（登记收敛）：技能目录从 .pi/skills/ 扫描生成（listSkills），消灭硬编码目录漂移——
  // 2026-10-13 实证：手工目录漏列 config-compare 致技能对模型不存在。
  const skillCatalog = listSkills()
    .map(s => `${s.name}——${(s.summary || '（无摘要）').slice(0, 60)}`)
    .join('；');
  pi.registerTool({
    name: 'load_skill',
    label: 'load_skill',
    description:
      '加载技能工作流全文。可用技能：' + (skillCatalog || '（暂无，目录扫描为空）') +
      '。用户请求命中任一技能场景时，先 load_skill(name) 加载全文再动手。' +
      'file 参数省略读 SKILL.md，传如 references/deliverable-spec.md 读引用文档。read 工具不可用，技能一律经本工具加载。',
    parameters: {
      type: 'object',
      properties: {
        name: { type: 'string', description: '技能名（小写字母/数字/连字符），如 car-reputation-research' },
        file: { type: 'string', description: '技能内相对路径（可选，默认 SKILL.md），如 references/deliverable-spec.md' },
        named_target: { type: 'string', description: '（仅 car-reputation-research）用户已在请求里指名道姓要深挖的具体对象（人/昵称）时填写——跳过扫描阶段直接进入深挖轮。用户未点名时不要填' },
      },
      required: ['name'],
    },
    async execute(toolCallId: string, p: Record<string, any>) {
      const r = readSkillFile(p.name, p.file);
      if (!r.ok) {
        return { content: [{ type: 'text', text: JSON.stringify({ status: 'unavailable', tool: 'load_skill', reason: r.reason, fallback: 'none' }) }] };
      }
      // 工作流状态门（登记收敛归档追加）：加载调研技能 → 进入扫描阶段（深挖工具上锁）；
      // 用户已点名（named_target）→ 直接 named（协议例外：指名道姓可跳过扫描轮，skill 文本条款）
      if (p.name === WORKFLOW_SKILL) {
        const nt = typeof p.named_target === 'string' ? p.named_target.trim() : '';
        skillPhase = nt ? 'named' : 'scanning';
        if (nt) { try { pi.appendEntry('prism-skill-phase', { phase: 'named', target: nt }); } catch {} }
      }
      const payload = { skill: p.name, file: p.file || 'SKILL.md', content: r.text, more_files: r.files };
      const { text } = truncateOutput(JSON.stringify(payload));
      return { content: [{ type: 'text', text }] };
    },
  });
}

// ---------------------------------------------------------------------------
// export_document 工具（社媒深挖能力包 M3：xlsx 交付，调 FastAPI /export）
// ---------------------------------------------------------------------------

function registerExportTool(pi: any) {
  pi.registerTool({
    name: 'export_document',
    label: 'export_document',
    description:
      '把表格数据导出为原生 .xlsx 文件并返回下载链接（典型用途：口碑调研报告、典型用户分析、对照表）。' +
      'sheets=[{name, headers, rows}]，单 sheet rows 建议 ≤200（过大先聚合）。' +
      '导出成功后在回复正文中用 markdown 链接给出返回的 url（相对路径，如 /export/download/{id}）。' +
      '数值/引语须已带来源列（URL 或行 ID）——交付物必须可溯源。',
    parameters: {
      type: 'object',
      properties: {
        title: { type: 'string', description: '报告标题，如 "风云T7典型用户分析"' },
        filename: { type: 'string', description: '文件名（可选，如 风云T7典型用户分析.xlsx；非法字符自动替换）' },
        sheets: {
          type: 'array',
          description: '工作表数组；每项 {name:表名, headers:[列头], rows:[[单元格,…],…]}',
          items: {
            type: 'object',
            properties: {
              name: { type: 'string', description: '工作表名（≤31字）' },
              headers: { type: 'array', items: { type: 'string' }, description: '列头' },
              rows: { type: 'array', items: { type: 'array' }, description: '数据行（单元格标量）' },
            },
            required: ['name', 'headers', 'rows'],
          },
        },
      },
      required: ['title', 'sheets'],
    },
    async execute(toolCallId: string, p: Record<string, any>) {
      const fail = (reason: string) => ({ content: [{ type: 'text' as const, text: JSON.stringify({ status: 'unavailable', tool: 'export_document', reason, fallback: 'none' }) }] });
      try {
        const res = await fetch(`${FASTAPI}/export`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: p.title, filename: p.filename, sheets: p.sheets }),
          signal: AbortSignal.timeout(30000),
        });
        const data = await res.json().catch(() => null);
        if (!res.ok || !data?.file_id) {
          return fail(`导出失败 HTTP ${res.status}：${typeof data?.detail === 'string' ? data.detail : JSON.stringify(data).slice(0, 150)}`);
        }
        return { content: [{ type: 'text', text: JSON.stringify({ status: 'ok', tool: 'export_document', file_id: data.file_id, filename: data.filename, url: data.url, sheets: data.sheets, hint: '在回复正文用 markdown 链接给用户：[下载 xlsx](url)' }) }] };
      } catch (e) {
        return fail(`导出服务不可达：${(e as Error).message}`);
      }
    },
  });
}

// ---------------------------------------------------------------------------
// Extension 工厂
// ---------------------------------------------------------------------------
export default function (pi) {
  // D1 启动自检（登记收敛）：包装 registerTool 记录实际注册名——三表互检在 before_agent_start。
  // 必须先于一切 register 调用（晚于则 registeredTools 缺员、自检全误报——self-check Gap1）。
  const registeredTools = new Set<string>();
  let selfCheckReported = false;
  const __origRegister = pi.registerTool.bind(pi);
  (pi as any).registerTool = (t: any) => { registeredTools.add(t?.name || String(t)); return __origRegister(t); };
  // 注册业务工具（3 口径视图 + 7 舆情 + 11 dashboards + resolve_series + 出口闸 = 23 个）
  registerPrismTools(pi);
  registerSentimentTools(pi);
  registerAutohomeTools(pi);
  registerGateTool(pi);
  // 社媒深挖能力包：TikHub 4 工具（web 类，不入业务白名单计数）
  registerTikhubTools(pi);
  // 社媒深挖能力包：load_skill（技能渐进披露）+ export_document（xlsx 交付，M3）
  registerSkillTool(pi);
  registerExportTool(pi);

  // before_agent_start：注入 AGENTS.md（红线SOP）+ SYSTEM.md（角色约束）
  // 块4 B2：从 ctx.json 读上下文（弃 prompt 前缀，不污染 prompt）
  pi.on('before_agent_start', async (event, ctx) => {
    // TikHub 每轮调用计数清零（回灌轮算新轮——before_agent_start 每次 agent run 均触发）
    tikhubCounter.reset();
    // 工作流状态门推进（登记收敛归档追加）：新用户轮（非回灌）把 scanning 推进到 named——
    // 用户已发声=可点名进入深挖。回灌轮不推进（验证器消化轮不应解锁深挖）。
    try {
      const promptText = typeof (event as any).prompt === 'string' ? (event as any).prompt : '';
      if (shouldAdvancePhase(skillPhase, promptText, isVerifierRetryTurn(promptText))) skillPhase = 'named';
    } catch {}
    // D1 启动自检（fail-loud，只首报）：登记三表互检 + 技能目录非空。漂移=告警不阻断（D5）。
    if (!selfCheckReported) {
      selfCheckReported = true;
      let skillsCount = 0;
      try { skillsCount = listSkills().length; } catch (e) { console.error('[prism-guardrails][自检] 技能目录扫描异常: ' + (e as Error).message); }
      const drift = collectRegistrationDrift(registeredTools, TRUNCATABLE_TOOLS, KNOWN_BUSINESS_TOOLS, skillsCount, truthEmitters);
      if (drift.length) console.error('[prism-guardrails][自检] 登记漂移: ' + drift.join(' | '));
    }

    let prompt = event.systemPrompt;

    // 读 ctx.json（P0-2：从 session 目录精确读，不扫盘）
    let seriesKey = '';
    let scope = 'agent';
    let userId = '';
    try {
      // 层0：从 session 文件路径推算 ctx.json（per-session）
      const sessionFile = (ctx as any)?.sessionManager?.getSessionFile?.() || '';
      if (sessionFile) {
        const sessionDir = sessionFile.replace(/[^/\\]+$/, '');
        const basename = sessionFile.split(/[/\\]/).pop()?.replace('.jsonl', '') || 'default';
        // P2-2：统一 key——优先按 pi sessionId 读（与网关写入对齐），再退回 jsonl basename（兼容旧写）
        // M3 T-S2：追加 'default' 候选（网关 fresh spawn 首轮 get_state 未返 sessionId 时写
        // default.ctx.json；网关每轮先写后 prompt，读到必新鲜）
        const sessionIdKey = (ctx as any)?.sessionManager?.getSessionId?.() || '';
        const ctxCandidates = [sessionIdKey, basename, 'default']
          .filter(Boolean)
          .map(k => resolve(sessionDir, k + '.ctx.json'));
        for (const ctxPath of ctxCandidates) {
          if (existsSyncSafe(ctxPath)) {
            const ctxData = JSON.parse(readFileSync(ctxPath, 'utf-8'));
            seriesKey = ctxData.series_key || '';
            scope = ctxData.scope || 'agent';
            userId = ctxData.user_id || '';
            // P0 链路焊死：eval 批次标识随 ctx 逐轮刷新（网关每轮先写后 prompt）
            evalRunId = ctxData.eval_run_id || '';
            evalTaskId = ctxData.eval_task_id || '';
            evalRepeat = Number.isInteger(ctxData.eval_repeat) ? ctxData.eval_repeat : null;
            ctxUserId = userId;
            try { unlinkSyncSafe(ctxPath); } catch {}
            break;
          }
        }
      }
    } catch {}

    // B2-2 录制归属：eval 用户名 eval_<taskId> → fixture 目录按题分（非 eval 用户落 _unknown）
    currentEvalTaskId = userId.startsWith('eval_') ? userId.slice(5) : (userId || '_unknown');

    // scope → setActiveTools（Gap 3：extension API 非网关）
    // A/R3：agent 模式也显式 setActiveTools（非注释维持），单一来源 ALLOWED_TOOLS
    // P2-5：setActiveTools 异常 fail-closed（不静默放行全工具）
    // P3：catch 降级到 [...KNOWN_BUSINESS_TOOLS]（去 ask_user_question，防 N1 反噬）
    // B2-2 web 受控：eval 上下文 off 剔除 pi-web-access 4 工具（只剔 web4，social_* 不波及——G1）
    try {
      // 看板模式预留（当前 agent 场景不触发，前端只发 scope='agent'）
      if (scope === 'bi_reviews') pi.setActiveTools(['query_reviews', 'resolve_series']);
      else if (scope === 'bi_sales') pi.setActiveTools(['query_sales', 'resolve_series']);
      else if (scope === 'bi_config') pi.setActiveTools(['query_config', 'resolve_series']);
      else if (EVAL_WEB_MODE === 'off' || (EVAL_WEB_MODE === 'fixture' && !existsSyncSafe(WEB_FIXTURE_DIR))) {
        pi.setActiveTools([...ALLOWED_TOOLS].filter((t) => !PI_WEB_ACCESS_TOOLS.has(t))); // 库内题零外呼
      }
      else pi.setActiveTools([...ALLOWED_TOOLS]);  // agent 模式：全业务白名单（live/fixture/生产）
    } catch (e) {
      console.error('[prism-guardrails] setActiveTools 失败，fail-closed:', (e as Error).message);
      try { pi.setActiveTools([...KNOWN_BUSINESS_TOOLS]); } catch (e2) { console.error('[prism-guardrails] catch 降级失败:', (e2 as Error).message); }
    }

    // 身份强制已移除：series_key 为空时不再 setActiveTools([]) 阻断
    // 红线#7 替代护栏在 agent_settled 执行层判据（2b）
    // M3 T-S1：只持久化非空 series_key——空值 append 会在回灌轮覆盖有效历史值
    //（回灌轮 before_agent_start 重跑时 ctx 已被消费删除 → 读到空 → 2b 判据被空值污染）
    if (seriesKey) {
      try { pi.appendEntry('prism-session-series-key', { series_key: seriesKey }); } catch {}
    }
    let identityCoverage: unknown = undefined;
    let identityWarning = '';
    let verifiedSeriesId = '';
    // seriesKey 非空时才 fetch /identity/resolve（空则跳过，避免空请求）
    if (seriesKey) {
      try {
        const res = await fetch(`${FASTAPI}/identity/resolve?series_key=${encodeURIComponent(seriesKey)}`);
        if (res.ok) {
          const idr = await res.json();
          identityCoverage = idr.coverage;
          if (idr.ambiguous) {
            identityWarning = `对象"${seriesKey}"歧义，命中 ${idr.candidates?.length ?? '?'} 候选：${(idr.candidates ?? []).slice(0, 5).join(' / ')}。请让用户澄清具体车系。`;
          } else if (idr.needs_online_verify) {
            identityWarning = `对象"${seriesKey}"未在库中确认（alias 未命中或数据全空，红线#7 fail-closed）。不要进行任何分析，直接告诉用户该对象未收录或需澄清。`;
          } else if (idr.series_id) {
            seriesKey = idr.canonical_name || seriesKey;
            verifiedSeriesId = String(idr.series_id);
          }
        } else {
          identityWarning = `身份核验服务返回 ${res.status}（fail-closed）。不要进行分析，告知用户核验服务暂不可用。`;
        }
      } catch {
        identityWarning = `身份核验服务不可达（fail-closed）。不要进行分析，告知用户核验服务暂不可用。`;
      }
    }
    // P2-8 修复：identityCoverage 存 session entry，供 agent_settled verifyCompletion 取出
    if (identityCoverage) {
      try { pi.appendEntry('prism-identity-coverage', { coverage: identityCoverage }); } catch {}
    }

    // 层1：提示词分层——通用层每轮注入，汽车分析层按需注入
    // 1. 通用层（每轮）
    try {
      const generalMd = readFileSync(resolve(process.cwd(), 'PRISM_GENERAL.md'), 'utf-8');
      prompt += '\n\n' + generalMd;
    } catch (e) {
      // A1b（2026-11-02）：缺文件不再静默——日志 + systemPrompt 双可见
      const msg = 'PRISM_GENERAL.md 未加载（通用能力层不可用）: ' + (e as Error).message;
      console.error('[prism-guardrails] ' + msg);
      prompt += '\n\n[提示词层缺失] ' + msg;
    }

    // 2. 意图检测：用户消息含分析词/维度词/车系名 → 注入汽车层
    const userMessage = (event as any)?.prompt || '';
    const ANALYSIS_RE = /销量|口碑|配置|对比|分析|报告|结论|环比|同比|市占率|零售|交付|舆情|市场|表现|评价|怎么样|值不值|好不好|推荐/;
    const DIMENSION_RE = /舒适|动力|操控|外观|空间|内饰|安全|价格|智能|辅助驾驶|售后|油耗|续航|电耗|充电/;
    const hasAnalysis = ANALYSIS_RE.test(userMessage);
    const hasDimension = DIMENSION_RE.test(userMessage);
    const hasCarSeries = !!seriesKey;  // series_key 非空也算

    // 3. 数据能力子层（涉及汽车数据即注入）
    if (hasAnalysis || hasDimension || hasCarSeries) {
      try {
        const systemMd = readFileSync(resolve(process.cwd(), 'SYSTEM.md'), 'utf-8');
        const warningsText = identityWarning || (seriesKey ? '无' : '未选择车系，查汽车数据时请先确认对象');
        const filled = systemMd
          .replace('{series_key}', seriesKey || '未指定')
          .replace('{series_id}', verifiedSeriesId || '(待核验)')
          .replace('{mode}', scope === 'agent' ? '对话模式' : '看板模式(' + scope + ')')
          .replace('{as_of}', new Date().toISOString().slice(0, 10))
          .replace('{warnings}', warningsText);
        prompt += '\n\n' + filled;
        if (identityWarning) {
          prompt += '\n\n[对象身份核验] ' + identityWarning;
        }
      } catch (e) {
        const msg = 'SYSTEM.md 未加载（角色/作答纪律不可用）: ' + (e as Error).message;
        console.error('[prism-guardrails] ' + msg);
        prompt += '\n\n[提示词层缺失] ' + msg;
      }
    }

    // 4. 分析框架子层（仅分析/判断问题注入）
    if (hasAnalysis) {
      try {
        const analysisMd = readFileSync(resolve(process.cwd(), 'PRISM_ANALYSIS.md'), 'utf-8');
        prompt += '\n\n' + analysisMd;
      } catch (e) {
        const msg = 'PRISM_ANALYSIS.md 未加载（分析框架不可用）: ' + (e as Error).message;
        console.error('[prism-guardrails] ' + msg);
        prompt += '\n\n[提示词层缺失] ' + msg;
      }
    }

    // memory.json 已删除（层1 v4：同会话延续由 pi session branch 承担）

    // 社媒深挖能力包 M2：技能指针行（不依赖 pi 原生发现；明示 read 不可用防教坏，self-check Gap1）
    prompt += '\n\n[技能] 车型社媒口碑调研/典型用户深挖工作流：调 load_skill("car-reputation-research") 加载'
      + '（read 工具不可用，技能一律经 load_skill 加载；触发场景：全网口碑扫描/真实车主识别/典型用户画像）。';

    return { systemPrompt: prompt };
  });

  // tool_call：行为级拦截 + fail-closed 未知业务工具
  // 职责划分（V2.1+R3-1 定夺）：
  //   - permission-system（已运行）：工具级批准，弹确认框
  //   - guardrail（此处）：行为级拦截（裸SQL/敏感文件/数据库直连）+ fail-closed 未知业务工具
  //   - 两者不重叠，叠加使用。--exclude-tools 管 pi 内置危险工具排除
  pi.on('tool_call', async (event) => {
    // 工作流状态门（登记收敛归档追加）：scanning 态锁深挖工具与模板 B 导出——
    // 两阶段协议的执行层强制（红线#5 法治），被拦时返回可自纠的指引。
    if (skillPhase === 'scanning') {
      const g = decideWorkflowGate(skillPhase, event.toolName, JSON.stringify(event.input || {}));
      if (g.block) return { block: true, reason: g.reason, terminate: false };
    }
    // B2-2 fixture 回放：web4 调用改道录制件（零外呼；block reason 携带原样数据）
    if (EVAL_WEB_MODE === 'fixture' && PI_WEB_ACCESS_TOOLS.has(event.toolName)) {
      const replay = webFixtureReplay(event.toolName, event.input);
      if (replay) return replay;
    }
    // TikHub 成本护栏：每轮上限，超限 fail-closed（引导走数据缺口范式，不硬凑）
    // P2 修复：缺必要参数的无效调用不计入预算（8 次无效调用不该耗尽配额；参数校验细节由 executeAction 报错）
    if (TIKHUB_TOOLS.has(event.toolName)) {
      const inp = (event.input || {}) as Record<string, any>;
      const hasEssential =
        (event.toolName === 'social_search' && inp.keyword) ||
        (event.toolName === 'social_post_comments' && inp.post_url_or_id) ||
        (event.toolName === 'social_user_profile' && inp.user_id) ||
        (event.toolName === 'social_user_posts' && inp.user_id);
      if (hasEssential) {
        const overLimit = tikhubCounter.bump();
        if (overLimit) {
          return { block: true, reason: TIKHUB_LIMIT_MSG, terminate: false };
        }
      }
    }
    const verdict = decideToolCall(event.toolName, event.input);
    if (verdict.block) {
      return { block: true, reason: verdict.reason, terminate: verdict.terminate };
    }
  });

  // tool_result：grounding（红线#1，校验 _meta + 标注名称真值集）+ M1 数字台账采集
  // 顺序契约（登记收敛 D2）：本 handler 内【先入账 → 再剥离 _truth】；截断在第二 handler。
  // 后续新增采集逻辑不得注册在本 handler 之后（截断看到的必须是已剥离的内容）。
  pi.on('tool_result', async (event) => {
    if (!event.toolName) return;

    // B2-2 web fixture 录制（live+PRISM_WEB_FIXTURE_DIR）：web4 工具结果按题落盘
    // （tool 层录制——模型实际看到的内容；本分支只旁观不改写，须在采集/截断逻辑之前）
    if (EVAL_WEB_MODE === 'live' && PI_WEB_ACCESS_TOOLS.has(event.toolName)) {
      try {
        const dir = resolve(WEB_FIXTURE_DIR, currentEvalTaskId);
        mkdirSync(dir, { recursive: true });
        const text = event.content?.map((c: any) => c.type === 'text' ? c.text : '').join('') || '';
        appendFileSync(resolve(dir, 'tools.jsonl'), JSON.stringify({
          ts: new Date().toISOString(), tool: event.toolName, input: event.input,
          isError: event.isError ?? false, content: text.slice(0, 100 * 1024),
        }) + '\n');
        console.error(`[prism-guardrails][web-record] 录制 ${event.toolName}（${currentEvalTaskId}，${text.length} 字）`);
      } catch (e) { console.error('[prism-guardrails][web-record] 落盘失败:', (e as Error).message); }
    }

    // D2 真值信封（登记收敛）：makeAutohomeTool 已在响应附 _truth{numbers,names}——
    // 入双账本后【剥离 _truth】再返回（模型上下文零增量）。剥离在最外层（self-check Gap2：
    // 只要解析出 _truth 就剥，入账条件分开判）；剥离后的文本仍走下方 generic 台账 walk（number 型兜底）。
    if (TOOL_CATEGORIES.business.has(event.toolName)) {
      const truthRaw = event.content?.map(c => c.type === 'text' ? c.text : '').join('') || '';
      let truthPayload: any = null;
      try { truthPayload = JSON.parse(truthRaw); } catch { truthPayload = null; }
      if (truthPayload && typeof truthPayload === 'object' && (truthPayload as any)._truth) {
        const tr = (truthPayload as any)._truth || {};
        if (Array.isArray(tr.numbers) && tr.numbers.length) {
          try { pi.appendEntry('prism-numeric-truth', { values: tr.numbers, kind: 'truth', source: event.toolName }); } catch {}
        }
        if (Array.isArray(tr.names) && tr.names.length) {
          try { pi.appendEntry('prism-name-truth', { names: tr.names, source: event.toolName }); } catch {}
        }
        const stripped = { ...truthPayload }; delete (stripped as any)._truth;
        // P1-1（隔离审查）：_truth 分支不再整包 generic walk——total/page/elapsed_ms 等响应元数据
        // 不得以 kind='truth' 入账；数据数字由 harvestTruth 选择性收割（已含 diff 金额段）。
        return { content: [{ type: 'text', text: JSON.stringify(stripped) }] };
      }
    }

    // M1 台账采集（§3.2）：business 全部数据工具（不含 submit_conclusion 自身）；错误载荷跳过（v1.5）
    if (TOOL_CATEGORIES.business.has(event.toolName) && event.toolName !== 'submit_conclusion') {
      const ledgerText = event.content?.map(c => c.type === 'text' ? c.text : '').join('') || '';
      if (!looksLikeErrorPayload(ledgerText)) {
        const values = extractLedgerValues(ledgerText);
        if (values.length > 0) {
          try { pi.appendEntry('prism-numeric-truth', { values, kind: 'truth', source: event.toolName }); } catch {}
        }
      }
    }

    // 社媒深挖能力包 M1：social_* 的名称真值 = 查询词（_meta.keyword）——车系名来自用户查询，
    // 是 agent 引用名称的天然锚点；items 里的昵称/正文不是名称字段，不进真值集（防污染）。
    // social_* 无 _meta.as_of 协议（web 类），不走下方 query_* 的 _warning 改写。
    if (event.toolName.startsWith('social_')) {
      try {
        const t = event.content?.map((c: any) => c.type === 'text' ? c.text : '').join('') || '';
        const d = JSON.parse(t);
        const kw = d?._meta?.keyword;
        if (kw) {
          try { pi.appendEntry('prism-name-truth', { names: [String(kw)], source: event.toolName }); } catch {}
        }
      } catch {}
      return;
    }

    // 出口闸源登记第二弹分支已退役（登记收敛 D2）：其形态感知采集被 _truth 信封 +
    // 上方 harvestTruth 泛化收割替代（同一能力，单点实现）。

    // G1（2026-10-11 出口闸舆情源登记）：名称真值采集范围扩至 resolve_series + sentiment_*
    // （舆情轮次不调 query_* 时真值集也要有锚点，否则品牌/维度/平台词全进 findClosest 误报）。
    // _meta as_of 校验仍仅限 query_*（舆情/resolve 无此协议，套上会被 _warning 全量改写）
    const isQueryTool = event.toolName.startsWith('query_');
    const isNameSource = isQueryTool || event.toolName === 'resolve_series' || event.toolName.startsWith('sentiment_');
    if (!isNameSource) return;

    const text = event.content?.map(c => c.type === 'text' ? c.text : '').join('') || '';
    try {
      const data = JSON.parse(text);
      // C3 联动：失败载荷（unavailable）不套 _meta、不进名称真值集
      if (data?.status === 'unavailable') return;
      // 校验 _meta（口径声明）——仅 query_*
      if (isQueryTool && (!data._meta || !data._meta.as_of)) {
        return {
          content: [{ type: 'text', text: JSON.stringify({ ...data, _warning: '缺少 as_of 口径声明' }) }],
        };
      }
      // 收集名称真值集（T-4.2 + G1：rows 数组 / 顶层数组（舆情多数端点）/ flat 对象（resolve_series））
      const rows = Array.isArray(data) ? data : (Array.isArray(data?.rows) ? data.rows : [data]);
      const truthSet = collectNameTruth(rows);
      if (truthSet.size > 0) {
        try { pi.appendEntry('prism-name-truth', { names: [...truthSet], source: event.toolName }); } catch {}
      }
    } catch {
      // 非 JSON，原样返回
    }
  });

  // agent_settled：出口闸改道（M2）——旧"事后正则验散文+回灌"退役
  // ─── 线B：统一工具结果截断（第二个 tool_result handler）─────────────────────
  // 顺序契约（self-check Gap1）：必须注册在上方采集/校验 handler **之后**——
  // pi tool_result 链式中间件按注册顺序执行：台账/名称真值/_meta 校验先看全量，
  // 本 handler 后跑，返回的 content 补丁才是进模型上下文与会话文件的内容
  //（"台账先抽后截"由注册顺序结构性保证；后续新增采集 handler 不得注册在本 handler 之后）。
  pi.on('tool_result', async (event) => {
    if (!event.toolName || !TRUNCATABLE_TOOLS.has(event.toolName)) return;
    const text = event.content?.map((c: any) => c.type === 'text' ? c.text : '').join('') || '';
    if (!text || text.length <= TRUNCATE_MAX_CHARS) return;
    // 整体兜底（审查 P2-1）：截断器任何异常不得 fail-open 放全量入上下文，退化 head/tail
    try {
      // 旁路文件（best-effort）：先写盘再截断——成功拿路径、失败传空；
      // 路径经 opts 进 _truncated marker（审查 P1-1：二次 parse 注入对顶层数组无效）
      let bypassPath = '';
      try {
        mkdirSync(TOOL_OUTPUT_DIR, { recursive: true });
        const ts = new Date().toISOString().replace(/[:.]/g, '-');
        // 审查 P2-2：并行工具模式同毫秒完成会同名互覆，追加 toolCallId
        bypassPath = resolve(TOOL_OUTPUT_DIR, `${ts}-${String(event.toolCallId || '').replace(/[^a-zA-Z0-9_-]/g, '')}-${event.toolName}.json`);
        writeFileSync(bypassPath, text, 'utf8');
      } catch { bypassPath = ''; }
      const r = truncateToolResult(text, {
        maxChars: TRUNCATE_MAX_CHARS,
        groupKey: TRUNCATE_DIST_KEYS[event.toolName],
        bypassPath: bypassPath || undefined,
      });
      if (!r.truncated) return;
      return { content: [{ type: 'text', text: r.text }] };
    } catch {
      return { content: [{ type: 'text', text: text.slice(0, 12000) + '\n…[_TRUNCATE_ERROR: 截断器异常退化截断]\n' + text.slice(-4000) }] };
    }
  });

  // 新职责：保底③身份 → 出口闸通过 pass → web/mixed（维持）→ 保底①漏提交 / ②凭空编造 → 默认 pass
  pi.on('agent_settled', async (_event, ctx) => {
    const entries = ctx.sessionManager.getEntries();
    const lastEntry = entries[entries.length - 1];
    // P2-10 修复：早返回（已 verified，compact/resume 二次触发）也写 verdict，防 mapEvent 读 stale
    if (lastEntry && lastEntry.customType === 'prism-verified') {
      // P2-10：早返回不重写 verdict（防 compact/resume 二次触发覆盖好 verdict）
      return;
    }

    const branch = ctx.sessionManager.getBranch();
    const lastAssistant = [...branch].reverse().find(e =>
      e.type === 'message' && e.message?.role === 'assistant'
    );
    if (!lastAssistant) return;

    const text = lastAssistant.message.content
      ?.filter(c => c.type === 'text')
      .map(c => c.text)
      .join('') || '';

    // 块2：tier 路由（P1-1：calledTools 限制到本轮，非全 branch）
    let turnStart = 0;
    for (let i = branch.length - 1; i >= 0; i--) {
      if (branch[i]?.type === 'message' && branch[i]?.message?.role === 'user') { turnStart = i + 1; break; }
    }
    const calledTools = branch.slice(turnStart).filter(e => e?.message?.role === 'assistant' && Array.isArray(e?.message?.content))
      .flatMap(e => e!.message!.content.filter((c: any) => c?.type === 'toolCall').map((c: any) => c.name));
    const tier = decideTier(calledTools);
    const sessionId = ctx.sessionManager?.getSessionId?.()
      ?? (ctx as any).sessionId ?? 'default';

    // P0-2b：新用户轮清 mixed 路径的内存签名（保底路径已改链级计数，无需清——链起点天然隔离）
    if (!isVerifierRetryTurn(lastUserMessageText(branch))) {
      lastFailureSigMap.delete(sessionId);
    }

    // 保底共用落盘+回灌（M2：语义化文案——系统校验通知，不回复通知本身）
    // E9 实测修正：同因截断只拦"连续同因"——保底①③交替失败可绕过（乒乓回灌，实测 200+ 轮）。
    // 改为链级总量硬顶：数 branch 内自最近一条真实用户消息以来的失败 settle 数（prism-verified
    // entry 落 session 文件，跨重启持久 = N9；计数即事实，无独立状态可失真）
    const backfill = (failures: string[], claim: Claim, scope: string, guidance: string) => {
      let chainFails = 0;
      for (let i = branch.length - 1; i >= 0; i--) {
        const be = branch[i] as any;
        if (be?.type === 'message' && be?.message?.role === 'user') {
          const txt = typeof be.message.content === 'string' ? be.message.content
            : Array.isArray(be.message.content) ? be.message.content.map((x: any) => x?.text ?? '').join('') : '';
          if (!txt.startsWith(VERIFIER_PREFIX)) break;  // 真实用户消息 = 链起点
        }
        if (be?.customType === 'prism-verified' && be?.data?.pass === false) chainFails++;
      }
      const canRetry = !isVerifierRetryTurn(lastUserMessageText(branch)) && chainFails < VERIFIER_MAX_RETRY;
      try { pi.appendEntry('prism-verified', { pass: false, reasons: failures, exhausted: !canRetry }); } catch {}
      writeVerdictFile(sessionId, { pass: false, failures, retry_limit: VERIFIER_MAX_RETRY, retry_count: chainFails }, claim, scope);
      appendTrajectory(sessionId, branch, text, claim, { pass: false, failures });
      if (canRetry) {
        const msg = VERIFIER_NOTICE_PREFIX + '·保底] ' + guidance
          + '\n修正后必须重新调用 submit_conclusion 提交（结论维持也须原样重交——仅回复确认文字不算提交），不要重述全文结论。'
          + '\n这是系统校验通知——请直接按要求修正（调 submit_conclusion 重新提交 / 核验对象），不要回复本通知。';
        try { pi.appendCustomMessageEntry('prism-verifier-retry', msg, false); } catch { try { pi.sendUserMessage(msg); } catch {} }
      }
    };

    // F1（v1.2 批跑归因修复）：已过闸/已提交判定从"本轮"扩为"本链"——自最近一条真实用户
    // 消息（VERIFIER_PREFIX 回灌伪轮不算链起点）以来扫描。此前本轮作用域把重试轮的"一句话
    // 确认"（未重新调 submit）误判为漏提交，与回灌机制乒乓至重试上限——v1.2 批跑 57 题全灭
    // 的真凶（归因报告：openspec/changes/多轮评估批/v1.2批跑归因报告.md）。
    let chainStart = branch.length; // 无真实用户消息时的兜底=全链
    for (let i = branch.length - 1; i >= 0; i--) {
      const be = branch[i] as any;
      if (be?.type === 'message' && be?.message?.role === 'user') {
        const txt = typeof be.message.content === 'string' ? be.message.content
          : Array.isArray(be.message.content) ? be.message.content.map((x: any) => x?.text ?? '').join('') : '';
        if (!txt.startsWith(VERIFIER_PREFIX)) { chainStart = i; break; }
      }
    }
    let turnVerified = false;
    for (let i = branch.length - 1; i >= chainStart; i--) {
      if ((branch[i] as any)?.customType === 'prism-conclusion-verified') { turnVerified = true; break; }
    }
    // 本链是否有提交记录（无通过 = 至少一次被拒，供保底①文案区分；两种 toolResult 形态兼容）
    let turnHasSubmit = false;
    for (let i = branch.length - 1; i >= chainStart; i--) {
      const m = branch[i]?.message;
      if (m?.role === 'assistant' && Array.isArray(m.content) &&
          m.content.some((c: any) => c?.type === 'toolResult' && c?.toolName === 'submit_conclusion')) {
        turnHasSubmit = true; break;
      }
      if (m?.role === 'toolResult' && m?.toolName === 'submit_conclusion') { turnHasSubmit = true; break; }
    }

    // 保底③ 身份未核验（原 2b 判据平移，优先级最高——先验身份再验提交；
    // 读取侧修正：只认最新非空 series_key；
    // E9 实测修正：回灌轮跳过——retry 轮模型在消化上一条意见，此时弹"新类别"意见
    //（身份）会与保底① 乒乓（模型为答①调 submit 没调 resolve → ③拦 → 为答③调 resolve
    //  没提交 → ①拦 → …）。回灌轮不叠加新意见类别）
    const isRetryTurn = isVerifierRetryTurn(lastUserMessageText(branch));
    if (tier === 'library' && !isRetryTurn) {
      let sessionSeriesKey = '';
      for (let i = entries.length - 1; i >= 0; i--) {
        if (entries[i]?.customType === 'prism-session-series-key' && entries[i]?.data?.series_key) {
          sessionSeriesKey = entries[i].data.series_key;
          break;
        }
      }
      if (!sessionSeriesKey && !calledTools.includes('resolve_series')) {
        backfill(['未核验对象身份（红线#7）'], extractClaim(text), '跨维度',
          '本轮在做库数据分析，但未调用 resolve_series 确认对象。请先核验车系再下结论。');
        return;
      }
    }

    // ── 对象覆盖守卫（v1.5，2026-11-01）：eval 模式拦截，线上只记录 ──────────
    // 归因：multi-07 题面点名 E5/B10/T7 三对象，回答只覆盖一个就收尾（2 分同源坏例）。
    // 清单来自 eval/tasks.json 的 cover_objects 声明（可复算）；线上无声明故天然只记录。
    // 处置：缺对象 → 回灌 1 次；重试轮仍缺 → 记录 prism-object-coverage 后放行（不乒乓）。
    if (text) {
      const coverObjects = declaredCoverObjects(evalTaskId, lastRealUserMessageText(branch));
      if (coverObjects.length > 0) {
        const uncovered = findUncoveredObjects(text, coverObjects);
        if (uncovered.length > 0) {
          const evalMode = !!process.env.PRISM_TRAJECTORY_FILE;
          try {
            pi.appendEntry('prism-object-coverage', {
              task_id: evalTaskId, declared: coverObjects, missing: uncovered,
              eval: evalMode, retry: isRetryTurn, enforced: evalMode && !isRetryTurn,
            });
          } catch {}
          if (evalMode && !isRetryTurn) {
            const coverClaim = extractClaim(text);
            backfill([`未覆盖题面对象: ${uncovered.join('、')}`], coverClaim, coverClaim.scope,
              `题面点名了 ${coverObjects.length} 个对象，回答里缺 ${uncovered.length} 个：${uncovered.join('、')}。`
              + '请逐对象补齐结论（各自给数或给判断，不整段罗列）；确实无法覆盖的，在回复末尾逐条写明「未覆盖：对象名（原因）」。');
            return;
          }
        }
      }
    }

    // ── 横评先筛池守卫（2026-11-02 显著性实验 B 臂）：eval 模式拦截，线上只记录 ──
    // 归因：config-07 三跑均未做价格带筛选，直接自选车型比配置 → 金标 top3 未覆盖。
    // 处置：触发 → 回灌 1 次；重试轮不再回灌（防乒乓）。臂=A 时整段跳过（零副作用）。
    if (text && currentArm() === 'B') {
      const poolCalls = branch.slice(turnStart)
        .filter((e: any) => e?.message?.role === 'assistant' && Array.isArray(e?.message?.content))
        .flatMap((e: any) => e.message.content
          .filter((c: any) => c?.type === 'toolCall')
          .map((c: any) => ({ name: c.name, input: c.input })));
      const poolCheck = checkPoolGuard(lastRealUserMessageText(branch), poolCalls);
      if (poolCheck.trigger) {
        const evalMode = !!process.env.PRISM_TRAJECTORY_FILE;
        try {
          pi.appendEntry('prism-pool-guard', {
            task_id: evalTaskId, eval: evalMode, retry: isRetryTurn,
            enforced: evalMode && !isRetryTurn, reason: poolCheck.reason,
          });
        } catch {}
        if (evalMode && !isRetryTurn) {
          const poolClaim = extractClaim(text);
          backfill(['横评未先筛候选池'], poolClaim, poolClaim.scope,
            '本轮是价格带横评问题，但你没有先按价格带+能源检索市场车系就进入车型级配置比较。'
            + '请先调用 search_cars（带 price_min / price_max / energy）取该价位按最新月销量降序的候选池，'
            + '再对池内前 5 款逐款取价位内版型做横评；配置数据缺失的车系照实点名，不得因此剔除。');
          return;
        }
      }
    }

    // 出口闸通过 → pass（主路径）
    if (turnVerified) {
      try { pi.appendEntry('prism-verified', { pass: true, reason: '出口闸通过（submit_conclusion 已验证）' }); } catch {}
      const c = extractClaim(text);
      // F-B（修正包）：verdict 行证据从通过的 submit 参数搬运——正文按输出分层政策无行 ID，
      // extractClaim 的散文抽取在合法回复上恒空（v1.2 89/89 pass 行 evidence_ids 全空的根因）
      const ev = extractPassClaimEvidence(branch);
      if (ev) {
        if (ev.supported_by.length) c.supported_by = ev.supported_by;
        if (ev.as_of) c.as_of = ev.as_of;
      }
      writeVerdictFile(sessionId, { pass: true, reason: '出口闸通过' }, c, c.scope);
      appendTrajectory(sessionId, branch, text, c, { pass: true, reason: '出口闸通过' });
      return;
    }

    // tier='web' 或 'mixed'：web 验证（URL 真值集）
    if (tier === 'web' || tier === 'mixed') {
      const webUrls = collectWebUrlsThisTurn(branch);
      const webResult = verifyWeb(text, webUrls);
      // mixed tier：库部分仍走 verifyCompletion（如果有库行 ID）
      if (tier === 'mixed') {
        const claim = extractClaim(text);
        let identityCoverage: unknown = undefined;
        for (const e of entries) {
          if (e?.customType === 'prism-identity-coverage' && e?.data?.coverage) {
            identityCoverage = e.data.coverage; break;
          }
        }
        // M2 运行时约束（2026-10-07 实测）：pi.exe(Bun) 内 better-sqlite3 NAPI panic
        // → 形状校验本地 + 行ID查库走 FastAPI /verify/claim（服务端真值，fail-closed）
        let libResult;
        try {
          const shape = verifyClaimShape(claim, identityCoverage);
          const failures = [...shape.failures];
          if (claim.supported_by.length > 0) {
            try {
              const vr = await fetch(`${FASTAPI}/verify/claim`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ supported_by: claim.supported_by }),
              });
              if (vr.ok) { const vd = await vr.json() as { failures?: string[] }; failures.push(...(vd.failures || [])); }
              else failures.push(`行ID校验服务不可用（HTTP ${vr.status}）`);
            } catch { failures.push('行ID校验服务不可达'); }
          }
          libResult = { pass: failures.length === 0, failures, attempt: 1, can_continue: true };
        }
        catch (e) { libResult = { pass: false, failures: [`verifyClaimShape 异常: ${(e as Error).message}`], attempt: 1, can_continue: true }; }
        // M9：verifyNames 只拦 truthNames 内名称（库外名在 web 真值集内放行）
        if (libResult.pass) {
          const nameTruth = collectNameTruthFromEntries(entries);
          if (nameTruth.size > 0) {
            const nameResult = verifyNamesWithWebExempt(text, nameTruth, webUrls);
            if (!nameResult.pass) {
              libResult = { ...libResult, pass: false, failures: [...libResult.failures, ...nameResult.mismatches.map((m: string) => `名称不匹配: ${m}`)] };
            }
          }
        }
        if (webResult.pass && libResult.pass) {
          try { pi.appendEntry('prism-verified', { pass: true, reason: 'mixed tier 通过（库+web）' }); } catch {}
          writeVerdictFile(sessionId, { pass: true, reason: 'mixed tier 通过' }, extractClaim(text), extractClaim(text).scope);
          appendTrajectory(sessionId, branch, text, extractClaim(text), { pass: true, reason: 'mixed 通过' });
          return;
        }
        // P0-3：lib pass 但 web fail → 降级告警（不硬死，同 pure web 降级逻辑）
        if (libResult.pass && !webResult.pass) {
          try { pi.appendEntry('prism-verified', { pass: true, reason: 'mixed: 库通过 web 降级 - ' + (webResult.reason||''), web_downgrade: true }); } catch {}
          writeVerdictFile(sessionId, { pass: true, reason: 'mixed 库通过 web 降级: ' + (webResult.reason||''), web_downgrade: true }, extractClaim(text), extractClaim(text).scope);
          appendTrajectory(sessionId, branch, text, extractClaim(text), { pass: true, reason: 'mixed web 降级' });
          return;
        }
        // P0-2a：mixed 分支新增放行——web 通过，但库部分的唯一失败是"缺少 supported_by 行 ID"
        // 场景：库外事实（上市时间/新闻）给不出库行 ID → verifyCompletion 必然判 fail → 落入回灌。
        // 该情形结论来源已由 web 真值集兜底，判 pass，不回灌、不置 web_downgrade。
        const claimForMixed = extractClaim(text);
        const libFails = libResult.failures || [];
        const onlyMissingSupportedBy = libFails.length > 0 && libFails.every(f => f === '缺少 supported_by 行 ID');
        const noLibRowIds = !claimForMixed.supported_by || claimForMixed.supported_by.length === 0;
        if (webResult.pass && !libResult.pass && noLibRowIds && onlyMissingSupportedBy) {
          try { pi.appendEntry('prism-verified', { pass: true, reason: 'mixed: web 兜底（库外事实无库行 ID）' }); } catch {}
          writeVerdictFile(sessionId, { pass: true, reason: 'mixed web 兜底：库外事实无库行 ID' }, claimForMixed, claimForMixed.scope);
          appendTrajectory(sessionId, branch, text, claimForMixed, { pass: true, reason: 'mixed web 兜底' });
          return;
        }
        // lib fail → 回灌（P0-2b 同因截断 + P0-2c 上限显式化）
        const mixedFailures = [...(libResult.failures||[]), ...(webResult.reason?[webResult.reason]:[])];
        const mixedSig = mixedFailures.join('; ');
        const mixedSameAsLast = lastFailureSigMap.get(sessionId) === mixedSig;  // 连续两次同因 → 停止重试
        const canRetry = !isVerifierRetryTurn(lastUserMessageText(branch)) && libResult.can_continue && !mixedSameAsLast;
        try { pi.appendEntry('prism-verified', { pass: false, reasons: mixedFailures, exhausted: !canRetry }); } catch {}
        writeVerdictFile(sessionId, { pass: false, failures: mixedFailures, retry_limit: VERIFIER_MAX_RETRY, retry_count: mixedSameAsLast ? VERIFIER_MAX_RETRY : 0 }, claimForMixed, claimForMixed.scope);
        appendTrajectory(sessionId, branch, text, claimForMixed, { pass: false, failures: libResult.failures });
        if (canRetry) {
          lastFailureSigMap.set(sessionId, mixedSig);
          const retryMsg = '[完成验证器] mixed tier 验收未通过：' + mixedFailures.join('; ');
          try { pi.appendCustomMessageEntry('prism-verifier-retry', retryMsg, false); } catch { try { pi.sendUserMessage(retryMsg); } catch {} }
        }
        return;
      }
      // pure web tier
      if (webResult.pass) {
        try { pi.appendEntry('prism-verified', { pass: true, reason: webResult.reason || 'web tier 通过' }); } catch {}
        writeVerdictFile(sessionId, { pass: true, reason: 'web tier 通过' }, extractClaim(text), '跨维度');
        appendTrajectory(sessionId, branch, text, extractClaim(text), { pass: true, reason: 'web 通过' });
        return;
      }
      // web fail → 降级告警（不回灌不阻断）
      try { pi.appendEntry('prism-verified', { pass: true, reason: webResult.reason || 'web 来源标注', web_downgrade: true }); } catch {}
      writeVerdictFile(sessionId, { pass: true, reason: 'web 降级告警: ' + (webResult.reason||''), web_downgrade: true }, extractClaim(text), '跨维度');
      appendTrajectory(sessionId, branch, text, extractClaim(text), { pass: true, reason: 'web 降级' });
      return;
    }

    // tier=library/none：出口闸保底（design §3.4）——旧 decideVerification/verifyCompletion 链路退役
    if (NUMERIC_CLAIM_RE.test(text)) {
      // 保底① 漏提交：做了库数据分析（tier=library）却未走出口闸
      if (tier === 'library') {
        const guidance = turnHasSubmit
          ? '本轮 submit_conclusion 提交被拒后未修正重提。请按拒绝原因修正后重新提交。'
          : '本轮含库数据数字结论但未通过 submit_conclusion 提交。请调 submit_conclusion 提交 CLAIM（含 supported_by/as_of/scope/numbers）。';
        backfill(['数字结论未经出口闸提交（漏提交）'], extractClaim(text), extractClaim(text).scope, guidance);
        return;
      }
      // 保底② 凭空编造：tier=none 且任一数字 ∉ ②判定集（truth ∪ declaredDerived，v1.5）
      if (tier === 'none') {
        const tokens = extractProseTokens(text);
        if (tokens.length > 0) {
          const ledger = readNumericLedger(entries);
          const union = new Set([...ledger.truth, ...ledger.declaredDerived]);
          const untraceable = [...new Set(tokens.filter(t => !ledgerHasValue(union, t.value, t.percent, t.wan)).map(t => t.value))];
          if (untraceable.length > 0) {
            backfill([`凭空编造数字（不在会话台账）: ${untraceable.join(', ')}`], extractClaim(text), extractClaim(text).scope,
              `回复中的数字 ${untraceable.join('、')} 未经任何工具返回或出口闸验证（红线#1）。请先查数再作答，或声明数据缺口。`);
            return;
          }
        }
      }
    }

    // 默认 pass（闲聊 / 复述已核验数字 / 过程叙述——现行"数字+维度词"粗筛退役）
    const passReason = tier === 'library'
      ? '本轮已查数但未形成需提交的数字结论（过程说明）'
      : '闲聊 / 复述 / 能力说明，放行';
    try { pi.appendEntry('prism-verified', { pass: true, reason: passReason }); } catch {}
    const passClaim = extractClaim(text);
    writeVerdictFile(sessionId, { pass: true, reason: passReason }, passClaim, passClaim.scope);
    appendTrajectory(sessionId, branch, text, passClaim, { pass: true, reason: passReason });
  });

  // session_before_compact：观测（开发期不自定义）
  pi.on('session_before_compact', async (_event) => {
    // 开发期：不 cancel，不自定义 summary，让 pi 默认压缩
    return;
  });

  // session_start：初始化
  pi.on('session_start', async (_event, ctx) => {
    // 可在此恢复 in-memory 状态
  });

  // session_shutdown：清理
  pi.on('session_shutdown', async (_event) => {
    // 清理 session-scoped 资源
  });
}
