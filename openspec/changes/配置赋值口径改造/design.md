# design · 配置赋值口径改造

- 日期：2026-10-13 · Step2 design（配套 proposal.md 决策 D1-D7）

## 架构总览

```
diff_pricing.json (新·唯一差价真值表, 插拔)
        │
compute_value_diff (新·共享纯函数, prism-dashboards/src/insights/value_diff.py)
   │  输入: spec_compare_horizontal 的 rows/present/cells + diff_pricing + manual_prices
   │  口径: ①presence差×单价 ②数值差×单价 ③文本档位差(双方落档相减) ④数量差 ⑤阈值
   │        ○选装=无 · 缺采整行跳过 · 缺规则→missing 拒绝汇总(不脑补)
   ├── GET/POST /dash/config/compare-valued (新端点, +get_trims 指导价→拉平价)
   │      ├── 看板前端 (dash_config.html §02 tfoot; 手填价 POST 重算)
   │      ├── /dash/config trim 视图 (§03 并入, 删 fold_prices)
   │      └── agent: compare_configs_valued 工具 (extension, 截断白名单 24)
   │               └── SKILL.md config-compare → 结论经 submit_conclusion 出口闸
   │                        └── /verify/claim + config_diff 引用分支
   └── 单测: parity(锁公式) + 新规则正反例
concept_weights.json (不动, 单车价值口径, A1 续航单价出处)
score_concept (标注归档, 不接线)
```

## D1 diff_pricing.json（真值表）

路径 `prism-dashboards/data/diff_pricing.json`，插拔惯例（换文件+重启生效）。schema：

```json
{
  "version": "v1-20261013",
  "source_notes": "续航=Prism拍板(100元/km无阈值); 标carkit者=其内置workbook默认, 用户2026-10-13拍板采用; 标Prism独有者=沿用concept_weights",
  "excluded": {"note": "carkit workbook划/项: 参与比较不计价", "ids": []},
  "items": { "<concept_id>": {"pricing": "flat|per_unit|band|threshold", ...参数, "basis": "carkit#N|prism|简化:说明"} }
}
```

**引擎支持 4 型**：`flat`（presence 或文本差一笔账，val）/ `per_unit`（数值或数量差×unit_price）/ `band`（文本 contains 档或数值区间档，档表 val，两车各自落档相减）/ `threshold`（|数值差|≥threshold → ±price，符号随方向）。

**61 项逐项落法**（口径核心，施工照此填表）：

| ID | 项 | pricing | 参数（元） | basis |
|---|---|---|---|---|
| A1 | CLTC纯电续航 | per_unit | 100/km 无阈值 | prism拍板 |
| A2 | 增程综合续航 | per_unit | 10/km | prism独有(现weights) |
| A3 | 驱动电机数 | per_unit | 8000/个 | prism独有 |
| A4 | 800V | flat | 2000 | carkit#3 |
| A5 | 对外放电 | flat | 500 | carkit#16 |
| B1 | 轮毂直径 | band(寸数) | R16:0 R17:700 R18:1400 R19:2100 R20:2800 R21:3500 R22:4200（=(寸−16)×700 取max 0） | carkit#4简化(铝+500 待补项change) |
| C1 | 高速NOA | flat | 5000 | carkit#9拆 |
| C2 | 城市NOA | flat | 3000（增量语义：C2蕴含C1时与carkit档位差数学一致；领域假设"城市NOA车型必有高速NOA"随项标注） | carkit#9拆 |
| C3/C4/C5 | 泊车三件 | flat | 现weights | prism独有 |
| D1/D2/D3 | 侧气囊/气帘/后排侧 | flat | 各350 | carkit#5简化：按项不按颗 |
| E1 | 天窗 | band | 无0/普通电动1000/不可开启全景2000/可开启全景2500 | carkit#18 |
| E2/E4/E5 | 无框门/隔音/隐私 | flat | 现weights | prism独有 |
| E6 | 电动尾门 | flat | 800 | carkit#13 |
| E7 | 吸合门 | flat | 2000 | carkit#11 |
| E8 | 行李架 | flat | 300 | carkit#14 |
| F1 | 座椅材质 | band | 织物0/仿皮1500/真皮2500/翻毛3000/NAPPA3500 | carkit#34 |
| F2 | 前排电动调节 | flat | 400 | carkit#35简化(方向数差×50留迭代) |
| F3/F4/F5 | 加热/通风/按摩 | flat | 500/800/1200（=carkit 每座价×2 前排） | carkit#36简化 |
| F6 | 座椅记忆 | flat | 200（100×2座） | carkit#45 |
| F7/F8/F14/F15 | 腰撑/二排/杯托/遮阳帘 | flat | 现weights | prism独有 |
| F10 | 冰箱 | flat | 1000 | carkit#43 |
| F11 | 氛围灯 | band | 单色200/多色600 | carkit#39 |
| F12 | 方向盘加热 | flat | 200 | carkit#27 |
| F13 | 方向盘电动+记忆 | flat | 900（800电调+100记忆） | carkit#26+#28 |
| G1 | 中控屏 | threshold | ≥3寸 ±500 | carkit#21 |
| G2 | 液晶仪表 | per_unit | 100/寸（lcd_bonus 200 留迭代） | carkit#29简化 |
| G3 | HUD | band | 无0/HUD1000/AR2000/P-HUD3000 | carkit#30 |
| G4 | 副驾屏 | band(寸数) | 无0/<12.6:1000/12.6-15.6:1500/>15.6:2000 | carkit#22 |
| G5 | 扬声器数 | per_unit | 100/个（数量差） | carkit#37 |
| G6 | 50W无线充电 | flat | 350（双充差留迭代） | carkit#33简化 |
| H1-H4 | 外后视镜四功能 | flat | 各100 | carkit#20 |
| H5 | 自动防眩目 | flat | 现weights | prism独有 |
| H6 | 内后视镜/流媒体 | band | 常规0/流媒体1000（carkit豁免"手动防眩目默认双方有"由 band 常规档0 天然实现） | carkit#31 |
| I1-I3/J1/J6/J8/K3/K4/L4 | 进入/语音/记录仪/哨兵/香氛 | flat | 现weights | prism独有 |
| K5 | 360全景 | flat | 1000 | carkit#7 |
| K6 | 540透明底盘 | flat | 1500 | carkit#7 |
| L1 | 感应雨刷 | flat | 100 | carkit#44 |
| L3 | 热泵 | flat | 2000 | carkit#40 |
| M2 | 可变悬架 | band | 无0/软硬1000/高低或空气8000/软硬+高低(空气)9000（组合枚举，与carkit可叠加语义一致） | carkit#6 |

"现weights"= 施工时从 `concept_weights.json` 读该项 `weights["1"]`（tier_high）落成 flat 值，表内注明出处。

## D2 compute_value_diff（共享纯函数）

`prism-dashboards/src/insights/value_diff.py`，零路由依赖、可单测。

```python
def compute_value_diff(rows: list[dict], pricing_table: dict,
                       manual_prices: dict[str, float] | None = None,
                       legacy_mode: bool = False) -> dict
```

- **输入**：spec_compare_horizontal 的 rows（id/name/cells/present/param）。
- **单价解析顺序（D5 手填覆盖优先）**：manual_prices[param] → diff_pricing[param] → 无（未定价）。`legacy_mode=True` 时单价源= rows 自带 price（concept_weights 兜底）——**仅供 parity 测试锁 JS 公式用**，生产不传。
- **逐行口径**（v1 生产）：只算 is_concept 行；present 含 None（缺采）→ 整行跳过（不计 comparable）；○ 前缀值按"无"判（与 `_state` 4 态一致）；verdict 相对列1：`多`(amount>0)/`少`(<0)/`同`(=0)/`不计`(excluded 或缺采)。
  - Δ 类型：① presence 差 → ±1；② 双方具备：数值型→数值差（per_unit/threshold 消费）、文本型→band 双方落档相减（**新能力**，原 JS 只展示）；band 内规则缺失→该行进 missing_rules。
- **汇总**：per 列 `amount_vs_col1/priced_n/total_n/comparable`；missing_rules 非空 → 各列 amount=None + missing 清单（照 carkit 不脑补）。两列时 col1 的 amount 即"配置优势（列2 相对列1）"。
- **parity 策略（风险#1 对策）**：单测两层——layer1 `legacy_mode` 下用构造行复刻 JS `_computeDiffCells` 全部分支（presence±1/数值差/非数值跳过/相等跳过/双无跳过/缺采跳过/未定价计数/文案四态），断言金额与计数一致；layer2 生产模式新规则正反例。**锁公式不锁单价源**：切换单价源导致的数字变化是拍板的口径升级，靠此区分。

## D3 端点 `GET|POST /dash/config/compare-valued`

- 入参：`sel=mid:spec`（2-6，第 1 个为基准列）query；POST body 可带 `{"manual_prices": {param: 元}}`。
- 流程：get_config_snapshot（缺快照→error 同 compare-horizontal 口径）→ spec_compare_horizontal 同源取数 → load diff_pricing → compute_value_diff → get_trims 填 trim_name+指导价（try/except，失败→guide_prices=null，**不阻塞逐项差价**）。
- 出参：`{cols(+msrp), rows(+verdict/amount/unit_price/basis), totals, flat_adv(两侧指导价齐才出，=(col−col1)+(msrp1−msrk)*10000 口径见 proposal D-公式), missing_rules, pricing_table_version, as_of}`；拉平指导价优势公式 = 配置优势 + (基准指导价 − 对方指导价) × 10000（万元→元，方向=对方贵多少拉平后还剩多少优势）。
- 幂等无副作用；不落任何库。

## D4 前端切换（dash_config.html §02）

- 删 `_computeDiffCells`（:526-568）与 `_refreshFooter` 内重算逻辑；`renderHorizontalCompare` 改调 compare-valued（初次 GET；`setRowPrice` 手填后 POST manual_prices 重取），tfoot 由响应渲染。
- 保留：三态样式（蓝=diff_pricing 兜底 / 绿=手填 / 灰=未定价——注意语义从"概念赋值兜底"改为"差价表兜底"，title 文案同步）。
- hint（:277）更新为五规则：①presence差×单价 ②数值差×单价 ③**文本档位差：双方落档相减** ④缺采不计价 ⑤缺规则项拒绝汇总并列出。
- §01 差异摘要条（updateDiffSummary）数据源同步切后端。

## D5 旧链路并入（/dash/config trim= 视图，D4 拍板）

- dashboard_routes.py:317-397：`fold_prices(raw, prices)` 调用点替换为 compute_value_diff（同一函数，行结构 compare_trims/_trim_diff_rows **保留**——它们是差异行生产者非计价层）。
- 删 `fold_prices`（dashboard_data.py:1198-1266）及其 import；模板 §03 消费 totals/pair_diffs 的渲染改为读新结构。
- `_concept_price_for_param`/`_concept_tier_for_state` 若仅剩 fold_prices 引用则一并评估退役（spec_compare_horizontal 仍在用，保留）。

## D6 agent 接线（extension + skill + 出口闸）

- 工具：`pi.registerTool(makeAutohomeTool('compare_configs_valued', '两版型赋值差价对比（61项口径）：逐项多/少/同判定+金额+配置优势+拉平指导价优势。第1个 sel 为基准。', {sel: array 2-6个 'series_id:spec_id'}))`；同步 **KNOWN_BUSINESS_TOOLS 与截断白名单 23→24**；guard 白名单单测同步。
- skill：`.pi/skills/config-compare/SKILL.md`，frontmatter 双受众（summary 给面板人看；description 给模型：配置对比/差价/值不值/竞争力/赋值/拉平/贵在哪 触发词全）。正文：触发→resolve_series（红线#7）→compare_configs_valued（说明基准列语义）→解读规范（五态人话/拉平价=“贵 X 万但配置多值 Y 万”句式）→**口径声明纪律**（“按配置差价表 v1-20261013，未含看板手填覆盖”）→missing_rules→数据缺口假设范式→越界纪律（配置差价不推销量因果）→清单外留痕→指导价缺失时只出配置优势不出拉平价。
- 出口闸：main.py `/verify/claim` 增 `config_diff:{midA}:{specA}:{midB}:{specB}` 引用分支（照 `_check_sentiment_ref` 模式：校验 4 段格式+两 mid 在 config_snapshots 有快照；prism-dashboards 不可达仅拒 config_diff，三维度不受影响）。

## D7 里程碑与依赖

M1（口径地基：D1 表+D2 函数+两层单测）→ M2（D3 端点+D4 前端+D5 旧链路）→ M3（D6 三件）→ M4（trap 2 条进 tasks.json/trap_check + D1.3 任务清单回写 + EVAL_STATUS + 设计图同步）。M3 依赖 M2 端点形态；M1/M2 可同子代理串行。

## 环境坑（施工必须遵守，出处 [[pi-harness-reference]]/[[prism-launcher]]）

1. 重启 9200 网关必须带 `PRISM_AUTO_APPROVE_UI=1`（统一走 prism.py）。
2. extension（Bun）内禁止原生模块查库；本 change 无需——差价纯函数在 prism-dashboards Python 侧。
3. 门禁若 0/9 先查网关重启记录（并行会话碰撞），再查代码。
4. 含反斜杠的编辑走 Edit 工具不走 heredoc。
5. 批跑/服务操作冻结纪律：跑门禁期间不做服务重启。
