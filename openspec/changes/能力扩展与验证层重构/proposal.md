# 能力扩展与验证层重构 · Step 2 Proposal

> 2026-10-07
> 前置：[explore.md](./explore.md) + [改造计划 v8](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-能力扩展与验证层重构-改造计划.md)

## WHY
Prism 从专科 agent 变通用助手。web 数据无法严格验证 → 验证层需 tier 路由。library tier 有 7 个失败题（根因已核验）→ 修地基。D 脱敏双实现 + B 上下文前缀 + C 池无上限 + B1 事件丢 → 收编本次。

## WHAT（块0.5 + 5 块）
| 块 | 内容 |
|---|---|
| 0.5 | 脱敏抽单一事实源 + 演示数据外置 |
| 1 | verifyScope 跨维度 + 验证入口短路修复 + runner NEG_RE |
| 2 | TrustTier + decideTier + tier 路由 + verifyWeb/Mixed + M9 |
| 3 | TOOL_CATEGORIES + EXCLUDE 删 + M1 实测 + 提示词 |
| 4 | 回改加固 + 上下文对象化 + memory.json + 单测 |
| 5 | B1 事件补全 + C 池上限/排队/压测 |

## 决策（v8 已拍板）
- tier 基于工具调用（非回复内容）
- tier 路由包裹既有链路非替换
- none tier 回落 decideVerification(text,false) 保留防编数
- M9 保留编造检测，只放宽库外名在 web 真值集内
- M1 推荐 web-search.json 设 eager 消除竞争
- 上下文对象化首选 pi RPC metadata，退化 ctx.json
- memory.json 收编本次（与上下文同函数）
- B1/C 收编本次（49 人正式风险）
- D 收编块0.5（须早于块4）
- export 独立 change

## 验收（26 条，同 v8）
## 不做
export / subagent / office / mem0 / mcp-adapter / 纪律按 tier 选 / 删既有库侧验证 / compaction 改写 / scorer 修复
