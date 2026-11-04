/**
 * T-8.4 动态评测集 · badcase 自动转评测题
 * 从 trajectories.jsonl 读 badcase（verdict=fail 或反馈=down），生成评测题模板
 * runner 读 dynamic-tasks.json 合并 TASKS
 *
 * 2026-10-31 badcase 回流机制（用户确认只做两轮：上线前评估 + 上线后 badcase 回流）：
 *   信号分两类——
 *     A 类（系统自标）：verdict=fail（出口闸判失败，免费、可复算）
 *     B 类（用户行为）：同 session 重问 / 显式纠正 / 问了没答（发现规则层漏掉的坏例）
 *   留档四件套（问题 + 回答 + 工具轨迹 + 判因）：只存问答无法定位"没查库"还是"查了编数字"，
 *   实测 reviews-07 那次"答对了却被判 0"，必须看工具与判据才看得出来。
 *   红线不变：判据（judge_rubric/truth）绝不自动生成——真实 badcase 是新场景，无原题可继承。
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

interface Trajectory {
  sessionId: string;
  timestamp: string;
  conversation: string[];
  toolCalls: Array<{ name: string; input: any }>;
  final_conclusion: string;
  evidence_ids: string[];
  verdict: 'pass' | 'fail';
  verdict_reason: string;
}

const TRAJ_FILE = resolve(process.cwd(), '.pi/sessions/trajectories.jsonl');
const OUTPUT_FILE = resolve(process.cwd(), 'eval/dynamic-tasks.json');
const BADCASE_FILE = resolve(process.cwd(), 'eval/badcases.json');

// 显式纠正词：用户主动指出上一答不对（强信号，比"重问"更明确）
const CORRECT_RE = /不对|错了|搞错|我是说|不是这个|重新查|再查一遍|漏了|答非所问/;
// 系统注入的续跑消息（如 "[完成验证器] mixed tier 验收未通过…"）：用户不会以 [ 开头打字。
// 实测 L4 这类行被误当成"用户问题"收进 badcase，导致题面是内部验证器文案——必须排除。
const SYS_INJECT_RE = /^\s*\[/;
// 重问判定阈值：字符二元组 Jaccard ≥ 0.6（无依赖、确定性、可复算）
const REPHRASE_SIM = 0.6;

/** badcase 记录（留档四件套 + 信号） */
export interface Badcase {
  signal: string;              // 主信号（首个命中）
  signals: string[];           // 全部命中信号
  sessionId: string;
  timestamp: string;
  source_line: number;         // 轨迹文件行号（1 起，可回溯原文）
  ref_line: number | null;     // 重问/纠正时指向被否定的上一轮
  question: string;            // 触发轮的用户问题（已排除系统注入的续跑消息）
  answer: string;              // 触发轮的助手回答（截断留档）
  tools: string[];             // 工具名清单（区分"没查库"与"查了编造"）
  has_sys_inject: boolean;     // 该轮含系统注入的消息（=验证器自纠后的重试轮）
  verdict: string;
  verdict_reason: string;
  evidence_ids: string[];
}

/** 字符二元组集合（中文按字切，零依赖） */
function bigrams(s: string): Set<string> {
  const out = new Set<string>();
  const t = String(s || '').replace(/\s+/g, '');
  for (let i = 0; i < t.length - 1; i++) out.add(t.slice(i, i + 2));
  return out;
}

/** 相似度：Jaccard（0-1），空串为 0 */
export function similarity(a: string, b: string): number {
  const A = bigrams(a);
  const B = bigrams(b);
  if (!A.size || !B.size) return 0;
  let n = 0;
  for (const x of A) if (B.has(x)) n++;
  return n / (A.size + B.size - n);
}

/**
 * 采集 badcase（纯函数，不写盘）。
 * conversation 数组每行是一条消息（"user: ..." / "assistant: ..."）；
 * 同一会话可出现在多行（每行=一次交互，带截至当轮的完整历史）。
 */
export function collectBadcases(trajPath: string = TRAJ_FILE): Badcase[] {
  if (!existsSync(trajPath)) return [];
  let lines: string[] = [];
  try { lines = readFileSync(trajPath, 'utf-8').trim().split('\n'); } catch { return []; }
  const out: Badcase[] = [];
  const lastUserBySession = new Map<string, { text: string; line: number }>();

  lines.forEach((line, idx) => {
    if (!line.trim()) return;
    let t: Trajectory;
    try { t = JSON.parse(line); } catch { return; }
    const conv = Array.isArray(t.conversation) ? t.conversation.filter((c) => typeof c === 'string') : [];
    const users = conv.filter((c) => c.startsWith('user:'));
    const assistants = conv.filter((c) => c.startsWith('assistant:'));
    // 只认人类真实提问：系统注入的续跑消息（"[完成验证器] …"）不是用户问题，跳过取上一条真实消息
    const humanUsers = users.filter((c) => !SYS_INJECT_RE.test(c.replace(/^user:\s*/, '')));
    const lastUser = humanUsers.length ? humanUsers[humanUsers.length - 1].replace(/^user:\s*/, '') : '';
    if (!lastUser) return;
    const hasSysInject = users.some((c) => SYS_INJECT_RE.test(c.replace(/^user:\s*/, '')));
    const sid = String(t.sessionId || '');

    const signals: string[] = [];
    let refLine: number | null = null;
    if (t.verdict === 'fail') signals.push('verdict_fail');
    if (CORRECT_RE.test(lastUser)) signals.push('user_correct');
    const prev = lastUserBySession.get(sid);
    if (prev && similarity(prev.text, lastUser) >= REPHRASE_SIM) {
      signals.push('user_rephrase');
      refLine = prev.line;
    }
    // 最后一条是 user：问了没等到回答（会话中断）
    if (conv.length && conv[conv.length - 1].startsWith('user:')) signals.push('no_answer');

    lastUserBySession.set(sid, { text: lastUser, line: idx + 1 });
    if (!signals.length) return;

    const tools = Array.isArray(t.toolCalls) ? t.toolCalls.map((c) => String(c?.name || '')).filter(Boolean) : [];
    out.push({
      signal: signals[0],
      signals,
      sessionId: sid,
      timestamp: String(t.timestamp || ''),
      source_line: idx + 1,
      ref_line: refLine,
      question: lastUser.slice(0, 500),
      answer: String(assistants[assistants.length - 1] || '').replace(/^assistant:\s*/, '').slice(0, 2000),
      tools: [...new Set(tools)],
      has_sys_inject: hasSysInject,
      verdict: String(t.verdict || ''),
      verdict_reason: String(t.verdict_reason || ''),
      evidence_ids: Array.isArray(t.evidence_ids) ? t.evidence_ids : [],
    });
  });
  return out;
}

/**
 * 从轨迹 badcase 生成评测题（原 T-8.4 逻辑保留，数据源改走 collectBadcases 以便复用信号判定）。
 * 题里只放"问什么/为什么收"，不放原答案——答案是留档件 badcases.json 的职责。
 */
export function generateDynamicTasks(): any[] {
  const cases = collectBadcases();
  const tasks: any[] = [];
  const seen = new Set<string>();

  for (const c of cases) {
    // 去重（同问题不重复生成）
    const key = c.question.slice(0, 50);
    if (seen.has(key)) continue;
    seen.add(key);

    tasks.push({
      id: `dynamic-${tasks.length + 1}`,
      // 2026-10-29：动态题统一打 set='dynamic'——runner 的 --set=all 不包含它，
      // 必须显式 --set=dynamic 单跑；判据未人工确认前不进任何分母。
      set: 'dynamic',
      requires_review: true,
      dimension: '跨维度',
      question: c.question,
      trap_type: null,
      // 红线：判据不自动生成（模型不能自己出题自己判）；真实 badcase 是新场景，无原题可继承
      judge_rubric: null,
      truth: null,
      source: c.signal === 'verdict_fail' ? 'badcase' : `badcase:${c.signal}`,
      sessionId: c.sessionId,
      source_line: c.source_line,
      // 2026-10-31 快照绑定：轨迹里不带快照 ID，不能假装知道当时挂的库 → 'any'（不参与漂移断言）
      snapshot_id: 'any',
      original_verdict: c.verdict,
      original_reason: c.verdict_reason,
      expected: '修正原 badcase：' + (c.verdict_reason || '补充证据/口径/缺口声明'),
    });
  }
  return tasks;
}

/**
 * 2026-10-29 新增：从评测报告回灌（真实入口——项目目前没有用户流量轨迹，但有批跑报告）。
 * 只收"有效跑次 + 低分(＜4) + 非 trap"的题：trap 题失败是真实编造/漏拦，应 hotfix + 冻结集回归，
 * 不属于"转题"；跑坏行（valid=false）无分析价值。
 * 判据（judge_rubric/truth）一律留空——由人工按扣分账本补，runner 对空判据题只跑不判分。
 */
export function generateFromReport(reportPath: string): any[] {
  const report = JSON.parse(readFileSync(resolve(process.cwd(), reportPath), 'utf-8'));
  let taskDefs: any[] = [];
  try { taskDefs = JSON.parse(readFileSync(resolve(process.cwd(), 'eval/tasks.json'), 'utf-8')); } catch {}
  const tmap = new Map(taskDefs.map((t: any) => [t.id, t]));
  const seen = new Set<string>();
  const out: any[] = [];
  for (const r of report.results || []) {
    if (r.valid === false) continue;              // 跑坏行不回灌
    if ((r.score ?? 5) >= 4) continue;            // 只收低分
    if (seen.has(r.task)) continue;               // 同题多跑只取一次
    const t: any = tmap.get(r.task) || {};
    // 红线级失败走 hotfix，不转题：按 trap_type 判，不按 id 前缀——config-13/reviews-07 的 id
    // 不以 trap 开头，但 trap_type=value_grounding，实测被漏放进了回灌清单。
    if (t.trap_type || String(r.task).startsWith('trap')) continue;
    seen.add(r.task);
    out.push({
      id: `dyn-${r.task}`,                        // 前缀固定，重复生成幂等
      set: 'dynamic',
      dimension: t.dimension || r.dimension || '跨维度',
      question: t.question || r.question || '',
      turns: t.turns || null,
      ui_strategy: t.ui_strategy || null,
      source: 'eval-badcase',
      source_run: report.run_id || null,
      source_task: r.task,
      // 2026-10-31 快照绑定：回灌题是原题复现，快照随原题继承（'any' 原样保留，不伪造）
      snapshot_id: t.snapshot_id ?? 'any',
      observed_score: r.score,
      observed_reasons: r.reasons || [],
      deduction_steps: (r.deduction_trace && r.deduction_trace.steps) || [],
      // 2026-10-30 修正：回灌题=原题原样复现（question/turns 逐字继承），判据必须一并继承。
      // 判据来自原题、先于本次运行就存在，不构成"模型自己出题自己判"；此前置 null 导致
      // 11 题跑出来全是 rubric_pending 不进分母，闭环空转（实测 10/11 题 q 同=true、原题均带 rubric）。
      judge_rubric: t.judge_rubric ?? null,        // 引用原题判据，不生成
      truth: t.truth ?? null,
      rubric_params: t.rubric_params ?? null,
      expected_evidence: t.expected_evidence ?? null,
      // 判据已随原题继承则无需人工复核；仅原题本身无判据时才挂 review（如待确认金标的题）
      requires_review: !(t.judge_rubric || t.truth),
      expected: '修正原题失败点：' + ((r.reasons || [])[0] || '见 observed_reasons'),
    });
  }
  return out;
}

// CLI：生成 dynamic-tasks.json / badcases.json
//   node eval/dynamic-tasks.ts                                   # 从轨迹 badcase 生成题
//   node eval/dynamic-tasks.ts --collect                         # 只采集留档（四件套）不转题
//   node eval/dynamic-tasks.ts --from-report=eval/reports/x.json # 从批跑报告回灌
// 2026-10-29 修正：Windows 下 `file://${argv[1]}` 拼出 file://C:\... 与 import.meta.url 不匹配，
// CLI 分支静默不执行（本次实测 exit 0 无输出）。改用 pathToFileURL + 小写比对（同 replay_check 教训）。
const IS_MAIN = (() => {
  try {
    return Boolean(process.argv[1]) && import.meta.url.toLowerCase() === pathToFileURL(process.argv[1]).href.toLowerCase();
  } catch { return false; }
})();
if (IS_MAIN) {
  const arg = process.argv.find((a) => a.startsWith('--from-report='));
  if (arg) {
    const p = arg.slice('--from-report='.length).replace(/^["']|["']$/g, '');
    const tasks = generateFromReport(p);
    writeFileSync(OUTPUT_FILE, JSON.stringify(tasks, null, 2));
    console.log(`从报告回灌 ${tasks.length} 个动态题（判据已随原题继承；requires_review=${tasks.filter(t => t.requires_review).length}）→ ${OUTPUT_FILE}`);
    for (const t of tasks) console.log(`  ${t.id}\t原分=${t.observed_score}\t首因=${(t.observed_reasons[0] || '').slice(0, 40)}`);
  } else if (process.argv.includes('--collect')) {
    // 只留档不转题：人工过目后再决定哪些值得进题库（badcase 不等于题）
    const cases = collectBadcases();
    writeFileSync(BADCASE_FILE, JSON.stringify(cases, null, 2));
    console.log(`采集 ${cases.length} 条 badcase（四件套留档）→ ${BADCASE_FILE}`);
    const bySignal = {};
    for (const c of cases) bySignal[c.signal] = (bySignal[c.signal] || 0) + 1;
    console.log(`  信号分布：${JSON.stringify(bySignal)}`);
    for (const c of cases) console.log(`  [${c.signal}] L${c.source_line} tools=${c.tools.length}\t${c.question.slice(0, 36)}\t${c.verdict_reason.slice(0, 30)}`);
  } else {
    const tasks = generateDynamicTasks();
    writeFileSync(OUTPUT_FILE, JSON.stringify(tasks, null, 2));
    console.log(`生成 ${tasks.length} 个动态评测题 → ${OUTPUT_FILE}`);
  }
}
