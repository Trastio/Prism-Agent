/** harness 登记收敛（2026-10-13）：真值信封收割 + 注册漂移检查的纯函数层。
 * 无 pi 依赖、无 IO——extension 调用方负责 appendEntry/console.error，本模块只算。 */

export interface TruthEnvelope {
  numbers: string[];
  names: string[];
}

const LEADING_NUM = /-?\d+(?:\.\d+)?/;

/** 从 compare_configs_valued / get_config_detail / get_trims 形态收割工具真值。
 * numbers：cells 前导数值（"410"/"15.4英寸"→410/15.4）+ price/amount/unit_price/msrp；
 * names：rows[].name（概念名）+ cols[].series_name/trim_name + trims[].name。
 * Set 去重；空/残缺响应返回空集。 */
export function harvestTruth(data: unknown): TruthEnvelope {
  const numbers = new Set<string>();
  const names = new Set<string>();
  if (!data || typeof data !== 'object') return { numbers: [], names: [] };
  const d = data as Record<string, any>;
  const pushNum = (v: unknown) => {
    if (typeof v === 'number') { if (Number.isFinite(v)) numbers.add(String(v)); return; }
    // P1-2（隔离审查）：千分位先去逗号防断章（"1,234"→1）；取全部数值段——
    // 区间 "11.98-14.98万" 两端都是工具真值，只取首段会误拒如实引用
    const s = String(v ?? '').replace(/,/g, '');
    if (!s) return;
    for (const m of s.matchAll(/\d+(?:\.\d+)?/g)) {
      const n = parseFloat(m[0]);
      if (Number.isFinite(n)) numbers.add(String(n));
    }
  };
  const pushName = (v: unknown) => {
    const s = typeof v === 'string' ? v.trim() : '';
    if (s) names.add(s);
  };
  for (const r of Array.isArray(d.rows) ? d.rows : []) {
    if (!r || typeof r !== 'object') continue;
    pushName(r.name);
    for (const c of Array.isArray(r.cells) ? r.cells : []) pushNum(c);
    pushNum(r.price); pushNum(r.amount); pushNum(r.unit_price);
  }
  for (const c of Array.isArray(d.cols) ? d.cols : []) {
    if (!c || typeof c !== 'object') continue;
    pushName(c.series_name); pushName(c.trim_name);
    pushNum(c.msrp); pushNum(c.price);
  }
  for (const t of Array.isArray(d.trims) ? d.trims : []) {
    if (!t || typeof t !== 'object') continue;
    pushName(t.name); pushNum(t.price);
  }
  // P1-1（隔离审查）：diff 段的金额（配置优势/拉平价/逐项金额）是 agent 结论的高频引用值，
  // 必须入真值集——否则如实引用 config_adv 即被拒"不在工具真值集"
  const diff = (d.diff && typeof d.diff === 'object') ? d.diff as Record<string, any> : null;
  if (diff) {
    pushNum(diff.config_adv); pushNum(diff.flat_adv);
    for (const c of Array.isArray(diff.columns) ? diff.columns : []) pushNum(c?.amount);
    const items = (diff.items && typeof diff.items === 'object') ? diff.items : null;
    if (items) for (const it of Object.values(items)) pushNum((it as any)?.amount);
  }
  return { numbers: [...numbers], names: [...names] };
}

/** D1 启动自检：三表互检 + 技能目录非空 + 真值发射方⊆业务白名单（P2-4）。返回漂移清单（空=健康），调用方 fail-loud。 */
export function collectRegistrationDrift(
  registered: Iterable<string>,
  truncatable: Iterable<string>,
  knownBusiness: Iterable<string>,
  skillsCount: number,
  truthEmitters?: Iterable<string>,
): string[] {
  const reg = new Set(registered);
  const drift: string[] = [];
  for (const t of truncatable) if (!reg.has(t)) drift.push(`截断表缺注册:${t}`);
  for (const t of knownBusiness) if (!reg.has(t)) drift.push(`业务白名单缺注册:${t}`);
  if (!(skillsCount > 0)) drift.push('技能目录为空或全部解析失败');
  if (truthEmitters) {
    const biz = new Set(knownBusiness);
    for (const t of truthEmitters) if (!biz.has(t)) drift.push(`真值发射方不在业务白名单:${t}`);
  }
  return drift;
}
