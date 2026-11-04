# 会话历史与对话侧完善 · archive（2026-10-12 十步走完归档，子代理施工+子代理隔离审查）

## 交付
1. **会话历史回显**：网关 `GET /session/messages`（switch_session→RPC get_messages→全程持 per-user 锁）+ main.py 转发 + ChatView 历史拉取渲染（convertHistoryMessages 按 rpc.md 真实形态转换：assistant blocks=text/thinking/toolCall(arguments)、toolResult 独立消息按 toolCallId 回填、未知块跳过）；>500 条保最近 200
2. **串显修复**：切换会话清屏（streaming 双防护：流式中不清、历史迟到不覆盖在途轮——施工子代理发现并防住"新会话首轮 session_info 回填触发 409 白屏"回归）
3. **新建会话修复**：onNewSession 真调 POST /session 开新会话（审查 P0-1：原设计只清前端 id，消息仍落 pi 当前活跃会话）+ 网关 POST /session inflight 409
4. **EvidenceDrawer 对话侧接线（选项 A）**：submit_conclusion 过闸（tool_result is_error=false）→ 溯源条（行 ID chips/as_of/scope/数字数）→ 抽屉（结论全文+supported_by 逐行+numbers 表）；历史会话也恢复
5. **被拒输入日志**：/identity/resolve 三拒绝点 → logs/identity-rejected.log JSONL（alias 决策数据后路）

## 十步执行记录（本 change 严格子代理制）
Step1-3.5 主会话（四件套，10 Gap 全处置）→ **Step5 施工子代理**（7 任务+自验四项全过+真实 session 转换器验证）→ Step6 主会话复核 → **Step7 隔离审查子代理**（P0×1/P1×2/P2×8）→ Step8 主会话修复（P0+P1+5×P2 修，3×P2 记录）→ Step9 实测（六项验收+门禁 9/9+tabbit UI 走查）→ Step10 归档

## 审查关键发现（勿重复推导）
- **session_id=null 不等于开新会话**：网关 /chat 的 null 只"跳过 switch"，消息落 pi 进程当前活跃会话（可能是刚浏览过的旧会话）——"新建会话"必须显式 POST /session
- **submit_conclusion 的展示必须闸口联动**：出口闸拒绝以 tool_result(is_error=true) 返回；被拒 CLAIM 渲染成"溯源"= 把未过闸结论包装成可溯源交付（红线 7 展示语义）——捕获必须在成对 tool_result 且 is_error=false
- **改写活跃会话的端点必须持锁**：switch/get_messages 与 /chat 用同一把 per-user inflightLock 互斥
- **startsWith 防穿越必须带分隔符**（`userDir + sep`）：default 可被 `../defaultx` 前缀撞名绕过
- pi get_messages 只给当前上下文视图（compaction 前历史不返回）——显示"能看到的"即诚实（D3）

## 记录未修（P2）
- 验证器注入消息在历史中以用户气泡出现（直播不显示，历史显示——D3 取舍）
- toolResult 无 id 时同名工具并发可能错配（罕见）
- 新建预建与秒发首条的窄竞态窗口（记录）
- /session/messages 无自动化测试（前端无框架；端到端 tabbit 走查+门禁覆盖）
- 建议：合档后用快照机制补 diff 能力（项目无 git，审查只能 mtime 窗口+符号溯源）

## 流程经验
- 隔离审查连续第二个 change 抓到 P0/P1（线 B×2 P1、本 change P0×1+P1×2）——**审查者实证复现**（"全前端零调用 POST /session" grep 实锤）是关键；设计者自审对"我以为的行为"盲区最重
- 施工子代理价值实证：主动防住设计未预见的回归（409 白屏）+ 按现实修正（Message Types 实读）
- tabbit（Tabbit CLI）UI 级验收链路打通：stdin 传 Playwright→receipt 收结果→localStorage 注入测试用户——后续 UI change 验收的标准手段
