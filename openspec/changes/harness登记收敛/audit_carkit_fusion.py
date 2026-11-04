# -*- coding: utf-8 -*-
"""carkit 融合对账审计：逐项比对 carkit(HEAD) 与 Prism diff_pricing/concept_configs。"""
import json, base64, subprocess, urllib.request, urllib.parse

TOK = subprocess.run(['gh', 'auth', 'token'], capture_output=True, text=True).stdout.strip()

def gh_get(path):
    p = urllib.parse.quote(path)
    req = urllib.request.Request(f'https://api.github.com/repos/a18012239736-rgb/carkit/contents/{p}')
    req.add_header('Authorization', f'Bearer {TOK}')
    d = json.load(urllib.request.urlopen(req))
    return base64.b64decode(d['content']).decode('utf-8')

# ---- carkit HEAD ----
import re, ast
valuer_src = gh_get('engine/valuer.py')
def _grab(name):
    m = re.search(name + r'\s*=\s*(\{.*?\n\})', valuer_src, re.S)
    return ast.literal_eval(m.group(1))
CK_DYN = _grab('DEFAULT_DYNAMIC_PARAMS')
m = re.search(r'DEFAULT_FLAT\s*=\s*\{(.*?)\}\n', valuer_src, re.S)
CK_FLAT = {int(k): int(v) for k, v in re.findall(r'(\d+):\s*(\d+)', m.group(1))}
m2 = re.search(r'EXCLUDED_ITEMS\s*=\s*\{([^}]*)\}', valuer_src)
CK_EXCLUDED = {int(x) for x in re.findall(r'\d+', m2.group(1))} if m2 else set()
checklist = json.loads(gh_get('engine/rules/checklist_v1.json'))
ck_names = {it['no']: it['name'] for it in checklist['items']}

# ---- Prism 侧 ----
DP = json.load(open('prism-dashboards/data/diff_pricing.json', encoding='utf-8'))
CC = json.load(open('prism-dashboards/data/concept_configs.json', encoding='utf-8'))
our_ids = {c['id'] for c in CC}
excluded = set(DP['excluded']['ids'])
items = DP['items']

# ---- carkit no → Prism id 映射（design 逐项对账表）----
MAP = {
 1:['A1'], 2:[], 3:['A4'], 4:['B1'], 5:['D1','D2','D3'], 6:['M2'], 7:['K5','K6'],
 8:[], 9:['C1','C2'], 10:['B2'], 11:['E7'], 12:['F9'], 13:['E6'], 14:['E8'], 15:['E3'],
 16:['A5'], 17:['E9'], 18:['E1'], 19:[], 20:['H1','H2','H3','H4'], 21:['G1'], 22:['G4'],
 23:['J2'], 24:[], 25:['F16'], 26:['F13'], 27:['F12'], 28:['F13'], 29:['G2'], 30:['G3'],
 31:['H6'], 32:['G7'], 33:['G6'], 34:['F1'], 35:['F2'], 36:['F3','F4','F5'], 37:['G5'],
 38:['G8'], 39:['F11'], 40:['L3'], 41:['L2'], 42:['D4'], 43:['F10'], 44:['L1'], 45:['F6'],
}
VERDICT = {
 1:'有意偏离(用户拍板:Prism 100元/km 无阈值)', 5:'简化融合(按项350;颗数差未建模)',
 7:'拆分融合(倒车360→K5/540→K6)', 9:'拆分融合(C2=3000为增量,数学等价)',
 10:'部分融合(铝+500在B1备注未建)', 12:'融合(flat 500;电动/手动档留迭代)', 20:'拆分融合(每功能100)',
 21:'融合(threshold 3寸±500)', 22:'偏离(实查G4=boolean无寸数,沿现weights 1700)', 26:'融合(并入F13=800+100)',
 28:'融合(记忆100并入F13)', 29:'部分融合(每寸100;lcd_bonus 200未建)', 33:'部分融合(一口价350;快慢充分计未建)',
 35:'简化融合(电调400;方向数差×50未建)', 36:'简化融合(每座价×前排2座)',
 1.5:'', 42:'融合(中央气囊 flat 350)',
}

rows = []
for no in sorted(CK_DYN.keys()) + [n for n in CK_FLAT if n not in CK_DYN]:
    kinds = []
    if no in CK_DYN: kinds.append('dynamic')
    if no in CK_FLAT: kinds.append(f'flat={CK_FLAT[no]}')
    ids = MAP.get(no, [])
    ours = []
    for i in ids:
        it = items.get(i)
        ours.append(f"{i}:{it['pricing']}" + (f"({it.get('val') or it.get('unit_price')})" if it else '(缺!)'))
    rows.append((no, ck_names.get(no, '?'), '+'.join(kinds), ids, ' | '.join(ours) or '未映射'))

print('=== carkit 45 项 → Prism 72 项 逐项对账 ===')
fused = simplified = deviated = missing = 0
for no, name, kinds, ids, ours in rows:
    tag = VERDICT.get(no, '')
    if not ids:
        cls = 'excluded' if no in (2, 8, 19, 24) else '未融合'
        if no == 8: cls = '已补K1(excluded)'
        if no == 42: cls = '已补D4'
        if no in (10,): cls = '已补B2'
        if no in (12, 15, 17, 23, 25, 32, 38, 41): cls = '已补'
    elif any('偏离' in tag for _ in [0]):
        cls = '偏离-' + tag
    elif '简化' in tag or '部分' in tag:
        cls = '简化/部分-' + tag
    else:
        cls = '等价融合'
    print(f'#{no:<3} {name[:10]:<12} carkit[{kinds[:50]}] → Prism[{ours[:60]}]  {cls}')
print()
print('Prism 项数:', len(our_ids), '| diff_pricing items:', len(items), '| excluded:', sorted(excluded))
print('carkit excluded(2/8/19/24):', sorted(CK_EXCLUDED), '→', '我们清单外/已排除')
