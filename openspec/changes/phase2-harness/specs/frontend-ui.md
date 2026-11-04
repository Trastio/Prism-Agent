# Spec · 2.5a 前端 UI 设计（基于设计稿 + 项目实际）

> 阶段2 · UI 设计层
> 上游：`UI设计/brand-spec.md`（色彩/字体/视觉规则，直接采用）+ `UI设计/hermes-agent-kanban.html`（布局原型）
> 依赖：2.2 口径视图（mv_*）+ 舆情 Board REST
> 关系：本 spec 是 frontend.md 2.5.1-2.5.9 的设计细化，frontend.md 2.5.10-2.5.11（API 网关/会话）归 pi-integration.md

---

## 一、设计稿采用策略

### 1.1 直接采用（brand-spec.md 全部）
- 色彩令牌（oklch）：`--bg --surface --fg --muted --border --accent --panel` + 派生令牌
- 字体栈：Display=Bodoni Moda（拉丁小标/品牌字）/ Body=PingFang SC / Mono=ui-monospace（指标数字）
- 5 条视觉规则：米白画布+白卡 1px 描边 / 主蓝每屏最多两次 / 中文标题 0 字距 / 图标 1.7px 描边 / 监测型用卡片图表+控制型用分组表单
- 对比度全部达标（已实测）

### 1.2 布局采用（HTML 稿结构）
```
┌─────────┬─────────────────────────────────────┐
│ 左侧栏   │ 顶部看板栏 [舆情|市场‖车型配置|口碑]    │
│ 264px   │ ─────────────────────────────────── │
│ 会话tab │ 看板内容区（KPI卡 + 图表 + 列表）       │
│ 车系tab │                                     │
│         │ ─────────────────────────────────── │
│ 会话列表 │ 底部 composer（基于当前看板提问）       │
│ 车系快切 │ 状态栏（网关/模型/三维度完成度/as_of）  │
└─────────┴─────────────────────────────────────┘
```

### 1.3 两处必须改（基于项目实际）

**改 1：配置看板含义**
- HTML 稿"配置"看板 = 系统配置（数据源/关键词/刷新/Agent行为）—— 这是 Hermes 通用模板，不对。
- Prism"配置看板" = **车型产品力配置**（座椅/隔音/轮毂/CLTC/赋分），读 mv_config_spec，是棱镜"配置=产品力"维度。
- 系统配置（数据源/刷新/Agent行为）挪到左侧栏齿轮入口，单独"设置"页。

**改 2：四看板字段对齐项目实际数据**
| 看板 | HTML 稿字段（通用模板） | 项目实际字段 | 数据源 |
|---|---|---|---|
| 舆情 | 声量/负面/渠道/趋势/情绪/议题/预警 | 声量趋势/情绪分布/维度热帖/竞品声量/事件预警 | 舆情 Board 21 GET |
| 市场 | 销量动向/价格/热度/关键词/竞品/渠道 | 月度销量/同比环比/版型结构/终端价(同版型)/竞品对比 | mv_sales_monthly |
| 车型配置 | （原是系统配置） | 版型对比表/年款分组/关键配置项/概念赋分 | mv_config_spec |
| 口碑 | 平均评分/评价数/NPS/评分分布/趋势/评价/主题 | 维度聚合(pro/con/净态度)/原文样本/打标覆盖率/口碑趋势 | mv_reviews_dim |

### 1.4 视图切换（已改：侧栏导航项，非顶部模式切换条）
**决策 1（2026-10-04 复审拍板）**：不做顶部"BI/Agent 模式切换条"。视图切换走 sidebar 导航项：
- 点 sidebar "Kanban" → 看板视图（board-bar + 看板内容 + composer + statusbar）
- 点 sidebar "新建会话" → 对话视图（全屏对话 + 右侧报告预览）
与 Hermes 原稿一致（Kanban 是 sidebar 导航项之一）。原 spec §1.4"顶部模式切换"作废。

---

## 二、四看板字段细化（基于阶段1 实测数据）

### 2.1 口碑看板（model_id=7650 E5 实测字段）
- **KPI 卡（3）**：
  - 口碑总数 1274 条（model_id=7650）
  - 标签总数 3235 个
  - 打标覆盖率 92.5%（1178/1274）
- **维度聚合表**（替代 HTML 稿"评分分布"）：
  - 9 维度（智能化/舒适/空间/续航/性价比/其他/外观/驾驶感受/内饰）
  - 每维：总数 / pro / con / con占比 / 净态度
  - 高亮：舒适 con 69.2%（8 命名维度最高）
- **原文样本卡**（替代 HTML 稿"最新评价"）：
  - 负面最集中维度 top3 原文（review_id + source_text + tag_name）
  - 例：k_5789427 '颠簸' / k_5833866 '隔音有点差点意思'
- **口碑趋势图**（areaChart）：近 12 周口碑量
- **"其他"桶提示**：276 条 con 82.6% 未拆解，UI 显示"待人工拆解"badge

### 2.2 市场看板（series='银河E5' 实测字段）
- **KPI 卡（3）**：
  - 当月零售（如 2026-08=4436）
  - 同比（1-8月 -42.9%）
  - 终端价降幅（同版型 26款530探索版 -12%）
- **月度销量趋势图**（barChart）：2025 vs 2026 对比，月末行
- **版型结构图**（hbars）：当月各版型 retail 占比
- **终端价趋势图**（areaChart）：同版型跨月 tp（非加权平均，标注"已控制版型"）
- **竞品对比表**（table）：同价位增程 SUV 7→8 月（零跑D19/理想L6/问界M7 等）

### 2.3 车型配置看板（series_id=7650 实测字段）
- **KPI 卡（3）**：
  - 在售版型数（sales_trim 24/26款 10 版型）
  - 配置快照版本（version=5, fetched_at）
  - 年款分布（2024/2026/2027 三年款，标注"2027款只在 config_snapshots"）
- **版型对比表**（table，横向）：12 spec_id × 关键配置项（座椅材质/侧窗隔音/前轮胎/CLTC/车机芯片）
  - 标注年款分组
  - 标注"79311 = 2027款 550 智充启航版（低配）"
- **赋分展示卡**：A1 CLTC=55000元 / B1 R18=2200元（concept_configs.json tiers）
- **"低配 vs 车系"提示**：侧窗隔音玻璃仅最低配 79311 无，中高配 2027款有前排——UI 显示"非车系级缺失"badge

### 2.4 舆情看板（嵌套舆情 Board）
- 开发期：iframe 嵌入舆情 Board（127.0.0.1:8000）
- 上线期：Prism 自绘 ECharts 读舆情 REST 21 GET，分 6 工具组：
  - sentiment_overview / trend / dimension / posts / competitive / events
- 字段：声量趋势 / 情绪分布 / 维度热帖 / 竞品声量 / 事件预警
- ⚠️ 上云风险：服务无鉴权+127.0.0.1+CORS本机 → sidecar 或加鉴权

---

## 三、底部 composer（BI 模式对话）

### 3.1 设计（HTML 稿 composer-row）
- 输入框 placeholder：`基于「{当前看板}」提问，或直接输入分析指令…`
- 附件按钮 / 模型选择 pill（Deepseek V4 Flash）/ 推理强度 pill / 语音（不上线可省）/ 发送

### 3.2 scope 锁定（BI 模式核心）
- 对话 scope = 当前看板筛选条件（车系/时间/维度等）
- 后端锁定：composer 提交时附带 `scope = { board, filters }`，pi SDK 会话工具白名单仅暴露当前看板对应工具
- 例：在口碑看板提问 → agent 只能调 query_reviews，不能调 query_sales

---

## 四、左侧栏

### 4.1 顶部 tab（HTML 稿 sb-tabs）
- **会话** tab：会话列表（浏览器本地 ID + Redis 持久化）
- **车系** tab（替代 HTML 稿"机器人"）：车系快速切换，调 resolve_series
  - 列表：最近查过的车系
  - 切换车系 → 全部看板刷新到该车系

### 4.2 导航项（HTML 稿 sb-nav）
- 新建会话 / 技能与工具 / 产物（报告交付物）/ 定时任务 / Kanban
- **新增齿轮"设置"入口**：系统配置（数据源连接/刷新/Agent行为/关键词）——从 HTML 稿"配置看板"挪来

### 4.3 会话列表
- 置顶 / 会话 / 定时任务 三组
- 每条：标题 + 时间 + 活跃 dot

---

## 五、状态栏（HTML 稿 statusbar，对齐 2.1.2 状态栏 hook）

| HTML 稿字段 | Prism 改成 |
|---|---|
| 网关就绪 | 数据源就绪（Atuohome + 舆情） |
| 本地模型已加载 | 当前模型（Deepseek V4 Flash） |
| GPU 1%·6G/12G | token 用量 / 成本（@narumitw/pi-usage） |
| 智能 / v0.17.6 | 三维度完成度（配置☐ 口碑☐ 销量☐）/ as_of |

---

## 六、技术落地（与 frontend.md 对齐）

### 6.1 组件映射
| HTML 稿组件 | React 实现栈 |
|---|---|
| .board-bar segmented control | shadcn Tabs（new-york） |
| .card / .kpi-value | shadcn Card + 自定义 KPI |
| .chart (手写 SVG) | **保留手写 SVG** 或迁 ECharts（舆情 Board 一致） |
| .hbars / .list / table | shadcn 自定义 |
| .composer | assistant-ui Composer |
| .switch / .select | shadcn Switch / Select |
| .empty | 自定义 EmptyState |

### 6.2 图表策略
- HTML 稿图表是手写 SVG（areaChart/barChart/hbars），轻量且可控。
- **决策**：口碑/市场/车型配置看板用手写 SVG（与设计稿一致，无 ECharts 依赖）；舆情看板上线期自绘用 ECharts（与舆情 Board 栈一致）。
- 开发期：舆情 iframe 嵌入，不重画。

### 6.3 主题
- brand-spec oklch 令牌直接进 Tailwind v4 CSS variables
- light/dark 双主题（HTML 稿已有 `prefers-color-scheme` 处理）

---

## 七、验收

1. brand-spec 色彩/字体/视觉规则在 React 项目落地，对比度达标
2. 三栏布局（左 sidebar / 中看板+composer / 状态栏）与 HTML 稿视觉一致
3. 四看板字段全部对齐项目实际数据（E5 实测值可复现）
4. 顶部模式切换（BI 看板 / Agent 对话）可切换
5. 底部 composer scope 锁定生效（在口碑看板提问只调 query_reviews）
6. 左侧栏"车系"tab 调 resolve_series 切换车系，看板刷新
7. 系统配置在齿轮入口，不在看板栏

---

## 八、与 frontend.md / pi-integration.md 的边界

| 本 spec (2.5a UI) | frontend.md (2.5) | pi-integration.md (2.5b) |
|---|---|---|
| UI 视觉 + 组件 + 字段 | 项目骨架 + Shell + 看板实现 | API 网关 + pi SDK 桥 + SSE + 会话 |
| 视觉契约 | 工程骨架 | 全链路集成 |

frontend.md 的 2.5.1-2.5.9 任务按本 spec 实现；2.5.10-2.5.11 归 pi-integration.md。
