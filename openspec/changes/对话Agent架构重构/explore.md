# 对话 Agent 架构重构 · Step 1 Explore

> 2026-10-07
> change: 对话Agent架构重构
> 对象：[改造方案 v4+收敛](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-对话Agent架构重构-改造方案.md)

## 4 项施工前核实结果

### 1. get_messages 返回结构
- 返回 `{messages: [AgentMessage...]}` — AgentMessage 对象（rpc.md L230）
- AgentMessage 含 role/content/toolCall 等字段（需实测具体结构，rpc.md 引用 Message Types 但未展开）
- 前端渲染映射：需在施工时抓一次真实返回确认字段

### 2. ctx.json per-user → per-session
- 当前：`ctxPath = resolve(SESSIONS_DIR, userId, 'ctx.json')`（pi_gateway L413）— per-user
- 需改：per-session（切会话时 series/as_of 不错配）
- 方案：ctx.json 路径改用 sessionDir 或在 switch_session 时清空

### 3. session_before_switch
- pi extensions.md L416-421 有 `session_before_switch` 事件（可 cancel）
- 当前 prism-guardrails **未注册**此事件 → 安全（不会 cancel switch）

### 4. pi compaction
- settings.json L16-19：`compaction.enabled=true / reserveTokens=16384 / keepRecentTokens=30000`
- compaction 保留近期 30000 tokens（约 15-20 轮对话）
- memory.json 删除后同会话远期结论可能丢（compaction 截断），但近期上下文保留 → 影响有限

## 其他核验（方案断言）

- /chat 不读 session_id ✅（pi_gateway L381-419 只读 message/scope/user_id/series_key）
- session_info 返 userId 非 sessionId ✅（L432 `rpc.sessionId || userId`，L119 `this.sessionId = userId`）
- ChatView 不加载历史 ✅（L56/L67 只 setSessionId 无 fetch）
- /session/rename 未实现 ✅（grep 零命中）
- memory.json 每轮注入 ✅（index.ts L778-792）
- verifyWeb host 白名单全是汽车站 ✅（index.ts L459）
- AGENTS.md 每轮全注入 ✅（index.ts L758-761）
- switch_session / get_messages / get_state / new_session 全是 pi RPC 原生命令 ✅

## 待办（15 项同方案清单）

### P0 会话模型（层0）
- [ ] 1. /session 列表返 sessionFile + id 统一
- [ ] 2. /session/switch 新增
- [ ] 3. /session/messages 新增
- [ ] 4. /chat 读 session_id + switch_session
- [ ] 5. session_info 返真实 id
- [ ] 6. session_id 白名单校验
- [ ] 7. ctx.json per-session
- [ ] 8. 前端 ChatView 加载历史
- [ ] 9. 前端新建会话改调 POST /session

### P0 提示词分层 + 删 memory.json（层1）
- [ ] 10. AGENTS.md 拆通用层 + 数据能力子层 + 分析框架子层
- [ ] 11. SYSTEM.md 通用角色 + 汽车上下文按需
- [ ] 12. before_agent_start 关键词检测 + 选注入
- [ ] 13. 删 memory.json 读+写

### P1 验证层通用放行（层2）
- [ ] 14. verifyWeb host 白名单降为标记 + 通用放行

### P1 前端去车系核心（层5）
- [ ] 15. 删 SeriesCombobox + 车系 tab + 三维度 + 数据源蓝点 + series prop + seriesKey 传参
