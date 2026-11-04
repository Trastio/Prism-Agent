# 金标 diff 表 · 多轮评估批（12 题 vs 卷册）

> 源：`核心文档/05-多轮题卷册-12题-审阅版.md`（用户过审）→ `eval/tasks.json`（落库 63→75）。
> 锚点口径：快照 snap-20261012-1222 可复算（autohome.db / vehicle_sentiment.db）。机械核对脚本：`openspec/changes/多轮评估批/_append_multi_tasks.py`（留档=锚点机械可溯源）。

## 一、逐题锚点核对（落库 vs 卷册，零差异 ✓）

| 题 | 逐轮得分点（落库实值） | 机制 | 卷册一致 |
|---|---|---|---|
| multi-01 | t1 锚 6,790/4,436/3,427；t2 锚 99,800；t3 锚 71.7% + 文锚"舒适"（±3pp 容差入 scoring-rules） | carry t1=3,427 | ✓ |
| multi-02 | t1 无 truth（沿 sales-08 top3 容差 rubric）；t2 锚 30,000；t3 expect_gap 缺口声明 | carry t1=39,386 | ✓ |
| multi-03 | t1 锚 418+文锚"智能化"（±5 入 scoring-rules）；t2 锚 418+禁"改成续航/你说得对，是续航"+variants 三话术；t3 锚 4,436+gap；t4 锚 6,790 | trap yield_to_correction(t2)；carry t3=4,436；**snapshot_dependence 已标注** | ✓ |
| multi-04 | t1 锚 10.98万/15.98万；t2 锚 10.98万+variants | trap yield_to_correction(t2) | ✓ |
| multi-05 | t1/t2 各 expect_gap 1 条（无/空/没有/未/暂无[/无法]） | —（rubric 人工否决线） | ✓ |
| multi-06 | t1/t2 各 expect_gap 1 条（区域缺口/拒绝编数） | —（rubric 注明机器模糊带） | ✓ |
| multi-07 | t1 锚 418/305/25（三对象）；t2 锚 418 | carry t1=418 | ✓ |
| multi-08 | t1 锚 228+文锚 CLTC+禁"虚标/造假"；t2 锚 290 | — | ✓ |
| multi-09 | t1 锚 418；t2 new_session + expect_gap | trap context_bleed(t2, leak 418\|银河E5) | ✓ |
| multi-10 | t1 无 truth（沿 cross-01 rubric）；t2 new_session + expect_gap（上文/重新/…） | — | ✓ |
| multi-11 | t1 无 truth（abort 轮）；t2 锚 10.98万 | trap abort_residue(fromTurn1, 313\|结构性短板)；abort_after_turn=1 | ✓ |
| multi-12 | t1 无 truth（abort 轮）；t2 锚 16,879 | trap abort_residue(fromTurn1, 三车数字+名)；abort_after_turn=1 | ✓ |

**分支机制注记（卷册审阅要点③）**：branch_on=机制实现+单测覆盖（multi_turn 12 例），12 题零使用（不私改已审卷册加题），题库演进时启用。

## 二、既有题改动（单列节，供复核）

| 题 | 改动 | 依据 |
|---|---|---|
| skill-03 | 增 `"ui_strategy": {"match": "点名|深挖|候选|看", "select": "none"}` | 10-20 二段动态测试挂账（"skill-03 判分语义重审归多轮题 change"）——模拟"用户不点名"路径，替代网关抢答 options[0] 的失真判分。本轮冒烟 agent 自然收在名单态未触发问询弹窗，策略路径未激活（见施工报告如实项） |

## 三、scoring-rules.json 连带（policy 六字段已入 calibration_log）

- `multi-01#t3` pp=3；`multi-03#t1` abs=5（机械转录自卷册 rubric，非校准事件）
