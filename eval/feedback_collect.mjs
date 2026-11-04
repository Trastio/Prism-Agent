/**
 * Prism-Agent · 点踩（👎）读取器（轮 2 通道 B，2026-11-01）
 *
 * 背景：ChatView 早已埋 feedback 事件（prism_events.db：event_type='feedback', value='up'|'down'），
 * 但没有消费者，导致"verdict=pass 但用户点踩"这类假阴性抓不到（badcases.md 通道 B 一直空着）。
 *
 * 本脚本把三路数据并成四象限：
 *   ① prism_events.db   feedback（👎/👍）+ chat_settled（pass/fail）事件
 *   ② .pi/sessions/trajectories.jsonl        生产轨迹（verdict/verdict_reason/question）
 *   ③ eval/trajectories/eval-trajectories.jsonl  eval 轨迹（同名结构）
 *
 * 象限口径（badcases.md 同源）：
 *   pass + 👎 = 假阴性（最高价值：规则层没抓住的真坏例）
 *   fail + 👎 = 双确认（次优先）
 *   fail + 无反馈 = 机器自报
 *   pass + 👍   = 正常，不动作
 *
 * 只读不写库；产出 eval/reports/feedback-quadrant.json，供人工裁决用。
 * 运行：node eval/feedback_collect.mjs [--days=90] [--cloud]
 *   --cloud：额外拉取云端生产源（ECS events 库 feedback/chat_settled 行 + 云端生产轨迹
 *   /root/prism/.pi/sessions/trajectories.jsonl），经 deploy/remote.py（凭据 deploy/.sshpass），
 *   落 eval/reports/cloud-sources/ 后与本地源并轨——2026-11-01 上云后生产流量只在云端，
 *   不加此 flag 只能看到本地/eval 流量。
 */

import { DatabaseSync } from 'node:sqlite';
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const EVENTS_DB = resolve(ROOT, 'prism_events.db');
const OUT_DIR = resolve(ROOT, 'eval/reports');
const CLOUD_DIR = resolve(OUT_DIR, 'cloud-sources');
const CLOUD_EVENTS_JSON = resolve(CLOUD_DIR, 'events-cloud.json');
const CLOUD_TRAJ = resolve(CLOUD_DIR, 'traj-cloud.jsonl');
const REMOTE_PY = resolve(ROOT, 'deploy', 'remote.py');
const SSHPASS = resolve(ROOT, 'deploy', '.sshpass');
const USE_CLOUD = process.argv.includes('--cloud');

const daysArg = process.argv.find((a) => a.startsWith('--days='));
const DAYS = daysArg ? Math.max(1, Number(daysArg.split('=')[1]) || 90) : 90;

/** 云端源清单（--cloud 时含云端生产轨迹 + 拉取产物） */
function trajFiles() {
  const files = [
    resolve(ROOT, '.pi/sessions/trajectories.jsonl'),
    resolve(ROOT, 'eval/trajectories/eval-trajectories.jsonl'),
  ];
  if (USE_CLOUD && existsSync(CLOUD_TRAJ)) files.push(CLOUD_TRAJ);
  return files;
}

/** 拉云端两源：events 行（feedback/chat_settled）与生产轨迹。
 *  内嵌 python 走 base64 管道（绕开 Node→cmd→ssh→bash→python3 四层引号）；execFileSync
 *  数组传参不做 shell 转义。凭据从 deploy/.sshpass 读，缺文件即报错退出（不静默降级）。 */
function fetchCloudSources() {
  if (!existsSync(SSHPASS)) {
    console.error('[cloud] 缺 deploy/.sshpass——无法拉取云端源（这是生产流量所在，不静默跳过）');
    process.exit(2);
  }
  const env = { ...process.env, PRISM_SSH_PASS: readFileSync(SSHPASS, 'utf-8').trim() };
  const py = process.platform === 'win32' ? 'python' : 'python3';
  const run = (cmd) => execFileSync(py, [REMOTE_PY, 'exec', cmd], {
    env, encoding: 'utf-8', maxBuffer: 64 * 1024 * 1024, timeout: 120000,
  });
  const inner = [
    "import sqlite3,json",
    "c=sqlite3.connect('/root/prism/data/prism_events.db')",
    "rows=c.execute(\"SELECT event_type,session_id,value,ts FROM events WHERE event_type IN ('feedback','chat_settled') AND session_id IS NOT NULL\").fetchall()",
    "print(json.dumps([{'event_type':r[0],'session_id':r[1],'value':r[2],'ts':r[3]} for r in rows]))",
  ].join(';');
  const b64 = Buffer.from(inner, 'utf-8').toString('base64');
  const evJson = run(`echo ${b64} | base64 -d | python3`);
  const traj = run('cat /root/prism/.pi/sessions/trajectories.jsonl');
  mkdirSync(CLOUD_DIR, { recursive: true });
  writeFileSync(CLOUD_EVENTS_JSON, evJson.trim(), 'utf-8');
  writeFileSync(CLOUD_TRAJ, traj, 'utf-8');
  const n = JSON.parse(evJson.trim()).length;
  console.log(`[cloud] 已拉取：events ${n} 行 · 生产轨迹 ${traj.length} 字节 → ${CLOUD_DIR}`);
}

/** 读轨迹：sessionId → { verdict, verdict_reason, question, ts }（同 session 取最新一条） */
function loadTrajectories() {
  const map = new Map();
  for (const f of trajFiles()) {
    if (!existsSync(f)) continue;
    const lines = readFileSync(f, 'utf-8').split('\n');
    for (const line of lines) {
      if (!line.trim()) continue;
      let o;
      try { o = JSON.parse(line); } catch { continue; }
      const sid = o.sessionId;
      if (!sid) continue;
      const prev = map.get(sid);
      if (!prev || String(o.timestamp ?? '') >= String(prev.ts ?? '')) {
        // 题面取首条 user 消息（系统注入的续跑消息不算题面）
        // 轨迹有两种历史格式：字符串 "user: ..." 与 {role, content} 对象，两种都要兼容
        const conv = Array.isArray(o.conversation) ? o.conversation : [];
        const firstUser = conv.find((m) => {
          if (typeof m === 'string') return m.startsWith('user:') && !m.startsWith('user: [');
          return m?.role === 'user' && !String(m.content ?? '').startsWith('[');
        });
        const question = String(
          typeof firstUser === 'string' ? firstUser.replace(/^user:\s*/, '') : (firstUser?.content ?? ''),
        ).slice(0, 120);
        map.set(sid, {
          verdict: o.verdict ?? null,
          verdict_reason: o.verdict_reason ?? '',
          question,
          ts: o.timestamp ?? '',
        });
      }
    }
  }
  return map;
}

/** 读事件库：feedback + chat_settled（只读打开，缺库返回空）；--cloud 时并入云端行 */
function loadEvents() {
  const since = new Date(Date.now() - DAYS * 86400000).toISOString();
  let feedback = [];
  let settled = [];
  if (existsSync(EVENTS_DB)) {
    const db = new DatabaseSync(EVENTS_DB, { readOnly: true });
    try {
      feedback = db
        .prepare(`SELECT session_id, value, ts FROM events WHERE event_type='feedback' AND session_id IS NOT NULL AND ts >= ? ORDER BY ts DESC`)
        .all(since);
      settled = db
        .prepare(`SELECT session_id, value, ts FROM events WHERE event_type='chat_settled' AND session_id IS NOT NULL AND ts >= ? ORDER BY ts DESC`)
        .all(since);
    } finally {
      db.close();
    }
  }
  if (USE_CLOUD && existsSync(CLOUD_EVENTS_JSON)) {
    const rows = JSON.parse(readFileSync(CLOUD_EVENTS_JSON, 'utf-8'));
    const inWin = (r) => String(r.ts ?? '') >= since;
    feedback = feedback.concat(rows.filter((r) => r.event_type === 'feedback' && inWin(r)));
    settled = settled.concat(rows.filter((r) => r.event_type === 'chat_settled' && inWin(r)));
  }
  return { feedback, settled };
}

function quadrantOf(verdict, feedback) {
  if (feedback === 'down') return verdict === 'pass' ? 'pass_down' : (verdict === 'fail' ? 'fail_down' : 'down_only');
  if (verdict === 'fail') return 'fail_silent';
  return 'normal';
}

const PRIORITY = { pass_down: 1, fail_down: 2, down_only: 3, fail_silent: 4, normal: 9 };

function main() {
  if (USE_CLOUD) fetchCloudSources();
  const traj = loadTrajectories();
  const { feedback, settled } = loadEvents();

  // chat_settled 兜底：轨迹缺失时用它判 verdict
  const settledBySession = new Map();
  for (const e of settled) if (!settledBySession.has(e.session_id)) settledBySession.set(e.session_id, e.value);

  // 同 session 只留最新一条反馈
  const perSession = new Map();
  for (const e of feedback) if (!perSession.has(e.session_id)) perSession.set(e.session_id, e);

  const rows = [];
  for (const [sid, e] of perSession) {
    const t = traj.get(sid) || {};
    const verdict = t.verdict ?? settledBySession.get(sid) ?? null;
    const quadrant = quadrantOf(verdict, e.value);
    rows.push({
      session_id: sid,
      feedback: e.value,
      feedback_ts: e.ts,
      verdict,
      verdict_reason: (t.verdict_reason || '').slice(0, 200),
      question: t.question || '',
      quadrant,
      priority: PRIORITY[quadrant] ?? 9,
    });
  }

  // 机器自报：verdict=fail 且该 session 无点踩
  for (const [sid, t] of traj) {
    if (t.verdict !== 'fail' || perSession.has(sid)) continue;
    // eval 跑次不算"用户流量"，按 evalRunId 前缀跳过（uid 以 eval_ 开头）
    rows.push({
      session_id: sid,
      feedback: null,
      feedback_ts: null,
      verdict: 'fail',
      verdict_reason: (t.verdict_reason || '').slice(0, 200),
      question: t.question || '',
      quadrant: 'fail_silent',
      priority: PRIORITY.fail_silent,
    });
  }

  rows.sort((a, b) => a.priority - b.priority || String(b.feedback_ts ?? '').localeCompare(String(a.feedback_ts ?? '')));

  const counts = rows.reduce((acc, r) => ((acc[r.quadrant] = (acc[r.quadrant] || 0) + 1), acc), {});
  const out = { generated_at: new Date().toISOString(), window_days: DAYS, counts, rows };

  mkdirSync(OUT_DIR, { recursive: true });
  const path = resolve(OUT_DIR, 'feedback-quadrant.json');
  writeFileSync(path, JSON.stringify(out, null, 2), 'utf-8');

  console.log(`[feedback] 窗口 ${DAYS} 天｜feedback 事件 ${feedback.length} 条（去重 session ${perSession.size}）｜chat_settled ${settled.length} 条`);
  console.log(`[feedback] 四象限：${JSON.stringify(counts)}`);
  for (const r of rows.slice(0, 10)) {
    if (r.quadrant === 'normal') continue;
    console.log(`  [${r.quadrant}] ${r.session_id} verdict=${r.verdict} 题=${r.question.slice(0, 30)}`);
  }
  console.log(`[feedback] 已写入 ${path}`);
}

main();
