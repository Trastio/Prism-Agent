# Phase 3 实施计划：看板与报告

基于 OpenSpec tasks.md T3.1-T3.9，拆解为 TDD 原子任务。

---

## T3.1 看板后端 API

### T3.1.1 测试：Dashboard API
- **文件**: `tests/test_dashboard_api.py`
- **内容**:
  - 测试 GET /api/dashboard/overview/{id} — 概览数据
  - 测试 GET /api/dashboard/trend/{id} — 趋势数据
  - 测试 GET /api/dashboard/platform-distribution/{id} — 平台分布
  - 测试 GET /api/dashboard/event-distribution/{id} — 事件分布
  - 测试 GET /api/dashboard/anomaly-timeline/{id} — 异常时间线
  - 测试 GET /api/dashboard/posts/{id} — 帖子列表（筛选/分页）
  - 测试 GET /api/dashboard/reports/{id} — 历史报告
- **TDD**: 先写测试 → 红灯

### T3.1.2 实现：Dashboard API
- **文件**: `api/routes/dashboard.py`
- **内容**:
  - `/api/dashboard/overview/{id}` — 5 指标（总量、正/负/中性、周变化、健康度）
  - `/api/dashboard/trend/{id}` — 热度趋势时序（含生命周期阶段标注）
  - `/api/dashboard/platform-distribution/{id}` — 平台声量分布
  - `/api/dashboard/event-distribution/{id}` — 事件分布 TOP15
  - `/api/dashboard/anomaly-timeline/{id}` — 异常事件时间线
  - `/api/dashboard/posts/{id}` — 帖子列表（支持 platform/sentiment 筛选、分页）
  - `/api/dashboard/reports/{id}` — 历史报告列表
  - 注册到 `api/main.py`
- **TDD**: 运行 T3.1.1 测试 → 绿灯

### T3.1.3 Commit
- `git commit -m "feat: dashboard API with TDD tests"`

---

## T3.2 看板前端 - Vue 3 组件

### T3.2.1 测试：前端文件存在性 + JS 语法检查
- **文件**: `tests/test_frontend.py`
- **内容**:
  - 测试 index.html 包含 Vue 3 CDN 引用
  - 测试 app.js 可被 Node 解析（无语法错误）
  - 测试 style.css 加载无报错
- **TDD**: 先写测试 → 红灯

### T3.2.2 实现：HTML 骨架 + 概览卡片
- **文件**: `frontend/index.html`
- **内容**:
  - Vue 3 CDN + ECharts CDN
  - Header（车型选择器 + 添加/采集/分析按钮）
  - 添加车型 Modal
  - Overview Cards（5 指标卡片）
  - 各 section 占位
- **TDD**: 运行 T3.2.1 → 绿灯（HTML 结构检查）

### T3.2.3 实现：Vue 3 App 核心
- **文件**: `frontend/static/js/app.js`
- **内容**:
  - Vue 3 app 实例（data、computed、methods）
  - `fetchVehicles()` / `addVehicle()` / `onVehicleChange()`
  - `loadOverview()` → 渲染概览卡片
  - `loadTrend()` → ECharts 趋势图（折线 + dataZoom）
  - `loadPlatformDist()` → ECharts 饼图
  - `loadEventDist()` → ECharts 柱状图
  - `loadAnomalies()` → 时间线渲染
  - `loadPosts()` → 表格渲染（筛选/分页）
  - `triggerCollection()` / `triggerAnalysis()`
  - 窗口 resize 处理

### T3.2.4 实现：CSS 样式
- **文件**: `frontend/static/css/style.css`
- **内容**: 完整响应式样式（header、cards、charts、timeline、table、modal、pagination）

### T3.2.5 Commit
- `git commit -m "feat: Vue 3 dashboard frontend with ECharts"`

---

## T3.3 事件简报

### T3.3.1 测试：简报生成 API
- **文件**: `tests/test_report_api.py`
- **内容**:
  - 测试 POST /api/reports/brief — 生成简报（mock DeepSeek API）
  - 测试 POST /api/reports/brief/stream — SSE 流式简报
  - 测试简报保存到 reports 表
  - 测试 anomaly event 的 brief_generated 标记更新

### T3.3.2 实现：简报生成
- **文件**: `api/routes/reports.py`
- **内容**:
  - `POST /api/reports/brief` — 同步生成简报
  - `POST /api/reports/brief/stream` — SSE 流式生成
  - Prompt 构建：车型 + 异常数据 + 情感变化 + top 帖子
  - 结果写入 reports 表 + 更新 anomaly_events
- **TDD**: 运行 T3.3.1 测试 → 绿灯

### T3.3.3 Commit
- `git commit -m "feat: event brief generation with SSE streaming"`

---

## T3.4 深度报告

### T3.4.1 测试：深度报告 API
- **文件**: `tests/test_report_api.py`（追加）
- **内容**:
  - 测试 POST /api/reports/deep-report — 生成深度报告（mock DeepSeek API）
  - 测试报告内容包含分析数据
  - 测试报告保存到 reports 表

### T3.4.2 实现：深度报告生成
- **文件**: `api/routes/reports.py`（追加）
- **内容**:
  - `POST /api/reports/deep-report` — 生成深度报告
  - 从 analyzed_posts + anomaly_events 提取上下文
  - DeepSeek API 单次调用生成结构化报告（6 章节）
  - 结果写入 reports 表
- **TDD**: 运行 T3.4.1 测试 → 绿灯

### T3.4.3 Commit
- `git commit -m "feat: deep report generation with TDD tests"`

---

## 任务依赖图

```
T3.1.1 → T3.1.2 → T3.1.3
                        ↘
T3.2.1 → T3.2.2 → T3.2.3 → T3.2.4 → T3.2.5
                                            ↘
                                             T3.3.1 → T3.3.2 → T3.3.3
                                                                       ↘
                                             T3.4.1 → T3.4.2 → T3.4.3
```

**Phase 3 预计 13 个原子任务，4 个 commit。**
