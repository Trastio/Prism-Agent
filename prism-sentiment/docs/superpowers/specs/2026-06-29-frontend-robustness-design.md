# 主题 A：前端健壮性 — 设计文档

> 日期：2026-06-29
> 治根主题 A（共 7 主题）：统一 API 调用层 + 错误反馈机制 + 事件去重

## 1. 背景与根因

前端 ~30 处 `fetch` 调用混乱：约一半无 try/catch（裸调），一半有但 catch 里只静默设空数据。**前端完全没有错误提示 UI**（无 alert/toast/notify）——API 失败时用户无感知，表现为白屏或空数据。`bindChartClick` 在每次 `renderAllCharts` 重复注册 click 监听器 → 点击图表多次弹 Dialog。

**共同根因**：
- 调用层：没有统一 API 调用封装，每个 fetch 各写各的
- 反馈层：没有错误反馈机制
- 事件层：没有事件注册去重

逐个补 try/catch = 头痛医头；治根 = 一个 `apiFetch` 收口所有调用 + 一个 toast 收口所有错误反馈，之后任何新 fetch 自动获得错误处理。

## 2. 目标

1. 所有 API 调用经统一 `apiFetch`：自动 `resp.ok` 检查 + 安全 JSON 解析 + 失败反馈。
2. API 失败时用户可见错误（toast），不再白屏/卡死/静默。
3. 图表 click 监听器不重复注册。
4. **治根判据**：未来新增任何 fetch，用 `apiFetch` 即自动健壮；不再可能出现裸调白屏。

## 3. 设计

### 3.1 `apiFetch(url, options)` — 统一 API 调用

置信度：高（fetch.ok + JSON 安全解析是前端标准实践）。

```js
async function apiFetch(url, { json, ...opts } = {}) {
  // 便捷：传 json 自动序列化 body + JSON header（消除 POST 样板）
  if (json !== undefined) {
    opts.body = JSON.stringify(json);
    opts.headers = { "Content-Type": "application/json", ...(opts.headers||{}) };
  }
  try {
    const resp = await fetch(url, opts);
    if (!resp.ok) { showToast(`请求失败 (${resp.status})`); return null; }
    // 安全 JSON 解析：非 JSON 响应（如 422 返回 HTML）不崩溃
    const text = await resp.text();
    try { return JSON.parse(text); }
    catch { showToast("响应解析失败"); return null; }
  } catch (e) {
    showToast(`网络错误: ${e.message}`);
    return null;
  }
}
```

- 失败返回 `null`（不抛异常）→ 调用方 `this.x = await apiFetch(url) || 默认值`
- GET：`apiFetch(url)`；POST JSON：`apiFetch(url, {method:"POST", json:{...}})`

### 3.2 toast 组件

置信度：高（toast 是标准 UX 组件）。

- Vue `data.toasts = []`
- `showToast(msg, type="error")`：推入 `{id, msg, type}`，`setTimeout` 3s 后按 id 移除
- `index.html` 加固定容器 `<div id="toast-container">`，Vue `v-for` 渲染
- CSS：固定右上角，`z-index` 高，error 红色背景，3s 淡出
- `showToast` 为全局函数（window 上），`apiFetch` 与任意场景均可调

### 3.3 事件去重（标记法）

置信度：高（echarts 事件重复注册是已知问题，标记守卫是标准解法）。

`bindChartClick` 注册前检查 `chart.__clickBound`：
```js
bindChartClick(chart, anchorType) {
  if (chart.__clickBound) return;
  chart.__clickBound = true;
  chart.getZr().on("click", ...);
  chart.on("click", ...);
}
```
`sentimentDonutChart.on("click")`（app.js:370）、`opinionTagsChart.on("click")`（app.js:401）同样加 `__clickBound` 守卫。

## 4. 改造范围

- **~30 处 fetch 全部改用 `apiFetch`**（grep `fetch(` 在 app.js 的所有命中点）
- 6 处无 try/catch 的（fetchVehicles/loadOverview/loadTrend/loadSentimentTrend/loadPlatformDist/loadTopPosts/loadPosts/loadReports/triggerCollection/sendDialogMessage/createGroup/loadGroupTrend）→ 用 apiFetch 自动错误处理
- 有 try/catch 的 → 也改 apiFetch（统一），catch 简化为兜底设默认值
- triggerCollection/sendDialogMessage 失败后**重置 loading 状态**（apiFetch 返 null 时）
- bindChartClick + 2 个直接 .on("click") → 标记去重

## 5. 错误处理（治根点）

- **不再白屏**：任一 API 失败 → toast + 该区域 `|| 默认值` 降级，`Promise.all` 不再因单个 reject 中断（各 load 方法独立返回默认值）
- **不再卡死**：triggerCollection/sendDialogMessage 失败 → toast + 重置 loading
- **用户可见**：每个错误有 toast 反馈

## 6. 验证（CDP 手动）

前端无测试基建，用 CDP 手动验证（复用项目已有 CDP 调试方法学）：
1. 模拟 API 失败：临时改一个 fetch url 为 404 → 看 toast 弹出 + 看板不白屏（其他区域正常）
2. 点击图表 → 确认只弹一次 Dialog（去重生效，对比修复前多次弹）
3. 触发采集 → 模拟失败看 loading 重置 + toast

## 7. 涉及文件

- `frontend/static/js/app.js` — 新增 `apiFetch` + `showToast` + toast data；改造 ~30 处 fetch；事件去重
- `frontend/index.html` — toast 容器
- `frontend/static/css/style.css`（或 index.html inline）— toast 样式

## 8. 非目标（YAGNI）

- 不做请求重试 / 超时（fetch 默认行为够用，YAGNI）
- 不做请求队列 / 取消（当前无此需求）
- 不改后端 API（本主题纯前端）
- 不重构 Vue 组件结构（只加封装层 + 改 fetch 调用）
