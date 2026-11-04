# 人工题集转金标 · Step8 receiving-review（2026-10-13）

> Step7 隔离审查结论：无 P0 / 2 P1 / 8 P2 / 4 简化项，可进 Step8。本文记录逐条处置。主会话执行。

## P1（全修）

- **P1-1 sentiment-05 键名口径错** → ✅ 修。主会话先行亲验（QQ3 负面帖事件标签聚合 售后83/质量67/异响57/维权33/提车32/4S店19/交付8 与金标逐项吻合；全量口径为另一串 上市224/提车192/售后152）。键名改"负面话题top(负面帖事件标签)"+expected_evidence 补注；生成器覆盖层同步。
- **P1-2 生成器未同步 3 处拍板改写（复跑回滚裁决）** → ✅ 修。`_gen_user_gold.py` 落盘前插入**裁决覆盖层**（_ov 函数固化 sales-09/config-03/04/sentiment-05 + 4 条口径注记）；重跑生成器 + 内容级 diff 校验——唯一差异为 sales-09 fail_closed 旧措辞"（block0-coder 在途）"（工作已完成，覆盖层版更准确，采纳生成器版），其余 38 题逐字一致。重跑幂等。

## P2（修 4 / 记 4）

- **P2-1 supported_by 口径错位 3 题** → ✅ 修（注记法）：reviews-03/04/06 expected_evidence 各补口径注记（车系级维度行 vs 版型级分组结论的支撑关系）。审查所指"第三处"定位：reviews-06（B1 陷阱题）supported_by 为两车系智能化/con 行，注记明确其仅佐证库内存在性、判分锚在"B1 不存在"。
- **P2-2 sentiment-03 排序口径微义差** → ✅ 修（注记法）：负面主题按负面帖计数（提车类亦有计数属口径细节，判分按方向）。
- **P2-3 verify 覆盖缺口** → ✅ 部分修：_verify_user_gold.py 固化 3 条审查代查断言（QQ3 负面话题 top7=金标 / 奇瑞集团 BEV top3=金标 / T1000 舆情库=0）。未固化项：筛选题输入属性完备性、reviews-10 站方口径等——随 Block2 转库时并入 truth-expectations（那里是更正确的宿主）。
- **P2-4 测试缺跨年锚月/平票用例** → ✅ 修：新增 2 测试（test_cross_year_anchor_prefers_latest_year——本 change 核心教训的回归保护；test_mode_tie_break_ascending_deterministic）。首跑即绿（20/20）。
- **P2-5 _meta.semantics 无断言/cap50 无真实验证/数据层 limit 无下限** → 部分：数据层 limit 钳 `max(1, limit)`（:334）；_meta 断言与真实验证大 fixture 留 Block2/Step9（活端点验证时覆盖）。
- **P2-6 数值参数接受 nan/inf** → 记录：extension 枚举约束下低危；路由层如需收紧加 isfinite 校验，留下一轮。
- **P2-7 文档漂移 3 处** → ✅ 修：tasks.md 行号 :731→**:885**（并行会话改动致漂移，已核）；design.md Block0 补 brand 规格（拍板B）；Block2 补 dimension 英文→中文映射注记。
- **P2-8 缓存键裸 k=v 拼接理论撞键** → 记录：参数全枚举+数字下实际不可达；留 P1 阶段 web 录制回放改造时一并加 quote。

## Simplification（修 1 / 记 3）

- ✅ _verify_user_gold.py :96 死行 `pid =` 删除。
- 记录：market_series_filter 与 market_series_all(:148-174) 内联重复可抽公共函数（审查已比对语义等价；涉工作代码重构留下一轮）；tests 两用例断言重复；数据层 energy ValueError 兜底保留（有意双保险）。

## Step9 增补事项（来自审查建议）

- 活端点验证抽核清单**加入 sales-08/10**（审查者已用同算法代查吻合，可作对照）
- 复跑全套验证：pytest 20/20 + _verify_user_gold.py 131 断言（128+3）+ 生成器重跑幂等

## 附：本步环境事实

- 并行会话（北极星看板 + 配置赋值口径改造两个 change）同期推进，prism-api 行号漂移两次（731→885），market_data.py 有磁盘变动提示——本步所有编辑前均重新 grep 锚定，无冲突。
