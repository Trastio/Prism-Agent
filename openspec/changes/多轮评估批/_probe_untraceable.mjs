// 归因终探针：对若干会话，用真实函数复算 settled ②保底——最终回复的数字 vs 台账并集，列出漏网数字形态
import { readFileSync, readdirSync } from 'node:fs';
import { readNumericLedger, ledgerHasValue, extractProseTokens } from '../../../src/verify/numeric-ledger.ts';

const dir = '.pi/sessions/eval';
const files = readdirSync(dir).filter(f => /^2026-10-25T15-2/.test(f)).slice(0, 6);
for (const f of files) {
  const lines = readFileSync(`${dir}/${f}`, 'utf-8').split('\n').filter(Boolean);
  const entries = lines.map(l => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
  const ledger = readNumericLedger(entries);
  // 最后一条 assistant 文本 = 最终回复
  let finalText = '';
  for (const e of [...entries].reverse()) {
    const m = e?.message;
    if (m?.role === 'assistant') {
      const t = Array.isArray(m.content) ? m.content.map(c => c?.text ?? '').join('') : String(m.content ?? '');
      if (t.trim()) { finalText = t; break; }
    }
  }
  const tokens = extractProseTokens(finalText);
  const miss = tokens.filter(t => !ledgerHasValue(new Set([...ledger.truth, ...ledger.declaredDerived]), t.value, t.percent, t.wan)).map(t => t.value + (t.percent ? '%' : ''));
  console.log(f.slice(0, 38), '| 台账truth=', ledger.truth.size, 'derived=', ledger.declaredDerived.size,
    '| 终稿散文数字=', tokens.length, '| 漏网=', miss.length ? miss.slice(0, 12).join(',') : '无');
}
