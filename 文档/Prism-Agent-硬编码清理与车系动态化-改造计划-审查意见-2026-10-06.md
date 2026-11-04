# Prism-Agent ·《硬编码清理 + 车系动态化改造计划》审查意见 · 2026-10-06

> 审查日期：2026-10-06
> 审查对象：[Prism-Agent-硬编码清理与车系动态化-改造计划.md](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-硬编码清理与车系动态化-改造计划.md)（**未改动计划、未改动代码**）
> 性质：**只读审查**（对"计划"的审查）
> 方法：逐条核验计划的 4 项诊断 + A–F 改动 + 验收 8 条，全部对照当前源码

---

## 0. 结论摘要

**计划核心根因判断正确**：`App.tsx` 有 `series` state 但**没传给 `KanbanView`**（已核验 [App.tsx L65](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.tsx#L65) 确实缺 `series` prop）——这是"看板不随车系变"的真根因，抓得准。

**但有 1 个致命遗漏 + 2 处诊断证据错标 + 3 处需收敛 + 3 处小问题**：

| 级别 | 数量 | 问题 |
|---|---|---|
| 🔴 致命 | 1 | **`prism-web/src` 下存在全套 `.js` 幽灵副本**，Vite 可能加载 `.js` 而非 `.tsx` → 改 `.tsx` 可能完全不生效 |
| 🔴 诊断失真 | 2 | 计划的 `KanbanView.tsx:53`、`ConfigBoard.tsx:118/127` 硬编码证据**实际是 `.js` 内容**；对应 `.tsx` 已是动态 |
| 🟠 需收敛 | 3 | C 节 `DemoCard` 已存在；F 节属功能新增非"清理"；D 节未定义对话侧 fail-closed |
| 🟡 小问题 | 3 | "不做"对 mapEvent 判断与全栈审查冲突；E 节已部分完成；验收缺前置 |

> **建议**：先做"防 0（清幽灵 `.js`）"→ 据**修正后的诊断**（§2）再施工。否则验收会"改了没反应"。

---

## 1. 🔴 致命遗漏：`prism-web/src` 下的 `.js` 幽灵副本（计划未覆盖）

**现象**：`src` 下与每个 `.tsx/.ts` 同名的 `.js` 副本共 **17 个**（`main.js`、`App.js`、`components/*.js`、`lib/chat.js`、`dashboard/*.js` 等）。

**机制（会不会被加载）**：
- 入口 [index.html L11](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/index.html#L11) 明确加载 `/src/main.tsx` ✓；
- 但 [main.tsx L10](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/main.tsx#L10) 是 **无扩展名导入** `import App from './App'`；
- [vite.config.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/vite.config.ts#L8-L10) **未自定义 `resolve.extensions`** → 用 Vite 默认顺序 `.mjs,.js,.mts,.ts,.jsx,.tsx,.json`，**`.js` 排在 `.tsx` 之前**；
- [tsconfig.json](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/tsconfig.json) 无 `noEmit`，而 `build` 脚本为 `tsc -b && vite build` → **`tsc` 会在源码目录原地生成 `.js`**（幽灵来源）。

**后果**：按上述顺序，`./App` 极可能解析到 **`App.js`（旧编译产物）**，`dev` 跑的是含硬编码 `银河E5` 的旧 `.js`。→ **计划只改 `.tsx`，验收（选海豚→看板变海豚）很可能不生效**。

**必须补做（防 0）**：
1. 删除 `prism-web/src/**/*.js` 全部 17 个幽灵文件；
2. 给 [tsconfig.json](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/tsconfig.json) 加 `"noEmit": true`，`build` 用 `tsc -b --noEmit && vite build`（或显式 `outDir` 到 `dist`）；
3. 验收**新增前置项**：浏览器 Network 确认加载的是 `.tsx`（`main.tsx`/`App.tsx`），而非 `.js`。

---

## 2. 🔴 诊断证据错标：部分行号实为 `.js`，对应 `.tsx` 已是动态

计划"问题2/问题4"中的两处证据，经核对**指向的是 `.js` 内容**，`.tsx` 本身**已经是动态的**：

| 计划表述 | `.tsx` 实际 | `.js`（幽灵，含硬编码） |
|---|---|---|
| `KanbanView.tsx:53` OverviewBoard 三个 useQuery 硬编码银河E5 | [L53-L73](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.tsx#L53-L73) **用 `series` 变量**（`queryKey:['reviews',series]`、`encodeURIComponent(series)`）——已动态 | `KanbanView.js:18-34` 硬编码 `'银河E5'` |
| `ConfigBoard.tsx:118/127` `src: 'config:series=银河E5/…'` | [L118/L127](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ConfigBoard.tsx#L116-L129) 是 `` `config:series=${series}/…` ``——已动态 | `ConfigBoard.js:85/89` 硬编码 `'银河E5'` |

> 说明：作者很可能读到了 `.js` 却标了 `.tsx` 行号——**这正是 §1 幽灵文件造成的认知污染**。→ 计划应在"防 0"后**重做诊断**。

**修正后的真实硬编码清单（仅 `.tsx`）**：
- **默认参数** `= '银河E5'`：`MarketBoard.tsx:8`、`ReviewsBoard.tsx:37`、`ConfigBoard.tsx:48`、`KanbanView.tsx:14`、`KanbanView.tsx:52`（OverviewBoard）
- **证据 src**：仅 `MarketBoard.tsx:67` `'mv_sales_monthly:series=银河E5/year=2026'`（唯一 `.tsx` 真硬编码 src）
- **CLAIM 卡片**：`KanbanView.tsx:118/123/127`（`银河E5` + `7650` + `79311`）✓
- **状态默认值**：`App.tsx:24` `useState('银河E5')` ✓
- **建议问题兜底**：`ChatView.tsx:176` `SUGGESTIONS(series || '银河E5')` ✓（`SUGGESTIONS` 已是函数）

---

## 3. 计划正确之处（已逐条确认，无需改）

- **问题1 根因**：`App.tsx L65` 未把 `series` 传给 `KanbanView` ✓ —— 这是看板不随车系变的真因。
- 默认值硬编码清单（四组件 + OverviewBoard）✓。
- `KanbanView.tsx:118/123/127` CLAIM 卡硬编码 `银河E5/7650/79311` ✓。
- `MarketBoard.tsx:67` 证据 src 硬编码 ✓。
- `App.tsx:24`、`ChatView.tsx:176` ✓。
- Sidebar 存在"会话/车系"两 tab（[L66-L67](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L66-L67)），车系 tab 内容为空态"暂无最近车系"（[L131-L136](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L131-L136)）✓。
- A/B/D/E 的**改造方向**正确，改动文件清单基本准确。

---

## 4. 需收敛项（3）

### 🟠 4.1 C 节：`DemoCard` 已存在，应"改用"而非"新增"
[MarketBoard.tsx L3](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/MarketBoard.tsx#L3) 已 `import { DemoCard, … } from './_shared'` → `_shared` **已导出 `DemoCard`**。计划 C 节"`_shared.tsx`：加 `DemoCard` 组件"应改为"让四张演示卡改用**已存在的** `DemoCard`"。
（另注：`_shared.js` 也在幽灵清单中，同 §1 处理。）

### 🟠 4.2 F 节：属"功能新增"，非"硬编码清理"（scope creep）
侧栏"车系"tab 实装 + `localStorage` 最近车系 + 搜索接 `/identity/resolve` —— 是**净新增功能**，与文档标题"硬编码清理与车系动态化"的"清理"部分不同源。建议：**单列为一节或移出本轮**，避免与清理工作混在一个 change 里。

### 🟠 4.3 D 节：默认 `series` 改空后，**对话侧**行为未定义
计划只写了"看板空态（`enabled: !!series`）"，但**未定义对话侧**：`series` 为空时 `chat.ts` 仍会带空 `series_key` → 网关拼出 `[ctx: series_key=, scope=…]`，而扩展 [T-2.5 L591-L597](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L591-L597) 是"**series_key 非空时**才 fetch `/identity/resolve`"→ **空值可能绕过 fail-closed**，与红线#7"对象身份前置核验"冲突。
→ 需补：**未选车系时，对话入口应拦截并提示"请先选车系"**（或发问前强制 `resolve_series`），而非放空值进链路。

---

## 5. 🟡 小问题（3）

1. **"不做"对 `mapEvent` 的判断与本项目其它审查冲突**：计划写"L1 mapEvent 事件不全（**实际不影响功能**，留 v2）"。但 `mapEvent` 缺 `turn_*`/`agent_end`/`session_*` 直接影响**埋点 / 北极星 / badcase 轨迹采集**（见[全栈深度审查 §1 L1](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-全栈深度审查-2026-10-06.md)）。建议改措辞为"**已知缺口，属观测域，非本计划范围**"，而非"不影响功能"。
2. **E 节已部分完成**：`ChatView.tsx:176` 已是 `SUGGESTIONS(series || '银河E5')`（函数化已做），仅剩**兜底 `'银河E5'`** 待去（改为通用文案）。
3. **验收缺前置项**：8 条验收无"先确认浏览器加载 `.tsx`（非 `.js`）"（见 §1）。另建议补一条"`prism-web/src` 下无残留 `.js`"。

---

## 6. 收敛判定

- **已核验**：计划的 4 项诊断、A–F 全部改动点、验收 8 条，**逐条对照当前源码**；关键证据（`App.tsx:65`、`KanbanView.tsx:52-73`、`ConfigBoard.tsx:116-129`、`MarketBoard.tsx:3/8/67`、`main.tsx:10`、`vite.config`、`tsconfig`）均已人工逐行确认。
- **结论**：计划**方向正确、根因准确**，但**必须补 §1（幽灵 `.js`）并据 §2 重做诊断**后才能施工；§4.2、§4.3 需先拍板。
- **无新的未核项 → 本轮收敛。**

---

## 附：建议的修订后执行顺序

| 序 | 事项 | 说明 |
|---|---|---|
| **防 0** | 清 `src/**/*.js` 幽灵 + `tsconfig noEmit` + 验证加载 `.tsx` | **新增，前置** |
| **诊断重做** | 据 §2 修正硬编码清单（剔除误标为 `.tsx` 的 `.js` 项） | 修正 |
| 1 | A：`KanbanView` 接 `series` prop 全链路打通 | 不变 |
| 2 | B：CLAIM 卡片动态化（118/123/127） | 不变 |
| 3 | C：四张演示卡**改用已存在的** `DemoCard` | 澄清 |
| 4 | D：默认空 series + **补对话侧拦截**（§4.3） | 补 |
| 5 | E：去 `ChatView:176` 兜底 `'银河E5'` | 澄清 |
| 6 | F：车系 tab 实装 | **确认是否本轮**（§4.2） |

---

# 附：v2 复审（第 2 轮）· 2026-10-06

> 复审对象：[改造计划 v2](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-硬编码清理与车系动态化-改造计划.md)
> 结论：**v1 的 7 条意见已全部吸收且修订到位**；本轮对 v2 自身新增断言取证，得 **1 🔴 + 2 🟠 + 2 🟡**，全部可复现 → 收敛

## W0. v2 修订确认（正面）
- §1 幽灵 `.js`、§2 诊断错标剔除、§4.1 DemoCard、§4.2 F 单列、§4.3 对话侧、§5.1/§5.2/§5.3 —— **均已按意见改到位**。
- 复核为真：`DemoCard` 确在 [`_shared.tsx:52`](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/_shared.tsx#L52)（v2 引用准确）；`SUGGESTIONS` 确已函数化（[ChatView.tsx:33](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/ChatView.tsx#L33)）；**17 个 `.js` 全部有 `.ts/.tsx` 对应**、**无任何显式 `.js` 导入** → 删除安全 ✓。

## W1. 🔴 防 0 改动 4 会打破 v2 自己的验收

v2 防 0 改动 4：`main.tsx` 改 `import App from './App.tsx'`（显式扩展名）。
但 [tsconfig.json](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/tsconfig.json) **无 `allowImportingTsExtensions`**（已全量 grep `tsconfig*.json`，零命中）。→ 带 `.tsx` 扩展名的导入会报 **TS5097**（"An import path can only end with a '.tsx' extension when 'allowImportingTsExtensions' is enabled"）→ **直接违反 v2 的"验收 0 / 验收 8：`npx tsc --noEmit` 零错误"**。

**改法（二选一）**：
- **推荐**：**删除改动 4**——清掉 `.js` 后，无扩展名 `./App` 即解析到 `App.tsx`，本无需改；
- 或保留改动 4 时，**必须同时**在 tsconfig 加 `"allowImportingTsExtensions": true`（其要求 `noEmit`，与 v2 已有改动 2 兼容）。

## W2. 🟠 D 的"extension 兜底阻断"不是真阻断

v2 拟改：`before_agent_start` 中 `if (!seriesKey) { return { systemPrompt: '对象未确认…' + prompt } }`。
实测该 hook 现有实现 [index.ts L633](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L631-L646)：
- 已对空 `seriesKey` 给出 `warningsText='对象未确认，分析前请先 resolve_series'`，并以 `return { systemPrompt: prompt }` 返回——**v2 的写法与之重复**；
- 且"往 systemPrompt 拼一句话"**只是提示词，不是阻断**：模型仍可继续调工具、给结论。**与红线#5"护栏在执行层不在提示词"相悖**。

**改法**：真 fail-closed 应在 `seriesKey` 为空时**收缩工具集或拒答**——如 `pi.setActiveTools([])`（或仅 `resolve_series`），而非拼提示词。前端 A 层禁用发送也要配合。

## W3. 🟠 验收 0 的命令在 Windows 下不可用

`find prism-web/src -name "*.js"` 是 **Unix 命令**；本机为 Windows（PowerShell），`find` 不是 GNU find（会报错或误行为）。
**改法**：`Get-ChildItem -Path prism-web/src -Recurse -Filter *.js`（或 `Select-String`/`dir /s /b`）。

## W4. 🟡 §B "series_id 从 useQuery 结果取" 取不到

复核 [main.py dashboard](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L236-L290)：
- reviews 行字段是 **`model_id`**（非 `series_id`）；config 行**含 `series_id`**；`_meta` 只有 as_of/source/coverage/口径，**无 series_name/series_id**。
→ §B "series_id 从 revData/salesData/configData 取"对 reviews/sales **不成立**。**改法**：`series_id` 应来自 `resolve_series`（`/identity/resolve` 已返回），或仅 config 从行取。

## W5. 🟡 `tsc -b --noEmit` 备选不可靠

v2 防 0 改动 3 给了备选 `tsc -b --noEmit`。`-b`（build 模式）历史上**忽略 `--noEmit`**（配置非 composite 时更如此，本 tsconfig 无 `composite`）。
**改法**：只保留确定可用的 `tsc --noEmit && vite build`。

## W6. 收敛判定（第 2 轮）

- **已核验**：v2 全部修订项 + 防 0 改动 1–4 + 修正后硬编码清单 + D 对话侧 + 验收 0–8，逐条对照源码；`tsconfig*.json` 全量 grep、17 `.js` ↔ 17 `.tsx` 配对、显式 `.js` 导入扫描、`_shared.tsx` 导出、`SUGGESTIONS`、extension hook 返回形态、dashboard 响应字段——**均已人工确认**。
- **结论**：v2 方向与主体正确；**仅需修 W1（必改）+ W2/W3（应改）+ W4/W5（小）** 即可施工。
- **无新的未核项 → 收敛。**

---

# 附：v3 复审（第 3 轮）· 2026-10-06

> 复审对象：[改造计划 v2](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-硬编码清理与车系动态化-改造计划.md)
> 本轮方法：**逐条对照 `.tsx` 现状 + 同名 `.js` 幽灵逐一比对**（新增比对维度）
> 结论：**发现一处严重度错位（Z0，计划 A/C 两节已被 `.tsx` 现状覆盖）+ 一处漏列硬编码（Z1）**→ 需重定位后再施工

## Z0. 🔴 严重度错位：计划的 A / C 两节**在 `.tsx` 里已完成**，只是被幽灵 `.js` 掩盖

**实测（`.tsx` 现状 vs 同名 `.js` 幽灵）**：

| 计划条目 | 计划措辞 | `.tsx` 现状（源码实测） | 同名 `.js`（幽灵/旧版） |
|---|---|---|---|
| **A.1** `App.tsx:65` 加 `series` prop | "（加 prop）" | **已有** `series={series}`（[App.tsx L65](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.tsx#L65)） | [App.js L34](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.js#L34) **无 series** |
| **A.2** `KanbanView` 签名 + 下发四 Board | "签名加 `series`，传给…" | **已有** `series?: string` + 4 处下发（[KanbanView.tsx L14](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.tsx#L14) / [L41-L45](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.tsx#L41-L45)） | [KanbanView.js L11](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.js#L11)/[L44](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.js#L44) **无 series** |
| **C** 四张演示卡改用 `DemoCard` | "改用已存在的 `DemoCard`" | **已用** `<DemoCard>`（[MarketBoard.tsx L74](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/MarketBoard.tsx#L74-L82)/[L85](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/MarketBoard.tsx#L85-L97)、[ReviewsBoard.tsx L99](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ReviewsBoard.tsx#L99-L105)/[L107](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ReviewsBoard.tsx#L107-L109)） | — |

**机制闭环**：[main.tsx L10](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/main.tsx#L10) `import App from './App'`（无扩展名）+ [vite.config.ts](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/vite.config.ts#L8-L12) **未自定义 `resolve.extensions`**（默认 `.js` 优先于 `.tsx`）→ 运行时加载的是**旧 `App.js`**（无 series）→ 整条 series 链路被旧 `.js` 掐断。

**推论（关键，改变计划定位）**：
- **"看板不随车系变"的唯一原因是"加载了旧 `.js`"，不是 `.tsx` 缺代码**。→ **一旦"防 0"完成（删 17 个 `.js`），A 与 C 自动生效**，验收 1（选海豚→四看板变海豚）与验收 3（演示卡折叠）**即应通过**。
- **"防 0"不是"前置"，而是本计划的"主修复"**；A/C 应从"待施工"改判为 **"已实现待验证"**。
- v2 把 A 标为"根因修复"、把防 0 标为"前置"，**严重度排序倒置**——应在正文中纠正，否则会重复施工已完成项。

## Z1. 🔴 计划漏列一处真硬编码：`ReviewsBoard.tsx:71`

[ReviewsBoard.tsx L71](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ReviewsBoard.tsx#L71)：
```
src: `review_tags:model_id=7650/tag_category=${r.tag_category}`
```
—— `model_id=**7650**` 写死（仅 `tag_category` 是动态）。v2 §2"修正后的真实硬编码清单"只列了 `MarketBoard.tsx:67` 与 `KanbanView.tsx:118/123/127`，**漏了这一处**。→ 应补入清单并纳入清理范围（属 A/B 同类：证据 src 动态化）。

## Z2. 复核 v2 清单（`.tsx` 全量 grep `银河E5|7650|79311` 确认）

命中行（仅 `.tsx`）：`App.tsx:24`、`ChatView.tsx:176`、`KanbanView.tsx:14/53`（默认参数）、`KanbanView.tsx:118/119/123/127/129`（CLAIM 卡）、`MarketBoard.tsx:8`、`ConfigBoard.tsx:48`、`ReviewsBoard.tsx:37`（默认参数）、`ReviewsBoard.tsx:71`（model_id，**Z1 新增**）。
→ **与 v2 清单基本一致，仅多 Z1 一处**；✅ 说明 v2 §2 的"诊断修正"方向正确。

## Z3. 🟠 A.3"默认参数改 `= ''`"的严重度需下调

因 `.tsx` 已从 `App` 下发**非空** `series`，五处默认参数 `= '银河E5'`（`KanbanView.tsx:14/53`、`MarketBoard.tsx:8`、`ConfigBoard.tsx:48`、`ReviewsBoard.tsx:37`）**运行时不会命中**（仅当 series 为空或组件被单独渲染时命中）。列为"硬编码"无误，但**严重度应下调**：它只有在 **D1（默认空 series）落地后**才真正生效。→ 表述改为"配合 D1 的兜底清理"。

## Z4. 删除安全性再确认（正面）

- grep `from '…js'`（`prism-web/src/**/*.{ts,tsx}`）**零命中** → 无任何显式 `.js` 导入，**17 个 `.js` 删除安全** ✓（与 v2 一致）。
- `vite.config.ts` 未改 `resolve.extensions` ✓，`tsconfig.json` 无 `noEmit` ✓（幽灵成因确认）。

## Z5. 收敛判定（第 3 轮）

- **已核验**：计划 A/B/C/D/E/F 六节 + 防 0 四条 + 硬编码清单 + 验收 0–8，**逐条对照 `.tsx` 现状并与同名 `.js` 逐一比对**；`银河E5|7650|79311` 全量 grep、显式 `.js` 导入扫描、`vite.config` 的 `resolve`、`tsconfig`、`main.tsx` 入口、四 Board 证据 src——**均已人工确认**。
- **结论**：**计划主体正确，但严重度排序需按 Z0 重定位**——「防 0 = 主修复（删 `.js` 即恢复动态，A/C 自动生效）」＞「B（CLAIM 卡）＞ D（默认空+fail-closed）＞ Z1（ReviewsBoard:71）＞ E ＞ F」；并补 **Z1**；**W1–W5 仍全部有效**。
- **无新的未核项 → 收敛。**
- **施工前必做**：① 先落地防 0（否则一切"改了没反应"）；② 在防 0 后**重新实测**验收 1/3（预计直接通过，无需再改 `.tsx`）；③ 再据实测残留（B/Z1/D/E/F）逐项施工。