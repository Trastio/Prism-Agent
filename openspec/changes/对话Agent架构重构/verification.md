# 对话Agent架构重构 · Step9 Verification（最终版）

## 验收
1. ✅ 顶栏无 SeriesCombobox / 蓝点
2. ✅ 侧栏无"车系" tab（只有"会话"）
3. ✅ 状态栏无三维度 / 数据源蓝点
4. ✅ "你好" → 闲聊（PRISM_GENERAL.md 注入，不含 prism_dimensions/discipline）
5. ✅ verifyWeb host 白名单降为标记（通用来源放行，真值集保留）
6. ✅ memory.json 删除（读+写全删）
7. ✅ 前端不传 series_key
8. ✅ smoke:all 5+43 全过 + tsc 零错
9. ✅ /session/switch + /session/messages 新增
10. ✅ /chat 读 session_id + switch_session + existsSync 校验
11. ✅ session_info 返真实 id（get_state）
12. ✅ ctx.json per-session
13. ✅ session_id 白名单校验
14. ✅ before_agent_start 意图检测（event.prompt + ctx 形参修复）

## Step8 修复
- P0-1 ctx 形参 + P0-2 event.prompt（提示词分层链路修复）
- P1-2 existsSync + P1-4 rpc.sessionId 更新
- P2-4 onToolCall no-op + P2-5 HOST_WHITELIST 死常量

## 留下一轮
P1-1 KanbanView 空看板 / P1-3 /session/messages 副作用 / P2 死代码清理 / simplify 抽函数
