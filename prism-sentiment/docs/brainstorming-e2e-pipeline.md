# Brainstorming: 端到端数据跑通

## 问题诊断

### 1. 前端超时（Critical）
`POST /api/vehicles/{id}/collect` 是同步阻塞的。采集链路耗时：
- Bocha + Anspire 新闻搜索：~5-10s
- MediaCrawler × 4 平台：每平台最长 300s（5 分钟）
- 百度指数：~5s
- 初始模式：3 个日期范围 × N 个关键词

**最坏情况：20+ 分钟**，浏览器 fetch 默认超时。

**同样问题存在于** `POST /api/analysis/trigger/{id}`：200 帖 × 30s API 超时 = 最坏 100 分钟。

### 2. 缺少自动链路
采集完成 → 需手动点"分析" → 需要手动刷新看板。没有 collect → analyze → heat calc → dashboard 的自动串联。

### 3. 对话面板
依赖 DeepSeek API key + 已分析数据。功能代码已完成，只需要真实数据填充后验证。

## 方案

### 核心改动：后台任务 + 轮询

**后端**：
1. 采集和分析都改为 `asyncio.create_task()` 后台执行
2. 后台任务创建独立 DB session（脱离 HTTP 请求生命周期）
3. 通过 `CollectionStatus.status` 字段追踪阶段：`collecting` → `analyzing` → `calculating` → `completed`
4. 新增 `GET /api/vehicles/{id}/pipeline-status` 端点，返回当前阶段 + 进度
5. 完整 pipeline：collect → analyze → heat calc → anomaly detect

**前端**：
1. 点击"采集"→ 立即返回 → 每 3 秒轮询 pipeline-status
2. 按钮旁显示当前阶段文字
3. completed 时自动刷新看板
4. "分析"按钮同样改为异步

### 不改动的部分
- 采集器代码（scheduler/collectors）不变
- 分析器代码（analyzer/batch_runner）不变
- 对话面板代码不变
- 看板渲染代码不变

## 风险
- SQLite 并发写入限制：后台任务写 + 前端轮询读，应无冲突
- MediaCrawler 可能不可用（is_available()=false），应优雅降级
- 百度指数需要 cookie，可能失败，不影响主流程

## 验证步骤
1. 启动服务器
2. 添加车型
3. 点击采集 → 观察轮询状态变化
4. 完成后看板自动刷新显示真实数据
5. 点击图表元素 → 对话面板打开 → DeepSeek 返回分析
