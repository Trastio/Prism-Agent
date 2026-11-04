# explore · 配置赋值口径改造（carkit 口径并入 + 差价链路 agent 化）

- 日期：2026-10-13（Step1 explore）
- 起因：carkit（内部配置对比工具，gh 私有仓）调研后用户拍板引入其赋值口径，改造 Prism 配置功能的赋值与差价链路，并打通 agent 出口。

## 0. 用户拍板记录（本 change 的口径宪法）

1. **续航 = Prism 口径**：per_unit 100 元/km、无阈值（继承 concept_weights A1）。carkit 的"50km 阈值 + 60 元/km"方案摒弃。
2. **其余项按 carkit**：文本档位差计价（材质/天窗/轮毂/NOA 档位/座椅功能等双方落档相减）+ carkit 内置金额参数（来源=其 workbook《竞争力对比配置清单参考(1).xlsx》内置默认，用户 2026-10-13 拍板采用）。
3. **授权改配置看板前端**（dash_config.html）。
4. **清单补项另立 change**：carkit 独有 ~9 项（轮圈材质/前备箱/主动进气格栅/灯光/车联网/方向盘材质/USB 数量/车外扬声器/后排出风口 ±中央气囊）不在本 change 内。
5. carkit 自划 `/` 不计价项（电芯品牌/激光雷达计价/后雨刷/KTV）保持参与比较但不计价。

## 1. 代码实况（本 explore 全部实测核验）

- **横表链路**：`GET /dash/config/compare-horizontal`（dashboard_routes.py:783）→ `spec_compare_horizontal`（dashboard_data.py:1321）。rows 每行已带 `price`（概念兜底单价）/`present`（三态 1/0/None）/`sources`（字段级溯源）。**差价不在后端**。
- **前端差价 JS（要下沉的对象）**：dash_config.html
  - `:486 _manualPrices`（内存态手填价）+ `:510` 取价顺序（手填→概念兜底）+ `:760-775` 输入校验（合法非负数字，空串删回退）
  - `:570-605 refreshDiffRow`：末行「配置差价（两车）」逐列相对第 1 列，口径= presence 差异 ±单价×1 + 数值型差异×数值差；文本/布尔差异只展示不计价；缺采不计价
  - `:277` hint 四规则文案（改造后需同步更新）
- **旧链路（要收敛的对象）**：`GET /dash/config` 主路由（dashboard_routes.py:317-397，`trim=` 版型级对比视图）仍走 `compare_trims_from_snapshots` + `fold_prices`（dashboard_data.py:1198，**presence-only 口径**、服务端算、totals/priced_n/diff_m/pair_diffs）→ 与横表口径**已是两套并存**。
- **价值分孤儿**：`score_concept`（concept_config.py:307）2026-10-08 移除 value_per_col 后零消费者（无路由无前端引用）。本 change 不复活，标注归档。
- **概念资产**：`data/concept_configs.json` 61 项（ID 跳号 8 个：E3/F9/J2/J7/K1/K2/L2/M1，项数不受影响）；`data/concept_weights.json` 61 项（per_unit×2 / per_count×1 / tier×58）。
- **指导价价源 ✅**：`get_trims`（src/tools/config.py:94）返回"版本名、指导价、spec_id"（走 autohome_api 活接口 + TTL 缓存；spec_compare_horizontal 已在用）→ 拉平指导价优势的价源现成。
- **出口闸接线模式 ✅**：main.py `/verify/claim`（:1064）已有 `sentiment_*` 七种引用分支（:1018 `_SENTIMENT_TABLES` + `:1042 _check_sentiment_ref`），扩 config 差价引用照此模式。
- **截断层**：extension 第二 tool_result handler 覆盖 23 数据工具（query3+sentiment6+dashboards10+social4），新工具注册后需同步白名单（23→24）。
- **carkit 对照账**（逐项对过）：重叠 ~38 项（换 carkit 金额口径）/ Prism 独有 ~23 项（无 carkit 依据，沿用现 weights）/ carkit 独有 13 项（4 项其自排除）。
- **carkit 赋值引擎事实**（gh 实读 valuer.py 564 行）：规则两形态 flat/dynamic；计价 5 型 flat/per_unit/band/segmented_per_km/manual；三指标公式（配置优势=Σ多−Σ少；拉平指导价=配置优势+(竞品指导价−自品指导价)×10000；综合=配置优势+竞品底价−自品底价）；防错纪律=缺任一规则整组拒绝出总数列 missing、○选装按无、[待定]跳过、"皮质"→"仿皮"归一、底价>0 校验且不得拿指导价充数、explain_rule 每项给计价依据。

## 2. 三组合并口径（需在设计定稿）

| 组 | carkit 口径 | Prism 现口径 | 推荐落法 |
|---|---|---|---|
| 气囊（D1/D2/D3 vs #5） | 一项"气囊数量"数量差×350 | 三项拆分（前排侧/侧气帘/后排侧）presence | **保留拆分**，carkit per_airbag 350 换算为各项单价 |
| 外后视镜（H1-H4 vs #20） | 一项"每功能 100" | 四项拆分 presence | 保留拆分，per_function 100 → 各项单价 |
| 座椅功能（F3/F4/F5(/F8) vs #36） | 逐子项×座位数（通风400/加热250/按摩600/头枕100） | 逐项 presence | 采纳 carkit 子项单价×座位数（seat_functions 解析），拆分行保持 |

## 3. 施工前待办（Step2/design 中落）

- T1 前端 `refreshDiffRow` 完整公式逐行抄录 → 作为 Python 移植的 **parity 期望值**（先锁旧行为，再叠新规则）。
- T2 `/dash/config` 版型级对比视图（fold_prices 用户）处置裁决：推荐**并入新差价引擎**（同页同口径），删 fold_prices/compare_trims 旧链；需确认该视图前端渲染点。
- T3 手填价交互：前端行内改价后**随请求传后端重算**（POST/带参 GET），保持"手填覆盖优先、内存态不落库"语义不变。
- T4 `/verify/claim` 新引用格式定稿：建议 `config_diff:{seriesA_spec}:{seriesB_spec}:{concept_id}`（或配对组级+逐项级两级），以及 diff_pricing.json 版本号如何进引用。

## 4. 范围

**做**：diff_pricing.json 真值表 / 后端共享差价纯函数 + parity 单测 / `GET /config/compare-valued` 端点 / 看板前端切后端（删 refreshDiffRow、hint 更新）/ 旧链路收敛（fold_prices/compare_trims 裁决处置）/ extension `compare_configs_valued` 工具 + 截断层白名单 / SKILL.md 配置对比 skill / /verify/claim config 引用分支 / deck 两错进 trap/grounding 素材 / 任务清单 D1.3 回写重述。

**不做**：清单补项（另立 change）/ 价值分（score_concept）复活 / 底价功能（v1 端点不收底价；agent 对话中用户口头给价可算，需在 skill 里写清这是"对话内计算、非端点口径"）/ carkit 的 PPT 导入与现抓。

## 5. 里程碑草案（Step2 细化）

- **M1 口径地基**：diff_pricing.json（续航=Prism 100元/km 标注 Prism 口径；其余=carkit 金额标注来源+拍板日期；excluded 项标记）+ `compute_value_diff` 共享纯函数 + parity 单测（对 JS 旧行为）+ 新规则单测（文本档位/数量差/○/缺采/待定/缺规则拒绝汇总）。
- **M2 服务出口+看板**：compare-valued 端点（内调 spec_compare_horizontal 同源取数 + get_trims 指导价 + 差价函数）+ 前端切换（手填价随请求传后端）+ 旧链路处置（T2）+ hint 文案。
- **M3 agent 接线**：extension 工具 + 截断白名单 23→24 + SKILL.md（触发条件/取数顺序/五态表述/拉平价解读/口径声明纪律/数据缺口范式/清单外留痕）+ /verify/claim 分支 + 门禁 E1-E9 回归。
- **M4 评估与账目**：deck 两错（15.6 中控 / 17扬(8)）进 trap/grounding 测试集 + D1.3 回写 + EVAL_STATUS 记录 + 设计图同步。
