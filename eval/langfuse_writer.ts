/**
 * Prism-Agent · langfuse 评估闭环（T-2.4.7 → 评估迭代基建包 A3 真实现）
 *
 * 已核实：@langfuse/pi-observability-plugin@0.1.2 hook tool_execution_start/end，
 * 自建工具全覆盖（OTLP trace 自动入库）。本模块负责把评估分数写回该题 trace。
 *
 * 实现口径（design Block A，2026-10-14 联调实测修正）：
 * - score 摄入：POST ${baseUrl}/api/public/scores，Basic pk:sk → 200 {id} 实证。
 *   （设计稿写的 legacy/score 在本部署 v4.50.0 events_only 下路由不存在——HTML 404；
 *   /api/public/traces 查询 API 同被 events_only 封锁。）
 * - traceId 解析：改查本机 ClickHouse events_core（langfuse.json 配 clickhouseUrl，
 *   按 sessionId 取最新 trace_id；容忍 OTLP 批量导出延迟，短重试）。
 * 失败仅 console.warn 不抛——观测降级不阻塞判分（红线：判分主链优先）。
 */

import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

export interface EvalTraceFields {
  eval_run_id: string;
  task_id: string;
  score: number;            // 六分制
  failure_dimensions: string[];   // 失败维度
  cost: {
    input_tokens: number;
    output_tokens: number;
    cache_hit: number;
    elapsed_ms: number;
  };
  trap_blocked: boolean;     // trap 是否被否决
  name_grounding_triggered: boolean;
  scope_overreach_blocked: boolean;
  // A3/A4 增补（可选字段，既有调用方不受影响）：
  traceId?: string;          // 缺省时按 sessionId 查 langfuse 最新 trace
  sessionId?: string;        // pi 会话 id（插件 trace 的 sessionId 属性）
  repeat?: number;           // --repeat 第几跑（幂等 id 的组成部分；缺省 1）
  set?: string;
  judge_rubric?: string;              // 题集标签（dev/frozen）
  snapshot_id?: string;      // 评测快照指纹
  environment?: string;      // G4 实例标签：production | eval（缺省读 LANGFUSE_TRACING_ENVIRONMENT，再缺省 eval）
  // 归因工具包（2026-10-16）：判分结果明细随 score 入 langfuse——单界面看"缺了什么"，不切本地文件
  truth_missing?: string[];         // truth 缺的锚（数字/形态）
  truth_forbid_hits?: string[];     // truth 违禁命中
  rubric_missing?: string[];        // rubric 缺的要素（如候选车名）
  first_error_turn?: number | null; // 首错轮（多轮题；单轮失败=1；通过/timeout=null）
}

/** 凭证：与插件同源（.pi/agent-minimal/langfuse.json；LANGFUSE_* env 优先，插件 README 口径）。
 * events_only 部署 traceId 只能查 ClickHouse → clickhouseUrl/User/Password 同放此文件（gitignored）。 */
interface LangfuseCreds {
  baseUrl: string;
  secretKey: string;
  publicKey: string;
  clickhouseUrl?: string;
  clickhouseAuth?: string; // "user:password"
}

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

function loadCreds(): LangfuseCreds | null {
  try {
    const file = JSON.parse(readFileSync(resolve(PROJECT_ROOT, '.pi/agent-minimal/langfuse.json'), 'utf-8'));
    return {
      publicKey: process.env.LANGFUSE_PUBLIC_KEY?.trim() || file.publicKey,
      secretKey: process.env.LANGFUSE_SECRET_KEY?.trim() || file.secretKey,
      baseUrl: process.env.LANGFUSE_BASE_URL?.trim() || file.baseUrl,
      clickhouseUrl: process.env.LANGFUSE_CLICKHOUSE_URL?.trim() || file.clickhouseUrl,
      clickhouseAuth: process.env.LANGFUSE_CLICKHOUSE_AUTH?.trim() || file.clickhouseAuth,
    };
  } catch { return null; }
}

/** events_only 封锁 /api/public/traces → 直查 ClickHouse events_core 按 sessionId 取最新 trace_id。
 * OTLP 批量导出有延迟——短重试（1s/2s/4s）后放弃（warn 不抛）。 */
async function resolveTraceId(creds: LangfuseCreds, sessionId?: string): Promise<string | null> {
  if (!sessionId || !creds.clickhouseUrl || !creds.clickhouseAuth) return null;
  const sql = `SELECT trace_id FROM events_core WHERE session_id = '${sessionId.replace(/'/g, "''")}' ORDER BY start_time DESC LIMIT 1`;
  const auth = 'Basic ' + Buffer.from(creds.clickhouseAuth).toString('base64');
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const res = await fetch(`${creds.clickhouseUrl}/?query=${encodeURIComponent(sql)}`, {
        headers: { Authorization: auth },
        signal: AbortSignal.timeout(5000),
      });
      if (res.ok) {
        const hit = (await res.text()).trim();
        if (hit) return hit;
      }
    } catch { /* 下轮重试 */ }
    await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
  }
  return null;
}

/**
 * 写回 langfuse trace（评分挂 traceId + eval 元数据）。
 * 同步签名（void）不变：内部 fire-and-forget，任何失败 console.warn 不抛——
 * 观测降级不阻塞判分。
 */
export function writeEvalTrace(fields: EvalTraceFields): void {
  postEvalScore(fields).catch((e) =>
    console.warn('[langfuse_writer] 观测降级（不阻塞判分）:', (e as Error)?.message ?? e));
}

/**
 * 多轮评估批 change（T4）：按 sessionId 查最新 trace_id——供 runner 补存 per-task traceId
 * （深度绑定 linkRun 挂链用）。纯新增导出：resolveTraceId 内部路径零改动。
 * fail-soft：无凭据/CH 不可达/超时重试耗尽 → null（调用方跳过计数，不抛）。
 */
export async function lookupTraceId(sessionId?: string): Promise<string | null> {
  try {
    const creds = loadCreds();
    if (!creds) return null;
    return await resolveTraceId(creds, sessionId);
  } catch {
    return null;
  }
}

/** 幂等 score id：run+题+第几跑 → 稳定哈希。
 * 同一批重跑/补写会 upsert 同一条，而不是再堆一条（历史 3 倍重复的根因之一）。 */
export function scoreIdFor(runId: string, taskId: string, repeat = 1): string {
  return 'ev-' + createHash('sha256').update(`${runId}|${taskId}|${repeat}|eval-score`).digest('hex').slice(0, 32);
}

async function postEvalScore(fields: EvalTraceFields): Promise<void> {
  const creds = loadCreds();
  if (!creds?.secretKey || !creds.baseUrl) throw new Error('langfuse 凭证缺失（.pi/agent-minimal/langfuse.json 或 LANGFUSE_* env）');
  const traceId = fields.traceId ?? await resolveTraceId(creds, fields.sessionId);
  if (!traceId) throw new Error(`无法定位 traceId（sessionId=${fields.sessionId ?? '未提供'}；查 langfuse.json clickhouseUrl 配置或 OTLP 落库延迟）`);
  const environment = fields.environment ?? process.env.LANGFUSE_TRACING_ENVIRONMENT ?? 'eval';
  const res = await fetch(`${creds.baseUrl}/api/public/scores`, {
    method: 'POST',
    headers: {
      // 实测：本路由 Bearer sk → 401 invalid public key，须 Basic pk:sk
      Authorization: 'Basic ' + Buffer.from(`${creds.publicKey}:${creds.secretKey}`).toString('base64'),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      id: scoreIdFor(fields.eval_run_id, fields.task_id, fields.repeat ?? 1), // 幂等 upsert
      traceId,
      name: 'eval-score',
      value: fields.score,
      dataTypes: ['NUMERIC'],
      environment, // 顶层字段才进 scores.environment（只放 metadata 会一直是 default）
      comment: fields.failure_dimensions.join('; ').slice(0, 500) || 'no failure dimensions',
      metadata: {
        eval_run_id: fields.eval_run_id,
        task_id: fields.task_id,
        set: fields.set ?? '',
        snapshot_id: fields.snapshot_id ?? '',
        environment: fields.environment ?? process.env.LANGFUSE_TRACING_ENVIRONMENT ?? 'eval',
        judge_rubric: fields.judge_rubric ?? '',
        // 归因工具包：判分明细（缺省空数组——旧调用方不受影响）
        truth_missing: fields.truth_missing ?? [],
        truth_forbid_hits: fields.truth_forbid_hits ?? [],
        rubric_missing: fields.rubric_missing ?? [],
        first_error_turn: fields.first_error_turn ?? null,
      },
    }),
    signal: AbortSignal.timeout(10000),
  });
  if (res.status !== 201 && res.status !== 200) {
    throw new Error(`api/public/scores HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
  }
}

/** 批跑后聚合 trace 查询（用 langfuse dashboard 或 API） */
export interface EvalRunSummary {
  eval_run_id: string;
  total_tasks: number;
  pass_rate: number;
  trap_block_rate: number;
  avg_score: number;
  failure_dim_distribution: Record<string, number>;
  total_cost: EvalTraceFields['cost'];
}

