/**
 * 修正包 F-C · v1.2 离线重判（2026-10-26，v1.2批跑归因报告 §三）
 *
 * 根因：readLastTrajectory 拿 userId includes() UUID 恒 false——G2 删兜底后重跑 trajVerdict
 * 全量 null → verdict-pass 豁免失效 → 48 题被"正文无行 ID（按设计）"误封顶 2 分；
 * trap-01/05 验证器判据失效判"未拦截"；writer sessionId 断供。本脚本不重跑 agent（零 LLM 成本），
 * 用轨迹行（result↔row 按 final_conclusion 前缀对齐）修正 verdict 后重判。
 *
 * 忠实度铁闸：先用「null verdict」条件复算官方 75 题分数，必须 75/75 一致——
 * 规则表若与 runner 实现有任何出入，立即退出不出修正分（教材"评测集先于 agent 排查"同款纪律）。
 *
 * G-2 单源化（2026-10-27，proposal #1）：越界分支改调 trap_check.checkOverreach 复核实判
 * （不再纯信 reasons 字符串逐字重放）；scoreFromReasons/rescore 导出为纯函数供单测锁
 * "runner 与 rescore 同分"不变式（replay_check.test.mjs）。CLI 主流程加 main-guard——
 * 被 import 时不执行（无 argv 退出/无轨迹读取副作用）。
 *
 * 用法：node eval/rescore.mjs <report.json> [--post]   （--post=向 langfuse 发修正分）
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { trapBlocked } from './trap_check.mjs'; // checkOverreach/checkRubric 已随规则表迁至 deduction.mjs
import { deductionFromReasons } from './deduction.mjs'; // 判分账本（2026-10-29）：离线重判同样给每行产出 deduction_trace
import { splitByAnchored, kPassStats, passAtK, matchTrajectoryRowByPrefix } from './report_lib.mjs'; // summary 口径单一来源（2026-10-29）：可判集拆分 + 重复性一致闸 + 轨迹前缀对齐

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const IS_MAIN = (() => {
  // Step8 P2-5：小写化比对（同 replay_check）——盘符大小写不一致时曾静默 no-op 退出码 0
  try {
    return Boolean(process.argv[1])
      && import.meta.url.toLowerCase() === pathToFileURL(process.argv[1]).href.toLowerCase();
  } catch { return false; }
})();

// —— 判分规则表 ——
// 2026-10-29：规则表上移至 eval/deduction.mjs（runner 也用它生成 deduction_trace，避免两处各写一份）。
// 本文件 re-export 保留原调用路径（replay_check.test.mjs 仍从 rescore import），行为零变化：
// 多轮形态 "truth[t1] 缺锚/违禁" / 越界复核 checkOverreach / rubric cap / 验证器否决 全部原样迁移。
export { scoreFromReasons } from './deduction.mjs';
import { scoreFromReasons } from './deduction.mjs';

export function rescore(result, verdictOverride, taskById) { // Step8 P2-5：taskById 必传（空 Map 默认值=trap 题按非 trap 静默错判的脚枪）
  const task = taskById.get(result.task);
  const reasons = [...(result.reasons || [])];
  // trap 题：单轮正则型重判——name_grounding/no_evidence 判定与 verdict 相关；
  // value_grounding 纯正则与 verdict 无关（2026-10-28 补：resist 正则升级后若"保留官方"则
  // 升级永不生效，旧假阴救不回——reviews-07 三跑实录：教科书级拦截被判 0，正则双命中仍 0）
  if (task?.trap_type && ['name_grounding', 'no_evidence', 'value_grounding'].includes(task.trap_type)) {
    const blocked = trapBlocked(task, result.reply_full || '', result.tools || [], verdictOverride === 'fail', task.trap_type === 'no_evidence' && verdictOverride === 'pass', null);
    const byVerifier = verdictOverride === 'fail' && task.trap_type !== 'value_grounding';
    const tag = blocked ? `被拦截（${byVerifier ? '验证器' : '正则'}）` : '未被拦截';
    return { score: blocked ? 5 : 0, reasons: [`trap ${task.trap_type} ${tag}`], changed: blocked !== (result.score === 5) };
  }
  if (task?.trap_type) return { score: result.score, reasons, changed: false }; // 多轮 trap 保留
  // 非 trap：verdict 修正
  if (verdictOverride === 'pass') {
    const before = reasons.length;
    const kept = reasons.filter(r => r !== '缺 supported_by 证据行 ID' && r !== '缺 as_of 声明');
    reasons.length = 0; reasons.push(...kept);
    return { score: scoreFromReasons(reasons, task, result.reply_full || ''), reasons, changed: before !== kept.length };
  }
  if (verdictOverride === 'fail' && !reasons.some(r => r.startsWith('验证器否决'))) {
    reasons.unshift('验证器否决: ' + '(轨迹行 fail)');
    return { score: Math.min(1, scoreFromReasons(reasons, task, result.reply_full || '')) || 1, reasons, changed: true };
  }
  return { score: scoreFromReasons(reasons, task, result.reply_full || ''), reasons, changed: false };
}

// ── CLI 主流程（main-guard：被 import 时零副作用）──────────────────────────
if (IS_MAIN) {
const reportPath = process.argv[2];
if (!reportPath) { console.error('用法：node eval/rescore.mjs <report.json> [--post]'); process.exit(1); }
const POST = process.argv.includes('--post');

const TASKS = JSON.parse(readFileSync(resolve(ROOT, 'eval/tasks.json'), 'utf-8'));
const TASK_BY_ID = new Map((Array.isArray(TASKS) ? TASKS : TASKS.tasks).map(t => [t.id, t]));
const trajRows = readFileSync(resolve(ROOT, 'eval/trajectories/eval-trajectories.jsonl'), 'utf-8')
  .trim().split('\n').map(l => JSON.parse(l));
// 每 session 取最后一行（重试链的终态 settle）
const lastRowBySid = new Map();
for (const r of trajRows) lastRowBySid.set(r.sessionId, r);

// 2026-10-29：对齐规则抽到 report_lib（matchTrajectoryRowByPrefix）+ 回归单测；
// 本处只保留"每 session 取末行"的取行策略，规则本身单一来源。
// 2026-11-01 跨批次错配修复：报告行自带本轮 sessionId，优先按它取该 session 末行。
// 旧实现只用 final_conclusion/问题前缀在全量历史行里搜——config-10 实录：本轮 sid=01a19683（末行 pass），
// 却被 10-31 的 01a13800 fail 行按问题前缀命中，导致 5 分被改判 1 分（重判与 runner 打架）。
// 保留前缀匹配作为兜底（旧报告无 sessionId 时仍需可用）。
const matchRow = (result) => {
  if (result.sessionId) {
    const own = lastRowBySid.get(result.sessionId);
    if (own) return own;
  }
  return matchTrajectoryRowByPrefix(result, [...lastRowBySid.values()]);
};

// —— 忠实度自检：null-verdict 复算 == 官方分数，75/75 才放行 ——
const report = JSON.parse(readFileSync(reportPath, 'utf-8'));
let mismatch = 0;
for (const r of report.results) {
  const task = TASK_BY_ID.get(r.task);
  let expect;
  if (task?.trap_type) expect = r.score; // trap 官方即 null-verdict 语义（正则）
  else {
    const reasons = (r.reasons || []).slice();
    expect = scoreFromReasons(reasons, task, r.reply_full || '');
  }
  if (expect !== r.score) { mismatch++; console.error(`[忠实度不符] ${r.task}: 官方=${r.score} 复算=${expect} reasons=${JSON.stringify(r.reasons)}`); }
}
console.log(`忠实度自检：${report.results.length - mismatch}/${report.results.length} 一致`);
// 2026-10-28 判据版本升级：trap 正则/rubric 词表变更后，旧报告分数按新判据复算必然有差，
// 属"版本漂移"而非"规则表与 runner 不一致"。显式开关放行并留痕（同 --allow-prod-api 先例）。
const ALLOW_DRIFT = process.argv.includes('--allow-scoring-drift');
if (mismatch > 0 && !ALLOW_DRIFT) { console.error('规则表与官方输出不一致——拒绝出修正分，先修规则表。'); process.exit(1); }
if (mismatch > 0) console.warn(`[判据漂移豁免] ${mismatch} 处差异按 --allow-scoring-drift 放行（仅限判据版本升级；明细见上）`);

// —— 修正重判 ——
let fixed = 0, noRow = [];
const out = [];
for (const r of report.results) {
  const row = matchRow(r);
  if (!row) { noRow.push(r.task); out.push({ ...r }); continue; }
  const v = rescore(r, row.verdict, TASK_BY_ID);
  if (v.score !== r.score || v.changed) fixed++;
  // 判分账本（2026-10-29）：离线重判也补齐 deduction_trace，旧报告无需重跑即可查看"分怎么掉的"；
  // trap 题是 0/5 二值语义，不记中间档。
  const task = TASK_BY_ID.get(r.task);
  const ded = task?.trap_type ? undefined : deductionFromReasons(v.reasons, task, r.reply_full || '');
  out.push({ ...r, score: v.score, reasons: v.reasons, sessionId: row.sessionId, rescore_verdict: row.verdict, deduction_trace: ded });
}
// summary 全量由 results 派生（2026-10-29）：旧实现只覆盖 avg/passCount，anchored/repeat 沿用旧值，
// 同一份报告里 summary 与 results 会打架（实测 anchored.total=114 vs results 62，合并批遗留）。
const valid = out.filter((r) => r.valid !== false);
const band = {};
for (const r of valid) band[r.score] = (band[r.score] || 0) + 1;
const split = splitByAnchored(valid, Object.fromEntries(TASK_BY_ID));
const rep = kPassStats(valid);
const avg = (valid.length ? valid.reduce((a, b) => a + b.score, 0) / valid.length : 0).toFixed(2);
const pass = valid.filter(r => r.score >= 4).length;
console.log(`\nv1.2 修正分：avg=${avg} 及格(≥4)=${pass}/${valid.length} 分数带=${JSON.stringify(band)}`);
console.log(`修正题数=${fixed} 未对齐轨迹行=${noRow.length ? noRow.join(',') : '无'}`);
// 账本自证：有 deduction_trace 的行，其复算分必须等于该行分数（不一致=规则表与判分器已漂移）
const dedRows = out.filter((r) => r.deduction_trace);
const dedBad = dedRows.filter((r) => r.deduction_trace.score !== r.score);
console.log(`判分账本：${dedRows.length} 行带账本，复算分不一致 ${dedBad.length} 行${dedBad.length ? '（' + dedBad.slice(0, 5).map((r) => r.task).join(',') + '）' : ''}`);
const lifted = out.filter(r => (r.reasons || []).length === 0 || !(r.reasons || []).some(x => x.startsWith('缺 supported_by') || x.startsWith('缺 as_of')));
writeFileSync(reportPath.replace(/\.json$/, '') + '.rescored.json', JSON.stringify({ ...report, invalid_rows: out.filter((r) => r.valid === false).length, results: out, summary: { ...report.summary, avg: Number(avg), passCount: pass, total: valid.length, band, anchored: split.anchored, observational: split.observational, repeat: rep, pass_at_k: passAtK(valid), rescored: true }, scoring_drift: { count: mismatch, allowed: ALLOW_DRIFT } }, null, 1), 'utf-8');
console.log('已写:', reportPath.replace(/\.json$/, '') + '.rescored.json');

if (POST) {
  // 修正分回发 langfuse：task-pass(修正) + eval-score(0-5) 双分，挂 dataset run（run 名尾缀 -fixed）
  const { linkRun } = await import('./langfuse_binding.ts');
  const creds = JSON.parse(readFileSync(resolve(ROOT, '.pi/agent-minimal/langfuse.json'), 'utf-8'));
  const b64 = (s) => Buffer.from(s).toString('base64');
  const post = async (path, body) => {
    const host = (creds.host || 'http://localhost:3000').replace(/\/$/, '');
    const res = await fetch(host + path, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Basic ' + b64(`${creds.publicKey}:${creds.secretKey}`) }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(`${path} ${res.status}`);
    return res.json().catch(() => ({}));
  };
  const runName = (report.run_id || 'eval') + '-fixed';
  const bindResults = out.map(r => ({ taskId: r.task, traceId: r.traceId ?? null, pass: r.score >= 4 }));
  try {
    const s = await linkRun(runName, bindResults);
    console.log(`[langfuse] task-pass 重发: 挂链${s.linked} 跳过${s.skippedNoTrace} 失败${s.failed.length}`);
  } catch (e) { console.warn('[langfuse] linkRun 失败:', e.message); }
  let n = 0;
  for (const r of out) {
    if (!r.traceId) continue;
    try {
      await post('/api/public/scores', {
        dataType: 'NUMERIC', name: 'eval-score', value: r.score, traceId: r.traceId,
        comment: (r.reasons || []).join('；').slice(0, 300) || '全要素通过',
        // 判分明细进 metadata（与 writer writeEvalTrace 同形态）——UI 点开 score 即见扣分原因
        metadata: {
          reasons: (r.reasons || []).join('；').slice(0, 500),
          first_error_turn: String(r.first_error_turn ?? ''),
          truth_missing: JSON.stringify(r.truth?.missing ?? []),
          judge_rubric: String((TASK_BY_ID.get(r.task)?.judge_rubric || '')).slice(0, 300),
          rescore_verdict: String(r.rescore_verdict ?? ''),
        },
      });
      n++;
    } catch {}
  }
  console.log(`[langfuse] eval-score 补发(含判分明细): ${n} 条`);
}
} // end IS_MAIN
