# Prism-Agent · 全栈深度审查（全链路 / 架构 / 前端 UI / 前端交互）· 2026-10-06

> 审查日期：2026-10-06
> 审查根目录：`c:\Users\<you>\Desktop\Prism-Agent`
> 性质：**只读审查，未改动任何代码**
> 方法：四路并行子代理取证（全链路 / 架构 / UI / 交互）+ 关键项人工抽验
> **重要前提**：本项目《收敛执行总计划》**已大部分落地**——本报告基于**当前运行态**，此前针对"计划"的审查结论**多数已过时**（见 §0.2）。

---

## 0. 结论摘要

### 0.1 一句话
**"设计 ≫ 落地"的核心病灶已大幅改观**：身份核验（`resolve_series`）、身份端点（`/identity/resolve`）、UI 回填（`/ui-response`）、埋点端点（`POST /events`）、参数逐层透传、会话切换 **均已实现**。当前遗留问题从"没接线"转为**"接了但不够深 / 不够全"**：观测事件映射不全、身份注入用 prompt 文本前缀、前端演示数据混入真看板、交互缺"停止生成/点踩"、无路由。

### 0.2 相对本线程此前结论的反转（重要）
| 此前判断 | 当前实际 | 证据 |
|---|---|---|
| `resolve_series` 未注册 | **已注册** | 扩展 [index.ts L22-L33](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L22-L33)、[L122-L146](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L122-L146) |
| 无 `/identity/resolve` | **已存在** | [main.py L579-L676](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L579-L676) |
| 无 `/ui-response` 回填 | **已存在** | [main.py L378-L391](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L378-L391) |
| 无 `POST /events`（埋点） | **已存在**（写 SQLite events 表） | [main.py L96-L135](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L96-L135) |
| `series_key/scope` 未透传 | **已逐层透传** | [main.py L307-L332](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L307-L332) |
| 会话列表不可点 | **可点击切换 + 双击重命名** | [Sidebar.tsx L29-L60](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L29-L60) |

> 结论：**不要再拿旧结论当判据**；以本报告为准。

---

## 1. 全链路审查（当前态）

链路：`prism-web` (React) → `prism-api/main.py` (FastAPI) → `pi_gateway.mjs` (Node) → `pi.exe` → 扩展 → 语义工具/DB。

**已打通（确认）**：前端 `sendChat` 传 `scope/user_id/session_id/series_key`（[chat.ts L16-L31](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/lib/chat.ts#L16-L31)）→ main.py `/chat/stream` 透传（[L307-L332](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L307-L332)）→ gateway 拼 `[ctx: series_key=…, scope=…]` 前缀并入 prompt（[pi_gateway.mjs L344-L352](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L344-L352)）→ 扩展注册工具并实现 `resolve_series`（→`/identity/resolve`）。vite 代理已含 `/chat/stream`/`/ui-response`/`/events`/`/identity`（[vite.config.ts L13-L29](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/vite.config.ts#L13-L29)）。

**仍存断点 / 风险**：

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| L1 | 🔴 | `mapEvent` 只映射 `message_update`/`tool_execution_start\|end`/`agent_start`/`agent_settled`/`extension_error`/`aborted`/`ui_request`；**遗漏** `turn_*`/`message_start`/`agent_end`/`session_*`/`tool_call`——而埋点与轨迹采集正依赖这些 | [pi_gateway.mjs L42-L85](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L42-L85) |
| L2 | 🔴 | 身份上下文以 **prompt 文本前缀** `[ctx: …]` 注入（非结构化字段/非 system 级）→ 与计划要求的"条件注入 / 闲聊不注入 / 禁复述"目标冲突；模型可见，可能被复述 | [pi_gateway.mjs L344-L352](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L344-L352) |
| L3 | 🟡 | `/autohome/{tool_name}` 白名单（`AUTOHOME_TOOL_MAP`）若与扩展注册工具不一致 → 404 断点 | [main.py L539-L561](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L539-L561) |
| L4 | 🟡 | `/health` 双份、口径不一：main.py 只返回 SQLite 表数，gateway 另有健康探针 | [main.py L566-L573](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L566-L573) |

---

## 2. 整体架构审查

### 2.1 重复实现（漂移风险）
- **取数语义层**：扩展内联 `query_reviews/sales/config`（走 FastAPI `/dashboard/*`）[index.ts L74-L103](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L74-L103) **vs** `src/tools/query_*.ts`——两套语义层并存，口径易漂移。
- **验证器**：扩展内联完成验证器（查 `supported_by`/`as_of`）[L363-L389](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L363-L389) **vs** `src/verify/*`（数值 grounding [grounding.ts L53-L79](file:///c:/Users/<you>/Desktop/Prism-Agent/src/verify/grounding.ts#L53-L79)）——逻辑重复。

### 2.2 硬耦合（与 pi 本体）
spawn 处硬编码 `--mode rpc`/`--model`/`--exclude-tools`/扩展路径/`PI_CODING_AGENT_DIR`/`MEM0_API_KEY`：[pi_gateway.mjs L251-L288](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L251-L288)。

### 2.3 结构性风险
- **每用户一常驻进程 + 池无上限 + 同用户锁直接拒绝**（非排队）→ 40 并发不保证。
- **300s 一刀切超时**（`PRISM_TURN_TIMEOUT`）→ 长分析被腰斩：[L191-L210](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L191-L210)。
- 崩溃自动 respawn（容错有，但无背压）[L110-L123](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L110-L123)。

### 2.4 配置
`.pi/agent-minimal/settings.json` 已装载全套插件（permission-system / cc-safety-net / langfuse / ask-user-question 等）[L2-L18](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/agent-minimal/settings.json#L2-L18)——与旧状态文档（2026-10-04"全没装"）不一致，**已更新**。

### 2.5 设计亮点
数据源强制只读（`readonly: true`，[datasource.ts L72-L93](file:///c:/Users/<you>/Desktop/Prism-Agent/src/registry/datasource.ts#L72-L93)）；护栏/fail-closed 已有；前端视图保活。

---

## 3. 前端 UI 审查

### 3.1 视图/看板清单
`KanbanView` 五 tab：overview / sentiment / config / reviews / sales（[L12-L45](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.tsx#L12-L45)），分别渲染 `OverviewBoard`/`SentimentBoard`/`ConfigBoard`/`ReviewsBoard`/`MarketBoard`；舆情页为 iframe 嵌 `/sentiment-board/`（[SentimentBoard.tsx L5-L20](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/SentimentBoard.tsx#L5-L20)）。

### 3.2 真数据 vs 演示数据（逐项）
| 位置 | 判定 | 证据 |
|---|---|---|
| 销量-月度零售 | ✅ 真数据 | [MarketBoard L62-L72](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/MarketBoard.tsx#L62-L72) |
| 销量-版型结构 | ⚠️ **演示数据**（`demo-watermark`） | [MarketBoard L74-L83](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/MarketBoard.tsx#L74-L83) |
| 销量-竞品对比 | ⚠️ **演示数据**（硬编码 4 行） | [MarketBoard L86-L99](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/MarketBoard.tsx#L86-L99) |
| 口碑-维度聚合 | ✅ 真数据 | [ReviewsBoard L88-L95](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ReviewsBoard.tsx#L88-L95) |
| 口碑-舒适 con 样本 | ⚠️ **演示数据**（硬编码 review_id） | [ReviewsBoard L99-L106](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ReviewsBoard.tsx#L99-L106) |
| 口碑-口碑趋势 | ⚠️ **演示数据**（硬编码数组） | [ReviewsBoard L108-L110](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ReviewsBoard.tsx#L108-L110) |
| 配置-矩阵/赋分 | ✅ 真数据（`KEY_ITEMS` 为展示列常量） | [ConfigBoard L48-L144](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ConfigBoard.tsx#L48-L144) |
| 结论-CLAIM 卡片 | ⚠️ 数字取自接口，**结论文案硬编码模板** | [KanbanView L97-L130](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.tsx#L97-L130) |

> 判定：演示数据**均已标注 `demo-watermark`/meta="演示数据"**，非欺骗；但**与真数据同屏**，PM 易误读。红线#1"不编造数字"被"标注"缓解，仍建议演示卡与真数据**物理分区**或**默认折叠**。

### 3.3 UI 其它问题
- **证据源硬编码车系**：月度零售点击证据 `src: 'mv_sales_monthly:series=银河E5/…'` 写死银河E5，与动态 `series` 不一致 → 换车系后证据行错。[MarketBoard L67](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/MarketBoard.tsx#L67)
- 顶部栏仅 Logo + `SeriesCombobox` + spacer（[App.tsx L43-L50](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.tsx#L43-L50)）；早前"产物/设置空壳"在**当前顶部已不见**（现状已变）。
- 状态栏"数据源就绪"为**静态文案**，非来自 `/health`（[App.tsx L84-L90](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.tsx#L84-L90)）。
- 基础可访问性已覆盖（`role="tablist"`/`aria-selected`/`aria-label`），但深度对比度/键盘可达未系统验证。

---

## 4. 前端交互审查

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| I1 | 🔴 | **无"停止生成/取消"**：`handleSend` 无 abort；流异常或无 `settled` 时前端持续等待 | [ChatView.tsx L72-L160](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/ChatView.tsx#L72-L160) |
| I2 | 🔴 | **无路由**：`view` state 切换，刷新/回退不恢复 URL 状态 | [App.tsx L19-L58](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.tsx#L19-L58) |
| I3 | 🟠 | 反馈仅"👍 采纳"，缺 **点踩 / 复制 / 重试** | [ChatView.tsx L213-L220](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/ChatView.tsx#L213-L220) |
| I4 | 🟠 | 流式用 `fetch` 读响应流（非 EventSource），**无显式超时/取消** | [chat.ts L16-L67](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/lib/chat.ts#L16-L67) |
| I5 | 🟡 | 消息列表 `key={i}` → 流式追加时 React 复用风险 | [ChatView.tsx L184-L219](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/ChatView.tsx#L184-L219) |
| I6 | 🟡 | `initialMessage` useEffect 仅清 timer，输入态清理依赖卸载 | [ChatView.tsx L62-L70](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/ChatView.tsx#L62-L70) |

**已实现**：会话列表点击切换 + 双击重命名（[Sidebar L29-L60](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L29-L60)）；`ui_request` 回填（chat.ts 侧 `respondUi`）；视图保活。

---

## 5. 覆盖缺口（相对设计）

1. **观测/埋点事件不全**（§1 L1）：`/events` 端点已建、前端埋点已有，但 **pi hook 层事件未映射进流** → 产品北极星（周成功交付结论数）与 badcase 轨迹仍**采不全**。
2. **交互完备度**（§4 I1/I3）：缺停止生成、点踩、重试。
3. **架构重复未收敛**（§2.1）：TS vs HTTP 语义层、verify vs 内联验证器。

---

## 6. 收敛判定

- **已审计面**：全链路（前端→api→gateway→extension→tools→DB）、整体架构（边界/耦合/配置/风险/死代码面）、前端 UI（5 看板 + 逐图真伪 + 空壳 + 样式/a11y）、前端交互（导航/流式/会话/状态/反馈/输入/竞态）——**全部覆盖**。
- **证据强度**：关键项已人工抽验（MarketBoard/ReviewsBoard/App.tsx 已逐行确认）；其余为子代理核对，标注了行号可复核。
- **无新的未审计面**；剩余均为**实施项**，不存在"待查"。
- **本轮判定：收敛。**

### 建议优先级（供拍板，非缺陷）
1. **P0**：补 `mapEvent` 事件映射（观测/埋点/轨迹的前提）；前端加"停止生成"。
2. **P1**：身份注入改为**结构化 system 级**（而非 prompt 前缀）；演示数据与真数据分区；证据 src 车系动态化。
3. **P2**：前端引入路由；补点踩/重试/复制；收敛 TS vs HTTP 重复层。