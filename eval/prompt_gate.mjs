#!/usr/bin/env node
/**
 * 提示词回归门禁（prompt-gate change，2026-10-16）
 *
 * 背景：提示词是本系统变更最频繁、测试为零的"代码"（教材 7.10.4：系统提示应有与代码
 * 同等的版本控制与回归测试）。L1-2 越界修复即提示词变更——无门禁时改一处可静默改坏
 * 另一处，直到数周后全量批跑才暴露。
 *
 * 机制：提示词层文件集 → sha256 指纹快照 → commit 前（pre-commit hook，秒级）比对
 * last_green——变更未冒烟 = 拦（红条+冒烟指引；PRISM_PROMPT_GATE_BYPASS=1 显式绕过留痕）。
 * 冒烟 = 快照实例跑 trap 子集（一票否决线，提示词变更的主要风险面）后 mark-green。
 * 静态检查（2026-10-20 微change）：check 同时跑 skill 文件内容级 lint（A 双登记 /
 * B frontmatter 完整 / C 硬数字黑名单）——违例即红，与指纹状态无关。
 *
 * 用法：
 *   node eval/prompt_gate.mjs fingerprint            # 打印当前指纹与文件清单
 *   node eval/prompt_gate.mjs check [--hook]         # 绿=0 / 红=1 / 从未跑过=2 / bypass=0
 *   node eval/prompt_gate.mjs mark-green [--note ..] # 冒烟通过后记录
 *
 * 状态文件 eval/prompt_gate.json（last_green + history，改指纹必留痕）。
 * runner.mjs 批跑报告亦记录 prompt_files_hash——每份报告自动绑定当时的提示词版本。
 */
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, existsSync, readdirSync } from 'node:fs';
import { resolve, dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execSync } from 'node:child_process';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');

// 提示词层文件集（拍板范围）：红线SOP + 角色约束 + skills 全部 md + 回灌前缀常量。
// 不含 .pi/extensions（代码层，自有单测/回归）；新增 skill 时在登记处同步本清单
// （D1 启动自检三表互检同源教训：两处目录不同步=静默漂移）。
// 漏登记由 lintSkillFiles 断言 A 自动拦截（磁盘 .pi/skills md 必须全部入本清单）。
export const PROMPT_FILES = [
  'AGENTS.md',
  'SYSTEM.md',
  '.pi/skills/car-reputation-research/SKILL.md',
  '.pi/skills/car-reputation-research/references/deliverable-spec.md',
  '.pi/skills/car-reputation-research/references/platform-notes.md',
  '.pi/skills/config-compare/SKILL.md',
  'src/shared/verifier-prefix.ts',
];

export function computeFingerprint(files, root = ROOT) {
  const per = [];
  for (const rel of files) {
    const abs = resolve(root, rel);
    per.push([rel, existsSync(abs) ? createHash('sha256').update(readFileSync(abs)).digest('hex').slice(0, 16) : null]);
  }
  const agg = createHash('sha256').update(per.map(([r, h]) => `${r}:${h}`).join('\n')).digest('hex').slice(0, 32);
  return { hash: agg, files: per, missing: per.filter(([, h]) => h === null).map(([r]) => r) };
}

const STATE_FILE = resolve(ROOT, 'eval/prompt_gate.json');

export function readState(stateFile = STATE_FILE) {
  try { return JSON.parse(readFileSync(stateFile, 'utf-8')); } catch { return null; }
}

export function writeState(s, stateFile = STATE_FILE) {
  writeFileSync(stateFile, JSON.stringify(s, null, 2), 'utf-8');
}

export function markGreen(stateFile = STATE_FILE, note = '') {
  const fp = computeFingerprint(PROMPT_FILES);
  let gitHead = null;
  try { gitHead = execSync('git rev-parse --short HEAD', { cwd: ROOT }).toString().trim(); } catch {}
  const prev = readState(stateFile) || { last_green: null, history: [] };
  const entry = { hash: fp.hash, files: fp.files, marked_at: new Date().toISOString(), git_head: gitHead, note };
  writeState({ last_green: entry, history: [...(prev.history || []), entry].slice(-50) }, stateFile);
  return entry;
}

/** → {level: green|red|never|bypass, fp, since?, changedFiles?}；不碰 exit code（CLI 层管） */
export function checkGate(stateFile = STATE_FILE) {
  const fp = computeFingerprint(PROMPT_FILES);
  if (process.env.PRISM_PROMPT_GATE_BYPASS === '1') {
    const st = readState(stateFile);
    return { level: 'bypass', fp, changed: !st?.last_green || st.last_green.hash !== fp.hash };
  }
  const st = readState(stateFile);
  if (!st?.last_green) return { level: 'never', fp };
  if (st.last_green.hash === fp.hash) return { level: 'green', fp, since: st.last_green };
  const oldMap = new Map(st.last_green.files || []);
  const changedFiles = fp.files
    .filter(([r, h]) => !oldMap.has(r) || oldMap.get(r) !== h)
    .map(([r]) => r);
  return { level: 'red', fp, since: st.last_green, changedFiles };
}

// ── 静态 lint：skill 文件内容级检查（2026-10-20 微change「skill 静态检查」）──────
// 起因：SKILL.md 复制真值数字致三处漂移实锤（护栏 8→20 次文案没跟 / 差价清单 61→71 条 /
// 快照车系 244→353 系）。真值会动、文案不会自跟——治本=文案只写指针；本 lint=防复发。
//   A 双登记：.pi/skills/ 下全部 md 必须 ⊆ files（新增 skill 漏登记=门禁对它失明）
//   B frontmatter：SKILL.md 顶层必含 name/summary/description + version（顶层或嵌套），
//     且 name=目录名（version 纪律：改行为语义必 bump）
//   C 硬数字黑名单：SKILL.md 正文禁写死会漂移的真值数字（N 次 / N 项 / N 系）——
//     配额/清单项数/覆盖车系数以护栏/清单/库为准；references 模板文件不查数字
const VOLATILE_NUM = /\d+\s*项|\d+\s*系(?![列统])|\d+\s*次(?![数])/;

/** 递归收集 root 下 .pi/skills 全部 .md 的相对路径（正斜杠） */
export function listSkillFiles(root = ROOT) {
  const out = [];
  const walk = (d) => {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      if (e.name.startsWith('.')) continue;
      const p = join(d, e.name);
      if (e.isDirectory()) walk(p);
      else if (e.name.endsWith('.md')) out.push(relative(root, p).replace(/\\/g, '/'));
    }
  };
  walk(join(root, '.pi/skills'));
  return out.sort();
}

/** 解析 frontmatter（顶层 key/value；整块保留供嵌套 version 探测） */
function parseFrontmatter(text) {
  const m = text.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!m) return null;
  const top = {};
  for (const line of m[1].split(/\r?\n/)) {
    const kv = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
    if (kv) top[kv[1]] = kv[2].trim();
  }
  return { top, block: m[1] };
}

/** → 违例字符串数组（空=过）；root/files 参数化供单测注入 */
export function lintSkillFiles(root = ROOT, files = PROMPT_FILES) {
  const v = [];
  for (const f of listSkillFiles(root)) {
    if (!files.includes(f)) v.push(`[A 双登记] ${f} 在 .pi/skills 但未入 PROMPT_FILES——门禁对它失明，请登记`);
  }
  for (const f of files) {
    if (!f.startsWith('.pi/skills/')) continue;
    const abs = resolve(root, f);
    if (!existsSync(abs)) { v.push(`[A 双登记] ${f} 已登记但磁盘缺失`); continue; }
    if (!f.endsWith('/SKILL.md')) continue;
    const text = readFileSync(abs, 'utf-8');
    const fm = parseFrontmatter(text);
    if (!fm) { v.push(`[B frontmatter] ${f} 缺 frontmatter（--- 包裹的头部）`); continue; }
    for (const k of ['name', 'summary', 'description']) if (!fm.top[k]) v.push(`[B frontmatter] ${f} 缺字段 ${k}`);
    if (!/^(\s+)?version:\s*\S+/m.test(fm.block)) v.push(`[B frontmatter] ${f} 缺 version（改行为语义必 bump）`);
    const dirName = f.split('/')[2];
    if (fm.top.name && fm.top.name !== dirName) v.push(`[B frontmatter] ${f} name="${fm.top.name}" ≠ 目录名 "${dirName}"`);
    const body = text.replace(/^---\r?\n[\s\S]*?\r?\n---/, '');
    const hit = body.match(VOLATILE_NUM);
    if (hit) v.push(`[C 硬数字] ${f} 正文写死真值数字"${hit[0]}"——配额/清单项数/车系数会漂移，改写指针（以护栏/清单/库为准）`);
  }
  return v;
}

// ── CLI（入口守卫：被 import 时不执行——单测直接引纯函数） ─────────────
const isDirectRun = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
const [, , cmd, ...rest] = process.argv;
if (!isDirectRun) {
  // 被 import：什么都不做（纯函数已导出）
} else if (cmd === 'fingerprint') {
  const fp = computeFingerprint(PROMPT_FILES);
  console.log(`prompt_files_hash: ${fp.hash}`);
  for (const [r, h] of fp.files) console.log(`  ${h ?? 'MISSING!'}  ${r}`);
  if (fp.missing.length) { console.error(`缺失: ${fp.missing.join(', ')}`); process.exit(1); }
} else if (cmd === 'check') {
  const hook = rest.includes('--hook');
  const lint = lintSkillFiles();
  if (lint.length) {
    console.error('✗ skill 静态检查未过（内容级 lint，与指纹状态无关）：');
    for (const x of lint) console.error(`  - ${x}`);
    process.exit(1);
  }
  const r = checkGate();
  if (r.level === 'green') {
    if (!hook) console.log(`✓ 提示词门禁绿（自 ${r.since.marked_at} / ${r.since.git_head ?? '-'}，hash=${r.fp.hash.slice(0, 12)}）`);
    process.exit(0);
  } else if (r.level === 'bypass') {
    console.log(`⚠ 提示词门禁 BYPASSED（显式绕过留痕；变更=${r.changed ? '有' : '无'}）`);
    process.exit(0);
  } else if (r.level === 'never') {
    console.log(`! 提示词门禁从未标绿——先跑一次冒烟：\n  prism.py eval start && node eval/runner.mjs --only=trap\n  然后: node eval/prompt_gate.mjs mark-green`);
    process.exit(hook ? 1 : 2);
  } else {
    console.log(`✗ 提示词层已变更未冒烟（hash ${r.since?.hash?.slice(0, 12)} → ${r.fp.hash.slice(0, 12)}）：`);
    for (const f of r.changedFiles || []) console.log(`  - ${f}`);
    console.log(`  跑冒烟: prism.py eval start && node eval/runner.mjs --only=trap && node eval/prompt_gate.mjs mark-green`);
    console.log(`  确认无碍可显式绕过（留痕）: PRISM_PROMPT_GATE_BYPASS=1 git commit ...`);
    process.exit(1);
  }
} else if (cmd === 'mark-green') {
  const i = rest.indexOf('--note');
  const entry = markGreen(undefined, i >= 0 ? rest[i + 1] || '' : '');
  console.log(`✓ 已标绿: hash=${entry.hash} git=${entry.git_head ?? '-'} ${entry.note ? `note=${entry.note}` : ''}`);
} else {
  console.log('用法: prompt_gate.mjs <fingerprint|check [--hook]|mark-green [--note ..]>');
  process.exit(2);
}
