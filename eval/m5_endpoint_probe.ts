/**
 * M5 端点实测探针（社媒深挖能力包）——跑真实 TikHub 调用过我们的完整链路
 * （callEndpoint + normalizer），校准 TODO-verify 字段映射 + 落真实 fixtures。
 *
 * 运行：npx tsx eval/m5_endpoint_probe.ts
 * 成本：~7 次调用（约 $0.05-0.2）；PRISM_TIKHUB_KEY 从 prism-api/.env 读
 */
import { writeFileSync, mkdirSync, readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';

// 读 key（不经 shell 转义陷阱——cut -d= 会吃掉尾部 ==，2026-10-12 事故教训）
const envPath = resolve(process.cwd(), 'prism-api/.env');
if (existsSync(envPath)) {
  const m = readFileSync(envPath, 'utf-8').match(/^TIKHUB_KEY_PRISM\s*=\s*(.+)$/m);
  if (m) process.env.PRISM_TIKHUB_KEY = m[1].trim().replace(/^["']|["']$/g, '');
}
if (!process.env.PRISM_TIKHUB_KEY) { console.error('无 PRISM_TIKHUB_KEY，退出'); process.exit(1); }

const { executeAction } = await import('../.pi/extensions/prism-guardrails/tikhub.ts');

const SEC_UID = 'MS4wLjABAAAASYNTHETIC0SECUID0000000000000000000000000'; // 测试作者A
const CASES: Array<{ label: string; tool: string; action: any; params: any }> = [
  { label: 'profile-douyin', tool: 'social_user_profile', action: 'profile', params: { platform: 'douyin', user_id: SEC_UID } },
  { label: 'posts-douyin', tool: 'social_user_posts', action: 'posts', params: { platform: 'douyin', user_id: `sec_uid:${SEC_UID}`, count: 5 } },
  { label: 'search-xhs', tool: 'social_search', action: 'search', params: { platform: 'xiaohongshu', keyword: '风云T7 提车' } },
  { label: 'search-douyin', tool: 'social_search', action: 'search', params: { platform: 'douyin', keyword: '风云T7' } },
  { label: 'search-weibo', tool: 'social_search', action: 'search', params: { platform: 'weibo', keyword: '风云T7' } },
  { label: 'search-kuaishou', tool: 'social_search', action: 'search', params: { platform: 'kuaishou', keyword: '风云T7' } },
  { label: 'search-bilibili', tool: 'social_search', action: 'search', params: { platform: 'bilibili', keyword: '风云T7' } },
];

const outDir = resolve(process.cwd(), 'eval/artifacts/tikhub-fixtures');
mkdirSync(outDir, { recursive: true });

for (const c of CASES) {
  process.stdout.write(`[${c.label}] ... `);
  try {
    const r = await executeAction(c.tool, c.action, c.params);
    const text = r.content[0].text;
    let d: any;
    try { d = JSON.parse(text); } catch { d = { unparseable: text.slice(0, 200) }; }
    if (d.status === 'unavailable') {
      console.log(`FAIL: ${String(d.reason).slice(0, 100)}`);
    } else {
      const items = d.items || [d];
      const withUrl = items.filter((x: any) => x.url).length;
      const first = items[0] || {};
      console.log(`ok items=${items.length} withUrl=${withUrl} first.nickname=${first.nickname ?? first.author ?? '-'} first.url=${(first.url || '-').slice(0, 55)}`);
      writeFileSync(resolve(outDir, `${c.label}.json`), text, 'utf-8');
    }
  } catch (e) {
    console.log('EXCEPTION:', (e as Error).message);
  }
}
console.log(`\nfixtures 落盘: ${outDir}`);
