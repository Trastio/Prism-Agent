# 身份强制移除 · Step 2 Proposal + Tasks + Self-check

## WHY
用户"打开 Prism 就能发消息，像豆包一样交互，不需要先选车系"。当前身份强制把红线#7（对象核验）和工具可用性耦合——不选车系全关工具，连 web 搜索/闲聊都做不了。

## WHAT（13 项）
删 2 处身份强制 + 新增 2a 持久化 + 2b 执行层判据 + 9 改（SYSTEM.md 4 处 + index.ts 3 处 + pi_gateway 1 处 + completion.ts 1 处）

## 决策
- 全开工具 + 执行层判据（不收窄工具集——会破坏一轮查数）
- 身份证据仅认 resolve_series
- NEG_RE 对齐规格（逐词判定，任一无否定即 fail）

## 验收（13 条同方案）

## Self-check
- Gap1: 2a appendEntry 无条件写（含空值）——已明确
- Gap2: 2b 取最新一条 entry（非首个）——已明确
- 无悬空依赖，可施工
