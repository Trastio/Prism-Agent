/**
 * D/R5：插件裁剪静态自检单测
 * 运行：node --test openspec/changes/插件能力裁剪加固/plugin-guard.test.mjs
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const ROOT = resolve(import.meta.dirname, '../../..');

// 从源码提取常量（避免 import pi_gateway.mjs 启动 server）
const idxSrc = readFileSync(resolve(ROOT, '.pi/extensions/prism-guardrails/index.ts'), 'utf-8');
const gwSrc = readFileSync(resolve(ROOT, 'prism-api/pi_gateway.mjs'), 'utf-8');

const knownMatch = idxSrc.match(/KNOWN_BUSINESS_TOOLS = new Set\(\[([\s\S]*?)\]\)/);
const knownTools = knownMatch[1].match(/'([^']+)'/g).map(s => s.replace(/'/g, ''));
const allowedMatch = idxSrc.match(/ALLOWED_TOOLS = new Set\(\[([\s\S]*?)\]\)/);
// ALLOWED_TOOLS 现在是 [...KNOWN_BUSINESS_TOOLS, ...EXTRA_TOOLS]（展开，无字面量）
// 从 EXTRA_TOOLS 提取实际工具名
// 从 TOOL_CATEGORIES 提取 web + utility 工具名
const webMatch = idxSrc.match(/web:\s*new Set\(\[([\s\S]*?)\]\)/);
const webTools = webMatch ? (webMatch[1].match(/'([^']+)'/g) || []).map(s => s.replace(/'/g, '')) : [];
const utilMatch = idxSrc.match(/utility:\s*new Set\(\[([\s\S]*?)\]\)/);
const utilTools = utilMatch ? (utilMatch[1].match(/'([^']+)'/g) || []).map(s => s.replace(/'/g, '')) : [];
const extraTools = [...webTools, ...utilTools];
const allowedTools = [...knownTools, ...extraTools];

// EXCLUDE_TOOLS 从源码提取（不 import）
const excludeMatch = gwSrc.match(/export const EXCLUDE_TOOLS = \[([\s\S]*?)\];/);
const excludeTools = excludeMatch[1].match(/'([^']+)'/g).map(s => s.replace(/'/g, ''));

// 已注册业务工具（两种注册方式：makeQueryTool('name',...) 和 pi.registerTool({name:...})）
const regFromFactory = [...idxSrc.matchAll(/pi\.registerTool\(make\w+Tool\(\s*'([^']+)'/g)];
const regFromObj = [...idxSrc.matchAll(/pi\.registerTool\(\{[\s\S]*?name:\s*'([^']+)'/g)];
const registeredTools = [...regFromFactory.map(m => m[1]), ...regFromObj.map(m => m[1])];

// settings.json 12 包版本
const settings = JSON.parse(readFileSync(resolve(ROOT, '.pi/agent-minimal/settings.json'), 'utf-8'));

describe('plugin-guard 静态自检', () => {
  it('Q1: KNOWN_BUSINESS_TOOLS ⊆ 已注册业务工具', () => {
    const unregistered = knownTools.filter(t => !registeredTools.includes(t));
    assert.deepEqual(unregistered, [], `未注册的业务工具: ${unregistered}`);
  });

  it('Q1: ALLOWED_TOOLS = KNOWN_BUSINESS_TOOLS ∪ EXTRA_TOOLS（含 web/utility）', () => {
    // 块4 回改：ALLOWED_TOOLS 从 TOOL_CATEGORIES 派生
    assert.ok(allowedMatch[1].includes('...KNOWN_BUSINESS_TOOLS'), 'ALLOWED_TOOLS 应展开 KNOWN_BUSINESS_TOOLS');
    assert.ok(allowedMatch[1].includes('...EXTRA_TOOLS'), 'ALLOWED_TOOLS 应展开 EXTRA_TOOLS');
    // extra 工具集 = web + utility
    const expectedExtra = ['ask_user_question', 'web_search', 'fetch_content', 'source_check', 'get_search_content'];
    const extra = allowedTools.filter(t => !knownTools.includes(t));
    for (const e of expectedExtra) {
      assert.ok(extra.includes(e), `ALLOWED_TOOLS 应含 ${e}`);
    }
  });

  it('EXCLUDE_TOOLS ∩ ALLOWED_TOOLS = ∅（白名单工具没被 exclude）', () => {
    // 块4 回改：用完整 ALLOWED_TOOLS 做冲突检查
    const fullAllowed = [...knownTools, 'ask_user_question', 'web_search', 'fetch_content', 'source_check', 'get_search_content'];
    const conflict = fullAllowed.filter(t => excludeTools.includes(t));
    assert.deepEqual(conflict, [], `白名单工具被 exclude: ${conflict}`);
  });

  it('N12: 12 包版本一致性（settings 声明 == 已安装）', () => {
    for (const pkg of settings.packages) {
      const stripped = pkg.replace('npm:', '');
      // @scoped/pkg@version → name=@scoped/pkg, version=后@之后
      // pkg@version → name=pkg, version=@之后
      const lastAt = stripped.lastIndexOf('@');
      const name = stripped.slice(0, lastAt);
      const declaredVersion = stripped.slice(lastAt + 1);
      if (!/^\d+\.\d+\.\d+$/.test(declaredVersion)) continue;
      const installedVersion = JSON.parse(
        readFileSync(resolve(ROOT, `.pi/agent-minimal/npm/node_modules/${name}/package.json`), 'utf-8')
      ).version;
      assert.equal(installedVersion, declaredVersion, `${name} 版本不一致: settings=${declaredVersion} installed=${installedVersion}`);
    }
  });
});
