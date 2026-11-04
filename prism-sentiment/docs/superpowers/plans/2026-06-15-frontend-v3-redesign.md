# Frontend v3 Redesign Implementation Plan

> **For agentic workers:** 按区块执行，每步改完刷新浏览器看效果（前端视觉工作不适合单测，验证=肉眼）。Steps use checkbox (`- [ ]`) syntax.

**Goal:** 把 `frontend/redesign-preview.html`（v3 静态设计稿）的视觉系统接入实际服务，重做 `index.html` 模板 + restyle 图表，保留 `app.js` 全部 Vue 逻辑与 21 个 API 接线。

**Architecture:** v3 是纯视觉层（设计系统 + 布局 + ECharts 调色板），`app.js` 是数据/逻辑层（已接好 API）。改造 = 用 v3 的 CSS 变量/字体/卡片/chrome 栏替换 `index.html` 的 `<style>`，按 v3 的 6 区块布局重排模板，图表 option 改用 v3 调色板（蓝正红负无绿）+ hbar 辅助函数。`app.js` 的 data/methods/fetch 几乎不动，只调整图表渲染函数的 option。

**Tech Stack:** Vue 3 (CDN) / ECharts 5 / echarts-wordcloud / 原生 CSS（v3 设计 token）

---

## 背景

- `frontend/index.html`（服务实际页面，499 行）+ `app.js`（983 行 Vue）= 当前看板，设计陈旧
- `frontend/redesign-preview.html`（333 行，未提交未挂载）= v3 静态设计稿，写死假数据，**0 个 API 调用**
- 当前 app 功能比 v3 全：多了分组/报告/全部帖子/锚点对话/词云/竞品对比。v3 是核心看板的视觉重设计，不是 1:1 替换
- 目标：localhost:8000 呈现 v3 视觉 + 真实数据

## 设计决策

- **CSS 全量替换**：v3 的 `:root` 设计 token（`--bg/--ink/--accent/--pos/--neg` 等）+ 字体（Inter+Noto Sans SC）整体替换 `index.html` 的 `<style>`，旧 class 逐个映射或重写
- **保留所有功能**：分组/报告/对话/词云等 v3 没有的区块保留，只 restyle，不删
- **图表调色板统一**：新建 JS 常量 `CHART_COLORS`（对齐 v3 的 C 对象），所有 ECharts option 改用它；新增 `hbar()`/`spark()` 辅助函数（从 v3 抄进 app.js）
- **app.js 最小改动**：只动图表渲染函数（renderXxx）的 option 部分；data/methods/fetch 不动
- **分阶段可见**：Phase 1 单独交付就足以让页面"变 v3"

## File Structure

- **Modify** `frontend/index.html` — `<style>` 全替换为 v3 token；`<body>` 模板按 v3 chrome+6区块重排（保留现有功能区块）
- **Modify** `frontend/static/js/app.js` — 新增 `CHART_COLORS`/`hbar`/`spark`；各 `renderXxx` 图表 option 改用 v3 调色板
- **参考** `frontend/redesign-preview.html` — 设计源（不直接用，逐元素迁移）

---

## Phase 1: 设计系统 + Chrome 壳（单独交付即"变 v3"）

### Task 1: 替换 `<style>` 为 v3 设计 token

**Files:** Modify `frontend/index.html`（`<style>` 块）

- [ ] **Step 1: 备份当前 style 的关键 class 名**（迁移用）

读 `index.html` 的 `<style>`，列出 body/header/.section/.card/.btn/.chart-container 等核心 class 的当前样式，作为后续 restyle 的对照。

- [ ] **Step 2: 注入 v3 设计 token 到 `<style>` 顶部**

把 `redesign-preview.html:10-98` 的 `:root` 变量 + `body/.num/.wrap/.card/.card-title/.sec-title/.kpi-*` 等基础样式，作为新 `<style>` 的开头加进 `index.html`（保留旧样式在下方，逐步迁移避免一次性全崩）：

```css
:root{
  --bg:#fafaf7; --ink:#15140f; --muted:#5a564e;
  --border:#e7e5e0; --thead:#f4f1ec; --grid:#f0ece5;
  --accent:#c96442; --accent-d:#a44f33;
  --pos:#2348b8; --neg:#9c2a25; --neu:#9e9e9e; --info:#3a6ea5;
}
body{background:var(--bg);font-family:'Inter','Noto Sans SC',sans-serif;color:var(--ink);margin:0;line-height:1.5}
.num{font-family:'Inter',sans-serif;font-feature-settings:'tnum' on}
/* + v3 的 .wrap/.card/.card-title/.sec-title/.chrome 等 */
```
（完整从 redesign-preview.html:23-98 抄）

- [ ] **Step 3: 引入字体**

`<head>` 加（redesign-preview.html:8）：
```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Noto+Sans+SC:wght@400;500;600;700&display=swap" rel="stylesheet">
```

- [ ] **Step 4: 刷新浏览器看底色/字体变化**

打开 http://localhost:8000，确认背景变暖白(#fafaf7)、字体变 Inter。若旧布局错位，正常（后续 Task 修）。

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html
git commit -m "ui: adopt v3 design tokens (colors/fonts/base styles)"
```

---

### Task 2: 顶部 Chrome 栏（sticky 工具栏）

**Files:** Modify `frontend/index.html`（header 区块，约 27-75 行）

- [ ] **Step 1: 重做 header 为 v3 chrome 栏**

把现有 `<header>`（search combobox/group/time/collect/overflow）包进 v3 的 `.chrome` sticky 栏结构（redesign-preview.html:103-112）。保留所有现有交互（v-model/@click 不动），只改外层 class 与布局：

```html
<div class="chrome">
  <div class="chrome-brand">汽车舆情<span class="dot">·</span>监控</div>
  <!-- 现有 search combobox，class 改 chrome-search -->
  <!-- 现有 group dropdown，class 改 chrome-select -->
  <div class="chrome-spacer"></div>
  <!-- 现有 time range，class 改 chrome-time -->
  <button class="chrome-btn" @click="triggerCollection" :disabled=...>采集</button>
  <!-- 现有 overflow ⋮ 改 chrome-icon -->
  <div class="chrome-icon" title="异常告警">🔔<span v-if="activeAlerts.length" class="badge">{{ activeAlerts.length }}</span></div>
</div>
```
（v-if/disabled/@click 全部沿用现有，只搬外衣）

- [ ] **Step 2: 把 alert-bar 改 v3 样式**

现有 `.alert-bar`（14-25 行）套用 v3 的 alert-bar CSS（redesign-preview.html:42-47）：左边框 3px accent、label 大写 letter-spacing。保留 `v-if="activeAlerts.length"` 和 `@click="dismissAlerts"`。

- [ ] **Step 3: 刷新看 chrome 栏吸顶 + 告警条样式**

确认顶部栏 sticky 吸顶、橙色 accent、告警条左红边。下拉/搜索/采集按钮功能正常。

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html
git commit -m "ui: rebuild header as v3 sticky chrome bar + alert bar"
```

---

### Task 3: 页面标题区（eyebrow/title/meta/lede）

**Files:** Modify `frontend/index.html`（chrome 栏下、第一个 section 前）

- [ ] **Step 1: 加 v3 header.pb 区块**

chrome 栏后、overview 前，插入 v3 的标题区（redesign-preview.html:126-139），绑定真实数据：

```html
<header class="pb" v-if="currentVehicleId">
  <div class="header-row">
    <div>
      <div class="eyebrow">当前车型 · {{ currentVehicleName }}</div>
      <h1 class="title">舆情看板 · {{ currentVehicleName }}</h1>
    </div>
    <div class="meta">
      <div>来源: <b>5 平台社媒 + 新闻</b></div>
      <div>区间 <b class="num">{{ rangeStart }} ~ {{ rangeEnd }}</b></div>
      <div v-if="lastCollectionTime">上次采集 <b class="num">{{ lastCollectionTime }}</b></div>
    </div>
  </div>
  <p class="lede" v-if="overview.total_posts">
    采集 <b class="num">{{ overview.total_posts }}</b> 条、分析 <b class="num">{{ overview.analyzed_total }}</b> 条。
    健康分 <b class="num">{{ overview.health_score }}</b>，正面 {{ overview.positive_pct }}%。
    检测出 <b class="num">{{ eventCount }}</b> 个事件聚类。
  </p>
</header>
```

- [ ] **Step 2: 确认 app.js 有 currentVehicleName / eventCount**

若 `currentVehicleName` 无 computed，加一个（从 vehicles 找 currentVehicleId 对应 name）。`eventCount` 同理（events 数组长度，若无则加 computed）。`overview.positive_pct` 若无，加 computed = positive/total*100。

- [ ] **Step 3: 刷新看标题区**

确认大标题 + 灰色 lede 摘要行（数字用 Inter tabular）。

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html frontend/static/js/app.js
git commit -m "ui: add v3 header (eyebrow/title/meta/lede) with real data"
```

---

## Phase 2: Overview / KPI 卡片（v3 的 01 区块）

### Task 4: 4 张 KPI 卡 + sparkline

**Files:** Modify `frontend/index.html`（overview-v5 区块 138-199）+ `app.js`（renderSentimentRing 旁加 renderSparklines）

- [ ] **Step 1: 重做 overview 为 v3 kpi-grid**

把现有 overview-v5 section（138-199）替换为 v3 的 4 卡 kpi-grid（redesign-preview.html:142-170），绑定真实数据：

```html
<section class="sec" v-if="currentVehicleId">
  <h2 class="sec-title">01 · 核心指标</h2>
  <div class="kpi-grid">
    <div class="card">
      <div class="kpi-label">健康分</div>
      <div class="kpi-value num">{{ overview.health_score }}<span class="sub"> / 100</span></div>
      <div class="kpi-delta"><span :class="overview.health_score>=50?'delta-up':'delta-down'">▲ {{ overview.week_change_rate||0 }}%</span> <span style="color:var(--muted)">vs 上期</span></div>
      <div class="spark" id="sp-health"></div>
    </div>
    <!-- 舆情总量/正面占比/事件聚类 三张卡同理 -->
  </div>
</section>
```

- [ ] **Step 2: app.js 加 spark 渲染**

抄 v3 的 `spark()` 函数（redesign-preview.html:272-277）进 app.js，新增 `renderSparklines()` method，用 sentimentTrendData 最近 N 周数据画 4 条 sparkline（health/volume/pos/event）。在 loadOverview 后调用。

- [ ] **Step 3: 刷新看 4 卡 + sparkline**

确认 4 张卡片横排、数字大号、下方有迷你折线。

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html frontend/static/js/app.js
git commit -m "ui: v3 KPI cards (health/volume/positive/events) with sparklines"
```

---

## Phase 3: 图表调色板统一 + hbar 化

### Task 5: app.js 加 CHART_COLORS + hbar/spark helper

**Files:** Modify `frontend/static/js/app.js`（顶部）

- [ ] **Step 1: 加常量与 helper**

app.js 顶部加（对齐 redesign-preview.html:269-315）：

```js
const CHART_COLORS = {accent:'#c96442', accentD:'#a44f33', pos:'#2348b8', neg:'#9c2a25', neu:'#9e9e9e', info:'#3a6ea5', grid:'#f0ece5', muted:'#5a564e', ink:'#15140f'};
const BASE_AXIS = {axisLine:{show:false}, axisTick:{show:false}, splitLine:{lineStyle:{color:CHART_COLORS.grid}}, axisLabel:{color:CHART_COLORS.muted, fontSize:11}};

function hbarChart(el, data, opts={}) { /* 抄 redesign-preview.html:305-315 */ }
function sparkChart(el, data, color) { /* 抄 redesign-preview.html:272-277 */ }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/static/js/app.js
git commit -m "ui: add CHART_COLORS palette + hbar/spark helpers (from v3)"
```

---

### Task 6: 各图表 option 改用 v3 调色板

**Files:** Modify `frontend/static/js/app.js`（renderTrendChart/renderSentimentChart/renderPlatformChart/renderEventChart/renderOpinionChart）

逐个把图表 option 的 `itemStyle.color`/`lineStyle.color` 从旧色（绿/默认）改为 CHART_COLORS（蓝正红负无绿）。每个改完刷新看一眼：

- [ ] **Step 1: sentiment-chart（堆叠）** — 正面=pos 蓝、负面=neg 红、中性=neu 灰（去掉绿）
- [ ] **Step 2: trend-chart（热度折线）** — 线色=accent，area 渐变 accent
- [ ] **Step 3: platform-chart** — 改用 hbarChart（v3 横条），颜色 accent 渐变
- [ ] **Step 4: event-chart** — 改用 hbarChart
- [ ] **Step 5: opinion-chart** — 改用 hbarChart
- [ ] **Step 6: 逐个刷新验证无绿、蓝红对比**

- [ ] **Step 7: Commit**

```bash
git add frontend/static/js/app.js
git commit -m "ui: apply v3 palette (blue=pos/red=neg/no green) to all charts"
```

---

### Task 7: 新增 ABSA 维度体检图（v3 的 04 区块）

**Files:** Modify `frontend/index.html`（新 section）+ `app.js`（renderDimChart + 数据来源 overview.dim_sentiment）

- [ ] **Step 1: 加维度体检 section**

index.html 加（redesign-preview.html:202-209）：
```html
<section class="sec" v-if="currentVehicleId">
  <h2 class="sec-title">04 · 维度体检 · ABSA 15 维度</h2>
  <div class="card">
    <div class="card-title">各维度情感均分<span class="card-sub">-1 负面 ~ 1 正面</span></div>
    <div id="dim-chart" style="height:420px"></div>
  </div>
</section>
```

- [ ] **Step 2: app.js 加 renderDimChart**

数据源 = overview 接口返回的 dim_sentiment 聚合（dashboard overview 已返回 dim_sentiment，见 dashboard.py:112）。若 overview 没聚合均分，加后端聚合 OR 前端从 overview 强维度算均分。用 hbarChart 画（redesign-preview.html:319-328）。

- [ ] **Step 3: 刷新看 15 维度横条**

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html frontend/static/js/app.js
git commit -m "feat(ui): ABSA 15-dimension health chart (v3 section 04)"
```

---

## Phase 4: 异常 + 洞察 + 热帖 restyle

### Task 8: 异常时间线 + 关键洞察（v3 的 05 区块）

**Files:** Modify `frontend/index.html`（异常与竞品区 247-283）

- [ ] **Step 1: 异常列表改 v3 ano-list 样式**

现有异常展示套用 v3 的 `.ano-list/.ano-item/.ano-tag.spike/.ano-drop`（redesign-preview.html:82-90, 217-223）。保留现有 anomalies 数据 + root_cause。

- [ ] **Step 2: 加关键洞察卡片（4 格）**

抄 v3 的 insight 卡（redesign-preview.html:225-233），但内容动态化——从 overview/eventDist/anomalies 提炼 4 条洞察（如：主导事件标签、最强/最弱维度、异常峰值）。可先用静态文案占位，后续接数据。

- [ ] **Step 3: 刷新看异常列表 + 洞察卡**

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html frontend/static/js/app.js
git commit -m "ui: v3 anomaly timeline + insight cards"
```

---

### Task 9: 热帖 TOP + 平台分布 restyle（v3 的 06 区块）

**Files:** Modify `frontend/index.html`（TOP10 热帖 316-346）

- [ ] **Step 1: 热帖改 v3 卡片样式**

现有 topPosts 列表套用 v3 热帖样式（redesign-preview.html:246-251）：标题加粗 + 灰色元信息行（平台/点赞/评论/日期）。保留 tab 切换 + platformLabel。

- [ ] **Step 2: 平台分布并到热帖旁（grid-2）**

把 platform-chart 移到热帖左侧（v3 的 grid-2 布局，redesign-preview.html:240-243）。

- [ ] **Step 3: 刷新看布局**

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html
git commit -m "ui: v3 top-posts + platform distribution layout"
```

---

## Phase 5: 收尾

### Task 10: 方法论 details + 清理旧样式 + 全量验证

**Files:** Modify `frontend/index.html`

- [ ] **Step 1: 加方法论折叠**

底部加 v3 的 `<details class="meth">`（redesign-preview.html:256-263），内容写实（双模型/事件聚类/健康分公式）。

- [ ] **Step 2: 删除旧 `<style>` 残留**

Phase 1 保留的旧样式，确认无引用后删除（grep class 名确认）。

- [ ] **Step 3: 全量功能验证**

刷新 http://localhost:8000，逐个点：车型切换/搜索/分组/时间范围/采集/各图表/锚点对话/全部帖子/报告/添加车型。确认 v3 视觉 + 全功能正常。

- [ ] **Step 4: Commit**

```bash
git add frontend/index.html
git commit -m "ui: add methodology, clean legacy styles, full verify"
```

---

## Self-Review

**Spec coverage:** v3 的 6 区块全覆盖——chrome(Task2)/header(Task3)/KPI(Task4)/趋势(Task6 sentiment+heat)/事件(Task6 event+opinion)/维度(Task7)/异常+洞察(Task8)/平台+热帖(Task9)。✓

**保留功能:** 分组/报告/全部帖子/锚点对话/词云/竞品对比/添加车型 modal——这些 v3 没有，计划里明确"只 restyle 不删"，散落在各 Task 的"保留现有交互"。Task10 Step3 全量验证兜底。

**风险:** app.js 图表 option 改动可能破坏现有渲染——每步刷新浏览器即时验证。维度图(Task7)数据源需确认 overview 是否返回聚合均分，若无要加后端（小改动）。

**执行策略:** Phase 1（Task1-3）单独交付即"变 v3"，可先做到这看效果再决定是否继续 Phase 2-5。
