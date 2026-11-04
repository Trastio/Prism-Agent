# Prism-Agent · 架构级收敛清单 · 2026-10-06

> 生成日期：2026-10-06
> 性质：**结构性欠账总账**（只读汇总裁决，非施工方案；每项附最小改造方向）
> 来源：本会话多轮审查的合并收敛——
> - [全栈深度审查](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-全栈深度审查-2026-10-06.md)（链路 / 架构 / UI / 交互）
> - [插件继承与能力裁剪审查](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-插件继承与能力裁剪审查-2026-10-06.md)（R1–R6）
> - [硬编码清理与车系动态化审查意见](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-硬编码清理与车系动态化-改造计划-审查意见-2026-10-06.md)（v1–v3）
> - [插件能力裁剪加固审查意见](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-插件能力裁剪加固-改造计划-审查意见-2026-10-06.md)（F1–F8）
> 方法：逐条对照源码实测（`pi_gateway.mjs` / `prism-guardrails/index.ts` / `agent-minimal/settings.json` / 前端组件）

---

## 0. 总判决

**架构骨架合理**（分层清晰、原则统一、复用 pi 原生机制），**但有五类结构性欠账**——它们不会被单个功能修复解决，会持续再生新坑：

| 编号 | 结构性问题 | 类别 | 优先级 |
|---|---|---|---|
| **A** | 把产品语义压在 pi 的 settings/hook 语义上，却**未 pin 版本、无启动自检** → 内核升级即行为漂移 | 耦合面 | 中 |
| **B** | 网关是"**翻译层**"而非"**契约**"：事件映射不全 + 身份/scope 靠 **prompt 文本前缀**传递 | 缝合线 | **高** |
| **C** | 进程模型**每用户一 `pi.exe`，无池上限 / 无排队** → 真并发不可保证 | 规模化 | **高**（多用户前提） |
| **D** | **TS 与 HTTP 双实现并存** + **演示数据与真数据同屏** | 一致性 | 中 |
| **E** | **业务/通用双语义未分层**：两种语义共用一个 `scope`，靠 if 分支区分；叠加"信任层级非一等概念 + 工具治理四源 + 评估层不可度量" | 缝合线（新增） | **高**（能力扩展的前提，见 §5） |

**一句话**：合理，但停在"能用且方向对"，未到"稳固且可演进"。目标是**当前小规模可用**则只需收紧 B；目标是**多用户规模化 + 长期演进**则 A/C/D 须一并排期；**要做"能力扩展"（web/记忆/导出）则 E 须先解**。

---

## 1. A · 内核耦合与版本漂移

**现象**：prism 的运行时行为（工具白名单、scope、插件 hook、settings 合并）**完全依赖 pi 的内部语义**，但对内核与插件**几乎不 pin、无运行期校验**。

**证据**：
- [agent-minimal/settings.json L2-L15](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/settings.json#L2-L15)：12 个包中**仅 2 个 pin**（`cc-safety-net@2.4.15`、`@langfuse/pi-observability-plugin@0.1.2`），其余 10 个浮动。
- [pi_gateway.mjs L279](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L279)：`PI_CODING_AGENT_DIR` 指向 `agent-minimal`——一旦 pi 改变 settings 合并 / 路径解析 / hook 语义，行为静默漂移。
- 无任何机制在启动时断言"关键插件已加载 / 关键工具确不可达"。

**影响**：升级 pi 或插件后出现"行为变了但没人知道"；与 R5（[插件审查附 B](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-插件继承与能力裁剪审查-2026-10-06.md)）同源。

**最小改造方向**：
1. **pin 全部 12 个包版本**（写出精确版本号，不用浮动）；
2. 加**静态自检**（低成本）：单测断言 `KNOWN_BUSINESS_TOOLS ⊆ 已注册业务工具`，且 `--exclude-tools` 列表 ∩ 业务工具 = ∅；
3. 记录**"已冻结的 pi 版本"**（内核二进制 + 插件组合）到配置注释，升级前需过自检。

---

## 2. B · 网关缝合线（最高优先）

### B1 事件契约不完整

**现象**：`mapEvent` 是前端唯一的事件来源，但它**只覆盖部分事件**，其余静默丢成 `null`。

**证据**：
- [pi_gateway.mjs L43-L86](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L43-L86)：仅映射 `message_update`(text/thinking delta)、`tool_execution_start/end`、`agent_start`、`agent_settled`、`extension_error`、`aborted`、`ui_request`；[L84](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L84) 明确 "turn_start/end、message_start/end 等不透传"。
- **两条 `ui_request` 通路并存**：`mapEvent` 的 `ui_request`（L81-82）与 `_handleLine` 直达 `eventQueue`（[L163-167](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L163-L167)）。`/chat/stream` 走 `mapEvent`（[L385-388](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L385-L388)）——**哪条生效未证实**（正是加固计划 F3 的根因）。

**影响**：前端拿不到完整生命周期 → 无法做"停止生成/阶段提示/重试"；且 permission 观测会误判。

**最小改造方向**：**定义事件契约**——列出"前端可依赖的事件类型集合"（含 `turn_start/end`、`ui_request`），补全 `mapEvent` 并写死为前后端接口；明确单一通路（合并 `_handleLine` 与 `mapEvent` 的 ui 分支）。

### B2 上下文用 prompt 文本前缀传递

**现象**：`series_key / scope` 不是结构化字段，而是**拼进 prompt 文本**再在扩展里正则解析。

**证据**：
- 网关侧组装：[pi_gateway.mjs L348-L352](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L348-L352) `[ctx: series_key=…, scope=…]\n` 前缀拼进 `message`。
- 扩展侧解析：[index.ts L564-L576](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L564-L576) 正则 `\[ctx:\s*([^\]]+)\]` 提取，再 `replace` 删除。

**影响**：① 有**复述污染**风险（模型可能把元数据当内容复述）；② 解析靠正则，脆弱；③ 上下文不是"对象"，无法校验/扩展。

**最小改造方向**：把 `{series_key, scope, user}` 变为**显式会话上下文对象**，经 RPC 原生通道（或扩展可读的 session 元数据）传递；扩展读结构化字段，不再解析文本。**与 B1 合并为一个 change 做**（都是"网关 → 扩展"的接口化）。

---

## 3. C · 进程模型与规模化

**现象**：每用户一个常驻 `pi.exe`，池**无上限、无排队、无背压**。

**证据**：
- 池与回收：[pi_gateway.mjs L294-L298](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L294-L298) 空闲 >30min 清理；[L325](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L325) `/health` 暴露 `poolSize/pool`。
- 崩溃自动 respawn：[L118-L122](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L118-L122)。
- 单轮超时：`PRISM_TURN_TIMEOUT || 300` 秒（[L209](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L209)、[L324](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L324)）。
- 同用户串行锁：[L39-L40](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L39-L40)。

**影响**：N 个活跃用户 → N 个常驻进程；**无全局上限**，突发并发会耗尽内存/句柄；从未做压测（40 并发结论见[数据埋点文档](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-数据埋点与北极星指标-2026-10-06.md)）。

**最小改造方向**：池治理三件套——① **全局上限**（`PRISM_MAX_PROCS`）+ 超限**排队/拒绝**（明确 429 或排队）；② **背压**（并发阈值告警）；③ 明确超时与 abort 的**用户可见反馈**。设计目标：从"每用户一进程"演进为"有限池 + 会话挂载"。

---

## 4. D · 一致性

### D1 TS 与 HTTP 双实现并存

**现象**：同一业务逻辑在项目 TS（`src/verify/*`、扩展）与 FastAPI `/dashboard/*` 中各写一份；扩展**无法 import 项目 TS 模块**。

**影响**：改一处漏一处 → 逻辑分叉；已验证的语义（覆盖率守卫、grounding）可能两边不一致。

**最小改造方向**：指定**唯一真源**（建议 HTTP `/dashboard/*`，因已被 Agent 与前端共用、有校验、已在运行——见项目记忆），另一侧退化为**薄转发**，不留第二份业务逻辑。

### D2 演示数据与真数据同屏

**现象**：看板中演示卡（DemoCard）与真实 `useQuery` 数据并排，仅靠 `meta="…演示数据"` 区分。

**证据**：`MarketBoard.tsx`（版型结构 / 竞品对比）、`ReviewsBoard.tsx`（舒适样本 / 口碑趋势）等。

**影响**：PM 可能把演示数字当真数据 → 信任风险（已按项目决策保留但需降风险）。

**最小改造方向**：演示卡**默认折叠 + 显著标识**（非仅小字 meta）；或彻底移除、改由真实接口驱动。

---

## 5. E · 业务/通用双语义未分层（本次变化新增）

> 来源：《能力扩展与插件解禁-审查意见》§8（2026-10-06）。本次变化（web 解禁 + 跨会话记忆 + 文档导出）是**加能力**、非改结构，故新增此条缝合线。

**现象**：计划已明确否决新增 `office` scope → 「业务分析」与「通用办公」两种语义**共用一个 `scope=agent`**，靠 `decideVerification` / prompt 里的 **if 分支**区分（查数分支 vs web 分支 vs 闲聊分支）。

**影响**：
1. **"用分支代替模型"**——三路判定互斥但语义不互斥（混合回复即 M9/M10 误判），分支随需求只增不减；
2. **信任层级不是一等概念**——红线#1 原为"库行 ID 可复算"，web 后降级为"URL 在真值集 + host 白名单"，契约被削弱却只用一个告警分支表达；
3. **工具治理无单一清单**——`EXCLUDE_TOOLS`/`EXTRA_TOOLS`/`ALLOWED_TOOLS`/`setActiveTools` **四源**，改一处需同步三处文档（H1→M1 已连栽两次）；
4. **评估层是坏尺子**——scorer 死码 + 正则误判 ⇒ 本次变化**无法被现有 harness 验证**。

**最小改造方向（三件事，本次变化上线的前置）**：
- (a) **工具治理单一清单**——一源派生 EXCLUDE / EXTRA / 断言，消灭四源；
- (b) **验证层引入"信任层级"一等概念**——按 `library | web | none` 路由，替代并列 if 分支；
- (c) **评估层先能度量**——人工判据标准化或修 scorer，否则上线无验收锚点。

---

## 6. 收敛路线（按批次）

| 批次 | 事项 | 理由 |
|---|---|---|
| **批次 1**（低风险 / 高收益） | A-2 静态自检、A-1 版本 pin；B1 事件契约补全；D2 演示卡折叠 | 不动核心机制，立即可做，直接堵住"误判 + 信任"两类问题 |
| **批次 2**（结构性） | **B2 上下文对象化**（与 B1 同 change）；**C 进程治理三件套** | 触及网关与进程模型，需设计与压测 |
| **批次 2.5**（本次变化前置） | **E 双语义分层三件事**：工具治理单一清单 / 验证层信任层级(tier) 路由 / 评估层先可度量 | 《能力扩展与插件解禁》上线的前置结构条件（见审查意见 §8） |
| **批次 3**（长期） | D1 双实现收敛；A-3 内核版本冻结流程 | 影响面大，需排期 |

> 交叉提醒：加固计划的 **F3（B0 确认 `ui_request` 通路）** 本质是 B1 的一部分——做 B1 时一并解决，可避免"permission 实测误判"。

---

## 附 · 证据索引

| 断言 | 证据 |
|---|---|
| 仅 2/12 包 pin | [settings.json L2-L15](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/settings.json#L2-L15) |
| 事件映射不全 | [pi_gateway.mjs L43-L86](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L43-L86) |
| 两条 ui_request 通路 | [L81-L82](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L81-L82)、[L163-L167](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L163-L167) |
| ctx 前缀注入 | [L348-L352](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L348-L352) |
| 扩展正则解析前缀 | [index.ts L564-L576](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L564-L576) |
| 池无上限 | [L294-L298](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L294-L298)、[L325](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L325) |
| 单轮超时 300s | [L209](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L209)、[L324](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L324) |
| 业务工具单一常量已存在 | [index.ts L24-L33](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L24-L33) |
| 演示卡 | `MarketBoard.tsx`、`ReviewsBoard.tsx`