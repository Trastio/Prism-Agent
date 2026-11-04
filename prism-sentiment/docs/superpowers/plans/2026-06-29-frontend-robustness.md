# 主题 A：前端健壮性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** 前端所有 API 调用经统一 `apiFetch`（ok 检查+安全JSON+失败toast），告别白屏/卡死/静默；图表 click 监听器去重。

**Architecture:** 新增 Vue methods `apiFetch`/`showToast` + `toasts` data + HTML 容器；~30 处 fetch 改用 `apiFetch`（失败返 null，调用方 `|| 默认值`降级）；bindChartClick + 2 处 `.on("click")` 加 `__clickBound` 标记去重。

**Tech Stack:** Vue 3 CDN（无构建/无前端测试）→ 验证用 CDP 手动。

**Spec:** `docs/superpowers/specs/2026-06-29-frontend-robustness-design.md`

---

## File Structure

| 文件 | 职责 |
|------|------|
| `frontend/static/js/app.js` | 新增 `apiFetch`/`showToast` methods + `toasts` data；改造 ~30 处 fetch；事件去重 |
| `frontend/index.html` | toast 容器 + 样式 |

## Task 依赖

- Task 1（基础设施）→ Task 2/3（改造依赖 apiFetch 存在）
- Task 4（事件去重）独立
- Task 5（验证）依赖 1-4

---

## Task 1: apiFetch + showToast + toast 基础设施

**Files:** `frontend/static/js/app.js`（data + methods）、`frontend/index.html`

- [ ] **Step 1: 加 toasts data**

在 Vue `data()` 返回对象中加 `toasts: []`（定位 data() return，通常在文件前部）。

- [ ] **Step 2: 加 showToast method**

在 `methods` 内（234 行起）加：
```js
showToast(msg, type = "error") {
    const id = Date.now() + Math.random();
    this.toasts.push({ id, msg, type });
    setTimeout(() => {
        this.toasts = this.toasts.filter(t => t.id !== id);
    }, 3000);
},
```

- [ ] **Step 3: 加 apiFetch method**

在 `methods` 内（showToast 后）加：
```js
async apiFetch(url, { json, ...opts } = {}) {
    if (json !== undefined) {
        opts.body = JSON.stringify(json);
        opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
    }
    try {
        const resp = await fetch(url, opts);
        if (!resp.ok) { this.showToast(`请求失败 (${resp.status})`); return null; }
        const text = await resp.text();
        try { return JSON.parse(text); }
        catch { this.showToast("响应解析失败"); return null; }
    } catch (e) {
        this.showToast(`网络错误: ${e.message}`);
        return null;
    }
},
```

- [ ] **Step 4: index.html 加 toast 容器 + 样式**

在 `<body>` 末尾（或 `#app` 内合适位置）加：
```html
<div class="toast-container">
    <div v-for="t in toasts" :key="t.id" :class="['toast', t.type]">{{ t.msg }}</div>
</div>
```
（toast-container 需在 Vue 挂载根 `#app` 内，使 `v-for="t in toasts"` 生效）

CSS（index.html `<style>` 或 style.css）：
```css
.toast-container { position: fixed; top: 16px; right: 16px; z-index: 9999; display: flex; flex-direction: column; gap: 8px; }
.toast { padding: 10px 16px; border-radius: 6px; color: #fff; font-size: 14px; box-shadow: 0 4px 12px rgba(0,0,0,.15); animation: toast-in .2s; }
.toast.error { background: #e74c3c; }
@keyframes toast-in { from { opacity: 0; transform: translateX(20px); } to { opacity: 1; transform: translateX(0); } }
```

- [ ] **Step 5: 冒烟验证**

CDP 打开看板，浏览器控制台跑 `app.apiFetch('/api/dashboard/overview/不存在')` → 应弹 toast「请求失败 (404)」并返回 null。`app.showToast('测试')` → 右上角弹 toast 3s 消失。

- [ ] **Step 6: Commit**

```bash
git add frontend/static/js/app.js frontend/index.html
git commit -m "feat(frontend): apiFetch 统一封装 + toast 错误反馈基础设施"
```

---

## Task 2: 改造 GET 类 fetch → apiFetch

**Files:** `frontend/static/js/app.js`

**改造模式**（所有 GET fetch 统一）：
```js
// 旧
const resp = await fetch(url);
this.x = await resp.json();
// 新
this.x = await this.apiFetch(url) || 默认值;
```

**默认值映射表**（每处的 `|| 默认值`）：

| 方法 | 行 | data 字段 | 默认值 |
|------|:--:|------|------|
| fetchVehicles | 260 | this.vehicles | `[]` |
| loadOverview | 452 | this.overview | `{}` |
| loadTrend | 456 | this.trendData | `[]` |
| loadSentimentTrend | 460 | this.sentimentTrend | `[]` |
| loadDimSentiment | 466 | this.dimSentiment | `[]`（已有 try/catch，改后 catch 可简化或删）|
| loadOpinionTags | 478 | this.opinionTags | `[]`（同上）|
| loadEventTimeline | 488 | this.eventTimeline | `[]`（同上）|
| loadPlatformDist | 493 | this.platformDist | `[]` |
| loadTopPosts | 501 | this.topPosts | `[]` |
| pollCollectionStatus | 510 | (status) | `null`（已有 try/catch）|
| loadPosts | 529 | this.posts | `[]` |
| loadWordCloud | 537 | this.wordCloudData | `[]`（已有 try/catch）|
| loadReports | 545 | this.reports | `[]` |
| loadControversialPosts | 552 | this.controversialPosts | `[]`（已有 try/catch）|
| loadEventTagsDist | 558 | this.eventTagsDist | `[]`（已有 try/catch）|
| fetchDashboardSummary | 851 | (report) | 已有 try/catch，改 apiFetch |
| searchVehicles | 930 | (results) | 已有 try/catch |
| loadGroups | 953 | this.groups | `[]`（已有 try/catch）|
| loadGroupOverview | 969 | (Promise.all) | 已有 try/catch |
| loadGroupTrend | 1012 | this.groupTrendData | `[]` |

- [ ] **Step 1: 逐处改造**（按上表，每处 `fetch+json` → `this.apiFetch(url) || 默认值`；已有 try/catch 的，apiFetch 已处理错误，catch 可简化为兜底设默认值或删除冗余）

- [ ] **Step 2: CDP 冒烟**——打开看板选车型，所有区域正常加载（无白屏）；控制台故意 `app.apiFetch('/bad')` 确认 toast。

- [ ] **Step 3: Commit**

```bash
git add frontend/static/js/app.js
git commit -m "refactor(frontend): GET 类 fetch 改用 apiFetch 统一错误处理"
```

---

## Task 3: 改造 POST 类 fetch + loading 状态重置

**Files:** `frontend/static/js/app.js`

- [ ] **Step 1: triggerCollection（879）— 失败重置 loading**

```js
// 旧（裸调，失败 loading 永久 true）
async triggerCollection() {
    this.loading = true;
    this.pipelinePhase = "collecting";
    const resp = await fetch(`/api/vehicles/${this.currentVehicleId}/collect`, { method: "POST" });
    const data = await resp.json();
    ... 
}
// 新
async triggerCollection() {
    this.loading = true;
    this.pipelinePhase = "collecting";
    const data = await this.apiFetch(`/api/vehicles/${this.currentVehicleId}/collect`, { method: "POST" });
    if (!data) { this.loading = false; this.pipelinePhase = ""; return; }  // 失败重置
    ...
}
```

- [ ] **Step 2: sendDialogMessage（1116）— 失败反馈 + 不卡死**

流式响应特殊：apiFetch 不适用（它 parse JSON，但 dialog 是 SSE 流）。改为：保留 fetch + reader，但加 try/catch + resp.ok 检查 + 失败 toast + 移除等待中的用户消息：
```js
async sendDialogMessage() {
    ...
    try {
        const resp = await fetch("/api/dialog/anchor", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({...}) });
        if (!resp.ok) { this.showToast(`对话请求失败 (${resp.status})`); /* 移除等待消息 */ return; }
        const reader = resp.body.getReader();
        ... (现有流处理)
    } catch (e) {
        this.showToast(`网络错误: ${e.message}`);
        /* 移除等待消息 */
    }
}
```

- [ ] **Step 3: createGroup（1081）— POST JSON 用 apiFetch 便捷参数**
```js
// 旧
const resp = await fetch("/api/groups", { method:"POST", headers:{...}, body: JSON.stringify({...}) });
const data = await resp.json();
// 新
const data = await this.apiFetch("/api/groups", { method:"POST", json: { name: ..., vehicle_ids: ... } });
if (!data) return;
```

- [ ] **Step 4: createVehicle（307，POST /api/vehicles）— 同 createGroup 模式**

- [ ] **Step 5: CDP 冒烟**——触发采集正常；模拟采集失败（断网）确认 loading 重置 + toast。

- [ ] **Step 6: Commit**

```bash
git add frontend/static/js/app.js
git commit -m "refactor(frontend): POST fetch 改用 apiFetch + 失败重置 loading/sendDialog 加错误反馈"
```

---

## Task 4: 图表 click 事件去重

**Files:** `frontend/static/js/app.js`

- [ ] **Step 1: bindChartClick（430）加标记守卫**
```js
bindChartClick(chart, anchorType) {
    if (!chart) return;
    if (chart.__clickBound) return;   // 新增：已绑定则跳过
    chart.__clickBound = true;        // 新增
    chart.getZr().on("click", (params) => { ... });  // 不变
    chart.on("click", (params) => { ... });          // 不变
},
```

- [ ] **Step 2: sentimentDonutChart（370）加守卫**
```js
if (this.sentimentDonutChart.__clickBound) return;  // 新增（在 .on 之前）
this.sentimentDonutChart.__clickBound = true;
this.sentimentDonutChart.on("click", (params) => { ... });
```

- [ ] **Step 3: opinionTagsChart（401）加守卫**（同上模式）

- [ ] **Step 4: CDP 冒烟**——点击趋势图 → 确认只弹**一次** Dialog（修复前会多次）；点击情感环/观点标签同样单次。

- [ ] **Step 5: Commit**

```bash
git add frontend/static/js/app.js
git commit -m "fix(frontend): 图表 click 监听器标记去重，避免重复弹 Dialog"
```

---

## Task 5: CDP 端到端验证

**前置:** FastAPI 服务在线（:8000）+ CDP proxy（:3456）+ Chrome。

- [ ] **Step 1: 错误反馈验证**

CDP 打开看板，浏览器控制台执行：
```js
// 模拟 API 404
app.apiFetch('/api/dashboard/overview/不存在').then(r => console.log('返回:', r))
```
Expected: 右上角弹 toast「请求失败 (404)」，控制台 `返回: null`。

- [ ] **Step 2: 不白屏验证**

临时改一个 load 方法的 url（或断网），重新 onVehicleChange → 确认该区域降级空、其他区域正常、无白屏。

- [ ] **Step 3: 点击去重验证**

点击趋势图 → 确认只弹一次 Dialog（开发者工具 Network 看只一次 /api/dialog/anchor 请求）。

- [ ] **Step 4: 采集失败恢复验证**

断网后点采集 → 确认 loading 重置（按钮可再点）+ toast 提示。

- [ ] **Step 5: 记录验证结果**，无代码改动则无需 commit；若有修复补提交。

---

## 完成标准（spec §2）

- [ ] 所有 ~30 处 fetch 经 `apiFetch`（grep `fetch(` 仅剩 apiFetch 内部 + sendDialogMessage 的流式）
- [ ] API 失败 → toast + 降级，不白屏/不卡死
- [ ] 图表点击单次触发
- [ ] CDP 5 项验证全过

## Self-Review

（写完 plan 后自检：spec 覆盖、placeholder、一致性。Task 2 的默认值映射表覆盖所有 GET fetch；POST 在 Task 3；事件在 Task 4；验证在 Task 5。无 placeholder。apiFetch 接口与 spec §3.1 一致。）
