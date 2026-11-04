#!/usr/bin/env node
/**
 * 人工判读落账 CLI（langfuse 深度绑定 T3，2026-10-19）
 *
 * 用法: node eval/annotate.mjs <traceId> <名称> <分值> [--note "备注"]
 * 名称自动补 human- 前缀（与 judge score 并存不覆盖，拍板③）；score append-only，
 * 同名重打=历史轨迹可回溯。凭证/POST 助手复用 langfuse_binding.ts（env 优先）。
 */
import { pathToFileURL } from 'node:url';
import { postScore } from './langfuse_binding.ts';

/** human- 前缀强制（无则补，有不重复加）；导出供单测。 */
export function humanizeScoreName(name) {
  const n = String(name ?? '').trim();
  return n.startsWith('human-') ? n : 'human-' + n;
}

function parseArgs(argv) {
  const rest = [];
  let note = '';
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === '--note') { note = argv[i + 1] || ''; i++; }
    else rest.push(argv[i]);
  }
  return { rest, note };
}

const HELP = [
  '用法: node eval/annotate.mjs <traceId> <名称> <分值> [--note "备注"]',
  '名称自动补 human- 前缀（人工判读分与 judge 分并存不覆盖）；分值按数字写入（dataType=NUMERIC）',
  '例: node eval/annotate.mjs tr-abc123 tone 5 --note "口径清晰，结论克制"',
].join('\n');

async function main() {
  const { rest, note } = parseArgs(process.argv.slice(2));
  const [traceId, rawName, rawValue] = rest;
  if (!traceId || !rawName || rawValue === undefined) {
    console.log(HELP);
    process.exit(2);
  }
  const value = Number(rawValue);
  if (!Number.isFinite(value)) {
    console.error('分值必须是数字');
    process.exit(2);
  }
  const name = humanizeScoreName(rawName);
  try {
    const id = await postScore({ name, value, traceId, comment: note || undefined });
    if (id == null) {
      // Step8 P2-5：2xx 但没取到 score id = 响应形状异常，不能打 ✓ 装成功
      console.warn(`⚠ 写入返回 2xx 但未取到 score id（响应形状异常，请到 langfuse UI 核对）: name=${name} value=${value}`);
    } else {
      console.log(`✓ score 已写入: id=${id} name=${name} value=${value} trace=${traceId}`);
    }
  } catch (e) {
    // postScore 错误只带路径+状态码，不含凭证（红线①）
    console.error(`写入失败: ${e?.message ?? e}`);
    process.exit(1);
  }
}

// 入口守卫：被 import（单测/复用）时不执行 CLI（参考 prompt_gate.mjs 的 CLI 分发隔离）
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main();
}
