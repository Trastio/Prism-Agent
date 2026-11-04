/**
 * prism-guardrails · tool_call hook 单测（红线#2/#3 + fail-closed 未知工具）
 * 框架：node:test（Node 内置，无依赖）
 * 运行：node --test --import tsx .pi/extensions/prism-guardrails/tool_call.test.ts
 *
 * 覆盖：
 * - fail-closed 未知业务工具拦截（业务前缀不在白名单 → block）
 * - 裸 SQL 拦截（DROP TABLE → block + terminate）
 * - 敏感文件拦截（.env / auth.json → block）
 * - 数据库直连拦截（bash psql → block）
 * - 已知工具放行（query_reviews → 不 block）
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  decideToolCall,
  KNOWN_BUSINESS_TOOLS,
  BUSINESS_PREFIXES,
  coverKeys,
  findUncoveredObjects,
  declaredCoverObjects,
  checkPoolGuard,
} from './index.ts';

// ── 横评先筛池守卫（2026-11-02 显著性实验 B 臂）───────────────────────────
// 契约：价格带横评问法 + 已进入车型级比较 + 未做价格带/能源筛选 → 触发。
// 任何一条不满足都必须不触发（误伤会在其它题上制造假回灌）。
describe('checkPoolGuard · 横评先筛池', () => {
  const cmpOnly = [{ name: 'search_cars', input: { keyword: '海豚' } }, { name: 'compare_configs_valued', input: {} }];

  it('价格带横评 + 只按 keyword 搜 + 已比配置 → 触发', () => {
    assert.equal(checkPoolGuard('12万元左右哪个BEV车型的配置最好', cmpOnly).trigger, true);
    assert.equal(checkPoolGuard('15万元以下，你有哪些推荐？', cmpOnly).trigger, true);
  });

  it('已带价格带/能源筛选 → 不触发', () => {
    const ok = [
      { name: 'search_cars', input: { energy: 'BEV', price_min: 100000, price_max: 120000 } },
      { name: 'compare_configs_valued', input: {} },
    ];
    assert.equal(checkPoolGuard('12万元左右哪个BEV车型的配置最好', ok).trigger, false);
  });

  it('未进入车型级比较 → 不触发', () => {
    assert.equal(checkPoolGuard('12万元左右哪个BEV车型的配置最好', [{ name: 'search_cars', input: {} }]).trigger, false);
  });

  it('非价格带横评问法 → 不触发（防误伤）', () => {
    assert.equal(checkPoolGuard('银河E5比零跑B10多哪些配置', cmpOnly).trigger, false);
    assert.equal(checkPoolGuard('海狮06的配置如何', cmpOnly).trigger, false);
    assert.equal(checkPoolGuard('分析银河E5的三维度，舒适性是否为结构性短板', cmpOnly).trigger, false);
  });

  it('空工具序列 / 空问题 → 不触发', () => {
    assert.equal(checkPoolGuard('', cmpOnly).trigger, false);
    assert.equal(checkPoolGuard('12万元左右哪个BEV车型的配置最好', []).trigger, false);
  });
});

describe('decideToolCall · fail-closed 未知业务工具', () => {
  it('业务前缀但不在白名单 → block（query_xxx 幻觉工具）', () => {
    const r = decideToolCall('query_comfort', { series_key: '银河E5' });
    assert.equal(r.block, true);
    assert.match(r.reason ?? '', /fail-closed.*未知业务工具/);
  });

  it('search_xyz 幻觉工具 → block', () => {
    const r = decideToolCall('search_fleet', { q: 'x' });
    assert.equal(r.block, true);
    assert.match(r.reason ?? '', /fail-closed/);
  });

  it('get_invented → block', () => {
    const r = decideToolCall('get_invented', {});
    assert.equal(r.block, true);
  });
});

describe('decideToolCall · 裸 SQL 拦截', () => {
  it('DROP TABLE → block + terminate', () => {
    const r = decideToolCall('bash', { cmd: 'echo "DROP TABLE users;"' });
    assert.equal(r.block, true);
    assert.equal(r.terminate, true);
    assert.match(r.reason ?? '', /红线#2.*裸 SQL/);
  });

  it('DELETE FROM → block', () => {
    const r = decideToolCall('bash', { cmd: "sqlite3 x.db 'DELETE FROM t'" });
    // 注意：此输入同时命中裸SQL + 数据库直连，裸SQL 优先（terminate=true）
    assert.equal(r.block, true);
    assert.equal(r.terminate, true);
  });

  it('INSERT/UPDATE/ALTER → block', () => {
    for (const kw of ['INSERT', 'UPDATE', 'ALTER']) {
      const r = decideToolCall('bash', { cmd: `echo "${kw} INTO t"` });
      assert.equal(r.block, true, `${kw} 应被拦截`);
    }
  });
});

describe('decideToolCall · 敏感文件拦截', () => {
  it('.env → block', () => {
    const r = decideToolCall('read', { path: '.env' });
    assert.equal(r.block, true);
    assert.match(r.reason ?? '', /红线#3.*敏感文件/);
  });

  it('auth.json → block', () => {
    const r = decideToolCall('read', { path: 'config/auth.json' });
    assert.equal(r.block, true);
  });

  it('id_rsa / .ssh / credentials → block', () => {
    for (const p of ['~/.ssh/id_rsa', 'credentials.json', 'secret_key']) {
      const r = decideToolCall('read', { path: p });
      assert.equal(r.block, true, `${p} 应被拦截`);
    }
  });
});

describe('decideToolCall · 数据库直连拦截', () => {
  it('bash psql → block', () => {
    const r = decideToolCall('bash', { cmd: 'psql -U user -d db' });
    assert.equal(r.block, true);
    assert.match(r.reason ?? '', /红线#2.*直连数据库/);
  });

  it('bash mysql / sqlite3 → block', () => {
    for (const cmd of ['mysql -u root', 'sqlite3 data.db']) {
      const r = decideToolCall('bash', { cmd });
      assert.equal(r.block, true, `${cmd} 应被拦截`);
    }
  });
});

describe('decideToolCall · 已知工具放行', () => {
  it('query_reviews → 不 block', () => {
    const r = decideToolCall('query_reviews', { series_key: '银河E5' });
    assert.equal(r.block, false);
  });

  it('query_sales / query_config / resolve_series → 不 block', () => {
    for (const name of ['query_sales', 'query_config', 'resolve_series']) {
      const r = decideToolCall(name, { series_key: '银河E5' });
      assert.equal(r.block, false, `${name} 应放行`);
    }
  });

  it('sentiment_overview / get_trims / score_models → 不 block', () => {
    for (const name of ['sentiment_overview', 'get_trims', 'score_models']) {
      const r = decideToolCall(name, { vehicle_name: '银河E5' });
      assert.equal(r.block, false, `${name} 应放行`);
    }
  });

  it('pi 内置工具（read/glob/grep/bash 无敏感内容）→ 不 block', () => {
    const r = decideToolCall('read', { path: 'src/verify/grounding.ts' });
    assert.equal(r.block, false);
  });
});

describe('KNOWN_BUSINESS_TOOLS / BUSINESS_PREFIXES · 配置完整性', () => {
  it('白名单含 23 个业务工具', () => {
    // 3 query + 7 sentiment + 11 dashboards + resolve_series + submit_conclusion = 23
    // 2026-10-08 迁移适配：Atuohome 14→10（4 个退役：代际/能耗/新闻/报价，8010 无等价）
    // 2026-10-13 配置赋值口径改造：+compare_configs_valued（差价引擎出口）
    // 2026-10-20 舆情工具层跟进：+sentiment_defects（缺陷话题簇）
    assert.equal(KNOWN_BUSINESS_TOOLS.size, 23);
    assert.ok(KNOWN_BUSINESS_TOOLS.has('query_reviews'));
    assert.ok(KNOWN_BUSINESS_TOOLS.has('resolve_series'));
    assert.ok(KNOWN_BUSINESS_TOOLS.has('compare_configs_valued'));
    assert.ok(KNOWN_BUSINESS_TOOLS.has('sentiment_defects'));
  });

  it('业务前缀 6 个', () => {
    assert.deepEqual(BUSINESS_PREFIXES, ['query_', 'sentiment_', 'search_', 'get_', 'score_', 'resolve_']);
  });
});

// ---------------------------------------------------------------------------
// 对象覆盖守卫（v1.5，2026-11-01）：题面点名对象漏答 → 执行层回灌
// 归因：multi-07 只答银河E5、漏零跑B10 与风云T7（2 分同源坏例）
// ---------------------------------------------------------------------------
describe('对象覆盖守卫 · 题面声明与漏答判定', () => {
  it('coverKeys：全名 + 含数字型号尾串（E5/B10/T7 可命中简称）', () => {
    assert.deepEqual(coverKeys('银河E5'), ['银河e5', 'e5']);
    assert.deepEqual(coverKeys('零跑B10'), ['零跑b10', 'b10']);
    // 无数字型号（元UP）只认全名——防 "UP" 误命中 SUV
    assert.deepEqual(coverKeys('比亚迪 元UP'), ['比亚迪元up']);
  });

  it('只答一个对象 → 另外两个进缺答清单', () => {
    const missing = findUncoveredObjects('银河E5 智能座舱 con 418 条', ['银河E5', '零跑B10', '风云T7']);
    assert.deepEqual(missing, ['零跑B10', '风云T7']);
  });

  it('三对象全覆盖（含简称与空格变体）→ 无缺答', () => {
    const reply = 'E5：con 418；零跑 B10：con 305；T7 舆情：630 帖';
    assert.deepEqual(findUncoveredObjects(reply, ['银河E5', '零跑B10', '风云T7']), []);
  });

  it('末尾声明「未覆盖：X」→ 视作已覆盖（不再回灌，防乒乓）', () => {
    const reply = '银河E5：con 418。未覆盖：零跑B10（库内无智舱口碑）、风云T7（舆情接口不可达）';
    assert.deepEqual(findUncoveredObjects(reply, ['银河E5', '零跑B10', '风云T7']), []);
  });

  it('declaredCoverObjects：多轮题按本轮 message 对齐（t2 只问 E5 不要求三对象）', () => {
    assert.equal(
      declaredCoverObjects('multi-07', 'E5和B10的智能座舱口碑，加上风云T7的舆情，一起说说').length, 3);
    assert.equal(declaredCoverObjects('multi-07', '把E5的智能座舱口碑展开讲讲').length, 0);
    assert.equal(declaredCoverObjects('multi-07', '未声明的第三轮').length, 0);
    assert.equal(declaredCoverObjects('cross-01', '分析银河E5的三维度').length, 0); // 未声明
    assert.equal(declaredCoverObjects('no-such-task', 'x').length, 0);
  });
});
