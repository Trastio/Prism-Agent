# Prism-Agent · 架构收敛与能力扩展审查（合并版）· 2026-10-06

> 由两份文档合并：架构级收敛清单 + 能力扩展与插件解禁-审查意见（两者均保留为独立原件，本文件为整合视图）
> 整合日期 2026-10-06

---

## 阅读指引

本文件 = **架构层（第一部分）** + **本次能力扩展的审查（第二部分）**。两者并非彼此独立：本次能力扩展（web 解禁 + 跨会话记忆 + 文档导出）受架构层既有欠账约束，尤其受**结构性欠账 E（业务/通用双语义未分层）**制约——E 是「能力扩展上线的前置结构条件」。因此第一部分给出架构欠账 A–E 与收敛路线，第二部分给出本次变化的 P/N/H/M 四轮审查findings，二者在「第 0 部分 · 统一总判决」汇总为一张三层判定表、一张 A–E 欠账表和一份待决策清单。建议先读第 0 部分，再按需下钻第一/第二部分。

---

## 第 0 部分 · 统一总判决

### 0.1 三层收敛判定表

> 取自《能力扩展与插件解禁-审查意见》§8.3（整体收敛性判定）。

| 层 | 判定 | 依据 |
|---|---|---|
| 计划条目层 | 未收敛 | M1-M13 未落 |
| Harness 层 | 未收敛 | 验证层无 tier 模型 / 工具治理四源 / 评估层坏尺子 |
| 架构层 | **未收敛** | 变化不改结构、只叠能力；新增缝合线 E；C 风险上升 |

**本次变化与其范围决策（"马上上线、不留 v2"）不匹配**——它在三条未收敛的缝合线上再加负载（源自《能力扩展与插件解禁-审查意见》§8.4）。

### 0.2 结构性欠账 A–E

> 取自《架构级收敛清单》§0。

**架构骨架合理**（分层清晰、原则统一、复用 pi 原生机制），**但有五类结构性欠账**——它们不会被单个功能修复解决，会持续再生新坑：

| 编号 | 结构性问题 | 类别 | 优先级 |
|---|---|---|---|
| **A** | 把产品语义压在 pi 的 settings/hook 语义上，却**未 pin 版本、无启动自检** → 内核升级即行为漂移 | 耦合面 | 中 |
| **B** | 网关是"**翻译层**"而非"**契约**"：事件映射不全 + 身份/scope 靠 **prompt 文本前缀**传递 | 缝合线 | **高** |
| **C** | 进程模型**每用户一 `pi.exe`，无池上限 / 无排队** → 真并发不可保证 | 规模化 | **高**（多用户前提） |
| **D** | **TS 与 HTTP 双实现并存** + **演示数据与真数据同屏** | 一致性 | 中 |
| **E** | **业务/通用双语义未分层**：两种语义共用一个 `scope`，靠 if 分支区分；叠加"信任层级非一等概念 + 工具治理四源 + 评估层不可度量" | 缝合线（新增） | **高**（能力扩展的前提，见第一部分 §5 E 节） |

**一句话**：合理，但停在"能用且方向对"，未到"稳固且可演进"。目标是**当前小规模可用**则只需收紧 B；目标是**多用户规模化 + 长期演进**则 A/C/D 须一并排期；**要做"能力扩展"（web/记忆/导出）则 E 须先解**。

### 0.3 能力扩展上线前置三件事

> 取自《能力扩展与插件解禁-审查意见》§8.4（出路①「降范围」）。

先做 3 件最小结构动作再上线：

- (a) **工具治理单一清单**（一源派生 EXCLUDE/EXTRA/断言）——消灭四源；
- (b) **验证层引入"信任层级"一等概念**（`library`/`web`/`none` 路由，替代并列分支）；
- (c) **让评估层先能度量**（人工判据标准化或修 scorer），否则上线无锚点。**（注：(c) 目前「暂挂：人工度量未启动」）**

### 0.4 待决策清单

> 汇聚两份文档中所有「待用户拍板 / 待核实」项。

| 编号 | 待决策 / 待核实事项 | 出处 | 当前状态 / 影响 |
|---|---|---|---|
| M1 | `web_enable`（保留 loader 名）是否需纳入 `EXTRA_TOOLS`（实测 `toolActivation` 支持 `auto`/`dynamic`/`eager`）；`mcp__pi-web-access` 的 EXCLUDE 条目删不删 | 第二部分 §7.1 | 待拍板——不落则批次 A 的"联网"可能整个不生效 |
| M2 | verdict 可见性取哪种：改为「仅记录（用户不可见）」还是补前端渲染 | 第二部分 §7.1 | 待拍板——实测 verdict 只落 `verdict.json`，对话流不渲染 |
| M3 | URL 真值集"本轮"语义：是否按"自最后一条 user 消息起"收集（与 ③ 的 `session entry prism-web-urls` 会话级存储冲突） | 第二部分 §7.2 | 待拍板——否则跨轮旧 URL 会误通过 |
| M4 | `setToolDescription`/覆盖第三方工具描述的 API 是否可行（决定 A.2「改 web_search 的 description」是否落空） | 第二部分 §6.1 / §7.2 | 待核实 |
| M5 | 多处"已有"未复核：前端 `getUserId()`、`/chat/stream` 带 `user_id` 是否"已有" | 第二部分 §7.2 | 待核实 |
| M11 | N7 路径一致性：extension 路径与网关 `SESSIONS_DIR` 是否"一致"（`SESSIONS_DIR` 实际值未核） | 第二部分 §7.2 | 待核实 |
| M6 | A.7「人工复核」的判据 / 条数 / 通过线（决定验收 #11 是否可测） | 第二部分 §7.3 | 待拍板 |
| M7 | N12 300s 超时的 abort 后果（用户拿到空回复？半截？） | 第二部分 §7.3 | 待拍板 |
| M8 | 回改加固计划 D 断言是跨文档动作，需同步其审查文档，否则两份计划冲突 | 第二部分 §7.3 | 待拍板 |
| — | "工具治理单一清单"是否本次做（上线前置动作 (a)） | 第二部分 §8.4 / 本文 §0.3 | 待拍板 |
| N1 | URL 真值集落地（决定 P2 后门是否堵死） | 第二部分 §5.1 | 必解——待方案 |
| N2 | `user_id` 全链路来源定义（前端 `prism_user_id` → `/chat/stream` → 网关 → ctx 前缀） | 第二部分 §5.1 | 必解——待方案 |
| N3 | "降级告警"动作语义三选一（拦回灌 / 仅标注 / 仅记日志） | 第二部分 §5.1 | 必解——待方案 |
| N6 | A.4 改 AGENTS.md 撞"永不动"：裁定是"运行时不可改"还是"设计冻结" | 第二部分 §5.2 | 待裁定 |
| H4 | 新工具（web/export）是否弹框、与 `--approve` 如何交互 | 第二部分 §6.2 | 待拍板 |

> 说明：《能力扩展与插件解禁-审查意见》原 §8（架构层 + Harness 层判定）已上提至本「第 0 部分 · 统一总判决」，故本文第二部分不再重复 §8。

---

## 第一部分 · 架构级收敛清单

> 来源与生成信息：
> 生成日期：2026-10-06
> 性质：**结构性欠账总账**（只读汇总裁决，非施工方案；每项附最小改造方向）
> 来源：本会话多轮审查的合并收敛——
> - [全栈深度审查](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-全栈深度审查-2026-10-06.md)（链路 / 架构 / UI / 交互）
> - [插件继承与能力裁剪审查](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-插件继承与能力裁剪审查-2026-10-06.md)（R1–R6）
> - [硬编码清理与车系动态化审查意见](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-硬编码清理与车系动态化-改造计划-审查意见-2026-10-06.md)（v1–v3）
> - [插件能力裁剪加固审查意见](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-插件能力裁剪加固-改造计划-审查意见-2026-10-06.md)（F1–F8）
> 方法：逐条对照源码实测（`pi_gateway.mjs` / `prism-guardrails/index.ts` / `agent-minimal/settings.json` / 前端组件）
> 注：原件 §0「总判决」（A–E 欠账表）已上提至本文「第 0 部分」，此处自 §1 起保留。

---

### 1. A · 内核耦合与版本漂移

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

### 2. B · 网关缝合线（最高优先）

#### B1 事件契约不完整

**现象**：`mapEvent` 是前端唯一的事件来源，但它**只覆盖部分事件**，其余静默丢成 `null`。

**证据**：
- [pi_gateway.mjs L43-L86](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L43-L86)：仅映射 `message_update`(text/thinking delta)、`tool_execution_start/end`、`agent_start`、`agent_settled`、`extension_error`、`aborted`、`ui_request`；[L84](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L84) 明确 "turn_start/end、message_start/end 等不透传"。
- **两条 `ui_request` 通路并存**：`mapEvent` 的 `ui_request`（L81-82）与 `_handleLine` 直达 `eventQueue`（[L163-167](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L163-L167)）。`/chat/stream` 走 `mapEvent`（[L385-388](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L385-L388)）——**哪条生效未证实**（正是加固计划 F3 的根因）。

**影响**：前端拿不到完整生命周期 → 无法做"停止生成/阶段提示/重试"；且 permission 观测会误判。

**最小改造方向**：**定义事件契约**——列出"前端可依赖的事件类型集合"（含 `turn_start/end`、`ui_request`），补全 `mapEvent` 并写死为前后端接口；明确单一通路（合并 `_handleLine` 与 `mapEvent` 的 ui 分支）。

#### B2 上下文用 prompt 文本前缀传递

**现象**：`series_key / scope` 不是结构化字段，而是**拼进 prompt 文本**再在扩展里正则解析。

**证据**：
- 网关侧组装：[pi_gateway.mjs L348-L352](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L348-L352) `[ctx: series_key=…, scope=…]\n` 前缀拼进 `message`。
- 扩展侧解析：[index.ts L564-L576](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L564-L576) 正则 `\[ctx:\s*([^\]]+)\]` 提取，再 `replace` 删除。

**影响**：① 有**复述污染**风险（模型可能把元数据当内容复述）；② 解析靠正则，脆弱；③ 上下文不是"对象"，无法校验/扩展。

**最小改造方向**：把 `{series_key, scope, user}` 变为**显式会话上下文对象**，经 RPC 原生通道（或扩展可读的 session 元数据）传递；扩展读结构化字段，不再解析文本。**与 B1 合并为一个 change 做**（都是"网关 → 扩展"的接口化）。

---

### 3. C · 进程模型与规模化

**现象**：每用户一个常驻 `pi.exe`，池**无上限、无排队、无背压**。

**证据**：
- 池与回收：[pi_gateway.mjs L294-L298](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L294-L298) 空闲 >30min 清理；[L325](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L325) `/health` 暴露 `poolSize/pool`。
- 崩溃自动 respawn：[L118-L122](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L118-L122)。
- 单轮超时：`PRISM_TURN_TIMEOUT || 300` 秒（[L209](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L209)、[L324](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L324)）。
- 同用户串行锁：[L39-L40](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L39-L40)。

**影响**：N 个活跃用户 → N 个常驻进程；**无全局上限**，突发并发会耗尽内存/句柄；从未做压测（40 并发结论见[数据埋点文档](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-数据埋点与北极星指标-2026-10-06.md)）。

**最小改造方向**：池治理三件套——① **全局上限**（`PRISM_MAX_PROCS`）+ 超限**排队/拒绝**（明确 429 或排队）；② **背压**（并发阈值告警）；③ 明确超时与 abort 的**用户可见反馈**。设计目标：从"每用户一进程"演进为"有限池 + 会话挂载"。

---

### 4. D · 一致性

#### D1 TS 与 HTTP 双实现并存

**现象**：同一业务逻辑在项目 TS（`src/verify/*`、扩展）与 FastAPI `/dashboard/*` 中各写一份；扩展**无法 import 项目 TS 模块**。

**影响**：改一处漏一处 → 逻辑分叉；已验证的语义（覆盖率守卫、grounding）可能两边不一致。

**最小改造方向**：指定**唯一真源**（建议 HTTP `/dashboard/*`，因已被 Agent 与前端共用、有校验、已在运行——见项目记忆），另一侧退化为**薄转发**，不留第二份业务逻辑。

#### D2 演示数据与真数据同屏

**现象**：看板中演示卡（DemoCard）与真实 `useQuery` 数据并排，仅靠 `meta="…演示数据"` 区分。

**证据**：`MarketBoard.tsx`（版型结构 / 竞品对比）、`ReviewsBoard.tsx`（舒适样本 / 口碑趋势）等。

**影响**：PM 可能把演示数字当真数据 → 信任风险（已按项目决策保留但需降风险）。

**最小改造方向**：演示卡**默认折叠 + 显著标识**（非仅小字 meta）；或彻底移除、改由真实接口驱动。

---

### 5. E · 业务/通用双语义未分层（本次变化新增）

> 来源：《能力扩展与插件解禁-审查意见》§8（2026-10-06）。本次变化（web 解禁 + 跨会话记忆 + 文档导出）是**加能力**、非改结构，故新增此条缝合线。（该 §8 已上提至本文「第 0 部分 · 统一总判决」）

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

### 6. 收敛路线（按批次）

| 批次 | 事项 | 理由 |
|---|---|---|
| **批次 1**（低风险 / 高收益） | A-2 静态自检、A-1 版本 pin；B1 事件契约补全；D2 演示卡折叠 | 不动核心机制，立即可做，直接堵住"误判 + 信任"两类问题 |
| **批次 2**（结构性） | **B2 上下文对象化**（与 B1 同 change）；**C 进程治理三件套** | 触及网关与进程模型，需设计与压测 |
| **批次 2.5**（本次变化前置） | **E 双语义分层三件事**：工具治理单一清单 / 验证层信任层级(tier) 路由 / 评估层先可度量 | 《能力扩展与插件解禁》上线的前置结构条件（见本文「第 0 部分 · 统一总判决」） |
| **批次 3**（长期） | D1 双实现收敛；A-3 内核版本冻结流程 | 影响面大，需排期 |

> 交叉提醒：加固计划的 **F3（B0 确认 `ui_request` 通路）** 本质是 B1 的一部分——做 B1 时一并解决，可避免"permission 实测误判"。

---

### 附 · 证据索引

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
| 演示卡 | `MarketBoard.tsx`、`ReviewsBoard.tsx` |

---

## 第二部分 · 能力扩展与插件解禁 · 审查意见

> 日期：2026-10-06
> 被审对象：`设计图总览/Prism-Agent-能力扩展与插件解禁-改造计划.md`
> 审查方式：只读；所有结论附代码行号，可复算
> 判定：**未收敛**（4 处硬伤 + 5 处覆盖缺口 + 3 处表述/结构问题）

---

### 0. 结论摘要

| 类别 | 数量 | 编号 |
|---|---|---|
| 硬伤（必改） | 4 | P1-P4 |
| 覆盖缺口 | 5 | P5-P9 |
| 表述/结构 | 3 | P10-P12 |

**计划说对的地方（先确认）**：
- 「decideVerification 已有放行逻辑，补 web 分支」——属实（三路放行：查数/未查数/闲聊）。
- 「EXCLUDE 删除 + ALLOWED_TOOLS 加入 + setActiveTools 按 scope 生效」——机制成立；`bi_*` 各用 2 工具、`agent` 用 `ALLOWED_TOOLS`，故解禁后**看板模式不会泄漏 web 工具**。

---

### 1. 硬伤（必改）

#### P1 · 记忆设计依赖不存在的通道，且可能 49 人串号
**计划原文**：「extension `agent_settled` 写 `.pi/sessions/{userId}/memory.json`……按 userId 隔离（不串号）」。

**实测**：
- 扩展**没有 userId**（全仓 grep 无 `userId`），只有会话 id：
  `const sid = ctx.sessionManager?.getSessionId?.() ?? (ctx as any).sessionId ?? 'default'`
  —— [index.ts L716](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L716)、[L725](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L725)
- 兜底值是 **`'default'`**：若 RPC 模式下 `getSessionId()` 返回空，**所有用户共写 `.pi/sessions/default/memory.json`** → 正是计划声称要避免的"49 人串号"。
- `userId` 只存在于**网关侧**（`pool` 以 `userId` 为键、`--session-dir` = 用户目录）——[pi_gateway.mjs L262-L275](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L262-L275)，**未下传给扩展**。

**影响**：记忆要么串号（安全问题），要么退化成"单会话记忆"（"跨会话"目标落空）。

**修法（二选一，施工前必须定）**：
1. 把 `user_id` 加进 `[ctx: ...]` 前缀显式下传（与现有 series_key/scope 同路，[pi_gateway.mjs L352-L360](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L352-L360)）；或
2. 实证 `getSessionId()` 在 RPC 模式确为用户稳定 id，并取消 `'default'` 兜底（改为 fail-closed 不写记忆）。

---

#### P2 · "URL 即放行"把红线#1 整条豁免掉
**计划原文**：验证层 B —— `if (回复含 web URL 且不含库行 ID) → 放行（不跑库校验）`。

**实测**：`decideVerification` 一旦 `pass` 即 **early-return，根本不进 `verifyCompletion`/`verifyNames`** —— [index.ts L715-L721](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L715-L721)。

**影响**：**agent 只要给数字配一个 URL，编造数据也能全绿通过**。红线#1"数据真实性"是硬底线，这里等于开了一条"引用 URL 即免检"的后门；且与计划自己"库优先"的目标互相拆台——选 web 比选库更省事、还免检。

**修法（至少）**：
- 加 **URL host 白名单**（非白名单 host 不放行）；
- 业务数字类问题若**只给 web 来源**→ 降级为"标注 web 来源/不可复算"或告警，而非沉默放行；
- 明确登记为**已接受风险**，并补 1 条回归用例（编造数字 + 假 URL 应被识别）。

---

#### P3 · 加 web/export 进 `ALLOWED_TOOLS` 会打破加固计划 v6 的不变量
**实测**：`ALLOWED_TOOLS = new Set([...KNOWN_BUSINESS_TOOLS, 'ask_user_question'])` —— [index.ts L39](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L39)。

**冲突**：加固计划 v6 的 D 断言为 `ALLOWED_TOOLS \ KNOWN_BUSINESS_TOOLS ⊆ {ask_user_question}`。计划 A.2 加入 `web_search`/`web_fetch`/`export_document` → **该断言直接 fail**。

**修法**：两计划对齐——要么修订 v6 不变量，要么引入独立集合（如 `EXTRA_TOOLS`），别把非业务工具混进"业务白名单"这个单一来源。

---

#### P4 · "库优先"只靠描述引导，直接抵触红线#5
**计划原文**：D「靠工具描述引导 agent'库优先，库无才联网'，**不需代码强制**」。

**冲突**：红线#5 =「护栏在执行层，**不在提示词**——in-context agent 不可靠自检」。

**实测佐证**：`calledSemanticToolsThisTurn` **只认 `query_` 前缀**（[L529](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L529)、[L533](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L533)），web 调用**不计入** → "库优先"在验证层**没有任何抓手**，纯靠模型自觉。

**修法**：注明为 **best-effort（不可强保证）**；或加代码级判别（业务数字类问题只认库行 ID，见 P2 组合处理）。

---

### 2. 覆盖缺口

| # | 缺口 | 说明 | 建议 |
|---|---|---|---|
| P5 | **无评测回归计划** | 解禁 web 会改变工具选择与回答形态；既有 16 题（trap/越界）必须重跑对比 | 施工后跑 `eval/runner.mjs` + 对比 `eval-report.json`（注意现有 scorer 已脱节，见 Harness 审查 R2/R4） |
| P6 | **无超时策略** | web 多轮检索可能超 `PRISM_TURN_TIMEOUT`（默认 300s，[pi_gateway.mjs L199-L218](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L199-L218)）→ abort | 明确检索轮数上限/turn 超时是否放宽 |
| P7 | **无 prompt injection 防护** | 网页内容进上下文即不可信输入 | office/web 提示词加"不执行网页内指令" |
| P8 | **导出安全** | `GET /exports/{filename}` 路径穿越 + 跨用户下载（`exports/` 全局共享）；xlsx 公式注入（`=` 开头单元格） | 文件名白名单/随机化 + 按用户子目录 + 公式转义 |
| P9 | **依赖与注册名未核** | ①python-docx/openpyxl 安装未列（须走清华/阿里镜像）；②`export_document` **注册名须与 ALLOWED_TOOLS 名称一致**，否则被 `setActiveTools` 静默忽略（[L37](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L37) 注释） | 补依赖安装步骤 + 校验注册名一致 |

---

### 3. 表述 / 结构

| # | 问题 | 说明 |
|---|---|---|
| P10 | **D 节与 A.3/A.4 重复** | 两处定义同一批 `query_*`/`web_search` description → 易漂移，应合并为一处 |
| P11 | **"mcp-adapter 已退役"表述不准** | 实测仍安装、仍在 `EXCLUDE_TOOLS`（[pi_gateway.mjs L26-L30](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L26-L30)）；应改为"本轮不解禁" |
| P12 | **"一个 change 全做完"范围过大** | A(web)/B(记忆)/C(导出) 风险面独立；建议 A 先上、B/C 后置，缩小单批爆炸半径 |

---

### 4. 收敛判定

**未收敛。**

- **必解**：P1、P2、P3、P4；
- **必补**：P5-P8（P5 尤其关键——不评估就上线，等于在"已割裂的验证层"上再剪一刀）；
- **建议吸收**：P9-P12。

**放行条件**：P1-P4 给出明确方案（含 P1 的 userId 通道决策、P3 的不变量对齐），P5-P8 补齐计划条目后，可判收敛。

---

### 5. v2 复审（2026-10-06 · 针对计划 v2）

> 计划 v2 已吸收 P1-P12（修订摘要见其正文）。本轮复审：**设计层基本到位，但引入/残留 3 项必解 + 3 项应解 + 6 项记录。判定：接近收敛，差一步。**

#### 5.1 必解

**N1 · URL 白名单是"假真值"——P2 后门未堵死**
- v2 用「URL host 白名单」放行 web 回复，但**只校验域名，不校验该 URL 是否真由本轮 `web_search`/`web_fetch` 返回过**。
- agent 可编造 `https://www.autohome.com.cn/xxx` → host 命中 → 放行 ⇒ **编造数字 + 伪造白名单域名 URL 依然免检**。
- 修法：要求 URL **必须出现在本轮 web 工具实际返回内容里**（新增"本轮 URL 真值集"，类比 `prism-name-truth`）。否则 P2 只是把后门从"任意 URL"收窄为"白名单域名 URL"。

**N2 · `user_id` 来源未定义 → A.6/B.1 无法落地**
- v2 说「ctx 前缀加 `user_id=usr_xxx`」，但**谁生成、格式、前端如何传**全未写。
- 网关 `pool` 键确为 `userId` —— [pi_gateway.mjs L262](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L262)，但该值来源未定。**P1 的修复完全依赖它，此点不落 = P1 未修。**
- 修法：明确全链路：前端 `prism_user_id`(localStorage) → `/chat/stream` → 网关 → ctx 前缀。

**N3 · "降级告警"动作语义未定义，验收 #5 不可测**
- v2 多处"降级告警"，但未定义其**动作**：仅记 `verdict.json`？回灌重答？用户可见标注？
- 验收 #5 只写"降级告警"，**无可测判据**。
- 修法：定义告警 =（a）拦回灌 /（b）仅标注 /（c）仅记日志，三选一并写入验收。

#### 5.2 应解

| # | 问题 | 说明 |
|---|---|---|
| N4 | 评测基线不可信 | P5 靠「runner.mjs 对比 eval-report.json」，但 Harness 审查已证 **scorer 死码 + 正则误判越界**（R2/R4）→ 坏尺子量回归无效。需先修 scorer 或改人工复核 |
| N5 | `EXTRA_TOOLS` 两处定义不一致 | ③ 工具接口层写 `['ask_user_question','web_search','web_fetch','export_document']`；A.1 写 `['ask_user_question','web_search','web_fetch']`（export 推迟 C）→ 需统一 |
| N6 | A.4 改 AGENTS.md 撞"永不动" | AGENTS.md 头部「全局 SOP（永不动）· 不可被会话修改」→ 需先裁定"永不动"是"运行时不可改"还是"设计冻结" |

#### 5.3 记录（低优先）

| # | 问题 |
|---|---|
| N7 | `memory.json` 路径：扩展用 `process.cwd()/.pi/sessions/{id}`，网关用 `SESSIONS_DIR` → 需确认一致 |
| N8 | ②「compaction 保留 web URL」：`session_before_compact` 当前**仅观测**（[L787-L790](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L787-L790)），无改写能力 → 需核实，否则空头支票 |
| N9 | `export_document` 是**写副作用**工具，与现有只读业务工具性质不同，未提资源/频次限制 |
| N10 | 业务数字关键词含"舒适/动力/续航"易误报降级告警 |
| N11 | 验收 #3「库优先」与 P4 的 best-effort 自相张力（建议标注为不强保证） |
| N12 | web 多轮 + 业务查询的超时未给具体数值 |

#### 5.4 收敛判定

**接近收敛，差一步。** P1-P12 已解；**N1/N2/N3 必解**（N1 尤甚——它是 P2 的残留后门，不堵等于 P2 白改），N4-N6 应解。放行条件：N1-N3 给出明确方案 + N4-N6 补齐。

---

### 6. Harness 适应性复审（2026-10-06 · 针对本次变化）

> 问题：本次变化（web 解禁 + 记忆 + 导出）下，harness 是否需改、改哪里。
> 计划 v2 已给出"Harness 五层调整"（①提示词 ②上下文 ③工具接口 ④验证层 ⑤编排），方向对，**但落点有硬伤与缺口**。

#### 6.0 地基级错误：web 工具真名与计划不符

pi-web-access 实际注册的工具名（`DEFAULT_TOOL_NAMES`，[pi-web-access/index.ts L250-L254](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/npm/node_modules/pi-web-access/index.ts#L250-L254)）：

| 真名 | 计划里写的 | 后果 |
|---|---|---|
| `web_search` | ✅ 一致 | — |
| **`fetch_content`** | ❌ 计划写 `web_fetch` | **删 `web_fetch` = 空操作**；真正该动的 `fetch_content` 没提 |
| `source_check` | ❌ 未提 | 未处理 |
| `get_search_content` | ❌ 未提 | 未处理 |
| `web_enable`（保留 loader 名） | ❌ 未提 | 若是 lazy-loader，缺它可能**根本不激活** |

⇒ 计划 A.1「删 EXCLUDE 的 `web_search`/`web_fetch`」**删错**；且只放 `web_search` 会**没有取页能力**（`fetch_content` 未启用），"联网查询"残缺。

#### 6.1 必改

**H1 · 工具名纠正**（= 6.0）
A.1/A.2/A.3 的地基。需改为枚举 `web_search` + `fetch_content`（并决定 `source_check`/`get_search_content`/`web_enable` 是否启用）。

**H2 · A.2「改 web_search 的 description」大概率不可行**
该工具由 pi-web-access 包注册，扩展只能注册自己的工具；除非 pi 提供覆盖第三方工具描述的 API（需核实有无 `setToolDescription`/override），否则 A.2 落空 ⇒ "库优先"引导只能写进 SYSTEM.md/AGENTS.md。

**H3 · 评估层 harness 完全未适配**
计划只写 P5「跑一次对比」，但本次变化**改变了"正确答案"的定义**（web 来源题 / 库优先题 / 混合题 / 记忆跨会话题 / 导出题）；且现有 scorer 是死码、正则误判越界（Harness 审查 R2/R4）⇒ **拿旧 16 题对比 = 无效回归**。需新增题型 + scorer 支持 web/混合（与 N4 合并处理）。

#### 6.2 应改

| # | 缺口 | 说明 |
|---|---|---|
| H4 | 闸0 permission-system 未纳入 | 新工具（web/export）是否弹框、与 `--approve`（[pi_gateway.mjs L279](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L279)）如何交互未定 → 可能阻断 web |
| H5 | 新增 harness 组件未登记/未配单测 | 本轮要新增的纯函数——**URL 真值集**(N1)、**业务数字识别**(P2/P4)——应列入"组件机制"并加 `smoke:verify` 用例；计划只写"smoke:all 全过" |
| H6 | 前端层未提 | export 下载链接如何在对话中渲染/点击；`mapEvent` 是否需新事件（导出链接事件） |
| H7 | ② 注入顺序引用不存在的组件 | "状态栏 → memory.json → SYSTEM.md"中的**状态栏当前未做**（Harness 审查：状态栏未实现） |
| H8 | ②"compaction 保留 web URL"无能力 | `session_before_compact` 仅观测（[index.ts L787-L790](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L787-L790)），无改写能力（同 N8） |

#### 6.3 说明（非缺口）

- **H9**：`tool_result` 跳过 grounding——现状**已只处理 `query_*`**（[index.ts L666-L688](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L666-L688)），计划把它当"改动"表述失真。要么澄清"无需改"，要么与 H5 的 URL/数字采集合并。

#### 6.4 判定

**harness 必须改，且计划的"五层调整"不完整**——**H1/H2/H3 为必改**。尤其 **H1**：工具名错了，其后 EXCLUDE/ALLOWED/description 全建在错名上。

---

### 7. v3 复审（2026-10-06 · 计划仍为 v3 未更新）

> 说明：本轮读取计划文件，**版本仍为 v3，与 §5/§6 复审对象一致**，未见对 M 系（§7 前身）的修订。以下为本轮复审，含 2 条推翻 v3 原判断的新发现。

#### 7.1 必改

**M1 · web 可用性地基仍未闭环（H1 只修了一半）**
v3 把 4 个工具名改对了，但漏了两个决定"web 到底能不能用"的东西：
- **`web_enable`（保留 loader 名）**：实测 pi-web-access 有 `toolActivation` 配置项，取值 `auto`/`dynamic`/`eager`（[index.ts L1084-L1085](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/npm/node_modules/pi-web-access/index.ts#L1084-L1085)），并保留 `web_enable` 作为 loader 名（[L348](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/npm/node_modules/pi-web-access/index.ts#L348)）。**若默认为 dynamic，必须把 `web_enable` 纳入 EXTRA_TOOLS**，否则工具注册了但不激活。
- **`mcp__pi-web-access`**：EXCLUDE 里这条仍在（[pi_gateway.mjs L27](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L27)），计划未说明删不删。
→ 不落此两点，批次 A 的"联网"可能整个不生效。

**M2 · N3 的"用户可见 verdict 标注"与实测矛盾**
v3（L102）仍写"用户可见 verdict 标注"。实测：verdict 只落 `verdict.json`（[index.ts L467](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L467)），仅被 main.py 某列表端点读取（[main.py L480-L513](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L480-L513)），**对话流不渲染**（前端无 verdict 引用）。
→ 改为"仅记录（用户不可见）"，或补前端渲染。

**M9 · 推翻 v3 "verifyNames 无需改" 的结论（新发现 · 混合回复误判）**
v3（L105）称"verifyNames 只校验 query_* 返回的名称……H9 现状已跳过非 query_，无需改"。**这是把 tool_result 的采集逻辑与 verifyNames 的判定逻辑混为一谈**：`verifyNames(rawText, truthNames)` 作用于**整段回复文本**，与"哪个工具产生"无关。当回复**混合**了库内业务名与 web 来源名（如查竞品动态时引用库外车型），库外名不在 `truthNames` 中 → 被判**编造 → veto 归 0**。H9 只覆盖 tool_result 收集，不覆盖 verifyNames。
→ 必须改：web 分支下 `verifyNames` 需跳过"本轮 web 真值集内的名称"，或 web-only 回复不跑 verifyNames。

**M10 · 混合回复（库 + web）无定义（新发现）**
v3 的三路判定（L91-96）是互斥的，但**未定义"同时调了 query_* 和 web_search、并同时引用两侧数字/名称"**的情形：按 L91 分支 1 命中（调过 query_*）→ 走严格 verifyCompletion，web 侧数字不匹配库 → 误判。需补"混合分支"规则。

#### 7.2 应改

| # | 问题 | 说明 |
|---|---|---|
| M3 | URL 真值集"本轮"语义与存储层冲突 | N1 说"**本轮**"，③ 写存 `session entry prism-web-urls`（会话级）。不按"自最后一条 user 消息起"收集，跨轮旧 URL 会误通过——正是 N1 要堵的洞 |
| M4 | "pi 无 setToolDescription API"是未证实断言 | v2 复审要求"需核实"，v3（L45/L200）直接当结论写进"不做"清单 |
| M5 | 多处"已有"未复核 | L52-L53 称前端 `getUserId()`、`/chat/stream` 带 user_id "已有"——**未核**；同类"照设计稿断言"风险 |
| M11 | N7 路径一致性是断言非核实 | L30 称 extension 路径与网关 `SESSIONS_DIR` "一致"，未核 `SESSIONS_DIR` 实际值 |
| M12 | memory.json 无脱敏/无上限 | schema（L166）含 question/conclusion 原文，无 PII 脱敏（前端 tracker 有 VIN 脱敏，记忆侧无）+ recent 无条数上限（无界增长） |

#### 7.3 记录（低优先）

- **M6**：A.7「人工复核」无判据/条数/通过线 → 验收 #11 不可测；且 scorer 不修 → `ci.sh` 自动门禁持续失效（v3 未点明）。
- **M7**：N12 只说 300s 默认，未定义 abort 后果（用户拿到空回复？半截？）。
- **M8**：回改加固计划 D 断言是跨文档动作，需同步其审查文档，否则两份计划冲突。
- **M13**（新）：A.1 删 EXCLUDE 的 `fetch_content`/`source_check`/`get_search_content` **多半是删不存在的条目**（EXCLUDE 原只有 web_search/web_fetch）→ 无副作用，但说明"EXCLUDE 是操作闸"的表述失真；真正生效的是 `EXTRA_TOOLS` + setActiveTools。

#### 7.4 判定

**未收敛。** v3 已解 N/H 表层条目，但 **M1（web 地基）、M2（自述矛盾）、M9（新：verifyNames 混合误判）、M10（新：混合分支缺失）为必改**；M3-M5、M11-M12 应改。
**放行条件**：M1/M2/M9/M10 给出明确方案 + M3-M5/M11-M12 补齐。

> 原 §8 架构层+Harness 层判定已上提至本文「第 0 部分 · 统一总判决」

---

### 8. v4 复审（2026-10-06 · 针对计划 v4）

> 对象：计划 v4（已吸收 M1-M13 + 架构层 E 决策）。本轮核了两处决定 M2/M9 成立与否的实现事实，发现 **M2 修订方向搞反**，并有一条与架构清单直接对立。

#### 8.1 必改

**K1 · v4 与架构清单 §0 直接矛盾（文档对立）**
架构清单 §0（本文件 §0.2）明写"**要做"能力扩展"（web/记忆/导出）则 E 须先解**"；v4（L8/L34-L38/L149）却决定"E 不是本轮做，if 分支 4 路够用"。**两份文档结论对立**，必须改其一：改清单为"E 完整解留治理，本轮以 if 分支过渡"，或承认本次上线违反前置条件。

**K2 · M12 的修法不可行**
v4（L24/L60）写"VIN/车牌脱敏**复用 tracker.ts sanitize**"。tracker.ts 是前端 TS，**扩展无法 import 项目 TS 模块**（架构清单 D1 已证）→ 必须在 extension 内**重实现**，并登记为 D1 的**新实例**。

**K3 · M2 改反了（有实测反证）**
- v4 L17 改"仅记录 verdict.json（**用户不可见**）"，同句又说"前端 verdict 显示是已有功能"——**自相矛盾**。
- 实测前端**确实渲染** verdict：[ChatView.tsx L234](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/ChatView.tsx#L234) 显示 `验证: {lastVerdict.verdict} · {reason}`，[L153-L155](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/ChatView.tsx#L153-L155) 从 settled 事件顶层取 verdict。
→ **v3 的"用户可见"原本正确，v4 反改错**。正确做法：保持用户可见，让 `web_downgrade` 提示走同一条 `reason` 渲染路径。

**K4 · M9 的修法误伤两条红线检测**
实测 [grounding.ts L118-L186](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/grounding.ts#L118-L186)：v4 要改的"只拦 truthNames 内名称被写错"，实际等于**移除**——
- L155-L157「库源无对应版型名（**疑似编造**）」→ 编造版型名不再拦；
- L167-L183 全局兜底「品牌/车系**张冠李戴**」→ 不再拦。
→ **削弱红线#6（名称编造 fail-closed）**。应改为"把**本轮 web 真值集内的名称**并入可接受集"，而非整体关闭。

#### 8.2 应改

| # | 问题 | 说明 |
|---|---|---|
| K5 | 混合分支无"分片"判据 | v4 L44/A.3"库部分走 verifyCompletion + web 部分走 URL 真值集"——**如何界定哪段是库、哪段是 web** 未定义 → 不可实现、不可测 |
| K6 | A.7 评测与"人工度量暂挂"决定冲突 | v4 仍把 A.7 放在批次 A 必做 → 应随决定标暂挂或移出本轮 |

#### 8.3 记录

- **K7**：M11"一致"未覆盖 spawn cwd（`process.cwd()` 是否 = PROJECT_ROOT）。
- **K8**：别沿用网关 `.pi/sessions/last-verdict.json` 的**全局兜底**模式到 memory.json（[pi_gateway.mjs L79](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L79)）——共享文件会跨用户泄漏。
- **K9**：ChatView 对 reason **截断 30 字符**（L234）→ web_downgrade 文案需控长。

#### 8.4 判定

**未收敛。** M1-M13 已落，但 **K1-K4 必改**（K1 文档对立 / K3 改反 / K4 误伤红线 / K2 不可行）。
**放行条件**：K1 二选一裁定 + K2 改为 extension 内实现 + K3 恢复"用户可见" + K4 改为"并入 web 真值集名称"。

---

### 附录 · 证据索引

- 扩展：[prism-guardrails/index.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts) — L39(ALLOWED_TOOLS)/L368-394(decideVerification)/L518-539(calledSemanticTools)/L566-651(before_agent_start)/L690-784(agent_settled)/L716,L725(sessionId)
- 网关：[pi_gateway.mjs](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs) — L26-30(EXCLUDE)/L199-218(超时)/L262-297(池/userDir)/L352-360(ctx 前缀)
- 关联计划：[加固计划 v6](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-插件能力裁剪加固-改造计划.md)（D 断言来源）
- 关联审查：[Harness 深度审查 v2](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-Harness深度审查-2026-10-06.md)（R2/R4 评估层脱节）

---

## 第 3 部分 · 交叉引用

### 3.1 两份源文件的互引关系

| 引用方 | 引用位置 | 被引方 | 内容 |
|---|---|---|---|
| 源文件1（架构级收敛清单） | §5 E 的来源注 | 源文件2（能力扩展与插件解禁-审查意见）§8 | 本次变化新增缝合线 E 的判定来源（已上提至本文第 0 部分） |
| 源文件1 | §6 收敛路线「批次 2.5」 | 源文件2 §8 | 「能力扩展上线的前置结构条件」（已上提至本文第 0 部分） |
| 源文件2 | §7.3 M8 | 源文件1 / 加固计划 v6 | 回改加固计划 D 断言需同步审查文档，否则两份计划冲突 |
| 源文件2 | §5.2 N4 / §6.1 H3 | Harness 深度审查 v2 | scorer 死码 + 正则误判（R2/R4）使回归无效 |

### 3.2 源文件1 的关联文档

- [全栈深度审查](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-全栈深度审查-2026-10-06.md)（链路 / 架构 / UI / 交互）
- [插件继承与能力裁剪审查](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-插件继承与能力裁剪审查-2026-10-06.md)（R1–R6）——源文件1 §1 引用其附 B（R5 同源）
- [硬编码清理与车系动态化审查意见](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-硬编码清理与车系动态化-改造计划-审查意见-2026-10-06.md)（v1–v3）
- [插件能力裁剪加固审查意见](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-插件能力裁剪加固-改造计划-审查意见-2026-10-06.md)（F1–F8）——源文件1 §6 交叉提醒引用其 **F3**（B0 确认 `ui_request` 通路）
- [数据埋点与北极星指标](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-数据埋点与北极星指标-2026-10-06.md)——源文件1 §3 引用其 40 并发结论

### 3.3 源文件2 的关联文档

- 被审计划：`设计图总览/Prism-Agent-能力扩展与插件解禁-改造计划.md`
- [加固计划 v6](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-插件能力裁剪加固-改造计划.md)（D 断言来源）
- [Harness 深度审查 v2](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-Harness深度审查-2026-10-06.md)（R2/R4 评估层脱节）

### 3.4 关键代码/配置引用（两份源文件共有）

- [.pi/extensions/prism-guardrails/index.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts)
- [prism-api/pi_gateway.mjs](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs)
- [.pi/agent-minimal/npm/node_modules/pi-web-access/index.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/npm/node_modules/pi-web-access/index.ts)
- [prism-api/main.py](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py)
- [.pi/agent-minimal/settings.json](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/settings.json)