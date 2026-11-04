"""扫描≤30万车系的能源类型（纯电/增程/插混/其他），从 get_full_config 基本参数取。
并发限制 6，结果落 JSON。供"30万以下纯电+增程+插混在售车型数"统计。"""
import sys, asyncio, re, json, os, time
sys.path.insert(0, '.')
sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None
from src.api.autohome_api import get_autohome_api, close_autohome_api

def _check_price(price_range, pmax=30.0):
    if not price_range: return False
    nums = re.findall(r'[\d.]+', price_range.replace(',', ''))
    vals = [float(n) for n in nums if 0 < float(n) < 1000]
    return bool(vals) and vals[0] <= pmax

def _classify_energy(cfg):
    """从 get_full_config categories 的基本参数取'能源类型'值。"""
    cats = cfg.get('categories', {}) if isinstance(cfg, dict) else {}
    base = cats.get('基本参数', {}) or {}
    for k, v in base.items():
        if '能源类型' in k or '能源' in k:
            val = ""
            if isinstance(v, dict):
                vals = [str(x).strip() for x in v.values() if x]
                val = vals[0] if vals else ""
            else:
                val = str(v).strip()
            low = val.lower()
            if '纯电' in val or 'bev' in low or '电动' in val:
                return '纯电'
            if '增程' in val or 'rev' in low:
                return '增程'
            if '插' in val and ('混' in val or 'phev' in low) or 'dm-i' in low or 'dm-p' in low or 'dmh' in low:
                return '插混'
            if '混动' in val and '插' not in val and '增' not in val:
                return '油电混动'
            if '汽油' in val or '柴油' in val or '燃油' in val:
                return '燃油'
            return val or '未知'
    return '未知'

async def main():
    api = await get_autohome_api()
    index = await api.build_series_index()
    cheap = [(sid, s) for sid, s in index.items() if _check_price(s.get('price_range', ''))]
    print(f'起售价≤30万: {len(cheap)} 车系，开始查能源类型...', flush=True)
    sem = asyncio.Semaphore(6)
    results = {}
    t0 = time.time()
    done = 0
    async def fetch_one(sid, s):
        nonlocal done
        async with sem:
            try:
                cfg = await api.get_full_config(sid)
                en = _classify_energy(cfg)
                # 在售判断：get_series_specs 返回在售版型，空=停售
                specs = await api.get_series_specs(sid)
                on_sale = '在售' if specs else '停售'
            except Exception as e:
                en = f'ERR:{e!r}'[:40]
                on_sale = '未知'
            results[sid] = {'name': s['name'], 'price': s.get('price_range',''), 'level': s.get('level',''), 'energy': en, 'sale_state': on_sale}
            done += 1
            if done % 50 == 0:
                print(f'  进度 {done}/{len(cheap)} 用时{time.time()-t0:.0f}s', flush=True)
    await asyncio.gather(*[fetch_one(sid, s) for sid, s in cheap])
    # 统计
    counts = {}
    for r in results.values():
        en = r['energy']
        counts[en] = counts.get(en, 0) + 1
    print(f'\n===== 统计（≤30万起售） =====', flush=True)
    for en, c in sorted(counts.items(), key=lambda x: -x[1]):
        print(f'  {en}: {c}', flush=True)
    # 只看在售
    sale_counts = {}
    for r in results.values():
        if r.get('sale_state') == '在售':
            en = r['energy']
            sale_counts[en] = sale_counts.get(en, 0) + 1
    print(f'\n===== 只看在售（≤30万） =====', flush=True)
    for en, c in sorted(sale_counts.items(), key=lambda x: -x[1]):
        print(f'  {en}: {c}', flush=True)
    target = {'纯电','增程','插混'}
    target_onsale = sum(c for en, c in sale_counts.items() if en in target)
    print(f'\n纯电+增程+插混 在售合计: {target_onsale}', flush=True)
    print(f'  其中 纯电: {sale_counts.get("纯电",0)} / 增程: {sale_counts.get("增程",0)} / 插混: {sale_counts.get("插混",0)}', flush=True)
    out = {'generated_at': time.strftime('%Y-%m-%d %H:%M'), 'total_cheap': len(cheap), 'counts': counts, 'sale_counts': sale_counts, 'target_onsale': target_onsale, 'series': results}
    with open('docs/30w以下能源类型扫描-2026-09-26.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'已落 docs/30w以下能源类型扫描-2026-09-26.json', flush=True)
    await close_autohome_api()

asyncio.run(main())
