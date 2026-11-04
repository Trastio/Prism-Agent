# phase2-fix · Step 8 receiving-code-review

> 对 13 findings 逐条判定
> 2026-10-04

---

## P0（3 个，全修）

| # | finding | 判定 | 处理 |
|---|---|---|---|
| 1 | 事件重复消费（入队+喂 waiter） | **接受+已修** | waiter 只通知不从 msg 取，统一从队列 shift |
| 2 | POST /session 缺失 | **接受+已修** | 加 POST /session 路由（get_state 拿 sessionId） |
| 3 | stdin 背压未处理 | **接受+已修** | writeSafe 返回 Promise，write 返回 false 时等 drain |

---

## P1（8 个）

| # | finding | 判定 | 处理 |
|---|---|---|---|
| 4 | abort 后事件循环不退出 | **接受** | 待修：abort 后推 {type:'aborted'} 到队列 |
| 5 | 同用户并发 prompt 串台 | **接受** | 待修：同 userId 串行锁 |
| 6 | 超时不清理 stdin | **接受** | 待修：超时后发 abort |
| 7 | extension_ui 自动回填无 gate | **接受** | 待修：env gate PRISM_AUTO_APPROVE_UI |
| 8 | tool_call 裸 SQL 正则可绕过 | **接受** | 待修：白名单 bash 命令 |
| 9 | read_meta 表名拼接 | **接受** | 潜在，待修：白名单 |
| 10 | sentiment_proxy SSRF | **接受** | 待修：path 白名单 |
| 11 | 错误泄露内部信息 | **接受** | 待修：固定文案 |

---

## P2（2 个）

| # | finding | 判定 | 处理 |
|---|---|---|---|
| 12 | UTF-8 多字节截断 | **接受** | 待修：StringDecoder |
| 13 | Windows SIGTERM 无效 | **接受** | 待修：taskkill /F |

---

## 汇总

- **P0 3 条**：全修 ✅
- **P1 8 条**：接受，留下一轮修（非阻塞核心功能）
- **P2 2 条**：接受，留下一轮

## 备注

- pi RPC 事件双发（tool_execution_start ×2 等）是 pi 的行为，非 bug——前端去重
- P1 的 8 条影响健壮性但不阻塞核心对话链路，留 phase2-fix-v2
