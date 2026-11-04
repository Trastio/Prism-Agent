# Proposal · 对话功能修复

> 2026-10-05 · P0(角色收窄) + P1(工具链断点) + P2(稳健性)

## WHAT

### P0：收窄前端对话角色
1. 写真正的 SYSTEM.md（不只是 AGENTS.md）
2. 对话模式 excludeTools 收窄（禁 bash/文件/源码）
3. 验证器话术隐藏（不以 user 角色出现在前端）

### P1：打通工具链断点
4. query_sales 加 group_by='spec' 全链路
5. get_sales_detail 参数修（model_id → series）
6. sentiment_* 路径修

### P2：稳健性
7. session_id 透传
8. ChatView args/arguments 修 + 删重复 case
