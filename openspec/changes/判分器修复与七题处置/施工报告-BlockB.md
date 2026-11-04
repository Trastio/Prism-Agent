# 施工报告 · Block B（multi-12 abort 残留修复，网关域）

> 2026-10-27 Step5 施工子代理。工单=tasks.md Block B（B1~B3）。
> 环境：`pwd=C:\Users\<you>\Desktop\Prism-Agent`，HEAD=`aeded93`，node `v25.2.1`（守卫通过）。

## B1 · 探明修法落点（接口证据链）

### pi RPC 无会话注入命令（主案形态裁决依据）

- `pi-windows-x64/docs/rpc.md` §Commands（L41-855）全命令面：`prompt / steer / follow_up / abort / clear_queue / new_session / get_state / get_messages / set_model / … / switch_session / fork / clone / get_fork_messages / get_entries / get_tree / get_last_assistant_text / set_session_name / get_commands`。
  - 消息注入类仅 `prompt/steer/follow_up`（rpc.md L43-123）：三者都会**触发 agent 轮**（steer/follow_up 还要求在流中排队），无一可"静默追加一条系统注记"。
  - `get_entries` 等全是只读。**结论：pi 会话接口不支持事后注入注记。**
- extension 侧 `pi.appendCustomMessageEntry`（prism-guardrails/index.ts:1674，验证器回灌在用）能追加，但 extension 文件不在本工单允许改动集内。

### 工单认可的第三形态＝"下一次请求附加上下文" → 主案

pi_gateway.mjs 本身就是 per-request 上下文的既有落点：`/chat` 把 series_key/scope/eval_run_id 写进 ctx.json（L514-529 一带，extension before_agent_start 读取）。同理，网关可在**发 prompt 时**给用户消息附注记——这是主案实现形态。

### 关键实锤：eval runner 的 /chat/abort 走幂等分支（决定 flag 必须双分支落位）

- `eval/runner.mjs:513-521`：`streamChat` 读到流 `done` 才返回（runner.mjs:387-408），**t1 完整结束后**才 POST `/chat/abort`。
- `pi_gateway.mjs /abort` 幂等分支：无在途锁 → `{ok:true, aborted:false}`，**不调 RpcClient.abort()**。
- v1.2 报告佐证（eval/reports/eval-2026-10-26T15-23-07-811Z.json，multi-12 条目）：`turnVerdicts:["pass","pass"]`、`settled:true`、`abortedTurn:1`——t1 是完整交付后被"名义中止"的。
- 因此若只在真中止分支落标记，**修复够不到 multi-12**。用户语义统一为"按下中止=取消上一轮"：幂等分支同样落标记（生产点击竞态：流刚结束才送达，同一路径）。

### 前端回显兼容裁决（为何不借 VERIFIER 前缀）

- ChatView 历史投影唯一过滤：user 消息 `startsWith(VERIFIER_NOTICE_PREFIX)` 跳过（ChatView.tsx:111-112，前缀=`[完成验证器`，src/shared/verifier-prefix.ts）。
- **复用该前缀会误触 extension**：`isVerifierRetryTurn` 用同一无闭括号前缀（index.ts:806-808）→ 本轮被判回灌伪轮 → `canRetry=false`（index.ts:1671）破坏出口闸 retry 语义。排除。
- 主案取"注入内容不进前端"路径：live 流从不回显用户消息（ChatView 渲染本地文本）；历史回显在**网关 `/session/messages` 出口剥离注记**（前端零改动、零泄漏，与 D4 前缀过滤契约同向）。

## B2 · 落地实现（生产 9200 与 eval 9201 同代码路径）

改动文件（未 commit，按工单留工作树）：

| 文件 | 改动 |
|---|---|
| `prism-api/abort_note.mjs`（新建，纯函数模块） | `ABORT_NOTE`/`ABORT_NOTE_MARK` 常量 + `withAbortNote(message, flagSessionId, currentSessionId)` + `stripAbortNoteFromMessages(messages)`。外置同 map_event.mjs 先例（pi_gateway import 即 listen，内联不可单测） |
| `prism-api/pi_gateway.mjs` | ① RpcClient 构造器 `pendingAbortNote=null`；② `/chat` 发 prompt 前一次性消费标记，同会话才在消息**尾部**追加注记（跨会话不注记；发送失败 catch 归还标记）；③ `/abort` **两个分支**（真中止+幂等）都落 `pendingAbortNote=rpc.sessionId`；④ `/session/messages` 出口剥离注记 |
| `tests/abort_api.test.ts` | +纯函数单测组（4 用例）+ e2e 门控组注记生效双断言 |

机制一句话：/abort（无论真假中止）记下被中止会话 id → 同会话下一轮 /chat 的 prompt 尾部附 `[Prism 系统注记] 上一轮回答已被用户中止……不应作为有效上下文引用……独立查证作答` → 历史回显剥离。注记文案**不含任何车系名/数字**（multi-12 trap_params.residue 词面防误伤，有专测）。

- 注记附在消息**尾部**而非头部：保护 extension 各处 prompt 匹配（isVerifierRetryTurn/链起点扫描均 startsWith 语义，index.ts:1667/1693）与 shouldAdvancePhase（实为不看 prompt 内容，workflow-gate.ts:41-43，已核）。
- 生产同路径同行为：生产用户点中止（真中止分支）或点击竞态（幂等分支）后，下一问同样不被上一轮未交付内容污染。
- 边界：内部 abort（断连 S8 P1-4 / 20s 无事件 S8 P0-3 / 连续空轮）**不落标记**——那三条路径本就零内容无残留可引用。
- 既有未提交变更保留：pi_gateway.mjs 工作树原有的"P0 链路焊死"（eval_run_id/eval_task_id/eval_repeat 进 ctx.json）hunk 原样未动（git diff 已核对，仅叠加 Block B hunk）。

## B3 · 定向测试（只跑本文件，未动全量 smoke/verify）

命令：`node --test --import tsx tests/abort_api.test.ts`

```text
▶ abort_note · 中止残留注记纯函数（Block B，无服务依赖）
  ✔ withAbortNote：同会话标记才追加注记；异会话/无标记原样返回 (0.4502ms)
  ✔ 注记文案不含 multi-12 残留词面（trap_params.residue 同源正则，防误伤判分） (0.2591ms)
  ✔ stripAbortNoteFromMessages：字符串与 blocks 两种 content 形态都剥离；其他角色/干净消息不动 (0.2895ms)
  ✔ round-trip：附注记→剥离=原文；非数组入参原样返回 (0.5499ms)
✔ abort_note · 中止残留注记纯函数（Block B，无服务依赖） (2.1094ms)
▶ /chat/abort · fast（健康+幂等）
  ﹣ api/gateway 不可达 → skip (0.0537ms) # SKIP
✔ /chat/abort · fast（健康+幂等） (0.1203ms)
▶ /chat/abort · e2e 真流中止（PRISM_E2E_ABORT=1）
  ﹣ 未设 PRISM_E2E_ABORT=1 → skip (0.0487ms) # SKIP
✔ /chat/abort · e2e 真流中止（PRISM_E2E_ABORT=1） (0.1217ms)
ℹ tests 6
ℹ suites 3
ℹ pass 4
ℹ fail 0
ℹ cancelled 0
ℹ skipped 2
ℹ duration_ms 872.0517
```

`node --check` 两文件语法通过（SYNTAX-OK）。生产栈（8002/9200）当前未起：fast/e2e 组按既有 serviceUp 机制 skip，与并行 eval 施工（9201 栈）零互踩。

e2e 门控组（PRISM_E2E_ABORT=1）已补 Block B 双断言，供 Step9/C1 复用：a) pi 原始会话文件 `.pi/sessions/{uid}/{sid}.jsonl` **含**注记（prompt 确实携带=注入路径通）；b) 网关 `/session/messages` 回显**不含**注记且保留原文（剥离路径通）。

## 未尽事项（留 Step9/后续）

1. **multi-12 E2E 实跑验证未做**（工单归 Block C：`node eval/runner.mjs --only=multi-12`，t2 含 16,879 且无 E5/B10/MG4X 残留）——本工单禁跑 eval 域与全量门禁。
2. 网关需**重启**才生效（needsRestart 自检已有：/health 的 fileMtime 比对）；Step9 起栈自然覆盖。
3. 断连即中止（S8 P1-4 res.close）未落标记：用户关页面场景同有残留风险，但语义（"用户中止"vs"网络断"）与工单范围都不覆盖，留待拍板。
4. 标记是 RpcClient 内存态：30min 清理/崩溃 respawn 后丢失（中止→下一问窗口通常秒级，风险极低，如实声明）。
5. 一次性消费语义：中止于会话 A 后下一问去了会话 B → 标记消费不注记，此后回 A 也不补（简单可预期，已注释说明）。
6. 本修复是提示级软保证（模型遵循注记）；trap 判分仍在（若模型仍引用照判 0）——multi-12 从"必然残留"变"按注记遵循概率"，E2E 实跑是唯一硬验证。
