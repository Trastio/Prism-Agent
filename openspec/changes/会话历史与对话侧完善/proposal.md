# 会话历史与对话侧完善 · proposal

## WHY
会话历史三件套缺一（切旧会话看不到之前聊的内容）+ 两个显示层 bug（串显、新建会话续旧会话）；同时收编两个已拍板小活（EvidenceDrawer 对话侧接线=产品化"可溯源"卖点、被拒输入日志=alias 决策的数据后路）。合并一个 change 一次走完严格十步。

## WHAT

### A 会话历史回显（主体）
1. **网关** `GET /session/messages?user_id&session_id`：switch_session(目标) → RPC get_messages → 同步 rpc.sessionId → 返回 `{session_id, messages}`；目标文件不存在 → 404；switch 失败 → 502 固定文案
2. **main.py** 转发同款（~8 行）
3. **ChatView**：`sessionIdProp` 变化且非空 → 清 msgs → 拉取 → AgentMessage[] 转本地 Msg[]（user→text；assistant→text/thinking 合并；toolCall/toolResult 形态以 rpc.md Message Types 实测为准，转换失败的 block 静默跳过不整轮失败）；加载态显示；拉取失败 → 空屏可继续聊（续聊不受影响）
4. **串显修复**：切换即清屏（A3 内含）
5. **新建会话修复**：Sidebar"新建会话"→ App `setSelectedSessionId(undefined)`（与"返回对话视图"区分——最小改法施工时定）

### B EvidenceDrawer 对话侧接线（选项 A）
1. ChatView 捕获 `tool_call(name=submit_conclusion)` 的 args → 存 lastClaim（重试链天然取最后=过闸那次）
2. 最后一条 agent 消息下方渲染**溯源条**：supported_by chips（≤3 个 + "N 项"溢出）+ as_of + scope + numbers 计数
3. 点击 → App.openEvidence 复用现有 EvidenceDrawer 管线；EvidenceDrawer 扩展渲染：conclusion_text（name）、supported_by 全列表（src，逐行）、numbers 表（value/source/derived_from）、data_gaps_declared
4. 无 submit 的普通对话不显示溯源条

### C 被拒输入日志
main.py /identity/resolve 两个拒绝返回点（needs_online_verify ×2、ambiguous）append JSONL 到 `logs/identity-rejected.log`；写失败静默（日志是 best-effort）

## 决策记录
| # | 决策 | 理由 |
|---|---|---|
| D1 | 历史拉取走 RPC get_messages（switch 后取），非直接读 session 文件 | 网关不引 pi 内部解析逻辑；switch 与 /chat 现有路径一致；文件格式解析归 pi 管 |
| D2 | EvidenceDrawer 数据源=前端捕获 submit_conclusion args，不加后端端点 | tool_call 事件已到前端，数据即完整 CLAIM；零后端改动零验证层触碰（红线区不动） |
| D3 | 历史渲染"尽力转换"：未知 block 跳过 | 历史 schema 随 pi 版本变，宁缺勿崩 |
| D4 | 日志只记 series_key+reason 不记 user_id | 端点本无 user 参数；alias 决策只需输入词分布 |

## 影响范围
prism-web：ChatView/App/Sidebar/EvidenceDrawer；prism-api：pi_gateway.mjs/main.py。**不碰**：extension（红线区）、verify/*、工具层、子服务。

## 验收
1. 侧栏点旧会话 → 屏幕显示该会话完整历史（含 thinking 折叠/工具活动），无串显；续聊上下文正常
2. 新建会话 → 空白新会话，不再续旧
3. 跑一轮 E5 分析（触发 submit_conclusion）→ 回复下方出现溯源条（行 ID chips/as_of/scope）→ 点击 → 抽屉展开显示结论全文+supported_by 全列表+numbers
4. /identity/resolve?series_key=胡编车系 → logs/identity-rejected.log 出现一行
5. 静态：根 tsc 零新增 + web tsc/build 通过 + smoke:all 全过（98+ 基线）+ E1-E9 门禁不回归（前端改动为主，跑一轮确认）
6. UI 级验证：headless Chrome 或用户走查

## 不做
- 历史消息的分页/懒加载（单会话量级小）
- 会话内搜索（侧栏搜索框是死的——留待需要时）
- 抽屉内"点行 ID 跳库原文"（需要新端点，留下一轮）
- parallel 分支历史的树形渲染（get_messages 只给主线）
