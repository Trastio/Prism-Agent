# Proposal · 阶段2 收尾

> 2026-10-04 · 三件事：前端联调 + session 验证 + P1 修复

---

## WHAT

### A. 前端 dev 联调
- 启动 vite + FastAPI + pi_gateway 三方
- 浏览器 ChatView 真实对话验证
- 修联调发现的问题

### B. session 上下文持久
- 验证 RPC 模式连续两轮对话
- 若 pi_gateway 没传 --session → 加 --session 参数复用会话文件

### C. P1×8 修复
| # | 修法 |
|---|---|
| 4 abort 循环不退 | eventQueue 推 aborted + while 检查 |
| 5 并发串台 | 同 userId in-flight 锁 |
| 6 超时不清理 | 超时发 abort + 丢弃迟到响应 |
| 7 auto-approve gate | env PRISM_AUTO_APPROVE_UI |
| 8 SQL 正则 | 白名单 bash + 受限工具 |
| 9 read_meta | 表名白名单 |
| 10 SSRF | path 白名单 |
| 11 错误泄露 | 固定文案 |

---

## 验收
1. 浏览器输入"用 query_reviews 查银河E5舒适"→ 流式响应 + 工具活动 + 真实数据
2. 连续两轮对话 agent 记得第一轮
3. P1×8 全修
