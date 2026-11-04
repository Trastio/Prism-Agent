# phase2-finalize · Step 8 receiving-code-review

> 2026-10-04 · code-review 8 findings（P1×5 + P2×3）

---

## P1（5 个，全修）

| # | finding | 判定 | 处理 |
|---|---|---|---|
| 1 | 并发锁被错误释放 | **接受+已修** | 锁检查移到 try 前 + lockSet 标记 + finally 只删自己的 |
| 2 | extension_error 不终止流 | **接受+已修** | 检查 mapped.type === 'error' 退出 |
| 3 | POST /session 不建新会话+泄露 | **接受+已修** | 改用 new_session RPC 命令 + 固定错误文案 |
| 4 | read 工具无路径限制 | **接受+已修** | 敏感文件正则拦截（.env/auth.json/.ssh/id_rsa/credentials/secret） |
| 5 | 验证器 retry 绕过 | **接受+已修** | 只查最后一条 entry 是否 prism-verified |

## P2（3 个，全修）

| # | finding | 判定 | 处理 |
|---|---|---|---|
| 6 | sentiment_proxy 丢 query | **接受+已修** | 拼接 request.url.query |
| 7 | chat_stream 错误泄露 | **接受+已修** | 固定文案"对话服务暂时不可用" |
| 8 | bash 死代码 | **接受+已删** | P1#4 重写时已删 |

## 汇总
- 8 条全接受 + 全修 ✅
- 0 条拒绝 / 留下一轮
