# Prism-Agent · 《收敛执行总计划》修订意见 · 2026-10-06

> 评审日期：2026-10-06
> 评审对象：[Prism-Agent-收敛执行总计划.md](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-收敛执行总计划.md)
> 性质：**评审意见 + 修订建议**（本文只给意见与建议改法，未改动总计划正文）
> 判据来源：主报告[《PM推理能力与Harness成熟度评估》§5 统一收敛清单](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-PM推理能力与Harness成熟度评估-2026-10-05.md#L286-L319)（**唯一优先级口径**）、[《数据埋点与北极星指标》](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-数据埋点与北极星指标-2026-10-06.md)、以及源码实测

---

## 0. 结论摘要

总计划**方向基本正确**（先接线 → 再观测 → 最后埋点算北极星），**但有 4 个硬伤 + 2 类打断风险 + 9 条 P0/P1 漏项**，不建议直接照做。

| 级别 | 数量 | 问题 |
|---|---|---|
| 🔴 严重 | 4 | Step 1 方向与主报告 §5 P0#1 相反；Step 2↔3 时序不可能；Step 7 与"不做的"自相矛盾；先删后建会丢逻辑 |
| 🟠 打断 | 2 | 删除会断 `package.json` 多个 smoke 脚本；Step 6 扩展 import langfuse SDK 可行性未验证 |
| 🟡 缺口 | 9 | 漏 §5 的 P0#7 及其余 P1/P2 多条 |
| ⚪ 小问题 | 3 | "不做的"表述含糊、命名/计数不准、缺每步验收 |

---

## 1. 必须修正的硬伤

### 1.1 Step 1「删」与主报告 §5 P0#1「接线」方向相反 ★最严重

- 总计划 [Step 1 L11-L16](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-收敛执行总计划.md#L11-L16)：**删除** `src/tools/guardrail.ts`、`src/verify/completion.ts`、`src/identity/resolve.ts` 等。
- 主报告 [§5 P0#1](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-PM推理能力与Harness成熟度评估-2026-10-05.md#L291)：**接线**——"把 guardrail.ts、verify/completion.ts、identity/resolve.ts **真正挂到**扩展的 `tool_call` / `agent_settled` / 工具注册；统一或删除取数层的 TS vs HTTP 重复"。
- 同时与此前**方案 A 拍板**（保留 extension+HTTP 作唯一语义层，**只精准退 `src/tools/query_*.ts`，保留 `src/verify/*`**）冲突。

**建议改法**：Step 1 由"清场删码"改为**"接线（让设计生效）"**：

```
Step 1（改）：接线——让已有设计进入运行时
- 把 guardrail 逻辑挂到扩展 tool_call hook（fail-closed 默认拒绝未知工具）
- 把 CLAIM 验证挂到 agent_settled（行 ID 回查 prism_views.db + scope 越界 + 缺口声明）
- 把身份解析做成 resolve_series 工具（见 Step 2）
- TS vs HTTP 重复：按方案 A 只退役 src/tools/query_*.ts（保留 src/verify/* 与 _shared.ts）
- **删除动作推迟到"全部移植并验证等价之后"（见 Step 10）**
```

### 1.2 Step 2 ↔ Step 3 时序上不可能

- [Step 2 L22](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-收敛执行总计划.md#L22)："agent 调 `resolve_series` 后结果注入 **before_agent_start** 的 `{series_key}`"。
- 事实：`before_agent_start` 在**本轮开始前**触发；`resolve_series` 是 agent **本轮里才调用**的工具。**先发生的钩子无法使用后发生的结果**。

**建议改法**：

```
Step 2（改）：身份注入 + 核验分离
- {series_key}/{series_id} 由【前端/会话】在发起请求时带入（这才是 before_agent_start 时点已知的）
- resolve_series 工具只做【核验 + 覆盖率守卫】：命中则放行，未命中 fail-closed 提示"对象未确认"
- FastAPI /identity/resolve 供核验使用（不承担"为注入提供值"的职责）
```

### 1.3 Step 7 与"不做的"自相矛盾（在线时长到底做不做）

- [Step 7 L51](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-收敛执行总计划.md#L51)：实现 `active_tick(30s心跳)` —— 这正是**在线时长**的数据源。
- [不做的 L71](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-收敛执行总计划.md#L71)：**"在线时长（上线后，开发期数据量不够）"**。

**建议改法**：二选一。推荐——**采集先做，展示后做**：

```
Step 7（改）：保留 active_tick 心跳采集（数据先攒着），仅把"在线时长指标展示/看板"列入上线后
        —— 即"不做的"改为"在线时长的【看板展示】"
```

### 1.4 先删后建 → 会丢实现逻辑（违反"保留原逻辑"规则）

Step 1 删 `resolve.ts` / `completion.ts`，Step 2/4 又在 FastAPI / extension 里**重写**身份解析 + CLAIM 验证 + 行 ID 查库。不先"移植"就删，等于**丢掉唯一参考实现**。

**建议改法**：凡"要在别处重建"的模块，**先移植 → 验证等价 → 再删**；删除统一放到最后的"收尾"步（见 §5 的 Step 10）。

---

## 2. 会打断现有资产

### 2.1 删除会断 `package.json` 的 smoke 脚本（计划未交代）

已核实依赖链：

- `src/tools/query_sales.ts` / `query_config.ts` / `query_reviews.ts` 均 `import { resolve_series } from '../identity/resolve.ts'`（各自 L14）。
- `src/verify/completion.ts` / `reference.ts` 均 `import ... from '../tools/_shared.ts'`。
- [package.json](file:///c:/Users/<you>/Desktop/Prism-Agent/package.json)：`smoke:identity→src/identity/smoke.ts`、`smoke:tools→src/tools/smoke.ts`、`smoke:grounding→src/verify/smoke.ts`、`smoke:m3→src/verify/smoke_m3.ts`。

**结论**：删 `resolve.ts` / `verify/*` / `query_*` 后，上述脚本**全部报错**；总计划既未同步更新 scripts，也未交代 `src/tools/_shared.ts` 去留。

**建议**：Step 1（接线步）内明确——同步删除/改写对应 smoke 脚本，或保留到 Step 10 收尾时一并处理；`_shared.ts` 明确"保留（HTTP 语义层仍可能用）/删除"。

### 2.2 Step 6「扩展里加 langfuse SDK」可行性未验证

- 本仓 pi 扩展**只 `import { node:fs } / { node:path }`**（[index.ts L15-L16](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L15-L16)），**全仓无 import 第三方/本地包先例**——扩展能否 import langfuse SDK 未验证。
- 且**已有** `@langfuse/pi-observability-plugin` 在自动埋点。

**建议**：Step 6 先加一个**验证前置**——"确认扩展可 import langfuse SDK（或改用给现有插件补 Prism metadata / 由网关侧埋点）"，再动手。

---

## 3. 覆盖面缺口（声称融合 25+7+20，实际漏项）

对照主报告 §5，总计划正文**漏掉**下列条目（建议补入对应 Step）：

| 漏项 | §5 条目 | 级别 | 建议归入 |
|---|---|---|---|
| **`/ui-response` 回填打通**（否则确认弹窗卡整轮 / 护栏被绕过） | 第 7 条 | **P0** | Step 5 |
| `/chat/stream` 透传 `session_id` + 补 `session_info` | 第 22 条 | P1 | Step 5 |
| 评测门禁批跑（16+34 题、正则换验证器、进 CI） | 第 8 条 | P1 | 新增 Step |
| 单测/集成测试 | 第 9 条 | P1 | 新增 Step |
| 鉴权/权限分层（管理者 vs 只读） | 第 12 条 | P1 | 新增 Step |
| `--exclude-tools` 补 `mcp`/记忆/子代理 | 第 15 条 | P1 | Step 5 |
| **密钥移出源码**（`MEM0_API_KEY` 现硬编码在 [pi_gateway.mjs L258](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L258)） | 第 24 条 | P2 | Step 5 |
| 前端小缺陷（`args` 字段 / 重复 `case` / as_of 提取） | 第 21 条 | P2 | Step 7 |
| 视图库只读打开 + 清理残留 `prism_views.db` | 第 23 条 | P2 | Step 1/10 |

> "评估体系 v2(20项)"里，`Annotation Queues` / `评测即 CI` / `两层回归(轨迹前缀)` / `五维归因补权限边界` / `infra_fail 重试` / `mock 固定外部世界` 等**基本未进正文**（Step 8 仅覆盖轨迹 + 动态评测集一部分）。

---

## 4. 小问题

1. **"不做的"表述含糊**：[L67](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-收敛执行总计划.md#L67)"40 并发治理（上线前）"放在"不做的（本轮边界）"里 —— 到底"本轮不做、上线前做"还是"不做"？建议写成"**本轮不做，列入上线前 gate**"。
2. **命名/计数不准**：头部"PM推理审查报告"实际是《PM推理能力与Harness成熟度评估》；"数据埋点与北极星(7项)"实际是 **7 个小节**非 7 项任务；"评估体系v2(20项)"与评估体系 §9 表 19 行对不上。
3. **缺每步验收/回归**：仅 Step 5 有一句验证，其余步骤无"完成判据"、无"改后回归（评测/冒烟）"。建议每步补"验收判据 + 回归命令"。

---

## 5. 建议的修订版执行顺序（Step 骨架）

> 原则：**先接线让设计生效 → 补缺口 → 观测 → 埋点 → badcase → 评测门禁 → 最后才删死代码**。

| Step | 主题 | 相对原计划的变化 |
|---|---|---|
| 0 | **基线**：跑一遍评测 + 全部 smoke，留"改前"基线 | 新增 |
| 1 | **接线**（挂 guardrail / verify / resolve 到扩展；方案 A 退役 `query_*.ts`） | 原 Step 1 由"删"改"接" |
| 2 | **身份注入+核验**：前端/会话注入 series_key；resolve_series 仅核验 | 修正时序 |
| 3 | 修上下文注入（动态化 / 条件注入 / 禁复述 / 角色分流） | 不变 |
| 4 | 护栏完整化（**移植**已有逻辑，非重写） | 明确"移植" |
| 5 | 重启 + 运行态=磁盘 **+ 补 `/ui-response`、`session_id` 透传、`exclude-tools` 补 mcp/记忆/子代理、密钥移出源码** | 补 P0/P1 漏项 |
| 6 | Prism 自建观测层（**先验证 import 可行性**） | 加验证前置 |
| 7 | 前端埋点 + `/events` 端点 + 北极星（**保留 active_tick**；"不做的"改为"看板展示上线后"） | 修正矛盾 |
| 8 | badcase 轨迹（轨迹落盘 + 点踩回放 + 动态评测集） | 不变 |
| 9 | **评测门禁 + 单测**（批跑 16+34、正则换验证器、进 CI） | 新增（补 §5#8/#9） |
| 10 | **收尾清理**：删已移植完的死代码 + 同步 smoke 脚本 + 视图库只读 | 删除后置、脚本同步 |

---

## 附：证据索引

| 编号 | 证据 | 位置 |
|---|---|---|
| E1 | 总计划 Step 1 删除 vs §5 P0#1 接线 | [总计划 L11-L16](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-收敛执行总计划.md#L11-L16) · [主报告 §5#1](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-PM推理能力与Harness成熟度评估-2026-10-05.md#L291) |
| E2 | `query_*.ts` import `resolve.ts` | `src/tools/query_sales.ts`/`query_config.ts`/`query_reviews.ts` L14 |
| E3 | `verify/*` import `tools/_shared.ts` | `src/verify/completion.ts` L15 · `reference.ts` L10 |
| E4 | smoke 脚本指向将被删目录 | [package.json](file:///c:/Users/<you>/Desktop/Prism-Agent/package.json) |
| E5 | 扩展仅 import node:fs/node:path | [index.ts L15-L16](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L15-L16) |
| E6 | `MEM0_API_KEY` 硬编码 | [pi_gateway.mjs L258](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L258) |
| E7 | `eval/runner.mjs` 未 import `scorer.ts`（scorer.ts 仅被自身引用 → 确为死码） | `eval/runner.mjs` L11-L13 |

---

# 附：v2 复审（收敛版）· 2026-10-06

> 复审对象：[Prism-Agent-收敛执行总计划.md v2](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-收敛执行总计划.md)
> 性质：**只读复审**（未改动 v2 正文）
> 判据：主报告 [§5 统一收敛清单 25 项](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-PM推理能力与Harness成熟度评估-2026-10-05.md#L286-L319) + 源码实测
> 状态：**已收敛**——以下各项互相无冲突、均已溯源，无悬而未决项

## V0. 收敛判定

v2 相对 v1 已修好 4 个硬伤（删→接、Step2↔3 时序、Step7 矛盾、先删后建）。本轮新确认：**2 个仍会卡执行的硬伤 + 1 处未声明的决策反转 + 4 个对 §5 的覆盖缺口 + 3 个技术前置未交代 + 7 个表述/口径问题**。剩余 3 项属**范围决策**（非缺陷）。

## V1. 仍会卡住执行的硬伤（2）

### V1.1 Step 2 的注入通道落不了地
- `before_agent_start` 是**扩展 hook**（[extensions.md L530](file:///c:/Users/<you>/Desktop/Prism-Agent/pi-windows-x64/docs/extensions.md#L530)），网关无此能力。
- 网关 [/chat 只读 user_id/message](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L305-L311)；[main.py /chat/stream 只转发 message/user_id/scope/session_id](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L158-L163)，**均无 series_key**。
- 池是**每用户常驻进程**，`env` 在 [spawn 时一次性设定](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L253-L261)，按请求塞 series_key 不可行。
- **改法**：补"series_key 如何进 pi 进程"的选型（拼进 prompt / RPC 自定义命令 / 池按 `(userId, seriesKey)` 分键）。

### V1.2 Step 1 的保留理由事实错误（[L45](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-收敛执行总计划.md#L45)）
extension [只 import node:fs / node:path](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L15-L16)，**不 import `_shared.ts` 也不 import `src/verify/*`**——它用的是内联验证器。→ "`_shared.ts` 仍被 extension 引用"不成立；保留理由应改为"作为唯一参考实现保留到 Step 10"。

## V2. 未声明的决策反转（1）

**V2.1 挂 guardrail 白名单 vs 扩展既有注释冲突**
扩展 [tool_call L397-L398](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L397-L398) 明确写：**"权限分层交给 pi-permission-system（弹确认），不再手写白名单"**。而 Step 1/4 要挂 `guardrail.ts` 白名单 + fail-closed。→ 需先定：**自建白名单 vs 复用 permission-system**（两者叠加还是替换），v2 未声明此反转。

## V3. 对 §5 的覆盖缺口（4）

| §5 条目 | 级别 | v2 现状 |
|---|---|---|
| **#12 鉴权/权限分层（管理者 vs 只读）** | P1 | **完全缺失**（正文零处） |
| **#25 竞品对比/优先级建议工具 + 跨会话记忆** | P2 | **完全缺失**（正文零处） |
| **#10 并发治理** | P1 | 整条降级进"不做的"；其中**"可配超时"**为原子小改，本轮可做却一并砍掉 |
| **#6 的"进程守护/就绪探针"** | P0 | 缺失：Step 5 只有"重启网关 + 清理孤儿 vite" |

> §5 声称"25 项全覆盖"，实际落到 Step 的仅 21 项。

## V4. 技术前置未交代（3）

- **V4.1 Step 9 读不到验证器结果**：[`mapEvent` L40-65](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L40-L65) 不映射任何 verdict（仅 text/tool_call/settled/error）。runner 无从"调验证器结果"——需先加事件映射或读库/`trajectories.jsonl`。
- **V4.2 Step 9 与 Step 10 冲突**：[scorer.ts 就是基于验证器的评分器](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/scorer.ts#L9-L11)；Step 9 想要验证器评分，Step 10 却[把它当死码删](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-收敛执行总计划.md#L181)。
- **V4.3 Step 7 `/events` 缺 vite 代理**：[vite.config 现无](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/vite.config.ts#L15-L24)；Step 5 给 `/ui-response` 记得加代理，Step 7 的 `POST /events` 未提，前端会 404。

## V5. 表述/口径问题（7）

1. **`SeriesCombobox` 不存在**：Step 2 [L65](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-收敛执行总计划.md#L65)"前端 SeriesCombobox 接 resolve_series"——全仓 grep 零结果，应为"**新建**"。
2. **"AGENTS.md 改条件注入"表述不准**：条件逻辑只能落在 extension（它 [L377-L382 读文件后追加](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L377-L395)），非改文件本身。
3. **Step 3 残留时序病**：[L71](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-收敛执行总计划.md#L71) 仍写 `{series_key}` "从 resolve_series 取"，与 v2 自修的坑矛盾。
4. **Step 0 基线不可比**：旧正则评分留基线，Step 9 换验证器后口径不同；且 runner [写死 `eval/eval-report.json`](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/runner.mjs#L182)。
5. **Step 10 漏改 `smoke:all`**：[package.json L15](file:///c:/Users/<you>/Desktop/Prism-Agent/package.json#L15) 的 `smoke:all` 串联了将删的 4 个脚本，只删 script 不改它 → 验收命令报错。
6. **Step 5 P1#16 语义可疑**："BI看板→仅 query_reviews"——看板有 5 个 board，限成只读 query_reviews 说不通，疑为笔误。
7. **Step 4 的 8 名称测试集在 `src/verify`**（[grounding.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/grounding.ts#L8) / [smoke.ts L42](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/smoke.ts#L42)），Step 10 要删该目录——移植时须把测试集一并搬到 extension。

## V6. 已核验正确（无需改）

- `/ui-response` 双向通道**真实存在**（网关 [`ui_request` L145](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L145) / [`extension_ui_response` L140](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L140)），Step 5 P0#7 可做。
- `before_agent_start` / `agent_settled` / `session_before_compact` / [`setActiveTools`](file:///c:/Users/<you>/Desktop/Prism-Agent/pi-windows-x64/docs/extensions.md#L1677) 均为真实 API。
- `smoke:all`、`SYSTEM.md`、`eval/user-tasks-template.md`、`series_alias`/`series_summaries` 查询均存在。
- `resolve_series` 缺失、`guardrail.ts`/`verify/*`/`identity/resolve.ts` 运行时未加载、16 题 + trap 设计——与 §5 判断一致。

## V7. 待你拍板的范围决策（3，非缺陷）

1. §5#10 并发治理：是否本轮做"可配超时"这一小改（池上限/排队/压测仍可留上线前）。
2. §5#12 鉴权/权限分层：是否进本轮 change。
3. §5#25 PM 推理工具（竞品对比/优先级建议）+ 跨会话记忆：是否进本轮 change。

---

# 附：v3 增量复审（第 3 轮）· 2026-10-06

> 复审对象：同上（v2 正文）
> 本轮聚焦尚未审计面：**运行态插件装载 / Langfuse 观测栈 / pi hook 全集 / 设计文档存在性 / §5 覆盖率闭合**
> 结论：**仅新增 1 必改 + 2 补记，并修正 1 处旧判据过时**；无新的未审计面 → 收敛

## V8. 关键新证据：运行态已装载全套插件

当前 [.pi/agent-minimal/settings.json L2-L15](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/settings.json#L2-L15) 已声明、`node_modules` 已实装：

- `@gotgenes/pi-permission-system` ✓、`cc-safety-net` ✓、`@juicesharp/rpiv-ask-user-question` ✓
- `@langfuse/pi-observability-plugin` ✓（+ `@langfuse/core`/`tracing`/`otel`），且 [langfuse.json](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/langfuse.json) 已配 key + `baseUrl=http://localhost:3000` ✓

> ⚠️ `openspec/changes/phase2-finalize/插件接通状态.md`（2026-10-04）称"插件全没装"，**已过时，不可作判据**。

## R3-1（🔴 升级为必改）：白名单方案必须定夺——permission-system 已在运行

pi-permission-system + cc-safety-net **已实装并在运行**，与扩展 [tool_call L397-L398](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L397-L398) 注释一致。Step 1/4 若再挂 `guardrail.ts` 自建白名单 + fail-closed，会与已运行门禁**叠加/冲突**。
**改法**：计划须写死二选一——① 以 permission-system 为主、自建仅补 fail-closed；② 明确替换。

## R3-2（🟠 Step 5 遗漏）：确认闸门 env 未纳入

[pi_gateway.mjs L33-L34](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L33-L34)：生产不设 `PRISM_AUTO_APPROVE_UI=1` → UI 确认全部**拒绝**；开发设 `=1` → 全部自动通过（[L134-L145](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L134-L145)）。v2 Step 5 P0#7 只说"加转发 + 明确确认策略"，未提该 env。
（网关侧 `POST /ui-response` **已存在**于 [L409](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L409)，v2 "main.py 加转发"方向正确。）

## R3-3（🟡 影响范围补记）

- v2 影响范围表 [L239-L247](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-收敛执行总计划.md#L239-L247) **未列 `.pi/agent-minimal/settings.json`**；Step 1/3/5 可能改它，应补。
- **修正 V6**：Step 0/6 依赖的 Langfuse **确认可跑**（插件 + keys + baseUrl 齐备）。

## V9. 本轮已审计面（收敛依据）

Step 0-10 全步 · UI Track 全项 · §5 25 项覆盖率 · pi hook 全集（[extensions.md](file:///c:/Users/<you>/Desktop/Prism-Agent/pi-windows-x64/docs/extensions.md#L651-L675)：`tool_execution_end`/`turn_start`/`turn_end`/`session_shutdown` 均真实）· 插件装载 · Langfuse 栈 · DB 表 · eval · 前端代理/组件 · 三份 HTML 设计文档（运行架构/运行流程/八项工作设计稿）存在性。