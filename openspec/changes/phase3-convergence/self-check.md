# Phase3 · Step 3.5 自查收敛

> 2026-10-06
> 对象：7 个 spec。反复审查任务依赖完整 / 验收可验 / 技术前置交代 / 时序无悬空。
> 结果：**7 Gap 全修**（5 必修 + 2 小修）。

---

## Gap 1（必修）· extension import 第三方包漏 better-sqlite3

**问题**：spec 2.6 Step6.1 前置验证只提 langfuse SDK，但 completion.ts 移植依赖 better-sqlite3（行ID查库，completion.ts:70 `import('better-sqlite3').Database`）。两个第三方包都要验证。

**改法**：Step6.1 前置验证扩为"better-sqlite3 + langfuse"。better-sqlite3 已在项目 node_modules，需验证 pi 子进程能 resolve（pi 用自己的模块解析，extension 目录无 package.json/tsconfig）。

## Gap 2（必修）· verdict 进 appendEntry 但 RPC 不出事件流

**问题**：extension agent_settled 已用 `pi.appendEntry('prism-verified', {pass, reasons})`（index.ts:467/476）落 verdict。但 RPC 模式下 appendEntry 的 custom entry **不出 RPC 事件流**（rpc.md 无 custom_entry 事件，appendEntry 只 TUI 渲染）。pi_gateway 读不到 verdict，mapEvent verdict 无数据源。

**改法**：extension agent_settled 时写 verdict 文件 `.pi/sessions/{userId}/{sessionId}.verdict.json`。pi_gateway 收 agent_settled 事件后读该文件，mapEvent 输出 `{type:'verdict', data:{verdict, evidence_ids, scope, reason}}`。runner 同样读此文件或 trajectories.jsonl。

## Gap 3（必修）· setActiveTools 是 extension API 非网关

**问题**：spec 2.6 说"pi_gateway 读 scope，spawn 后 setActiveTools"——错。`pi.setActiveTools()` 是 extension 内 API（extensions.md:1371/1677），网关调不到。

**改法**：scope 拼进 prompt 前缀（同 series_key：`[ctx: series_key=银河E5, scope=bi_reviews]`）。extension before_agent_start 读 scope，调 `pi.setActiveTools(allowedForScope)`。allowedForScope：bi_reviews→[query_reviews, resolve_series]，bi_sales→[query_sales, resolve_series]，bi_config→[query_config, resolve_series]，agent→全 23 工具。

## Gap 4（必修）· resolve_series agent 不一定主动调

**问题**：spec 2.2 说 resolve_series 工具做核验，但 agent 可能不调它（series_key 已在 prompt 前缀，agent 直接用）。核验不发生→红线#7 失守。

**改法**：before_agent_start 时 extension **强制调** FastAPI /identity/resolve（series_key 已在 prompt 前缀，extension 内 fetch /identity/resolve），未命中→fail-closed 阻断本轮（return {systemPrompt: 带阻断提示} 或抛错）。resolve_series 工具仍注册供 agent 查询详情，但**核验是强制前置**，不依赖 agent 主动调。

## Gap 5（必修）· scorer.ts .mjs→TS 对接未定

**问题**：spec 2.4 说"tsx eval/runner.ts 或编译"——没定。runner.mjs 是 .mjs，scorer.ts 是 TS，动态 import TS 模块在 .mjs 里跑不通。

**改法**：runner.mjs → runner.ts，用 `tsx eval/runner.ts` 跑（项目已装 tsx）。scorer.ts 直接 import。tasks.md T-9.1 改"runner.mjs 重命名为 runner.ts"。

## Gap 6（小修）· completion.ts 相对路径错

**问题**：spec 2.2 写 `../../src/verify/completion.ts`（两级），实际从 .pi/extensions/prism-guardrails/ 到 src/verify/ 是**三级** `../../../src/verify/completion.ts`（已 node path.relative 核验）。

**改法**：spec 2.2 修正路径。

## Gap 7（必修）· 8 测试集搬移依赖链未交代

**问题**：spec 2.2 Step4.4 说"8 测试集搬到 extension/name-tests.ts"。但 grounding.ts 的 verifyNames 依赖 collectNameTruth + findClosest + _shared.ts（openPrismViews 查库）。搬测试集得带整个依赖链。

**改法**：**不搬代码**。extension 直接 import grounding.ts 的 verifyNames/collectNameTruth（`../../../src/verify/grounding.ts`）。8 测试集留在 src/verify/smoke.ts，smoke:grounding 跑原位置。extension 的 grounding 校验调 grounding.ts 函数。spec 2.2 Step4.4 改"extension import grounding.ts，8 测试集留原位置"。

---

## 自查结论

- spec 层无悬空依赖（7 Gap 全修）
- 验收可验（每个 Gap 都有核验路径）
- 技术前置交代（better-sqlite3 + langfuse import 验证前置）
- 时序无悬空（series_key/scope 都走 prompt 前缀，before_agent_start 统一解析）
- verdict 数据源明确（verdict.json 文件，网关读）

**可进 Step5 subagent-driven-development**。修正后的 spec 落盘更新。
