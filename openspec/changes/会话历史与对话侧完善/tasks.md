# 会话历史与对话侧完善 · tasks

## Step1-3.5（设计方=主会话）
- [x] T0 explore（三件套现状/get_messages 形态/submit_conclusion args/两个显示 bug）→ explore.md
- [x] T1 proposal（A/B/C 三件 + D1-D4 决策）→ proposal.md
- [x] T2 tasks（本文档）
- [x] T3 self-check（3.5 收敛）→ self-check.md

## Step5 施工（subagent-driven：委派施工子代理，任务单如下）
- [x] T-A1 网关 GET /session/messages（switch→get_messages→sessionId 同步；404/502 语义）
- [x] T-A2 main.py GET /session/messages 转发
- [x] T-A3 ChatView：sessionIdProp 变化 → 清屏+拉取+AgentMessage→Msg 转换渲染（D3 尽力转换）+加载态+失败兜底
- [x] T-A4 新建会话修复（Sidebar"新建会话"≠"返回对话"；App 侧 setSelectedSessionId(undefined)）
- [x] T-B1 ChatView 捕获 submit_conclusion args → lastClaim → 溯源条渲染（chips≤3+溢出/as_of/scope）
- [x] T-B2 EvidenceDrawer 扩展渲染（conclusion_text/supported_by 全列表/numbers 表/data_gaps）+ 接 App.openEvidence
- [x] T-C1 main.py identity-rejected.log（两个拒绝点 append JSONL）
- [x] T-V1 子代理自验：根 tsc 零新增 + web tsc/build + node --check 网关 + py_compile

## Step6-10
- [x] T5 simplify（子代理施工时附带 + 主会话复核）
- [x] T6 requesting-code-review：**隔离子代理审查轮**（不带设计/施工结论）
- [x] T7 receiving-code-review：P0 全修/P1 判断/P2 记录
- [x] T8 verification：服务重启 → 验收 1-6 实测（含 E1-E9 不回归）→ verification.md
- [x] T9 archive：archive.md + 记忆更新
