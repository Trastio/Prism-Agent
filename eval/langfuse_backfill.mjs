/**
 * Langfuse 回填：把已有评估报告灌进自托管 Langfuse v4（不重跑 agent，零 LLM 成本）
 *
 * 背景：①本批跑进程启动时凭证未就位，loadCreds() 返回 null，写入被静默跳过；
 *      ②Langfuse v4 默认 LANGFUSE_MIGRATION_V4_WRITE_MODE=events_only，/api/public/ingestion 只收 score，
 *        trace 必须走 OTLP（/api/public/otel/v1/traces）。
 * 因此：trace 用 OTLP 写（每题每跑一个 span，traceId 即 Langfuse trace id），score 再用 ingestion 关联同一 traceId。
 *
 * 用法：node eval/langfuse_backfill.mjs [report.json]   （缺省取 eval/reports 最新含 results 的报告）
 * 凭证：.pi/agent-minimal/langfuse.json（baseUrl/publicKey/secretKey），env LANGFUSE_* 优先
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function loadCreds() {
  const env = {
    baseUrl: process.env.LANGFUSE_BASE_URL || process.env.LANGFUSE_HOST,
    publicKey: process.env.LANGFUSE_PUBLIC_KEY,
    secretKey: process.env.LANGFUSE_SECRET_KEY,
  };
  if (env.baseUrl && env.publicKey && env.secretKey) return env;
  try {
    const f = JSON.parse(readFileSync(resolve(ROOT, '.pi/agent-minimal/langfuse.json'), 'utf-8'));
    return { baseUrl: f.baseUrl, publicKey: f.publicKey, secretKey: f.secretKey };
  } catch {
    return null;
  }
}

function latestReport() {
  const dir = resolve(ROOT, 'eval/reports');
  return readdirSync(dir)
    .filter((f) => /^eval-.*\.json$/.test(f) && !f.includes('.rescored') && !f.includes('.manifest'))
    .map((f) => ({ f, m: statSync(join(dir, f)).mtimeMs }))
    .sort((a, b) => b.m - a.m)
    .map((x) => join(dir, x.f))
    .find((p) => {
      try { return Array.isArray(JSON.parse(readFileSync(p, 'utf-8')).results); } catch { return false; }
    });
}

const hex = (s, n) => createHash('sha256').update(s).digest('hex').slice(0, n);
const attr = (k, v) => ({ key: k, value: { stringValue: String(v ?? '') } });

/** 一行结果 → 一个 OTLP span（traceId 稳定：run+task+repeat，重跑不堆叠） */
function rowToSpan(r, runId, seq) {
  const traceId = hex(`${runId}:${r.task}:r${r.repeat ?? 1}`, 32);
  const spanId = hex(`span:${traceId}`, 16);
  const t = Date.now() + seq * 1000; // 轻微错开，避免同毫秒排序抖动
  const reply = String(r.reply_full || r.replyPreview || '');
  const attrs = [
    attr('langfuse.trace.name', r.task),
    attr('langfuse.session.id', `${runId}:${r.task}`),
    attr('langfuse.observation.type', 'span'),
    attr('langfuse.observation.input', r.question || ''),
    attr('langfuse.observation.output', reply),
    // 归因所需明细：判分链 / 工具 / 状态，全进 metadata，UI 里点开即可看
    attr('langfuse.trace.metadata', JSON.stringify({
      dimension: r.dimension ?? null,
      score: r.score ?? null,
      reasons: r.reasons || [],
      deduction_steps: r.deduction_trace?.steps || [],
      tools: r.tools || [],
      tool_calls: (r.tools || []).length,
      settled: r.settled ?? null,
      verdict: r.verdict ?? null,
      repeat: r.repeat ?? 1,
      valid: r.valid !== false,
      first_error_turn: r.first_error_turn ?? null,
      reply_length: r.replyLength ?? reply.length,
      tokens: r.cost?.tokens?.totalTokens ?? null,
      snapshot_id: runId && null,
    })),
    attr('langfuse.trace.tags', JSON.stringify([`run:${runId}`, `dim:${r.dimension || 'unknown'}`])),
  ];
  return {
    traceId, spanId, name: String(r.task), kind: 1,
    startTimeUnixNano: String(t * 1e6),
    endTimeUnixNano: String((t + 1) * 1e6),
    attributes: attrs,
  };
}

async function main() {
  const creds = loadCreds();
  if (!creds) {
    console.error('未找到 Langfuse 凭证（.pi/agent-minimal/langfuse.json 或 LANGFUSE_* env）');
    process.exit(1);
  }
  const reportPath = process.argv[2] ? resolve(process.argv[2]) : latestReport();
  if (!reportPath) throw new Error('找不到含 results 的报告');
  const report = JSON.parse(readFileSync(reportPath, 'utf-8'));
  const runId = report.run_id || 'eval';
  const rows = report.results || [];
  const base = creds.baseUrl.replace(/\/$/, '');
  const auth = 'Basic ' + Buffer.from(`${creds.publicKey}:${creds.secretKey}`).toString('base64');
  console.log(`报告 ${reportPath}\nrun_id ${runId}｜${rows.length} 行 → ${base}`);

  const spans = rows.map((r, i) => rowToSpan(r, runId, i));

  // ① trace 走 OTLP（每批 100 span）
  let okTrace = 0, failTrace = 0;
  for (let i = 0; i < spans.length; i += 100) {
    const part = spans.slice(i, i + 100);
    const body = {
      resourceSpans: [{
        resource: { attributes: [attr('service.name', 'prism-eval'), attr('deployment.environment', 'eval')] },
        scopeSpans: [{ scope: { name: 'prism.eval' }, spans: part }],
      }],
    };
    const res = await fetch(`${base}/api/public/otel/v1/traces`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: auth }, body: JSON.stringify(body),
    });
    const text = await res.text();
    if (!res.ok) { failTrace += part.length; console.error(`trace 批次 ${i / 100 + 1} 失败 HTTP ${res.status}: ${text.slice(0, 200)}`); }
    else okTrace += part.length;
  }

  // ② score 走 ingestion（v4 events_only 只收 score 事件）
  let okScore = 0, failScore = 0;
  const scoreEvents = [];
  rows.forEach((r, i) => {
    if (typeof r.score !== 'number' || r.valid === false) return;
    const traceId = spans[i].traceId;
    scoreEvents.push({
      id: `sc-${i}`,
      type: 'score-create',
      timestamp: new Date(Date.now() + i * 1000).toISOString(),
      body: { id: `${traceId}:score`, traceId, name: 'eval_score', value: r.score, comment: (r.reasons || []).join('；') || '通过' },
    });
  });
  for (let i = 0; i < scoreEvents.length; i += 200) {
    const part = scoreEvents.slice(i, i + 200);
    const res = await fetch(`${base}/api/public/ingestion`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: auth }, body: JSON.stringify({ batch: part }),
    });
    const text = await res.text();
    let errs = [];
    try { errs = JSON.parse(text).errors || []; } catch {}
    if (!res.ok || errs.length) { failScore += errs.length || part.length; console.error(`score 批次 ${i / 200 + 1}: ${text.slice(0, 200)}`); }
    else okScore += part.length;
  }

  console.log(`trace(OTLP) 成功 ${okTrace} / 失败 ${failTrace}｜score(ingestion) 成功 ${okScore} / 失败 ${failScore}`);
  console.log('数据由 worker 异步落库，约 10-30 秒后可在 UI 看到');
  if (failTrace || failScore) process.exitCode = 1;
}

main();
