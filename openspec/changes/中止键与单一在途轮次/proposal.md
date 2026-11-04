# Proposal · 中止键与单一在途轮次

## WHY

现状"能发不能停"不对称：两层时序锁存在但会脱钩（流异常中断→前端解锁、后端锁死→首答永失+新消息被拒），且用户等不及无任何打断手段。用户拍板目标交互：**发送后箭头变中止方块；生成中禁止发送（可打字）；唯一打断=点中止**（单一在-flight turn + 用户主权中止，ChatGPT/Claude.ai 同款语义；不做消息排队——第二问常依赖第一问答案）。

## WHAT

1. **前端双态按钮**：streaming 时 ico-arrow-up → ico-stop（新增 sprite），click 提交 → handleAbort；输入框不禁。
2. **中止链路打通**：`abortChat()`(chat.ts) → POST /chat/abort(main.py 透传) → POST /abort(gateway) → `RpcClient.abort()`（已有：唤醒读循环 + 发 RPC abort 到 pi 本体）→ 流收 aborted 事件 → 循环 break → finally 清锁。
3. **断线即中止（脱钩根治）**：sendChat 跟踪 sawSettled；流结束/异常而未见 settled 且非用户主动中止 → fire-and-forget abortChat()，前后端状态强制对齐。
4. **契约清理**：mapEvent 将 aborted 映射为一等 `{type:'aborted'}`（不再是 error）；ChatEvent union + ChatView 分支（状态"已中止生成"，半截答案保留）；/chat finally drain eventQueue（防迟到事件泄入下一轮）。

## 决策（D1-D6）

- **D1 交互**：按钮双态；输入不禁；suggest-pills 仅空会话显示不受影响；initialMessage（看板预填）streaming 时挂起等待，流结束再发（防丢消息）。
- **D2 abort 幂等**：/abort 无在途锁/无 rpc → `{ok:true, aborted:false}`；有则 abort()。
- **D3 本地兜底**：handleAbort 先调 abortChat()，2.5s 后仍 streaming 则 AbortController 本地断流（防端点不可达时卡死）；sendChat 挂 module-level activeController。
- **D4 中止语义**：不写库、无 verdict、session 可续用；extension/pi 零改动。
- **D5 drain 时机**：/chat finally 中 `rpc.eventQueue.length = 0`（break 后无本请求 waiter；同 user 锁防并发，安全）。
- **D6 fallback**：E2E 若发现回灌轮在中止后仍继续 → abort 后 1s 复发一次；仍不行 → dispose+respawn（记入 tasks 可选项，实测后定）。

## 影响范围

- prism-web：ChatView.tsx / chat.ts / Icons.tsx（+ico-stop）
- prism-api：main.py（+/chat/abort）
- pi_gateway.mjs（+/abort 路由、mapEvent aborted 一等化、/chat finally drain）
- 新增 tests/abort_api.test.ts（活服务）
- eval/runner.mjs：核对未知事件 type 的处理（预期忽略，若抛错则补 ignore）

## 验收

1. E2E（API 层）：发长问题 → 3s 后 /chat/abort → 流在数秒内收 aborted 并结束；**锁已清**（立发第二问不再"上一个请求仍在进行中"且正常获答）；session 列表正常。
2. 幂等：无在途时 /chat/abort 返回 ok 不报错。
3. UI：streaming 时按钮为方块且 disabled 提交逻辑不触发发送；点方块 → 状态"已中止生成"；中止后立即可再发。
4. 断线即中止：模拟流中断（abort 本地 fetch）后发新消息不被拒（后端已被对齐中止）。
5. smoke:all 全绿（mapEvent 契约变化不破既有测试）；tsc 零新增。

## 不做

- 不做消息排队/多轮并发
- 不改 extension / pi 运行时
- 不做"中止后部分答案打标未验证"的 UI 标注（中止轮无 verdict 已是语义，气泡保持原样）
