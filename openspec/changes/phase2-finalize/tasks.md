# Tasks · 阶段2 收尾

| ID | 任务 | 状态 |
|---|---|---|
| T1 | 启动三方（vite + FastAPI + pi_gateway） | ✅ |
| T2 | 浏览器 ChatView 对话验证 | ✅ 浏览器 fetch /chat/stream 收到 NDJSON 流 |
| T3 | session 连续两轮验证 | ✅ agent thinking 记得"银河E5"（上下文持久）；完成验证器太激进待调优 |
| T4 | P1#4 abort 循环 | ✅ eventQueue 推 aborted + while 检查 |
| T5 | P1#5 并发锁 | ✅ inflightLocks 串行 |
| T6 | P1#6 超时清理 | ✅ 超时发 abort + 丢弃迟到响应 |
| T7 | P1#7 auto-approve gate | ✅ env PRISM_AUTO_APPROVE_UI |
| T8 | P1#8 SQL 白名单 | ✅ 工具白名单 + bash 检查 |
| T9 | P1#9 read_meta 白名单 | ✅ _META_TABLES |
| T10 | P1#10 SSRF path 白名单 | ✅ 禁 .. + content-type 限制 |
| T11 | P1#11 错误固定文案 | ✅ "对话处理出错，请重试" |
| T12 | P2#12 UTF-8 StringDecoder | ✅ |
| T13 | P2#13 Windows taskkill | ✅ proc.kill() + 通知等待者 |
| T14 | mapEvent 事件映射 | ✅ RPC 原始→前端友好(text_delta/tool_call/tool_result/settled) |
| T15 | 精简 agentDir（禁 pi-memory） | ✅ .pi/agent-minimal + PI_CODING_AGENT_DIR |
| T16 | --session-dir 每用户独立 | ✅ |
