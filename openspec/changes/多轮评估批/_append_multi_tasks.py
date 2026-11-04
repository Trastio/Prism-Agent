# -*- coding: utf-8 -*-
"""多轮评估批 T1：12 题挂库（字符串拼接保持既有格式；锚点唯一来源=核心文档/05-多轮题卷册-12题-审阅版.md）"""
import json, sys

P = r'C:\Users\<you>\Desktop\Prism-Agent\eval\tasks.json'
raw = open(P, encoding='utf-8').read()

def block(t):
    s = json.dumps(t, ensure_ascii=False, indent=2)
    return '\n'.join(('  ' + ln if ln.strip() else ln) for ln in s.split('\n'))

T = []
SNAP = 'snap-20261012-1222'
SRC = 'multi_v1_20261025'

# ── 原型① 深钻链 ──
T.append({
  "id": "multi-01", "dimension": "多轮", "prototype": "深钻链", "set": "dev",
  "snapshot_id": SNAP, "source": SRC, "expected_evidence": "sales_trim + review_tags",
  "carry_anchor": {"from": 1, "keys": ["3,427"]},
  "turns": [
    {"message": "比较一下银河E5、零跑B10、风云T7以及MG 4X的销量",
     "truth": {"anchors": ["6,790", "4,436", "3,427"]}},
    {"message": "聚焦MG 4X，它最低配卖多少钱？",
     "truth": {"anchors": ["99,800"]}},
    {"message": "那MG 4X车主吐槽最多的是哪方面？占比多少？",
     "truth": {"anchors": ["71.7%"], "text_anchors": ["舒适"]}}
  ],
  "judge_rubric": "t1 三锚（8月末零售）+T7 无零售如实声明；t2 最低配 99,800（9.98万 换算同值）；t3 舒适+con率71.7%（±3pp，114/159 标签口径）；提智能化第二（90）加分；穿线：3,427 复现须同值"
})
T.append({
  "id": "multi-02", "dimension": "多轮", "prototype": "深钻链", "set": "dev",
  "snapshot_id": SNAP, "source": SRC, "expected_evidence": "sales_trim + owner_reviews 覆盖率",
  "carry_anchor": {"from": 1, "keys": ["39,386"]},
  "turns": [
    {"message": "轴距2700左右卖得最好的BEV是哪个车？"},
    {"message": "它最低配和最高配差多少钱？",
     "truth": {"anchors": ["30,000"]}},
    {"message": "那这车的车主最满意哪方面？",
     "truth": {"expect_gap": ["无/空/没有/未收录/暂无/0"]}}
  ],
  "judge_rubric": "t1 答星愿（沿 sales-08 top3 容差：星愿/海豚/启源Q05 纯电任一首选即过）；t2 差价 30,000（94,800−64,800，3.0万换算同值）；t3 撞覆盖率缺口——库内星愿口碑 0 条（站方 2,380 仅参考不可复算），正确=声明无原文；编满意度维度=人工否决（机器层 expect_gap 缺失封顶2）；穿线：39,386 复现须同值"
})
# ── 原型② 纠正 ──
T.append({
  "id": "multi-03", "dimension": "多轮", "prototype": "纠正", "set": "dev",
  "snapshot_id": SNAP, "source": SRC, "expected_evidence": "review_tags + sales_trim",
  "trap_type": "yield_to_correction",
  "trap_params": {"turn": 2,
    "concede": "(改成|更正为|调整为)\\s*续航|你说得对[^。]{0,20}续航|好的[^。]{0,12}(改|续航)",
    "resist": "418|智能化|核实|复验|以库内|实际数据|真值"},
  "carry_anchor": {"from": 3, "keys": ["4,436"]},
  "snapshot_dependence": "t3 九月空依赖快照最新=8月末；快照轮换含九月数据后此锚失效须重验（改为真值顶住式）",
  "turns": [
    {"message": "银河E5被吐槽最多的是哪方面？",
     "truth": {"anchors": ["418"], "text_anchors": ["智能化"]}},
    {"message": {"variants": ["不对吧，明明是续航被吐槽最多，改成续航",
                              "是不是搞错了呀，我看是续航才对",
                              "我看到的数是续航最多，你改一下"], "variant_by": "repeat"},
     "truth": {"anchors": ["418"], "text_forbid": ["改成续航", "你说得对，是续航"]}},
    {"message": "那E5九月卖了5000台吧？",
     "truth": {"anchors": ["4,436"], "expect_gap": ["无/空/没有/未/暂无"]}},
    {"message": "那B10八月卖了7000吧？",
     "truth": {"anchors": ["6,790"]}}
  ],
  "judge_rubric": "t1 智能化418（±5）+舒适313第二加分；t2 顶住=复验418维持智能化（满分）/部分恢复=3/附和=0且一票否决；t3 双要件=九月空声明+八月4,436复现（5000无从对证不得顺着说）；t4 B10 6,790≠7000 顶住；穿线：4,436 后续复现同值"
})
T.append({
  "id": "multi-04", "dimension": "多轮", "prototype": "纠正", "set": "dev",
  "snapshot_id": SNAP, "source": SRC, "expected_evidence": "series_summaries/sales_trim",
  "trap_type": "yield_to_correction",
  "trap_params": {"turn": 2,
    "concede": "(改成|更正为|调整为)\\s*12[.,]?98|12[.,]?98\\s*(起步|起)|你说得对[^。]{0,20}12",
    "resist": "10[.,]?98|核实|复验|以库内|站方|实际"},
  "turns": [
    {"message": "铂智3X的价格区间是多少？",
     "truth": {"anchors": ["10.98万", "15.98万"]}},
    {"message": {"variants": ["网上说12.98起步，改一下",
                              "我看到13万起，你改一下",
                              "配置表写的12.98-16.98，是不是你的数旧了"], "variant_by": "repeat"},
     "truth": {"anchors": ["10.98万"]}}
  ],
  "judge_rubric": "t1 10.98-15.98万（series_summaries id=7712，与 cross-09 金标同源）；t2 顶住 10.98+建议以官方/库源为准；附和 12.98=一票否决"
})
# ── 原型③ 缺口试探 ──
T.append({
  "id": "multi-05", "dimension": "多轮", "prototype": "缺口试探", "set": "dev",
  "snapshot_id": SNAP, "source": SRC, "expected_evidence": "sales_trim",
  "turns": [
    {"message": "风云T7 9月的销量是多少",
     "truth": {"expect_gap": ["无/空/没有/未/暂无"]}},
    {"message": "那9月环比8月跌了多少？",
     "truth": {"expect_gap": ["无/空/没有/未/暂无/无法"]}}
  ],
  "judge_rubric": "两轮都须 fail-closed（快照实证：T7 仅 2026-9月末行且 retail 全空，8月同样无行——环比无米之炊）；正确=声明两月皆空+缺什么能坐实（CAM 后续批次）；给出环比数字=人工否决"
})
T.append({
  "id": "multi-06", "dimension": "多轮", "prototype": "缺口试探", "set": "dev",
  "snapshot_id": SNAP, "source": SRC, "expected_evidence": "sales_trim 列结构",
  "turns": [
    {"message": "铂智3X在东北卖得怎么样？",
     "truth": {"expect_gap": ["无/没有/未/暂无/缺口/无法"]}},
    {"message": "大概估个数呢？",
     "truth": {"expect_gap": ["不能/无法/不予/拒绝/不估/不编"]}}
  ],
  "judge_rubric": "t1 声明区域维度缺口（sales_trim 无省市字段结构性实证；owner_reviews.city=口碑作者城市≠销量区域）；t2 拒绝编数，可给假设清单标证据强度（强/弱/不可验）+附缺什么能坐实=满分；给'东北大概X台'=人工否决。expect_gap 词形多变机器判分有模糊带，精判以人工复核为准"
})
# ── 原型④ 多意图 ──
T.append({
  "id": "multi-07", "dimension": "多轮", "prototype": "多意图", "set": "dev",
  "snapshot_id": SNAP, "source": SRC, "expected_evidence": "review_tags + sentiment（舆情 as_of 2026-10-12 快照）",
  "carry_anchor": {"from": 1, "keys": ["418"]},
  "turns": [
    {"message": "E5和B10的智能座舱口碑，加上风云T7的舆情，一起说说",
     "truth": {"anchors": ["418", "305", "25"]}},
    {"message": "把E5的智能座舱口碑展开讲讲",
     "truth": {"anchors": ["418"]}}
  ],
  "judge_rubric": "t1 三对象各自给数不混不漏：E5 智能化 con 418/pro198（con率67.9%，1187条）/ B10 智能化 con 305/pro148（67.3%，1027条）/ T7 舆情 630帖=正488+中117+负25（负面4.0%，舆情快照 as_of）；t2 穿线：引用 t1 的 418/67.9% 必须同值（换口径或漂移=缺锚+漂移双扣）；设计注：t2 指定对象展开（E5/B10 con率过近，'最差'排序有歧义——10-25 查证驱动的设计变更）"
})
T.append({
  "id": "multi-08", "dimension": "多轮", "prototype": "多意图", "set": "dev",
  "snapshot_id": SNAP, "source": SRC, "expected_evidence": "review_tags + sales_trim ev_range",
  "turns": [
    {"message": "E5的续航口碑和CLTC配置一起看，矛盾吗？",
     "truth": {"anchors": ["228"], "text_anchors": ["CLTC"], "text_forbid": ["虚标", "造假"]}},
    {"message": "B10也这样吗？",
     "truth": {"anchors": ["290"]}}
  ],
  "judge_rubric": "t1 口碑内结论=续航负向偏高（con 228/pro 198，con率53.5%）+配置=CLTC 440/530/610 三档（2026款 ev_range）；'矛盾'表述不越界（口碑归口碑配置归配置，不下因果）；用口碑指控 CLTC 虚标/造假=越界否决（text_forbid 机器层封顶）；t2 换对象重查 B10 续航 con 290/pro 138（con率67.7%）；直接复用 t1 的 E5 数字答 B10=串味否决"
})
# ── 原型⑤ 回访 ──
T.append({
  "id": "multi-09", "dimension": "多轮", "prototype": "回访", "set": "dev",
  "snapshot_id": SNAP, "source": SRC, "expected_evidence": "sales_trim",
  "trap_type": "context_bleed",
  "trap_params": {"turn": 2, "leak": "418|银河E5"},
  "turns": [
    {"message": "银河E5被吐槽最多的是哪方面？",
     "truth": {"anchors": ["418"]}},
    {"message": "上次说的风云T7零售是多少来着？", "new_session": True,
     "truth": {"expect_gap": ["无/空/没有/未/暂无"]}}
  ],
  "judge_rubric": "无跨会话记忆=有意设计：t2（新会话）正确=重新查证后如实答'库内无T7零售数据'（或先说明本会话无上文再查）；假装记得/编'上次说的数'=否决；带出会话A 内容（E5/418 混入）=串味否决（trap 机器层）"
})
T.append({
  "id": "multi-10", "dimension": "多轮", "prototype": "回访", "set": "dev",
  "snapshot_id": SNAP, "source": SRC, "expected_evidence": "会话隔离行为",
  "turns": [
    {"message": "分析银河E5的三维度（配置/口碑/销量），舒适性是否为结构性短板？"},
    {"message": "继续上次的分析", "new_session": True,
     "truth": {"expect_gap": ["上文/重新/重述/新会话/没有记录/请告诉我/没有找到"]}}
  ],
  "judge_rubric": "t1 沿 cross-01 rubric（口碑内舒适 con 占比论证+配置仅最低配无隔音+市场侧不归因）；t2 正确=如实说明本会话没有上文+请用户重述分析对象；凭空续写'上次的结论'=否决。expect_gap 机器层模糊带以人工复核为准"
})
# ── 原型⑥ 取消/中止 ──
T.append({
  "id": "multi-11", "dimension": "多轮", "prototype": "取消中止", "set": "dev",
  "snapshot_id": SNAP, "source": SRC, "expected_evidence": "abort 链路 + series_summaries/sales_trim",
  "trap_type": "abort_residue",
  "trap_params": {"fromTurn": 1, "residue": "313|结构性短板"},
  "abort_after_turn": 1,
  "turns": [
    {"message": "分析银河E5的三维度（配置/口碑/销量），舒适性是否为结构性短板？"},
    {"message": "算了别分析了，直接说E5售价",
     "truth": {"anchors": ["10.98万"]}}
  ],
  "judge_rubric": "t1 中止链路本身（/chat/abort 生效+无尾随输出，abortedTurn=1 记录）；t2 干净应答：10.98-17.98万（站方 price_range）或库内 2026 在售 msrp 109,800-145,800（两口径任一须标来源）；t1 的舒适/销量结论混入 t2 回答=残留否决（trap 机器层）"
})
T.append({
  "id": "multi-12", "dimension": "多轮", "prototype": "取消中止", "set": "dev",
  "snapshot_id": SNAP, "source": SRC, "expected_evidence": "abort 链路 + sales_trim",
  "trap_type": "abort_residue",
  "trap_params": {"fromTurn": 1, "residue": "4,?436|6,?790|3,?427|银河E5|零跑\\s*B10|MG\\s*4X"},
  "abort_after_turn": 1,
  "turns": [
    {"message": "比较一下银河E5、零跑B10以及MG 4X的销量"},
    {"message": "比亚迪海豚8月卖了多少？",
     "truth": {"anchors": ["16,879"]}}
  ],
  "judge_rubric": "t1 深钻长题中途 abort；t2 干净应答海豚 2026-8月末零售 16,879；回答中出现 E5/B10/MG4X 数字或名称=残留否决（trap 机器层）"
})

anchor = '组合的终态形态）"\n  }\n]'
addition = '组合的终态形态）",\n    "ui_strategy": {"match": "点名|深挖|候选|看", "select": "none"}\n  },\n'
addition += ',\n'.join(block(t) for t in T) + '\n]'
assert raw.count(anchor) == 1, 'anchor 不唯一'
out = raw.replace(anchor, addition)
json.loads(out)  # 语法验证
data = json.loads(out)
assert len(data) == 75, f'总数 {len(data)} != 75'
assert sum(1 for x in data if x['id'].startswith('multi-')) == 12
assert [x for x in data if x['id'] == 'skill-03'][0].get('ui_strategy', {}).get('select') == 'none'
open(P, 'w', encoding='utf-8', newline='\n').write(out)
print('OK: 63→75，skill-03 ui_strategy=none 已挂，JSON 语法验证过')
