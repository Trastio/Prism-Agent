# self-check · 配置赋值口径改造（Step 3.5 自查收敛）

过审对象：proposal/design/tasks 三件 + explore。逐项过，7 个 Gap 已修入文档：

1. **Gap-parity 单价源切换**：parity 锁公式不锁单价源（design D2 legacy_mode 仅供测试），否则 T1.3 必假绿。→ 已写入 D2 与风险#1。
2. **Gap-C2 增量语义**：城市NOA=3000 拆分与 carkit 档位差的一致性依赖"C2 蕴含 C1"领域假设——已标注进 D1 表，skill 里也要求该假设随结论披露。
3. **Gap-D1 band 数值档**：B1 用 band 而非动态公式（(寸−16)×700 枚举到 R16-R22），避免引擎引入公式求值；若出现 R23 以上→落不了档→missing（fail-closed 正确行为，不补猜）。已在 D1 注明。
4. **Gap-get_trims 活接口**：指导价走 autohome_api 网络调用——端点必须 try/except 降级（T2.1/T2.4 有断网模拟）；skill 写明"无指导价只出配置优势"。
5. **Gap-模板 §03 消费者**：fold_prices 的 totals/pair_diffs 被 dash_config.html §03 渲染消费——删层不同步模板=白屏级回归。T2.3 显式含模板同步。
6. **Gap-白名单三处同步**：KNOWN_BUSINESS_TOOLS、截断数据工具白名单（23→24）、guard 白名单单测断言——漏一处=工具被 fail-closed 拦或截断旁路。T3.1 三处并列。
7. **Gap-出口闸范围**：config_diff 不可达仅拒 config_diff 引用（照 sentiment 分支的 fail-closed 局部化），不拖累三维度——D6 已写。

另核对（无 Gap）： mv_* 已退役不受影响；compare-horizontal 原端点保留不动（get_config_detail 工具仍用它，本 change 只增不删端点）；extension Bun 侧无原生查库需求；smoke 现有 57 项不受口径影响（m3 断言是口碑不是配置差价）。

**结论：spec 层无悬空依赖、验收可验、口径表可施工。可进 Step5。**
