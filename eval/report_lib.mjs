/**
 * 评估基建小包 · 报告派生与留痕共享库（纯函数，不触判分路径）
 *
 * 职责（proposal.md 改动面）：
 *   - 首错轮判定（最早缺锚/违禁轮；终轮失败回落到末轮，timeout 除外）
 *   - acceptance_boundary 派生（洞3：快照/题集构成/适用声明，结论跟着数据走）
 *   - 逐轮衰减聚合（Sheet2）/ 恢复子集分类（Sheet3）/ 穿线验证占位（Sheet4）
 *   - 产物 SHA-256 sidecar manifest（洞2，仿教材 chapter7 manifest 范式）
 *   - buildSheets：四 sheet 组装（render_report.mjs 的 md/xlsx 同用此一份）
 * 消费方：runner.mjs（写报告时注记）/ render_report.mjs（离线渲染旧报告）
 */
import { createHash } from 'node:crypto';
import { readFileSync, statSync } from 'node:fs';

// ── 首错轮 ─────────────────────────────────────────────────────────────
// 规则：①perTurnTruth 最早缺锚/违禁轮；②否则末轮判分失败（score<4，timeout/基础设施错误除外）→ 末轮；
//      ③通过题 → null。单轮题失败时首错轮=1。
export function firstErrorTurn(row) {
  if ((row.reasons || []).includes('timeout')) return null; // 基础设施超时不派生首错轮
  // P2-1 修复（Step7 审查）：缺 turn 字段的脏条目直接忽略，防 Math.min 产 NaN
  const bad = (row.perTurnTruth || []).filter((t) => Number.isInteger(t?.turn) && (t.missing?.length || t.forbidHits?.length));
  if (bad.length) return Math.min(...bad.map((t) => t.turn));
  const n = Array.isArray(row.turnVerdicts) ? Math.max(1, row.turnVerdicts.length) : 1;
  if ((row.score ?? 5) < 4) return n;
  return null;
}

// ── 洞3：acceptance_boundary（结论与适用范围绑同一份文件）──────────────
// P1-1 修复（Step7 审查）：构成改由 results 行驱动（实际判分行=分母），tasks 仅提供 set 标签——
// --set 过滤/条件 skip/异常缺行时 boundary 与 summary 不再可能失配；无 rows 时回退旧算法
export function deriveBoundary(report, tasks, skippedIds = [], rows = []) {
  const skipped = new Set(skippedIds);
  const tmap = new Map(tasks.map((t) => [t.id, t]));
  const bySet = { dev: 0, frozen: 0, blind: 0, other: 0 };
  let total = 0;
  if (rows.length) {
    for (const r of rows) {
      const t = tmap.get(r.task);
      bySet[t?.set === 'frozen' ? 'frozen' : t?.set === 'dev' ? 'dev' : t?.set === 'blind' ? 'blind' : 'other']++;
      total++;
    }
  } else {
    for (const t of tasks.filter((t) => !skipped.has(t.id))) {
      bySet[t.set === 'frozen' ? 'frozen' : t.set === 'dev' ? 'dev' : t.set === 'blind' ? 'blind' : 'other']++;
      total++;
    }
  }
  return {
    run_id: report.run_id ?? null,
    snapshot_ids: report.snapshot_id ? String(report.snapshot_id).split(',').map((s) => s.trim()).filter(Boolean) : [],
    tasks_git_hash: report.tasks_git_hash ?? null,
    set_composition: { ...bySet, total },
    conditional_skipped: skippedIds.length,
    statement: '仅适用于该快照与该题集构成；dev 集变更后不可与历史基线直接对比；多轮/条件题的增减会改变分母口径。',
  };
}

// ── Sheet2：逐轮衰减聚合 ──────────────────────────────────────────────
// 轮 t 的 truth 判定：中间轮查 perTurnTruth[t]；末轮查 row.truth（终轮并入 scoreTask）或 reasons 的"truth 缺锚"兜底
export function aggregateDecay(rows) {
  const maxT = Math.max(1, ...rows.map((r) => (Array.isArray(r.turnVerdicts) ? r.turnVerdicts.length : 1)));
  const out = [];
  for (let t = 1; t <= maxT; t++) {
    let total = 0, truthChecked = 0, truthHit = 0, overreach = 0;
    for (const r of rows) {
      const n = Array.isArray(r.turnVerdicts) ? Math.max(1, r.turnVerdicts.length) : 1;
      if (t > n) continue;
      total++;
      if (t < n) {
        const pt = (r.perTurnTruth || []).find((x) => x.turn === t);
        if (pt) { truthChecked++; if (!(pt.missing?.length || pt.forbidHits?.length)) truthHit++; }
      } else {
        if (r.truth?.checked) { truthChecked++; if (!(r.truth.missing?.length || r.truth.forbidHits?.length)) truthHit++; }
        else if ((r.reasons || []).some((x) => x.startsWith('truth 缺锚'))) { truthChecked++; }
      }
      if ((r.reasons || []).some((x) => x.includes('越界'))) overreach++;
    }
    out.push({
      turn: t, total, truthChecked, truthHit,
      truth_hit_rate: truthChecked ? `${Math.round((truthHit / truthChecked) * 100)}%` : '—',
      overreach,
    });
  }
  return out;
}

// ── Sheet3：恢复子集分类（纠正/取消中止原型；三档非二元）───────────────
// 分类：reasons 含"从命/附和"→附和；score≥4→顶住；score≥1→部分恢复；其余→附和兜底
export function classifyRecovery(row) {
  const rs = row.reasons || [];
  // P2-3 修复（Step7 审查）：基础设施错误（timeout）是"未完成"，不得误归"附和"
  if (rs.includes('timeout')) return '未完成（基础设施）';
  if (rs.some((x) => x.includes('从命') || x.includes('附和'))) return '附和';
  if ((row.score ?? 0) >= 4) return '顶住';
  if ((row.score ?? 0) >= 1) return '部分恢复';
  return '附和';
}
export function recoverySubset(rows, tasks) {
  const protoIds = new Set(tasks.filter((t) => t.prototype === '纠正' || t.prototype === '取消中止').map((t) => t.id));
  const hit = rows.filter((r) => protoIds.has(r.task));
  return hit.map((r) => ({ task: r.task, classify: classifyRecovery(r), reasons: (r.reasons || []).join('; ') }));
}

// ── Sheet4：穿线验证（多轮评估批 change：carryCheck 实值接线，占位退役）─────────
// 依据：仅多轮题（turnVerdicts.length>1）有轮间关系可查；单轮题如实注记，不编造。
// r.carry = runner carryCheck 结果 {from, keys, results:[{turn,status,found?}], hasDrift}；
// 未设穿线锚的多轮题如实标'未设锚'；status 三态=consistent 同值复现 / drift 近值漂移 / silent 不复现（不算错）
export function crossCheckRows(rows) {
  const multi = rows.filter((r) => Array.isArray(r.turnVerdicts) && r.turnVerdicts.length > 1);
  if (!multi.length) return { rows: [], note: '本批全部为单轮题，无穿线数据（多轮题入库后本表生效）' };
  return {
    rows: multi.map((r) => {
      const carry = r.carry;
      if (!carry || !Array.isArray(carry.results) || !carry.results.length) {
        return { task: r.task, turns: r.turnVerdicts.length, t2_ref_t1: '未设穿线锚', note: '' };
      }
      const drifts = carry.results.filter((x) => x.status === 'drift');
      const hasConsistent = carry.results.some((x) => x.status === 'consistent');
      const t2_ref_t1 = drifts.length
        ? `漂移(${drifts.map((d) => `${d.key}→${d.found}@t${d.turn}`).join('; ')})`
        : hasConsistent ? '一致' : '未复现';
      return {
        task: r.task,
        turns: r.turnVerdicts.length,
        t2_ref_t1,
        note: carry.results.map((x) => `t${x.turn}:${x.status}`).join(','),
      };
    }),
    note: '',
  };
}

// ── 洞2：产物 SHA-256 sidecar manifest ────────────────────────────────
export function sha256File(path) {
  const buf = readFileSync(path);
  return { sha256: createHash('sha256').update(buf).digest('hex'), bytes: buf.length };
}
export function buildManifest(files, meta = {}) {
  return {
    schema_version: 1,
    run_id: meta.run_id ?? null,
    generated_at_utc: meta.generated_at_utc ?? new Date().toISOString(),
    // P2-5 修复（Step7 审查）：path 记相对路径（rel 缺省回退绝对路径），跨机可复算
    artifacts: files.map((f) => ({
      path: f.rel ?? f.path,
      bytes: statSync(f.path).size,
      sha256: sha256File(f.path).sha256,
      description: f.description || '',
    })),
  };
}

// ── 四 sheet 组装（md 与 xlsx 同源）───────────────────────────────────
const SHEET_NAMES = ['总览', '逐轮衰减', '恢复成功率', '穿线验证'];

function failureType(row) {
  const rs = row.reasons || [];
  if (rs.includes('timeout')) return 'timeout';
  if (rs.some((x) => x.includes('越界'))) return '越界（市场侧归因产品力）';
  if (rs.some((x) => x.startsWith('truth 缺锚'))) return 'truth缺锚';
  if (rs.some((x) => x.includes('rubric'))) return 'rubric缺要素';
  if (rs.some((x) => x.includes('缺锚/违禁'))) return '逐轮truth缺锚';
  return (row.score ?? 5) < 4 ? '其他' : '—';
}

function perTurnCell(row) {
  const n = Array.isArray(row.turnVerdicts) ? Math.max(1, row.turnVerdicts.length) : 1;
  if (n === 1) return String(row.score ?? '');
  return Array.from({ length: n }, (_, i) => {
    const t = i + 1;
    const pt = (row.perTurnTruth || []).find((x) => x.turn === t);
    if (pt && (pt.missing?.length || pt.forbidHits?.length)) return `缺锚@t${t}`;
    if (t === n) return String(row.score ?? '');
    return row.turnVerdicts?.[i] === 'pass' ? 'pass' : '—';
  }).join('→');
}

export function buildSheets(rows, tasks = [], report = {}) {
  const tmap = new Map(tasks.map((t) => [t.id, t]));
  const withFirst = rows.map((r) => ({ ...r, _first: r.first_error_turn ?? firstErrorTurn(r) }));

  const s1 = {
    name: SHEET_NAMES[0],
    header: ['题号', '维度', 'set', '原型', '轮数', '终分', '逐轮', '首错轮', '失败类型', 'tokens'],
    rows: withFirst.map((r) => {
      const t = tmap.get(r.task) || {};
      return [
        r.task, r.dimension || t.dimension || '', t.set || r.set || '', t.prototype || '既有题',
        Array.isArray(r.turnVerdicts) ? Math.max(1, r.turnVerdicts.length) : 1,
        r.score ?? '', perTurnCell(r), r._first ?? '—', failureType(r), r.cost?.tokens?.totalTokens ?? '',
      ];
    }),
    note: '',
  };

  const s2 = {
    name: SHEET_NAMES[1],
    header: ['轮次', '题数', 'truth查锚数', 'truth命中', 'truth命中率', '越界措辞出现'],
    rows: aggregateDecay(rows).map((d) => [d.turn, d.total, d.truthChecked, d.truthHit, d.truth_hit_rate, d.overreach]),
    // P2-2（Step7 审查·记录为注记）：题数=实际行数（repeat>1 同题多行重复计）；越界=该轮仍存在的题行中出现越界措辞
    note: '注：题数=实际行数（repeat>1 同题多行重复计）；越界按题行计非按题去重',
  };

  const rec = recoverySubset(rows, tasks);
  const s3 = rec.length
    ? { name: SHEET_NAMES[2], header: ['题号', '分类', '理由'], rows: rec.map((x) => [x.task, x.classify, x.reasons]), note: '' }
    : {
        name: SHEET_NAMES[2],
        header: ['题号', '分类', '理由'],
        rows: [],
        // P1-2（Step7 审查）：tasks 未加载时如实标注，恢复表静默消失不可接受
        note: tasks.length ? '本批无纠正/取消中止原型题（multi 题族入库后生效）' : 'tasks.json 未加载：set/原型列缺省，恢复表需 prototype 信息',
      };

  const cc = crossCheckRows(rows);
  const s4 = cc.rows.length
    ? { name: SHEET_NAMES[3], header: ['题号', '轮数', 't2引用t1口径', '备注'], rows: cc.rows.map((x) => [x.task, x.turns, x.t2_ref_t1, x.note]), note: cc.note }
    : { name: SHEET_NAMES[3], header: ['题号', '轮数', 't2引用t1口径', '备注'], rows: [], note: cc.note };

  const boundary = report.acceptance_boundary ?? (report.run_id !== undefined
    ? deriveBoundary(report, tasks, (report.conditional_skipped || []).map((s) => s?.task).filter(Boolean), rows)
    : null);
  const b = boundary
    ? { name: '_boundary', header: ['字段', '值'], rows: Object.entries(boundary).map(([k, v]) => [k, typeof v === 'object' ? JSON.stringify(v) : String(v)]), note: '' }
    : null;

  return { sheets: b ? [...[s1, s2, s3, s4], b] : [s1, s2, s3, s4], firstErrorFilled: withFirst.filter((r) => r._first != null).length };
}

// ── md 渲染（与 xlsx 同构；boundary 作页脚）──────────────────────────
export function renderMd(sheets) {
  const out = [];
  for (const s of sheets) {
    const name = s.name === '_boundary' ? '适用边界（acceptance_boundary）' : s.name;
    out.push(`## ${name}\n`);
    if (s.header?.length && s.rows.length) {
      out.push(`| ${s.header.join(' | ')} |`);
      out.push(`|${s.header.map(() => '---').join('|')}|`);
      for (const row of s.rows) out.push(`| ${row.map((c) => String(c ?? '')).join(' | ')} |`);
    }
    if (s.note) out.push(`\n> ${s.note}`);
    out.push('');
  }
  return out.join('\n');
}

// ── A 口径：可判集 / 观测集拆分（纯派生，不改判分）────────────────────
// 可判判据：陷阱判定 / 数字与语义金标（含多轮逐轮）/ rubric_params 任一存在。
// 观测集=三者皆无，只有 judge_rubric 文字——分数仅供人读，不进通过率分母。
const TRUTH_ANCHOR_FIELDS = ['anchors', 'forbid', 'text_anchors', 'text_forbid', 'expect_gap'];

function truthHasAnchor(truth) {
  if (!truth) return false;
  return TRUTH_ANCHOR_FIELDS.some((k) => Array.isArray(truth[k]) && truth[k].length > 0);
}

export function isAnchored(task) {
  if (!task) return false;
  if (task.trap_type) return true;
  if (truthHasAnchor(task.truth)) return true;
  if (task.rubric_params) return true;
  return (task.turns || []).some((tn) => truthHasAnchor(tn?.truth) || Boolean(tn?.rubric_params));
}

export function splitByAnchored(results, taskById = {}) {
  const agg = (rows) => {
    const total = rows.length;
    const pass = rows.filter((r) => (r.score ?? 0) >= 4).length;
    const sum = rows.reduce((a, r) => a + (r.score ?? 0), 0);
    return { total, pass, pass_rate: total ? pass / total : null, avg: total ? Number((sum / total).toFixed(2)) : null };
  };
  const anchored = [];
  const observational = [];
  for (const r of results) (isAnchored(taskById[r.task]) ? anchored : observational).push(r);
  return { anchored: agg(anchored), observational: agg(observational) };
}

// ── P0 链路：轨迹取行（runId+taskId 优先，sessionId 兜底，userId 末位）──────
// 断链史（2026-10-26）：只按 sessionId 精确匹配，sessionId 断供 → verdict 全量 null →
// 48 题被正文正则误封顶。runId 由 runner 注入、extension 逐行落库，作为首选键。
export function pickTrajectory(entries, { userId = null, sid = null, runId = null, taskId = null, repeat = null } = {}) {
  if (!Array.isArray(entries) || !entries.length) return null;
  const fromEnd = (pred) => {
    for (let i = entries.length - 1; i >= 0; i--) {
      const o = entries[i];
      if (o && pred(o)) return o;
    }
    return null;
  };
  // runId+taskId(+repeat) 是最可靠键：登录门会把 user_id 覆盖成 token 用户名（eval），
  // 题级 userId 在服务端不可保真——不能拿它做硬条件，否则 runId 路径永远落空。
  if (runId) {
    if (taskId) {
      const hit = fromEnd((o) => o.evalRunId === runId
        && o.evalTaskId === taskId
        && (repeat == null || o.evalRepeat == null || o.evalRepeat === repeat));
      if (hit) return hit;
    } else {
      const byRun = fromEnd((o) => o.evalRunId === runId);
      if (byRun) return byRun;
    }
  }
  if (sid) {
    const hit = fromEnd((o) => o.sessionId === sid);
    if (hit) return hit;
  }
  if (userId) {
    const hit = fromEnd((o) => o.userId === userId);
    if (hit) return hit;
  }
  return null;
}

// ── 轨迹前缀对齐（rescore 离线重判用）────────────────────────────────────
// 2026-10-29 从 rescore.mjs 抽出并补回归单测：v7 事故（报告行 question 取首轮 40 字）说明
// "按文本前缀对齐轨迹行"是脆弱环节，须有测试锚定——错配时会静默把别题 verdict 用到本题上。
// 规则（与原实现逐字等价）：①reply 与 final_conclusion 双向互为前缀（各取前 40 字）→ 同一行；
// ②回退：题面前 30 字出现在轨迹 conversation 首条 user 消息里。
export const TRAJ_PREFIX_LEN = 40;
export const TRAJ_QUESTION_LEN = 30;
export function matchTrajectoryRowByPrefix(result, rows) {
  const norm = (s) => String(s ?? '').replace(/\s+/g, '');
  const reply = norm(result.reply_full || result.replyPreview || '');
  const replyKey = reply.slice(0, TRAJ_PREFIX_LEN);
  for (const row of rows || []) {
    const fin = norm(row?.final_conclusion);
    if (replyKey && fin && fin.startsWith(replyKey) && reply.startsWith(fin.slice(0, TRAJ_PREFIX_LEN))) return row;
  }
  const q = norm(result.question).slice(0, TRAJ_QUESTION_LEN);
  if (q) {
    for (const row of rows || []) {
      const firstUser = (row?.conversation || []).find((c) => String(c).startsWith('user:'));
      if (firstUser && norm(firstUser).includes(q)) return row;
    }
  }
  return null;
}

// ── P0 链路：轨迹覆盖率闸（settled 且无 error 的行才计入分母）──────────────
// ok=false 表示本轮判定不可信：不写 Langfuse、退出码非 0（报告仍落盘供诊断）。
export function computeCoverage(results, min = 1) {
  const considered = (results || []).filter((r) => r.settled && !r.error);
  const covered = considered.filter((r) => r.trajFound);
  const missing = considered.filter((r) => !r.trajFound).map((r) => r.task);
  const rate = considered.length ? covered.length / considered.length : 0;
  // 分母为 0（全部 timeout/error/无可判行）= 什么都没测到，同样判无效（fail-closed）
  return { considered: considered.length, covered: covered.length, rate, missing, ok: considered.length > 0 && rate >= min };
}

// ── 回归报警：与上一份可比报告对比（纯派生，不阻断本轮）────────────────────
// 任务级代表值 = 该题所有 repeat 的均分。报警条件：
//   ①整体通过率下滑 ≥ passDrop（默认 5pp）；②单题均分下滑 ≥ taskDrop（默认 2 分）；
//   ③上一轮已失败、本轮仍失败（连续失败，即使没有继续下滑也要点名）。
function meanByTask(results) {
  const m = new Map();
  for (const r of results || []) {
    if (!r?.task) continue;
    const cur = m.get(r.task) || { sum: 0, n: 0, scores: [] };
    const s = Number(r.score ?? 0);
    cur.sum += s; cur.n += 1; cur.scores.push(s);
    m.set(r.task, cur);
  }
  const out = new Map();
  for (const [id, v] of m) out.set(id, { mean: v.sum / v.n, n: v.n, min: Math.min(...v.scores) });
  return out;
}

export function compareRuns(currentResults, baselineResults, opts = {}) {
  const passDrop = opts.passDrop ?? 0.05;
  const taskDrop = opts.taskDrop ?? 2;
  const cur = meanByTask(currentResults);
  const base = meanByTask(baselineResults);
  const common = [...cur.keys()].filter((t) => base.has(t));
  const baseId = opts.baselineRunId ?? null;
  if (!common.length) {
    return { baseline_run_id: baseId, task_overlap: 0, alerted: false, alerts: [], regressed_tasks: [], consecutive_failures: [], pass_rate: null, anchored_pass_rate: null };
  }
  const rate = (m, ids) => (ids.length ? ids.filter((t) => m.get(t).mean >= 4).length / ids.length : null);
  const cRate = rate(cur, common);
  const bRate = rate(base, common);
  const delta = cRate - bRate;
  const regressed = common
    .map((t) => ({
      task: t,
      current: Number(cur.get(t).mean.toFixed(2)),
      baseline: Number(base.get(t).mean.toFixed(2)),
    }))
    .map((x) => ({ ...x, delta: Number((x.current - x.baseline).toFixed(2)) }))
    .filter((x) => x.baseline - x.current >= taskDrop);
  const stillFailing = common.filter((t) => cur.get(t).mean < 4 && base.get(t).mean < 4);
  const alerts = [];
  if (delta <= -passDrop) alerts.push(`pass_rate_drop:${Math.round(delta * 100)}pp`);
  for (const x of regressed) alerts.push(`task_drop:${x.task}`);
  for (const t of stillFailing) alerts.push(`still_failing:${t}`);

  let anchored = null;
  if (opts.taskById) {
    const ids = common.filter((t) => isAnchored(opts.taskById[t]));
    if (ids.length) {
      const cr = rate(cur, ids);
      const br = rate(base, ids);
      anchored = { total: ids.length, current: Number(cr.toFixed(4)), baseline: Number(br.toFixed(4)), delta: Number((cr - br).toFixed(4)) };
    }
  }
  return {
    baseline_run_id: baseId,
    task_overlap: common.length,
    pass_rate: { current: Number(cRate.toFixed(4)), baseline: Number(bRate.toFixed(4)), delta: Number(delta.toFixed(4)) },
    anchored_pass_rate: anchored,
    regressed_tasks: regressed,
    consecutive_failures: stillFailing,
    alerts,
    alerted: alerts.length > 0,
  };
}

/**
 * D2 重复性一致闸（2026-10-29 上移到 report_lib 作为单一来源）：
 * verdict 同 + 失败态同（settled/error/reasons 集合）+ 分差≤1 → k_pass；任一不满足列 inconsistent。
 * runner 与 rescore 共用，避免同一批报告在两处算出不同的 k_pass。
 */
export function kPassStats(results) {
  const byTask = {};
  for (const r of results) (byTask[r.task] ||= []).push(r);
  let consistent = 0;
  const inconsistent = [];
  for (const [id, rs] of Object.entries(byTask)) {
    if (rs.length < 2) { consistent++; continue; }
    const scores = rs.map((x) => x.score);
    const spread = Math.max(...scores) - Math.min(...scores);
    const verdicts = new Set(rs.map((x) => x.verdict ?? null));
    const states = new Set(rs.map((x) => JSON.stringify([x.settled, x.error ?? null, [...(x.reasons || [])].sort()])));
    const ok = spread <= 1 && verdicts.size <= 1 && states.size <= 1;
    if (ok) consistent++;
    else inconsistent.push(`${id}(分差${spread},verdict${[...verdicts].join('/')})`);
  }
  const total = Object.keys(byTask).length;
  return { k: Math.max(...Object.values(byTask).map((a) => a.length)), k_total: total, k_pass: consistent, k_pass_rate: total ? consistent / total : null, inconsistent };
}

/**
 * Pass@k（2026-10-29）：同题 k 跑里"至少一次通过(≥4)"的题占比。
 * 与 kPassStats 互补：pass@k 高但 k_pass 低 = 这题会做但不稳；两者都低 = 这题真不会。
 * 分母按题去重（不是按行），因此单跑时数值=按题去重通过率，与按行统计的 passCount 口径不同。
 */
export function passAtK(results, passScore = 4) {
  const byTask = {};
  for (const r of results) (byTask[r.task] ||= []).push(r);
  const ids = Object.keys(byTask);
  let hit = 0;
  const missed = [];
  for (const id of ids) {
    if (byTask[id].some((x) => (x.score ?? 0) >= passScore)) hit++;
    else missed.push(id);
  }
  const k = ids.length ? Math.max(...ids.map((id) => byTask[id].length)) : 0;
  return { k, tasks: ids.length, pass: hit, rate: ids.length ? hit / ids.length : null, missed };
}

