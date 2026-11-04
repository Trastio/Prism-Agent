# 出口闸-验证层根治 · Step1 explore

> 日期：2026-10-07 · 方案依据：`设计图总览/Prism-Agent-出口闸-验证层根治方案.md` **v1.5**
> 任务：核验方案 §十 Step1 四件事 + v1.4 相对路径提示 + 两个施工可行性问题（execute 读台账 / attemptMap 耦合）

## 一、结论摘要

**可行性 7/7 绿灯，0 个阻塞项**；发现 **1 个必须在校验层解决的设计耦合**（⑦ attemptMap）；运行时基线好于预期（四服务全在跑、网关进程已是新代码）。

## 二、逐项核验

### ① tool_execution_end 事件带 result 字段 ✅

`json.md:107`：`tool_execution_end` fields = `toolCallId, toolName, result, isError`。
→ 出口闸拒绝文本作为 `result` 流向网关（mapEvent 已映射 tool_result）与前端；模型同轮修正循环 = pi 原生工具循环（工具结果 → 下一次模型调用），无需额外机制。方案 §3.3 成立。

### ② appendCustomMessageEntry：文档缺位但实测有效 ✅（保底路径沿用）

官方 extensions.md:79-80 只列 `sendUserMessage()` / `sendMessage()` / `appendEntry()`，**无 appendCustomMessageEntry 条目**；但现行代码 `index.ts:1045` 在用且实测有效（10-04 以来所有回灌轮均由它触发，trajectories 可证）。
→ 保底回灌沿用现行 API 不动（D3 定案），不引入文档未覆盖的新用法。

### ③ 网关 mapEvent 传 realSessionId：改动点共 3 处 ✅

- `pi_gateway.mjs:449-450`：`get_state` 已返回 `realSessionId`（现成，无需改）
- `pi_gateway.mjs:463`：`mapEvent(event, userId)` 调用处 → 加传 realSessionId
- `pi_gateway.mjs:75`：`event.sessionId || userId` → 优先用传入 realSessionId（json.md:45 已证 agent_settled 无 sessionId 字段，现行取值恒 undefined）

### ④ submit_conclusion 工具描述写法 ✅

现行描述范式（`index.ts:131-169`：一句功能 + expected + 口径提示）。防漏调双保险已在方案：SYSTEM.md 教协议（M5）+ agent_settled 保底兜底（M2）。注册时须同步三处：`KNOWN_BUSINESS_TOOLS`、`TOOL_CATEGORIES.business`（ALLOWED_TOOLS 派生自它）、`decideTier` 的 hasLib 显式追加（`index.ts:51`）。

### ⑤ sentiment_events 相对路径防双前缀 ✅

`index.ts:214`：execute 拼 `${SENTIMENT_BASE}/api/dashboard${path}` → 工具模板必须填 **router 相对路径** `/vehicles/{vehicle_id}/events`（dashboard.py:1399 的路由定义形式）。若填完整路径会产生 `/api/dashboard/api/dashboard/...` 双前缀。

### ⑥ execute ctx 可读 session entries（台账读取可行性）✅【关键绿灯】

- `types.d.ts:492`：execute 签名 `(toolCallId, params, signal, onUpdate, ctx: ExtensionToolContext)`
- `types.d.ts:269`：`ExtensionToolContext extends ExtensionContext`
- `types.d.ts:223`：`ExtensionContext.sessionManager: ReadonlySessionManager`
- `session-manager.d.ts:178`：`ReadonlySessionManager = Pick<SessionManager, "getCwd"|"getSessionDir"|"getSessionId"|"getSessionFile"|"getLeafId"|"getLeafEntry"|"getEntry"|"getLabel"|"getBranch"|"buildContextEntries"|"buildSessionProjection"|"getHeader"|"getEntries"|"getTree"|"getSessionName">`

→ **submit_conclusion 的 execute 里可直接 `ctx.sessionManager.getEntries()` 读台账 entries（prism-numeric-truth / prism-name-truth / prism-identity-coverage）、`getSessionId()` 取会话标识；写入用闭包 `pi.appendEntry`（agent_settled 现行同款）。无需进程内存态台账，N9 持久性可达成。**
（另：`ExtensionToolContext.executeTool`（types.d.ts:280）可调其他工具——v1 不用，记录备查。）

### ⑦ 【新发现·design 必解】verifyCompletion 的 attemptMap 副作用与出口闸耦合 ⚠️

- `completion.ts:164-165`：verifyCompletion 每次调用 `attemptMap[sessionId]++`
- `completion.ts:193`：`can_continue = !pass && attempt < 2`
- **污染链**：一轮内模型提交 1-3 次（拒了重提），每次 execute 调 verifyCompletion 都消耗 attempt 预算 → agent_settled 保底再调时 attempt 已 ≥2 → `can_continue=false` → 保底误判 exhausted、不回灌 → **漏提交场景失守**
- 方案约束"不改 verifyCompletion 四件套内部逻辑"（§七.1）与解法兼容：**提取纯函数 `verifyClaimChecks(claim, identity_coverage) → {pass, failures}`**（四件套本体，零逻辑变更）；verifyCompletion 保持原签名行为（= 纯函数 + attemptMap 计数）；submit_conclusion 只调纯函数。单测不受影响。
- 备选（不推荐）：submit 调后重置 attemptMap——时序脆弱，多进程不共享。

## 三、运行时基线（C0 现状，netstat + /health 实测）

| 服务 | 端口 | 状态 |
|---|---|---|
| 舆情 Board | 8000 | LISTENING ✅ |
| Atuohome | 8001 | LISTENING ✅（502×105 主因已消除，线 C 可拿基线） |
| FastAPI | 8002 | LISTENING ✅ |
| pi_gateway | 9200 | LISTENING ✅ · `startedAt 10:24:13Z > fileMtime 10:22:57Z` → **needsRestart=False**（网关进程为代码变更后启动，EXCLUDE_TOOLS 已生效）· pool=0 |
| 前端 dev | 5173 | LISTENING ✅ |

→ C0"上游服务启动"与"旧进程重启验证"**当前均已就位**；施工期只需在验收前复查一次（服务可能中途被关）。

## 四、评估落点（M4）

- `eval/runner.mjs`：TASKS 16 题内联 + dynamic-tasks.json 动态合并 + **已读 trajectories.jsonl 的 verdict 字段**（T-9.1 Gap5）→ E1-E9 只需：①新 task 集 ②断言扩展（settled 次数 / bash 调用数 / submission 字段）
- `eval/ci.sh`：已有 veto 零 + 通过率 ≥70% 骨架 → 挂 E1-E9 门槛
- `index.ts:583-616` appendTrajectory：需增 **submission 字段**（提交次数 / 最终 pass / 拒绝原因），供 runner 断言 E2/E3/E9

## 五、影响面（文件级）

| 文件 | 改动 |
|---|---|
| `.pi/extensions/prism-guardrails/index.ts` | submit_conclusion 注册（3 处白名单同步）、数字台账（tool_result hook 扩采+排除规则）、agent_settled 改道+保底①②、verdict/trajectory 字段、线 C 的 C1/C2/C3 |
| `src/verify/completion.ts` | 提取 verifyClaimChecks 纯函数（D7，四件套逻辑零变更） |
| `prism-api/pi_gateway.mjs` | mapEvent 传 realSessionId（3 处） |
| `AGENTS.md` / `SYSTEM.md` / `PRISM_ANALYSIS.md` | 提示词配套（M5） |
| `eval/runner.mjs` / `eval/ci.sh` / 新 task 文件 | E1-E9 + 门禁（M4） |
| `src/verify/*.test.ts` | verifyClaimChecks 单测 + 台账归一化单测（新增用例） |

## 六、留给 propose / 3.5 的决策点

- **D7（新）**：attemptMap 解耦方式 → 建议"提取 verifyClaimChecks 纯函数"（见 ⑦）
- **D8（新）**：E1-E9 存放 → 建议独立 `eval/tasks_gate.json`（不污染 16 题基线，可单独跑 `node eval/runner.mjs --gate`）
- 3.5 必查：tier × 有无提交 × 数字形态 九宫格枚举；台账 entry 读取时序（tool_result hook 先于 submit execute，同轮数据已在 entries）；回灌消息对"提交被拒未修正"场景的文案适配（① 分支新语义）
