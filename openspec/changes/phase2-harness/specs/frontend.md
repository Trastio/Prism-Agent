# Spec · 2.5 前端看板层

> 阶段2 · 新增层（2026-10-04 拍板：对话为中心 + 看板侧边预览，Web 站，参考 Hermes UI）
> 依赖：2.2 口径视图（M1 完成后并行启动）
> 被依赖：阶段4 上线（本层即上线前端，阶段2 做 v1，阶段4 部署上云）

---

## 待办清单

| ID | 待办 | 优先级 | 依赖 |
|---|---|---|---|
| 2.5.1 | Web 项目骨架（Vite + React 19 + TS + shadcn + Tailwind v4） | P0 | — |
| 2.5.2 | 三栏布局 Shell（左 sidebar / 中对话 / 右预览，可拖拽分割） | P0 | 2.5.1 |
| 2.5.3 | Agent 对话区（assistant-ui 流式 + 工具活动 + 状态栏） | P0 | 2.5.2, 2.2.3 |
| 2.5.4 | 右侧预览面板：4 看板 tab + 报告预览 | P0 | 2.5.2, 2.2.2 |
| 2.5.5 | 口碑看板（读 mv_reviews_dim + ECharts） | P1 | 2.5.4, 2.2.2 |
| 2.5.6 | 市场看板（读 mv_sales_monthly + ECharts） | P1 | 2.5.4, 2.2.2 |
| 2.5.7 | 配置看板（读 mv_config_spec + 对比表） | P1 | 2.5.4, 2.2.2 |
| 2.5.8 | 舆情看板（嵌套舆情 Board 21 dashboard GET） | P2 | 2.5.4 |
| 2.5.9 | 报告交付物预览（md/excel/word） | P2 | 2.5.4 |
| 2.5.10 | 后端 API 网关（FastAPI：对话 SSE + 看板数据 + pi SDK 桥） | P0 | 2.5.3, 2.5.4 |
| 2.5.11 | 会话/用户身份（浏览器本地 ID + 会话列表 sidebar） | P1 | 2.5.2 |

---

## 2.5.1 Web 项目骨架

### 设计
- **Vite + React 19 + TypeScript**（对齐 Hermes renderer 栈，去掉 Electron）
- **shadcn/ui (new-york) + Tailwind v4**（与 Hermes 一致，components.json 抄）
- **assistant-ui**（流式对话组件库，Hermes 同款）
- **ECharts**（图表，与舆情 Board 一致）
- **Radix + TanStack Query**（交互 + 数据获取）
- **react-router**（路由）

### 目录
```
prism-web/
├── src/
│   ├── app/              # 路由页面
│   ├── components/
│   │   ├── ui/           # shadcn 组件
│   │   ├── chat/         # 对话区（参考 Hermes src/app/chat）
│   │   ├── sidebar/      # 左侧栏
│   │   └── dashboards/   # 右侧四个看板
│   ├── lib/              # utils, api client
│   ├── hooks/
│   └── store/            # nanostores（与 Hermes 一致）
├── index.html
├── package.json
└── vite.config.ts
```

### 验收
- `npm run dev` 启动 Vite，空白三栏 Shell 可见
- shadcn 组件可添加（`npx shadcn add button`）

---

## 2.5.2 三栏布局 Shell

### 设计（参考 Hermes layout-constants + master-detail）
```
┌─────────────┬───────────────────────┬──────────────────┐
│ 左侧栏 16rem │  对话主区 flex-1       │ 右预览 min 320px  │
│ (可折叠3rem) │                       │ (可拖拽分割)      │
└─────────────┴───────────────────────┴──────────────────┘
```
- 左侧栏：`SIDEBAR_WIDTH=16rem`，折叠 `SIDEBAR_WIDTH_ICON=3rem`，<640px 转 Sheet（Hermes 同款）
- 右预览：拖拽分割，`SPLIT_MIN_LEFT_PX=320`（对话区最小），`SPLIT_MIN_RIGHT_PX=240`（预览最小）
- 主题：light/dark，neutral 基色（Hermes 同款）

### 验收
- 三栏可拖拽调整宽度
- 左侧栏可折叠
- 移动端（<640px）左侧栏转 Sheet

---

## 2.5.3 Agent 对话区

### 设计（参考 Hermes src/app/chat）
- **assistant-ui** 流式响应：消息列表 + composer 输入框
- **工具活动面板**：实时显示 agent 调用的工具名/参数/返回（参考 Hermes status-stack）
- **状态栏**：当前车系 / 三维度完成度 / 工具调用计数 / as_of（与 2.1.2 状态栏 hook 联动）
- **D3 来源标记渲染**：`<external_content source>` 标签渲染为可点击溯源 chip

### 数据流
- 前端 → 后端 API（SSE 流）→ pi SDK createAgentSession
- 工具活动通过 SSE 事件流推送（pi 的 `message_update` 事件）

### 验收
- 输入"分析银河E5" → 流式响应可见
- 工具调用实时显示
- 状态栏联动

---

## 2.5.4 右侧预览面板：4 看板 tab + 报告预览

### 设计
右侧面板顶部 tab 切换：
- **口碑看板** / **市场看板** / **配置看板** / **舆情看板** / **报告**

行为：
- agent 调用 query_* 工具时，自动切到对应看板 + 高亮当前查询结果
- 用户可手动切看板查看固定视图（不依赖对话）
- 报告 tab：agent 产出 md/excel/word 时预览（2.5.9）

### 验收
- 5 tab 可切换
- agent 调用 query_reviews 时自动切口碑看板

---

## 2.5.5 口碑看板

### 设计
读 `mv_reviews_dim` + ECharts：
- 维度分布图（柱状/雷达）：pro/con/净态度 per tag_category
- 车系列表（左侧 master）→ 选车系后右侧详情（维度聚合 + 原文样本）
- 筛选：车系 / 维度 / sentiment
- 内嵌对话 scope：当前筛选条件下数据集

### 验收
- E5 维度分布图渲染（舒适 con 69.2% 可见）
- 筛选联动图表
- 原文样本可点击查看

---

## 2.5.6 市场看板

### 设计
读 `mv_sales_monthly` + ECharts：
- 月度销量趋势图（折线，分年对比）
- 终端价趋势图（同版型对比，非加权平均）
- 版型结构图（堆叠柱状，retail by spec）
- 筛选：车系 / 年份 / 版型

### 验收
- E5 2025 vs 2026 月度趋势可见
- 同版型 tp 对比（26款530探索版 -12%）

---

## 2.5.7 配置看板

### 设计
读 `mv_config_spec`：
- 版型对比表（横向对比，关键配置项 × 版型）
- 年款分组（2024/2026/2027 不混）
- 赋分展示（A1 CLTC / B1 轮毂 等概念赋分）
- 筛选：车系 / 年款 / spec_id

### 验收
- E5 12 版型对比表可见（标注年款）
- 79311 = 2027款 550 智充启航版（非 530 远航版）

---

## 2.5.8 舆情看板

### 设计
嵌套舆情 Board（127.0.0.1:8000，21 dashboard GET 分 6 工具组）：
- **方案：反向代理 + iframe 嵌入**（开发期），上线期改造为 Prism 自绘 ECharts 读舆情 REST
- 6 工具组：sentiment_overview / trend / dimension / posts / competitive / events
- 筛选：vehicle_id / 时间范围

### 上云风险（来自 sentiment-board-survey）
- 舆情服务无鉴权 + 127.0.0.1 + CORS 本机 → sidecar 内网或加鉴权（D3.12）
- TikHub 单点依赖（红线#4，D3.14）

### 验收
- 舆情看板可嵌入显示
- 6 工具组数据可获取

---

## 2.5.9 报告交付物预览

### 设计
- md：直接渲染（react-markdown）
- excel：SheetJS 渲染表格
- word：mammoth.js 转 HTML 渲染
- 下载按钮

### 验收
- E5 报告 md 可预览
- 三种格式可下载

---

## 2.5.10 后端 API 网关

### 设计（FastAPI，与舆情 Board 栈一致）
```
prism-api/
├── main.py              # FastAPI 入口
├── routes/
│   ├── chat.py          # SSE 流式对话（pi SDK createAgentSession）
│   ├── dashboard.py     # 看板数据（读 mv_* + 舆情代理）
│   └── auth.py          # 浏览器本地 ID（无登录）
├── pi_bridge.py         # pi SDK 桥（createAgentSession + 工具注册 + hook）
└── ws.py                # WebSocket（状态栏实时推送）
```

- **chat SSE**：`POST /chat/stream` → pi SDK 流式响应
- **dashboard**：`GET /dashboard/{type}?series=...` → 读口径视图
- **pi_bridge**：封装 pi SDK，注册 2.2.3 的 3 工具 + 2.2.4 护栏 + 2.3 验证器
- **会话状态**：Redis（2026-09-30 拍板，多实例共享）

### 验收
- `POST /chat/stream` 可流式返回
- `GET /dashboard/reviews?series=银河E5` 返回 mv_reviews_dim 数据
- pi SDK 桥可创建会话

---

## 2.5.11 会话/用户身份

### 设计（2026-09-30 拍板）
- 浏览器 localStorage 生成 `usr_xxx`（无登录）
- 会话列表存 sidebar（服务端 Redis 持久化）
- 管理者操作弹密码（仅采集触发等）

### 验收
- 首次访问自动生成 usr_xxx
- 会话列表可切换
- 管理者操作弹密码

---

## 关键路径与里程碑（前端层）

```
M1 完成（口径视图）→ 启动 2.5.1-2.5.4（Shell + 对话 + 预览框架）
                  ↘ 2.5.5-2.5.7（三看板）并行
                  ↘ 2.5.10（API 网关）依赖 2.5.3+2.5.4
M2 完成（TS 工具）→ 2.5.3 对话区可联调
M3 完成（验证器）→ 2.5.3 状态栏联动
```

前端层与后端 2.2/2.3 并行，M1 完成即可启动 Shell + 静态看板。

---

## 验收（2.5 整层）

1. 三栏 Shell 可见，可拖拽调整
2. 输入"分析银河E5" → 流式对话 + 右侧口碑看板自动切 + 销量数据实时显示
3. 四个看板可手动切换查看固定视图
4. 报告 md 可预览下载
5. 浏览器本地 ID 生效，会话列表可切换

---

## 与 Hermes 的差异（避免照搬误区）

| Hermes | Prism 调整 |
|---|---|
| Electron 桌面 | Web 站（无 Electron 壳） |
| Python 后端本地 | FastAPI 后端 + pi SDK 桥 |
| 通用 agent | 汽车数据 agent（棱镜 SOP 注入） |
| 文件浏览器 | 无（Prism 不暴露文件系统） |
| Voice | 无（提纲排除） |
| 多 pane 复杂分割 | 三栏固定（左 sidebar / 中对话 / 右预览） |
| 主题 neutral | 同（可后续定制品牌色） |
