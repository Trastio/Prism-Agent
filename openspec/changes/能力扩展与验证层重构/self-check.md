# 能力扩展与验证层重构 · Step 3.5 自查

## Gap 1（必修）· 块4 上下文对象化 pi RPC metadata 未确认
**问题**：v8 说"首选 pi RPC metadata，退化 ctx.json"，但 grep extensions.md/rpc.md 零命中——pi 可能不支持 metadata。
**修法**：施工前先核实（读 rpc.md 完整 + 实测 send prompt 带 metadata）。若不支持→直接走退化方案 ctx.json。

## Gap 2（必修）· 块1.1 verifyScope 改返回类型
**问题**：v8 verifyScope 改返回 `{pass, reason}`，但当前返回 `string[]`（failures 数组）。调用方 verifyCompletion 用 `failures.push(...verifyScope(claim))`。改返回类型需同步改调用方。
**修法**：verifyScope 保持返回 `string[]`，内部用内容组合判定后 push failures。不改返回类型。

## Gap 3（小修）· 块2 decideTier 与既有 decideVerification 的对接
**问题**：tier 路由包裹 decideVerification，但 decideVerification 当前在 agent_settled L711 被调用。tier 路由要在 decideVerification 之前判 tier → 改 agent_settled 结构。
**修法**：agent_settled 先判 tier，再按 tier 路由（library 走既有 decideVerification+verifyCompletion，web 走 verifyWeb，mixed 走 verifyMixed，none 走 decideVerification(text,false)）。

## Gap 4（小修）· 块0.5 prism-web import src/shared
**问题**：prism-web tsconfig include:["src"]，import 仓库根 src/shared 可能不编译。
**修法**：实测。不行则 src/shared 复制到 prism-web/src/shared 或用相对路径 import。

## 自查结论
4 Gap（2 必修 + 2 小修），可进 Step5 施工。
