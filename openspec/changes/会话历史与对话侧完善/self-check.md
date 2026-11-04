# 会话历史与对话侧完善 · self-check（Step3.5，2026-10-12）

| Gap | 问题 | 处置 |
|---|---|---|
| 1 | get_messages 作用于**当前活跃会话**——若用户 A 的网关客户端 active=会话 X，请求拉会话 Y：switch(Y)→get_messages→保持 Y active。**竞态**：用户此时在旧会话 X 上还有在途对话？ | 在途对话存在 inflightLock（/chat 设）——messages 端点同样检查 `inflightLocks.has(userId)` → 忙时返回 409 固定文案（历史拉取晚几秒无害，不许打断在途流） |
| 2 | AgentMessage 的 content blocks 精确形态（thinking 块名？toolCall 在 assistant content 里还是独立消息？toolResult 形态？）explore 未完全核实 | 施工子代理**必须先读 pi-windows-x64/docs/rpc.md 的 Message Types 段**再写转换器；转换器遵循 D3 尽力转换 + 单测式自验（拿一个真实 session 的 get_messages 响应跑转换） |
| 3 | get_messages 含不含 compaction 前历史/回灌轮（isRetry 气泡在历史里怎么显示）？ | D3 兜底：历史轮不区分 retry（显示为普通 agent 消息）；compaction 前历史 get_messages 不返回（文档语义：get_messages=当前上下文视图），可接受——显示"能看到的"即诚实 |
| 4 | 溯源条数据在 retry 链中被多次 submit 覆盖——最后 args 未必是"过闸"那次（若末次仍 fail 走保底） | 取**最后一次** args 渲染（与保底交付的结论对应）；verdict fail 到最终的情况照显（用户点开看到的是真实提交内容，as_of/scope 都在） |
| 5 | ChatView 是并行会话活跃区（中止键/状态灯近期都改过它）——施工冲突面 | 任务单明示：以盘上最新代码为基线，改前先 Read 目标段落；改动聚焦 useEffect/渲染段，不动 handleSend 流式逻辑与 abort 相关 |
| 6 | /session/messages 的 user_id 校验与会话归属（用户 A 能否拉用户 B 的会话） | 网关端点校验：sessionPath 必须在 SESSIONS_DIR/{userId} 内（startsWith 防 ../，rename 端点同款先例）——跨用户拉取 → 404 |
| 7 | 历史很大时全量渲染卡顿 | 单会话量级实测 50-200 条消息，可接受；>500 条时截断显示前 200+提示（渲染层防御，不做分页） |
| 8 | identity-rejected.log 与 prism.py 日志目录的权限/编码 | append + utf-8 + 失败静默；Windows 路径 join 用 os.path |
| 9 | 新建会话修复的判据：Sidebar"新建会话"按钮与"返回对话"共用 onNavigate('chat')？ | 施工时读最新 Sidebar：若共用，给 Sidebar 加可选 onNewSession 回调（缺省回落 onNavigate）——App 传 setSelectedSessionId(undefined)+setView('chat') |
| 10 | 验收 5 要求 E1-E9 不回归——本 change 不碰 extension/verify，理论零影响 | 仍跑一轮实证（流程要求不因"应该没事"跳过）；批跑窗口与并行会话错开（昨晚教训） |

**结论**：路径全通（get_messages 现成/tool_call args 已到前端/转发先例齐），竞态与越权有先例可抄（Gap1/6），无悬空依赖。可进 Step5 子代理施工。
