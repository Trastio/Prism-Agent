# 对话Agent架构重构 · Step8 Receiving Code Review

## 已修
- P0-1 before_agent_start 缺 ctx 形参 → 补 `async (event, ctx) =>`
- P0-2 event.message → event.prompt（pi 官方签名）
- P1-2 /chat switch_session 加 existsSync 校验
- P1-4 /session/switch 成功后更新 rpc.sessionId
- P2-4 App.tsx onToolCall no-op 删除
- P2-5 HOST_WHITELIST 死常量删除

## 留下一轮
- P1-1 KanbanView 看板全空（需产品定夺：内置 series 选择器 / 默认 demo / 废弃看板）
- P1-3 /session/messages 切会有副作用（改只读文件解析）
- P2-1 Sidebar 车系 tab 死代码残留
- P2-2 SeriesCombobox 孤儿文件
- P2-3 ChatView series prop 死参数
- P2-6 AGENTS.md 与 PRISM_GENERAL.md 内容重复
- P2-7 每轮 readFileSync 可缓存
- P2-8 last-verdict.json 多用户竞态
- P2-9 get_state 字段名未实测
- simplify 5 项抽函数
