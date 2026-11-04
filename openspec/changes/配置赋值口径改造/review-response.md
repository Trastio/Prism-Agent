# review-response · 配置赋值口径改造（Step8）

- 审查：2026-10-13 隔离子代理（general-purpose + 代码全文内嵌 ~40KB，不给设计结论）
- 报告：1 P0 + 3 P1 + 6 P2；主会话逐条核实后处置如下

## 处置总表

| 编号 | 发现（一句话） | 核实 | 处置 |
|---|---|---|---|
| P0-1 | 手填价 `"Infinity"` 过 `float()`+`>=0` 防线 → round(inf) OverflowError → 500 | 成立（float("Infinity")=inf，inf≥0 True） | ✅ 修：端点 isfinite 守卫；TestClient 实证 200 |
| P1-1 | 全缺采列"差价值不可用"但 config_adv=0.0、端点 `or 0` 吞成有效拉平价 | 成立（初值 0.0 只挡 blocked 未挡 available） | ✅ 修：config_adv 加 available 守卫（legacy 同）；端点显式 None→"配置差价不可用"；单测 test_unavailable_column_config_adv_none |
| P1-2 | has_diff 原始字符串比较 vs _cell_state 三态口径分裂（["○","—"] 假 blocked） | 成立 | ✅ 修：_row_sig 语义签名（absent/missing 折叠为状态；present 保留 strip 原文）；same_all 同修；单测×2 |
| P1-3 | config_diff 超大数字段 int 绑 SQLite 抛 OverflowError 逃出 except → /verify/claim 500 | 成立（OverflowError∉ValueError/sqlite3.Error） | ✅ 修：except 元组加 OverflowError |
| P2-1 | round() banker's ≠ JS Math.round half-up（10000.5→10000） | 成立 | ✅ 修：_fmt_amount 用 floor(x+0.5)；单测 |
| P2-2 | 多列（≥3）行级 verdict 塌陷为"不计"且无金额，与列汇总矛盾 | 成立 | ⚠️ 缓解：note 下发 amounts 数组（前端未消费）；行级多列展示留口径迭代 |
| P2-3 | note() None 过滤吞显式重置（重复 id 行） | 不可达：rows 的 id 来自 concept_configs 唯一遍历，单趟每 id 一次 | 📝 记录不修 |
| P2-4 | diff_pricing 字段缺失（手编表）→ KeyError 500，与 fail-closed 姿态不一致 | 成立 | ✅ 修：flat/per_unit/threshold 字段访问 fail-closed 入 missing；单测 |
| P2-5 | _manualPrices 切换对比对象残留并静默计价 | 成立（模块级无清空点） | ✅ 修：renderHorizontalCompare 顶部清空（手填路径走 refreshDiffFromServer 不经此处） |
| P2-6 | 200+error 体污染 _hcData（路由 error 信封走 200） | 成立 | ✅ 修：GET/POST 两处 fetch 加 `j.error` 守卫 |

## 修复后验证

- pytest 36/36（31 原有 + 5 审查回归：unavailable/假blocked×2/half-up/字段缺失）
- smoke:all 全绿；根 tsc 零新增（TS5097 历史基线除外）
- TestClient：Infinity 手填 → 200 正常出数（-4300/+5700 不变）；常规 GET 回归一致
- 8010 活页面四检查：新 hint 在/新函数在/旧 JS 无/renderDiffFoot 在

## 教训

本轮隔离审查再次验证"设计者对自己以为的行为有盲区"——P0-1 的防线注释自称"API 防线"却只挡了负数；P1-1 是我写引擎时主动埋的初值 0.0 被下游 or 0 放大。审查子代理未给设计结论，全部发现靠代码自证，均一次核实成立（0 误报；上一会话曾出现的虚构报告未复现，"实证推导链"硬要求有效）。
