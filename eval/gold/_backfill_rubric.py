# -*- coding: utf-8 -*-
"""rubric_params 回填（Step8 P1-1）：把三类中间档判分挂到已知题型上。幂等可复跑。
- ranking：top3 名单从金标 gold.numbers 提取（含数字元组的取[0]，纯名单直取），hard_first=首位
- sentiment_pattern：sentiment-03..07（五要素默认集）
- gap：仅 web-缺口题（config-03/04/10）——纯库内缺口题（sales-04/11/12）不挂：
  gap 要素含 URL+不可复算，对"声明无数据即可"的题会过度惩罚（要素子集能力留 P2，见 review-response）
"""
import json, re, sys
GOLD = json.load(open('eval/gold/user-20261013.json', encoding='utf-8'))
TASKS = json.load(open('eval/tasks.json', encoding='utf-8'))
gmap = {g['new_id']: g for g in GOLD}

RANKING = ['sales-08', 'sales-09', 'sales-10', 'config-07']
SENTIMENT = ['sentiment-03', 'sentiment-04', 'sentiment-05', 'sentiment-06', 'sentiment-07']
GAP = ['config-03', 'config-04', 'config-10']

def extract_top3(g):
    nums = g.get('gold', {}).get('numbers', {})
    for k, v in nums.items():
        if isinstance(v, list) and len(v) >= 3 and all(isinstance(x, (list, str)) for x in v[:3]):
            names = [re.sub(r'\s*[\d,]+\s*$', '', (x[0] if isinstance(x, list) else x)).strip() for x in v[:3]]
            if all(isinstance(n, str) and n for n in names):
                return names
    return None

for t in TASKS:
    tid = t['id']
    if tid in RANKING:
        top3 = extract_top3(gmap[tid])
        assert top3, f'{tid} 提取 top3 失败'
        t['rubric_params'] = {'kind': 'ranking', 'gold_top3': top3, 'candidates': top3, 'hard_first': top3[0]}
        print(f'{tid}: ranking top3={top3}')
    elif tid in SENTIMENT:
        t['rubric_params'] = {'kind': 'sentiment_pattern'}
        print(f'{tid}: sentiment_pattern')
    elif tid in GAP:
        t['rubric_params'] = {'kind': 'gap'}
        print(f'{tid}: gap')

n = sum(1 for t in TASKS if t.get('rubric_params'))
assert len(TASKS) == 60
json.dump(TASKS, open('eval/tasks.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print(f'rubric_params 挂载 {n} 题')
