# Spec 2.5 · 前端 UI 层

> UI Track 全量 + Step 7 埋点。前置 [design.md](./design.md#ui-track与主线并行)。

## 待办

### P0
- UI-1 删顶部三个死元素 + 侧栏空壳实装/下架
- UI-2 口碑/市场/配置看板接 _meta + ConfigBoard 赋分接真链路 + 销量同比接 2025 数据 + 演示态水印
- UI-7 ChatView 点踩/采纳按钮（Step7.4）
- UI-8 SeriesCombobox 新建（接 /identity/resolve）

### P1
- UI-3 SKILLS 库侧栏入口 + 展开面板 + GET /skills
- UI-4 会话行内编辑 + rename 接口 + list onClick 切换

### P2
- UI-5 hero 大字态（Didone 字型）+ Logo 卢浮宫金字塔
- UI-6 视图保活 + 产物视图数据模型 + 修 args 字段/重复 case/as_of 提取

### 埋点（Step7）
- 7.1 SDK：page_view/chat_start/active_tick(30s)/feedback
- 7.2 sendBeacon 上报
- 7.5 脱敏 VIN/车牌正则

## 设计细节

**UI-2 图表接真数据**：
- ReviewsBoard：KPI 从 _meta.coverage 提（已有正则，改结构化字段）+ rows.reduce 算标签总数
- MarketBoard：KPI 从 rows 算累计/月份/版型数 + 销量同比接 2025 对比数据（需 mv_sales_monthly 扩 2025 列或后端算）
- ConfigBoard：从 specs.length 算 + 赋分卡接真实赋分链路（A1 CLTC/B1 R18 等，去"示例"标）
- 演示态：未接数据的看板加 dev-only 水印（CSS .demo-watermark）

**UI-8 SeriesCombobox**：
- prism-web 新建 components/SeriesCombobox.tsx
- input + dropdown，输入触发 /identity/resolve
- 歧义时显示候选列表供选择
- 选中后回填 composer 的 series_key

**UI-4 会话重命名**：
- Sidebar 会话行双击→行内 input
- POST /session/rename {session_id, name}
- pi_gateway 转发 + pi SessionManager 更新 session metadata
- list 返回 custom_name 字段
- 会话行 onClick 切换（当前缺，补 useQuery invalidate）

**UI-5 hero + Logo**：
- 新建会话空态：hero 大字"Prism"（Didone 字型，bodoni-moda 字体已自托管）
- Logo：卢浮宫金字塔抽象 SVG，放应用栏左侧

**UI-6 视图保活**：
- App.tsx 视图切换不卸载（keep-alive 模式，display:none 而非 unmount）
- 产物视图：ChatView 右侧 preview tab，数据模型 {type:'report'|'excel'|'word', url, session_id}

**埋点 SDK**：
- prism-web/lib/tracker.ts
- page_view：路由切换触发
- active_tick：Page Visibility API + 30s setInterval（可见时才 tick）
- feedback：点踩/采纳按钮触发
- sendBeacon('/events', JSON.stringify({events})) 关页不丢

**脱敏**：
- tracker.ts 内 sanitize()：VIN `[A-HJ-NPR-Z0-9]{17}` → `***`，车牌 `[京津沪...]·[A-Z]·[A-Z0-9]{5}` → `***`

## 验收
- 5 看板真数据（无硬编码）+ 演示态水印
- SeriesCombobox 选车系→series_key 进请求
- 点踩→/events 落行
- 会话重命名+切换可用
- SKILLS 库面板可展开
- hero+Logo 渲染
- 视图切换不丢状态
- 3 小缺陷清零（args/重复 case/as_of）

## 依赖
- Step 2.6 /identity/resolve（SeriesCombobox）
- Step 5.11 vite 代理 /events（埋点）
- Step 7.3 /events 端点（埋点）
