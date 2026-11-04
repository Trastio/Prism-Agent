# 硬编码清理与车系动态化 · Step 1 Explore

> 2026-10-06
> change: 硬编码清理与车系动态化
> 对象：[改造计划 v3](file:///c:/Users/<you>/Desktop/Prism-Agent/设计图总览/Prism-Agent-硬编码清理与车系动态化-改造计划.md)
> 性质：探查代码现状（不写方案，方案在 Step2 propose）

---

## 1. 探查方法

- 前端：主会话亲自 grep + Read（只读工具，不依赖分类器）
- extension fail-closed：子代理探查（进行中）

---

## 2. 幽灵 .js 现状

**17 个 .js 文件**（src 下，与 .tsx/.ts 同名）：
- src/App.js / main.js
- src/components/*.js（ChatView/KanbanView/Sidebar/SeriesCombobox/SkillsPanel/PyramidLogo/EvidenceDrawer/Icons 共 8 个）
- src/components/dashboards/*.js（ConfigBoard/MarketBoard/ReviewsBoard/SentimentBoard/_shared 共 5 个）
- src/lib/*.js（chat.js / tracker.js）

**机制**：
- `main.tsx:10` `import App from './App'`（无扩展名）
- `vite.config.ts` 未自定义 `resolve.extensions`（默认 `.mjs,.js,.mts,.ts,.jsx,.tsx,.json`，.js 优先于 .tsx）
- `tsconfig.json` 无 `noEmit`，`build` 脚本 `tsc -b && vite build` → tsc 在源码目录原地生成 .js

**显式 .js import**：grep `from '.*\.js'` 零命中 → 删除安全

**后果**：vite 极可能加载 .js（旧编译产物含硬编码银河E5），改 .tsx 不生效

---

## 3. .tsx 真硬编码清单（grep 银河E5|7650|79311）

| 位置 | 硬编码内容 | 类型 |
|---|---|---|
| `App.tsx:24` | `useState('银河E5')` | 默认 state |
| `KanbanView.tsx:14` | `series = '银河E5'` | 默认参数 |
| `KanbanView.tsx:53` | `series = '银河E5'`（OverviewBoard） | 默认参数 |
| `KanbanView.tsx:118` | `src: 'review_tags#7650/舒适/con ; config#79311 ; sales_trim#银河E5/2026'` | CLAIM supported_by |
| `KanbanView.tsx:119` | `scope: 'series=7650'` | CLAIM scope |
| `KanbanView.tsx:123` | `scope 银河E5` | CLAIM 显示 |
| `KanbanView.tsx:127` | supported_by 硬编码 | CLAIM |
| `KanbanView.tsx:129` | `scope: 'series=7650'` | CLAIM |
| `ReviewsBoard.tsx:37` | `series = '银河E5'` | 默认参数 |
| `ReviewsBoard.tsx:71` | `src: \`review_tags:model_id=7650/tag_category=${r.tag_category}\`` | 证据 src model_id 硬编码 |
| `ConfigBoard.tsx:48` | `series = '银河E5'` | 默认参数 |
| `MarketBoard.tsx:8` | `series = '银河E5'` | 默认参数 |
| `ChatView.tsx:176` | `SUGGESTIONS(series || '银河E5')` | 兜底 |

**注**：KanbanView.tsx:53 OverviewBoard useQuery、ConfigBoard.tsx:118/127 证据 src、MarketBoard.tsx:67 证据 src **已动态**（用 series 变量/模板字符串），不在硬编码清单。

---

## 4. series prop 全链路（.tsx 现状）

- `App.tsx:65` `<KanbanView active={view === 'kanban'} onEvidence={openEvidence} series={series} />` ✅ 已传
- `KanbanView.tsx:14` 签名 `series?: string` ✅ 已接
- `KanbanView.tsx:41-45` 下发 OverviewBoard/ConfigBoard/ReviewsBoard/MarketBoard ✅
- 四 Board 签名均接 `series?: string` ✅

**结论**：series prop 全链路在 .tsx 已打通。**唯一阻碍是幽灵 .js 被加载**（Z0 确认）。

---

## 5. DemoCard 现状

- `_shared.tsx:52` `export function DemoCard(...)` ✅ 已导出
- `MarketBoard.tsx:74/85` `<DemoCard>` ✅ 已用（版型结构/竞品对比）
- `ReviewsBoard.tsx:99/107` `<DemoCard>` ✅ 已用（舒适样本/口碑趋势）

**结论**：C 节在 .tsx 已完成，删 .js 后自动生效。

---

## 6. Sidebar 车系 tab 现状

- `Sidebar.tsx:68` 有"车系"tab 按钮
- `Sidebar.tsx:131-137` tab 内容：`<div className="sb-label">最近车系</div>` + `<li>暂无最近车系</li>`
- **无 onSelectSeries prop**，无车系选择逻辑
- 搜索框（L88）placeholder 是"搜索车系…"但未接 /identity/resolve

**结论**：车系 tab 是空壳，需实装（F 节）。

---

## 7. tsconfig + build 现状

- `tsconfig.json` 无 `noEmit`，无 `allowImportingTsExtensions`，无 `outDir`
- `package.json` build: `tsc -b && vite build`
- `vite.config.ts` resolve 只有 alias，无 extensions

---

## 8. extension fail-closed 现状

（子代理探查结果待回，先记录已知）
- `index.ts:595` `if (seriesKey) { fetch /identity/resolve }` —— seriesKey 为空时跳过核验
- `index.ts:633` `warningsText = identityWarning || (seriesKey ? '无' : '对象未确认...')` —— 空时拼提示词
- **非真阻断**：没有 setActiveTools([])，模型仍可调工具

---

## 9. 待办清单（按 v3 施工顺序）

### 防 0（主修复）
- 0.1 删 17 个幽灵 .js
- 0.2 tsconfig 加 noEmit
- 0.3 build 改 `tsc --noEmit && vite build`
- 0.4 验证加载 .tsx + 验收 1/3 实测

### B（CLAIM 动态化）
- B.1 KanbanView.tsx:118/123/127/129 CLAIM 卡片 series/series_id/supported_by 动态化
- B.2 series_id 从 /identity/resolve 取（reviews/sales 字段是 model_id 无 series_id，W4）

### Z1（ReviewsBoard:71）
- Z1.1 ReviewsBoard.tsx:71 model_id=7650 动态化（从 useQuery 结果取 model_id）

### D（默认空 + 真阻断）
- D.1 App.tsx:24 useState('') + 看板 enabled: !!series
- D.2 ChatView handleSend series 为空时禁用发送
- D.3 extension before_agent_start 空系列Key 时 pi.setActiveTools([]) 真阻断

### E（去兜底）
- E.1 ChatView.tsx:176 去 '银河E5' 兜底，空时通用文案

### F（车系 tab 实装）
- F.1 Sidebar 加 onSelectSeries/series prop
- F.2 车系 tab 搜索接 /identity/resolve + 最近车系 localStorage + 选中高亮

### A/C（不施工）
- A series prop 全链路：.tsx 已完成，删 .js 后验证
- C DemoCard：.tsx 已完成，删 .js 后验证

---

## 10. 下一步

进 Step2 propose：写 proposal.md + design.md + specs + tasks.md 四件套。
