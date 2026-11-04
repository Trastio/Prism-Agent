# 主题 E：前端功能补全 — 设计文档

> 日期：2026-06-29
> 治根主题 E（共 7 主题，最大）：补全前端缺失功能（分组对比 UI + overview 字段 + 未调用 API）

## 1. 侦察结论

### E1 分组对比 UI 完全缺失（最大）
- **app.js JS 完备**：`currentGroupId`/`groupOverview`/`groupComparison`/`onGroupChange`/`selectGroupVehicle`/`renderGroupComparisonChart`/`renderGroupRadarChart`/`loadGroupTrend`/`addGroup` 全有
- **index.html 只有**："新建分组"按钮（47）+ 添加分组 Modal（409）。**缺**：分组选择器（切换 currentGroupId）、分组展示 section（车型卡片 + 对比图 + 趋势图 + 雷达图容器）
- 后端 `/api/groups/*` 完备（overview/comparison/trend）
- → JS 渲染方法找不到 DOM，分组功能完全不显示

### E2 overview 分析字段未展示
API `/overview` 返回（dashboard.py:137-146）：`week_change_rate`/`peak_date`/`best_dim`/`best_dim_score`/`worst_dim`/`worst_dim_score` + 已展示的 `positive_pct`/`health_score`。
前端 KPI 只用 `positive_pct`/`health_score` → 4 类分析字段（周环比、峰值日、最强/最弱维度）白算。

### E3 `/competitor-comparison`（dashboard.py:469）未调用
app.js 无此端点调用。需确认用途（vehicle 级竞品对比 vs 分组对比）后接入或标注弃用。

## 2. 设计

### E1 分组 section（核心）
index.html 加（位置：02 概览之后，或独立 section）：
- **分组选择器**：chrome 区或 section 头，下拉切换 `currentGroupId`（v-model + onGroupChange）
- **分组 section** `v-if="currentGroupId"`：
  - 车型卡片网格（`groupOverview.cards`：各车型名 + 总量 + 正/负/中）
  - 对比图（`#group-comparison-chart`，已 bind renderGroupComparisonChart）
  - 趋势图（`#group-trend-chart`，已 bind renderGroupTrendChart）
  - 雷达图（`#group-radar-chart`，已 bind renderGroupRadarChart）

### E2 KPI 字段
在 02 概览 KPI 区加：
- 周环比 `overview.week_change_rate`（% 带↑↓）
- 峰值日 `overview.peak_date`
- 最强维度 `overview.best_dim`（+score）/ 最弱 `overview.worst_dim`

### E3 competitor-comparison
实现时读 dashboard.py:469 确认语义。若 vehicle 级竞品 → 加入口；若与分组重叠 → 标注弃用。

## 3. 子任务
1. E1 分组选择器 + section HTML + 确认 JS 绑定（容器 id 与 renderGroup* 对齐）
2. E2 KPI 4 字段展示（index.html + 可能 app.js computed）
3. E3 competitor-comparison 接入决策

## 4. 验证（浏览器，Chrome remote debugging）
- 创建分组 → 选分组 → 显示车型卡片 + 对比/趋势/雷达图
- KPI 显示周环比/峰值日/最强最弱维度
- competitor-comparison 接入后正确渲染

## 5. 非目标
- 不重构现有 5 个 section 结构
- 分组对比若与 competitor-comparison 重叠，合并而非两套

## 6. 实现前置
**需 Chrome remote debugging**（前端大改，盲写风险高，须浏览器联调）。
