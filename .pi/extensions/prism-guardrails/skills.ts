/**
 * load_skill 受限读取（社媒深挖能力包 M2）
 *
 * 背景：pi 原生 skill 全文加载靠 agent 自调 read/bash——两者均在 EXCLUDE_TOOLS，
 * 描述能进提示词但全文加载不了 → 本模块用 allowlist 目录的受限读取替代，
 * 保住渐进披露（progressive disclosure）同时不破红线（不给通用 read）。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

export const SKILLS_ROOT = resolve(process.cwd(), '.pi/skills');

const NAME_RE = /^[a-z0-9-]+$/;
const FILE_RE = /^[a-z0-9/_.-]+$/;

/** 目录内全部文件（浅层递归一层，供"可继续加载"清单） */
export function listSkillFiles(name: string): string[] {
  try {
    const dir = resolve(SKILLS_ROOT, name);
    const out: string[] = [];
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isFile() && entry !== 'SKILL.md') out.push(entry);
      else if (statSync(full).isDirectory()) {
        for (const sub of readdirSync(full)) out.push(`${entry}/${sub}`);
      }
    }
    return out;
  } catch { return []; }
}

/** D5 技能目录扫描（登记收敛）：扫 SKILLS_ROOT 下各技能目录的 SKILL.md frontmatter
 * name/summary。单源目录——load_skill 描述由此动态生成，消灭"面板扫目录 vs 模型硬编码
 * 目录"双轨漂移（2026-10-13 实证：config-compare 漏列硬编码目录致技能对模型不存在）。
 * 容错：单目录缺 SKILL.md/frontmatter 跳过；根不存在返回空（extension 自检第 3 查告警）。 */
export function listSkills(): { name: string; summary: string }[] {
  const out: { name: string; summary: string }[] = [];
  try {
    for (const entry of readdirSync(SKILLS_ROOT)) {
      let text = '';
      try { text = readFileSync(join(SKILLS_ROOT, entry, 'SKILL.md'), 'utf-8'); } catch { continue; }
      const nameM = text.match(/^name:\s*(.+)$/m);
      if (!nameM) continue;
      const sumM = text.match(/^summary:\s*(.+)$/m);
      out.push({ name: nameM[1].trim(), summary: sumM ? sumM[1].trim() : '' });
    }
  } catch { /* 根目录不存在 → 空清单 */ }
  return out;
}

/**
 * 读技能文件。防穿越三重闸：name/file 正则 + resolve 后必须仍在 SKILLS_ROOT 内 + 只读文件。
 * 返回 { ok, text?, files?, reason? }——绝不 throw。
 */
export function readSkillFile(name: string, file?: string): {
  ok: boolean; text?: string; files?: string[]; reason?: string;
} {
  const n = String(name || '').trim();
  if (!NAME_RE.test(n)) return { ok: false, reason: `技能名非法（只允许小写字母/数字/连字符）：${n}` };
  let rel = 'SKILL.md';
  if (file !== undefined && file !== '') {
    if (!FILE_RE.test(file) || file.includes('..')) return { ok: false, reason: `文件路径非法：${file}` };
    rel = file;
  }
  const full = resolve(SKILLS_ROOT, n, rel);
  // 前缀闸：解析后的绝对路径必须仍在技能根内（防 .. / 绝对路径 / 盘符穿越）
  if (!full.startsWith(SKILLS_ROOT + '\\') && !full.startsWith(SKILLS_ROOT + '/')) {
    return { ok: false, reason: '路径越出技能目录' };
  }
  try {
    const text = readFileSync(full, 'utf-8');
    return { ok: true, text, files: listSkillFiles(n) };
  } catch {
    return { ok: false, reason: `技能文件不存在：${n}/${rel}（files=${listSkillFiles(n).join(', ') || '无'}）` };
  }
}
