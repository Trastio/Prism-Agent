# Prism-Agent · M0 基线 · smoke 全集 · 2026-10-06

> 改前快照（phase3-convergence 接线前）

## smoke:all 结果（6 个全过）

| smoke | 状态 | 关键验证 |
|---|---|---|
| datasource | ✅ | 3 数据源注册，银河E5 286行+2026月末53行 |
| identity | ✅ | 4 case：银河E5 命中/铂智7X needs_online_verify/7X歧义7候选/虚构 fail-closed |
| tools | ✅ | 3 query 工具取数 |
| grounding | ✅ | 8 名称错误测试集拦截 + 数值容差 |
| m3 | ✅ | 销量真值 + 口碑维度真值（舒适 pro150/con337） |
| guard | ✅ | 21 passed 0 failed（拦截/自回灌阻断/isRetryTurn） |

## 当前状态摘要

- extension 23 工具（3 query + 6 sentiment + 14 Atuohome）
- agent_settled 内联 regex 验证（不 import completion.ts）
- {series_key} 硬编码银河E5
- 无 fail-closed 未知工具
- better-sqlite3 在项目根 node_modules（M1 移植验证 resolve）
- scorer.ts 是死码（runner 用本地正则）

## 16 题基线

推迟到 M1 接线后跑（接线前跑旧代码 trace 有 bash，意义不大）。
