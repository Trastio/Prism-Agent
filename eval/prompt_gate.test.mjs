/**
 * 提示词回归门禁单测（prompt-gate change，2026-10-16）
 * 覆盖：指纹稳定性 / 内容变更检测 / 状态机三态（绿红从未）/ bypass / markGreen 留痕
 * 运行：node --test eval/prompt_gate.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { computeFingerprint, checkGate, markGreen, readState, writeState, PROMPT_FILES, lintSkillFiles } from './prompt_gate.mjs';

test('PROMPT_FILES 全部真实存在（清单漂移=门禁失明）', () => {
  const fp = computeFingerprint(PROMPT_FILES);
  assert.deepEqual(fp.missing, [], `提示词文件缺失: ${fp.missing.join(', ')}`);
});

test('computeFingerprint: 同内容稳定 / 变内容即变 / 缺文件入 missing（root 参数化注入 tmp）', () => {
  const dir = mkdtempSync(join(tmpdir(), 'pg-'));
  mkdirSync(join(dir, 'sub'), { recursive: true });
  writeFileSync(join(dir, 'a.md'), '内容A', 'utf-8');
  writeFileSync(join(dir, 'sub/b.md'), '内容B', 'utf-8');
  const f1 = computeFingerprint(['a.md', 'sub/b.md'], dir);
  const f2 = computeFingerprint(['a.md', 'sub/b.md'], dir);
  assert.equal(f1.hash, f2.hash, '同内容指纹必须稳定');
  writeFileSync(join(dir, 'a.md'), '内容A改', 'utf-8');
  const f3 = computeFingerprint(['a.md', 'sub/b.md'], dir);
  assert.notEqual(f1.hash, f3.hash, '内容变更指纹必须变');
  const f4 = computeFingerprint(['a.md', 'nope.md'], dir);
  assert.deepEqual(f4.missing, ['nope.md']);
  rmSync(dir, { recursive: true, force: true });
});

test('checkGate: 三态——从未(never) → 标绿(green) → 变更(red 且列出文件)', () => {
  const dir = mkdtempSync(join(tmpdir(), 'pg2-'));
  const state = join(dir, 'state.json');
  writeFileSync(join(dir, 'p.md'), 'v1', 'utf-8');
  // 用参数化 root 造指纹：直接操纵 state 文件模拟（checkGate 的文件集固定 PROMPT_FILES+ROOT，
  // 这里只测状态机：手动构造 state 让 hash 匹配/不匹配）
  const fp = computeFingerprint(PROMPT_FILES); // 真实文件集
  const fakeEntry = { hash: fp.hash, files: fp.files, marked_at: '2026-10-16T00:00:00Z', git_head: 'abc1234', note: '' };
  assert.equal(checkGate(state).level, 'never', '无状态文件=never');
  writeState({ last_green: fakeEntry, history: [fakeEntry] }, state);
  assert.equal(checkGate(state).level, 'green', 'hash 相同=green');
  const entry2 = { ...fakeEntry, hash: 'deadbeef'.repeat(4), files: fp.files.map(([r]) => [r, '0'.repeat(16)]) };
  writeState({ last_green: entry2, history: [] }, state);
  const red = checkGate(state);
  assert.equal(red.level, 'red');
  assert.ok((red.changedFiles || []).length >= PROMPT_FILES.length, '全文件都变了应全部列出');
  rmSync(dir, { recursive: true, force: true });
});

test('markGreen: 记录当前真实指纹 + history 追加不丢失', () => {
  const dir = mkdtempSync(join(tmpdir(), 'pg3-'));
  const state = join(dir, 'state.json');
  const e1 = markGreen(state, '首次');
  const st1 = readState(state);
  assert.equal(st1.last_green.hash, e1.hash);
  assert.equal(st1.history.length, 1);
  const e2 = markGreen(state, '二次');
  const st2 = readState(state);
  assert.equal(st2.history.length, 2, 'history 必须追加留痕');
  assert.equal(st2.last_green.hash, e2.hash);
  rmSync(dir, { recursive: true, force: true });
});

// ── 静态 lint（skill 静态检查微change，2026-10-20）──────────────────────────
const FM_OK = `---
name: alpha
summary: 一句话给面板看
description: 给模型触发用，含意图与交付物
metadata:
  version: "1.0.0"
---
`;
const BODY_OK = '# Alpha\n\n流程见差价清单（项数以清单为准）。\n';

test('lintSkillFiles: 真实仓库当前零违例（写死数字/漏登记/坏 frontmatter 即红）', () => {
  assert.deepEqual(lintSkillFiles(), [], '真实 skill 文件面应全部通过 lint');
});

test('lintSkillFiles: A 双登记——磁盘 md 未入清单即报，登记齐则过', () => {
  const dir = mkdtempSync(join(tmpdir(), 'pg-lint-'));
  mkdirSync(join(dir, '.pi/skills/alpha'), { recursive: true });
  writeFileSync(join(dir, '.pi/skills/alpha/SKILL.md'), FM_OK + BODY_OK, 'utf-8');
  const v = lintSkillFiles(dir, []);
  assert.ok(v.some((x) => x.includes('[A 双登记]') && x.includes('alpha/SKILL.md')), JSON.stringify(v));
  const ok = lintSkillFiles(dir, ['.pi/skills/alpha/SKILL.md']);
  assert.deepEqual(ok, [], JSON.stringify(ok));
  rmSync(dir, { recursive: true, force: true });
});

test('lintSkillFiles: B frontmatter 缺字段/缺 version/name≠目录名', () => {
  const dir = mkdtempSync(join(tmpdir(), 'pg-lint2-'));
  mkdirSync(join(dir, '.pi/skills/beta'), { recursive: true });
  writeFileSync(join(dir, '.pi/skills/beta/SKILL.md'), '---\nname: wrong\nsummary: s\n---\n正文', 'utf-8');
  const v = lintSkillFiles(dir, ['.pi/skills/beta/SKILL.md']);
  assert.ok(v.some((x) => x.includes('缺字段 description')), JSON.stringify(v));
  assert.ok(v.some((x) => x.includes('缺 version')), JSON.stringify(v));
  assert.ok(v.some((x) => x.includes('name="wrong" ≠ 目录名')), JSON.stringify(v));
  rmSync(dir, { recursive: true, force: true });
});

test('lintSkillFiles: C 硬数字黑名单——N 次/N 项/N 系 命中，指针写法放行', () => {
  const dir = mkdtempSync(join(tmpdir(), 'pg-lint3-'));
  mkdirSync(join(dir, '.pi/skills/gamma'), { recursive: true });
  const bad = FM_OK.replace('name: alpha', 'name: gamma') + '每轮最多 8 次调用；按 61 项口径；现 244 系。\n';
  writeFileSync(join(dir, '.pi/skills/gamma/SKILL.md'), bad, 'utf-8');
  const v = lintSkillFiles(dir, ['.pi/skills/gamma/SKILL.md']);
  assert.ok(v.some((x) => x.includes('[C 硬数字]')), JSON.stringify(v));
  const good = FM_OK.replace('name: alpha', 'name: gamma') + '配额以系统护栏为准；按差价清单口径（项数以清单为准）。\n';
  writeFileSync(join(dir, '.pi/skills/gamma/SKILL.md'), good, 'utf-8');
  assert.deepEqual(lintSkillFiles(dir, ['.pi/skills/gamma/SKILL.md']), [], '指针写法不应命中黑名单');
  rmSync(dir, { recursive: true, force: true });
});
