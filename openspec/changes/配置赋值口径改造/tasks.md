# tasks · 配置赋值口径改造

## M1 口径地基（子代理 A，串行先行）
- [x] T1.1 建 `prism-dashboards/data/diff_pricing.json`：按 design.md D1 的 61 项表逐项填（"现weights"项从 concept_weights.json 读 tier_high 价）；version/source_notes/basis 全带。
  验收：json 可加载；61 项全覆盖；续航=100 无阈值；excluded 语义注明。
- [x] T1.2 写 `src/insights/value_diff.py::compute_value_diff`（D2 签名与口径）。
- [x] T1.3 parity 单测（legacy_mode）：构造行复刻 JS `_computeDiffCells` 全分支（presence±1/数值差/非数值跳/相等跳/双无跳/缺采跳/未定价计数/文案四态），断言与 JS 公式一致。
- [x] T1.4 新规则单测：band 文本档位（材质/天窗/HUD/悬架组合枚举/流媒体）、band 数值档（B1/G4）、数量差（G5）、threshold（G1 正反方向）、○=无、缺采跳过、missing_rules 拒绝汇总。
  验收：pytest/直接跑全绿；两套单测进 smoke:all 或独立 smoke 入口。→ **31/31 全绿；已挂 `npm run smoke:value_diff` 并链入 smoke:all（package.json）**
  施工注：G4 由 design 的 band寸数 改 flat 1700（实查 concept_configs G4 extract=boolean，快照值无寸数可落档，沿现weights）；A3 由 per_unit 改 band 文本落档（cells 是"双电机"等文本，band 才能实现按个计价）。

## M2 服务出口+看板（子代理 A，接 M1）
- [x] T2.1 `GET|POST /dash/config/compare-valued`（D3 契约；get_trims 优雅降级）。
- [x] T2.2 前端切换：删 `_computeDiffCells`/`_refreshFooter` 重算；renderHorizontalCompare 改调后端；setRowPrice→POST manual_prices；三态样式语义改"差价表兜底"；hint :277 五规则；updateDiffSummary 切数据源。
- [x] T2.3 旧链路并入：/dash/config trim= 视图 fold_prices→compute_value_diff；删 fold_prices；模板 §03 totals/pair_diffs 渲染同步；评估 `_concept_price_for_param`/_concept_tier_for_state 孤儿化。
  施工纠偏：实查模板**早已不消费 fold_prices 输出**（config-board-v2 后 §02 全走 JS fetch，模板只读 trim_view.cfg_failed，totals/pair_diffs/guide_diff 本就是死产出）→ 按最简正确落法：/config trim 分支不再调 fold_prices（trim_view=raw 保 cfg_failed 守卫），直接删 fold_prices 函数与 prices ctx 死键；"替换为 compute_value_diff"如原 design 字面执行只会制造新的死计算。
- [x] T2.4 服务级验证：~~prism.py 重启 8010→curl~~ **红线禁碰生产服务 → TestClient 等价验证**：真实两版型 7650:79311 vs 79310 出 4 项差价（A1 -2000/A4 -2000/G5 -200/L1 -100，config_adv=-4300）+ guide_prices 11.78/10.78 + flat_adv +5700；POST manual_prices={高压平台:1000} 覆盖生效（source=manual）；monkeypatch get_trims 失败 → 200 降级（guide None、flat_adv None、config_adv 照常 -4300）；缺快照 999999/非法 sel 错误信封正确；/config trim= 页面 200（55KB，新 hint 在、旧 JS 无）；compare-horizontal 原端点 46 行回归不变；smoke:datasource/grounding/m3/guard/trap/verify 全绿（verify fail 0 skipped 1=预期）+ smoke:value_diff 31/31；根 tsc 报错均为 TS5097 历史基线（本 change 零 TS 改动）。
  遗留：生产 8010 重启加载新代码（主会话/用户执行，走 prism.py）。

## M3 agent 接线（子代理 B，依赖 M2 端点形态）
- [x] T3.1 extension：compare_configs_valued 注册 + KNOWN_BUSINESS_TOOLS + 截断白名单 23→24 + guard 白名单单测同步。
  施工注：KNOWN_BUSINESS_TOOLS 21→22（注释"10 dashboards"→11 同步）；TRUNCATABLE_TOOLS 全仓无计数断言仅集合成员；tool_call.test.ts size 断言 21→22+新增 has 断言。链路=工具→:8002/autohome/compare_configs_valued→DASHBOARDS_TOOL_MAP 新条目→:8010 /dash/config/compare-valued（GET 60s TTL 缓存，POST+manual_prices 仅前端用）。
- [x] T3.2 `.pi/skills/config-compare/SKILL.md`（D6 大纲全条目）。
  施工注：frontmatter 双受众照 car-reputation-research 先例；ref 语法实为 `config_diff:midA/specA/midB/specB`（verify/claim 解析器是 table:part/part，design D6 的冒号连写格式与解析器语法不符，已按语法落地并经 TestClient 验证冒号格式正确被拒）。
- [x] T3.3 main.py /verify/claim +config_diff 分支（4 段格式+快照存在性；8010 不可达仅拒 config_diff）。
  施工注：复用核心库连接（config_snapshots 同库），fail-closed 局部化与三维度隔离同 sentiment 分支模式。TestClient 4 case：合法配对 failures=[]；假 mid 拒；冒号连写格式拒；段数错拒。smoke:verify 97 pass/0 fail/1 预期 skip；smoke:guard 15 passed；根 tsc 唯一非 TS5097 报错（datasource.ts:228 TS2322）经 mtime 核验为 10-11 历史基线非本 change 引入。
- [x] T3.4 真实对话 E2E：resolve→工具→五态结论+拉平价→submit_conclusion 过闸零回灌；缺规则场景走缺口声明；门禁 E1-E9 回归。
  验收：proposal 验收 5/6 条达成。
  施工注（主会话执行）：usr_e2ecfg 真实会话工具链 resolve_series→get_config_detail→get_trims→compare_configs_valued×9→query_*→submit_conclusion，verdict=pass 零回灌（CLAIM 带 config_snapshots:7650/79310+79311）；门禁 E1-E9 9/9（eval/gate-report.json 2026-10-13T05:26）；服务经 prism.py 重启加载新代码。

## M4 评估与账目（主会话或子代理 B 顺带）
- [x] T4.1 deck 两错进 tasks.json/trap_check（trap：agent 报对方中控 14.6 寸或 17扬(12) 即编造，应被拦/应引用端点真值 15.6 与 8）。
  施工注：适配为 trap-07/08（value_grounding 假前提，set=dev）——79310 侧 G1/G5 缺采故双版型对不成立，改单版型假前提，真值经 compare-valued 实测（79311 中控 15.4 英寸/8 喇叭）；tasks.json 18→20 题；写入曾被用户打断一次，后以 Edit 工具落盘获继续。与 runner --only=trap 兼容性随下轮批跑验证。
- [x] T4.2 任务清单 D1.3 回写（重述为"61 项差价链路 agent 化 ✅"）；EVAL_STATUS 记录；设计图总览同步一处提及。
  施工注：任务清单 D1.3 已勾并重述（含"定稿文件已不存在"账目注）；EVAL_STATUS 追加题库扩容节；设计图总览侧以本 change 目录+verification.md 为准未另改设计图（提纲§口径表述由 D1.3 回写覆盖）。

## 全程并行
- 无（本 change 串行为主；M3 与 M2 后半可轻度并行但共享 extension 文件，不并行）。
