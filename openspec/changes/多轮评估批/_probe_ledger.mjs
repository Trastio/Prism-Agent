// 归因探针：拿真实会话里含 117800 的工具结果文本喂 extractLedgerValues（B层根因定案实验）
import { readFileSync, readdirSync } from 'node:fs';
import { extractLedgerValues, looksLikeErrorPayload } from '../../../src/verify/numeric-ledger.ts';

const dir = '.pi/sessions/eval';
const files = readdirSync(dir).filter(f => /^2026-10-25T1[5-7]/.test(f)).map(f => `${dir}/${f}`);
let done = 0;
outer:
for (const f of files) {
  for (const line of readFileSync(f, 'utf-8').split('\n')) {
    if (!line.includes('117800')) continue;
    let obj;
    try { obj = JSON.parse(line); } catch { continue; }
    // 会话行是树形 entry：递归找 toolResult 类 content 的 text
    const texts = [];
    (function walk(n) {
      if (!n || typeof n !== 'object') return;
      if (Array.isArray(n)) { n.forEach(walk); return; }
      if (n.type === 'text' && typeof n.text === 'string') texts.push(n.text);
      for (const v of Object.values(n)) if (typeof v === 'object') walk(v);
    })(obj);
    for (const t of texts) {
      if (!t.includes('117800')) continue;
      const vals = extractLedgerValues(t);
      let parseOk = false; try { JSON.parse(t); parseOk = true; } catch {}
      console.log('文件:', f.split('/').pop().slice(0, 40));
      console.log('文本长度:', t.length, '| JSON可解析:', parseOk, '| looksLikeErrorPayload:', looksLikeErrorPayload(t));
      console.log('extractLedgerValues含117800:', vals.includes('117800'), '| 抽出值数:', vals.length);
      console.log('文本尾80字:', JSON.stringify(t.slice(-80)));
      console.log('---');
      done++;
      if (done >= 3) break outer;
      break;
    }
  }
}
if (!done) console.log('未找到含117800的工具结果文本');
