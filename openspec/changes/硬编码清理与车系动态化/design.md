# 硬编码清理与车系动态化 · Step 2 Design

> 2026-10-06
> 架构 + 各项落法。前置 [proposal.md](./proposal.md) + [explore.md](./explore.md)

---

## 架构总览

```
用户选车系（SeriesCombobox 或 Sidebar 车系 tab）
  ↓ series state（App.tsx，默认空）
  ├─ KanbanView series prop → 四 Board useQuery（enabled: !!series）
  │   ├─ OverviewBoard CLAIM 卡（series_id 从 /identity/resolve 取）
  │   ├─ ReviewsBoard（model_id 从 useQuery 结果取，非硬编码 7650）
  │   ├─ MarketBoard（证据 src 动态 series）
  │   └─ ConfigBoard（证据 src 动态 series）
  └─ ChatView series prop → sendChat seriesKey
      ↓
FastAPI /chat/stream → pi_gateway 拼 prompt 前缀
  ↓
extension before_agent_start
  ├─ seriesKey 空 → pi.setActiveTools([]) 真阻断（W2）
  ├─ seriesKey 非空 → fetch /identity/resolve 核验
  └─ setActiveTools(scope 白名单)
```

---

## 各项落法

### 防 0（主修复）
- 删 `prism-web/src/**/*.js`（17 个）
- `tsconfig.json` 加 `"noEmit": true`
- `package.json` build: `tsc --noEmit && vite build`
- 验证：浏览器 Network 加载 .tsx + 验收 1/3 实测

### A/C（不施工，删 .js 后验证）
- series prop 全链路 + DemoCard 在 .tsx 已完成

### B（CLAIM 动态化）
- `KanbanView.tsx:118/123/127/129` OverviewBoard CLAIM 卡：
  - series 从 App series prop 取
  - series_id：OverviewBoard 加 useQuery `/identity/resolve?series_key=${series}`，从结果取 series_id（W4，reviews/sales 字段是 model_id 无 series_id）
  - supported_by：从 revData/salesData/configData 实际行取（review_tags:model_id=<动态>/tag_category=...）
  - series 空 → CLAIM 卡显示"请先选择车系"

### Z1（ReviewsBoard:71 model_id 动态化）
- `ReviewsBoard.tsx:71` `model_id=7650` → 从 useQuery 结果取（rows[0].model_id 或 _meta）
- 若 model_id 不在 rows 字段，从 /identity/resolve 取 series_id 作 model_id

### D（默认空 + 真阻断）
- `App.tsx:24` `useState('')`
- 四 Board useQuery 加 `enabled: !!series`
- ChatView handleSend：series 空 → 禁用发送 + 提示"请先选车系"
- extension before_agent_start：`if (!seriesKey) { pi.setActiveTools([]); return { systemPrompt: '对象未确认，请先选择车系（红线#7 fail-closed）' } }`（W2 真阻断）

### E（去兜底）
- `ChatView.tsx:176` `SUGGESTIONS(series)`，函数 series 空 时返回通用文案（"用 query_reviews 查口碑舒适维度"无车系名）

### F（车系 tab 实装）
- `Sidebar.tsx` 加 `onSelectSeries`/`series` prop
- 车系 tab：
  - 搜索框 input → onChange 触发 /identity/resolve
  - 命中显示候选列表（点击 onSelectSeries）
  - 最近车系：localStorage `prism_recent_series`（数组，unshift，去重，截 5）
  - 选中车系高亮（series prop 比对）
- `App.tsx`：`<Sidebar onSelectSeries={setSeries} series={series} ... />`

---

## 关键路径

防 0 → 验证 A/C → B → Z1 → D → E → F
