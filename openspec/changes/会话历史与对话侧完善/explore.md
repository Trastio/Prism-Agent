# 会话历史与对话侧完善 · explore（2026-10-12 实测）

> 起因：用户问"会话历史功能还存在么"——核对发现三件套半存在：列表✅/续聊✅/**历史回显❌**（死码清理删了零调用的 /session/messages，当时裁定"真要做时按需重建 20 行"），且藏一个串显 bug。本 change 同时收编两个已拍板小活（EvidenceDrawer 对话侧=选项A、被拒输入日志）。

## 1. 会话历史三件套现状（2026-10-12 核对）
- 列表：GET /session（网关 readdir + names.json custom_name，10-11 rename sidecar 已修）✅
- 续聊：/chat 带 session_id → 网关 switch_session（pi_gateway.mjs L434-446，resp.data.cancelled 语义已修）✅
- **回显：无**——main.py/网关均无 /session/messages（grep 零命中）；ChatView 切换会话只同步 id（ChatView.tsx L95 `useEffect(() => { setSessionId(sessionIdProp); }, [sessionIdProp])`），msgs 不动
- **串显 bug**：切换会话不清 msgs → A 会话的消息挂在屏幕上续 B 会话的新消息
- **新建会话语义 bug**：Sidebar"新建会话"只 onNavigate('chat')，selectedSessionId 保留 → 点新建仍续在旧会话上

## 2. 技术路径实测
- **pi RPC `get_messages`**（pi-windows-x64/docs/rpc.md:218）：作用于**当前活跃会话**，返回 `data.messages = AgentMessage[]`（Message Types 结构子代理施工时读同文件核对：user/assistant content blocks 含 text/thinking/toolCall；toolResult 形态需核实）
- 网关端点模式：switch_session(reqSessionId) → get_messages → rpc.sessionId 同步（与 /chat 现有 switch 逻辑一致，L437-453 有成熟先例，含 resp.data 读取坑）
- vite proxy `/session` 前缀已覆盖 /session/messages ✓
- main.py 转发先例：GET /session（L432）、POST /session/rename 均直接转发 PI_SERVER

## 3. EvidenceDrawer 接线（选项 A，2026-10-11 用户拍板方向）
- 组件休眠中：EvidenceDrawer.tsx 存在（EvidenceData{num,unit,name,src,asof,scope}），全站零入口（三看板 iframe 化后 onEvidence 链路悬空）
- **零后端改动链路**：submit_conclusion 的 schema（extension 实读）args 含 conclusion_text/supported_by[]/as_of/scope/data_gaps_declared/numbers[{value,source,derived_from}]——**网关 mapEvent 已把 tool_call(含 args) 发前端**（ChatView L144 已消费 tool_call 事件）→ ChatView 捕获 name=submit_conclusion 的 args 存为本轮 claim → 最后一次 submit（重试链末端=过闸那次）→ 渲染溯源 chips → 点击开抽屉
- 抽屉需小幅扩展：supported_by 数组/numbers 列表/conclusion_text 渲染（现有单值字段不够）
- App.tsx 已有 openEvidence/EvidenceDrawer 挂载（drawerOpen/evidence state）——复用现有管线

## 4. 被拒输入日志（series_alias 后路，2026-10-11 拍板）
- main.py /identity/resolve 的两个拒绝返回点：needs_online_verify（L~810 降级模式精确名未命中 + alias 未命中）与 ambiguous（多候选）——各 append 一行 JSONL 到 logs/identity-rejected.log（{ts, series_key, reason}；端点无 user_id 参数，不记）
- 用途：49 人开放后用真实被拒输入决定是否建 alias 表

## 5. 环境注意
- ChatView.tsx/Sidebar.tsx/App.tsx 是并行会话活跃区（昨夜至今多次变更：TikHub 状态灯、中止键双态发送键等）——施工以盘上最新代码为基线，改动区域避开中止键相关段（handleSend/streaming 逻辑）
- 五服务当前全绿；网关池空；PRISM_AUTO_APPROVE_UI 由 prism.py 内置
