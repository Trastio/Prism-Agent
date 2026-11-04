import sqlite3, json, re
from collections import defaultdict, Counter
from pathlib import Path as _Path
# 绝对派生（不依赖 CWD）：<prism-dashboards>/data/autohome.db
con = sqlite3.connect(str(_Path(__file__).resolve().parent.parent / 'data' / 'autohome.db'))
con.row_factory = sqlite3.Row
from src.scraper.collector import TAG_KEYWORDS

def jget(x):
    if not x: return None
    if isinstance(x, dict): return x
    try: return json.loads(x)
    except: return None

def num(s):
    if s is None: return None
    m = re.findall(r'[\d.]+', str(s))
    return float(m[0]) if m else None

def analyze(sid, name):
    print('\n'+'='*70)
    print(f'# {name}  (series_id={sid})')
    print('='*70)
    summ = con.execute('SELECT * FROM series_summaries WHERE series_id=?',(sid,)).fetchone()
    print(f'[概览] {summ["brand_name"]} | {summ["level_name"]} | {summ["price_range"]}万 | 均分{summ["average_score"]} | 口碑{summ["review_count"]}条(在售{summ["onsell_review_count"]}) | PPH百人故障率={summ["pph"]} | 同级排名{summ["level_rank"]}/{summ["level_series_count"]}')
    # series 维度分
    ds = jget(summ["dimension_scores"]) or []
    print('[车系维度评分-汽车之家]', {d["name"]:d["score"] for d in ds}, 'rank:', {d["name"]:d.get("rank") for d in ds})

    rows = con.execute('SELECT * FROM owner_reviews WHERE model_id=?',(sid,)).fetchall()
    # 聚合维度均分
    dim_acc = defaultdict(list)
    for r in rows:
        d = jget(r["dimensions"])
        if isinstance(d, dict):
            for k,v in d.items():
                try: dim_acc[k].append(float(v))
                except: pass
    print('[口碑维度均分-自聚合 n=%d]'%len(rows), {k: round(sum(v)/len(v),2) for k,v in sorted(dim_acc.items(), key=lambda x:-sum(x[1])/len(x[1]))})

    # 买点/槽点关键词
    best_texts = [(r["best_review_text"] or '') for r in rows if (r["best_review_text"] or '').strip()]
    worst_texts= [(r["worst_review_text"] or '') for r in rows if (r["worst_review_text"] or '').strip()]
    base_best = len(best_texts); base_worst = len(worst_texts)
    print(f'[原文] best={base_best}条 worst={base_worst}条')
    def kwstat(sentiment, texts, base):
        res=[]
        for tag,kws in TAG_KEYWORDS[sentiment].items():
            c=sum(1 for t in texts if any(k in t for k in kws))
            if c>0: res.append((tag,c,round(c/base*100,1)))
        res.sort(key=lambda x:-x[1])
        return res
    print('[买点TOP best文本命中]', [(t,c,f'{p}%') for t,c,p in kwstat('pro',best_texts,base_best)][:8])
    print('[槽点TOP worst文本命中]', [(t,c,f'{p}%') for t,c,p in kwstat('con',worst_texts,base_worst)][:8])

    # 能耗续航 exinfo
    cons=[]; rng=[]; price=[]
    for r in rows:
        ex=jget(r["exinfo"])
        if isinstance(ex,dict):
            for k,v in ex.items():
                vl=str(v)
                if any(x in k for x in ['电耗','能耗']) and 'kWh' in vl:
                    n=num(vl); 
                    if n and 5<=n<=30: cons.append(n)
                if '续航' in k and 'km' in vl:
                    n=num(vl)
                    if n and 100<=n<=800: rng.append(n)
                if '裸车' in k:
                    n=num(vl)
                    if n and 3<=n<=40: price.append(n)
    def stat(x): return f'均值{round(sum(x)/len(x),1)}(min{min(x)}-max{max(x)},n={len(x)})' if x else '无数据'
    print(f'[真实能耗] 夏季电耗: {stat(cons)}')
    print(f'[真实续航] 满电续航: {stat(rng)}')
    print(f'[真实裸车价] {stat(price)}')

    # 版本分布
    specs=Counter((r["spec_name"] or '未指定') for r in rows)
    print('[版本分布TOP5]', [(s,c) for s,c in specs.most_common(5)])

    # 原话采样 - 买点
    def sample(texts, kws, n=4):
        out=[]
        for t in texts:
            if any(k in t for k in kws) and 25<=len(t)<=180:
                out.append(t.strip())
            if len(out)>=n: break
        return out
    print('[买点原话样本]')
    for tag in ['空间大','外观好看','性价比高','舒适性好','配置丰富','动力强','续航长']:
        kws=TAG_KEYWORDS['pro'].get(tag,[])
        s=sample(best_texts,kws,2)
        if s:
            for it in s[:1]: print(f'   ({tag}) "{it[:130]}"')
    print('[槽点原话样本]')
    for tag in ['空间小','舒适性差','续航短','内饰差','性价比低','操控差','动力弱']:
        kws=TAG_KEYWORDS['con'].get(tag,[])
        s=sample(worst_texts,kws,2)
        if s:
            for it in s[:1]: print(f'   ({tag}) "{it[:130]}"')

for sid,name in [('8087','海狮06'),('8006','零跑B01'),('6998','小鹏MONA M03')]:
    analyze(sid,name)
con.close()
print('\n=== 分析完成 ===')
