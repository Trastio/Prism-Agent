# -*- coding: utf-8 -*-
"""
评估迭代基建包 B1 · tasks.json truth 回填脚本（可复跑，幂等）

步骤：
  0) trap-07/08 注入 trap_params={concede,resist}（B1-1，幂等覆盖）
  1) 38 题金标主锚数字机械回填 → tasks.json 每题可选 truth:{anchors,forbid}

纪律：
  - 锚点选取原则：只取主结论数字（1-3 个/题，rubric 明示"精确/硬锚/核心数字"者优先），
    不取佐证/口径数字（如分母、区间口径、可选加分项）；缺口题/范式题/开放题/top3 容差题
    不放 anchors（首选项不唯一，硬锚会假阴）。
  - 每个锚点做溯源断言：数字核心串必须出现在该题 gold.numbers 的 JSON 串里（forbid 类
    溯源到题面假值），不满足即报错退出——保证"机械回填"可审计，不夹带人工编造。
  - 改后断言：JSON 合法 + 题数仍为 60。
运行：python eval/gold/_backfill_truth.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASKS_FILE = ROOT / 'eval' / 'tasks.json'
GOLD_FILE = ROOT / 'eval' / 'gold' / 'user-20261013.json'
TASK_COUNT_EXPECTED = 60

# ── 步骤 0：trap-07/08 trap_params（与 trap_check.mjs value_grounding 分支配套）──
TRAP_PARAMS = {
    'trap-07': {'concede': r'14\.6', 'resist': r'15\.4'},
    'trap-08': {'concede': r'17\s*(个|只|喇叭|扬声器)', 'resist': r'8\s*(个|只|喇叭|扬声器)'},
}

# ── 步骤 1：truth 锚点表（源=gold.numbers；'trace' 仅注释用，断言按数字核心串全量核对）──
# anchors 数量超 3 的题（reviews-08 四好评率 / config-12 四顶配价）为 rubric 明示的逐项抽验数。
TRUTH = {
    # 销量：rubric"核心数字/精确(±0)/硬锚"
    'sales-03': {'anchors': ['0.63%', '28']},                # 星舰版占比/星舰版零售（4436 为分母口径，不入锚）
    'sales-05': {'anchors': ['5,218', '76.8%']},             # 27款合计/27款占比（6790 全系为佐证）
    'sales-06': {'anchors': ['408']},                        # 最低配零售
    'sales-07': {'anchors': ['2,047', '46.15%']},            # 最畅销版型零售/占比
    'sales-09': {'anchors': ['12,129']},                     # QQ3 EV 硬锚（BEV/NEV 两口径同第一）
    'sales-12': {'anchors': ['4,436']},                      # 最新可得 8 月末零售
    'sales-14': {'anchors': ['6,790', '4,436', '3,427']},    # 三车精确数字（T7=缺口声明无锚）
    # 配置：阶梯端点价/顶配价抽验（万单位，truth_check 按万换算可比）
    'config-08': {'anchors': ['19.98万', '12.99万']},        # EV 顶配/DM-i 入门（rubric 数字抽验两端）
    'config-12': {'anchors': []},  # v1 校准：金标锚顶配价，agent 合理选了中配/主力对比——对比基准弹性题不放价锚
    # 口碑：rubric 明示容差的端点数字（容差在 scoring-rules.json tolerance_overrides）
    'reviews-03': {'anchors': []},  # v1 校准：好评率端点按版型/聚合口径浮动大，方向判分归 rubric
    'reviews-05': {'anchors': ['418']},                      # 智能化 con 计数（top1 主锚）
    'reviews-08': {'anchors': []},  # v1 校准：同上，跨车好评率形态不稳
    # 舆情：五要素中的声量与正负占比（±10% 容差）
    'sentiment-03': {'anchors': []},  # v1 校准：718=直查口径，agent 工具返回 636——锚点须跟工具口径，复算后回填
    'sentiment-04': {'anchors': []},  # v1 校准：同上
    'sentiment-05': {'anchors': []},  # v1 校准：同上
    'sentiment-06': {'anchors': ['12.8%']},
    'sentiment-07': {'anchors': []},  # v1 校准：同上
    # 陷阱题：forbid 放题面假值（溯源到题面而非 gold）。
    # 单条 '20,000' 即覆盖回复各形态：truth_check 归一化后 "20,000"/"20000"/"2万" 同值命中。
    # trap-09 truth.forbid 已摘（wave2 判分单源 trap 分支——正确纠正复述假值不双罚；Step7 P1-2 修，勿回加）
}

# 无 truth 的 38 题金标题（脚本核对的"白名单"——此清单外补锚须同步改本脚本）：
#   缺口/前提不成立：sales-04/11/13、config-10/13、reviews-07/11、sentiment-08
#   范式/方法判分（无唯一数字主锚）：config-05/06/09/11、reviews-04/09/10、config-03/04（web 佐证方向不锁数）
#   top3 容差/口径弹性（首选项不唯一）：sales-08/10、config-07


def anchor_core(a: str) -> str:
    """锚点数字核心串（去千分位/%/万），用于 gold 溯源断言"""
    return re.sub(r'[,]', '', str(a)).rstrip('%万')


def main() -> None:
    tasks = json.loads(TASKS_FILE.read_text(encoding='utf-8'))
    gold = {g['new_id']: g for g in json.loads(GOLD_FILE.read_text(encoding='utf-8'))}
    assert len(tasks) == TASK_COUNT_EXPECTED, f'题数异常: {len(tasks)}'

    # 步骤 0：trap_params（幂等）
    for tid, params in TRAP_PARAMS.items():
        t = next((x for x in tasks if x['id'] == tid), None)
        assert t, f'{tid} 不在 tasks.json'
        t['trap_params'] = params

    # 步骤 1：truth 回填（幂等）+ 逐锚溯源断言
    for tid, truth in TRUTH.items():
        t = next((x for x in tasks if x['id'] == tid), None)
        assert t, f'{tid} 不在 tasks.json'
        for a in truth.get('anchors', []):
            g = gold.get(tid)
            assert g, f'{tid} 无 gold 条目，不能作为 anchors 源'
            blob = json.dumps(g.get('gold', {}).get('numbers', {}), ensure_ascii=False)
            assert anchor_core(a) in blob, f'{tid} 锚点 {a} 无法溯源到 gold.numbers（核心串 {anchor_core(a)}）'
        for f in truth.get('forbid', []):
            assert str(f) in t['question'] or anchor_core(f) in t['question'], f'{tid} 禁值 {f} 无法溯源到题面'
        t['truth'] = truth

    TASKS_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')

    # 改后断言：JSON 合法 + 题数 + trap_params/truth 落盘形态
    back = json.loads(TASKS_FILE.read_text(encoding='utf-8'))
    assert len(back) == TASK_COUNT_EXPECTED, f'回读题数异常: {len(back)}'
    t7 = next(x for x in back if x['id'] == 'trap-07')
    assert t7['trap_params'] == TRAP_PARAMS['trap-07'], f'trap-07 params 形态错误: {t7["trap_params"]}'
    t8 = next(x for x in back if x['id'] == 'trap-08')
    assert re.search(t8['trap_params']['concede'], '扬声器有 17 个'), 'trap-08 concede 正则失效'
    assert re.search(t8['trap_params']['resist'], '共 8 喇叭'), 'trap-08 resist 正则失效'
    n_truth = sum(1 for x in back if x.get('truth'))
    n_anchor = sum(len(x.get('truth', {}).get('anchors', [])) for x in back)
    n_forbid = sum(len(x.get('truth', {}).get('forbid', [])) for x in back)
    print(f'OK: {TASK_COUNT_EXPECTED} 题完好；trap_params×{len(TRAP_PARAMS)}；'
          f'truth 题数={n_truth}，anchors 总数={n_anchor}，forbid 总数={n_forbid}')


if __name__ == '__main__':
    sys.exit(main())
