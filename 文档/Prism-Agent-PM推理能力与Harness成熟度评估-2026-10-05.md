# Prism-Agent · 成熟度评估（PM 推理 / Harness / 前端 UI / 可观测性）· 收敛版

> 审查日期：2026-10-05
> 审查根目录：`c:\Users\<you>\Desktop\Prism-Agent`
> 议题：① 是否真能"像汽车产品经理一样思考"？② Harness 是否够好、能否保证正常运行？③ 前端 UI 与"他是谁"答非所问的根因？④ 可观测性：Langfuse 到底有没有 Prism 领域层？
> 性质：**只读审查，未改动任何代码**
> **文档关系**：本文为**主报告**，已并入两份子报告全部要点——《[Prism-Agent-UI改造需求与上下文注入根因](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-UI改造需求与上下文注入根因-2026-10-05.md)》与《[Prism-Agent-可观测性与全栈深审报告](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-可观测性与全栈深审报告-2026-10-05.md)》；三份文档的优先级一律以本文 **§5 统一收敛清单** 为准。

---

## 0. 结论摘要（四个问题的直接回答）

| 问题 | 裁决 | 一句话 |
|---|---|---|
| ① 像不像汽车 PM？ | **部分像（约 60%）** | "检索 + 纪律"做到了行业少见的严谨（三维度/口径/越界/假设清单）；但**"推理"薄**——竞品/区域/优先级/权衡缺工具，且**核心纪律工具 `resolve_series` 根本没注册**，纪律也多停留在提示词而非执行层 |
| ② Harness 够不够好？ | **不够** | 家底不薄（评测体系/验证器/护栏/身份解析**都写了**），但**大量"建好没接线"的死代码**：`guardrail.ts`、`verify/completion.ts`、`src/tools/*`、`src/identity/resolve.ts` **运行时全未加载**；无单测、评测**从未批跑**、无并发治理、无 Prism 层观测、运行态与磁盘代码不一致 |
| ③ 前端 UI / 上下文？ | **有硬伤** | 「他是谁」是**上下文硬编码注入**所致；UI 存在空壳项（产物/设置）、缺 SKILLS 库、会话不可重命名、顶部死元素、**半数图表为硬编码示例数据** |
| ④ 可观测性 / 与 pi 脱勾？ | **没有 Prism 领域层** | Langfuse **有 trace、也能看到业务工具**，但命名/结构/标签全是 pi 的（`Pi Turn`/`Conversational Turn`/`tags=pi`）；**无 series_key/维度/as_of/覆盖率/CLAIM/scope 的一等字段**；`prism-api` 与 `pi_gateway` **零埋点** |

**根因一句话**：**"设计完备度" 远高于 "运行时落地度"**——文档/spec/代码都写全了，但**执行层（pi 扩展）只加载了两行 `node:fs/node:path`**，把上层精心设计的护栏/验证/评测全部旁路。

---

## 1. 议题一：是否"像汽车 PM 一样思考"

### 1.1 已具备的 PM 资产（确实不多见）

| 资产 | 内容 | 位置 |
|---|---|---|
| 领域模型 | 棱镜三维度（配置=产品力 / 口碑=需求验证 / 销量=市场结果）+ 舆情外挂 | [AGENTS.md](file:///c:/Users/<you>/Desktop/Prism-Agent/AGENTS.md) |
| 分析纪律 | 分层推进、口径逐维声明 as_of、结论不越界、数据缺口假设范式、CLAIM 结构 | 同上 |
| 身份前置核验 | 红线#7：分析前先 `resolve_series`，不脑补对齐 | [src/identity/resolve.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/identity/resolve.ts) |
| Golden cases | E5 / 零跑D19 / 铂智7X 端到端 + 归因假设清单（排除假设→主嫌疑→相关≠因果） | [工作⓪-E5端到端](file:///c:/Users/<you>/Desktop/Prism-Agent/工作⓪-E5端到端) |
| 评测集 | 16 题（跨维度10 + trap6），每题对应一个拦截机制 | [eval/tasks_v1.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/tasks_v1.ts) |

实测会话也印证：Agent 能产出"月度走势表 + 环比/同比 + 版型销冠 + 交棒判断"这类**有 PM 味的结构化结论**（[14-59-42Z 会话](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/sessions/usr_g5r6h5ye)）。

### 1.2 判据评分（"像 PM"的 6 个硬指标）

| 判据 | 评分 | 依据 |
|---|---|---|
| 口径严谨（不看错数） | ★★★★☆ | 月末行口径、同版型 tp vs 加权、as_of 声明都到位 |
| 不越界（不乱归因） | ★★★★☆ | SOP + 验证器 regex 双重约束"市场侧不归因产品力" |
| 数据缺口处理 | ★★★★☆ | 假设清单范式（强/弱/不可验）已成型 |
| 竞品/横向推理 | ★★☆☆☆ | **无竞品对比工具**（看板"竞品对比"是硬编码；chat 只能靠 `search_cars` 拼） |
| 归因/因果推理 | ★★☆☆☆ | 有"排除假设"范式，但**无因果推断/量化拆解工具**，全靠模型自由发挥 |
| 优先级/取舍（PM 决策） | ★☆☆☆☆ | 无 KANO/RICE/ICE、无"该做什么"的建议层，只能"描述现状" |
| 记忆/连续性 | ★☆☆☆☆ | 无跨会话记忆；同一用户进程回收即忘 |

### 1.3 三个硬伤（直接导致"不够像 PM"）

**① 核心纪律工具 `resolve_series` 根本没注册（最严重）**

- 扩展实际注册 **23 个工具** = `query_reviews/query_sales/query_config`(3) + `sentiment_*`(6) + Atuohome 14（[index.ts L55-L237](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L55-L237)）。
- **没有 `resolve_series`**。但 AGENTS.md 红线#7 要求"分析前先 resolve_series"，eval `trap-04` 也按"是否调用 resolve 工具"判分。
- 后果：**最核心的身份核验纪律在运行时无工具可用**，Agent 只能绕过（用 `search_cars` 近似），`trap-04` 理论上**永远无法按设计通过**。

**② 纪律停留在提示词，执行层未接线**

- 复杂护栏 `src/tools/guardrail.ts`（白名单 / 管理者专属 / fail-closed）**从未被加载**（见 §2.2）。
- CLAIM 验证器 `src/verify/completion.ts`（supported_by 真实存在 / scope 越界 / 缺口声明）**从未被加载**；运行时用的是扩展内的一套轻量 regex 验证器。
- 结论：**"纪律"没有在执行层闭环**，与红线#5"护栏在执行层不在提示词"直接矛盾。

**③ 面向用户看到的"PM 结论"部分是罐头文案**

- "棱镜结论"三链卡片与 CLAIM 的**结论文案 + supported_by 行号是硬编码**（[KanbanView.tsx L99-L131](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.tsx#L99-L131)）。
- 即：用户以为在看"PM 判断"，实际一半是**静态字符串**（详见 §3.3 图表真伪对照表）。

---

## 2. 议题二：Harness 是否够好

> Harness 应覆盖 8 层：编排循环 / 工具供给 / 上下文注入 / 护栏 / 验证 / 观测 / 并发与资源 / 评测与测试。逐层核验如下。

### 2.1 分层现状

| Harness 层 | 现状 | 结论 |
|---|---|---|
| 编排循环 | 复用 pi RPC（[pi_gateway.mjs](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs)） | 借用，非自建 |
| 工具供给 | 23 个业务工具，**缺 resolve_series/竞品/优先级** | 不全 |
| 上下文注入 | **硬编码常量**注入（银河E5/7650），无角色分流 | 坏（见 §3.1） |
| 护栏 | **执行层只有 3 条 regex**；`guardrail.ts` 未接线 | 弱 |
| 验证 | 运行时 regex 验证器；`verify/completion.ts` 未接线 | 弱 |
| 观测 | Langfuse 仅 pi 通用；Prism 层零埋点 | 无 |
| 并发与资源 | **无池上限/无排队/无限流**；同用户串行；单轮 300s | 缺 |
| 评测与测试 | 评测集已写、**从未批跑**；**零单测**，仅 smoke | 未启动 |

### 2.2 关键发现：一整层"建好没接线"的死代码

**决定性证据**：`prism-guardrails/index.ts` 的 import **只有两行**——

```ts
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
```
（[index.ts L15-L16](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L15-L16)）

因此以下**全部未进入运行时**：

| 死代码 | 本应提供 | 运行时实际 |
|---|---|---|
| [src/tools/guardrail.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/tools/guardrail.ts) | 只读白名单 + 管理者专属 + 参数含 SQL 拦截 + fail-closed | 未加载；执行层只有扩展内 3 条 regex |
| [src/verify/completion.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/completion.ts) | CLAIM 完整性 + 行 ID 存在性 + scope 越界 + 缺口声明 | 未加载；运行时另一套 regex |
| [src/verify/grounding.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/grounding.ts) / [reference.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/reference.ts) / [koubei_claims.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/koubei_claims.ts) | grounding 改写 / 引用核验 | 未加载 |
| [src/tools/query_*.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/tools) | TS 版语义工具（含 `group_by='spec'`） | 未加载；扩展改走 FastAPI HTTP 另有一套 |
| [src/identity/resolve.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/identity/resolve.ts) | 身份解析 + 覆盖率守卫 | **未加载且无对应工具**（见 §1.3①） |

**双重实现的长期风险**：同一个"query_sales"在 `src/tools/query_sales.ts`（TS，直连 SQLite）与扩展+FastAPI（HTTP，读物化视图）**各有一份**，运行时只认后者；前者漂移无人察觉（此前"N 段断点"正是这种漂移的产物）。

### 2.3 评测门禁形同虚设

- 评测体系**设计很完整**：16 题 + 4 条发版门槛（veto 零命中 / Wilcoxon p<0.05 / 保留集 CI / 成本 CI）（[EVAL_STATUS.md](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/EVAL_STATUS.md)）。
- **但台账明写"待首次批跑"，通过率/trap否决率/门槛全为"—"**，34 道用户题"未提交"。
- 评分器是**浅层正则关键词**：如 trap 拦截判据是 `/探索型/.test(reply)`、`/印证|佐证|支撑/.test(reply)`（[runner.mjs L46-L57](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/runner.mjs#L46-L57)）——**措辞一变即误判**，不能作为质量门禁。
- 结论：**有评测的样子，没有评测的效力**。

### 2.4 运行时保障缺口（前序报告已证，此处归并）

| 缺口 | 影响 |
|---|---|
| 无并发池上限/排队/限流 | 在线人数↑ → 进程数线性↑ → 可能 OOM |
| 同用户串行 + 直接报错 | 多标签页/连续提问被拒 |
| 单轮 300s 超时 | 长分析（实测曾 25min）被中断 |
| Prism 层零观测 | 护栏裁决/工具时延/口径不可审计 |
| `/chat/stream` 丢 `session_id`；`/ui-response` 未代理 | 多轮易断；确认弹窗链路断 |
| 零鉴权 | spec 的"管理者可编辑/~49人只读"未落地 |
| **运行态 ≠ 磁盘代码** | 网关 21:22 启动、代码 22:36 才改 → 实测的是旧逻辑 |

### 2.5 能否"保证正常运行"？——分场景

| 场景 | 能否保证 |
|---|---|
| 单人演示 / 少量内部试用 | **勉强可以**（能跑通、结论有 PM 味） |
| 40 人并发（spec 目标） | **不能保证**：无背压、无观测、无鉴权、单轮超时偏短 |
| 可信赖的生产交付 | **不能**：无测试门禁、评测未跑、护栏/验证未接线、运行态漂移 |

---

## 3. 议题三：前端 UI 与上下文注入

参考资源（仓库已有）：[hermes-agent-kanban.html](file:///c:/Users/<you>/Desktop/Prism-Agent/UI设计/hermes-agent-kanban.html)、[brand-spec.md](file:///c:/Users/<you>/Desktop/Prism-Agent/UI设计/brand-spec.md)（含 oklch 色板、Didone 字体栈、对比度实测）。

### 3.1 「他是谁」根因分析（P0 · 证据链完整）

**机制**：`before_agent_start` 钩子在**每一轮**把 `AGENTS.md`（PM 长 SOP）+ `SYSTEM.md`（角色约束）拼到 systemPrompt，占位符**全用常量**填充（[index.ts L377-L395](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L377-L395)）：

```ts
const filled = systemMd
  .replace('{series_key}', '银河E5')      // ← 写死
  .replace('{series_id}', '7650')         // ← 写死
  .replace('{mode}', '对话模式')
  .replace('{as_of}', new Date().toISOString().slice(0, 10))
  .replace('{warnings}', '无');
prompt += '\n\n' + filled;
```

对应 [SYSTEM.md L23-L28](file:///c:/Users/<you>/Desktop/Prism-Agent/SYSTEM.md#L23-L28) 的「当前会话上下文」块（对象/模式/as_of/数据缺口）。

**为什么被"复述"出来**（三因叠加）：

1. **无条件注入**：不论问"他是谁"还是"银河E5销量"，都塞同一段"对象=银河E5"，纯闲聊也被强绑汽车上下文；
2. **无"元数据禁止复述"指令**：该块以普通正文形态出现，模型无法区分"后台参数"与"要输出的内容"，于是照抄；
3. **PM 长 SOP 加重**：同钩子追加 `AGENTS.md`（棱镜三维度/报告纪律/CLAIM），强化"必须声明上下文"的倾向。

**与角色/模式缺陷同源**：同一钩子是**唯一的上下文/角色入口**，同时承担对象、模式、as_of、角色分流，且**全用常量**。修法须一并做：上下文**动态化**（对象由真实会话目标/`resolve_series` 决定）、**条件注入**（纯闲聊不注入）、**元数据隔离**（声明禁止整段复述）、**角色分流**（PM 走棱镜 SOP，普通用户走轻量助手）。

### 3.2 前端 UI 需求逐条映射（对标 HERMES）

| # | 用户诉求 | 现状（文件·行） | 缺口 |
|---|---|---|---|
| U1 | 新建会话复刻 HERMES「大字」效果 | 空会话态即 [ChatView.tsx](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/ChatView.tsx)，无 hero 空白态 | 缺：Didone 衬线大字 hero（brand-spec 已定义 `Bodoni Moda/Didot`）+ 引导语/示例问 |
| U2 | 左侧栏「产物」空白不合理 | [Sidebar.tsx L42](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L42) 无 onClick、无视图 | 需实装「产物」视图（分析报告/结论/导出物）或先移除 |
| U3 | 左侧栏「设置」空白不合理 | [Sidebar.tsx L43](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L43) 无 onClick、无视图 | 需实装设置页（模型/权限/偏好）或先移除 |
| U4 | 左侧栏加「SKILLS 库」，点击展开 | **无任何入口** | 需新增：侧栏项 + 展开面板 + **后端 skills 清单接口**（当前无） |
| U5 | 会话可自定义名称（像 HERMES） | [Sidebar.tsx L63-L67](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L63-L67) 仅展示，无重命名 | 需：行内重命名 UI + 后端 rename 接口（见 §3.5） |
| U6 | 删顶部：银河E5 / 搜索车系 / 日夜切换 | [App.tsx L37-L49](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.tsx#L37-L49) 三者皆**无功能**死元素 | 直接删除；对象选择改由会话管理承担 |
| U7 | 图表必须有对应数据 | 见 §3.3，**半数硬编码** | 每个图表须绑定真实接口或显式标注"演示" |
| U8 | 卢浮宫抽象成 logo | [App.tsx L35](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.tsx#L35) 现为 `<span className="prism-dot">` 圆点 | 见 §3.4 |

**侧栏其余问题**：

- **会话点击无跳转**：`sb-row`（[L63-L67](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L63-L67)）无 onClick → 列出的会话**打不开**。
- **「新建会话」不新建**：`onClick={() => onNavigate('chat')}`（[L36-L38](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L36-L38)）**只切视图**，未调 `POST /session`（后端其实支持，见 §3.5）。
- **「已置顶」永远为空**：`<ul className="sb-list" />`（[L56](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L56)）无数据源。
- **「车系」Tab 是假列表**：银河E5/零跑D19/铂智7X 硬编码（[L76-L78](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L76-L78)）。
- **会话名取文件名**：`{s.name || s.id.slice(0,12)}`（[L66](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L66)），后端列表 `name` 就是文件名 → **即使重命名也不显示**。
- **视图切换丢状态**：[KanbanView.tsx L14-L45](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.tsx#L14-L45) 每次切换重挂载；[App.tsx L60-L75](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.tsx#L60-L75) 看板↔对话互相卸载 → 对话内存态丢失。

### 3.3 图表数据真实性对照表（U7 核心）

> 判据：是否 `fetch` 真实接口 vs 硬编码常量数组。

| 视图 · 面板 | 数据来源 | 真实/假 | 证据 |
|---|---|---|---|
| 舆情（Board 外挂） | iframe 反代 `:8000` | **真实** | [SentimentBoard.tsx](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/SentimentBoard.tsx) |
| 销量 · 月度走势 | `GET /dashboard/sales` | **真实** | [MarketBoard.tsx L11](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/MarketBoard.tsx#L11) |
| 销量 · 版型结构 | 硬编码 `2047/1854/…` | **假（示例数据）** | [MarketBoard.tsx L43-L51](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/MarketBoard.tsx#L43-L51) |
| 销量 · 竞品对比 | 硬编码 理想L6/零跑D19/问界M7/岚图Free | **假（示例数据）** | [MarketBoard.tsx L54-L66](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/MarketBoard.tsx#L54-L66) |
| 车型配置 · 配置矩阵 | `GET /dashboard/config` | **真实** | [ConfigBoard.tsx L13](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ConfigBoard.tsx#L13) |
| 车型配置 · 赋分展示 | 硬编码 `55000元/2200元` | **假（示例数据）** | [ConfigBoard.tsx L69-L74](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ConfigBoard.tsx#L69-L74) |
| 口碑 · 维度聚合 | `GET /dashboard/reviews` | **真实** | [ReviewsBoard.tsx L15](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ReviewsBoard.tsx#L15) |
| 口碑 · 原文样本 | 硬编码 review_id | **假（示例数据）** | [ReviewsBoard.tsx L71](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ReviewsBoard.tsx#L71) |
| 口碑 · 趋势 | 硬编码 `[28,35,30,…]` | **假（示例数据）** | [ReviewsBoard.tsx L79](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ReviewsBoard.tsx#L79) |
| 棱镜结论 · 三链卡片 | 数字真实 fetch，**结论文案硬编码** | **半真** | [KanbanView.tsx L99/L105/L111](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.tsx#L99-L111) |
| 棱镜结论 · CLAIM | 硬编码文案 + **假 supported_by 行号** | **假** | [KanbanView.tsx L115-L131](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.tsx#L115-L131) |
| 看板栏 · as_of | 硬编码 `2026-10-04` | **假** | [KanbanView.tsx L32](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.tsx#L32) |
| 全局 · 分析对象 | 硬编码 `'银河E5'`（4 处） | **假** | [App.tsx L19](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.tsx#L19)、KanbanView L54/L61/L68 等 |

**结论**：`示例数据` 仅靠一个灰色小 chip 标注，与真实数据**并排同款渲染**，汽车 PM 极易误读——与全局红线#1（数据真实性）冲突。

### 3.4 Logo：卢浮宫抽象方向（设计指引，非实现）

- **意象**：贝聿铭玻璃金字塔（三角棱面 / 折射）——与品牌名 **Prism**（棱镜）天然同源。
- **抽象建议**：取**正三角**为骨架，内部 2–3 条棱线切成多面，交点汇聚于顶点形成"折射"暗示；单色 `--accent`（`#0053FC`）描边、**1.7px 线宽、currentColor、无填充**（合 [brand-spec.md](file:///c:/Users/<you>/Desktop/Prism-Agent/UI设计/brand-spec.md) 视觉规则第 4 条）；极小尺寸（16–20px）降为**实心单三角**；可与 `P` 字负形结合做 monogram。
- **替换点**：现 [App.tsx L35](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.tsx#L35) 的 `<span className="prism-dot">`、看板栏 `<Icon name="atom">`（[KanbanView.tsx L21](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.tsx#L21)）。

### 3.5 后端需配套的接口（UI 需求的前置依赖）

| UI 需求 | 后端现状 | 需要补 |
|---|---|---|
| 新建会话 | ✅ `POST /session` 支持 `new_session` + `title`（[main.py L185-L190](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L185-L190)、[pi_gateway.mjs L385-L407](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L385-L407)） | 前端接上即可（当前未调用） |
| 会话重命名 | ⚠️ 仅建会话时可传 `title`（走 `set_session_name`） | 补 **rename 接口**（对已有会话）；且 **list 必须返回自定义名**（当前 `name` = 文件名，[pi_gateway.mjs L373](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L373)） |
| SKILLS 库 | ❌ 无任何接口 | 新增 `GET /skills`（名称/说明/所属维度/启用状态） |
| 产物 | ❌ 无接口/无存储 | 定义"产物"数据模型（结论/报告/导出）与 `GET /artifacts` |
| 图表版型结构 | ✅ `/dashboard/sales?group_by=spec` 已可用（[main.py L88-L102](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L88-L102)） | 前端接上即可（当前用硬编码） |
| 竞品对比 | ❌ 未见接口 | 需 `get_competitors` 类接口或复用 search_cars |
| 口碑原文/趋势 | ⚠️ reviews 接口有聚合 | 需补"原文样本 + 时间趋势"字段 |
| 顶部对象/主题 | — | 删除即可，无需后端 |

---

## 4. 议题四：可观测性（Langfuse 核验 · 实测）

> 与"是否与 pi 脱勾"同题。证据为 **Langfuse 公开 API 实测（一手）** + 运行进程实测 + 插件源码核对。

### 4.1 服务与凭据现状（更正旧结论）

| 项 | 实测结果 |
|---|---|
| Langfuse 在跑 | ✅ `GET /api/public/health` → `{"status":"OK","version":"4.50.0"}` |
| 项目 | ✅ `prism-dev`（组织 `Prism-Agent`） |
| 插件已装 | ✅ `@langfuse/pi-observability-plugin` v0.1.2（`.pi/agent-minimal/npm/node_modules/`） |
| **key 已配置** | ✅ [langfuse.json](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/langfuse.json) 含 `publicKey/secretKey/baseUrl=http://localhost:3000` |

> **更正**：旧报告"Langfuse key 未配 → 不产出任何 trace"**已过时**。实测 key 已配、插件已装、trace 已在产出。

### 4.2 trace 实测内容

`GET /api/public/v2/observations?limit=100`（时间窗 13:41–14:03 UTC，全部来自同一次事故会话）：

| name | 数量 | 类型 |
|---|---|---|
| `LLM Call` | 38 | GENERATION |
| `Tool: bash` | **33** | TOOL |
| `Tool: query_sales` | 9 | TOOL |
| `Conversational Turn` | 7 | SPAN（根） |
| `test-span` / `manual-test-span` | 3 / 2 | 人工测试 |
| `Tool: sentiment_*` | 5 | TOOL |
| `Tool: query_config` / `get_sales_detail` / `mcp` | 各 1 | TOOL |

根 span `Conversational Turn` 的 `sessionId` 与 `.pi/sessions/usr_g5r6h5ye/2026-10-05T13-39-59-978Z_01a10c4a-...jsonl` **完全一致**，证明确为本次会话的 trace。

### 4.3 判读：有没有"Prism 领域层"？——**没有**

```
Trace 名  = "Pi Turn"                 ← 插件常量 TRACE_NAME
  根 span = "Conversational Turn"     ← 插件常量 ROOT_OBSERVATION_NAME
    ├─ "LLM Call"                     ← 模型调用（token/cost/时延）
    └─ "Tool: query_sales"            ← 业务工具，仅"作为 pi tool"被通用事件捕获
tags = ["pi"] ; metadata.source = "pi"
```

- 证据：插件源码 `TRACE_NAME`/`ROOT_OBSERVATION_NAME`/`BASE_TAGS=["pi"]`/`source:"pi"`（[插件 index.ts L20-L28 / L612-L618](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/npm/node_modules/@langfuse/pi-observability-plugin/src/index.ts#L20-L28)）。
- **业务语义未被结构化**：`series_key`、维度、`as_of`、覆盖率、CLAIM、scope **都不是 trace 的一等字段**，只能"埋"在 tool span 的原始 `input`/`output` JSON 里。
- **Prism 自有层零可观测**：`main.py` 与 `pi_gateway.mjs` 无埋点；护栏裸 SQL 拦截、grounding 改写、完成验证器否决**全部不可审计**。
- 旁证：存在 `test-span`(3)/`manual-test-span`(2) 人工 trace → 集成处于"刚接上、还在自测"阶段。

**一句话**：Langfuse 看到的是"**pi 的对话轮次 + 被 pi 抓到的工具调用**"，**不是 Prism 的分析领域模型**；要评 Prism 的分层/口径/护栏，必须另建埋点。

### 4.4 贯穿风险：磁盘代码 ≠ 运行代码（P0）

> 与 §2.4 末行同源，此处补实测：网关进程 **PID 79716 启动于 21:22:13**，而 `pi_gateway.mjs` 文件 mtime 为 **22:36:36**；Langfuse 里 `Tool: bash`×33 反证运行的是**未含 `--exclude-tools` 的旧代码**。→ **任何复测前必须先重启网关**；另有 10/4 起多个孤儿 `vite --port 5173` 进程（环境脏化）。

---

## 5. 统一收敛清单（Harness + PM + UI + 可观测性 合并，唯一优先级口径）

> 本清单**取代**《Prism-Agent-UI改造需求与上下文注入根因-2026-10-05.md》§6 与《Prism-Agent-可观测性与全栈深审报告-2026-10-05.md》§7；三份文档若遇优先级不一致，一律以本清单为准。

**P0 · 决定"能不能信"（先做）**
1. **接线**：把 [guardrail.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/tools/guardrail.ts)、[verify/completion.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/completion.ts)、[identity/resolve.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/identity/resolve.ts) 真正挂到扩展的 `tool_call` / `agent_settled` / 工具注册；统一或删除取数层的 TS vs HTTP 重复（见 §2.2）。
2. **补 `resolve_series` 工具**（红线#7 的必需工具，当前缺失）。
3. **修上下文注入**：对象/as_of 动态化、纯闲聊不注入对象块、声明"后台元数据禁止复述"、角色分流（§3.1 / 可观测 E1/E2）。
4. **删顶部三个死元素**（UI U6）+ **侧栏空壳项处置**（UI U2/U3：实装或下架）。
5. **图表接真数据**：硬编码面板要么接接口、要么显式"演示"态隔离（加显著水印或 dev-only），不得与真实数据同款并排（§3.3 / 可观测 §3.3）。
6. **让运行态与磁盘一致**：重启网关；加进程守护/就绪探针；清理孤儿 `vite` 进程（§2.4 / §4.4）。
7. **打通 `ui_request` 回填**：`main.py` 加 `/ui-response` 转发 + vite 代理，并明确确认策略（要么禁用"需确认"操作，要么放行），避免**卡住整轮**或**护栏被静默绕过**（可观测 §3.2 / B3）。

**P1 · 决定"好不好用"**
8. **跑通评测门禁**：批跑 16 题、补 34 题、把正则评分换成基于验证器判定；进 CI。
9. **加单测/集成测试**（当前仅 smoke）：覆盖工具口径、护栏拦截、验证器、身份解析。
10. **并发治理（40 并发未兑现 · 见 H10）**：现状=**每用户 1 个 `pi.exe` 常驻进程**（spec [§5.7](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-项目提纲.md#L200-L205)/[运行流程](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-运行流程.html#L250) 原话是"1-2 个进程异步跑多循环"，实现走成 per-user spawn → 40 活跃用户 = 40 个进程，内存是主要风险）；**无池上限/无排队/无背压/无限流**；同用户并发**直接报错**（非排队）；单轮 300s 一刀切。需补：池上限 + 排队 + 限流 + 可配超时；**并补做 40 并发压测**（spec §5.4/§9 早列、至今未执行）。
11. **建 Prism 自建观测层** + 护栏裁决**结构化审计事件**，与 pi 的 Langfuse trace 以 `session_id` 关联（§4.3 / 可观测 E3/B5/G5）。
12. **补鉴权/权限分层**（管理者 vs 只读）。
13. **SKILLS 库**：侧栏入口 + 展开面板 + `GET /skills`（UI U4）。
14. **会话重命名**：行内编辑 UI + rename 接口 + list 返回自定义名（UI U5）；会话列表**可点击切换**（列表已渲染，缺 `onClick`/切换逻辑，可观测 §3.4）。
15. **收窄工具集**：`--exclude-tools` 补上 `mcp`/记忆/子代理等非业务扩展（可观测 E4）。
16. **模式分流贯通**：网关消费 `scope` + `setActiveTools` 白名单（可观测 G4 / §2.1）。

**P2 · 体验与完备**
17. **新建会话 hero 大字态**（UI U1，用 Didone 字型）。
18. **Logo 卢浮宫金字塔抽象落地**（UI U8）。
19. 视图切换保活（避免卸载丢状态）。
20. 「产物」视图数据模型（§3.5）。
21. **前端小缺陷**：修 `args` 字段、删重复 `case 'tool_result'`、修 as_of 提取（可观测 F1/F2/F4）。
22. `/chat/stream` 透传 `session_id` + 补 `session_info` 事件（可观测 B2/F3）。
23. 视图库只读打开 + 清理残留 0 字节 `prism_views.db`（可观测 B4/B7）。
24. **密钥移出源码**（可观测 G6）。
25. 竞品对比 / 优先级建议 等 PM 推理工具；跨会话记忆。

---

## 6. 结论

- **"像汽车 PM"**：**形似而神未满**。三维度框架、口径纪律、假设范式是真功夫，**但推理层的工具与执行层闭环缺失**，导致它更像"一个纪律很严的数据查询助手"，而非"能替你想策略的 PM"。
- **Harness**：**设计 A、落地 C**。最致命的是**护栏/验证/身份解析/语义工具这一整套"执行层保障"没有接线**，加上无测试、评测未跑、无并发治理、无观测、运行态漂移——**当前不足以"保证正常运行"**，只适合小范围演示。
- **前端 UI**：有硬伤——空壳项、缺 SKILLS、会话不可重命名、顶部死元素、**半数图表为示例数据**；「他是谁」根因在**上下文硬编码注入**。
- **可观测性**：Langfuse 里**没有 Prism 领域层**（trace 命名/标签全为 pi），`prism-api`/`pi_gateway` **零埋点**——**Prism 与 pi 未脱勾**，且观测层 100% 依赖 pi 插件。
- **收敛判断**：优先做 **P0-1 接线 + P0-2 补 resolve_series**，这两件事能让"已有的设计"真正生效，是投入产出比最高的收敛点。

---

## 附录 A · 证据索引

### A.1 Harness / PM 推理

| 编号 | 证据 | 位置 |
|---|---|---|
| H1 | 扩展仅 import `node:fs`/`node:path`（上层模块全未加载） | [index.ts L15-L16](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L15-L16) |
| H2 | 实注册 23 工具，无 `resolve_series` | [index.ts L55-L237](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L55-L237) |
| H3 | 死代码：白名单/管理者专属/fail-closed 护栏 | [src/tools/guardrail.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/tools/guardrail.ts) |
| H4 | 死代码：CLAIM 验证器 | [src/verify/completion.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/completion.ts) |
| H5 | 评测集 16 题 + trap 设计 | [eval/tasks_v1.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/tasks_v1.ts) |
| H6 | 评测台账"待首次批跑"、门槛未跑 | [eval/EVAL_STATUS.md](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/EVAL_STATUS.md) |
| H7 | 评分器为浅层正则 | [eval/runner.mjs L46-L57](file:///c:/Users/<you>/Desktop/Prism-Agent/eval/runner.mjs#L46-L57) |
| H8 | 仅 smoke 脚本、无 test 门禁 | [package.json L7-L18](file:///c:/Users/<you>/Desktop/Prism-Agent/package.json#L7-L18) |
| H9 | golden 归因假设清单（PM 推理样本） | [工作⓪-E5端到端](file:///c:/Users/<you>/Desktop/Prism-Agent/工作⓪-E5端到端) |
| H10 | **40 并发未兑现**：实现为"每用户 1 个 `pi.exe`"（设计原话"1-2 进程异步"），`pool` 无上限；同用户并发直接拒绝（非排队）；单轮 300s；从未压测 | [pi_gateway.mjs L232-L266](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L232-L266)（per-user spawn + `pool` 无上限）、[L268-L278](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L268-L278)（30min 空闲回收）、[L317-L327](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L317-L327)（同用户直接拒绝）、[L179-L189](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L179-L189)（300s 超时）；设计 [项目提纲 §5.7](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-项目提纲.md#L200-L205)、[运行流程 L250](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-运行流程.html#L250) |

### A.2 前端 UI / 上下文注入

| 编号 | 证据 | 位置 |
|---|---|---|
| A1 | SYSTEM.md「当前会话上下文」块 | [SYSTEM.md L23-L28](file:///c:/Users/<you>/Desktop/Prism-Agent/SYSTEM.md#L23-L28) |
| A2 | 变量硬编码 + 每轮注入 | [index.ts L377-L395](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L377-L395) |
| A3 | 侧栏空壳项/假列表/无重命名 | [Sidebar.tsx L36-L88](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L36-L88) |
| A4 | 顶部死元素 | [App.tsx L33-L50](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.tsx#L33-L50) |
| A5 | 硬编码"示例数据"面板 | MarketBoard L43/L54 · ConfigBoard L69 · ReviewsBoard L71/L79 · KanbanView L32/L99-L131 |
| A6 | 后端已有 new/rename 能力（list 不用自定义名） | [main.py L185-L190](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L185-L190)、[pi_gateway.mjs L373/L385-L407](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L373-L407) |
| A7 | HERMES 参考与品牌契约 | [hermes-agent-kanban.html](file:///c:/Users/<you>/Desktop/Prism-Agent/UI设计/hermes-agent-kanban.html)、[brand-spec.md](file:///c:/Users/<you>/Desktop/Prism-Agent/UI设计/brand-spec.md) |
| A8 | 会话日志（含"你是谁"轨迹） | [.pi/sessions/usr_g5r6h5ye](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/sessions/usr_g5r6h5ye) |

### A.3 可观测性（实测）

| 编号 | 证据 | 来源 |
|---|---|---|
| L1 | Langfuse health `{"status":"OK","version":"4.50.0"}`；项目 `prism-dev` | `GET /api/public/health`、`/api/public/projects` |
| L2 | 100 条观测统计（`LLM Call`38 / `Tool: bash`33 / `Tool: query_sales`9 / `Conversational Turn`7 …） | `GET /api/public/v2/observations?limit=100` |
| L3 | 根 span `Conversational Turn`，`sessionId=01a10c4a-…`（与事故会话一致） | 同上 |
| L4 | 插件 trace 命名/标签常量（`Pi Turn` / `Conversational Turn` / `tags=pi` / `source=pi`） | 插件 [src/index.ts L20-L28](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/npm/node_modules/@langfuse/pi-observability-plugin/src/index.ts#L20-L28) |
| L5 | key 已配，读取路径 `agentDir/langfuse.json` | [langfuse.json](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/langfuse.json) |
| R1 | 网关进程 PID 79716 启动 21:22:13；文件 mtime 22:36:36 | `Get-CimInstance Win32_Process`；`Get-Item` |
| R2 | 9100 健康 `poolSize=4`；8002 健康 `prism_views_tables=6` | 实测 HTTP |
| R3 | `--exclude-tools` 为 pi 合法 flag（denylist，覆盖内置+扩展工具） | `pi --help` 实测 |