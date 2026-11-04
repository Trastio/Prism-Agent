# archive · 配置赋值口径改造（Step10，2026-10-13 归档）

## 一句话

把配置差价口径从"前端 JS 独算"下沉为后端唯一实现并按 carkit 拍板口径升级（文本档位差/数量差计价），打通 agent 出口（工具+skill+出口闸引用），看板与 agent 双端消费同一引擎。

## 十步走痕

Step1 explore ✅ → Step2 四件套 ✅（specs/ 三件于归档后补录，按施工实际执行契约整理）→ Step3.5 自查 7 Gap ✅ → Step5 施工（fork 子代理 A=M1+M2，fork 子代理 B=M3，主会话 T3.4）✅ → Step6 simplify（guide_diff/_diff_vs_min 死代码清除）✅ → Step7 隔离审查（1P0+3P1+6P2）✅ → Step8 处置（修 6 记 2，review-response.md）✅ → Step9 验证（verification.md，7 条全达+3 声明项）✅ → Step10 归档（本件）✅

## 交付物

| 层 | 文件 |
|---|---|
| 真值表 | prism-dashboards/data/diff_pricing.json（61 项，v1-20261013，续航=Prism 100 元/km、其余 carkit 口径带 basis） |
| 引擎 | prism-dashboards/src/insights/value_diff.py（compute_value_diff，4 型 flat/per_unit/band/threshold，missing 拒绝汇总） |
| 端点 | GET\|POST /dash/config/compare-valued（同源取数+指导价降级+拉平价） |
| 看板 | dash_config.html（差价 JS 删净改调后端；hint 五规则；三态语义=差价表兜底）；fold_prices/compare_trims 折价层删除 |
| agent | extension compare_configs_valued（白名单 22/24）+ .pi/skills/config-compare/ + /verify/claim config_diff:midA/specA/midB/specB 分支 |
| 评估 | tasks.json trap-07/08（value_grounding 假前提）；EVAL_STATUS 补记；任务清单 D1.3 回写 |

## 验证快照

36 单测 + smoke:all 全绿；TestClient 真实配对 config_adv=-4300/flat_adv=+5700；真实对话 E2E verdict=pass 零回灌（工具链含 compare_configs_valued×9）；门禁 E1-E9 9/9；8010 活页面四检查过。

## 审查账

1P0+3P1+6P2 → 修 6（isfinite/available 守卫/_row_sig/OverflowError/half-up/字段 fail-closed/清手填/error 守卫）+ 记 2（P2-2 多列行级塌陷已加 amounts 缓解；P2-3 不可达）。详见 review-response.md。

## 留给下一轮

1. **补项 change**：carkit 独有 ~9 项（轮圈材质/前备箱/主动进气格栅/灯光/车联网/方向盘材质/USB 数量/车外扬声器/后排出风口±中央气囊）——每项需核之家字段+extract 规则；excluded 语义在 diff_pricing.excluded 预留；**USB 项照抄 carkit 新口径"默认共 3 个 0 元仅额外计差价"**（2026-10-13 usb.py default 修正）
2. **口径迭代愿望单**（carkit 2026-10-13 更新后刷新）：F2 方向数差×50（seat_adjust 解析）、G2 lcd_bonus、**G6 无线充电快慢充分计（快充 350/个、慢充 100/个，≥40W=快充，按前排/后排位置计数——wireless.py，需位置解析）**、**D1-D3 气囊按颗计价（airbags.py 位置级计数：主副驾各1/侧气囊前后排各2/头部前后排各1/中间1/膝部每标配项1——需位置解析）**、G4 副驾屏寸数档、B1 铝轮毂+500
3. **浏览器人工走查**：手填→POST→tfoot 更新的真人点按（代码链路+TestClient 已证）
4. **trap-07/08 批跑计分**：随 38 题人工题集全量轮；与 --only=trap 兼容性届时确认
5. **score_concept 孤儿**：保持归档；若棱镜交叉需要价值分维度另立 change
6. 敏感性备忘：diff_pricing 的 carkit 金额经用户 2026-10-13 拍板采用；T19NG 自产品配置数据从未进 Prism

## 归档后追加 · carkit 上游同步（2026-10-13 晚）

carkit 三日三更（10-12 阶梯扩展/10-13 气囊计数+映射修正/10-13 USB 默认值），对我们口径的落点：
- **已修**：M2 可变悬架对齐新 suspension.py 语义——空气/魔毯悬架=软硬+高低组合=9000 元（原表"魔毯"不含关键词 fallback 0 漏计 9000、"空气"单独 8000 漂移，均修+单测 7 断言）；顺带修 band 0−0=非差异语义（0 元档 vs 无不再计 0 元差异行，改"文本差异不计价"）
- **金额全表核对**：DEFAULT_DYNAMIC_PARAMS 仅 #33 新增 slow_charger:100，其余与已并入金额一致——无需重灌
- **愿望单更新**：G6 快慢充分计、气囊按颗（两个都需位置级解析，属引擎能力，非表数据）
- **确认无影响**：氛围灯（只分无/单色/多色，与表一致）、激光雷达（仍 excluded 计价）、USB 默认口径（补项 change 时照抄）

## 归档后追加 · skill v2 + 出口闸源登记第二弹（2026-10-13 深夜）

用户反馈"skill 范围窄+效果不好"→ 四轮同题复跑定位三 bug，全部修复：
1. **load_skill 目录漏列**：模型侧技能目录硬编码在 load_skill 描述里且只有 car-reputation-research——config-compare 永不触发（面板 /skills 目录扫描正常=注册假象，**两套目录**）。已补列。
2. **sel 参数容错**：makeAutohomeTool execute 对 compare_configs_valued 加字符串→数组归一（模型偶发传 "a:1,b:2"）。
3. **autohome 反代折叠重复键（最深）**：main.py `dict(request.query_params)` 把 sel=a&sel=b 折成单值——**agent 路径 compare_configs_valued 从未成功过**（M3 验证结论更正：verdict 骑的是 config_snapshots 引用）。改 multi_items() 保序转发。
4. **skill v2**：范围=差异/差价两用（纯差异只讲判定不报金额）、触发词扩配置差异类、版型选择指导（车系级→get_trims→默认主力版型开口声明）、口径声明轻量化、numbers 两条硬规则（纯数值/derived 声明）。
5. **出口闸源登记第二弹**：tool_result 加形态感知采集（三配置工具的 cells 数值/price/amount + 概念名/车系版型名入双账本）+ submit_conclusion 描述加数字格式两条硬规则。修后：工具调用 39→14→10、compare 1 次成功、数字类拒因清零；剩余 3 拒全为 R1-deep 名称散文误报（一轮自纠内容零伤害），**名称校验分层列愿望单**。纯差异结论 submit 仍 4 次（3 误报自纠），用户侧无感仅多耗 token。

## 基建沉淀（跨 change 复用）

- 施工子代理必须 **fork 型**（general-purpose 无 Read/Write/Edit/Bash，第 0 步自报防线让它安全空转）
- 隔离审查=general-purpose + 待审代码全文内嵌 + 硬性"输入→行→错误输出"推导链——本轮 0 误报全实证
- 改前备份 snapshots/ 的价值：本轮靠它裁决"已删 JS 的 parity 疑点"（_unitPrice 对 0 价行的处理）

## 归档后追加 · 清单补项 11 项 + 看板拉平价行（2026-10-14，用户拍板"看板也需要上这些"）

- **清单 61→72 项**（concept_configs v1.1 配套 diff_pricing v1.1-20261014）：B2 轮圈材质/D4 中央安全气囊/E3 主动闭合格栅/E9 近光灯光源/F9 前备厢/F16 方向盘材质/G7 USB 接口/G8 车外扬声器/J2 车联网(4G/5G)/L2 后排出风口——字段名全部从真实快照核出（前备厢容积(L)/激光雷达数量/4G/5G网络 等真名）；K1 激光雷达入 excluded（参与比较不计价，carkit '/' 语义）
- **引擎两处增强**：excluded.ids 豁免（不进 missing 不阻断汇总）+ sum_numbers 求和语义（USB"前排3个/后排2个"=5，差值口径下基础 3 个自然抵消）
- **看板拉平指导价优势行**：renderDiffFoot 二行——flat_adv 下发时显示"列2 比列1 ±¥X（配置差价+指导价差）"，不可得时显示原因（flat_adv_reason）
- **验证**：pytest 59/59（含 excluded 豁免+USB 求和+版本断言更新）；重启后实测 7650:79311 vs 79310：10 新项出现（D4 该系无字段整行不出现=正确）/K1 不计/blocked=False/config_adv -6800/flat_adv +3200（口径升级后数字变化）；smoke:verify 107/0；JS 语法过
- 之前记录的"补项 change"就此销账（本追加节即交付记录）
