# Step8 · Step7 审查处置（2026-10-16）

> 审查结论：0 P0 / 1 P1 / 4 P2，无阻首跑问题（step7-review-report.md）

## 处置表

| 级别 | 发现 | 处置 |
|---|---|---|
| P1-1 | budget_capped 触顶不可见：collection.py 只判 error→触顶后继续 Phase 2-9→终态覆盖 completed→daily_update 假"完成"退出 0 | **已修**：①collection.py 早退分支扩为 `in ("error","budget_capped")`（终态=budget_capped 不再被覆盖）②daily_update 加 capped 分支（单列统计+结束行汇总+次日自愈说明，不计 failed 不改退出码）③回归钉 test_pipeline_budget_capped_not_completed（断言终态≠completed） |
| P2① | 护栏计数在重试循环外：一次 _send 内最多 5 次计费重试只计 1 | **已修**：count_and_check 挪进循环顶（每次 HTTP 尝试前计数）；except 面核实过——AuthError 直抛/网络三态窄捕，预算异常（不继承 TikHubError）不会被吞 |
| P2② | 首跑 xhs 空窗补采变薄：10 天窗落"一月内"粗档+1 页+6 词，10-08~10-14 段趋势永久偏薄 | **待用户拍板**：接受（缺口段趋势略薄，两平台仅 xhs 受影响）vs 首跑后手工补采一轮（临时 2 页）——荐接受，两天窗的历史趋势价值有限 |
| P2③ | 每日双份互动刷新（Phase 9 每车刷+尾部 run_all 再刷，≈300 次/天存量冗余） | **记录**：存量行为非本 change 引入；首跑稳定后的"归档码清理轮"一并处置（省 ≈$0.6/天） |
| P2④ | run_cleanup dry-run 早返回泄漏一个连接 | **记录**：影响近零，清理轮顺手修 |

## 验证

- 全量 pytest：**900 过 + 新增回归钉 = 901 过** / 1 存量挂（test_cache_bust）
- 关联面（collection_api / budget_guardrail / daily_update）29 测全绿

## 遗留移交

- P2② 用户拍板 → Step9 前收口
- P2③④ + 归档死码清理轮（_collect_news 等）→ 首跑稳定后独立小轮
