/**
 * Prism-Agent · 数据源注册表（T-2.2.1）
 *
 * 注册 Atuohome SQLite（只读直连）+ 舆情 Board REST + RAG（预留第四口）。
 * 每个数据源声明：连接方式 / as_of / 覆盖率守卫 / 健康状态。
 *
 * 设计依据：
 * - spec `tool-interface.md` §2.2.1
 * - 红线#1：数据真实性硬底线；缺失数据如实声明
 * - 阶段1 复审教训：对象身份前置核验 + 覆盖率守卫（避免铂智7X 类对象查错）
 */

import { existsSync } from 'node:fs';
import { dirname, basename } from 'node:path';
import BetterSqlite3 from 'better-sqlite3';
import type { Database } from 'better-sqlite3';

// ---------------------------------------------------------------------------
// 类型
// ---------------------------------------------------------------------------

export type DataSourceType = 'sqlite' | 'http';

export interface HealthStatus {
  healthy: boolean;
  last_check: string;       // ISO 时间
  error?: string;
}

export interface CoverageGuard {
  /** 该数据源是否覆盖某车系（series_key） */
  series_covered: (series_key: string) => Promise<{ hit: boolean; rows?: number; detail?: string }>;
}

export interface DataSource {
  name: string;
  type: DataSourceType;
  connection: SQLiteConnection | HTTPConnection;
  as_of: string;            // 数据时点（销量/口碑=直查时间；配置=fetched_at）
  health: HealthStatus;
  coverage: CoverageGuard;
  health_check: () => Promise<boolean>;
  /** 健康降级：down 时返回声明，不 crash */
  degrade: () => { available: false; reason: string };
}

export interface SQLiteConnection {
  db_path: string;
  readonly: boolean;        // 强制只读
}

export interface HTTPConnection {
  base_url: string;
  endpoints: string[];      // 可用端点清单
  auth_required: boolean;   // 上线时需改造
}

// ---------------------------------------------------------------------------
// Atuohome SQLite（口碑/销量/配置 生产者）
// ---------------------------------------------------------------------------

// 2026-10-08 单源化：数据真值统一到 Prism 主库（prism-dashboards/data/autohome.db），
// 不再指向 Atuohome 原库。路径不含中文，chdir 兜底逻辑保留但不触发。
const AUTOHOME_DB_PATH = String(
  process.env.AUTOHOME_DB_PATH ??
    'C:\\Users\\<you>\\Desktop\\Prism-Agent\\prism-dashboards\\data\\autohome.db'
);

const atutohome_health: HealthStatus = {
  healthy: false,
  last_check: '1970-01-01T00:00:00Z',
};

/**
 * 只读打开 autohome.db。
 *
 * 实现注记：better-sqlite3 在 Windows 上对**绝对路径含中文**会 SQLITE_CANTOPEN
 * （已知 bug，immutable=1 URI 也不行）。解法：chdir 到目标目录 + 纯文件名打开。
 * 不破坏数据真实性红线：readonly=true，且 chdir 只影响本进程的相对路径解析。
 */
function openAutohomeReadonly(): Database {
  if (!existsSync(AUTOHOME_DB_PATH)) {
    throw new Error(`autohome.db 不存在: ${AUTOHOME_DB_PATH}`);
  }
  const dir = dirname(AUTOHOME_DB_PATH);
  const file = basename(AUTOHOME_DB_PATH);
  const cwd = process.cwd();
  try {
    process.chdir(dir);
    return new BetterSqlite3(file, { readonly: true, fileMustExist: true });
  } finally {
    // 恢复 cwd，避免影响其他模块的相对路径
    process.chdir(cwd);
  }
}

async function autohomeHealthCheck(): Promise<boolean> {
  try {
    const db = openAutohomeReadonly();
    const r = db.prepare('SELECT COUNT(*) as n FROM sqlite_master WHERE type=?').get('table') as { n: number };
    db.close();
    const ok = r.n > 0;
    atutohome_health.healthy = ok;
    atutohome_health.last_check = new Date().toISOString();
    atutohome_health.error = undefined;
    return ok;
  } catch (e) {
    atutohome_health.healthy = false;
    atutohome_health.last_check = new Date().toISOString();
    atutohome_health.error = (e as Error).message;
    return false;
  }
}

/** Atuohome 覆盖率守卫：检查 series_key 在销量/口碑/配置各表的覆盖 */
async function autohomeCoverage(series_key: string) {
  const db = openAutohomeReadonly();
  try {
    // sales_trim：series 字段精确匹配（禁 LIKE，避免重名加总）
    const sales_row = db
      .prepare("SELECT COUNT(*) as n FROM sales_trim WHERE series = ?")
      .get(series_key) as { n: number };
    // owner_reviews：需经 model_id（series_id）映射，这里先查 series_summaries
    const sum_row = db
      .prepare("SELECT series_id FROM series_summaries WHERE series_name = ?")
      .get(series_key) as { series_id: string } | undefined;
    let review_count = 0;
    let config_hit = false;
    if (sum_row?.series_id) {
      const r = db
        .prepare("SELECT COUNT(*) as n FROM owner_reviews WHERE model_id = ?")
        .get(sum_row.series_id) as { n: number };
      review_count = r.n;
      const c = db
        .prepare("SELECT version FROM config_snapshots WHERE series_id = ?")
        .get(sum_row.series_id) as { version?: number } | undefined;
      config_hit = !!c?.version;
    }
    return {
      sales_trim: { hit: sales_row.n > 0, rows: sales_row.n },
      owner_reviews: { hit: review_count > 0, count: review_count },
      config_snapshots: { hit: config_hit },
      series_summaries: { hit: !!sum_row },
    };
  } finally {
    db.close();
  }
}

// ---------------------------------------------------------------------------
// 舆情 Board REST
// ---------------------------------------------------------------------------

const SENTIMENT_BASE = String(process.env.SENTIMENT_BASE ?? 'http://127.0.0.1:8000');

const sentiment_health: HealthStatus = {
  healthy: false,
  last_check: '1970-01-01T00:00:00Z',
};

async function sentimentHealthCheck(): Promise<boolean> {
  try {
    // 用 OpenAPI /docs 或 /health 探活；开发期舆情 Board 在 127.0.0.1:8000
    const res = await fetch(`${SENTIMENT_BASE}/docs`, { method: 'GET' });
    const ok = res.ok;
    sentiment_health.healthy = ok;
    sentiment_health.last_check = new Date().toISOString();
    sentiment_health.error = undefined;
    return ok;
  } catch (e) {
    sentiment_health.healthy = false;
    sentiment_health.last_check = new Date().toISOString();
    sentiment_health.error = (e as Error).message;
    return false;
  }
}

async function sentimentCoverage(series_key: string) {
  // C1 修正（2026-10-11）：迁移后真实路由为 /api/dashboard/overview/{vehicle_id}（prism-sentiment
  // dashboard.py:55）。名称→ID 走 /api/vehicles/search（name/brand contains）；未收录如实返回 miss。
  try {
    const s = await fetch(`${SENTIMENT_BASE}/api/vehicles/search?q=${encodeURIComponent(series_key)}`);
    if (!s.ok) return { hit: false, detail: `vehicle search HTTP ${s.status}` };
    const vehicles = await s.json() as Array<{ id?: string | number; name?: string }>;
    const match = vehicles.find((v) => v.name === series_key) || vehicles[0];
    if (!match?.id) return { hit: false, detail: '舆情库未收录该车系' };
    const res = await fetch(`${SENTIMENT_BASE}/api/dashboard/overview/${match.id}`);
    if (!res.ok) return { hit: false, detail: `overview HTTP ${res.status}` };
    const data = await res.json() as unknown;
    return { hit: !!data, detail: `vehicle_id=${match.id}` };
  } catch (e) {
    return { hit: false, detail: (e as Error).message };
  }
}

// ---------------------------------------------------------------------------
// RAG（预留第四口）
// ---------------------------------------------------------------------------

const rag_health: HealthStatus = {
  healthy: false,
  last_check: '1970-01-01T00:00:00Z',
};

async function ragHealthCheck(): Promise<boolean> {
  // 预留：RAG 接入后实现
  rag_health.healthy = false;
  rag_health.last_check = new Date().toISOString();
  rag_health.error = 'RAG 数据源未接入（预留）';
  return false;
}

async function ragCoverage(_series_key: string) {
  return { hit: false, detail: 'RAG 未接入' };
}

// ---------------------------------------------------------------------------
// 注册表
// ---------------------------------------------------------------------------

export const registry: DataSource[] = [
  {
    name: 'atuohome',
    type: 'sqlite',
    connection: { db_path: AUTOHOME_DB_PATH, readonly: true },
    as_of: new Date().toISOString().slice(0, 10),
    health: atutohome_health,
    coverage: { series_covered: autohomeCoverage },
    health_check: autohomeHealthCheck,
    degrade: () => ({ available: false, reason: 'autohome.db 不可读，口碑/销量/配置维度全部不可用' }),
  },
  {
    name: 'sentiment',
    type: 'http',
    connection: {
      base_url: SENTIMENT_BASE,
      endpoints: [
        '/api/dashboard/overview/{vehicle_id}', '/api/dashboard/trend/{vehicle_id}',
        '/api/dashboard/dimension/{vehicle_id}', '/api/dashboard/posts/{vehicle_id}',
        '/api/dashboard/competitor-comparison/{vehicle_id}', '/api/dashboard/vehicles/{vehicle_id}/events',
      ],
      auth_required: false, // 上线时需改造（D3.12 sidecar 或加鉴权）
    },
    as_of: new Date().toISOString().slice(0, 10),
    health: sentiment_health,
    coverage: { series_covered: sentimentCoverage },
    health_check: sentimentHealthCheck,
    degrade: () => ({ available: false, reason: '舆情 Board 不可达，舆情维度降级（其余维度不受影响）' }),
  },
  {
    name: 'rag',
    type: 'http',
    connection: { base_url: '', endpoints: [], auth_required: false },
    as_of: 'n/a',
    health: rag_health,
    coverage: { series_covered: ragCoverage },
    health_check: ragHealthCheck,
    degrade: () => ({ available: false, reason: 'RAG 未接入（预留）' }),
  },
];

// ---------------------------------------------------------------------------
// 启动时健康检查
// ---------------------------------------------------------------------------

export async function bootHealthCheck(): Promise<Record<string, boolean>> {
  const results: Record<string, boolean> = {};
  for (const ds of registry) {
    results[ds.name] = await ds.health_check();
  }
  return results;
}

/** 任一数据源 down → 降级声明，不 crash（红线#1：缺失如实声明） */
export function getDataSourceStatus(): Array<{
  name: string;
  healthy: boolean;
  as_of: string;
  degrade_reason?: string;
}> {
  return registry.map((ds) => ({
    name: ds.name,
    healthy: ds.health.healthy,
    as_of: ds.as_of,
    degrade_reason: ds.health.healthy ? undefined : ds.degrade().reason,
  }));
}

/** 按 name 取数据源 */
export function getDataSource(name: string): DataSource | undefined {
  return registry.find((ds) => ds.name === name);
}

/** 打开 autohome 只读连接（供工具层/视图层调用） */
export function openAutohome(): Database {
  return openAutohomeReadonly();
}
