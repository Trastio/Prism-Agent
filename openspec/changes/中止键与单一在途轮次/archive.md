# Archive · 中止键与单一在途轮次（2026-10-12 归档）

## 一句话

对话交互从"能发不能停"升级为"单一在途轮次 + 用户主权中止"：发送键在生成中变中止方块，点击经 api 透传到网关 `RpcClient.abort()`（发 RPC abort 到 pi 本体），流收 `aborted` 一等事件收尾；配套断线即中止根治前后端状态脱钩；四连修堵死中止余波事件泄入新轮的竞态。

## 变更清单

- `prism-api/pi_gateway.mjs`：+/abort 路由（幂等+尾随排干）；mapEvent aborted 一等化；/chat finally 排干；S7-a 排干遇锁即停；S7-b 拿锁清残渣；S7-c 零内容 settled 残渣防线（仅 thinking/text 算内容）；**S7-d 中止余波等待**（rpc.lastAbortAt，覆盖超时中止路径）；rpc 声明提升
- `prism-api/main.py`：+/chat/abort 透传
- `prism-web/src/lib/chat.ts`：activeController/cancelActiveStream/abortChat；sawSettled 断线即中止；AbortError→合成 aborted
- `prism-web/src/components/ChatView.tsx`：按钮双态（stop/arrow-up）+handleAbort（2.5s 本地断流兜底）+streamingRef+case 'aborted'+initialMessage 挂起
- `prism-web/src/components/Icons.tsx`：+ico-stop
- `prism-web/vite.config.ts`：+/chat/abort 代理
- `tests/abort_api.test.ts`：fast 组（进 smoke）+ e2e 组（PRISM_E2E_ABORT=1 门控）

## 关键持久事实（勿重复推导）

- **pi 在 abort 后 ~1s 仍吐旧轮事件**（tool_result/agent_settled 尾随）——新 prompt 立即发出会与之交织，两种实测泄漏形态：尾随 settled 空转结束新流 / 尾随 tool 事件点亮内容防线后 settled break。治本=abort 后 2.5s 余波等待（S7-d），防线=零内容 settled 跳过（S7-c）
- 网关监听 **0.0.0.0:9200**（非 127.0.0.1）——杀进程 grep 要用 `:9200`，否则空 PID 假重启
- 中止轮语义：无 verdict=未交付结论（红线安全）；session 可续用；中止轮已查的工具数据留在会话，下一问 agent 可接着交付（race5 实证优雅续接）
- 中止链路必须发 RPC abort 到 pi 本体（extension 回灌自驱动，断网关流停不住）

## 验收

smoke:all 84/84 · tsc 基线持平 · UI 三断言过（tabbit 实测图标切换/已中止状态/恢复）· 竞态三轮递进终测（race5：abort 后 50ms 新问 42.7s 完整获答）

## 留下一轮

- T3.3 UI 手测走查留用户亲测（tabbit 已覆盖核心三项）
- heredoc 反斜杠折叠坑三犯（本轮 `\\n`/`\\1` 两次翻车）——**教训升级：含反斜杠的代码/正则编辑一律 Edit 工具，不走 bash heredoc**
- 多标签同 user_id 并发属已知边界（单在途轮语义下后发者会触发断线即中止对齐，可接受）


## 补充归档：隔离上下文审查轮（2026-10-12 第二轮）

- **隔离审查方法跑通**：代码内嵌提示（~40KB）→ 隔离子代理离线审 → **3 P0/5 P1/8 P2，自审漏掉的 P0 全被抓住**（前端定时器误杀/finally 补 abort 误杀/残渣判据挂死）——"需要隔离上下文审查"的价值实证
- 16 条全部处置（修复 13 / 记录 3），修复过程自查出 abortPending 标志残留新 bug 并即修
- 关键新不变量：**abortPending 消费即清**（循环消费 aborted 事件/内部清理 abort 后清——防用户意图残留杀下一轮）；**读循环双保险**（20s 无事件兜底 + !event 防崩）
- 流程结论：审查类子代理无本地工具时，"代码内嵌"是可行的独立审查路径，此后 change 的 Step7 可复用
