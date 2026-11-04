# Prism-Agent · 硬编码清理 + 车系动态化改造计划 v3

> 2026-10-06 · 修订版（融合三轮审查 W1-W5 + Z0-Z3）
> 取代 v2（v2 严重度排序倒置 + fail-closed 写法错 + 漏列 Z1 + W1 会触发 TS5097）
> 判据来源：[审查意见 v1/v2/v3 三轮](../../../文档/Prism-Agent-硬编码清理与车系动态化-改造计划-审查意见-2026-10-06.md) + 源码实测
> 性质：**改造计划**（待审阅，审阅通过按十步流程推进）

---

## v3 相对 v2 的修订摘要

| 审查项 | 修订 |
|---|---|
| **Z0 严重度倒置** | 防 0 从"前置"升级为"主修复"——删 .js 后 A/C 自动生效（.tsx 已完成）；A/C 从"待施工"改"已实现待验证" |
| **W1 TS5097** | 删防 0 改动 4（main.tsx 不改扩展名）——清 .js 后无扩展名自然解析到 .tsx |
| **W2 fail-closed 写法错** | D 节 extension 兜底改 `pi.setActiveTools([])`（真阻断，非拼提示词）——符合红线#5"护栏在执行层" |
| **Z1 漏列** | 补 ReviewsBoard.tsx:71 `model_id=7650` 硬编码进清单 |
| **W4 series_id 来源** | §B series_id 从 /identity/resolve 取（非 useQuery，reviews/sales 字段是 model_id 无 series_id） |
| **W5 tsc -b --noEmit** | 删备选，只保留 `tsc --noEmit && vite build` |
| **W3 Windows find** | 验收 0 命令改 Windows 兼容 |

---

## Z0 关键认知：防 0 = 主修复

**三轮审查最关键的发现**：v2 把"清幽灵 .js"当前置、A/C 当施工项，**严重度排序倒置**。

实测 `.tsx` 现状（[Z0](../../../文档/Prism-Agent-硬编码清理与车系动态化-改造计划-审查意见-2026-10-06.md#L181)）：
- `App.tsx:65` **已有** `series={series}` prop
- `KanbanView.tsx:14` **已有** `series?: string` + 下发四 Board
- `MarketBoard.tsx:74/85` **已用** `<DemoCard>`
- `ReviewsBoard.tsx:99/107` **已用** `<DemoCard>`

**机制**：`main.tsx:10` `import App from './App'`（无扩展名）+ vite 默认 `.js` 优先 → 运行时加载旧 `App.js`（无 series）→ series 链路被 .js 掐断。

**推论**：**"看板不随车系变"的唯一原因是加载了旧 .js，不是 .tsx 缺代码**。删 17 个 .js 后，A/C 自动生效，验收 1（选海豚→看板变）+ 验收 3（演示卡折叠）应直接通过。

---

## 防 0（主修复，最先做）

> 审查 §1 + Z0：清幽灵 .js 是主修复，非前置。删 .js 后 A/C 自动生效。

**改动**：
1. 删除 `prism-web/src/**/*.js` 全部 17 个幽灵文件
2. `tsconfig.json` 加 `"noEmit": true`
3. `package.json` build 脚本改 `tsc --noEmit && vite build`（删 `tsc -b --noEmit` 备选，W5）
4. ~~main.tsx 改扩展名~~（W1 删：tsconfig 无 allowImportingTsExtensions，会 TS5097）

**验收 0**：
- `Get-ChildItem -Path prism-web/src -Recurse -Filter *.js` 返回空（W3 Windows 兼容）
- 浏览器 Network 确认加载 `main.tsx`/`App.tsx`（非 .js）
- `npx tsc --noEmit` 零错误
- **重新实测验收 1/3**（选海豚→看板变 + 演示卡折叠，预计直接通过）

---

## 修正后的真实硬编码清单（仅 .tsx）

> 审查 §2 + Z1 + Z3：v2 清单漏 Z1，Z3 默认参数严重度下调（D1 后才生效）。

| 位置 | 硬编码内容 | 类型 | 严重度 |
|---|---|---|---|
| `App.tsx:24` | `useState('银河E5')` | 默认 state | 高（D1） |
| `KanbanView.tsx:14/53` | `series = '银河E5'` | 默认参数 | 低（Z3，D1 后才生效） |
| `MarketBoard.tsx:8` | `series = '银河E5'` | 默认参数 | 低（Z3） |
| `ReviewsBoard.tsx:37` | `series = '银河E5'` | 默认参数 | 低（Z3） |
| `ConfigBoard.tsx:48` | `series = '银河E5'` | 默认参数 | 低（Z3） |
| `KanbanView.tsx:118/123/127` | CLAIM 卡 `银河E5`+`7650`+`79311` | 硬编码值 | 高（B） |
| `ReviewsBoard.tsx:71` | `model_id=7650`（Z1 新增） | 硬编码 src | 中（Z1） |
| `ChatView.tsx:176` | `SUGGESTIONS(series || '银河E5')` 兜底 | 兜底 | 低（E） |

**注**：`KanbanView.tsx:53` OverviewBoard useQuery、`ConfigBoard.tsx:118/127` 证据 src、`MarketBoard.tsx:67` 证据 src **已动态**（.tsx），v1/v2 误标已剔除。

---

## 改造范围（A/C 已实现待验证，不施工）

### A. 看板 series prop 全链路（已实现，删 .js 后验证）

**状态**：✅ .tsx 已完成（App.tsx:65 有 series prop，KanbanView:14 接收并下发）

**施工**：无。防 0 后重新实测验收 1。

### B. CLAIM 卡片动态化

**目标**：OverviewBoard CLAIM 卡片不硬编码银河E5/7650/79311

**W4 修正**：series_id 从 /identity/resolve 取（非 useQuery——reviews/sales 字段是 model_id 无 series_id，config 有 series_id）。

改动：
- `KanbanView.tsx:118/123/127` CLAIM 卡片：
  - series 从 useQuery 结果的 series_name 取（或 App series prop）
  - series_id 从 /identity/resolve 调用结果取（OverviewBoard 加 useQuery /identity/resolve）
  - supported_by 证据行 ID 从实际数据行取（review_tags:model_id=<动态>/tag_category=...）
  - series 为空 → CLAIM 卡显示空态"请先选择车系"

### C. 演示数据默认折叠（已实现，删 .js 后验证）

**状态**：✅ .tsx 已完成（MarketBoard/ReviewsBoard 已用 DemoCard）

**施工**：无。防 0 后重新实测验收 3。

### D. 默认 series 改空（D1）+ 真阻断

**W2 修正**：extension 兜底改 `pi.setActiveTools([])`（真阻断），非拼提示词。

**D1 默认空**：
- `App.tsx:24` `useState('银河E5')` → `useState('')`
- SeriesCombobox series 为空时显示"选择车系"占位
- 看板 series 为空时显示空态，useQuery 加 `enabled: !!series`

**对话侧 fail-closed（W2 真阻断）**：
- **前端拦截（A 层）**：ChatView handleSend 在 series 为空时禁用发送 + 提示"请先选择车系"
- **extension 兜底（C 层，W2 修正）**：before_agent_start `if (!seriesKey)` 时 `pi.setActiveTools([])`（空工具集，模型无法分析，真阻断）+ 返回阻断 systemPrompt

### E. ChatView 建议问题动态化（已部分完成）

> 审查 §5.2：SUGGESTIONS 已函数化，仅剩兜底 '银河E5'。

改动：
- `ChatView.tsx:176` `SUGGESTIONS(series || '银河E5')` → `SUGGESTIONS(series)`，series 为空时函数返回通用文案

### F. 侧栏"车系" tab 实装（功能新增，与清理分离）

**当前状态**：Sidebar.tsx:131-137 车系 tab 只有"暂无最近车系"空态。

**改动**：
- `Sidebar.tsx` 加 `onSelectSeries` prop + `series` prop（当前选中高亮）
- 车系 tab 内容：
  - 搜索框接 /identity/resolve（输入车系名→核验→命中显示候选）
  - 最近车系列表（localStorage `prism_recent_series` 存最近 5 个，点击切换）
  - 选中车系高亮（与 SeriesCombobox 同步）
- `App.tsx`：`<Sidebar onSelectSeries={setSeries} series={series} ... />`

---

## 不做（本轮边界，明确表述）

- **mapEvent 事件不全**：已知缺口，属观测域，非本计划范围（留 v2）
- **L2 身份注入 prompt 前缀**：pi 能力限制，留 v2
- **路由/停止生成/复制/重试**：体验类，留下一轮
- **owner_reviews.model_id 体系不对应**：Atuohome 供给端问题，留已知限制

---

## 验收

0. **前置/主修复**：`Get-ChildItem prism-web/src -Recurse -Filter *.js` 返回空 + 浏览器加载 .tsx + tsc --noEmit 零错误
1. SeriesCombobox 选"海豚" → 4 个看板数据全是海豚的（A 防 0 后验证）
2. 切换车系后证据 src 显示正确车系名 + model_id（B + Z1）
3. 演示卡默认折叠，点击展开（C 防 0 后验证）
4. 默认进入看板空态/提示选车系（D1）
5. series 为空时对话发送被拦截 + extension setActiveTools([]) 真阻断（D fail-closed）
6. ChatView 建议问题 series 为空时通用文案（E）
7. 侧栏车系 tab 可搜车系 + 最近车系 + 点击切换 + 高亮（F）
8. `npx tsc --noEmit` 零错误

---

## 施工顺序（Z0 重定位后）

| 序 | 事项 | 说明 |
|---|---|---|
| **防 0** | 清 17 个 .js + tsconfig noEmit + build 改 | **主修复**，A/C 自动生效 |
| **验证** | 重新实测验收 1/3 | 预计直接通过 |
| **B** | CLAIM 卡动态化（series_id 从 /identity/resolve 取，W4） | 真硬编码 |
| **Z1** | ReviewsBoard:71 model_id=7650 动态化 | 漏列补 |
| **D** | 默认空 series + setActiveTools([]) 真阻断（W2） | fail-closed |
| **E** | 去 ChatView:176 兜底 '银河E5' | 已部分完成 |
| **F** | 车系 tab 实装 | 功能新增 |

**A/C 不施工**（.tsx 已完成，删 .js 即生效）。

**按十步流程走**：explore 已是本计划 → propose 即本文 → 3.5 自查（审查三轮已完成）→ Step5 施工 → Step6 simplify → Step7 code-review → Step8 receiving-review → Step9 verification → Step10 archive。
