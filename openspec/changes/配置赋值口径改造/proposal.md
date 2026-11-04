# proposal · 配置赋值口径改造

- 日期：2026-10-13 · Step2 propose
- explore：同目录 explore.md（含用户拍板记录与代码实况）

## WHY

配置看板的差价口径目前**只活在前端 JS**（`_computeDiffCells`，注释明言"前端唯一实现"），且口径残缺（文本档位差一律只展示不计价——配置对比最高频的"双方都有但档位不同"场景出不了金额）；agent 无任何差价出口；旧 fold_prices（presence-only）链路与横表并存=看板内部已是两套口径。carkit 调研证明其赋值表口径（文本档位差计价+金额参数+缺规则拒绝汇总）成熟且用户已拍板采用。不改则：①agent 永远答不了"X 比 Y 值不值差价"这一 PM 最高频问题；②口径继续两套漂移。

## WHAT

把差价口径**下沉为后端唯一实现**并按拍板升级（文本档位差/数量差计价），暴露 HTTP 端点，看板前端与 agent 双端消费；agent 侧新增 compare_configs_valued 工具+skill+出口闸引用分支。

## 决策记录（全部已拍板）

| # | 决策 | 内容 |
|---|---|---|
| D1 | 续航口径 | Prism per_unit 100元/km 无阈值（摒弃 carkit 50km阈值+60元/km） |
| D2 | 其余项口径 | 按 carkit：文本档位差计价+其内置 workbook 金额 |
| D3 | 看板前端 | 授权改动，差价 JS 删除改调后端 |
| D4 | 旧版型级对比视图 | **并入新引擎**，删 fold_prices 折价层（行结构 compare_trims 保留） |
| D5 | 手填价 | 随请求传后端重算，保持"手填覆盖优先"体验，内存态不落库不变 |
| D6 | 清单 | 61 项骨架不动；carkit 独有 ~9 项另立补项 change |
| D7 | 价值分 | score_concept 不复活，标注归档（孤儿引擎） |

## 影响范围

- prism-dashboards：data/diff_pricing.json（新）、src/insights/（差价函数新模块）、dashboard_routes.py（+1 端点、/dash/config trim 视图改）、dashboard_data.py（删 fold_prices 及其调用）、dash_config.html（差价 JS 删除、hint、tfoot 渲染）
- extension：KNOWN_BUSINESS_TOOLS + 截断白名单 23→24、新工具注册
- .pi/skills/config-compare/（新 skill）
- prism-api main.py：/verify/claim +config_diff 引用分支
- eval：trap 素材 2 条、tasks.json

## 风险

1. **口径切换=数字变化**：差价单价源从 concept_weights（row.price）切到 diff_pricing，看板差价数字会变——这是拍板的口径升级，parity 锁**公式**不锁单价源（design §D2）。
2. get_trims 走活接口（autohome_api）：网络失败→指导价 null→拉平价不出（逐项差价不受阻），端点须优雅降级。
3. /dash/config 模板 §03 消费 fold_prices 的 totals/pair_diffs——删层须同步模板渲染。
4. 工具白名单相关单测（guard 测试断言 23 工具）须同步 24。

## 验收（Step9 逐条验）

1. parity：compute_value_diff 在"旧口径模式"（presence+数值差+注入单价）下与 JS 公式对同一批构造行输出一致（单测）。
2. 新规则：文本档位差（材质/天窗/HUD/悬架）、数量差（扬声器/气囊组 flat）、阈值（中控屏）单测正反例全过；○选装=无；缺采整行跳过；缺规则→汇总拒绝+missing 清单。
3. 端到端：compare-valued 端点对真实库内两版型返回逐项判定+合计；missing 场景拒绝汇总。
4. 看板：横表 tfoot 数字来自后端（JS 重算逻辑已删）；手填价改值→POST→tfoot 更新；§03 视图并入新引擎。
5. agent：真实对话"海豚 vs 海鸥 值不值差价"→ resolve→工具→五态结论+拉平价，过闸零回灌；截断白名单含新工具。
6. 门禁 E1-E9 全绿；smoke 全绿含新单测。
7. trap 素材入库：deck 两错（中控 15.6 非 14.6 / 17扬(8) 非 17扬(12)）。

## 不做

清单补项（另立 change）/ 价值分复活 / 底价（v1 端点不收）/ carkit 的 PPT 导入与现抓 / carkit 引擎代码搬移（seat_adjust 方向数差、usb 解析等留口径迭代）。
