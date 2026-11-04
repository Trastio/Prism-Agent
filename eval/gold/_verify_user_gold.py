# -*- coding: utf-8 -*-
# 金标自检：从 user-20261013.json 取核心数字，对快照重算断言（红线#1 对我们也生效）
# D5（2026-10-14 评估迭代基建包）：PRISM_GOLD_FILE / PRISM_GOLD_SNAP env 可覆写
# 金标与快照路径（金标重算 dry-run 对演练体断言用）；缺省=生产路径，行为不变
import json, os, sqlite3, re, collections

_GOLD_FILE = os.environ.get('PRISM_GOLD_FILE', 'eval/gold/user-20261013.json')
_SNAP_DIR = os.environ.get('PRISM_GOLD_SNAP', 'eval/snapshots/snap-20261012-1222')

G = json.load(open(_GOLD_FILE, encoding='utf-8'))
by_id = {g['new_id']: g for g in G}
con = sqlite3.connect(f'file:{_SNAP_DIR}/autohome.db?mode=ro', uri=True)
cur = con.cursor()
sent = sqlite3.connect(f'file:{_SNAP_DIR}/vehicle_sentiment.db?mode=ro', uri=True)
sc = sent.cursor()
ok = fail = 0
def chk(name, cond, detail=''):
    global ok, fail
    if cond: ok += 1
    else:
        fail += 1
        print(f'FAIL: {name} {detail}')

def retail(s, y, m):
    return cur.execute("SELECT SUM(retail) FROM sales_trim WHERE series=? AND year=? AND month=?", (s, y, m)).fetchone()[0]

# sales
chk('E5 8末 total=4436', retail('银河E5',2026,'8月末')==4436)
chk('E5 星舰版=28', cur.execute("SELECT retail FROM sales_trim WHERE series='银河E5' AND year=2026 AND month='8月末' AND model_name LIKE '%星舰版'").fetchone()[0]==28)
chk('E5 9末 NULL', retail('银河E5',2026,'9月末') is None)
chk('E5 2025-9末=10377(历史年)', retail('银河E5',2025,'9月末')==10377)
chk('全库2026-9末无值', cur.execute("SELECT COUNT(*) FROM sales_trim WHERE year=2026 AND month='9月末' AND retail IS NOT NULL").fetchone()[0]==0)
chk('B10 27款=5218', cur.execute("SELECT SUM(retail) FROM sales_trim WHERE series='零跑 B10' AND year=2026 AND month='8月末' AND model_name LIKE '27款%'").fetchone()[0]==5218)
chk('B10 total=6790', retail('零跑 B10',2026,'8月末')==6790)
chk('MG4X total=3427', retail('MG 4X',2026,'8月末')==3427)
chk('MG4X 半固态自由版=408', cur.execute("SELECT retail FROM sales_trim WHERE series='MG 4X' AND year=2026 AND month='8月末' AND model_name LIKE '%半固态自由版'").fetchone()[0]==408)
chk('E5 探索版=2047', cur.execute("SELECT retail FROM sales_trim WHERE series='银河E5' AND year=2026 AND month='8月末' AND model_name LIKE '%探索版'").fetchone()[0]==2047)
chk('星愿=39386', retail('吉利星愿',2026,'8月末')==39386)
chk('海豚=16879', retail('比亚迪 海豚',2026,'8月末')==16879)
chk('启源Q05=13928', retail('启源Q05 纯电',2026,'8月末')==13928)
chk('荣放双擎=10568', retail('荣放 双擎',2026,'8月末')==10568)
chk('星越L=9100', retail('星越L',2026,'8月末')==9100)
chk('博越L=9067', retail('博越L',2026,'8月末')==9067)
chk('QQ3EV=12129', retail('奇瑞 QQ3 EV',2026,'8月末')==12129)
chk('风云A9=5796', retail('风云A9',2026,'8月末')==5796)
chk('iCAR V23=2479', retail('iCAR V23',2026,'8月末')==2479)
chk('T7 全库零售空', cur.execute("SELECT COUNT(*) FROM sales_trim WHERE series='风云T7' AND retail IS NOT NULL").fetchone()[0]==0)
chk('海狮06EV=8918', retail('比亚迪 海狮06 EV',2026,'8月末')==8918)
chk('海狮06DMi=4517', retail('比亚迪 海狮06 DM-i',2026,'8月末')==4517)
chk('A10=25084', retail('零跑 A10',2026,'8月末')==25084)

# config
def cat(sid): return json.loads(cur.execute("SELECT categories FROM config_snapshots WHERE series_id=?", (sid,)).fetchone()[0])
e5 = cat('7650')
chk('E5 顶配=78132 635智充激光 14.78万', e5['基本参数']['车型名称']['78132']=='银河E5 2027款 635 智充激光版' and e5['基本参数']['厂商指导价(元)']['78132']=='14.78万')
chk('E5 无27款销量行', cur.execute("SELECT COUNT(*) FROM sales_trim WHERE series='银河E5' AND model_name LIKE '%27款%'").fetchone()[0]==0)
t7 = cat('8660')
chk('T7 顶配=77784 11.89万', t7['基本参数']['车型名称']['77784']=='风云T7 2026款 600km 智享版' and t7['基本参数']['厂商指导价(元)']['77784']=='11.89万')
chk('T7 热泵全系●', all(v=='●' for v in t7['空调/冰箱']['热泵空调'].values()) and len(t7['空调/冰箱']['热泵空调'])==3)
chk('E5 热泵全系●', all(v=='●' for v in e5['空调/冰箱']['热泵空调'].values()) and len(e5['空调/冰箱']['热泵空调'])==12)
chk('T7/E5/B10 无PTC字段', all('PTC' not in json.dumps(cat(s), ensure_ascii=False).upper() for s in ['8660','7650','7877']))
b10 = cat('7877')
chk('B10 顶配=79024 540行政 14.98万', b10['基本参数']['车型名称']['79024']=='零跑B10 2027款 540行政版' and b10['基本参数']['厂商指导价(元)']['79024']=='14.98万')
h6 = cat('8087')
n_ev = sum(1 for n in h6['基本参数']['车型名称'].values() if 'EV' in n)
n_dm = sum(1 for n in h6['基本参数']['车型名称'].values() if 'DM-i' in n)
chk('海狮06 EV8+DMi7=15', n_ev==8 and n_dm==7 and len(h6['基本参数']['车型名称'])==15)
chk('MG4X 顶配=76775', cat('8564')['基本参数']['车型名称']['76775']=='MG 4X 2026款 610 智享版')
a9 = cat('7853')
chk('A9 MAX激光雷达 75849 零重力=副驾驶', a9['基本参数']['车型名称']['75849']=='风云A9 2026款 655 MAX激光雷达版')
zg = [v for it, vals in a9['座椅配置'].items() if '零重力' in it for v in [vals.get('75849')]]
chk('A9 零重力座椅(副驾驶)', zg and '副驾驶' in str(zg[0]))
chk('A10 无config行', cur.execute("SELECT COUNT(*) FROM config_snapshots WHERE series_id='8433'").fetchone()[0]==0)
chk('911/T1000/N9/B1 不在 summaries', all(cur.execute("SELECT COUNT(*) FROM series_summaries WHERE series_name=?",(n,)).fetchone()[0]==0 for n in ['保时捷911','风云T1000','腾势N9','零跑B1']))
chk('B10/B01 并存', all(cur.execute("SELECT COUNT(*) FROM series_summaries WHERE series_name=?",(n,)).fetchone()[0]==1 for n in ['零跑B10','零跑B01']))

# reviews
def rc(mid, cat_=None, sent_=None):
    q = "SELECT COUNT(*) FROM review_tags WHERE CAST(model_id AS TEXT)=?" + (f" AND tag_category='{cat_}'" if cat_ else '') + (f" AND sentiment='{sent_}'" if sent_ else '')
    return cur.execute(q, (mid,)).fetchone()[0]
chk('E5 智能化con=418', rc('7650','智能化','con')==418)
chk('E5 舒适con=313', rc('7650','舒适','con')==313)
chk('B10 智能化 净-157', rc('7877','智能化','pro')-rc('7877','智能化','con')==-157)
chk('T7 智能化标签=28', rc('8660','智能化')==28)
chk('海狮05 2026款=134', cur.execute("SELECT COUNT(*) FROM review_tags WHERE CAST(model_id AS TEXT)='7982' AND model_full_name LIKE '2026款%'").fetchone()[0]==134)
chk('海狮06 DMi205领航Pro pro87/con60', cur.execute("SELECT SUM(sentiment='pro'), SUM(sentiment='con') FROM review_tags WHERE CAST(model_id AS TEXT)='8087' AND model_full_name='2025款 DM-i 205领航Pro版'").fetchone()==(87,60))
chk('四车好评率', all(abs(cur.execute("SELECT SUM(sentiment='pro')*1.0/(SUM(sentiment='pro')+SUM(sentiment='con')) FROM review_tags WHERE CAST(model_id AS TEXT)=?",(m,)).fetchone()[0]-r)<0.005 for m,r in [('7650',0.592),('7877',0.545),('8660',0.508),('8564',0.622)]))
chk('A10/星愿 review_tags=0', rc('8433')==0 and rc('7806')==0)
chk('MG4 标签好评率61.6%', abs(cur.execute("SELECT SUM(sentiment='pro')*1.0/(SUM(sentiment='pro')+SUM(sentiment='con')) FROM review_tags WHERE CAST(model_id AS TEXT)='6651'").fetchone()[0]-0.616)<0.005)

# sentiment
def sv(nm): return sc.execute("SELECT id FROM vehicles WHERE name=?", (nm,)).fetchone()[0]
def sent_dist(nm):
    vid = sv(nm)
    d = dict(sc.execute("SELECT sentiment, COUNT(*) FROM analyzed_posts WHERE vehicle_id=? GROUP BY sentiment", (vid,)).fetchall())
    return d
chk('风云A9 718=503+123+92', sent_dist('风云A9')=={'positive':503,'neutral':123,'negative':92})
chk('T7 630=488+117+25', sent_dist('风云T7')=={'positive':488,'neutral':117,'negative':25})
chk('QQ3 398=222+59+117', sent_dist('QQ3')=={'positive':222,'neutral':59,'negative':117})
chk('星愿 1263=813+288+162', sent_dist('星愿')=={'positive':813,'neutral':288,'negative':162})
chk('星愿负面帖ID存在', sc.execute("SELECT COUNT(*) FROM raw_posts WHERE id IN ('eb965fb0-3002-47f8-b15a-84880db27692','3ae4a25a-a8f6-42c2-b965-b3d8743436a9','38ea60e6-c092-4b16-bd2e-d9d6087cd387')").fetchone()[0]==3)
chk('MG4X 在舆情库(explore误)', sc.execute("SELECT COUNT(*) FROM vehicles WHERE REPLACE(name,' ','')='MG4X'").fetchone()[0]==1)
# ---- Step7 P2-3 固化（审查代查断言，防快照更新后静默漂移）----
import json as _json
from collections import Counter as _Counter
def _neg_topics(vehicle):
    rows = sc.execute("SELECT a.sentiment, a.event_tags FROM analyzed_posts a JOIN vehicles v ON a.vehicle_id=v.id WHERE v.name=? AND a.event_tags IS NOT NULL", (vehicle,)).fetchall()
    c = _Counter()
    for s, tags in rows:
        try: tl = _json.loads(tags)
        except Exception: continue
        if s == 'negative':
            for t in tl: c[t] += 1
    return c
_nt = _neg_topics('QQ3')
chk('sentiment-05 负面话题top7=金标(售后83/质量67/异响57/维权33/提车32/4S店19/交付8)',
    [_nt.get(k, 0) for k in ['售后服务','质量问题','异响/故障','维权投诉','提车分享','4S店纠纷','交付延迟']] == [83,67,57,33,32,19,8])
_bev = con.execute("""SELECT series FROM sales_trim WHERE year=2026 AND month='8月末' AND retail IS NOT NULL AND CAST(retail AS TEXT)!=''
    AND energy_type='纯电动' AND (REPLACE(IFNULL(brand,''),' ','') LIKE '%奇瑞%' OR REPLACE(IFNULL(manufacturer,''),' ','') LIKE '%奇瑞%')
    GROUP BY series ORDER BY SUM(retail) DESC LIMIT 3""").fetchall()
chk('sales-09 奇瑞集团BEV top3=金标', [r[0] for r in _bev] == ['奇瑞 QQ3 EV','风云A9','iCAR V23'])
chk('sentiment-08 风云T1000 舆情库不存在', sc.execute("SELECT COUNT(*) FROM vehicles WHERE name LIKE '%T1000%'").fetchone()[0] == 0)
# supported_by 格式门禁自检：sales_trim 引用串须原生 series 存在
for g in G:
    for ref in g['gold'].get('supported_by', []):
        t, rest = ref.split(':', 1)
        p = rest.split('/')
        if t == 'sales_trim':
            chk(f"ref {ref} 原生串在库", cur.execute("SELECT COUNT(*) FROM sales_trim WHERE series=? AND year=?",(p[0],int(p[1]))).fetchone()[0]>0)
        elif t == 'review_tags':
            chk(f"ref {ref} 在库", cur.execute("SELECT COUNT(*) FROM review_tags WHERE CAST(model_id AS TEXT)=? AND tag_category=?",(p[0],p[1])).fetchone()[0]>0)
        elif t == 'config_snapshots':
            chk(f"ref {ref} 在库", cur.execute("SELECT COUNT(*) FROM config_snapshots WHERE series_id=?",(p[0],)).fetchone()[0]>0)
        elif t == 'sentiment_overview':
            chk(f"ref {ref} 车在库", sc.execute("SELECT COUNT(*) FROM vehicles WHERE REPLACE(name,' ','')=?",(p[0].replace(' ',''),)).fetchone()[0]>0)
        elif t == 'sentiment_dimension':
            dim = '/'.join(p[1:]); vid = sv(p[0])
            chk(f"ref {ref} 维度在库", sc.execute("SELECT COUNT(*) FROM analyzed_posts WHERE vehicle_id=? AND dim_sentiment LIKE ?",(vid,f'%"{dim}"%')).fetchone()[0]>0)
        elif t == 'sentiment_posts':
            chk(f"ref {ref} 帖在库", sc.execute("SELECT COUNT(*) FROM raw_posts WHERE id=?",(p[0],)).fetchone()[0]>0)
print(f'\n自检结果: OK={ok} FAIL={fail}')
