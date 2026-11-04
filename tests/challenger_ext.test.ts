/**
 * challenger-b1 扩展单测（取代性实验 B 系列 · 工单 W1）
 *
 * 覆盖：只读门拒写（validateSql + ro 库双层）/ 20KB 自截断 / read_file 白名单外拒 /
 * 快照只读开一次 SELECT 通（含冻结锚点 E5 2026-8月末=4436）/ 布防守卫（无 env 不注册工具）。
 * 离线：只读打开冻结快照，不起服务不触网。
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { DatabaseSync } from 'node:sqlite';

import {
  validateSql, serializeResult, executeSql, openReadOnly, resolveWhitelisted, readWhitelisted,
  resolveDbPaths, MAX_RESULT_CHARS, READ_FILE_WHITELIST,
} from '../.pi/extensions-available/challenger-b1/index.ts';
import factory from '../.pi/extensions-available/challenger-b1/index.ts';

const ROOT = resolve(import.meta.dirname, '..');
const SNAP_AUTOHOME = join(ROOT, 'eval/snapshots/snap-20261012-1222/autohome.db');

// ── 只读门（validateSql 纯函数）────────────────────────────────────────────
test('validateSql：SELECT/WITH 放行（含前导注释与结尾分号）', () => {
  assert.equal(validateSql('SELECT 1').ok, true);
  assert.equal(validateSql('  with t as (select 1) select * from t; ').ok, true);
  assert.equal(validateSql('-- 注释\nSELECT COUNT(*) FROM sales_trim').ok, true);
  assert.equal(validateSql('/* 块注释 */ SELECT 1').ok, true);
});

test('validateSql：写操作/DDL/PRAGMA/ATTACH/多语句一律拒', () => {
  for (const bad of [
    "INSERT INTO sales_trim VALUES (1)",
    "UPDATE sales_trim SET retail=0",
    "DELETE FROM owner_reviews",
    "DROP TABLE sales_trim",
    "CREATE TABLE x(a)",
    "ALTER TABLE sales_trim ADD COLUMN z",
    "PRAGMA query_only=OFF",
    "ATTACH DATABASE 'x.db' AS x",
    "SELECT 1; DROP TABLE sales_trim",   // 多语句链
    "SELECT 1; SELECT 2",                // 多语句（无写词也拒）
    "",
  ]) {
    const r = validateSql(bad);
    assert.equal(r.ok, false, `应拒: ${bad}`);
    assert.ok(r.reason, `拒因须非空: ${bad}`);
  }
});

// ── 真实 sqlite 双层防线（临时库造数据 → ro 打开拒写）──────────────────────
test('executeSql：临时库 SELECT 通；INSERT 在校验层被拒', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'challenger-ext-'));
  const dbp = join(dir, 't.db');
  const w = new DatabaseSync(dbp);
  w.exec('CREATE TABLE t(a INTEGER); INSERT INTO t VALUES (42)');
  w.close();
  try {
    const ok = await executeSql(dbp, 'SELECT SUM(a) AS s FROM t');
    assert.equal(ok.error, undefined);
    assert.equal((ok.rows![0] as any).s, 42);

    const rej = await executeSql(dbp, "INSERT INTO t VALUES (1)");
    assert.match(rej.error!, /只读工具/);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test('openReadOnly：ro 库上写语句被 SQLite 本层拒绝（绕过校验也写不进）', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'challenger-ext-'));
  const dbp = join(dir, 't.db');
  const w = new DatabaseSync(dbp);
  w.exec('CREATE TABLE t(a INTEGER)');
  w.close();
  try {
    const ro = await openReadOnly(dbp);
    assert.throws(() => ro.prepare('INSERT INTO t VALUES (1)').all(), /readonly|read-only/i);
    ro.close();
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

// ── 冻结快照只读验证（SELECT 通 + 已知锚点）───────────────────────────────
test('快照只读开一次：sales_trim 可查，E5 2026-8月末 SUM(retail)=4436（冻结锚点）', async () => {
  const r = await executeSql(SNAP_AUTOHOME,
    "SELECT COUNT(*) AS c FROM sales_trim");
  assert.equal(r.error, undefined);
  assert.ok((r.rows![0] as any).c > 0, 'sales_trim 行数应 >0');

  const e5 = await executeSql(SNAP_AUTOHOME,
    "SELECT SUM(retail) AS s FROM sales_trim WHERE REPLACE(series,' ','') LIKE '%银河E5%' AND year=2026 AND month='8月末'");
  assert.equal((e5.rows![0] as any).s, 4436);
});

// ── 20KB 自截断 ───────────────────────────────────────────────────────────
test('serializeResult：≤20KB 原样；>20KB 截断并附 _truncated 标记', () => {
  const small = serializeResult({ rows: [{ a: 1 }] });
  assert.equal(small.truncated, false);
  assert.deepEqual(JSON.parse(small.text).rows, [{ a: 1 }]);

  const big = serializeResult({ rows: [{ blob: 'x'.repeat(MAX_RESULT_CHARS + 500) }] });
  assert.equal(big.truncated, true);
  assert.ok(big.originalChars > MAX_RESULT_CHARS);
  assert.ok(big.text.length <= MAX_RESULT_CHARS + 400, '截断后长度应贴着帽+标记');
  assert.match(big.text.slice(-300), /_truncated/);
});

// ── read_file 白名单 ──────────────────────────────────────────────────────
test('resolveWhitelisted：三个白名单名放行（含 @ 前缀归一）；其余一律拒', () => {
  for (const good of READ_FILE_WHITELIST) {
    assert.equal(resolveWhitelisted(good).ok, true, good);
  }
  assert.equal(resolveWhitelisted('@SKILL-A.md').ok, true, 'pi 模型常带 @ 前缀，须归一');
  assert.equal(resolveWhitelisted(' SKILL-B.md ').ok, true, '首尾空白归一后放行');

  for (const bad of ['../AGENTS.md', 'index.ts', 'sub/SKILL-A.md', 'SKILL-a.md',
    'C:\\Users\\x\\SKILL-A.md', '/etc/passwd', '.', 'SKILL-A.md\x00']) {
    assert.equal(resolveWhitelisted(bad).ok, false, `应拒: ${JSON.stringify(bad)}`);
  }
});

test('readWhitelisted：schema.sql 实读含 sales_trim 建表句', () => {
  const r = readWhitelisted('schema.sql');
  assert.ok(!('error' in r), 'schema.sql 应可读');
  if (!('error' in r)) assert.match(r.text, /CREATE TABLE.*sales_trim/s);
});

// ── 库路径解析 + 布防守卫（自动发现零污染）───────────────────────────────
test('resolveDbPaths：缺省=冻结快照；env 覆盖；sentiment 恒为同目录兄弟文件', () => {
  const d = resolveDbPaths({}, ROOT);
  assert.equal(d.autohome, join(ROOT, 'eval/snapshots/snap-20261012-1222/autohome.db'));
  assert.equal(d.sentiment, join(ROOT, 'eval/snapshots/snap-20261012-1222/vehicle_sentiment.db'));

  const o = resolveDbPaths({ PRISM_CHALLENGER_DB: 'C:/x/snap/autohome.db' }, ROOT);
  assert.equal(o.autohome, 'C:/x/snap/autohome.db');
  assert.equal(o.sentiment, resolve('C:/x/snap/vehicle_sentiment.db'));
});

test('工厂布防守卫：PRISM_CHALLENGER 未设=不注册任何工具；=1 时恰注册 run_sql/read_file', () => {
  const reg = (names: string[]) => ({ registerTool: (t: any) => names.push(t.name) });

  const before = process.env.PRISM_CHALLENGER;
  delete process.env.PRISM_CHALLENGER;
  const off: string[] = [];
  factory(reg(off));
  assert.deepEqual(off, [], '无 env 时必须 no-op（防自动发现污染 A 系列工具面）');

  process.env.PRISM_CHALLENGER = '1';
  const on: string[] = [];
  factory(reg(on));
  assert.deepEqual(on.sort(), ['read_file', 'run_sql']);

  if (before === undefined) delete process.env.PRISM_CHALLENGER; else process.env.PRISM_CHALLENGER = before;
});
