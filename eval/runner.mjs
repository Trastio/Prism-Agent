/**
 * Prism-Agent · 评估批跑脚本（eval/runner.mjs）
 *
 * 循环调 pi_gateway /chat，收集 agent 回复 + 工具调用 + 验证器结果，
 * 输出每题分数 + 汇总报告。
 *
 * 用法：node eval/runner.mjs [--only=前缀] [--set=dev|frozen|blind|all] [--dry-run] [--gate] [--repeat=k]
 *      评测环境：PRISM_API_BASE=http://127.0.0.1:8003（prism.py eval start 拉起的快照实例）
 * 前提：网关 pi_gateway(:9200) + FastAPI(:8002) 在跑（缺省生产端口）
 *      --set 按 task.set 过滤（缺省 all，ci.sh 兼容）；--dry-run 只打印过滤结果不跑题不落报告
 *      --set=blind 只跑盲测集（从未参与判据/容差/提示词调参的题）；all 不含 blind，盲测须显式单跑
 *      盲测纪律：blind 题跑过一次即降级 frozen（set 就地改回），不得再用其结果回调判据
 *      --repeat=k 同题跑 k 次汇总（D2 一致闸：verdict 同+失败态同+分差≤1 → k_pass）
 *      多轮题 task.turns=[{message,truth?}] 依序 POST（session_id 穿线复用，判分=终轮+逐轮 truth）
 *      条件题 requires:["web"|"tikhub"]：启动探测不可用 → skip 不计分母（conditional_skipped 单列）
 */

import { readFileSync, existsSync, writeFileSync as _wf, unlinkSync, readdirSync, statSync, mkdirSync as _mkdir } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execSync, spawnSync } from 'node:child_process';
import { trapBlocked, checkOverreach } from './trap_check.mjs';
import { deductionFromReasons } from './deduction.mjs'; // 判分账本（2026-10-29）：扣分步骤结构化留痕（rescore 同源规则表）
import { checkTruth, DEFAULT_RULES } from './truth_check.mjs';
import { checkRubric } from './rubric_check.mjs'; // B2-1 中间档判分
import { challengerScore, buildAuditList, STRUCTURAL_TOOL_TRAPS } from './challenger_check.mjs'; // 取代性实验 B 系列（§10.2）：--challenger 臂判分（no-verdict 纯文本；默认路径零引用；STRUCTURAL=臂间可比指标剔除清单 审查P1-2）
import { firstErrorTurn, deriveBoundary, buildManifest, splitByAnchored, pickTrajectory, computeCoverage, compareRuns, kPassStats, passAtK } from './report_lib.mjs'; // 评估基建小包：首错轮+boundary+哈希侧车+可判集拆分+轨迹取行/覆盖率闸+回归报警+重复性一致闸（只派生，不动判分）
import { computeFingerprint, PROMPT_FILES } from './prompt_gate.mjs'; // prompt-gate：报告绑定提示词版本（教材 7.10.4）
const PROMPT_FP = computeFingerprint(PROMPT_FILES);
import { writeEvalTrace, lookupTraceId } from './langfuse_writer.ts'; // Node≥22 type-strip 直载（A3 评分写回 + T4 traceId 查询）
import { resolveMessage, selectBranch, carryCheck, checkSnapshotDrift } from './multi_turn.mjs'; // 多轮评估批 change：三机制纯函数（variants 话术轮换 / branch_on 条件分支 / carryCheck 穿线 / P1-2 快照漂移闸）
import { bindEvalRun } from './langfuse_binding.ts'; // langfuse 深度绑定（2026-10-19 change）：题库→dataset 同步 + run 链接（fail-soft）

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
// 判分规则指纹：判分相关字段变更才变。回归报警只在同版本之间比较，
// 避免"补了判据"被误报成"分数下滑"（2026-10-26 首次补锚点即出现 -60pp 假警）。
// 2026-10-29 修正：此前对 tasks.json 整文件哈希——改 set（dev/frozen/blind）这类纯归类字段
// 也会换指纹，把可比基线无故切断（实测 a4e12be004d97cc8 → aa49626b69451ac2 仅因盲测划分）。
// 现只取影响判分的字段；整文件哈希另存 CONTENT_FP 供审计，不参与可比性判定。
const SCORING_FP = (() => {
  const h = createHash('sha256');
  try {
    const tasks = JSON.parse(readFileSync(resolve(ROOT, 'eval/tasks.json'), 'utf-8'));
    const scoringFields = tasks.map((t) => ({
      id: t.id,
      dimension: t.dimension ?? null,          // 影响 isSocialTask 判据分支
      truth: t.truth ?? null,
      trap_type: t.trap_type ?? null,
      trap_params: t.trap_params ?? null,
      judge_rubric: t.judge_rubric ?? null,
      rubric_params: t.rubric_params ?? null,
      expected_evidence: t.expected_evidence ?? null,
      ui_strategy: t.ui_strategy ?? null,      // 影响 agent 收到的应答，间接影响分数
      turns: Array.isArray(t.turns)
        ? t.turns.map((x) => ({ message: x.message ?? null, truth: x.truth ?? null, branch_on: x.branch_on ?? null, new_session: x.new_session ?? null }))
        : null,
    }));
    h.update(JSON.stringify(scoringFields));
  } catch {}
  for (const f of ['eval/scoring-rules.json', 'eval/rubric_check.mjs', 'eval/trap_check.mjs', 'eval/truth_check.mjs', 'src/verify/completion.ts', 'src/verify/grounding.ts']) {
    try { h.update(readFileSync(resolve(ROOT, f))); } catch {}
  }
  return h.digest('hex').slice(0, 16);
})();
// 题库整文件指纹（仅审计留痕：可证明"跑的是哪一版题库"，但不当作可比性判据）
const CONTENT_FP = (() => {
  const h = createHash('sha256');
  try { h.update(readFileSync(resolve(ROOT, 'eval/tasks.json'))); } catch {}
  return h.digest('hex').slice(0, 16);
})();
// P0-#28：评测连快照实例（prism.py eval start，api:8003）；缺省 = 生产 8002
const GATEWAY = process.env.PRISM_API_BASE || 'http://127.0.0.1:8002';

// P0-#30 题源合一：唯一机器源 = eval/tasks.json（schema 三字段 snapshot_id/set/judge_rubric 见 方案§3.2；
// tasks_v1.ts 仅为阶段1设计归档，勿在此平行维护第二份题库）
const TASKS = JSON.parse(readFileSync(resolve(ROOT, 'eval/tasks.json'), 'utf-8'));

// ── 登录门禁（登录门禁 change T3，2026-10-15）：启动先过 /auth/login 拿 cookie，
// 后续所有 API fetch 携带；失败 fail-loud 退出（不静默跑成全 401）。dry-run 保持离线可验。
let AUTH_COOKIE = '';
let AUTH_USER = null; // 登录身份（token 用户名）——api 层 resolve_user_id 用它覆盖一切 body user_id，
// 网关 RPC 池按该身份键控 → ui-response/abort 回填必须用它（用题级 eval_<task> 会 404 no active session）
async function ensureLogin() {
  if (DRY_RUN) return; // dry-run 零网络请求（B1-2：无网关亦可验）
  const user = process.env.PRISM_EVAL_USER || 'eval';
  const pass = process.env.PRISM_EVAL_PASS || '666666';
  try {
    const res = await fetch(`${GATEWAY}/auth/login`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: user, password: pass }),
      signal: AbortSignal.timeout(10_000),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const m = (res.headers.get('set-cookie') || '').match(/prism_token=([^;]+)/);
    if (!m) throw new Error('响应无 prism_token cookie');
    AUTH_COOKIE = `prism_token=${m[1]}`;
    AUTH_USER = user;
    console.error(`[auth] eval 已登录: ${user}@${GATEWAY}`);
  } catch (e) {
    console.error(`[auth] 登录失败（${e.message}）——确认服务在跑/PRISM_EVAL_USER/PRISM_EVAL_PASS 配置；不静默跑成全 401`);
    process.exit(1);
  }
}
const authHeaders = () => (AUTH_COOKIE ? { Cookie: AUTH_COOKIE } : {});

// T-8.4 动态评测集：合并 dynamic-tasks.json（badcase 自动转题）
import { existsSync as _exists } from 'node:fs';
const DYNAMIC_TASKS_FILE = resolve(process.cwd(), 'eval/dynamic-tasks.json');
let DYNAMIC_TASKS = [];
if (_exists(DYNAMIC_TASKS_FILE)) {
  try { DYNAMIC_TASKS = JSON.parse(readFileSync(DYNAMIC_TASKS_FILE, 'utf-8')); } catch {}
}
const ONLY = (process.argv.find(a => a.startsWith('--only=')) || '').slice(7) || null; // --only=social 前缀匹配；支持逗号分隔多前缀
const ONLY_LIST = ONLY ? ONLY.split(',').map((s) => s.trim()).filter(Boolean) : null;
// B1-2 --set 题集过滤：缺省 all（ci.sh 兼容）；dev/frozen/blind 按 task.set 精确匹配（无 set 的题仅在 all 出现）
// 2026-10-27 盲测集：blind = 从未参与判据/容差/提示词调参的题，必须显式 --set=blind 单跑；
//   all 明确排除 blind，防止日常回归/CI 顺手把盲测消耗掉（报告 metadata.set_filter 留痕批次归属）。
const SET_ARG = (process.argv.find(a => a.startsWith('--set=')) || '').slice(6) || 'all';
// 2026-11-02 实验批：set 支持逗号多选（--set=dev,experiment），并新增 experiment 集合。
// experiment = 本次显著性实验的自制同机制题：不进 all、不转 frozen，日常全量仍是 63 题。
const SETS = SET_ARG.split(',').map((s) => s.trim()).filter(Boolean);
const ALLOWED_SETS = ['dev', 'frozen', 'blind', 'dynamic', 'experiment', 'all'];
if (!SETS.length || SETS.some((s) => !ALLOWED_SETS.includes(s))) {
  console.error(`--set 取值非法: ${SET_ARG}（dev|frozen|blind|dynamic|experiment|all，可逗号多选）`);
  process.exit(1);
}
const SET = SET_ARG;
const DRY_RUN = process.argv.includes('--dry-run'); // B1-2：只打印过滤结果，不跑题不落报告（无网关亦可验）

// ── 取代性实验 B 系列（§10.2，proposal WHAT#4）：--challenger 挑战者臂模式 ──
// 判分走 challenger_check（no-verdict 纯文本：truth 六分制断言 + trap 纯正则 + expect_gap + 越界），
// 跳过轨迹读取/verdict 通道（result.verdict 恒 'none'）；覆盖率闸不适用；langfuse 不写（防污染 A0 dataset）；
// 报告落 eval/challenger-report.json（不覆写 eval-report.json），metadata.challenger=true + 抽检清单 audit。
// flag 缺省=默认路径逐字节等价（本文件所有新分支均以 CHALLENGER 为前置条件）。
const CHALLENGER = process.argv.includes('--challenger');
if (CHALLENGER && process.argv.includes('--gate')) { // 审查 P2：两模式互斥（gate 题集走出口闸断言，与 no-verdict 臂判分语义冲突）；用 argv 直判防 TDZ（GATE_MODE 定义在后）
  console.error('[challenger] --challenger 与 --gate 互斥——挑战者无出口闸通道，gate 题集不适用');
  process.exit(1);
}
const ARM_PURITY = []; // 审查 P1-1：臂纯度违规收集（挑战者工具面必须 ⊆ {run_sql, read_file}——
// 误指常规栈（如 8003）会静默产出"全 A 系行为"的挑战者报告，读数作废且不可机器分辨（v1.2 漏 env 事故同类）
const CHALLENGER_ARM = (process.env.PRISM_CHALLENGER_ARM || 'a').toLowerCase() === 'b' ? 'b' : 'a';
const CHALLENGER_SKILL = CHALLENGER_ARM === 'b' ? 'SKILL-B.md' : 'SKILL-A.md';
const CHALLENGER_PREFIX = `[实验指示·取代性实验 B1${CHALLENGER_ARM} 臂] 你没有语义分析工具，只有 run_sql（快照库只读 SQL）与 read_file 两个工具。开始前必须先 read_file("${CHALLENGER_SKILL}")（业务 SOP${CHALLENGER_ARM === 'b' ? '+完整数据口径手册' : ''}）与 read_file("schema.sql")（库结构），之后用 run_sql 查库作答。\n\n`;

// v1.2 重跑护栏（2026-10-26 归因）：runner 的 API 缺省=8002 生产栈——漏传 PRISM_API_BASE 曾把
// 整场批跑打上生产（数据面=生产库/轨迹写生产回退文件/判分读陈旧行→57 题假死，归因报告在案）。
// 非 dry-run 必须显式指定；--allow-prod-api 显式豁免留痕（仅限刻意打生产栈的对照实验）。
if (!DRY_RUN && !process.env.PRISM_API_BASE && !process.argv.includes('--allow-prod-api')) {
  console.error('[env-guard] 未设置 PRISM_API_BASE——缺省会打生产栈(8002)！批跑必须用 prism.py eval start 打印的完整命令起跑。');
  console.error('  正确形态：PRISM_API_BASE=http://127.0.0.1:8003 PRISM_TRAJECTORY_FILE="<eval轨迹文件>" node eval/runner.mjs');
  console.error('  确要打生产栈：加 --allow-prod-api（报告 env 字段留痕）');
  process.exit(1);
}
// 2026-10-29 dynamic 回灌（T-8.4 落地）：badcase 转来的题默认 set='dynamic'，
// 与 blind 同等待遇——--set=all 不包含，必须显式 --set=dynamic 单跑；
// 否则未定判据的题会混进主分母，把通过率稀释成假信号。
const ALL_TASKS = ([...TASKS, ...DYNAMIC_TASKS])
  .filter(t => (!ONLY_LIST || ONLY_LIST.some(p => t.id.startsWith(p))) && (SETS.includes('all') ? (t.set !== 'blind' && t.set !== 'dynamic' && t.set !== 'experiment') : SETS.includes(t.set)));

// M4（D8）：--gate 模式——出口闸评估门 E1-E9（独立题集，与 18 题基线并存）
const GATE_MODE = process.argv.includes('--gate');
const GATE_TASKS_FILE = resolve(process.cwd(), 'eval/tasks_gate.json');
let GATE_TASKS = [];
if (GATE_MODE) {
  GATE_TASKS = JSON.parse(readFileSync(GATE_TASKS_FILE, 'utf-8'));
}

// 评分（T-9.1 Gap5 修正：读 trajectories.jsonl 的 verdict 字段，验证器判定优先于正则）
// A5 轨迹分离：eval 网关注入 PRISM_TRAJECTORY_FILE 时读独立 eval 轨迹（与 extension 写入侧同 env）
const TRAJ_FILE = process.env.PRISM_TRAJECTORY_FILE
  ? resolve(process.env.PRISM_TRAJECTORY_FILE)
  : resolve(process.cwd(), '.pi/sessions/trajectories.jsonl');

// A3：run 代际（B1-5 报告元数据头沿用；PRISM_EVAL_RUN_ID 可覆盖）
const EVAL_RUN_ID = process.env.PRISM_EVAL_RUN_ID || 'eval-' + new Date().toISOString().replace(/[:.]/g, '-');

// ── D2 --repeat=k（同题 k 跑一致闸）；D3 并行锁；B2-4 per-题超时 ──
const REPEAT = (() => {
  const a = process.argv.find((x) => x.startsWith('--repeat='));
  const k = a ? parseInt(a.slice(9), 10) : 1;
  if (!Number.isInteger(k) || k < 1 || k > 10) {
    console.error('--repeat 取值非法（1-10 整数）');
    process.exit(1);
  }
  return k;
})();
const TASK_TIMEOUT_MS = 300_000; // B2-4：per-题 300s，超时 score=0 reason=timeout 不拖垮批跑

// ── 实验臂（2026-11-02 显著性实验）：唯一真源 = eval/.arm 文件，缺省 A ──
// 守卫扩展在 agent_settled 时读同一个文件 → 臂切换=写文件，不需要重启任何进程。
// 报告逐跑记录 arm，保证"这条分数属于哪个臂"可审计。
const ARM_FILE = resolve(ROOT, 'eval/.arm');
function currentArm() {
  try {
    const v = String(readFileSync(ARM_FILE, 'utf-8')).trim().toUpperCase();
    return v === 'B' ? 'B' : 'A';
  } catch { return 'A'; }
}

const LOCK_FILE = resolve(ROOT, 'eval/.runner.lock');
function acquireLock() {
  const STALE_MS = 30 * 60 * 1000; // M3：stale>30min 可清
  if (existsSync(LOCK_FILE)) {
    let info = null;
    try { info = JSON.parse(readFileSync(LOCK_FILE, 'utf-8')); } catch {}
    const age = info?.ts ? Date.now() - info.ts : Infinity;
    let pidAlive = false;
    if (Number.isInteger(info?.pid)) {
      try { process.kill(info.pid, 0); pidAlive = true; } catch (e) { pidAlive = e.code === 'EPERM'; }
    }
    if (pidAlive && age < STALE_MS) { // P1-3（Step7）：PID 已死不判占用（Ctrl+C 后可立即重跑）；心跳由任务循环 touch 维持 ts 新鲜
      console.error(`[lock] eval/.runner.lock 被占用（pid=${info?.pid}，${Math.round(age / 1000)}s 前启动）——另一 runner 在跑；stale>30min 自动可清。退出。`);
      process.exit(1);
    }
    console.warn(`[lock] 清理 stale 锁（pid=${info?.pid}，age=${Math.round(age / 1000)}s）`);
    try { unlinkSync(LOCK_FILE); } catch {}
  }
  _wf(LOCK_FILE, JSON.stringify({ pid: process.pid, ts: Date.now(), started_at: new Date().toISOString() }) + '\n');
}
function releaseLock() { try { unlinkSync(LOCK_FILE); } catch {} }

// ── B2-2/B2-3 web 可用性探测（off 缺省不可用；live=明示；fixture=目录存在）──
const WEB_FIXTURE_DIR = resolve(ROOT, process.env.PRISM_WEB_FIXTURE_DIR || 'eval/fixtures/web');
function probeWeb() {
  const mode = (process.env.PRISM_EVAL_WEB || 'off').toLowerCase();
  if (mode === 'live') return { mode, ok: true };
  if (mode === 'fixture') {
    let ok = false;
    try { ok = readdirSync(WEB_FIXTURE_DIR).length > 0; } catch {}
    return { mode, ok };
  }
  return { mode: mode === 'off' ? 'off' : `off(未知值${mode}按off)`, ok: false };
}

// ── B2-5 成本台账：session jsonl 的 assistant message.usage（已实证含 token 事件）──
function extractCost(userId, sessionId, t0, toolCalls) {
  const duration_s = Number(((Date.now() - t0) / 1000).toFixed(1));
  const base = { duration_s, tool_calls: toolCalls, tokens: null, partial: true, note: 'session jsonl 无 usage 事件 → duration 兜底' };
  try {
    const dir = resolve(process.cwd(), '.pi/sessions', userId);
    const files = readdirSync(dir).filter((f) => f.endsWith('.jsonl'));
    let file = sessionId ? files.find((f) => f.endsWith('_' + sessionId + '.jsonl')) : null;
    if (!file) {
      file = files.map((x) => ({ x, m: statSync(resolve(dir, x)).mtimeMs })).sort((a, b) => b.m - a.m)[0]?.x;
    }
    if (!file) return base;
    let input = 0, output = 0, cacheRead = 0, total = 0, cost = 0, n = 0;
    for (const line of readFileSync(resolve(dir, file), 'utf-8').split('\n')) {
      try {
        const o = JSON.parse(line);
        if (o.type === 'message' && o.message?.role === 'assistant' && o.message?.usage) {
          const u = o.message.usage;
          input += u.input || 0; output += u.output || 0; cacheRead += u.cacheRead || 0;
          total += u.totalTokens || 0; cost += u.cost?.total || 0; n++;
        }
      } catch {}
    }
    if (!n) return base;
    return { duration_s, tool_calls: toolCalls, tokens: { input, output, cacheRead, totalTokens: total, cost_usd: Number(cost.toFixed(6)) }, partial: false };
  } catch { return base; }
}

// ── B1-3/B1-4 金标数字比对规则（外置 eval/scoring-rules.json，首跑后校准只改规则文件）──
let SCORING_RULES = DEFAULT_RULES;
try {
  SCORING_RULES = { ...DEFAULT_RULES, ...JSON.parse(readFileSync(resolve(ROOT, 'eval/scoring-rules.json'), 'utf-8')) };
} catch (e) {
  console.warn(`[warn] scoring-rules.json 读取失败（${e.message}），truth 比对用内置缺省规则`);
}

// ── B1-5 报告元数据头（M2）──
const RUNNER_VERSION = '2.1.0-b2';
const STARTED_AT = new Date().toISOString();
function gitHead() {
  try { return execSync('git rev-parse HEAD', { cwd: ROOT, encoding: 'utf-8' }).trim(); } catch { return null; }
}
const TASKS_GIT_HASH = gitHead();
const AGENT_RELEASE = (() => {
  try { return JSON.parse(readFileSync(resolve(ROOT, 'package.json'), 'utf-8')).version || null; } catch { return null; }
})();
const SNAPSHOT_IDS = [...new Set(ALL_TASKS.map(t => t.snapshot_id).filter(s => s && s !== 'any'))];

// P1-2 快照漂移闸（Step8 补实装 design §8 承诺）：多轮题锚点绑定快照，轮换后静默失效即拒跑。
// 真源=eval/snapshots/ACTIVE_SNAPSHOT.txt（prism.py eval start 写入）；--allow-snapshot-drift 显式放行留痕。
const ALLOW_SNAPSHOT_DRIFT = process.argv.includes('--allow-snapshot-drift');
const ACTIVE_SNAPSHOT = (() => {
  try { return readFileSync(resolve(ROOT, 'eval/snapshots/ACTIVE_SNAPSHOT.txt'), 'utf-8').trim() || null; } catch { return null; }
})();
const DRIFT = checkSnapshotDrift(ALL_TASKS, ACTIVE_SNAPSHOT);
if (!DRIFT.ok && !ALLOW_SNAPSHOT_DRIFT) {
  console.error(`[snapshot-drift] 拒跑：${DRIFT.note}${DRIFT.mismatches.length ? `（${DRIFT.mismatches.join(',')}）` : ''}`);
  console.error('  处置：python prism.py eval start <snap> 重挂正确快照；确要跑加 --allow-snapshot-drift（报告留痕）');
  process.exit(1);
} else if (!DRIFT.ok) {
  console.warn(`[snapshot-drift] 已放行（--allow-snapshot-drift）：${DRIFT.note}`);
}
// 补审 P1：放行审计字段——进报告与 manifest，放行跑与干净跑在审计件上可区分（此前只 console.warn 一闪即逝）
const SNAPSHOT_DRIFT_AUDIT = DRIFT.ok ? null : {
  note: DRIFT.note, mismatches: DRIFT.mismatches,
  allowed_by: ALLOW_SNAPSHOT_DRIFT ? '--allow-snapshot-drift' : null,
  active_snapshot: ACTIVE_SNAPSHOT,
};

// P0 链路：langfuse 写入延后到覆盖率闸之后（本轮无效则不写，避免脏数据再次堆积）
const PENDING_SCORES = [];

function readLastTrajectory(userId, sid = null, taskId = null, repeat = null) {
  try {
    const lines = readFileSync(TRAJ_FILE, 'utf-8').trim().split('\n').filter(Boolean);
    const entries = [];
    for (const line of lines) {
      try { entries.push(JSON.parse(line)); } catch { /* 坏行跳过，不拖垮取行 */ }
    }
    // P0 链路焊死（2026-10-26）：runId+taskId(+repeat) 优先（sessionId 断供不再影响判分；
    // 登录门会把 user_id 覆盖成 token 用户名，题级 userId 不可保真，故不作硬条件）。
    return pickTrajectory(entries, { userId, sid, runId: EVAL_RUN_ID, taskId, repeat });
  } catch { return null; }
}

function scoreTask(task, reply, tools, settled, trajVerdict, turnReplies = null) {
  const base = scoreTaskBase(task, reply, tools, settled, trajVerdict, turnReplies);
  // B3 金标数字比对（判分前置归一化比对）：任一 anchor 缺失或 forbid 命中 → 封顶 2（数字错误 > 缺证据）；
  // 全部命中不降档。无 truth 的题不比对。机制/规则契约见 truth_check.mjs / scoring-rules.json。
  const truth = checkTruth(task, reply, SCORING_RULES);
  if (truth.checked) {
    if (truth.missing.length) {
      base.score = Math.min(base.score, 2);
      base.reasons.push(`truth 缺锚: ${truth.missing.join('、')}`);
    }
    if (truth.forbidHits.length) {
      base.score = Math.min(base.score, 2);
      base.reasons.push(`truth forbid 命中: ${truth.forbidHits.join('、')}`);
    }
    if (!truth.missing.length && !truth.forbidHits.length) base.reasons.push(`truth 锚点全中(${truth.anchorsCount})`);
    base.truth = truth;
  }
  // B2-1 中间档判分（rubric_params 题级声明：排序/缺口/舆情范式/artifact 插槽）
  const rub = checkRubric(task, reply);
  if (rub.checked) {
    base.rubric = rub;
    if (rub.cap != null && rub.cap < base.score) {
      base.score = rub.cap;
      const detail = rub.forbidHits?.length
        ? `命中禁项: ${rub.forbidHits.join('、')}`
        : `缺要素: ${rub.missing.join('、') || rub.note || ''}`;
      base.reasons.push(`rubric[${rub.kind}] ${detail}`);
    } else if (rub.pass) {
      base.reasons.push(`rubric[${rub.kind}] 全要素命中`);
    }
  }
  return base;
}

function scoreTaskBase(task, reply, tools, settled, trajVerdict, turnReplies = null) {
  let score = 5;
  const reasons = [];

  // 验证器判定优先（T-9.1：从 trajectories.jsonl 读 verdict）
  if (trajVerdict) {
    if (trajVerdict.verdict === 'fail') {
      reasons.push(`验证器否决: ${trajVerdict.verdict_reason || '未知'}`);
      // trap 题验证器否决=正确拦截；非 trap 题否决=扣分
      if (!task.trap_type) {
        score = 1;
      }
    } else if (trajVerdict.verdict === 'pass' && trajVerdict.evidence_ids?.length > 0) {
      reasons.push('验证器通过（行ID查库+越界+缺口+名称）');
    }
  }

  // trap 检查（P0-#29：判定逻辑抽出 eval/trap_check.mjs——verdict fail 首要 + 方向化正则兜底，
  // 正反例契约见 trap_check.test.mjs；改规则先改测试）
  if (task.trap_type) {
    const blocked = trapBlocked(task, reply, tools, trajVerdict?.verdict === 'fail', task.trap_type === 'no_evidence' && trajVerdict?.verdict === 'pass', turnReplies); // v1 校准：no_evidence 闸 pass=证据已验；turnReplies=多轮新类（yield/bleed/residue）逐轮回复
    if (blocked) {
      return { score: 5, reasons: [`trap ${task.trap_type} 被拦截（${trajVerdict?.verdict === 'fail' ? '验证器' : '正则'}）`] };
    }
    return { score: 0, reasons: [`trap ${task.trap_type} 未被拦截`] };
  }

  // 非 trap 题：验证器 pass 时仍查证据完整性（兜底）
  if (!trajVerdict || trajVerdict.verdict !== 'fail') {
    // 社媒题（web tier）：证据判据=URL 溯源 + 抓取时间/不可复算声明（非库行 ID）
    const isSocialTask = task.dimension === '社媒' || /social/i.test(task.expected_evidence || '');
    if (isSocialTask) {
      const hasUrl = /https?:\/\//.test(reply);
      const hasStamp = /as_of|抓取时间|不可复算/i.test(reply);
      if (!hasUrl) { score = Math.min(score, 2); reasons.push('社媒题缺 URL 溯源'); }
      if (!hasStamp) { score = Math.min(score, 2); reasons.push('社媒题缺抓取时间/不可复算声明'); }
    } else {
      const hasEvidence = /review_tags|sales_trim|config_snapshots|mv_|supported_by/i.test(reply);
      const hasAsOf = /as_of|2026-10|数据时点/i.test(reply);
      // P1-4（Step7）：出口闸架构下证据行 ID 在 CLAIM/轨迹，回复正文不复述字面量——
      // verdict=pass 且带 evidence_ids 时豁免正文正则封顶（正则仅无 verdict 时兜底，符合 T-9.1"验证器优先"）
      const verdictPassed = trajVerdict?.verdict === 'pass'; // v1 校准：闸 pass 即豁免——定性结论 CLAIM 合法无 supported_by（evidence_ids 空但 pass 是正确行为）
      if (!hasEvidence && !verdictPassed) { score = Math.min(score, 2); reasons.push('缺 supported_by 证据行 ID'); }
      if (!hasAsOf && !verdictPassed) { score = Math.min(score, 2); reasons.push('缺 as_of 声明'); }
    }

    // 越界检查（块1.5 豁免；G-2 2026-10-27 单源化：正则+NEG_RE 豁免同体 = trap_check.checkOverreach
    // 纯函数——rescore 越界分支同调，判分逻辑不再双源；免责形态扩词见 trap_check NEG_RE 注释）
    if (checkOverreach(reply)) {
      score = 1; reasons.push('市场侧归因产品力（越界）');
    }

    // 数据缺口检查
    if (task.id === 'cross-08' && !/假设|不可得|缺口|证据强度/.test(reply)) {
      score = Math.min(score, 2); reasons.push('区域数据不可得却未走假设范式');
    }
  }

  return { score, reasons };
}

// 单轮 POST /chat/stream（B2-7 多轮复用；含 E2 keep-alive 复用竞态重试 1 次——同 runGateStep）
// settled 事件自带验证器 verdict（mapEvent 读 verdict.json）——逐轮 verdict 首要来源（G6）
// 多轮评估批 T3：ui_request 事件透传——EVAL_UI_SIM 网关不抢答，runner 按题级 ui_strategy 模拟应答
async function streamChat({ userId, sessionId, message, seriesKey = '', signal, onUiRequest, evalTaskId = '', evalRepeat = 1 }) {
  const body = JSON.stringify({
    message,
    user_id: userId,
    scope: 'agent',
    session_id: sessionId || undefined,
    series_key: seriesKey,
    // P0 链路焊死：批次+题级+第几跑随请求进 ctx.json → extension 逐行落轨迹
    eval_run_id: EVAL_RUN_ID,
    eval_task_id: evalTaskId,
    eval_repeat: evalRepeat,
  });
  let res;
  for (let attempt = 1; ; attempt++) {
    try {
      res = await fetch(`${GATEWAY}/chat/stream`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body, signal,
      });
      break;
    } catch (e) {
      if (attempt >= 2 || signal?.aborted) throw e;
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  const texts = [], tools = [], uiRequests = [];
  let settled = false, error = null, sid = sessionId || null, verdict = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop() || '';
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const e = JSON.parse(line);
        if (e.type === 'text_delta' && e.data?.text) texts.push(e.data.text);
        else if (e.type === 'tool_call') tools.push(e.data?.name || '?');
        else if (e.type === 'settled') { settled = true; if (e.verdict?.verdict) verdict = e.verdict; }
        else if (e.type === 'session_info' && e.data?.session_id) sid = e.data.session_id;
        else if (e.type === 'ui_request') {
          uiRequests.push(e.data);
          try { onUiRequest?.(e.data); } catch {} // 模拟应答失败不吞流（300s 任务帽兜底）
        }
        else if (e.type === 'error') error = e.data?.message;
      } catch {}
    }
  }
  return { reply: texts.join(''), tools, settled, error, sessionId: sid, verdict, uiRequests };
}

// 每题开新会话（2026-10-20 动态测试实锤修复）：登录门后 server 端身份=token
// （resolve_user_id 防冒用覆盖 body user_id），同批全部题落到同一 eval 用户 →
// 网关 continueRecent 共享一个会话，跨题上下文串味（实锤：skill-03 复用 skill-01
// 的扫描数据、整批单 sessionId）。修=每题首轮前显式 POST /session 开新会话，
// session_id 走既有 session_info 事件通道穿线（与多轮题同机制）；失败仅告警回落。
async function ensureFreshSession(userId) {
  try {
    const r = await fetch(`${GATEWAY}/session`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ user_id: userId }), signal: AbortSignal.timeout(10_000),
    });
    return r.ok;
  } catch { return false; }
}

// ── P3 余额/鉴权预检（2026-11-02 预注册）：一次最小请求，402/401 立即中止 ──
// 背景：2026-11-02 全量批跑 147/189 行为 402 空回复，报告仍自称 run_valid=true。
// 只对"余额/鉴权"类失败中止；其它异常仅告警（避免把偶发空回复当环境故障）。
async function preflight() {
  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(new Error('preflight timeout')), 90_000);
  try {
    await ensureFreshSession('eval_preflight');
    const r = await streamChat({
      userId: 'eval_preflight', sessionId: null, message: '你好', seriesKey: '',
      signal: ac.signal, onUiRequest: async () => {}, evalTaskId: 'preflight', evalRepeat: 1,
    });
    const msg = String(r.error || '');
    if (/402|401|Insufficient|insufficient|余额|Unauthorized/i.test(msg)) return { ok: false, fatal: true, reason: msg };
    if (!r.settled) return { ok: false, fatal: false, reason: msg || '未 settled' };
    return { ok: true, fatal: false, reason: '' };
  } catch (e) {
    return { ok: false, fatal: false, reason: String(e?.message || e) };
  } finally {
    clearTimeout(timer);
  }
}

// 模型名（仅报告留痕，供"同模型"事后审计）：网关 /status；eval 栈 api:8003 → gateway:9201
async function probeModel() {
  if (process.env.PRISM_MODEL) return process.env.PRISM_MODEL;
  const bases = [];
  try { const u = new URL(GATEWAY); u.port = String(Number(u.port) + 1198); bases.push(u.origin); } catch {}
  bases.push('http://127.0.0.1:9201');
  for (const b of [...new Set(bases)]) {
    try {
      const st = await fetch(`${b}/status`, { headers: authHeaders(), signal: AbortSignal.timeout(3000) }).then((r) => r.json());
      if (st?.model) return st.model;
    } catch {}
  }
  // 兜底（2026-11-02 A 轮实测 /status 取不到）：读网关启动日志的最后一条 model=
  for (const f of ['logs/gateway-eval.log', 'logs/gateway.log']) {
    try {
      const txt = readFileSync(resolve(ROOT, f), 'utf-8');
      const hits = [...txt.matchAll(/model=([A-Za-z0-9._\-]+)/g)];
      if (hits.length) return hits[hits.length - 1][1];
    } catch {}
  }
  return null;
}

// 跑一道题（B2-7 多轮：turns=[{message,truth?}] 依序 POST，session_id 穿线复用；
// 判分=终轮 verdict+scoreTask + 逐轮 truth 锚点（B3 同规则）；B2-4 整题 300s 超时）
async function runTask(task, repeatIdx = 1) {
  const t0 = Date.now();
  const userId = `eval_${task.id}` + ((REPEAT > 1 || repeatIdx > 1) ? `_r${repeatIdx}` : ''); // --repeat 各跑独立会话防上下文串味
  const turns = Array.isArray(task.turns) && task.turns.length
    ? task.turns
    : [{ message: task.question, truth: task.truth }];

  const ac = new AbortController();
  const timer = setTimeout(() => ac.abort(new Error('timeout')), TASK_TIMEOUT_MS);
  let turnResults = [];
  let sid = null;            // 会话 id 穿线（函数级作用域：终轮判分/轨迹取行都要用，不能只在 try 内）
  const resolvedTurns = [];  // 多轮评估批：每轮实际生效的 turn 规格（分支解析后；单轮=原样）
  const turnTruthLog = [];   // 多轮评估批：逐轮 truth 即时结果（branch_on 分支判定输入；{turn,ok}）
  const uiLog = [];          // 多轮评估批 T3：模拟应答留痕（判"问了没/答了啥"素材）

  // 多轮评估批 T3：ui_request 模拟应答——题级 ui_strategy 匹配（match 正则对 title+message）按策略应答，
  // 否则默认代答（select→first / confirm→true / input→''，与旧 AUTO_APPROVE 行为等价）；
  // select:'none' = cancelled:true（模拟"用户不点名"路径，skill-03 判分语义重审用）。
  // 兜底：POST 失败重试 1 次；handler 异常不吞流（300s 任务帽兜底）——pi 已带 --approve，permission 弹窗不到达本层。
  const respondUi = async (ui) => {
    const strat = task.ui_strategy;
    const hay = `${ui.title || ''} ${ui.message || ''}`;
    const matched = Boolean(strat && (!strat.match || new RegExp(strat.match).test(hay)));
    let value, cancelled = false;
    if (matched) {
      if (ui.method === 'select') {
        if (strat.select === 'none') { cancelled = true; value = null; }
        else if (strat.select === 'first' || strat.select == null) value = (ui.options || [])[0];
        else value = strat.select;
      } else if (ui.method === 'confirm') value = strat.confirm !== false;
      else value = strat.input ?? '';
    } else {
      value = ui.method === 'select' ? (ui.options || [])[0] : ui.method === 'confirm' ? true : '';
    }
    uiLog.push({ turn: turnResults.length + 1, method: ui.method, title: (ui.title || '').slice(0, 40), value: value === undefined ? null : value, cancelled, matched });
    for (let attempt = 1; attempt <= 2; attempt++) {
      try {
        await fetch(`${GATEWAY}/ui-response`, {
          method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() },
          // user_id 必须=登录身份（AUTH_USER）：api 层 resolve_user_id 把 /chat 的 user_id
          // 覆盖成 token 用户名 → 网关 RPC 池键控在该身份下；用题级 eval_<task> 会 404
          // no active session（multi-05/11 冒烟实证：404→每弹窗挂 30s 兜底→长题超时）
          body: JSON.stringify({ id: ui.id, value, cancelled, user_id: AUTH_USER || userId }),
          signal: AbortSignal.timeout(10_000),
        });
        return;
      } catch (e) {
        if (attempt >= 2) console.warn(`[ui] /ui-response 失败（${task.id}）: ${e.message}`);
      }
    }
  };

  try {
    // P1 隔离 fail-closed（2026-10-29）：会话创建失败不再静默回落到上一题的 recent session——
    // 回落会跨题串味，且污染分照样进分母（旧实现只 warn）。重试仍失败 → 本题标 invalid，不进任何分母。
    // 2026-11-01 实测补充：网关 pi 池有"idle 清理→重启"的数秒窗口，此时 POST /session 会 500；
    // 原实现两次重试之间零间隔，会连着撞同一窗口（7 题批里出现 invalid 的根因）。
    // 改为 3 次重试 + 递增间隔（3s/8s），fail-closed 语义不变。
    if (!(await ensureFreshSession(userId))) {
      await new Promise((r) => setTimeout(r, 3000));
      if (!(await ensureFreshSession(userId))) {
        await new Promise((r) => setTimeout(r, 8000));
        if (!(await ensureFreshSession(userId))) {
          clearTimeout(timer);
          return {
            task: task.id, dimension: task.dimension, repeat: repeatIdx,
            score: 0, valid: false, invalid_reason: 'session_create_failed',
            reasons: ['会话创建失败（重试 3 次）——本题未执行，不计分母'],
            settled: false, tools: [], truth: null,
          };
        }
      }
    }
    for (let ti = 0; ti < turns.length; ti++) {
      // 多轮评估批机制①：branch_on 条件分支（依据引用轮逐轮 truth 选 if_hit/else——τ²-bench known_info 规则版）
      let turn = turns[ti];
      let branchTaken;
      if (turn && turn.branch_on) {
        const sel = selectBranch(turn, turnTruthLog);
        turn = sel.turn; branchTaken = sel.branch;
      }
      // 多轮评估批：new_session 轮（multi-09/10 回访题）——该轮前显式开新会话并弃 sid（跨会话不串味由"必须重查"测）
      if (turn && turn.new_session) {
        // P1 隔离 fail-closed：回访轮新会话建不起来就不能"继续用当前会话"（跨会话不串味正是该轮考点）
        if (!(await ensureFreshSession(userId))) {
          if (!(await ensureFreshSession(userId))) {
            clearTimeout(timer);
            return {
              task: task.id, dimension: task.dimension, repeat: repeatIdx,
              score: 0, valid: false, invalid_reason: 'session_create_failed',
              reasons: [`回访轮 t${ti + 1} 新会话创建失败（重试 2 次）——本题未执行，不计分母`],
              settled: false, tools: [], truth: null,
            };
          }
        }
        sid = null;
      }
      // 多轮评估批机制②：variants 话术池轮换（REPEAT=k → [(k-1)%n]；string=旧格式直传零影响）
      // 取代性实验 B 系列：--challenger 首轮消息前缀带 SKILL 路径指示（proposal WHAT#4；仅挑战者路径）
      let msg = resolveMessage(turn ? turn.message : turns[ti].message, repeatIdx);
      if (CHALLENGER && ti === 0) msg = CHALLENGER_PREFIX + msg;
      const r = await streamChat({ userId, sessionId: sid, message: msg, seriesKey: task.series_key || '', signal: ac.signal, onUiRequest: respondUi, evalTaskId: task.id, evalRepeat: repeatIdx });
      sid = r.sessionId || sid;
      turnResults.push({ ...r, sentMessage: msg, branchTaken });
      resolvedTurns.push(turn || turns[ti]);
      // 多轮评估批：逐轮 truth 内联即时判（branch 分支需要前轮结果；末轮不入 perTurnTruth——保持既有报告形态）
      if (turn && turn.truth) {
        const tr = checkTruth({ id: `${task.id}#t${ti + 1}`, truth: turn.truth }, r.reply, SCORING_RULES);
        if (tr.checked) turnTruthLog.push({ turn: ti + 1, ok: !(tr.missing.length || tr.forbidHits.length), tr });
      }
      // T6 取消题机制：abort_after_turn=N → 第 N 轮回复后调 /chat/abort 中止在途；后续轮同 session 继续（恢复场景预留）。
      // 仅 task.abort_after_turn 显式设置时触发——既有 60 题零影响
      if (task.abort_after_turn === ti + 1) {
        try {
          const ar = await fetch(`${GATEWAY}/chat/abort`, {
            method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() },
            // user_id=登录身份（同 ui-response：网关按 token 身份池键控，题级 id 会 404）
            body: JSON.stringify({ user_id: AUTH_USER || userId }), signal: AbortSignal.timeout(10_000),
          });
          turnResults[turnResults.length - 1] = { ...turnResults[turnResults.length - 1], abortedAfter: ti + 1, abortOk: ar.ok };
        } catch {} // abort 通道失败仅静默注记，不改变判分路径
      }
    }
  } catch (e) {
    clearTimeout(timer);
    const isTimeout = ac.signal.aborted || String(e?.message || e) === 'timeout';
    if (isTimeout) {
      return {
        task: task.id, dimension: task.dimension, repeat: repeatIdx,
        score: 0, reasons: ['timeout'], error: `timeout: ${TASK_TIMEOUT_MS / 1000}s 超时（已中止上游流）`,
        settled: false, tools: [], cost: extractCost(userId, null, t0, 0),
      };
    }
    return { task: task.id, dimension: task.dimension, repeat: repeatIdx, score: 0, reasons: [String(e?.message || e)], error: String(e?.message || e), settled: false, tools: [] };
  }
  clearTimeout(timer);

  const last = turnResults[turnResults.length - 1];
  const reply = last.reply;
  const allTools = turnResults.flatMap((r) => r.tools);
  // 审查 P1-1：臂纯度 fail-closed——挑战者批里出现任何布防外工具=指向了错栈，记录并最终判无效
  // 白名单含 pi 内建 ask_user_question（通用 agent 形态自带问询，A 系同样可用——非 guardrails 污染；
  // B1a 实跑误报 2 题坐实：真正的污染=resolve_series/query_* 等语义工具）
  const CHALLENGER_TOOL_OK = new Set(['run_sql', 'read_file', 'ask_user_question']);
  if (CHALLENGER && allTools.some((t) => !CHALLENGER_TOOL_OK.has(t))) {
    ARM_PURITY.push({ task: task.id, repeat: repeatIdx, tools: [...new Set(allTools)] });
  }
  // T-9.1：读 trajectories.jsonl 本会话 verdict（验证器判定，含 evidence_ids）——P0：runId+taskId 优先
  // 取代性实验 B 系列：挑战者无 extension 写轨迹 → 跳过轨迹读取/verdict 通道（trajVerdict 恒 null）
  const traj = CHALLENGER ? null : readLastTrajectory(userId, sid, task.id, repeatIdx);
  const trajVerdict = traj ? { verdict: traj.verdict, verdict_reason: traj.verdict_reason, evidence_ids: traj.evidence_ids } : null;
  // 终轮 truth：末轮自带 truth 优先（多轮评估批：分支解析后的实际末轮），退回题级 truth
  const finalTask = { ...task, truth: resolvedTurns[resolvedTurns.length - 1]?.truth ?? task.truth };
  // 取代性实验 B 系列：判分走 challenger_check（no-verdict 纯文本，verdict 恒 none）
  const { score, reasons, truth, rubric } = CHALLENGER
    ? challengerScore(finalTask, reply, allTools, turnResults.map((r) => r.reply), SCORING_RULES)
    : scoreTask(finalTask, reply, allTools, last.settled, trajVerdict, turnResults.map((r) => r.reply));

  // 逐轮 truth（B3 同规则逐轮；终轮已并入 scoreTask，前 n-1 轮从内联判读消费——分支题用解析后的轮规格）
  const perTurnTruth = [];
  for (const entry of turnTruthLog) {
    if (entry.turn >= turnResults.length) continue; // 末轮已并入 scoreTask（含 abort 轮后重启的行对齐保护）
    perTurnTruth.push({ turn: entry.turn, missing: entry.tr.missing, forbidHits: entry.tr.forbidHits });
    if (entry.tr.missing.length || entry.tr.forbidHits.length) {
      reasons.push(`truth[t${entry.turn}] 缺锚/违禁: ${[...entry.tr.missing, ...entry.tr.forbidHits].join('、')}`);
    }
  }
  // 逐轮违规封顶同 B3（数字错误 > 缺证据）
  let finalScore = score;
  if (perTurnTruth.some((t) => t.missing.length || t.forbidHits.length)) finalScore = Math.min(finalScore, 2);

  // 多轮评估批机制③：穿线验证（题级 carry_anchor；轮级 turns[].carry_anchor 后声明优先）——
  // 同值复现=consistent / 近值不同=drift（±2% 窗，4436→4437 式轮间漂移）/ 不复现=silent 不算错
  const carrySpec = task.carry_anchor || turns.map((t) => t && t.carry_anchor).filter(Boolean).pop() || null;
  const carry = carryCheck(carrySpec, turnResults.map((r) => r.reply || ''));
  if (carry && carry.hasDrift) {
    finalScore = Math.min(finalScore, 2);
    for (const d of carry.results.filter((x) => x.status === 'drift')) {
      reasons.push(`轮间漂移: t${carry.from}=${d.key}→t${d.turn}=${d.found}`);
    }
  }

  // 判分账本（2026-10-29）：把"从 5 分掉到几分、被哪条判据封顶"逐条记成结构化步骤（放在
  // 所有封顶逻辑之后，reasons 才是完整的）。非 trap/非挑战者题才记（trap 是 0/5 二值语义）。
  // consistent=false = 规则表复算分与官方分不一致——不阻断判分，报告可查，用于抓规则表漂移。
  let deductionTrace = null;
  if (!CHALLENGER && !task.trap_type) {
    const d = deductionFromReasons(reasons, task, reply);
    deductionTrace = { base: d.base, computed: d.score, consistent: d.score === finalScore, steps: d.steps };
  }

  // A3：评分写回 langfuse（score 挂插件 traceId；失败仅 warn 不阻塞判分——观测降级）
  // P0：先入队，覆盖率闸通过后统一 flush（无效轮不写 Langfuse）
  // 取代性实验 B 系列：挑战者臂不入队——分数写 A0 的 dataset/run 会污染基线观测（报告/audit 件承担留痕）
  if (!CHALLENGER) PENDING_SCORES.push({
    eval_run_id: EVAL_RUN_ID,
    task_id: task.id,
    repeat: repeatIdx,
    score: finalScore,
    failure_dimensions: reasons,
    cost: { input_tokens: 0, output_tokens: 0, cache_hit: 0, elapsed_ms: Date.now() - t0 }, // B2-5 台账见 result.cost（此处保持 A3 兼容形态）
    trap_blocked: Boolean(task.trap_type) && finalScore === 5,
    name_grounding_triggered: false, // runner 侧不可观测，extension 层事件（默认 false）
    scope_overreach_blocked: reasons.some((r) => r.includes('越界')),
    sessionId: last.sessionId || traj?.sessionId, // F-D 同源修复：traj=null 时 sessionId 曾断供（writer"未提供"根因）
    set: task.set,
    snapshot_id: task.snapshot_id,
    judge_rubric: (task.judge_rubric || '').slice(0, 600), // 分数细则随 score 入 langfuse（单界面闭环）
    // 归因工具包（2026-10-16）：判分明细随 score 入 langfuse
    truth_missing: truth?.missing ?? [],
    truth_forbid_hits: truth?.forbidHits ?? [],
    rubric_missing: rubric?.missing ?? [],
    first_error_turn: firstErrorTurn({ score: finalScore, reasons, perTurnTruth, turnVerdicts: turnResults.map((r) => r.verdict?.verdict ?? null) }),
  });

  // 多轮评估批 T4：per-task traceId 补存（CH 按 sessionId 查最新 trace——OTLP 导出延迟由 writer 短重试兜）；
  // fail-soft：查不到/null（深度绑定 linkRun 按既有语义跳过计数），不阻塞判分
  let traceId = null;
  if (!CHALLENGER) try { traceId = await lookupTraceId(last.sessionId || traj?.sessionId || undefined); } catch {}

  const cost = extractCost(userId, last.sessionId || traj?.sessionId, t0, allTools.length);

  // C1b（2026-11-02）：判分出口硬闸——空回复 / 未 settled / 无工具（闲聊类豁免）一律无效，
  // 不产生分数、不进任何分母；此前 149/189 空回复仍被判 pass 并给 5 分。
  const _noToolOk = /闲聊|复述|能力说明|拒答/.test(String(trajVerdict?.verdict_reason || ''));
  const _invalidReason = !String(reply || '').trim() ? 'empty_reply'
    : (!last.settled ? 'not_settled'
      : ((allTools.length === 0 && !_noToolOk) ? 'no_tools' : null));
  if (_invalidReason) {
    return {
      task: task.id,
      sessionId: sid || traj?.sessionId || null,
      dimension: task.dimension,
      question: (turns[0].message || '').slice(0, 40),
      repeat: repeatIdx,
      arm: CHALLENGER ? undefined : currentArm(),
      score: null,
      reasons: [`invalid: ${_invalidReason}`],
      settled: last.settled,
      trajFound: CHALLENGER ? undefined : Boolean(traj),
      verdict: CHALLENGER ? 'none' : (trajVerdict?.verdict ?? last.verdict?.verdict ?? null),
      tools: allTools.slice(0, 30),
      turnReplies: turnResults.map((r) => r.reply || ''),
      replyLength: reply.length,
      replyPreview: reply.slice(0, 100),
      reply_full: reply,
      error: turnResults.map((r) => r.error).filter(Boolean)[0] || null,
      valid: false,
      invalid_reason: _invalidReason,
      cost,
    };
  }

  return {
    task: task.id,
    sessionId: sid || traj?.sessionId || null, // F-A：落库 result 带 sessionId（审计/离线重判的对齐键）
    dimension: task.dimension,
    question: (turns[0].message || '').slice(0, 40),
    repeat: repeatIdx,
    arm: CHALLENGER ? undefined : currentArm(), // 2026-11-02 实验：本次跑次所属臂（A=守卫关 / B=守卫开）
    score: finalScore,
    reasons,
    truth, // B3：无 truth 的题为 undefined（JSON 序列化时省略）
    rubric, // B2-1：无 rubric_params 的题为 undefined
    deduction_trace: deductionTrace || undefined, // 判分账本（2026-10-29）：扣分步骤 {base,computed,consistent,steps[]}；trap/挑战者题省略
    perTurnTruth, // B2-7：多轮题逐轮 truth 结果（单轮题为 []）
    turnVerdicts: turnResults.map((r) => r.verdict?.verdict ?? null), // G6：逐轮 verdict（settled 事件首要）
    abortedTurn: turnResults.find((r) => r.abortedAfter)?.abortedAfter, // T6：取消题实中止轮（未设题 undefined→JSON 序列化省略）
    traceId, // 多轮评估批 T4：深度绑定 run 链接激活（null=CH 不可达降级）
    carry: carry || undefined, // 多轮评估批机制③：穿线结果（Sheet4 实值源；未设锚题省略）
    ui: uiLog.length ? uiLog : undefined, // 多轮评估批 T3：模拟应答留痕（无问询题省略）
    turnMessages: turnResults.some((r) => r.sentMessage) ? turnResults.map((r) => (r.sentMessage || '').slice(0, 80)) : undefined, // 话术池实际用词（归因可追溯变体）
    // 2026-11-02 可复现性补账：逐轮回复全文落报告。此前只落末轮 reply_full，perTurnTruth/carry
    // 的触发句无法离线重放（multi-01 漂移、multi-08 违禁两例均无法复现），归因只能靠猜。
    turnReplies: turnResults.map((r) => r.reply || ''), // 单轮题=1 项；多轮题=逐轮（与 turnResults 对齐）
    tools: allTools.slice(0, 30), // 2026-10-28：5→30——slice(0,5) 截断曾误导 multi-07 定性（"仅 resolve 系"实为前 5 假象，轨迹 toolCalls 全量 18 个）；30 覆盖实际链长上限
    settled: last.settled,
    trajFound: CHALLENGER ? undefined : Boolean(traj), // P0 覆盖率闸：settled 题是否取到轨迹行（判分可信度的前提）；挑战者无轨迹通道（undefined→序列化省略）
    verdict: CHALLENGER ? 'none' : (trajVerdict?.verdict ?? last.verdict?.verdict ?? null), // 挑战者 verdict 恒 none（§10.2 公平性规则3）
    error: turnResults.map((r) => r.error).filter(Boolean)[0] || null,
    cost, // B2-5：{tokens?, duration_s, tool_calls, partial}
    replyLength: reply.length,
    replyPreview: reply.slice(0, 100),
    reply_full: reply, // 归因工具包（2026-10-16）：回复全文落报告——归因材料包/本地复盘用（旧报告无此字段，材料包容错降级）
  };
}

// 主
async function main() {
  acquireLock(); // D3：并行锁（stale>30min 自动可清；获取失败 exit 1）
  try {
    await ensureLogin(); // 登录门禁 T3：先拿 cookie 再跑题（dry-run 内部自跳过）
    if (GATE_MODE) return await mainGate();
    return await mainEval();
  } finally {
    releaseLock();
  }
}

// D2 --repeat 一致闸：kPassStats 已上移至 report_lib.mjs（单一来源，rescore 同用）——此处不再本地定义。


// 选基线：eval/reports 下最近一份「题集重叠 ≥60%」的报告（排除本轮/manifest/rescored）。
// 单题冒烟报告不会成为基线；跨集合跑（如 --only=cross）可与最近全量报告比。
function findRegression(results, currentId, taskById, scoringFp) {
  try {
    const dir = resolve(ROOT, 'eval/reports');
    if (!existsSync(dir)) return null;
    const ids = new Set(results.map((r) => r.task));
    const need = Math.max(1, Math.ceil(ids.size * 0.6));
    const cands = readdirSync(dir)
      .filter((f) => /^eval-.*\.json$/.test(f) && !f.endsWith('.manifest.json') && !f.includes('.rescored') && !f.startsWith(currentId))
      .map((f) => ({ path: resolve(dir, f), m: statSync(resolve(dir, f)).mtimeMs }))
      .sort((a, b) => b.m - a.m);
    let sawAny = false;
    for (const c of cands) {
      let rep;
      try { rep = JSON.parse(readFileSync(c.path, 'utf-8')); } catch { continue; }
      const rows = Array.isArray(rep?.results) ? rep.results : [];
      if (!rows.length) continue;
      sawAny = true;
      // 判分规则版本不同（题库/规则/判分器改过）→ 不可比，跳过（防补判据被误报为分数下滑）
      if (rep.scoring_fingerprint !== scoringFp) continue;
      const overlap = rows.filter((r) => ids.has(r.task)).length;
      if (overlap < need) continue;
      return {
        ...compareRuns(results, rows, {
          baselineRunId: rep.run_id || c.path.split(/[\\/]/).pop(),
          taskById,
          passDrop: Number(process.env.PRISM_EVAL_ALERT_PASS_DROP || 0.05),
          taskDrop: Number(process.env.PRISM_EVAL_ALERT_TASK_DROP || 2),
        }),
        baseline_path: c.path, // 2026-10-29：发版门槛（stats.py）要拿同一份基线文件路径，避免二次扫描出不同基线
      };
    }
    return sawAny ? { skip_reason: 'scoring_changed' } : null;
  } catch { /* 基线不可读 → 不报警，不影响本轮 */ }
  return null;
}

// ── 发版门槛进主流程（2026-10-29）──────────────────────────────────────
// 报告落盘前调 eval/stats.py 做四条件配对判定（veto/Wilcoxon+Cliff/frozen CI/成本），
// 同时由 stats.py 往 eval/EVAL_STATUS.md 自动追加一行台账。
// 为什么走子进程而非在 Node 重写统计：bootstrap/Wilcoxon 只有 Python 一份实现，
// 重写会形成双源（kPassStats 曾在两处算出不同值的教训）。无基线时走 --status-only 只记账。
// fail-soft 铁律：门槛不可用不阻断批跑，报告里留 release_gate_error。
function runReleaseGate(report, reportId, baselinePath) {
  const tmpCand = resolve(ROOT, `eval/reports/.gate-cand-${reportId}.json`);
  const gateJson = resolve(ROOT, `eval/reports/gate-${reportId}.json`); // 门槛判定件长期留痕（与报告同目录，不进 manifest）
  try {
    _mkdir(resolve(ROOT, 'eval/reports'), { recursive: true }); // 临时候选件与判定件都落 reports/，目录可能尚未创建
    _wf(tmpCand, JSON.stringify(report));
    const args = ['eval/stats.py'];
    if (baselinePath) args.push('--baseline', baselinePath);
    else args.push('--status-only');
    args.push('--candidate', tmpCand, '--json-out', gateJson);
    const res = spawnSync('python', args, { cwd: ROOT, encoding: 'utf-8', timeout: 180_000 });
    if (res.error) throw res.error;
    // stats.py 用退出码表达门槛是否通过（1=未过），不是执行失败——只看有无判定文件
    if (!existsSync(gateJson)) {
      return { error: `stats.py 无输出（exit ${res.status ?? '?'}）${String(res.stderr || '').slice(0, 200)}` };
    }
    return { gate: JSON.parse(readFileSync(gateJson, 'utf-8')), status: res.status };
  } catch (e) {
    return { error: e.message };
  } finally {
    try { unlinkSync(tmpCand); } catch { /* 临时文件清理失败不影响批跑 */ }
  }
}

async function mainEval() {
  console.log('='.repeat(60));
  console.log('  Prism-Agent 评估批跑 · ' + new Date().toISOString());
  const bySet = {};
  for (const t of ALL_TASKS) bySet[t.set || '(无set)'] = (bySet[t.set || '(无set)'] || 0) + 1;
  console.log(`  题数: 本批 ${ALL_TASKS.length}（题库静态 ${TASKS.length} + 动态 ${DYNAMIC_TASKS.length}；blind 与 dynamic 不进 all）`);
  console.log('  题集: --set=' + SET + (ONLY ? `，--only=${ONLY}` : '') + '（' + Object.entries(bySet).map(([k, v]) => `${k}=${v}`).join(' ') + '）');
  const BLIND_TOTAL = [...TASKS, ...DYNAMIC_TASKS].filter(t => t.set === 'blind').length;
  if (SET === 'all' && BLIND_TOTAL) console.log(`  另有 ${BLIND_TOTAL} 道 blind 盲测题未纳入本批（需 --set=blind 单独跑，跑过即降级 frozen）`);
  if (REPEAT > 1) console.log(`  --repeat=${REPEAT}（同题 ${REPEAT} 跑，一致闸=verdict同+失败态同+分差≤1）`);
  const WEB = probeWeb();
  console.log(`  web 受控: PRISM_EVAL_WEB=${WEB.mode}${WEB.mode === 'fixture' ? `（fixture 目录 ${WEB.ok ? '存在' : '缺失'}）` : ''}`);
  console.log('='.repeat(60));

  // B1-2 --dry-run：只验证过滤口径，不跑题不落报告（无网关亦可验）
  if (DRY_RUN) {
    for (const t of ALL_TASKS) {
      const webNeed = t.requires?.includes('web');
      const willSkip = webNeed && !WEB.ok ? ' [将skip:web不可用]' : '';
      console.log(`  ${t.id}\tset=${t.set || '-'}\ttrap=${t.trap_type || '-'}\ttruth=${t.truth?.anchors?.length ?? 0}锚${t.truth?.forbid?.length ? '+forbid' + t.truth.forbid.length : ''}${t.turns ? `\tturns=${t.turns.length}` : ''}${webNeed ? '\trequires=web' : ''}${willSkip}`);
    }
    console.log(`  [dry-run] run_id=${EVAL_RUN_ID} git=${TASKS_GIT_HASH} snapshot=${SNAPSHOT_IDS.join(',') || '-'} runtime=${ACTIVE_SNAPSHOT || '-'} agent_release=${AGENT_RELEASE}`);
    return;
  }

  const results = [];
  const conditionalSkipped = [];
  const dynamicPending = []; // dynamic 回灌题中"判据未人工确认"的清单（跑但不判分，不进分母）
  // 社媒深挖：TikHub 可用性探测（/tikhub/status configured；探不通按未配置 skip）
  let TIKHUB_OK = false;
  try {
    const st = await fetch(`${GATEWAY}/tikhub/status`, { headers: authHeaders(), signal: AbortSignal.timeout(5000) }).then(r => r.json());
    TIKHUB_OK = st?.configured === true;
  } catch {}
  const GATEWAY_MODEL = await probeModel();
  // P3 预检（预注册）：上游余额/鉴权不可用 → 直接退出，不进入批跑（不产生任何分数）
  if (!DRY_RUN && !CHALLENGER && process.env.PRISM_SKIP_PREFLIGHT !== '1') {
    const pf = await preflight();
    if (!pf.ok && pf.fatal) {
      console.error(`\n[preflight] 上游不可用（${pf.reason}）——立即中止，不进入批跑；本次不产生分数`);
      process.exit(3);
    }
    if (!pf.ok) console.warn(`[preflight] 非致命异常（${pf.reason}）——继续，该条不计分`);
    else console.log('[preflight] OK（模型可达）');
  }
  const totalUnits = ALL_TASKS.length * REPEAT;
  let unit = 0;
  let fatalRows = 0;      // 2026-11-02 自证闸：余额/鉴权类失败行数
  let ABORTED = null;     // 连续 2 次致命错误 → 中止（避免再跑满整批空回复）
  for (let k = 1; k <= REPEAT && !ABORTED; k++) {
    for (let i = 0; i < ALL_TASKS.length && !ABORTED; i++) {
      const task = ALL_TASKS[i];
      unit++;
      process.stderr.write(`[${unit}/${totalUnits}]${REPEAT > 1 ? `[r${k}]` : ''} ${task.id}: ${(task.turns?.[0]?.message || task.question).slice(0, 30)}... `);
      // B2-3 requires 探测：不可用 → skip 不计分母（conditional_skipped 单列）
      if (task.requires_tikhub && !TIKHUB_OK) {
        conditionalSkipped.push({ task: task.id, requires: 'tikhub', reason: 'TikHub 未配置' });
        process.stderr.write('SKIP（TikHub 未配置，不计分母）\n');
        continue;
      }
      if (task.requires?.includes('web') && !WEB.ok) {
        conditionalSkipped.push({ task: task.id, requires: 'web', reason: `PRISM_EVAL_WEB=${WEB.mode}${WEB.mode === 'fixture' ? ' 且 fixture 目录缺失' : ''}` });
        process.stderr.write(`SKIP（web 不可用（${WEB.mode}），不计分母）\n`);
        continue;
      }
      try {
        try { _wf(LOCK_FILE, JSON.stringify({ pid: process.pid, ts: Date.now(), heartbeat: true }) + '\n'); } catch {} // P1-3：锁心跳，长批跑不被误判 stale
        const result = await runTask(task, k);
        // dynamic 回灌题（2026-10-29）：判据未经人工确认（无 judge_rubric / truth / trap_type）时，
        // 跑出来的分数只作观察——标 valid:false + invalid_reason='rubric_pending'，不进任何分母，
        // 同时收进 dynamic_pending 供人工补判据。红线：判据绝不自动生成（模型不能自己出题自己判）。
        const pendingRubric = task.set === 'dynamic' && !task.judge_rubric && !task.truth && !task.trap_type;
        if (pendingRubric) {
          result.valid = false;
          result.invalid_reason = 'rubric_pending';
          result.pending_rubric = true;
          dynamicPending.push({ task: task.id, question: String(task.question || '').slice(0, 100), observed_score: result.score, reasons: result.reasons || [] });
        }
        results.push(result);
        // 2026-11-02 自证闸：连续 2 次"余额/鉴权"类失败 → 立即中止（当日 147 行空跑事故防线）
        if (/402|401|Insufficient|insufficient|余额|Unauthorized/i.test(String(result.error || ''))) {
          fatalRows++;
          if (fatalRows >= 2) { ABORTED = `upstream_auth_or_balance(${fatalRows})`; process.stderr.write('\n[abort] 连续余额/鉴权失败，停止批跑\n'); break; }
        }
        process.stderr.write(`score=${result.score} tools=${result.tools.length} settled=${result.settled}${result.cost?.tokens ? ` tokens=${result.cost.tokens.totalTokens}` : ' tokens=partial'}${pendingRubric ? ' PENDING_RUBRIC(不计分母)' : ''}\n`);
      } catch (e) {
        results.push({ task: task.id, repeat: k, score: 0, reasons: [String(e?.message || e)], error: String(e?.message || e) });
        process.stderr.write(`ERROR: ${e.message}\n`);
      }
    }
  }

  // 汇总
  console.log('\n' + '='.repeat(60));
  console.log('  汇总' + (conditionalSkipped.length ? `（conditional skip ${conditionalSkipped.length} 题不计分母）` : ''));
  console.log('='.repeat(60));

  // P1 invalid 隔离（2026-10-29）：会话创建失败等"跑坏"的行标 valid:false，不进任何分母——
  // 此前"跑坏"与"答错"都记 0 分混在统计里，是"0 分是真错还是没跑起来"无法区分的主因。
  const invalidRows = results.filter((r) => r.valid === false);
  const validResults = results.filter((r) => r.valid !== false);
  const scores = validResults.map(r => r.score);
  const avg = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
  const passCount = scores.filter(s => s >= 4).length;
  // trap 汇总：按题库 trap_type 判定（旧口径只数 id 前缀 trap，漏掉 multi/skill 类陷阱题）
  const taskById = Object.fromEntries(ALL_TASKS.map((t) => [t.id, t]));
  const trapResults = validResults.filter(r => taskById[r.task]?.trap_type);
  const trapBlockedCount = trapResults.filter(r => r.score === 5).length;
  // 审查 P1-2：挑战者批的臂间对比指标剔除"结构性臂差题"（判据依赖工具名，两臂机械确定分差，
  // 不剔除会以 ±8pp 噪声淹没预注册"trap 差≥40pp"门槛）——A0 重放侧须同规则对称剔除
  const STRUCTURAL = new Set(STRUCTURAL_TOOL_TRAPS);
  const cmpTrap = CHALLENGER ? trapResults.filter(r => !STRUCTURAL.has(r.task)) : trapResults;
  const cmpTrapBlocked = cmpTrap.filter(r => r.score === 5).length;
  // A 口径：可判集（有锚点）为正式分母，观测集单列不进通过率
  const split = splitByAnchored(validResults, taskById);
  // P0 覆盖率闸：settled 且无 error 的题必须都取到轨迹行，否则本轮判分不可信
  const COVERAGE_MIN = Number(process.env.PRISM_EVAL_COVERAGE_MIN || 1);
  const coverage = computeCoverage(validResults, COVERAGE_MIN);
  // 审查 P1-1/P2：挑战者有效性行政=臂纯度（覆盖率闸不适用——无轨迹通道，改打纯度断言）
  // 2026-11-02 自证闸：空回复率 >20% 或出现余额/鉴权失败行 → 本轮无效（当日 147 行空跑仍自称有效的防线）
  // C1b（2026-11-02）：空回复/未 settled/无工具由 runTask 标 valid:false（invalidRows）。
  // 本轮有效性 = 100% 有效行（任何 invalid 行即 false），不再用 20% 空回复率兜底。
  const emptyRows = invalidRows.filter((r) => r.invalid_reason === 'empty_reply');
  const emptyRate = results.length ? emptyRows.length / results.length : 0;
  const validRate = results.length ? validResults.length / results.length : 0;
  const runValid = CHALLENGER
    ? ARM_PURITY.length === 0
    : (coverage.ok && fatalRows === 0 && invalidRows.length === 0);
  if (CHALLENGER && ARM_PURITY.length) {
    console.error(`\n[arm-purity] 挑战者批出现布防外工具（${ARM_PURITY.length} 题）——疑似误指常规栈（PRISM_API_BASE=${process.env.PRISM_API_BASE || '未设'}），读数作废：`);
    for (const v of ARM_PURITY) console.error(`  ${v.task}#r${v.repeat}: ${v.tools.join(', ')}`);
  }
  // B3 truth 比对汇总（首跑后据此校准 scoring-rules.json 容差）
  const truthChecked = validResults.filter(r => r.truth?.checked);
  const truthFail = truthChecked.filter(r => r.truth.missing.length > 0 || r.truth.forbidHits.length > 0);

  console.log(`  总题数: ${validResults.length}${invalidRows.length ? `（另有 invalid ${invalidRows.length} 行不计分母：${invalidRows.map(r => r.task).join(',')}）` : ''}`);
  const pct = (v) => (v == null ? '-' : `${(v * 100).toFixed(0)}%`);
  const num = (v) => (v == null ? '-' : v);
  console.log(`  可判集(有锚点): ${split.anchored.pass}/${split.anchored.total} = ${pct(split.anchored.pass_rate)}，均分 ${num(split.anchored.avg)}`);
  console.log(`  观测集(无锚点): ${split.observational.pass}/${split.observational.total} = ${pct(split.observational.pass_rate)}，均分 ${num(split.observational.avg)}`);
  console.log(`  全量(仅供参考): ${passCount}/${validResults.length} = ${validResults.length ? (passCount / validResults.length * 100).toFixed(0) : 0}%，均分 ${avg.toFixed(2)}`);
  console.log(`  trap 否决率: ${trapBlockedCount}/${trapResults.length} = ${trapResults.length ? (trapBlockedCount / trapResults.length * 100).toFixed(0) : 0}%`);
  if (CHALLENGER) console.log(`  trap 否决率(臂间可比, 剔除结构题${STRUCTURAL_TOOL_TRAPS.join('/')}): ${cmpTrapBlocked}/${cmpTrap.length} = ${cmpTrap.length ? (cmpTrapBlocked / cmpTrap.length * 100).toFixed(0) : 0}%`);
  if (CHALLENGER) console.log(`  臂纯度: ${ARM_PURITY.length === 0 ? 'OK（工具面 ⊆ {run_sql, read_file}）' : `违规 ${ARM_PURITY.length} 题，读数作废`}`); // 审查 P2：挑战者批改打纯度，不再打无意义的 0% 覆盖率
  else console.log(`  轨迹覆盖率: ${coverage.covered}/${coverage.considered} = ${(coverage.rate * 100).toFixed(1)}%${coverage.ok ? '' : ' ← 本轮无效（判分不可信）'}`);
  if (!coverage.ok) console.log(`  未取到轨迹: ${coverage.missing.join(', ')}`);
  if (truthChecked.length) {
    console.log(`  truth 锚点: ${truthChecked.length - truthFail.length}/${truthChecked.length} 全中` + (truthFail.length ? `（缺锚/违禁: ${truthFail.map(r => r.task).join(',')}）` : ''));
  }
  if (conditionalSkipped.length) {
    console.log('  conditional_skipped: ' + conditionalSkipped.map(s => `${s.task}(${s.requires})`).join(', '));
  }
  let repeatStats = null;
  if (REPEAT > 1) {
    repeatStats = kPassStats(validResults);
    console.log(`  k_pass: ${repeatStats.k_pass}/${repeatStats.k_total} = ${(repeatStats.k_pass_rate * 100).toFixed(0)}%` + (repeatStats.inconsistent.length ? `（不一致: ${repeatStats.inconsistent.join(', ')}）` : ''));
  }

  console.log('\n--- 明细 ---');
  for (const r of validResults) {
    console.log(`  ${r.task}${REPEAT > 1 ? `#r${r.repeat}` : ''}: score=${r.score} | ${r.reasons.join('; ')}`);
  }
  for (const r of invalidRows) {
    console.log(`  ${r.task}${REPEAT > 1 ? `#r${r.repeat}` : ''}: INVALID(${r.invalid_reason}) 不计分 | ${r.reasons.join('; ')}`);
  }

  // 写 JSON（B1-5 元数据头 + 归档副本 eval/reports/<run_id>.json，D 门槛配对的基础）
  const reportPath = resolve(ROOT, CHALLENGER ? 'eval/challenger-report.json' : 'eval/eval-report.json'); // 挑战者独立报告件，不覆写主报告
  const { writeFileSync, mkdirSync } = await import('node:fs');
  // 评估基建小包：首错轮注记（最早缺锚/违禁轮；仅派生字段，判分路径零改动）
  for (const r of results) r.first_error_turn = firstErrorTurn(r);
  const reportId = (CHALLENGER ? 'challenger-' : '') + (REPEAT > 1 ? `${EVAL_RUN_ID}-r${REPEAT}` : EVAL_RUN_ID);
  const reportsDir = resolve(ROOT, 'eval/reports');
  // 回归报警：与最近一份题集重叠 ≥60% 的报告对比；只告警不阻断本轮
  // 盲测集例外（2026-10-27）：首跑即唯一一次测真，不与任何历史报告比（防提前暴露基线、防把盲测读成"回归"）
  const regression = (SET === 'blind' || CHALLENGER) ? null : findRegression(validResults, reportId, taskById, SCORING_FP);
  if (CHALLENGER) console.log('\n[challenger] 挑战者批：不做历史基线比较（臂间判分通道不同；A0 对照须 no-verdict 重放对齐，proposal 决策3）');
  if (SET === 'blind') {
    console.log('\n[blind] 盲测批：不做历史基线比较（首跑即真值）');
  } else if (regression?.skip_reason === 'scoring_changed') {
    console.log('\n[alert] 跳过比较：判分规则已变更，无同版本基线（以本轮为新基线）');
  } else if (regression?.alerted) {
    console.warn(`\n[alert] 回归告警（对比 ${regression.baseline_run_id}，重叠 ${regression.task_overlap} 题）`);
    const rd = regression.pass_rate;
    if (rd) console.warn(`  通过率 ${pct(rd.current)} ← ${pct(rd.baseline)}（${Math.round(rd.delta * 100)}pp）`);
    for (const x of regression.regressed_tasks) console.warn(`  分数下滑 ${x.task}: ${x.current} ← ${x.baseline}`);
    for (const t of regression.consecutive_failures) console.warn(`  连续失败 ${t}`);
  } else if (regression) {
    console.log(`\n[alert] 无回归（对比 ${regression.baseline_run_id}，重叠 ${regression.task_overlap} 题）`);
  }
  const report = {
    run_id: EVAL_RUN_ID,
    started_at: STARTED_AT,
    runner_version: RUNNER_VERSION,
    tasks_git_hash: TASKS_GIT_HASH,
    snapshot_id: SNAPSHOT_IDS.join(',') || null, // 题库声明的"设计快照"（题目锚点绑定的那一版）
    // 2026-10-31 快照绑定补实：此前报告只有题库声明，无法自证"实际跑的是哪份库"——
    // 题库写 1222 而 eval start 挂 1217 时，报告看起来仍正常。runtime 取自 ACTIVE_SNAPSHOT.txt（真源）。
    runtime_snapshot: ACTIVE_SNAPSHOT, // 实际运行挂载快照；null=未挂载/未知（drift 闸已在启动时判过）
    snapshot_drift: SNAPSHOT_DRIFT_AUDIT, // 补审 P1：null=干净跑；非 null=曾漂移放行（审计件可区分）
    agent_release: AGENT_RELEASE,
    model: GATEWAY_MODEL, // 2026-11-02：模型名留痕（"同模型"可事后审计；null=探测失败）
    arm: CHALLENGER ? undefined : currentArm(), // 2026-11-02 实验：本批所属臂（A=守卫关 / B=守卫开）
    prompt_files_hash: PROMPT_FP.hash, // prompt-gate change：本报告锚定的提示词层指纹（跨报告可比，判读差异先看这个有没有变）
    scoring_fingerprint: SCORING_FP, // 判分规则版本（只哈希判分相关字段）：不同版本之间不做回归比较
    content_fingerprint: CONTENT_FP, // 题库整文件指纹（仅审计，不参与可比性判定；改 set 标签不影响 scoring_fingerprint）
    invalid_rows: invalidRows.length, // 跑坏行数 + C1b 判分无效行（空回复/未 settled/无工具），不进任何分母
    empty_rows: emptyRows.length, // C1b：其中空回复行数
    empty_rate: Number(emptyRate.toFixed(3)),
    valid_rate: Number(validRate.toFixed(4)), // C1b：有效行覆盖率（<1 即 run_valid=false）
    abort_reason: ABORTED, // 非 null=批跑被自证闸中止（余额/鉴权）
    set_filter: SET,
    // 取代性实验 B 系列（§10.2）：挑战者臂标记 + 编造率抽检清单（数字锚题的金标锚 vs 回复实数，供 SQL 复算）
    ...(CHALLENGER ? {
      challenger: true,
      challenger_arm: CHALLENGER_ARM,
      challenger_skill: CHALLENGER_SKILL,
      challenger_note: '无轨迹/verdict 通道（verdict 恒 none）；覆盖率闸不适用；langfuse 不写（防污染 A0 dataset）；判分=challenger_check no-verdict 纯文本',
    } : {}),
    env: {
      PRISM_API_BASE: process.env.PRISM_API_BASE || null,
      PRISM_EVAL_WEB: process.env.PRISM_EVAL_WEB || null,   // B2-2：off 缺省（eval 网关注入）/live/fixture
      PRISM_WEB_FIXTURE_DIR: process.env.PRISM_WEB_FIXTURE_DIR || null,
      PRISM_FAKE_TODAY: process.env.PRISM_FAKE_TODAY || null, // B2-6 预留：舆情保质期假今日
      node: process.version,
    },
    timestamp: new Date().toISOString(),
    results,
    ...(CHALLENGER ? { audit: buildAuditList(ALL_TASKS, results) } : {}), // 挑战者编造率抽检清单（§10.2 公平性规则4）
    conditional_skipped: conditionalSkipped, // B2-3：条件题不可用单列（不计分母）
    acceptance_boundary: deriveBoundary( // 洞3：结论与适用范围绑同一份文件（快照/题集构成/适用声明）
      { run_id: EVAL_RUN_ID, tasks_git_hash: TASKS_GIT_HASH, snapshot_id: SNAPSHOT_IDS.join(',') || null, snapshot_drift: SNAPSHOT_DRIFT_AUDIT },
      ALL_TASKS,
      conditionalSkipped.map((s) => s.task),
      results, // P1-1 修复（Step7 审查）：构成由实际判分行驱动，boundary 与 summary 永不失配
    ),
    summary: {
      avg, passCount, trapBlockedCount,
      trap_total: trapResults.length,
      ...(CHALLENGER ? { trap_cmp_excluded: STRUCTURAL_TOOL_TRAPS, trap_cmp_total: cmpTrap.length, trap_cmp_blocked: cmpTrapBlocked } : {}), // 审查 P1-2：臂间可比口径（剔结构题）
      anchored: split.anchored,            // A 口径：正式分母（有机器锚点）
      observational: split.observational,  // 观测集：无锚点，不进通过率
      set_filter: SET,
      repeat: REPEAT > 1 ? repeatStats : undefined,
      pass_at_k: passAtK(validResults, 4), // Pass@k（2026-10-29）：按题去重"至少一次通过"，与 k_pass 互补
      dynamic_pending: dynamicPending.length ? dynamicPending : undefined, // dynamic 回灌题判据待确认清单（已标 valid:false 不进分母）
      // P0：本轮有效性（覆盖率闸）+ 判分可信度所需的最小元数据
      run_valid: runValid,
      valid_rate: Number(validRate.toFixed(4)), // C1b：有效行覆盖率（1.0 = 无 invalid 行）
      trajectory_coverage: {
        considered: coverage.considered, covered: coverage.covered,
        rate: Number(coverage.rate.toFixed(4)), min: COVERAGE_MIN, missing: coverage.missing,
      },
      truth: { checked: truthChecked.length, fail: truthFail.length, failTasks: truthFail.map(r => r.task) },
      regression, // 回归报警：与上一份可比报告的差异（null=无可比基线）
    },
  };
  // 发版门槛进主流程（2026-10-29）：报告落盘前用 stats.py 配对判定 + 自动往 EVAL_STATUS.md 记一行台账。
  // 无效跑次（覆盖率不足）不判门槛；无同版本基线时走 --status-only 只记账（首跑豁免语义不变）。
  if (!CHALLENGER && runValid) {
    const gateBaseline = regression?.baseline_path || null;
    const g = runReleaseGate(report, reportId, gateBaseline);
    if (g.gate) {
      report.release_gate = { ...g.gate, gate_file: `eval/reports/gate-${reportId}.json`, baseline_source: gateBaseline ? 'auto' : null };
      // 三态：pass_all=null 表示无同版本基线（单跑记账），不能打印成"❌ 0/0 未全过"
      const conds = g.gate.conditions || {};
      const headline = g.gate.pass_all == null
        ? '— 单跑记账（无同版本基线，门槛未判）'
        : `${g.gate.pass_all ? '✅ 四条件全过' : '❌ 未全过'}（${Object.values(conds).filter((c) => c.met).length}/${Object.keys(conds).length}）`;
      console.log(`\n[release-gate] ${headline} | 台账已记 EVAL_STATUS.md | 判定件: eval/reports/gate-${reportId}.json`);
    } else {
      report.release_gate_error = g.error;
      console.warn(`\n[release-gate] 未判定（不阻断批跑）: ${g.error}`);
    }
  }

  // C1a（2026-11-02）：主副本只由有效跑写入；废跑只落 reports/（+ invalid 标记件），
  // 绝不覆盖 eval/eval-report.json——此前 08:09 废跑覆盖主副本导致下游读到 3 行假数据。
  mkdirSync(reportsDir, { recursive: true });
  writeFileSync(resolve(reportsDir, `${reportId}.json`), JSON.stringify(report, null, 2));
  if (runValid) {
    writeFileSync(reportPath, JSON.stringify(report, null, 2));
  } else {
    const invalidPath = resolve(ROOT, 'eval/eval-report.invalid.json');
    writeFileSync(invalidPath, JSON.stringify(report, null, 2));
    console.warn(`[report] 本轮无效（run_valid=false）：不覆盖主副本，废跑写入 ${invalidPath}`);
  }
  // 洞2：产物 SHA-256 sidecar manifest（教材 chapter7 manifest 范式；失败不阻塞批跑）
  try {
    const _artifacts = [
      { path: resolve(reportsDir, `${reportId}.json`), rel: `eval/reports/${reportId}.json`, description: '批跑报告归档副本' },
    ];
    if (runValid) _artifacts.unshift({ path: reportPath, rel: 'eval/eval-report.json', description: '批跑报告主副本（eval-report.json）' });
    const manifest = buildManifest(
      _artifacts,
      { run_id: reportId, generated_at_utc: new Date().toISOString() },
    );
    writeFileSync(resolve(reportsDir, `${reportId}.manifest.json`), JSON.stringify(manifest, null, 2));
    console.log(`产物哈希侧车: ${reportId}.manifest.json（${manifest.artifacts.length} artifacts）`);
  } catch (e) {
    console.warn(`manifest 写入失败（不阻塞）: ${e.message}`);
  }
  console.log(`\n报告已写入: ${reportPath}`);
  console.log(`归档副本: ${resolve(reportsDir, `${reportId}.json`)}`);

  // ── langfuse 深度绑定（2026-10-19 change，T2）：题库→dataset 单向同步 + run 链接 ──
  // env PRISM_LANGFUSE_BINDING=0 可关（缺省开）；fail-soft 铁律=任何失败只 warn 不影响退出码（拍板④）。
  // P0 出口闸：覆盖率不足 → 本轮判分不可信。报告已落盘供诊断，但不写 Langfuse（防脏数据），退出码 2。
  if (!runValid) {
    if (CHALLENGER) {
      // 臂纯度违规（非覆盖率）：挑战者无轨迹通道，A 系覆盖率闸不适用——消息按实际原因报
      console.error(`\n[arm-purity-exit] 挑战者批臂纯度违规（明细见上方 [arm-purity]）——读数作废，退出码 2`);
    } else {
      console.error(`\n[run-invalid] 轨迹覆盖率 ${(coverage.rate * 100).toFixed(1)}% < ${(COVERAGE_MIN * 100).toFixed(0)}%`
        + `（未取到: ${coverage.missing.join(',') || '-'}）；空回复 ${emptyRows.length}/${validResults.length}=${(emptyRate * 100).toFixed(0)}%`
        + `${ABORTED ? `；中止原因=${ABORTED}` : ''}`
        + `——跳过 Langfuse 写入（${PENDING_SCORES.length} 条未写），退出码 2`);
    }
    process.exitCode = 2;
  } else if (CHALLENGER) {
    console.log('\n[challenger] langfuse 写入跳过（挑战者臂不写 A0 dataset/run，防基线污染；留痕=报告+audit 清单）');
  } else {
    for (const p of PENDING_SCORES) writeEvalTrace(p);
  }

  // 多轮评估批 T4：runner 已补存 per-task traceId（CH 按 sessionId 查，fail-soft null）——
  // linkRun 从"全跳过计数"变为真实挂链；CH 不可达批次仍是 null+skippedNoTrace（降级语义不变）
  // P0：本轮无效时不绑定（run 级汇总同样会污染看板）
  if (runValid && !CHALLENGER && process.env.PRISM_LANGFUSE_BINDING !== '0') {
    const runName = `${reportId}-${(PROMPT_FP.hash || 'nogate').slice(0, 8)}`; // Gap2：ts+prompt 指纹短码，同 hash 重跑天然分 run 不覆盖
    const bindResults = results.map((r) => ({ taskId: r.task, traceId: r.traceId ?? null, pass: r.score >= 4 })); // 及格线=4（与上方 passCount 同口径）
    const bound = await bindEvalRun(ALL_TASKS, runName, bindResults);
    console.log(bound
      ? `[langfuse_binding] run=${runName} | sync: 新建${bound.sync.created} 已存在${bound.sync.skipped} 失败${bound.sync.failed.length} | link: 挂链${bound.link.linked} noTrace跳过${bound.link.skippedNoTrace} 失败${bound.link.failed.length}`
      : '[langfuse_binding] 未绑定（fail-soft 降级，警告见上）');
  }
}

main().catch(e => {
  console.error('Fatal:', e);
  process.exit(1);
});

// ===========================================================================
// --gate 模式：出口闸评估门 E1-E9（M4，方案 v1.5 §六）
// 多步会话（steps 同 user 同 session）+ 断言基于末步事件流 + trajectories（含 submission）
// ===========================================================================
async function runGateStep(userId, sessionId, message) {
  const body = JSON.stringify({ message, user_id: userId, scope: 'agent', session_id: sessionId });
  // 连接层重试：undici 复用刚被对端关闭的 keep-alive 连接会 ECONNRESET（fetch failed）——
  // 长流结束（如 E1 四步）后 <1s 发新请求时确定性复现（2026-10-08 两轮门禁 E2 同位失败实证）
  let res;
  for (let attempt = 1; ; attempt++) {
    try {
      res = await fetch(`${GATEWAY}/chat/stream`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body,
      });
      break;
    } catch (e) {
      if (attempt >= 2 || String(e.cause?.code || e.message).includes('HTTP')) throw e;
      await new Promise(r => setTimeout(r, 2000));
    }
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  const texts = [], tools = [], verdicts = [];
  let settledCount = 0, error = null, sid = sessionId;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop() || '';
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const e = JSON.parse(line);
        if (e.type === 'text_delta' && e.data?.text) texts.push(e.data.text);
        else if (e.type === 'tool_call') tools.push(e.data?.name || '?');
        else if (e.type === 'settled') { settledCount++; if (e.verdict?.verdict) verdicts.push(e.verdict.verdict); }
        else if (e.type === 'session_info' && e.data?.session_id) sid = e.data.session_id;
        else if (e.type === 'error') error = e.data?.message || 'error';
      } catch {}
    }
  }
  return { texts: texts.join(''), tools, settledCount, verdicts, error, sessionId: sid };
}

function evalGateTask(task, stepResults, traj) {
  const last = stepResults[stepResults.length - 1];
  const allTools = stepResults.flatMap(s => s.tools);
  const reply = last.texts;
  const finalVerdict = last.verdicts[last.verdicts.length - 1] || null;
  const conv = (traj?.conversation || []).join('\n');
  const backfillCount = (conv.match(/\[完成验证器·保底\]/g) || []).length;
  const sub = traj?.submission || null;
  const exp = task.expect || {};
  const fails = [];
  if (exp.settledMax != null && last.settledCount > exp.settledMax) fails.push(`settled=${last.settledCount}>${exp.settledMax}`);
  if (exp.verdict && finalVerdict !== exp.verdict) fails.push(`verdict=${finalVerdict}≠${exp.verdict}`);
  if (exp.noBackfillText && /完成验证器|验收整改/.test(reply)) fails.push('回复含回灌/整改体');
  if (exp.bashMax != null && allTools.filter(t => t === 'bash').length > exp.bashMax) fails.push('bash 调用超限');
  if (exp.noError && last.error) fails.push(`error: ${String(last.error).slice(0, 60)}`);
  if (exp.guardFired && backfillCount < 1) fails.push('保底未触发');
  if (exp.backfillMax != null && backfillCount > exp.backfillMax) fails.push(`回灌 ${backfillCount} 次>${exp.backfillMax}`);
  if (exp.fabricNeverPass && reply.includes(exp.fabricNeverPass) && finalVerdict === 'pass'
      && !/无法确认|不能确认|不予确认|无法核实|不予采信|不能直接确认|无法验证|不予提交|不能提交|拒绝/.test(reply)) {
    fails.push(`编造数字 ${exp.fabricNeverPass} 以 pass 通过`);
  }
  if (exp.submissionPass && !sub?.pass) fails.push('submission 未通过');
  // E5 不变量：出口闸或保底必有其一（模型合规提交走闸 / 违规时保底兜底，均合法）
  if (exp.eitherGuardOrGate && !(sub?.pass || backfillCount >= 1)) fails.push('出口闸与保底均未触发（数字结论无把关）');
  if (exp.rejectContains && !(sub?.lastReject || '').includes(exp.rejectContains)) fails.push(`拒绝原因不含「${exp.rejectContains}」`);
  return { pass: fails.length === 0, fails };
}

async function mainGate() {
  console.log('='.repeat(60));
  console.log('  出口闸评估门 E1-E9（--gate）· ' + new Date().toISOString());
  console.log('='.repeat(60));
  const results = [];
  for (const task of GATE_TASKS) {
    const userId = `eval_${task.id.toLowerCase()}`;
    process.stderr.write(`[${task.id}] ${task.desc.slice(0, 30)}... `);
    try {
      const stepResults = [];
      let sid = null;
      for (const step of task.steps) {
        const r = await runGateStep(userId, sid, step.message);
        sid = r.sessionId;
        stepResults.push(r);
      }
      const traj = readLastTrajectory(userId, sid);
      const { pass, fails } = evalGateTask(task, stepResults, traj);
      results.push({
        task: task.id, pass, fails,
        steps: stepResults.map(s => ({ settled: s.settledCount, verdicts: s.verdicts, tools: s.tools.slice(0, 6), error: s.error })),
        submission: traj?.submission || null,
        replyPreview: (stepResults[stepResults.length - 1].texts || '').slice(0, 120),
      });
      process.stderr.write(`${pass ? 'PASS' : 'FAIL ' + fails.join('; ')}\n`);
    } catch (e) {
      results.push({ task: task.id, pass: false, fails: [e.message] });
      process.stderr.write(`ERROR: ${e.message}\n`);
    }
  }
  const failed = results.filter(r => !r.pass);
  console.log('\n' + '='.repeat(60));
  console.log(`  门禁结果: ${results.length - failed.length}/${results.length} 通过`);
  for (const r of results) {
    console.log(`  ${r.pass ? '✔' : '✖'} ${r.task}: ${r.pass ? '' : r.fails.join('; ')}`);
  }
  const { writeFileSync } = await import('node:fs');
  writeFileSync(resolve(ROOT, 'eval/gate-report.json'), JSON.stringify({ timestamp: new Date().toISOString(), results }, null, 2));
  console.log('\n报告已写入: eval/gate-report.json');
  if (failed.length > 0) process.exitCode = 1;  // 不绿不合档（exitCode 代 exit，D3 锁 finally 可释放）
}
