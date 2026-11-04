/**
 * challenger-b1 · 取代性实验 B 系列（评估方案 §10.2）挑战者扩展
 *
 * 形态：零 hook，仅注册两个工具——
 * - run_sql(sql, db?)：快照库只读查询（mode=ro URI + readOnly 选项 + query_only PRAGMA 三重只读门；
 *   仅允许单条 SELECT/WITH；结果 JSON 序列化超 20KB 自截断并附截断标记）
 * - read_file(path)：白名单仅本扩展目录下的 SKILL-A.md / SKILL-B.md / schema.sql（相对名，其余一律拒）
 *
 * 布防守卫（关键）：本扩展放在 .pi/extensions/challenger-b1/ 会被 pi 自动发现（docs/extensions.md
 * "Extension Locations"），A 系列/生产网关 spawn 的 pi 进程也会加载本文件——故工厂函数必须
 * PRISM_CHALLENGER=1 才注册工具，否则 no-op 退出。缺 env 时对默认路径零行为变化
 * （不注册任何工具、不订阅任何事件），A 系列工具面不受污染。
 *
 * sqlite 访问：优先 node:sqlite 内置模块；**注意（审查 Step8 校正）：本机 pi.exe=Bun 1.3.14 实测
 * 无 node:sqlite——pi 进程内实际走 spawn 系统 node 兜底通道（该链路已单测实证可用），Node 环境直跑
 * 测试时才命中 node:sqlite 主路径。（prism-guardrails 禁 better-sqlite3 的原因仍是 NAPI panic）；
 * "20KB 截断"按字符数计（2004*1024 → 20*1024 chars），非字节数。
 * 导入失败时兜底 spawn 系统 node 执行同款只读查询（SQL 经 env 传递，无命令行注入面）。
 *
 * 快照缺省 eval/snapshots/snap-20261012-1222（判分同快照）；PRISM_CHALLENGER_DB 可换 autohome 库路径，
 * sentiment 库恒取同目录 vehicle_sentiment.db（两库同快照成对）。
 */

import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

const EXT_DIR = dirname(fileURLToPath(import.meta.url));

/** 结果自截断上限（工单口径：JSON 序列化超 20KB 截断 + 截断标记） */
export const MAX_RESULT_CHARS = 20 * 1024;
/** read_file 内容上限（SKILL-B ~数十 KB / schema.sql ~11KB；超限截断附标记） */
const MAX_FILE_CHARS = 100 * 1024;
/** read_file 白名单：仅本扩展目录下三个相对名（挑战者臂物料 + 库结构） */
export const READ_FILE_WHITELIST = ['SKILL-A.md', 'SKILL-B.md', 'schema.sql'] as const;

/** 库路径解析（纯函数，供单测）：缺省主库=冻结快照 autohome.db，舆情库=同目录 vehicle_sentiment.db */
export function resolveDbPaths(env: Record<string, string | undefined> = process.env, cwd = process.cwd()) {
  const autohome = env.PRISM_CHALLENGER_DB || resolve(cwd, 'eval/snapshots/snap-20261012-1222/autohome.db');
  const sentiment = resolve(dirname(autohome), 'vehicle_sentiment.db');
  return { autohome, sentiment };
}

/**
 * 只读门（纯函数，供单测）：仅放行单条 SELECT/WITH 开头的语句。
 * - 剥离行注释/块注释后判首词；EXPLAIN/PRAGMA/ATTACH 等一律拒（schema 已由 schema.sql 提供）
 * - 拒绝多语句（除结尾单分号外出现 ';' 即拒——防 ';DROP' 链）
 * - 写操作词出现在首词即拒；深层防线由 ro 库 + query_only 兜底（即使绕过本层也写不进去）
 */
export function validateSql(sql: string): { ok: boolean; reason?: string } {
  const raw = String(sql ?? '');
  if (!raw.trim()) return { ok: false, reason: 'sql 为空' };
  // 剥块注释与行注释（只影响首词判定与分号扫描，不改语义）
  const stripped = raw
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/--[^\n]*/g, ' ')
    .trim();
  const first = (stripped.match(/^[a-zA-Z]+/) || [''])[0].toUpperCase();
  if (first !== 'SELECT' && first !== 'WITH') {
    return { ok: false, reason: `只读工具：仅允许 SELECT/WITH 查询（收到首词 ${first || '(空)'}）。写操作/DDL/PRAGMA/ATTACH 一律拒绝。` };
  }
  const body = stripped.replace(/;\s*$/, '');
  if (body.includes(';')) {
    return { ok: false, reason: '只允许单条语句（检测到多语句）；请拆成多次 run_sql 调用' };
  }
  return { ok: true };
}

/** 序列化 + 20KB 自截断（纯函数，供单测）：超限截断并附标记（原长度/截断标志就地可辨） */
export function serializeResult(payload: unknown): { text: string; truncated: boolean; originalChars: number } {
  const s = JSON.stringify(payload);
  if (s.length <= MAX_RESULT_CHARS) return { text: s, truncated: false, originalChars: s.length };
  const cut = s.slice(0, MAX_RESULT_CHARS);
  const marker = `\n{"_truncated": true, "note": "结果超 ${MAX_RESULT_CHARS} 字符已自截断（原 ${s.length} 字符）；请加 WHERE/LIMIT/聚合缩小结果集后重查", "original_chars": ${s.length}}`;
  return { text: cut + marker, truncated: true, originalChars: s.length };
}

/** file: URI（Windows 反斜杠归一 + mode=ro） */
function roUri(dbPath: string): string {
  return `file:${dbPath.replace(/\\/g, '/')}?mode=ro`;
}

/** node:sqlite DatabaseSync 类型（内置模块，动态导入以容错 pi.exe 缺实现） */
type RoDb = {
  exec: (sql: string) => void;
  prepare: (sql: string) => { all: () => Array<Record<string, unknown>> };
  close: () => void;
};
let sqliteMod: { DatabaseSync: new (path: string, opts?: { readOnly?: boolean }) => RoDb } | null | undefined;

/** 打开只读库（三重门：mode=ro URI + readOnly 选项 + query_only PRAGMA） */
export async function openReadOnly(dbPath: string): Promise<RoDb> {
  if (sqliteMod === undefined) {
    try { sqliteMod = await import('node:sqlite' as string) as typeof sqliteMod; }
    catch { sqliteMod = null; }
  }
  if (!sqliteMod) throw new Error('node:sqlite 不可用（宿主运行时未实现内置 sqlite 模块）');
  const db = new sqliteMod.DatabaseSync(roUri(dbPath), { readOnly: true });
  db.exec('PRAGMA query_only = ON');
  return db;
}

/**
 * 执行只读查询（单条 SELECT/WITH）。返回 {rows} 或 {error}——不抛出（工具结果语义化，模型可自救）。
 * node:sqlite 缺失时兜底 spawn 系统 node：SQL 经 env PRISM_CHALLENGER_SQL 传递（无 shell/argv 注入面），
 * stdout 输出 JSON。
 */
export async function executeSql(dbPath: string, sql: string): Promise<{ rows?: Array<Record<string, unknown>>; error?: string }> {
  const v = validateSql(sql);
  if (!v.ok) return { error: v.reason };
  try {
    const db = await openReadOnly(dbPath);
    try {
      const rows = db.prepare(sql).all().map((r) => ({ ...r })); // null-prototype → 普通对象（JSON 序列化稳定）
      return { rows };
    } finally { db.close(); }
  } catch (e) {
    // node:sqlite 缺实现 → 系统 node 兜底（同款三重只读门在子进程内生效）
    if (/node:sqlite/.test(String((e as Error).message))) return executeSqlViaNode(dbPath, sql);
    return { error: `SQL 执行失败（只读库）: ${(e as Error).message}` };
  }
}

const HELPER_SRC = [
  "const m = await import('node:sqlite');",
  "const db = new m.DatabaseSync(process.env.PRISM_CHALLENGER_DB_URI, { readOnly: true });",
  "db.exec('PRAGMA query_only = ON');",
  "try {",
  "  const rows = db.prepare(process.env.PRISM_CHALLENGER_SQL).all().map((r) => ({ ...r }));",
  "  process.stdout.write(JSON.stringify({ rows }));",
  "} finally { db.close(); }",
].join('\n');

/** 系统 node 兜底通道（同款校验已在上层做过；此处再受 ro URI + query_only 双门约束） */
function executeSqlViaNode(dbPath: string, sql: string): Promise<{ rows?: Array<Record<string, unknown>>; error?: string }> {
  return new Promise((done) => {
    let out = '', err = '';
    // 恒用 PATH 上的 node（本兜底只在 pi.exe 宿主触发，此时 execPath=pi.exe 不可用）
    const child = spawn('node', ['-e', HELPER_SRC], {
      env: { ...process.env, PRISM_CHALLENGER_DB_URI: roUri(dbPath), PRISM_CHALLENGER_SQL: sql },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const timer = setTimeout(() => { child.kill(); done({ error: '查询超时（15s）——请缩小结果集' }); }, 15_000);
    child.stdout.on('data', (d) => (out += d));
    child.stderr.on('data', (d) => (err += d));
    child.on('error', () => { clearTimeout(timer); done({ error: 'node 兜底进程启动失败：请确认 PATH 有 node≥22' }); });
    child.on('close', () => {
      clearTimeout(timer);
      if (out) { try { done(JSON.parse(out)); } catch { done({ error: '兜底输出不可解析' }); } }
      else done({ error: `node 兜底失败: ${err.slice(0, 300)}` });
    });
  });
}

/** read_file 白名单解析（纯函数，供单测）：只收三个相对名；任何路径分量/绝对路径/大小写变体一律拒 */
export function resolveWhitelisted(name: string, extDir = EXT_DIR): { ok: boolean; path?: string; reason?: string } {
  const raw = String(name ?? '').trim().replace(/^@/, '').replace(/^\.\//, '');
  if (!raw) return { ok: false, reason: 'path 为空' };
  if (raw.includes('/') || raw.includes('\\') || raw.includes('..')) {
    return { ok: false, reason: `path 只接受白名单相对名（${READ_FILE_WHITELIST.join('/')}），禁止任何路径分量` };
  }
  if (!(READ_FILE_WHITELIST as readonly string[]).includes(raw)) {
    return { ok: false, reason: `path 不在白名单：${raw}（仅 ${READ_FILE_WHITELIST.join('/')}）` };
  }
  return { ok: true, path: resolve(extDir, raw) };
}

/** 读白名单文件（超 100KB 截断附标记） */
export function readWhitelisted(name: string, extDir = EXT_DIR): { text: string; truncated?: boolean } | { error: string } {
  const w = resolveWhitelisted(name, extDir);
  if (!w.ok) return { error: w.reason! };
  try {
    const content = readFileSync(w.path!, 'utf-8');
    if (content.length <= MAX_FILE_CHARS) return { text: content };
    return {
      text: content.slice(0, MAX_FILE_CHARS) + `\n[截断] 文件超 ${MAX_FILE_CHARS} 字符（原 ${content.length}）`,
      truncated: true,
    };
  } catch (e) {
    return { error: `读取失败: ${(e as Error).message}` };
  }
}

// ---------------------------------------------------------------------------
// Extension 工厂（PRISM_CHALLENGER=1 才布防；否则 no-op——自动发现零污染，见文件头注）
// ---------------------------------------------------------------------------
export default function (pi: any) {
  if (process.env.PRISM_CHALLENGER !== '1') {
    console.log('[challenger-b1] PRISM_CHALLENGER!=1 —— 未布防（no-op；仅挑战者网关注入 env 时注册工具）');
    return;
  }
  const { autohome, sentiment } = resolveDbPaths();
  console.log(`[challenger-b1] 布防。autohome=${autohome} sentiment=${sentiment}`);

  pi.registerTool({
    name: 'run_sql',
    label: 'run_sql',
    description:
      '对评测快照数据库执行只读 SQL 查询（仅单条 SELECT/WITH；写操作一律拒绝）。' +
      'db 缺省 autohome 主库（sales_trim 销量/owner_reviews 口碑原文/review_tags 口碑标签/config_snapshots 配置/series_summaries 车系），' +
      'db="sentiment" 切舆情库 vehicle_sentiment（vehicles/analyzed_posts/defect_threads 等）。' +
      '两库表结构见 read_file("schema.sql")。结果为 JSON（rows 数组），超 20KB 自截断——请用 WHERE/LIMIT/聚合控制行数。' +
      '所有汽车数据（销量/口碑/配置/舆情）都以本工具查库为准，禁止凭记忆作答。',
    parameters: {
      type: 'object',
      properties: {
        sql: { type: 'string', description: '单条 SELECT/WITH 语句（SQLite 方言）' },
        db: { type: 'string', enum: ['autohome', 'sentiment'], description: '选库：缺省 autohome；sentiment=舆情库' },
      },
      required: ['sql'],
    },
    async execute(_toolCallId: string, params: Record<string, unknown>) {
      const dbPath = params.db === 'sentiment' ? sentiment : autohome;
      if (params.db != null && params.db !== 'sentiment' && params.db !== 'autohome') {
        // 审查 P2：非枚举 db 值曾静默回落主库——打错名（如 'sentiments'）必须 fail-loud，防查错库不自知
        return { content: [{ type: 'text', text: JSON.stringify({ status: 'error', tool: 'run_sql', reason: `db 参数非法: ${params.db}（仅 'autohome' | 'sentiment'）` }) }] };
      }
      const out = await executeSql(dbPath, String(params.sql ?? ''));
      const payload = out.error
        ? { status: 'error', tool: 'run_sql', reason: out.error }
        : { status: 'ok', db: params.db === 'sentiment' ? 'sentiment' : 'autohome', rows: out.rows, row_count: out.rows!.length };
      const { text } = serializeResult(payload);
      return { content: [{ type: 'text', text }] };
    },
  });

  pi.registerTool({
    name: 'read_file',
    label: 'read_file',
    description:
      '读取本扩展目录下的白名单文件：SKILL-A.md（业务 SOP=AGENTS.md 原文）、SKILL-B.md（SOP+完整数据口径手册）、' +
      'schema.sql（两库全部表结构）。开始答题前必须先读 SKILL 文件与 schema.sql。',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: '白名单相对名：SKILL-A.md / SKILL-B.md / schema.sql' },
      },
      required: ['path'],
    },
    async execute(_toolCallId: string, params: Record<string, unknown>) {
      const r = readWhitelisted(String(params.path ?? ''));
      const payload = 'error' in r ? { status: 'error', tool: 'read_file', reason: r.error } : { status: 'ok', file: String(params.path), content: r.text, ...(r.truncated ? { _truncated: true } : {}) };
      const { text } = serializeResult(payload);
      return { content: [{ type: 'text', text }] };
    },
  });
}
