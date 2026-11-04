# 阶段2·收尾（前端联调 + session 验证 + P1 修复）· Step 1 explore

> 2026-10-04
> 范围：三件事合并——前端浏览器联调 / session 上下文持久验证 / P1×8 修复
> 上游：phase2-fix（P0 修完，P1 留下一轮）+ 前端代码（ChatView/chat.ts，未在浏览器验证）

---

## 一、待做事项

### A. 前端 dev 联调（验证浏览器里能真实对话）
- vite dev server + FastAPI + pi_gateway 三方启动
- ChatView composer → fetch /chat/stream → 浏览器流式渲染
- 工具活动面板实时显示
- 状态栏联动
- 可能遇到：vite proxy / React 渲染 / NDJSON 解析 / CDP 自动化

### B. session 上下文持久验证（RPC 模式下连续对话）
- 第一轮对话 → 拿 session_id
- 第二轮同 session_id（pi_gateway 复用 RPC 子进程）→ agent 是否记得第一轮
- 若不记得：查 pi RPC 怎么传 --session 参数 + pi_gateway 怎么复用
- pi_gateway 当前 getOrCreateRpc 没传 --session，每用户一进程天然复用，但 pi 可能每次 prompt 新建 session

### C. P1×8 修复
| # | 问题 | 修法 |
|---|---|---|
| 4 | abort 后事件循环不退 | abort 推 {type:'aborted'} 到 eventQueue + while 检查 |
| 5 | 同用户并发串台 | 同 userId 串行锁（in-flight promise） |
| 6 | 超时不清理 stdin | 超时后发 abort + 标记迟到响应丢弃 |
| 7 | auto-approve 无 gate | env PRISM_AUTO_APPROVE_UI 默认关 |
| 8 | 裸 SQL 正则绕过 | 白名单 bash 命令 + 专用受限工具 |
| 9 | read_meta 表名拼接 | 白名单校验 |
| 10 | sentiment_proxy SSRF | path 白名单 |
| 11 | 错误泄露内部信息 | 固定文案 + 日志记详情 |

---

## 二、依赖关系

```
A 前端联调（验证链路）→ 发现问题 → 修
B session 验证（RPC 续接）→ 若失败 → 修 pi_gateway --session
C P1 修复（独立，可并行）
```

A 和 B 都需要 pi_gateway + FastAPI 在跑，可并行验证。C 独立修代码。

---

## 三、风险

1. **vite proxy SSE 透传**：vite 可能缓冲 NDJSON，需 proxy 配置
2. **RPC session 续接**：pi --mode rpc 默认每次新建 session？需查 --session 参数
3. **浏览器 NDJSON 解析**：fetch ReadableStream 在浏览器里跟 Node 行为可能不同
4. **P1#5 并发锁**：同 userId 串行可能让多标签页用户卡住（可接受，单用户串行）

---

## 四、explore 结论

三件事合并一个 change，A+B 验证 + C 修复。A/B 验证发现问题后跟 C 一起修。

**下一步 Step 2 propose**：proposal + design + tasks。
