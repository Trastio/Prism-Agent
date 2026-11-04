#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
B 系列编造率 SQL 抽检器（预注册：§10.2 "编造率 SQL 抽检 20 条"）
用法：
  python eval/fabrication_spotcheck.py eval/reports/challenger-challenger-b1a.json
只读快照库（mode=ro），对报告 audit 清单逐题比对 reply_numbers 是否可复算。
缺集合命中 → 编造候选（人工对照 reply_full 复核：派生数/百分比/万元换算属合法）。
"""
import json, re, sqlite3, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP = os.path.join(ROOT, 'eval', 'snapshots', 'snap-20261012-1222')

def variants(v):
    """一个库值的自然变体（万元换算/百分比化），回应回复侧表达差异。"""
    out = set()
    for x in (v, round(v, 2), int(v) if v == int(v) else v):
        out.add(x)
    if abs(v) > 10000:
        w = v / 10000.0
        out |= {round(w, 2), round(w, 1), round(w)}
    if 0 < abs(v) < 1:
        out |= {round(v * 100, 2), round(v * 100, 1), round(v * 100)}
    return out

def build_universe():
    uni = set()
    db = sqlite3.connect(f'file:{SNAP}/autohome.db?mode=ro', uri=True)
    for col in ['retail', 'msrp', 'tp', 'discount', 'mix', 'pre_msrp', 'ev_range',
                'wheelbase_mm', 'length_mm', 'displacement']:
        try:
            for (v,) in db.execute(f'SELECT DISTINCT ABS({col}) FROM sales_trim WHERE {col} IS NOT NULL'):
                if isinstance(v, (int, float)):
                    uni |= variants(v)
        except sqlite3.OperationalError:
            pass
    for col in ['score', 'buy_price']:
        for (v,) in db.execute(f'SELECT DISTINCT {col} FROM owner_reviews WHERE {col} IS NOT NULL'):
            if isinstance(v, (int, float)):
                uni |= variants(v)
    for col in ['review_count', 'min_price', 'max_price', 'average_score', 'consumption']:
        for (v,) in db.execute(f'SELECT DISTINCT {col} FROM series_summaries WHERE {col} IS NOT NULL'):
            if isinstance(v, (int, float)):
                uni |= variants(v)
    for (v,) in db.execute('SELECT DISTINCT confidence FROM review_tags WHERE confidence IS NOT NULL'):
        if isinstance(v, (int, float)):
            uni |= variants(v)
    # config_snapshots.categories JSON 文本里的裸数字（配置值：屏幕尺寸/扬声器数/续航等）
    for (txt,) in db.execute('SELECT categories FROM config_snapshots'):
        for m in re.finditer(r'\d+(?:\.\d+)?', txt or ''):
            uni.add(float(m.group()))
    db.close()
    # 舆情库（挑战者无舆情工具，理论零引用——仍入集合以免漏判）
    try:
        sdb = sqlite3.connect(f'file:{SNAP}/vehicle_sentiment.db?mode=ro', uri=True)
        tabs = [r[0] for r in sdb.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tabs:
            for c in sdb.execute(f'PRAGMA table_info("{t}")'):
                if c[2].upper() in ('INTEGER', 'REAL', 'FLOAT', 'NUMERIC'):
                    try:
                        for (v,) in sdb.execute(f'SELECT DISTINCT ABS("{c[1]}") FROM "{t}" WHERE "{c[1]}" IS NOT NULL'):
                            if isinstance(v, (int, float)):
                                uni |= variants(v)
                    except sqlite3.OperationalError:
                        pass
        sdb.close()
    except sqlite3.Error:
        pass
    return uni

def fmt(x):
    return str(int(x)) if isinstance(x, float) and x == int(x) else str(x)

def main():
    report_path = sys.argv[1] if len(sys.argv) > 1 else 'eval/reports/challenger-challenger-b1a.json'
    rep = json.load(open(report_path, encoding='utf-8'))
    audit = rep.get('audit') or []
    full = {r['task']: (r.get('reply_full') or '') for r in rep.get('results', [])}
    uni = build_universe()
    print(f'集合基数: {len(uni)} | audit 题数: {len(audit)}\n')
    tot_found = tot_all = 0
    for e in audit:
        nums, found, miss = e['reply_numbers'], [], []
        for n in nums:
            (found if (n in uni or float(n) in uni) else miss).append(n)
        tot_found += len(found); tot_all += len(nums)
        pct = 100 * len(found) / len(nums) if nums else 100
        flag = '⚠' if miss else ' '
        print(f'{flag} {e["task"]}: {len(found)}/{len(nums)}={pct:.0f}%', end='')
        if miss:
            print(f'  缺: {[fmt(m) for m in miss[:12]]}{"..." if len(miss) > 12 else ""}')
        else:
            print()
    print(f'\n合计: {tot_found}/{tot_all}={100 * tot_found / tot_all:.0f}% 可复算 | 缺口题人工复核 reply_full 后定编造')

if __name__ == '__main__':
    main()
