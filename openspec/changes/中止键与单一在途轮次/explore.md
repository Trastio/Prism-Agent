# Explore · 中止键与单一在途轮次

日期：2026-10-12 · 触发：用户发现 agent 未答完时能发下一条；拍板"发送键变中止键 + 生成中锁发送，唯一打断=点中止"。

## 现状诊断（全部代码实证）

**设计上已有两层时序锁**：
- 前端 ChatView.tsx:101 `if (!text || streaming) return;` + :315 `<button disabled={streaming}>`；UI-6 视图保活（App.tsx:94 display:none 切换不卸载，streaming 状态不丢）
- 后端 pi_gateway.mjs:449-456 per-user `inflightLocks`：在途时第二个 /chat 立即回 `{"type":"error","message":"上一个请求仍在进行中"}` 并关流

**用户实际能再发的根因（推断+证据）**：chat.ts sendChat 无 AbortController、无"settled 见证"跟踪——NDJSON 流异常中断时 `finally setStreaming(false)` 解锁，但后端真轮次仍在跑（inflightLocks 未清）→ 前端解锁可发、后端拒收且**首答流已断永不可达**=前后端状态脱钩。E2 keep-alive 竞态史（已修）证明这类中断真实存在。

**中止能力完全缺失但地基全在**：
- pi_gateway.mjs:282-287 `RpcClient.abort()` 已完整：本地 eventQueue 推 aborted 唤醒 /chat 读循环（P1#4 教训的修复）+ `send('abort')` 发 RPC 命令到 **pi 本体**（abort 必须到 pi 进程——extension 回灌自驱动，断网关流停不住，2026-10-08 实证）
- 超时清理（send() 内 PRISM_TURN_TIMEOUT=300s）已在用同一 abort RPC 命令，行为已知
- /chat 读循环 break 条件已含 `event.type === 'aborted'`（L534）；finally 清锁（L546）
- mapEvent L102-103 现把 aborted 映射成 `{type:'error', message:'aborted'}`——语义不当（中止非错误）

## 四层坐标

| 层 | 文件:位置 | 现状 |
|---|---|---|
| 前端 UI | ChatView.tsx:99-229 handleSend / :310-315 composer | streaming 锁有；无中止；无 aborted 分支 |
| 前端网络 | chat.ts sendChat | 裸 fetch 无 signal；不跟踪 settled；无 abortChat |
| API 透传 | main.py:396-426 /chat/stream | httpx 透传；无 /chat/abort |
| 网关 | pi_gateway.mjs:427-549 /chat；:282 abort()；:401 createServer 路由表 | abort() 就绪未暴露；无 /abort 路由；/chat finally 不清 eventQueue 残留（迟到事件可能泄入下一轮） |
| 图标 | Icons.tsx sprite | 有 arrow-up，**无 stop 方块** |

## 中止后语义（红线对齐，无需改 extension/pi）

- abort 只断当前 turn；session 可继续；已发生的工具调用 entries 留存（数值真值下轮可用，无害）
- 中止轮无 verdict = 未交付结论（用户主动放弃，不违反红线#1）
- inflightLocks 由 /chat finally 清（abort 唤醒循环→break→finally）

## 风险预判

- R1：回灌自驱动轮期间 abort 的效果——RPC abort 中断当前 run；若 extension 已排队下一轮回灌可能继续。E2E 实测"中止后立发新消息是否正常"即检验；fallback=abort 后 1s 复发或 dispose+respawn 该 user rpc
- R2：mapEvent 契约变化（aborted 一等事件）波及 eval runner.mjs（读同一事件流）——需核对其对未知 type 的处理
- R3：Icons 需补 ico-stop
