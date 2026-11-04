# phase2-integration · Step 8 receiving-code-review

> 对 18 findings 逐条判定（接受/拒绝/留下一轮）
> 日期：2026-10-04

---

## P0

| # | finding | 判定 | 处理 |
|---|---|---|---|
| 1 | user_id 路径穿越 | **接受** | phase2-fix T1（白名单校验） |

---

## P1

| # | finding | 判定 | 处理 |
|---|---|---|---|
| 2 | SessionManager.open 误用 | **接受** | phase2-fix T2（open 传 path） |
| 3 | 同 session 并发竞态 | **接受** | phase2-fix T2（每请求新建 session 实例） |
| 4 | 订阅不取消 → 泄漏 | **接受** | phase2-fix T2（session 用完即弃） |
| 5 | 客户端中断不感知 | **接受** | phase2-fix T2.5（req.on close + abort） |
| 6 | sessionPool 无淘汰 → OOM | **接受** | phase2-fix T2（删 sessionPool） |
| 7 | message 缺失挂死 | **接受** | phase2-fix T3.1（类型校验 + try） |
| 8 | 前端 fetch 失败永久卡 | **接受** | phase2-fix T4.1/T4.2（try/catch + finally） |

---

## P2

| # | finding | 判定 | 理由 |
|---|---|---|---|
| 9 | 错误事件泄露 stack | **接受** | phase2-fix T4.3（安全相关，不返 stack） |
| 10 | initialMessage 时序竞态 | **留下一轮** | 非阻塞，影响小（仅 Kanban→Chat 切换时） |
| 11 | 工具 fetch 无超时 | **接受** | phase2-fix T3.2（AbortController + res.ok） |
| 12 | readBody 无上限 | **接受** | phase2-fix T3.3（Content-Length 校验） |
| 13 | POST /session JSON.parse 未保护 | **接受** | phase2-fix T3.4（try/catch） |
| 14 | sentiment_proxy SSRF | **接受** | phase2-fix T3.5（path 校验禁 ..） |
| 15 | FastAPI 转发无错误处理 | **接受** | phase2-fix T4.4（try/except） |
| 16 | pi_server CORS 全开 | **接受** | phase2-fix T4.5（限本机） |
| 17 | KanbanView 硬编码 | **接受** | phase2-fix T5（as_of + 刷新） |
| 18 | 前端流式无 AbortController | **留下一轮** | 非阻塞，依赖 #5 后端 abort 先做 |

---

## 汇总

- **接受 16 条** → 进 phase2-fix 修
- **留下一轮 2 条**（#10 / #18）→ 非阻塞，下个 change
- **拒绝 0 条**

## 结论

phase2-integration 的核心链路（对话/工具/数据回流/session 列表/舆情反代）功能达成，但有 16 个需修缺陷（1 P0 安全 + 7 P1 可用性 + 8 P2 健壮性）。这些缺陷归入 phase2-fix 统一修复。phase2-integration 在 phase2-fix 完成后一起 archive。
