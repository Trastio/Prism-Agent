# 可视化看板 + 事件分析 + 深度报告 — 完整计划

## 现状盘点

### 数据模型（已有，无需改表）
| 表 | 关键字段 | 用途 |
|----|---------|------|
| RawPost | platform, likes, comments, shares, published_at | 原始帖子 + 互动 |
| AnalyzedPost | sentiment, event_tags(JSON), opinion_tags(JSON) | 分析结果 |
| HeatMetric | attention_index, discussion_volume, media_volume, interaction_intensity | 每日热度 |
| AnomalyEvent | event_type, volume_change_rate | 异常事件 |
| Vehicle | competitor_ids | 竞品关联 |

### API 端点（已有）
- Dashboard: overview, trend, platform-distribution, event-distribution, anomaly-timeline, posts, reports
- Analysis: trigger, heat-metrics, anomalies, sentiment-summary, top-events, **top-opinions**
- Reports: brief, deep-report
- Dialog: anchor, history

### 前端（已有）
- Vue 3 + ECharts，概览/趋势/平台/事件/异常/帖子/报告 7 个区
- Dialog 面板 + Generative UI（stat_cards/table/post_list/chart）

---

## 任务一：看板可视化完善（轻量级）

### 缺口分析

| # | 缺什么 | API 侧 | 前端侧 |
|---|--------|--------|--------|
| T1.1 | 趋势图缺百度指数线 | API 已返回 attention_index，无需改动 | app.js 加第 4 条 series + 右 Y 轴 |
| T1.2 | 缺观点 TOP10 图表 | `/api/analysis/top-opinions/{id}` 已存在 | app.js 加第 3 栏柱状图 |
| T1.3 | 概览周变化趋势显示不全 | API 返回 week_total（本周量），需改为变化率 | 显示 ↑↓ 箭头 + 百分比 |
| T1.4 | 缺竞品对比 | 新增 `/api/dashboard/competitor-comparison/{id}` | 新增分组柱状图 |

### 实施步骤

**T1.1 趋势图叠加百度指数** — 只改前端
- `app.js:renderTrendChart()` 添加第 4 条 series: `{name: "注意力指数", type: "line", yAxisIndex: 1, data: trendData.map(d => d.attention_index)}`
- 添加右侧 Y 轴配置
- legend 添加 "注意力指数"

**T1.2 观点 TOP10** — 只改前端
- `index.html` 分析区从 2 栏改为 3 栏，加 `<div id="opinion-chart">`
- `app.js` 添加 `loadOpinionTop()` → `GET /api/analysis/top-opinions/{id}` → 渲染横向柱状图
- `onVehicleChange()` 中调用

**T1.3 概览周变化** — API 微调 + 前端
- `dashboard.py:get_overview()` 增加上周同期查询，计算 `week_change_rate`
- `index.html` 概览卡片显示变化率箭头

**T1.4 竞品对比** — 新 API + 前端
- `dashboard.py` 新增 `/api/dashboard/competitor-comparison/{vehicle_id}`
  - 读取 `vehicle.competitor_ids`，对各车型查 `AnalyzedPost` 情感分布
  - 返回 `[{name, positive, negative, neutral}]`
- `index.html` 异常区改为"异常与竞品区"，增加竞品对比 div
- `app.js` 添加分组柱状图渲染

### 验收标准
- 趋势图 4 条线（讨论声量/媒体声量/互动烈度/注意力指数）
- 分析区 3 栏（平台声量/事件分布/观点TOP10）
- 概览卡显示周变化率
- 竞品对比分组柱状图（需要有竞品数据）

---

## 任务二：事件深度分析（中等）

### 缺口分析

当前 `dialog.py` 的 `_build_context()` 只传文本描述（"用户点击了趋势图上 2026-05-20 的数据点"），不传实际数据。DeepSeek 拿不到真实数据，只能泛泛而谈。

### 实施步骤

**T2.1 丰富上下文注入** — 改 `dialog.py:_build_context()`
- trend 锚点：查询当天 HeatMetric 4 层指标 + AnalyzedPost 情感分布 + RawPost 热门帖子 TOP5
- platform 锚点：查询该平台帖子数 + 情感分布 + 热门帖子
- event 锚点：查询该事件标签下的帖子列表 + 情感占比 + 互动量 TOP 帖子
- anomaly 锚点：查询异常详情 + 当天帖子 + 情感突变

**T2.2 增强 system prompt** — 改 `dialog.py:generate_dialog_response()`
- 指导 LLM 使用 Generative UI 标签输出结构化内容
- 针对不同锚点类型给出不同的分析框架提示

**T2.3 前端对接** — 无需改动
- Generative UI 已支持 stat_cards/table/post_list/chart
- SSE 流式已实现
- 对话持久化已实现

### 验收标准
- 点击趋势图某天：返回当天 4 层热度 + 情感分布 + 数据卡片
- 点击平台：返回该平台统计 + TOP 帖子列表
- 点击事件：返回事件关联数据 + 情感分析
- 多轮追问能保持上下文

---

## 任务三：深度报告生成（严格遵循 OpenSpec + Superpowers）

### 为什么需要完整流程
- 从"单次 LLM 调用"到"模板→章节→校验→HTML"是全新子系统
- 涉及 4 个新模块 + API 改造 + 前端报告查看器
- 参考 BettaFish ReportEngine 架构，需要设计决策

### 执行流程

#### Phase 1: OpenSpec（定义 WHAT）

**Step 1: brainstorming**
- 明确 3 个报告模板的章节结构和数据需求
- 确定 HTML 渲染方案（Jinja2 模板 vs 纯 Python 字符串拼接）
- 防幻觉校验策略（正则提取数值 vs LLM 自校验）
- 输出：`docs/brainstorming-deep-report.md`

**Step 2: OpenSpec 产物**
- 新建 `openspec/changes/deep-report-engine/`
- `proposal.md` — Why/What Changes/Capabilities/Impact
- `specs/*.md` — 每个模块一个 spec（templates, chapter-generator, verifier, html-renderer, orchestrator）
- `design.md` — 模块交互图、数据流、技术选型
- `tasks.md` — 可执行任务清单

#### Phase 2: Superpowers（实现 HOW）

**Step 3: writing-plans**
- 基于 tasks.md 拆分实施计划，识别并行任务

**Step 4: subagent-driven-development / executing-plans**
- TDD RED→GREEN→REFACTOR

**Step 5: simplify**
- 审查变更代码质量

**Step 6: requesting-code-review**
- 对照 OpenSpec specs 验证实现

**Step 7: verification-before-completion**
- 全量测试通过 + 报告端到端验证

#### Phase 3: OpenSpec 收尾

**Step 8: opsx:archive**
- 归档 deep-report-engine change
- 归档 agent-chat-architecture change（之前的）

### 预估模块

| 模块 | 文件 | 职责 |
|------|------|------|
| 模板定义 | `pipeline/reports/templates.py` | 3 个模板结构 + LLM/规则选择 |
| 章节生成器 | `pipeline/reports/chapter_generator.py` | 逐章调用 LLM-2，每章独立 prompt |
| 防幻觉校验 | `pipeline/reports/verifier.py` | 数值提取 + DB 对比 + 超阈值重生成 |
| HTML 渲染 | `pipeline/reports/html_renderer.py` | 自包含 HTML + 目录 + 图表 + 预警高亮 |
| 编排器 | `pipeline/reports/report_generator.py` | 串联上述 4 步 |
| API 改造 | `api/routes/reports.py` | 接入新管线，返回 HTML 报告 |
| 前端 | `frontend/` | 报告查看器（iframe / 新窗口） |

---

## 执行顺序

```
任务一 (T1.1-T1.4)  →  任务二 (T2.1-T2.3)  →  任务三 (完整 OpenSpec 流程)
   轻量增强               中等改造                重建子系统
```

任务一和二在同一分支上完成，TDD + code review。
任务三独立 worktree，完整流程。
