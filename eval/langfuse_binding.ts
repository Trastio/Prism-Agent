/**
 * Prism-Agent · langfuse 深度绑定（评估迭代 change，2026-10-19，T1）
 *
 * 半绑定→深度绑定三件之两件：题库单向同步（tasks.json → dataset `prism-eval-60`，
 * item=题：input=题面，expectedOutput=金标要点，metadata.taskId=幂等键）+ 批跑 run
 * 链接（dataset-run-items 挂 traceId + task-pass score）。人工判读 CLI 见 annotate.mjs。
 *
 * API 契约（10-19 活栈实测，v4 self-host；两处终态口径与 proposal 初稿不同，以实测为准）：
 * - POST dataset-items 不幂等（重复=两条）→ 先查后建；幂等键 = metadata.taskId（externalId 不回显，弃用）
 * - POST /api/public/scores 关联字段 = datasetRunItemId（值=dataset-run-item 的 id）→ 200 实证；
 *   datasetRunId（run 的 id）会被 400 拒（Step9 活栈冒烟实证，早前转录颠倒已纠）
 * - 凭证绝不进日志/异常消息：错误只带 请求路径+状态码，不带响应体/请求头（红线①）
 *
 * fail-soft 铁律（拍板④）：bindEvalRun 整体 try/catch，任何异常 console.warn 一条
 * 汇总警告后返回 null——绝不让调用方（runner）崩（判据：删掉 langfuse 批跑照常出报告）。
 *
 * 风格对齐 langfuse_writer.ts：ESM、Node≥22 type-strip 直载（.mjs 可直接 import）、
 * 零新依赖、fetch 原生、loadCreds 复刻而非导出改造（writer 已验证路径不动，红线③）。
 */
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const DEFAULT_DATASET = 'prism-eval-60';
const HTTP_TIMEOUT_MS = 15_000;

export interface BindingCreds {
  baseUrl: string;
  publicKey: string;
  secretKey: string;
}

/** 凭证加载（复刻 writer 口径：.pi/agent-minimal/langfuse.json + LANGFUSE_* env 优先）。
 * 缺失/解析失败返回 null；凭证值绝不进异常消息（红线①）。 */
export function loadBindingCreds(): BindingCreds | null {
  // 文件缺失/损坏不连坐 env（Step8 P2-3：原实现 try 包整个读取，文件不在时 env 再全也返回 null）
  let file: any = {};
  try {
    file = JSON.parse(readFileSync(resolve(PROJECT_ROOT, '.pi/agent-minimal/langfuse.json'), 'utf-8'));
  } catch {
    /* 文件缺失 → env-only（单测依赖此路径打桩凭证） */
  }
  const creds: BindingCreds = {
    publicKey: process.env.LANGFUSE_PUBLIC_KEY?.trim() || file.publicKey,
    secretKey: process.env.LANGFUSE_SECRET_KEY?.trim() || file.secretKey,
    baseUrl: process.env.LANGFUSE_BASE_URL?.trim() || file.baseUrl,
  };
  if (!creds.publicKey || !creds.secretKey || !creds.baseUrl) return null;
  return creds;
}

// ── 纯逻辑（零 IO，可单测）────────────────────────────────────────

export interface DatasetItemLike {
  id: string;
  metadata?: Record<string, unknown> | null;
}

export interface EvalTaskLike {
  id: string;
  question?: string;
  [key: string]: unknown;
}

/** 幂等 diff：existing=langfuse 已有 items，tasks=题库题数组；返回需要新建的题。
 * 幂等键 = item.metadata.taskId 与 task.id 匹配；无 metadata（或 taskId 非字符串）
 * 的存量 item 视为不可匹配——不据此跳过任何题。 */
export function diffDatasetItems(existing: DatasetItemLike[], tasks: EvalTaskLike[]): EvalTaskLike[] {
  const seen = new Set<string>();
  for (const item of existing ?? []) {
    const tid = item?.metadata?.taskId;
    if (typeof tid === 'string' && tid) seen.add(tid);
  }
  return (tasks ?? []).filter((t) => !seen.has(t.id));
}

/** 单题 item payload（题面+简短字段 / 金标要点截断 500 防超大 / taskId+group 幂等键）。
 * 及格线字段（pass_line）当前题集不存在→省略；出现时透传进 expectedOutput.pass。 */
export function buildDatasetItemBody(datasetName: string, task: EvalTaskLike) {
  const digest = String(task.judge_rubric || task.expected_evidence || '').slice(0, 500);
  const input: Record<string, unknown> = { question: task.question ?? '' };
  for (const k of ['dimension', 'set', 'as_of', 'trap_type']) {
    if (task[k] != null) input[k] = task[k];
  }
  const expectedOutput: Record<string, unknown> = { golden_digest: digest };
  if (task.pass_line != null) expectedOutput.pass = task.pass_line;
  return {
    datasetName,
    input,
    expectedOutput,
    metadata: { taskId: task.id, group: (task.set as string) ?? null },
  };
}

// ── HTTP 助手（统一 Basic auth + 15s 超时；错误只带 路径+状态码，不含凭证）──

function basicAuth(creds: BindingCreds): string {
  // 实测：本路由 Bearer sk → 401，须 Basic pk:sk（与 writer 同口径）
  return 'Basic ' + Buffer.from(`${creds.publicKey}:${creds.secretKey}`).toString('base64');
}

async function getJson(creds: BindingCreds, path: string): Promise<any> {
  const res = await fetch(`${creds.baseUrl}${path}`, {
    headers: { Authorization: basicAuth(creds) },
    signal: AbortSignal.timeout(HTTP_TIMEOUT_MS),
  });
  if (!(res.status >= 200 && res.status < 300)) throw new Error(`langfuse GET ${path} HTTP ${res.status}`);
  // Step8 P1：200 但非 JSON 对象时必须抛（原 .catch(()=>null) 会静默当"空库"→全量 POST→item 翻倍不可恢复）
  const json = await res.json().catch(() => null);
  if (json === null || typeof json !== 'object') throw new Error(`langfuse GET ${path} 响应非 JSON`);
  return json;
}

async function postJson(creds: BindingCreds, path: string, body: unknown): Promise<any> {
  const res = await fetch(`${creds.baseUrl}${path}`, {
    method: 'POST',
    headers: { Authorization: basicAuth(creds), 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(HTTP_TIMEOUT_MS),
  });
  if (!(res.status >= 200 && res.status < 300)) throw new Error(`langfuse POST ${path} HTTP ${res.status}`);
  return res.json().catch(() => null);
}

async function requireCreds(): Promise<BindingCreds> {
  const creds = loadBindingCreds();
  if (!creds) throw new Error('langfuse 凭证缺失（.pi/agent-minimal/langfuse.json 或 LANGFUSE_* env）');
  return creds;
}

/** 列 dataset 全量 items（page/limit=50 循环到 meta.totalPages；>100 页熔断防呆）。 */
async function listDatasetItems(creds: BindingCreds, datasetName: string): Promise<DatasetItemLike[]> {
  const items: DatasetItemLike[] = [];
  let page = 1;
  let totalPages = 1;
  let guard = 0;
  do {
    const r = await getJson(
      creds,
      `/api/public/dataset-items?datasetName=${encodeURIComponent(datasetName)}&page=${page}&limit=50`,
    );
    // Step8 P1：结构校验 fail-loud（data 非数组/totalPages 非数字 = 响应形状异常，宁拒不猜）
    if (!Array.isArray(r?.data) || !r?.meta || typeof r.meta.totalPages !== 'number') {
      throw new Error('dataset-items 响应结构异常（data/meta.totalPages 缺失）');
    }
    items.push(...r.data);
    totalPages = r.meta.totalPages;
    page++;
  } while (page <= totalPages && ++guard < 100);
  return items;
}

// ── 对外能力 ───────────────────────────────────────────────────────

export interface SyncSummary {
  datasetName: string;
  created: number;
  skipped: number; // 已存在（taskId 匹配）未重建
  failed: string[]; // 单题失败（taskId+原因），失败继续其余
}

/** 题库→dataset 单向同步：dataset 先查后建（v4 重复 POST=两条）→ 翻页列 items →
 * diffDatasetItems 算缺 → 逐题建（单题失败记 failed 继续）。凭证/网络级错误会抛，
 * 由 bindEvalRun fail-soft 兜底。 */
export async function syncDatasetItems(
  tasks: EvalTaskLike[],
  opts: { datasetName?: string } = {},
): Promise<SyncSummary> {
  const datasetName = opts.datasetName ?? DEFAULT_DATASET;
  const creds = await requireCreds();
  const list = await getJson(creds, '/api/public/datasets?limit=50');
  if (!Array.isArray(list?.data)) throw new Error('datasets 响应结构异常（data 缺失）');
  const found = list.data.some((d: any) => d?.name === datasetName);
  if (!found) await postJson(creds, '/api/public/datasets', { name: datasetName });
  const existing = await listDatasetItems(creds, datasetName);
  const missing = diffDatasetItems(existing, tasks ?? []);
  let created = 0;
  const failed: string[] = [];
  for (const task of missing) {
    try {
      await postJson(creds, '/api/public/dataset-items', buildDatasetItemBody(datasetName, task));
      created++;
    } catch (e) {
      failed.push(`${task.id}: ${(e as Error)?.message ?? e}`);
    }
  }
  return { datasetName, created, skipped: (tasks ?? []).length - missing.length, failed };
}

export interface RunResult {
  taskId: string;
  traceId?: string | null;
  pass: boolean;
}

export interface LinkSummary {
  linked: number;
  failed: string[];
  skippedNoTrace: number; // traceId 为空跳过并计数（当前 runner 未存 per-task traceId）
}

/** run 链接：taskId→item.id 映射 → 每题 dataset-run-item（挂 traceId）+ task-pass score。
 * - run 按 runName 归并（同 runName 同 datasetRunId，实测）；同 taskId 多条（--repeat）
 *   去重取最后一条——每 run 每题只建一次（proposal 契约）
 * - traceId 由 runner 补存（多轮评估批 change T4：lookupTraceId 按 sessionId 查 CH）；
 *   为空的条目跳过并计数（CH 不可达批次的可接受降级）
 * - score 关联字段实测名 = datasetRunItemId（值=run-item 的 id）→ 200；datasetRunId → 400 被拒
 *   （10-20 深度绑定 Step9 活栈纠错——早前探针结论转录颠倒，mock 曾随错契约假绿）*/
export async function linkRun(
  runName: string,
  results: RunResult[],
  opts: { datasetName?: string } = {},
): Promise<LinkSummary> {
  const datasetName = opts.datasetName ?? DEFAULT_DATASET;
  const creds = await requireCreds();
  const items = await listDatasetItems(creds, datasetName);
  const idByTask = new Map<string, string>();
  for (const it of items) {
    const tid = it?.metadata?.taskId;
    if (typeof tid === 'string' && tid) idByTask.set(tid, it.id);
  }
  const dedup = new Map<string, RunResult>();
  for (const r of results ?? []) dedup.set(r.taskId, r);
  let linked = 0;
  let skippedNoTrace = 0;
  const failed: string[] = [];
  for (const r of dedup.values()) {
    const itemId = idByTask.get(r.taskId);
    if (!itemId) {
      failed.push(`${r.taskId}: dataset item 不存在（先 syncDatasetItems）`);
      continue;
    }
    if (!r.traceId) {
      skippedNoTrace++;
      continue;
    }
    try {
      const runItem = await postJson(creds, '/api/public/dataset-run-items', {
        runName,
        datasetItemId: itemId,
        traceId: r.traceId,
      });
      // Step9 活栈冒烟纠错：score 关联字段实测 = datasetRunItemId（值=run-item 的 id）→ 200；
      // datasetRunId（值=run 的 id）→ 400 被拒。早前探针结论转录颠倒，mock 测试随错契约假绿。
      if (!runItem?.id) throw new Error('响应缺 run-item id');
      await postScoreWith(creds, {
        id: runScoreId(runName, r.taskId, 'task-pass'), // 幂等 upsert：同 run 同题只留一条
        name: 'task-pass',
        value: r.pass ? 1 : 0,
        traceId: r.traceId,
        datasetRunItemId: runItem.id,
        comment: 'auto: prism eval run',
        environment: 'eval',
      });
      linked++;
    } catch (e) {
      failed.push(`${r.taskId}: ${(e as Error)?.message ?? e}`);
    }
  }
  return { linked, failed, skippedNoTrace };
}

/** score 写入（linkRun 与 annotate.mjs 共用）：dataType 固定 NUMERIC，返回 score id。 */
export async function postScore(body: {
  name: string;
  value: number;
  traceId: string;
  comment?: string;
  datasetRunItemId?: string;
}): Promise<string | null> {
  const creds = await requireCreds();
  return postScoreWith(creds, body);
}

async function postScoreWith(
  creds: BindingCreds,
  body: {
    name: string; value: number; traceId: string; comment?: string;
    datasetRunItemId?: string; id?: string; environment?: string;
  },
): Promise<string | null> {
  const r = await postJson(creds, '/api/public/scores', { dataType: 'NUMERIC', ...body });
  return r?.id ?? null;
}

/** run 内评分幂等键：runName+题+分数名 → 稳定哈希（重跑补写不堆重复） */
function runScoreId(runName: string, taskId: string, name: string): string {
  return 'ev-' + createHash('sha256').update(`${runName}|${taskId}|${name}`).digest('hex').slice(0, 32);
}

export interface BindSummary {
  sync: SyncSummary;
  link: LinkSummary;
}

/** fail-soft 总出口（runner 挂接点）：syncDatasetItems + linkRun 组合；任何异常
 * console.warn 一条汇总警告后返回 null——绝不让调用方（runner）崩（拍板④）。 */
export async function bindEvalRun(
  tasks: EvalTaskLike[],
  runName: string,
  results: RunResult[],
  opts: { datasetName?: string } = {},
): Promise<BindSummary | null> {
  try {
    const sync = await syncDatasetItems(tasks, opts);
    const link = await linkRun(runName, results, opts);
    return { sync, link };
  } catch (e) {
    console.warn(`[langfuse_binding] 绑定降级（不阻塞评估）: ${(e as Error)?.message ?? e}`);
    return null;
  }
}
