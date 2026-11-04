# Phase3 · Step8 Receiving Code Review

> 2026-10-06
> 对象：Step7 code-review 报告（1 P0 + 7 P1 + 10 P2）+ Step6 simplify（12 项）

## 已修（本轮）

### P0
- **P0-1 runner.mjs 重复 import**：删 L41-42 重复 import，`node --check` 通过

### P1
- **P1-1 tracker.ts 脱敏被覆盖**：`...data` 移到前面，value/series_key 脱敏在后覆盖
- **P1-2 verdict 路径错**：ChatView 改读 `(e as any).verdict`（事件顶层，非 e.data.verdict）
- **P1-3 series 不传对话**：App.tsx 传 `series` prop 给 ChatView，ChatView sendChat opts 带 `seriesKey: series`
- **P1-4 identity fetch fail-OPEN**：fetch 失败/非200 时设 identityWarning（fail-closed，非降级放行）
- **P1-6 retry 不流给客户端**：网关循环改判定——settled 且 verdict.pass=true 或 exhausted 才 break，fail 有 retry 继续读

### P2
- **P2-1 sales_trim 列名**：`WHERE series_key=?` → `WHERE series=?`
- **P2-2 config_snapshots 列名**：`WHERE series_key=?` → `WHERE series_id=?`（参数用 series_id）

### Step6 simplify
- V1 getUserId 死导入删除
- V3 done case 死代码删除
- G1 default 双 return 删第二行
- M1 陈旧注释删（指向不存在的 resolve.ts）
- C1 chat.ts 内联 ui-response 改调 respondUi

验证：smoke:guard 21 passed + 真实分析 verdict=pass 流到前端 + /identity/resolve 银河E5 sales_trim 286 行/config hit=True

## 留下一轮（不阻塞 archive，记入待办）

### P1（生产期前必修）
- **P1-5 并发 double writeHead**：同 userId 并发请求 ERR_HTTP_HEADERS_SENT。开发期单用户不触发。修法：锁检查移到 writeHead 之前
- **P1-7 last-verdict.json 多用户覆盖**：固定单路径，多用户并发互相覆盖。修法：按 sessionId 分目录，或 verdict 走 RPC 事件流

### P2（数据准确性）
- **P2-3 verifyCompletion 异常 attemptMap 泄漏**：catch 块里手动 delete attemptMap[sessionId]
- **P2-4 readLastTrajectory 忽略 userId**：循环加 sessionId 过滤
- **P2-5 setActiveTools 异常 fail-OPEN**：catch 里 console.error + fail-closed
- **P2-7 LIKE 未转义**：ESCAPE + 转义 %/_
- **P2-8 verifyCompletion 传 undefined identity_coverage**：before_agent_start 存 coverage 到 session entry，agent_settled 取出
- **P2-9 tool_result as_of 提取**：兼容 content 数组形态
- **P2-10 早返回不写 verdict.json**：compact/resume 二次触发时清空或重写

### Step6 simplify 中/低优先级
- M2 trajectory 读取三处抽函数
- M3 series_id 反查抽函数
- S1 EVIDENCE_RE 与 REF_RE 统一
- S2 new RegExp 包装去掉
- G2 verdict.json 读取抽函数
- M5 跨语言正则重复加同步注释

## 判断依据
- P0/P1-1~4/P1-6/P2-1~2 已修：影响红线#7 + 评估可跑 + verdict 可见 + 脱敏生效，必须本轮修
- P1-5/P1-7 并发：开发期单用户不触发，生产期前必修（记入上线前 gate）
- P2-3~10：数据准确性/健壮性，不阻塞当前验证，下一轮统一改
- simplify 中低：纯质量，不阻塞
