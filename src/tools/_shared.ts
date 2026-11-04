/**
 * Prism-Agent · 工具层共享基础设施
 *
 * 2026-10-08 单源化：物化视图 prism_views.db 退役，统一**实时**读 Prism 主库
 * （prism-dashboards/data/autohome.db；路径不含中文，无 better-sqlite3 中文参数 bug）。
 * - 工具返回统一格式：{ rows, _meta }
 * - 名称字段强制库源落地：所有 series/brand/model_name 从 DB 直取
 */

import BetterSqlite3 from 'better-sqlite3';
import type { Database } from 'better-sqlite3';

/** 数据真值：Prism 主库（迁移后唯一源），可用 AUTOHOME_DB_PATH 覆盖 */
const AUTOHOME_DB_PATH = String(
  process.env.AUTOHOME_DB_PATH ??
    'C:\\Users\\<you>\\Desktop\\Prism-Agent\\prism-dashboards\\data\\autohome.db'
);

/** 开 Prism 主库（只读）。路径英文，中文参数绑定正常，无需 chdir 兜底 */
export function openAutohomeForTools(): Database {
  return new BetterSqlite3(AUTOHOME_DB_PATH, { readonly: true, fileMustExist: true });
}
