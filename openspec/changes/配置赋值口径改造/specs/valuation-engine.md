# spec · 差价真值表与计算引擎（配置赋值口径改造）

> 归档后补录（2026-10-13）：本 spec 按施工实际执行的契约整理（含 Step8 审查修复与 carkit 上游同步后的最终形态），非施工前预留。对应 design.md D1/D2，任务 T1.1-T1.4。

## 待办清单（已完成）

- [x] 建 diff_pricing.json（61 项差价真值表，schema 见下）
- [x] 实现 value_diff.compute_value_diff（口径唯一实现）
- [x] parity 单测（legacy_mode 锁原 JS 公式）
- [x] 新规则单测（band/数量差/threshold/○/缺采/missing 拒绝汇总/魔毯 9000/0−0=非差异）

## 真值表 schema（data/diff_pricing.json，插拔：换文件+重启生效）

```json
{
  "version": "v1-20261013",
  "source_notes": "三类口径来源声明",
  "excluded": {"note": "参与比较不计价（carkit '/' 语义）", "ids": []},
  "items": {"<concept_id>": {"pricing": "...", "...参数": "...", "basis": "溯源"}}
}
```

**pricing 4 型**：

| 型 | 参数 | 语义 |
|---|---|---|
| flat | val | presence 差异记一笔（±val）；双方都有的文本差异不计价 |
| per_unit | unit_price, num_pattern? | 数值/数量差 × 单价（A1 续航 100 元/km、G5 扬声器 100/个） |
| band | bands[]（contains/all/any/range + val）, fallback, num_pattern? | 双方各自落档相减；组合关键词用 all；匹配序=数组序（长词优先防子串） |
| threshold | threshold, price, num_pattern? | \|数值差\|≥阈值 → ±price，符号随方向（G1 中控屏 ±500/3寸） |

**61 项口径要点**（全表见该 json 的 basis 字段）：
- A1 续航=per_unit 100 元/km 无阈值（用户 2026-10-13 拍板，摒弃 carkit 阈值方案）
- 38 项 carkit workbook 金额；23 项 Prism 独有沿用 concept_weights tier1 价
- 简化项（basis 注明）：F3/F4/F5=每座价×前排2座、D1-D3 按项不按颗、F2 只取电调 bonus、G6 一口价
- M2 可变悬架（2026-10-13 对齐 carkit suspension.py）：**空气/魔毯=软硬+高低组合=9000**；软硬单 1000；高低单 8000；未识别类型 0 元档

## 引擎契约（src/insights/value_diff.py::compute_value_diff）

```python
compute_value_diff(rows, pricing_table, manual_prices=None, legacy_mode=False) -> dict
# rows = spec_compare_horizontal 的 rows（is_concept/id/name/param/cells/present[/price]）
# 返回 {columns:[{k,available,text,amount,priced_n,total_n,comparable}],
#       items:{id:{verdict,amount,unit_price,price_source,basis,note[,amounts]}},
#       missing_rules:[id], blocked, config_adv, flat_adv:None, legacy:bool}
```

**口径（生产模式）**：
1. 单价解析序：manual_prices[param] → diff_pricing.items[id] → 无（未定价）。手填价使整行退化为"单价×(有无/数值差)"旧口径
2. 三态判读 _cell_state：""/缺采/None→missing；该车系无此项/—/✕/○前缀等→absent（○选装=无）；其余 present
3. 任一列 missing → 整行"不计"，不入 comparable；未知 pricing 或规则字段缺失 → missing_rules（fail-closed）
4. band 落档相减为 0（含 0 元档 vs 无）→ 非差异（"文本差异不计价"）；行级差异判定用 _row_sig 语义签名（absent 态折叠，present 保留 strip 原文）
5. missing_rules 非空 → blocked：各列 amount=None、文案"待定价（缺规则 N 项）"、config_adv=None——**不脑补**
6. config_adv 仅在 n_cols==2、未 blocked、**列 available**（comparable>0）三者齐时出数；"差价值不可用"不得被当 0
7. 金额文案 half-up（floor(x+0.5) 对齐 JS Math.round）
8. legacy_mode=True：单价源=rows.price（concept_weights 兜底），逐字复刻原 JS _computeDiffCells 公式——**仅供单测锁公式，生产禁传**

## 验收标准（已在 Step9 复核）

1. parity：legacy_mode 对构造行复刻 JS 全分支（含 0 价行计入计算的细节）
2. 新规则正反例：4 型×方向/子串序/组合枚举/○/缺采/字段缺失 fail-closed/missing 拒绝汇总/魔毯 9000/0−0=非差异
3. 单测位于 prism-dashboards/tests/test_value_diff.py，挂 npm run smoke:value_diff → smoke:all

## 依赖

上游：spec_compare_horizontal（rows 形态）；下游：dashboard-endpoint spec（D3）、agent-integration spec（工具消费 diff 字段）。
