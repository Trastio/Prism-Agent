# Prism-Agent UI 重构方案（v2 · 大刀阔斧）

> 生成：2026-10-04 ｜ 状态：**已定稿（用户已批准决策，见 §12）｜ 未动一行代码**
> 参考：① hermes 桌面 UI（`UI设计/hermes-agent-kanban.html` + 用户上传的 hermes 桌面截图）= 外壳 / 布局 / 交互 / 气质
> 　　　② Vehicle Sentiment Analysis Board（`frontend/static/css/style.css` 的 v3 Design Tokens）= 配色 / 排版 / 语义色
> 约束：`AGENTS.md` 红线与报告纪律六条；`openspec/changes/phase2-harness/specs/frontend-ui.md`
> 输入：`UI设计/Prism-Agent-看板UI-复审意见-2026-10-04.md`（两轮 11 条待修问题 → 本方案将其**重定位为约束条件**）

---

## 0. 一句话主张

把 Prism 从"**四个同构仪表盘并排**"改造成"**对象优先的棱镜分析工作台**"：

> **hermes 的桌面外壳**（侧栏 + 主区 + 单一 composer + 发丝状态栏）
> ＋ **Vehicle Sentiment 的暖纸编辑风配色**（terracotta 强调 + 蓝/红语义）
> ＋ **明确的三维度因果叙事**（配置 → 口碑 → 销量，舆情外挂）
> ＋ **可下钻的证据链**（每个数字可复算）

---

## 1. 现状诊断：为什么"设计逻辑 / 交互 / 美学"都不满

### 1.1 设计逻辑（最根本）
1. **四看板同构**——都是"Header + 3 KPI 卡 + 2 卡片"，看不出**棱镜三维度的差异**，更看不出"配置→口碑→销量"的因果链，看板退化成"四张一样的仪表盘"。
2. **对象缺位**——没有任何"当前车系"的显性锚点（车系选择器 CSS 都搬了却没渲染），看板不知道自己"在分析谁"，违反红线 7「对象身份前置核验」。
3. **口径与缺口无处安放**——as_of / coverage / 样本不足 / 数据缺口没有统一承载位，违反报告纪律第 2、4 条。
4. **"外挂"没被表达**——舆情本是与三维外挂、仅与销量交叉，却和三维平铺在同一排 tab 里，语义被抹平。
5. **两套 IA 没打通**——侧栏（会话/车系/产物/设置）与主区（四看板）是两个平行世界：看板的数字点不动、不能"带去对话"，对话里也回不到看板。

### 1.2 交互体验
6. **零下钻**——所有数字是死文本，无 hover 溯源、无点击展开、无"为什么是这个数"。
7. **无对象操作**——无车系搜索/切换、无时间范围、无对比选择；四个看板把车系写死成"银河E5 / 7650 / 2026"。
8. **无状态表达**——无加载骨架、无错误兜底、无 toast；失败时静默变空表（口碑曾整表拉不到）。
9. **无键盘可达**——`Ctrl N` 是假的，无命令面板、无 focus 管理。
10. **无响应式**——全站 0 条 `@media`，窄窗下卡片挤压、图表被压成 167×44px。

### 1.3 设计美学
11. **配色寡淡且无体系**——单一冷蓝 `oklch(52.7% .258 262.7)` 通吃，缺 VS 那种"暖纸 + terracotta + 蓝红语义"的**编辑风层次**。
12. **底部笨重**——composer 是"带框输入 + 一圈带边框 pill + 38px 蓝圆钮"，statusbar 又加边框底色，底部三段线，重。hermes 是**一个圆角软容器 + 无边框状态栏**。
13. **字体退化**——Bodoni Moda 走 Google Fonts，国内 2.6s 超时（`responseStatus=0`）→ 回退宋体，字标气质全失。

> 以上 11 条不再作为"补丁清单"，而是**新设计的硬约束**（见 §11 映射表）。

---

## 2. 设计原则

| # | 原则 | 落地含义 |
|---|---|---|
| P1 | **对象优先** | 全局维持一个"当前车系"上下文，所有维度共用；对象未核验不出数 |
| P2 | **棱镜因果轴** | 三维按 配置→口碑→销量 排列；舆情以"外挂"身份在视觉/交互上明确区分 |
| P3 | **证据可下钻** | 每个数字可展开 supported_by 行 ID / as_of / 口径；不可复算的数字不显示 |
| P4 | **双模同源** | 看板(BI) 与 对话(Agent) 共享同一"对象+维度"上下文，可从任意数字"带去对话" |
| P5 | **克制的暖** | 暖纸底 + 单一 terracotta 强调 + 蓝/红仅表语义，绝不做彩虹配色 |

---

## 3. 设计令牌（Tokens）：VS 配色 × Prism 语义

### 3.1 基础层（直接取自 Vehicle Sentiment v3 Tokens）

| Token | 值 | 用途 | 来源 |
|---|---|---|---|
| `--bg` | `#fafaf7` | 应用底（暖纸） | VS |
| `--surface` | `#ffffff` | 卡片 | VS |
| `--panel` | `#f4f1ec` | 侧栏 / 次级面板 | VS `--thead` |
| `--grid` | `#f0ece5` | 分隔/图表网格 | VS |
| `--border` | `#e7e5e0` | 发丝边框 | VS |
| `--ink` | `#15140f` | 主文字（暖墨） | VS |
| `--ink-2` | `#5a564e` | 次文字 | VS `--muted` |
| `--ink-3` | `#7a7670` | 三级/占位 | VS `--neu` |

### 3.2 强调与语义层

| Token | 值 | 用途 | 来源 |
|---|---|---|---|
| `--accent` | `#b85638` | **品牌/主交互色**（激活 tab、主按钮、eyebrow、focus 环） | VS |
| `--accent-d` | `#a44f33` | accent hover/active | VS |
| `--accent-bg` | `#fdf4ef` | accent 浅底（选中行、tag） | VS `--primary-bg` |
| `--pos` | `#2348b8` | **正面**（口碑 pro、舆情正、指标向好） | VS |
| `--neg` | `#9c2a25` | **负面**（口碑 con、舆情负、风险） | VS |
| `--neu` | `#7a7670` | 中性 | VS |
| `--warn` | `#b58a1a` | 警示（样本不足、待拆解） | VS `#d29922` 加深 |
| `--info` | `#3a6ea5` | 信息/链接 | VS |
| `--xt` | `#7C3AED` | **舆情外挂**标识色 | VS（subject 紫） |

### 3.3 形态层

| Token | 值 | 说明 |
|---|---|---|
| `--radius` | `16px` | 卡片圆角（VS 用 16） |
| `--radius-sm` | `10px` | 按钮/输入/小卡 |
| `--radius-pill` | `999px` | tab、chip、composer |
| `--shadow-hair` | `0 1px 0 var(--grid)` | 卡片发丝阴影（VS 同款，比投影更"编辑风"） |
| `--shadow-md` | `0 2px 8px rgba(21,20,15,.06)` | hover 抬升 |
| `--shadow-lg` | `0 12px 30px -26px rgba(0,0,0,.5)` | composer / 弹层 |
| 间距基准（设计刻度） | `4 / 8 / 12 / 16 / 20 / 24 / 32 / 36` | 8 基准；区块间距 36 |
| 间距基准（**原型实测**） | 卡片 `padding:17px 18px`；卡片栅格 `gap:14px`；内容区 `padding:24px 24px 30px`；区块标题 `margin:26px 0 12px`；侧栏 `264px`；抽屉 `400px` | 密度微调允许在设计刻度 ±2px 内浮动，见 §14.4 检查项 1 |

### 3.4 字体

| 角色 | 字体 | 用法 |
|---|---|---|
| UI 正文 | `Inter, "Noto Sans SC", system-ui` | 全部正文、表格、按钮（VS 同款） |
| Display | `Bodoni Moda`（**自托管**，弃 Google Fonts） | 仅 hero 字标 + `eyebrow/kicker` |
| 数字 | `Inter` + `font-feature-settings:'tnum'` | 所有数值列右对齐等宽（VS `.num`） |

### 3.5 维度标识色（**已定：方案 A**）

- **✅ 方案 A（已采纳 · 克制）**：不给维度配彩色。四维靠 **图标 + 文案 + 版面** 区分；颜色只留给语义（正蓝/负红/警示琥珀）与品牌 terracotta。最接近 hermes/VS 的原生气质。
- ⬜ 方案 B（未采纳 · 备查）：仅用于 tab 激活下划线 + kicker + 图标着色，全部取自 VS 现有色相：

| 维度 | 色 | 值 |
|---|---|---|
| 配置（产品力，主轴） | terracotta | `#b85638` |
| 口碑（需求验证） | 蓝 | `#2348b8` |
| 销量（市场结果） | 琥珀 | `#b58a1a` |
| 舆情（外挂） | 紫 | `#7C3AED` |

---

## 4. 布局架构（hermes 桌面外壳）

```text
┌──────────────────────────────────────────────────────────────────────────┐
│ ① 应用栏（可选，40px）：Prism 标 + 当前对象 chip + 全局命令(⌘K) + 主题/窗口 │
├────────────┬─────────────────────────────────────────────────────────────┤
│ ② 侧栏      │ ③ 看板栏 board-bar                                          │
│ 264px      │  [棱镜结论 | 舆情 ‖ 车型配置 · 口碑 · 销量]  [时间范围][示例数据]│
│            │  ───────────────────────────────────────────────────────────│
│ 会话|车系   │ ④ 内容区（board-scroll，max-width 1240，居中）              │
│ ─────────  │    · 看板头：kicker + 标题 + lede + 右侧对象/范围控件        │
│ 新建会话    │    · 区块 sec：KPI 行 / 图卡 / 表卡 / 列表卡 / 缺口卡        │
│ 棱镜工作台  │    · 一切数值可 hover 溯源、点击下钻                         │
│ 产物       │                                                             │
│ 设置       │                                                             │
│ ─────────  │                                                             │
│ 搜索框      │                                                             │
│ 会话/车系   │                                                             │
│ 列表        │                                                             │
│ ─────────  │                                                             │
│ 底部图标组  │ ⑤ composer（**仅对话视图**；看板视图无输入框）              │
│            │  ⊕ [提问…]  模型▾  推理▾  🎤  ⬤发送                        │
│            │ ⑥ 状态栏（发丝，无边框底色）                                 │
│            │  ●数据源就绪 · 模型 · 三维度：配置✓口碑◐销量○ · as_of       │
└────────────┴─────────────────────────────────────────────────────────────┘
                ⑦ 右抽屉（下钻证据 / 报告预览，可收，宽 360–420）
```

| 区 | 内容 | 关键点 |
|---|---|---|
| ① 应用栏 | 品牌 + **当前对象 chip**（车系）+ ⌘K | 让"对象优先"在全局可见；hermes 无此条 → 新增，但用同一暖纸底与发丝线，不抢戏 |
| ② 侧栏 | 顶部 tab（会话/车系）、导航（新建会话/棱镜工作台/产物/设置）、搜索 combobox、列表、底部图标 | 补 **设置入口真实可用**；列表接真实会话/车系 |
| ③ 看板栏 | 分段 tab + 右侧 时间范围 + 数据源 chip + 刷新 | 外挂舆情与三维之间**保留 `‖` 分隔**，强化"外挂"语义 |
| ④ 内容区 | 每维一版差异化版面 | 见 §6 |
| ⑤ composer | **仅存在于对话视图**：hermes 式**整体圆角容器**（border+radius14+shadow，内部无分隔线） | 模型/推理 pill 无边框透明，发送 32px 墨底圆钮；**看板视图不出现任何输入框** |
| ⑥ 状态栏 | 数据源/模型/三维度完成度/as_of | 发丝，无 border-top 与底色（对齐 hermes） |
| ⑦ 右抽屉 | 下钻证据、报告预览、工具活动 | 由"点击数字"触发；把现有 ChatView 的右栏升级复用 |

---

## 5. 交互模型

### 5.1 全局对象上下文（P1）
- 应用栏与每个看板头都显示**当前对象**（车系 chip），点击 → 车系 combobox（VS `.search-combobox` 样式）。
- 切换车系 → 通过 `resolve_series` 核验身份 → 四个看板**同时**刷新；未核验成功则显示"对象未确认"缺口卡，不出数（红线 7）。
- 对象状态写入 URL（`?series=…&board=…&range=…`），可分享、可回退。

### 5.2 下钻与证据链（P3）
- 数值 hover → 出现细下划线/游标；点击 → 右抽屉打开「证据」：
  - 该数字的 `supported_by`（真实行 ID / 主键，非通配符）
  - `as_of` 与口径（该维度的口径声明）
  - 「带去对话」按钮 → 切到对话并预填上下文
- 汇总行可展开到明细行（表格 `expandable`）。
- 不可复算 / 缺失 → **不出数字**，出缺口卡。

### 5.3 状态四态（统一）
| 态 | 表达 |
|---|---|
| 空 | 缺口卡：缺什么 + 附"缺什么能坐实" + 证据强度徽标 |
| 加载 | 骨架（skeleton），非"加载中…"文本 |
| 错误 | 行内错误卡 + 重试按钮 + toast（VS `.toast`） |
| 满 | 正常渲染 |

### 5.4 键盘与命令
- `⌘/Ctrl+K` 命令面板：跳看板 / 切车系 / 切时间范围 / 新建会话 / 打开设置。
- 侧栏 `Ctrl N` **真实生效**（补齐或移除角标，二选一，不留假角标）。
- 全站 `:focus-visible` 统一 2px `--accent` 环。

### 5.5 双模同源（P4）
- 侧栏切换 Kanban/对话 保持（**已锁定决策**，不改顶部模式条）。
- 但两者共享 URL 上的 `series / board / range`；从看板"带去对话"时，对话首条消息自动携带对象与维度。
- 对话的工具活动与看板的证据链**共用同一套来源展示组件**。

#### 5.5.1 对话入口的唯一性（**已定：看板不留对话模式**）
- **全局只有一个 composer，位于对话视图**。看板视图**不出现任何输入框**（避免与 Agent 模式重复、避免"这俩有啥区别"）。
- 看板的提问方式是 **选中即问（selection-based ask）**：点中任一 KPI / 图表 / 表格行 → 浮出 `问这个 ↗` → 打开**右抽屉**就地出一问一答（带 `supported_by / as_of / 口径`）。
- 就地问答**锁 scope**（当前对象 + 当前维度）、**单轮**、**不产生会话**（不进侧栏会话列表）。
- 出口：「**扩展为会话 ↗**」→ 把 scope + 上下文送去对话视图，升格为多轮（单向升级路径）。

### 5.6 响应式
- `≤1180`：双栏卡塌单栏；`≤900`：侧栏收起为图标条或抽屉、KPI 单列、看板栏换行；`≤600`：表格横向滚动或转卡片。
- 与 hermes 断点对齐（1200/900），但**必须真实存在**。

---

## 6. 四看板信息架构重设计

### 6.1 棱镜结论 Overview（**已定：新增为默认首格**）
> 理由：当前"四格平铺"缺一个**结论落点**。棱镜的价值在"三维交叉"，需要一个页把 配置→口碑→销量 的链路与舆情外挂并置，让 PM 一眼看到"谁在拖后腿"。
> **与早期"四格"决定的关系**：原始四格（舆情/市场/配置/口碑）**全部保留**，总览是**新增的第 5 格并置于最左**，不替换任何一格。若后续坚持严格四格，可将本页内容并入「配置」页顶部作为"棱镜结论头"。

- 区块：`棱镜链路`（配置→口碑→销量 三段箭头卡，各自带 1 个结论句 + 证据徽标）＋ `舆情外挂`（与销量交叉的 1 图）＋ `本期结论`（CLAIM：conclusion_text + supported_by + as_of + scope）＋ `缺口清单`。

#### 6.1.1 定义（一句话）
> 在**单一对象（一个车系）**下，把 配置 → 口碑 → 销量 的因果链与舆情外挂并置，输出**本期结论（CLAIM）＋缺口清单**的页面。

层级定位：

```text
证据层  配置 / 口碑 / 销量 / 舆情   ← 四个看板（明细、图表、表格）
判断层  棱镜结论                     ← 交叉 + 结论 + 缺口（本页）
追问层  对话                         ← 对结论做深挖
```

#### 6.1.2 它不是什么（防误读）

| 易误读成 | 实际 |
|---|---|
| 四看板的"缩略拼盘" | **不重复**各维度明细表 / 图 |
| 又一组 KPI 卡 | 放的是**判断**，不是**数据** |
| 第五个"维度" | 棱镜仍只有三维 + 1 外挂，本页只是"收口" |

#### 6.1.3 构成三件套（缺一不可）

| # | 构成 | 判据 |
|---|---|---|
| 1 | 链路 | 配置→口碑→销量 三段，每段**一句结论 + 一个证据徽标** |
| 2 | 交叉 | 舆情 × 销量 的**一处**交叉图，明确标注"外挂" |
| 3 | 落点 | CLAIM（conclusion_text + supported_by + as_of + scope）＋ 缺口清单 |

#### 6.1.4 三条硬边界

1. **不重复明细**——出现"12 版型矩阵""月度零售柱图"即越界（归配置页 / 销量页）。
2. **可下钻**——每条结论须能点开对应维度的证据（`supported_by`）。
3. **不全不下结论**——数据缺口时禁止出结论，转缺口卡（缺什么 + 缺什么能坐实 + 证据强度），呼应 `AGENTS.md` 的 `gap_assumption_pattern`。
4. **只并置、不归因**——本页只做"跨维度并置观察 + 假设"，**不做因果断言**（用"同期出现/待验证"，不用"导致"）；市场侧（销量）**不归因到产品力**（`AGENTS.md` discipline 3 / `<layered_rules>`）；**某维未查完不得用它维下结论**（discipline 5）。

#### 6.1.5 验收口诀

> 本页每一块内容都必须能回答"**所以呢？**"；答不出，就说明它该留在四看板里。

#### 6.1.6 命名

- ✅ **定名：棱镜结论**（用户拍板 2026-10-04）。点明本页放的是**判断（CLAIM）+ 缺口**，不会被误读成"四看板缩略拼盘"。
- 弃用：棱镜总览（"总览"歧义）／棱镜作战台（略口语，未采纳）。
- 改名成本：方案 §6.1 + 原型 1 处 label（`data-board` 不变）。

### 6.2 舆情（外挂 · 紫标识）
- **落地方式（已定）**：本期采用 **iframe 嵌现有舆情板**（`127.0.0.1:8000` 的 Vehicle Sentiment Analysis Board），把 tab 从"空壳"变成"有内容"；视觉统一（自绘对齐 Prism 令牌）**延后**到 P5 之后再评估，**不在本期范围**。
- **图表实现（已定）**：舆情图表 **单独用 ECharts**（沿用 spec §6.2 现文），与其余三看板的**手写 SVG** 并存；两套并存是**有意为之**（舆情板由既有 Vue+ECharts 应用承载，重写为 SVG 得不偿失）。
- 头控件：**时间范围**（近 24h/7d/30d，VS `.time-range/.preset-btn`）+ 渠道多选。
- KPI：声量总计 / 负面占比（**负红**）/ 覆盖渠道（`n/6 已连接`）。
- 区块：声量趋势（面积图）｜ 情绪分布（正负双色 hbar）｜ 渠道 pchips（VS `.pchip`，含 collecting/done/error 态）｜ 热点议题 list（热度条 + tag）｜ **风险横幅**（VS `.risk-banner`，左粗边 + 渐变）｜ 事件预警 list。
- 空态：**iframe 内应用未启动 / 未连接**（加载失败或超时）→ 缺口卡（而非现在的"未连接"死文案 + 全 `—` KPI），附"缺什么能坐实"（启动舆情板服务 / 配好数据源）。
- 交互边界：iframe 内为**独立应用**，其内部交互**不受 Prism 控制**；Prism 侧只保留外层容器（高度撑满、`allow` 白名单、超时兜底 + 缺口卡）。iframe 内**不承载** Prism 的"选中即问"（§5.5.1）。

### 6.3 配置（产品力 · 主轴）
- 头控件：**对象三级**（车系 → 年款 → 版型），默认"全部年款"。
- KPI：在售版型数（**从接口 distinct spec_id 计算**）/ 配置快照版本 / 年款分布。
- 区块：**横排版型×配置项矩阵**（12 个 spec_id × 关键配置项，列可横向滚动、可冻结首列）｜ 赋分展示卡（A1/B1 等，**来自配置源**）｜ 「非车系级缺失」缺口徽标（琥珀）。
- 修正：`SPECS` 硬编码 10 个 → 改为接口返回的 12 个（含 73943/73944）。

### 6.4 口碑（需求验证 · 蓝/红语义主场）
- 头控件：时间范围 + 维度筛选（默认"舒适"）。
- KPI：口碑总数 / 标签总数 / 打标覆盖率（**全部走接口**）。
- 区块：维度聚合表（pro 蓝 / con 红 / con% / 净态度，`净态度>0` 蓝、`<0` 红）｜ 维度总量分布 hbars（con% 高→红）｜ **原文样本卡**（review_id + 原文 + 情感 + 溯源）｜ 口碑趋势图 ｜ **「其他」桶待拆解**徽标。
- 双色纪律：全站**正面=蓝、负面=红**（沿用 VS 语义，替代当前绿/红）。

### 6.5 销量（市场结果）
- 头控件：年/月范围 + 口径切换（月末行 retail / 同版型 tp）。
- KPI：累计零售 / 终端价降幅（同版型）/ 在售版型（**全部走接口**）。
- 区块：月度零售柱图（峰值高亮）｜ 版型结构 hbars ｜ **竞品对比表**（车系/上月/本月/环比，环比涨跌用红蓝语义）｜ 终端价趋势图。

---

## 7. 数据与口径落地（清硬编码）

| 项 | 现状 | 目标 |
|---|---|---|
| 口碑 KPI | 写死 `1274/3235/92.5%` | 接口算 |
| 销量 KPI 环比 | 写死 `-42.9%` | 接口算 |
| 竞品对比表 | 疑似写死 4 行 | 接口 / 明确标"示例" |
| 配置赋分卡 | 写死 `55000/2200` | 配置源 tiers |
| 配置版型列表 | 硬编码 10 | 接口 12 |
| 舆情 KPI | 全 `—` | 接入舆情源 |
| 更新时间 / as_of | `--:--` / 写死日期 | 接口 `_meta.as_of` |
| 状态栏三维度完成度 | 写死 `☐` | 由本次查询实际命中维度驱动 |

**统一口径徽标**：每个数字区块右上角一个 `as_of · 口径 · 覆盖率` 的发丝小签，来自接口 `_meta`。

---

## 8. 组件清单

| 组件 | 新建/改造 | 说明 |
|---|---|---|
| `AppShell` | 改造 | 四区 grid：应用栏/侧栏/主区/右抽屉；行四段：看板栏/内容/composer/状态栏（**composer 仅对话视图渲染**） |
| `AskPopover`（选中即问） | 新建 | 看板内点中数值/卡片 → 浮层 `问这个 ↗` → 右抽屉就地问答（锁 scope / 单轮 / 不留痕） |
| `SettingsPage` | 新建 | 系统配置页（数据源 / 监测关键词 / 刷新策略），由侧栏「设置」进入 |
| `ObjectChip` + `SeriesCombobox` | 新建 | 对象上下文；VS combobox 样式 |
| `RangePicker` | 新建 | VS `.time-range` + preset |
| `SegTabs` | 改造 | 加 role=tab/tabpanel、外挂分隔语义、URL 驱动 |
| `KpiCard` | 改造 | 支持 delta 语义色、溯源下钻、缺口态 |
| `DataCard`（含 head/meta/foot） | 改造 | 统一 `as_of·口径·覆盖率` 小签 |
| `EvidenceDrawer` | 新建 | 右抽屉：supported_by / as_of / 口径 / 带去对话 |
| `GapCard` | 新建 | 缺口范式（缺什么 + 能坐实什么 + 证据强度） |
| `Skeleton` `ErrorCard` `Toast` | 新建 | 状态四态 |
| `RiskBanner` `Pchip` | 新建 | 舆情风险横幅、渠道 chip |
| `Charts`（手写 SVG） | 改造 | **配置 / 口碑 / 销量**三看板用；手写 SVG，色板换 VS；正负双色；响应式 |
| `SentimentFrame`（iframe 容器） | 新建 | **舆情**看板专用：嵌 `127.0.0.1:8000` 既有舆情板（内含 ECharts）；超时/加载失败 → `GapCard` |
| `Composer` | 改造 | 还原 hermes 单容器形态 |
| `StatusBar` | 改造 | 发丝、无底色、真实完成度 |
| `CommandPalette` | 新建 | ⌘K |
| `Typography` | 改造 | Inter + Noto Sans SC + 自托管 Bodoni Moda |

---

## 9. 实施路径（分阶段 · 仅范围，不含代码）

| 阶段 | 范围 | 产出 | 验收 |
|---|---|---|---|
| P0 设计底座 | 令牌落地（§3）、字体自托管、图标、`@media` 断点 | 一份可用的 `tokens` + 全局样式 | 表格/字体/响应式立刻不丑；窄窗不再挤压 |
| P1 外壳 | `AppShell` 四区、侧栏补齐（真实入口/列表）、看板栏、**仅对话视图的 composer**、状态栏 | hermes 式桌面外壳 | 三栏视觉对齐 hermes；底部不再笨重 |
| P2 对象上下文 | `ObjectChip`/`SeriesCombobox`/`RangePicker`、URL 状态、`resolve_series` 接入 | 对象优先 | 切车系四看板同刷；对象 chip 全局可见 |
| P3 四看板重设计 | §6 各维版面 + 图表 + 列表 + 缺口卡；**舆情改 `SentimentFrame`（iframe 嵌 `127.0.0.1:8000`）** | 四版差异化看板 | 四维不再同构；舆情不再空壳（iframe 有内容或缺口卡） |
| P4 证据链 | `EvidenceDrawer`、**`AskPopover`（选中即问）**、数值溯源、带去对话、双模上下文 | 可下钻 | 任一数字可查 supported_by + as_of；看板有提问入口 |
| P5 数据接入 | §7 清硬编码、口径徽标、状态四态 | 数据可信 | 无写死数字；缺口如实标注 |

> 每阶段独立可验收；P0→P1 见效最快（"怪"的两大来源：响应式 + 底部）。

### 9.1 P0–P1 文件级清单（待执行 · 本轮不动代码）

| 阶段 | 文件 | 动作 |
|---|---|---|
| P0 | `prism-web/src/styles.css` | 全量替换 §3 令牌；补 `@media`(≤1180 / ≤900 / ≤600)；发丝阴影；`.num` 等宽右对齐；统一 `:focus-visible` 环 |
| P0 | `prism-web/index.html` | 移除 Google Fonts 在线链接；改引本地 `@font-face` |
| P0 | `prism-web/src/assets/fonts/`（新建） | 落地 Bodoni Moda / Inter / Noto Sans SC 本地字体文件（镜像下载） |
| P0 | `prism-web/src/components/Icons.tsx` | sprite 首帧预注入（消除图标闪帧） |
| P1 | `prism-web/src/App.tsx` | 重建为 `AppShell` 四区模型（应用栏 / 侧栏 / 主区 / 右抽屉）；**修 ChatView 行模型塌陷** |
| P1 | `prism-web/src/components/Sidebar.tsx` | 补真实「设置」入口；`Ctrl N` 二选一（生效或去角标）；列表接真实数据 |
| P1 | `prism-web/src/components/KanbanView.tsx` | 看板栏加 `role=tab/tabpanel`、外挂 `‖` 语义、URL 驱动；**移除看板 composer**（看板底部只留状态栏）；statusbar 发丝化 + 真实完成度 |
| P1 | `prism-web/src/components/dashboards/*` | 暂保留现有内容，仅套用新令牌（内容重设计放 P3） |

> 注：P1 会改动 `App.tsx` 的布局骨架（核心结构），实施前会先说明改动点。

---

## 10. 验收标准

1. 视觉：与 hermes 外壳气质一致（暖纸/发丝/单容器 composer/细状态栏），配色遵守 §3 令牌；**看板视图不得出现输入框**。
2. 逻辑：每个看板有**对象锚点**与**维度叙事**；舆情外挂身份明确。
3. 交互：数值可下钻、可带去对话；四态齐备；键盘可用；URL 可分享。
4. 响应式：1180/900 断点真实生效（图表不再被压扁）。
5. 数据：零写死数字；每个数字带 `supported_by + as_of`；缺口走缺口卡。
6. 纪律：符合 `AGENTS.md` 红线 1/6/7 与报告纪律六条。
7. 舆情：tab 打开**有内容**（iframe 载入既有舆情板）或**明确缺口卡**（服务未启动）；不得再是"未连接"死文案 + 全 `—`。
8. 主题：**本期仅 light**；不做暗色（dark 延后，spec §6.3 已改注）。

---

## 11. 旧问题 → 新方案映射（把 11 条 bug 重定位为约束）

| 旧问题 | 新方案中的对应设计 |
|---|---|
| 无响应式 `@media` | §3.3 间距/断点 + §5.6 |
| 对话视图塌陷 | §4 区⑦ / `AppShell` 行模型重定义 |
| 舆情 tab 空壳 | §6.2 |
| 配置表少 2 版型 | §6.3 修正 |
| 无 Settings 组件 | §4 区② 补真实设置入口 |
| 看板页头右半边空 | §4 区③ + §5.1 对象/范围控件 |
| 底部未照 hermes | §4 区⑤⑥ + §3.3（**composer 仅对话视图**，见 §5.5.1） |
| 字体 CDN 不可达 | §3.4 自托管 |
| KPI 硬编码 | §7 |
| 死交互/占位 | §5.3 §5.4（真实状态与键盘） |
| a11y role / 图标闪帧 / color-scheme | §8 组件清单（role、sprite 预注入） |

---

## 12. 已定决策（用户已批准 · 2026-10-04）

| # | 决策 | 结论 | 落点 |
|---|---|---|---|
| 1 | 配色 | ✅ **方案 A**（克制 · 单强调 terracotta），方案 B 仅备查 | §3.5 |
| 2 | 棱镜结论 | ✅ **新增第 5 格并置于最左**；原四格全部保留 | §6.1 |
| 3 | 语义色 | ✅ 统一 **正面 = 蓝 `#2348b8` / 负面 = 红 `#9c2a25`**，替代当前绿/红 | §3.2 |
| 4 | 字体 | ✅ **自托管 Bodoni Moda**（经清华/阿里镜像下载，禁用 Google Fonts 在线） | §3.4 |
| 5 | 实施顺序 | ✅ **P0→P1 先行**（先解决响应式 + 底部），再推进 P2–P5 | §9 |
| 6 | 对话入口 | ✅ **看板不留对话模式**；全局唯一 composer 在对话视图，看板改"选中即问 → 右抽屉" | §5.5.1 |
| 7 | 舆情落地 | ✅ **开发期 iframe 嵌现有舆情板**（`127.0.0.1:8000`）；视觉自绘对齐**延后**，不在本期 | §6.2 |
| 8 | 第 5 格命名 | ✅ **棱镜结论**（弃「棱镜总览」/「棱镜作战台」） | §6.1.6 |
| 9 | 图表实现 | ✅ **舆情单独用 ECharts**（沿 spec 现文）；其余三看板手写 SVG；**两套并存是有意为之** | §6.2 / §8 |
| 10 | 暗色主题 | ✅ **本期只做 light**；dark 延后（spec §6.3 需改注） | §3 / §12.1 |

> 遗留小项见 §12.1（spec 改注）与 §12.2（未收敛关闭清单，✅ 已全部关闭）。**注**：P1 移除看板 composer 后，看板的提问入口要到 P4 的 `AskPopover` 才补齐（过渡期看板无提问入口，可接受）。

#### 12.1 spec `frontend-ui.md` 改注清单（已逐条核实行号）

| spec 条款 | 现状 | 处置 |
|---|---|---|
| §1.1（L14 字体 Body=PingFang SC / Mono=ui-monospace） | 与 §3.4（Inter + `tnum`）冲突 | **改 spec** |
| §1.1（L15"主蓝每屏最多两次"） | 与 §3.2（terracotta 强调 + 蓝/红语义）冲突 | **改 spec** |
| §1.2（L21 / L26"底部 composer（基于当前看板提问）"） | 与 §5.5.1（看板不留 composer）冲突 | **改 spec** |
| §三（L101-111 底部 composer · BI 模式对话） | 同上；scope 锁定语义保留，但迁移为"对话视图 composer + 看板选中即问" | **改 spec** |
| §七.4（L172"顶部模式切换…可切换"） | §1.4 已改为侧栏，§七验收项未同步 | **改 spec** |
| §七.5（L173 composer scope 锁定） | 需限定为"仅对话视图 composer + 看板选中即问" | **改 spec** |
| §2.3（L83"10 版型" vs L86"12 spec_id"） | **spec 自身矛盾**；接口实测为 12 | **改 spec**（统一为 12） |
| §6.2（L158 舆情用 ECharts） | 与 §8 手写 SVG 取向不一致 | **不改 spec** ✅（L158 保留 ECharts；§8 已补 `SentimentFrame`，两套并存口径已写入 §6.2） |
| §6.3（L163 light/dark 双主题） | 方案本期未含暗色 | **改 spec** ✅（限定"本期仅 light，dark 延后"） |

> 已确认**无需**改注：§1.4（L46-50）已是"侧栏切换"，与决策 1 一致（此前 §12 的指认已作废）。

#### 12.2 未收敛关闭清单（✅ 已全部关闭 · 2026-10-04）

| # | 未决项 | ✅ 结论 | 落点 |
|---|---|---|---|
| A | 舆情 tab 落地方式 | **iframe 嵌现有舆情板**（`127.0.0.1:8000`）；自绘对齐延后，不在本期 | §6.2 / §8 `SentimentFrame` |
| B | 第 5 格命名 | **棱镜结论** | §6.1.6 |
| C | 舆情图表实现 | **舆情单独用 ECharts**（沿 spec 现文）；其余三维手写 SVG；两套并存为有意为之 | §6.2 / §8 |
| D | light/dark 双主题 | **本期只做 light**，dark 延后 | §3 / §12.1（spec §6.3 改注） |

> **收敛判定**：§12.2 四项已关闭；§12.1 九条 spec 改注方向已定（其中 §6.2 **不改**、其余 **改**）。方案层面**已收敛**，可进入执行（P0 → P1）。

---

## 13. 参考与文件索引

| 用途 | 路径 |
|---|---|
| hermes 参照稿（外壳/组件 CSS/断点） | `UI设计/hermes-agent-kanban.html` |
| hermes 桌面截图（气场参照） | 用户上传：`paste-files/9a6045d7-…-image.png` |
| **配色来源**（v3 Design Tokens） | `C:\Users\<you>\Desktop\Agent项目\Vehicle Sentiment Analysis Board\frontend\static\css\style.css` |
| 两轮问题诊断 | `UI设计/Prism-Agent-看板UI-复审意见-2026-10-04.md` |
| UI 规格 | `openspec/changes/phase2-harness/specs/frontend-ui.md` |
| 全局 SOP / 红线 | `AGENTS.md` |
| 现有实现 | `prism-web/src/**`（`App.tsx` / `styles.css` / `components/*`） |
| **原型（本方案的可视化实现参考）** | `UI设计/prism-ui-prototype-v2.html`（详见 §14，全文快照见附录 A） |

---

## 14. 原型（prism-ui-prototype-v2.html）

> 定位：**本方案的可视化实现参考**——把 §3 令牌、§4 外壳、§5 交互、§6 四看板 IA 落成一份单文件、零外部请求的 HTML。
> 本节用"内容清单（§14.2）+ 决策对照（§14.3）+ 同步契约（§14.4）"保证**方案说了什么 ↔ 原型做了什么**可逐条核对；原型全文快照见**附录 A**。

### 14.1 打开方式

| 项 | 值 |
|---|---|
| 文件 | `UI设计/prism-ui-prototype-v2.html`（单文件自包含） |
| 本地服务 | 在 `UI设计/` 目录下执行 `python -m http.server 8899 --bind 127.0.0.1` |
| 地址 | `http://127.0.0.1:8899/prism-ui-prototype-v2.html` |
| 外部依赖 | **0**（字体栈 / 图标 sprite / 图表 / 脚本全部内联，离线可开） |
| 改后查看 | 必须 **Ctrl+Shift+R 硬刷新**，否则浏览器读旧缓存（本轮已踩过一次） |
| 内嵌可行性 | 原型内**不含三反引号序列**，故附录 A 可按 `html` 围栏原文嵌入 |

### 14.2 原型内容清单

**视图与容器**

| 容器 | 内容 |
|---|---|
| `.app` | 四区：`① appbar` / `② sidebar` / `.main` / `⑦ drawer`（+ `#drawerScrim` 遮罩） |
| `① appbar` | `Prism Agent` 字标 + **对象 chip**（`#objChip`：银河E5 · 2026 款 · resolve_series 已核验）+ `⌘K` 命令条（`#cmdk`）+ 主题/窗口按钮 |
| `② sidebar` | 顶 tab（会话/车系）、主导航（新建会话 `Ctrl N` / 棱镜工作台 / 产物 / 设置）、搜索框、置顶+会话列表、车系列表、底部图标组 |
| `.main` | 行模型**两行**：视图（撑满）/ 状态栏；composer 已移入 `#viewChat` |
| `#viewBoard` | 行模型**两行**：看板栏（③）/ 内容区（④） |
| `#viewChat` | 行模型**两行**：对话滚动区 / composer（⑤） |
| `⑦ #drawer` | 宽 400px 右抽屉：证据 + **就地问答**；由「选中即问」触发 |

**③ 看板栏**：`棱镜看板` 字标 + `[棱镜结论 | 舆情 ‖ 车型配置 | 口碑 | 销量]`（舆情与三维之间保留 `‖` 外挂分隔）+ 时间范围 select + `示例数据` chip + `as_of` + 刷新钮

**④ 五个看板**

| 看板 | id | 区块 |
|---|---|---|
| **棱镜结论**（默认首格） | `board-overview` | 棱镜链路（配置→口碑→销量 三卡 + 箭头，各带结论句 + 证据徽标）+ 舆情外挂×销量交叉图 + 本期结论 CLAIM 卡（supported_by / as_of / scope / 覆盖率）+ 缺口清单（2 项，带"缺什么能坐实"） |
| 舆情（外挂） | `board-sentiment` | 风险横幅 + KPI×3（声量总计 / 负面占比 / 覆盖渠道）+ 声量趋势 + 情绪分布 + 渠道采集状态（pchip 三态 + 重试）+ 热点议题 + 事件预警 |
| 车型配置 | `board-config` | KPI×3（在售版型数 / 配置快照版本 / 年款分布）+ 版型×配置项矩阵（12 spec_id）+ 赋分展示卡 + 关键配置项覆盖 |
| 口碑 | `board-reviews` | KPI×3（口碑总数 / 标签总数 / 打标覆盖率）+ 维度聚合表（pro 蓝 / con 红 / 净态度）+ 维度总量分布 + 原文样本 + 口碑趋势 |
| 销量 | `board-sales` | KPI×3（累计零售 / 终端价降幅 / 在售版型）+ 月度零售 + 版型结构 + 竞品对比（涨蓝跌红）+ 终端价趋势 |

**`#viewChat` 对话视图**：空态 hero（`Prism Agent` 巨型衬线字标 + 对象 chip + 4 条建议胶囊 + 「查看示例对话」）↔ 有消息态（用户命题 → Agent 正文 → 嵌看板卡 → 证据徽标行 → 工具活动折叠 → CLAIM 卡）

**⑤ composer（仅对话视图）**：附件 + `scope 锁定` pill + 输入框 + `Deepseek V4 Flash` pill + `推理 High` pill + 语音 + 墨底发送钮

**⑦ 证据抽屉**：数值 + `supported_by` / `as_of` / 口径·scope / 覆盖率 + 可复算片段 + 假设与证据强度　**＋ 就地问答块**（`scope 已锁定 · 单轮` 药丸 + "不产生会话 · 不进侧栏" + 输入框 + `问这个 ↗` + 就地回答区）＋ 底部 `关闭` / **`扩展为会话 ↗`**

**⚠️ 原型中与方案"表述不同"的实现细节（已在方案内有承接阶段，非矛盾）**

| # | 原型现状 | 方案条款 | 处置 |
|---|---|---|---|
| 1 | 舆情看板为**手写 SVG 演示图** | §6.2 决策 7/9：**iframe 嵌 `127.0.0.1:8000` 现有舆情板（ECharts）** | 原型此处是"自绘意图"演示；**P3 换为 `SentimentFrame`**，届时同步原型 |
| 2 | 字体栈仅声明 `"Bodoni Moda"`（无 `@font-face`，离线回退 Didot/Georgia/Songti） | §3.4 决策 4：**自托管字体文件** | 原型为**离线单文件**故不内嵌字体二进制；**P0 落地本地 `@font-face`** |
| 3 | `#themeBtn` 为占位（仅 toast） | §12 决策 10：**本期只做 light** | 一致（dark 不做）；占位按钮不算矛盾 |
| 4 | 四态仅实现**缺口态** + hover/focus/过渡 | §5.3 四态（空/加载/错误/满） | **P5 补 `Skeleton` / `ErrorCard`**；缺口卡已符合"缺口如实标注" |
| 5 | 演示数值（1,284 / 12.6% / -42.9% 等） | §7 清硬编码 | 原型**通篇挂「示例数据」chip**，与 §7 不冲突 |
| 6 | `#cmdk` 命令条、侧栏 `Ctrl N` 角标均为**视觉占位**（无键盘监听） | §5.4 键盘与命令（`⌘/Ctrl+K` 命令面板；`Ctrl N` 生效或去角标） | **P1 实现 `CommandPalette`**；届时同步原型（去掉假角标或接上真监听） |
| 7 | 卡片间距为 `gap:14px` / `padding:17px 18px` | §3.3 设计刻度 `4/8/12/16/20/24/32/36` | 已写入 §3.3「原型实测」行，属**刻度内的密度微调**，非矛盾 |

### 14.3 决策（§12）× 原型 对照

| 决策 | 原型体现 | 状态 |
|---|---|---|
| 1 配色方案 A（单强调 terracotta） | `:root` 无维度彩条，强调只用 `--accent` | ✅ |
| 2 棱镜结论为第 5 格且置最左 | `tab-overview` 首位 + `board-overview` 默认 `is-active` | ✅ |
| 3 正蓝 / 负红 | `--pos #2348b8` / `--neg #9c2a25`，用于 delta、hbar、竞品环比、负面占比 | ✅ |
| 4 自托管字体 | 字体栈已声明，字体**文件**未内嵌（见 §14.2 差异 2） | ⚠️ 部分 |
| 5 P0→P1 先行 | 阶段划分不是原型的表达对象 | — |
| 6 **看板不留对话模式** | `composer-row` 位于 `#viewChat` **内部**；看板视图底部仅状态栏。判据：**`#viewBoard` 子树内 `<input>` 数 = 0**（`#askInput` 属 `#drawer`，不计入） | ✅ |
| 7 舆情 iframe | 未实现（见 §14.2 差异 1） | ⚠️ 待 P3 |
| 8 命名「棱镜结论」 | tab 标签 / 看板标题 / `LABEL.overview` 三处一致 | ✅ |
| 9 舆情图表用 ECharts | 未实现（原型为 SVG 演示，见 §14.2 差异 1） | ⚠️ 待 P3 |
| 10 本期只做 light | 全站单套 light 令牌 | ✅ |

### 14.4 单一事实源与同步契约（防矛盾）

- **规范源** = **本方案 md**（§3 令牌 / §5.5.1 交互 / §6 IA / §12 决策）；原型是**实现参考**，附录 A 是原型的**只读快照**。
- **一致性规则**：任何涉及「决策 / 令牌 / IA / 交互」的变更，必须**同一轮内同时改 ① 本 md ② 原型文件 ③ 附录 A 快照**；只改一边视为未完成。
- **冲突裁决**：三者不一致时 **以本 md 为准**（决策只在 md 定稿），立即回写原型与快照。
- **每次改动后的检查清单**：
  1. §3 令牌值 ↔ 原型 `:root`（L14–27）逐项相同？
  2. §4 线框的 tab 标签与顺序 ↔ 原型看板栏相同？
  3. §5.5.1（composer 仅在对话视图）仍成立？判据：**`#viewBoard` 子树内 `<input>` 数 = 0**（抽屉 `#askInput` 属 `#drawer`，不计入）
  4. §12 决策 1–10 ↔ §14.3 对照表逐行仍成立？
  5. §14.2「已知差异」表哪几项已关闭？关闭后必须从表中删行。
  6. 附录 A 快照已重新生成、字节数与时间戳已更新？

---

## 附录 A · 原型全文快照（`prism-ui-prototype-v2.html`）

> 快照时间：2026-10-04 ｜ 源文件：`UI设计/prism-ui-prototype-v2.html`
> 源文件度量：**112,404 字节 / 1,745 行 / 103,450 字符（UTF-8）**
> 性质：**只读快照**，目的是让本 md **单文件自洽**（可离线阅读、归档、交付）。
> 冲突裁决：本附录与原型文件不一致时，**以原型文件为准**，并按 §14.4 检查清单回写本附录。
> 生成方式：由原型文件原文读取后原样内嵌（未做任何改写），故附录内即为**原型当前全量代码**。

<details>
<summary>展开查看完整单文件 HTML（约 112 KB / 1,745 行）</summary>

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prism-Agent · 棱镜分析工作台（高保真原型 v2）</title>
<style>
/* =====================================================================
   Prism-Agent UI 原型 v2 · 单文件自包含
   设计令牌：Vehicle Sentiment v3 × Prism 语义（正面=蓝 / 负面=红）
   外壳参照：hermes 桌面壳（暖纸 / 发丝 / 单容器 composer / 细状态栏）
   本文件为「设计原型」，所有数值均为示例数据，不联网、可离线打开。
   ===================================================================== */
:root{
  --bg:#fafaf7; --surface:#ffffff; --panel:#f4f1ec; --grid:#f0ece5; --border:#e7e5e0;
  --ink:#15140f; --ink-2:#5a564e; --ink-3:#7a7670;
  --accent:#b85638; --accent-d:#a44f33; --accent-bg:#fdf4ef;
  --pos:#2348b8;  /* 正面=蓝 */
  --neg:#9c2a25;  /* 负面=红 */
  --warn:#b58a1a; --info:#3a6ea5; --xt:#7C3AED;
  --radius:16px; --radius-sm:10px; --radius-pill:999px;
  --shadow-hair:0 1px 0 var(--grid);
  --shadow-md:0 2px 8px rgba(21,20,15,.06);
  --shadow-lg:0 12px 30px -26px rgba(0,0,0,.5);
  --font-ui:Inter,"Noto Sans SC",system-ui,"Microsoft YaHei",sans-serif;
  --font-display:"Bodoni Moda",Didot,Georgia,"Songti SC",SimSun,serif;
}
*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0;background:var(--bg);color:var(--ink);
  font-family:var(--font-ui);font-size:14px;line-height:1.6;
  -webkit-font-smoothing:antialiased;
}
button{font-family:inherit;color:inherit;cursor:pointer}
h1,h2,h3{margin:0;font-weight:600}
a{color:var(--info)}
svg{display:block}
.sprite{position:absolute;width:0;height:0;overflow:hidden}
.ico{width:16px;height:16px;flex:none;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.num{font-variant-numeric:tabular-nums;letter-spacing:-.01em}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}
[hidden]{display:none !important}

/* ---------------- 应用外壳 ---------------- */
.app{
  display:grid;
  grid-template-columns:264px minmax(0,1fr);
  grid-template-rows:40px minmax(0,1fr);
  height:100vh;overflow:hidden;
}

/* ① 应用栏 40px */
.appbar{
  grid-column:1/-1;display:flex;align-items:center;gap:14px;
  padding:0 14px;background:var(--bg);border-bottom:1px solid var(--border);
  min-width:0;
}
.brand{display:flex;align-items:center;gap:8px;font-family:var(--font-display);font-size:15px;letter-spacing:.02em;white-space:nowrap}
.brand .prism-dot{width:11px;height:11px;transform:rotate(45deg);background:var(--accent);border-radius:2px;flex:none}
.brand small{font-family:var(--font-ui);font-size:10.5px;letter-spacing:.18em;text-transform:uppercase;color:var(--ink-3)}
.obj-chip{
  display:inline-flex;align-items:center;gap:7px;height:26px;padding:0 10px;
  background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-pill);
  font-size:12.5px;transition:border-color .16s ease,background .16s ease;
}
.obj-chip:hover{border-color:var(--accent);background:var(--accent-bg)}
.obj-chip b{font-weight:600}
.obj-chip .ico{width:13px;height:13px;color:var(--ink-3)}
.appbar-spacer{flex:1}
.cmdk{
  display:inline-flex;align-items:center;gap:8px;height:28px;padding:0 12px;min-width:200px;
  background:var(--panel);border:1px solid var(--border);border-radius:var(--radius-sm);
  color:var(--ink-3);font-size:12.5px;transition:border-color .16s ease,background .16s ease;
}
.cmdk:hover{border-color:var(--ink-3);background:var(--surface)}
.cmdk .ico{width:14px;height:14px}
.cmdk kbd{margin-left:auto;font-family:var(--font-ui);font-size:11px;color:var(--ink-3);background:var(--surface);border:1px solid var(--border);border-radius:5px;padding:0 5px}
.appbar-tools{display:flex;align-items:center;gap:4px}

/* ---------------- ② 侧栏 264px ---------------- */
.sidebar{
  display:flex;flex-direction:column;min-height:0;
  background:var(--panel);border-right:1px solid var(--border);font-size:13px;
}
.sb-top{display:flex;align-items:center;gap:8px;padding:8px 10px}
.icon-btn{
  display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;
  border:1px solid transparent;border-radius:9px;background:transparent;color:var(--ink-2);
  transition:background .16s ease,color .16s ease,border-color .16s ease;
}
.icon-btn:hover{background:var(--surface);color:var(--ink)}
.sb-tabs{display:inline-flex;gap:2px;padding:2px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-pill)}
.sb-tab{border:0;background:transparent;color:var(--ink-2);font-size:12px;padding:0 12px;height:24px;border-radius:var(--radius-pill);transition:background .16s ease,color .16s ease}
.sb-tab:hover{color:var(--ink)}
.sb-tab.is-on{background:var(--accent);color:#fff}
.sb-nav{display:flex;flex-direction:column;gap:1px;padding:4px 8px 8px}
.sb-item{
  display:flex;align-items:center;gap:10px;width:100%;min-height:34px;padding:0 9px;
  border:0;border-radius:9px;background:transparent;font-size:13px;color:var(--ink);text-align:left;
  transition:background .16s ease,color .16s ease;
}
.sb-item .ico{color:var(--ink-3)}
.sb-item:hover{background:var(--surface)}
.sb-item.is-active{background:var(--surface);box-shadow:var(--shadow-hair)}
.sb-item.is-active .ico{color:var(--accent)}
.sb-item kbd{margin-left:auto;font-family:var(--font-ui);font-size:10.5px;color:var(--ink-3);background:var(--bg);border:1px solid var(--border);border-radius:5px;padding:1px 5px}
.sb-search{display:flex;align-items:center;gap:8px;margin:0 14px 10px;padding:0 10px;height:32px;background:var(--surface);border:1px solid var(--border);border-radius:9px;color:var(--ink-3)}
.sb-search input{flex:1;min-width:0;border:0;background:transparent;outline:none;font:inherit;font-size:12.5px;color:var(--ink)}
.sb-search input::placeholder{color:var(--ink-3)}
.sb-search:focus-within{border-color:var(--accent)}
.sb-scroll{flex:1;min-height:0;overflow-y:auto;padding:0 8px 8px}
.sb-scroll::-webkit-scrollbar,.board-scroll::-webkit-scrollbar,.matrix-wrap::-webkit-scrollbar{width:9px;height:9px}
.sb-scroll::-webkit-scrollbar-thumb,.board-scroll::-webkit-scrollbar-thumb,.matrix-wrap::-webkit-scrollbar-thumb{background:#d8d4cc;border:3px solid transparent;background-clip:padding-box;border-radius:99px}
.sb-group{margin-bottom:12px}
.sb-label{display:flex;align-items:center;gap:7px;padding:6px 8px 4px;font-size:11px;letter-spacing:.04em;color:var(--ink-3)}
.sb-label .ico{width:13px;height:13px}
.sb-list{list-style:none;margin:0;padding:0}
.sb-row{display:flex;align-items:center;gap:8px;min-height:30px;padding:0 8px;border-radius:8px;color:var(--ink);transition:background .16s ease;cursor:pointer}
.sb-row:hover{background:var(--surface)}
.sb-row-title{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12.5px}
.sb-row-time{margin-left:auto;font-size:11px;color:var(--ink-3);flex:none}
.sb-row .dot{width:5px;height:5px;border-radius:99px;background:var(--accent);flex:none}
.sb-month{padding:6px 8px 2px;font-size:11.5px;color:var(--ink-3)}
.sb-foot{display:flex;align-items:center;gap:2px;padding:8px 10px;border-top:1px solid var(--border)}

/* ---------------- 主区 ---------------- */
/* 行模型：视图（撑满） / 状态栏（发丝）。composer 已移入对话视图，看板视图不出现输入框 */
.main{display:grid;grid-template-rows:minmax(0,1fr) auto;min-width:0;background:var(--bg)}

/* ③ 看板栏 */
.board-bar{
  display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;
  padding:11px 24px;background:var(--bg);border-bottom:1px solid var(--border);
  transition:box-shadow .2s ease;
}
.board-bar.is-scrolled{box-shadow:0 6px 18px -14px rgba(0,0,0,.5)}
.bar-left{display:flex;align-items:center;gap:12px;min-width:0}
.bar-brand{display:inline-flex;align-items:center;gap:7px;font-size:12px;letter-spacing:.04em;color:var(--ink-3);white-space:nowrap}
.bar-brand .ico{width:14px;height:14px}
.seg{display:flex;align-items:center;gap:2px;padding:3px;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius-pill);flex-wrap:wrap}
.seg-btn{
  display:inline-flex;align-items:center;gap:8px;height:32px;padding:0 15px;border:0;
  border-radius:var(--radius-pill);background:transparent;color:var(--ink-2);font-size:13px;
  transition:background .18s ease,color .18s ease;
}
.seg-btn:hover{color:var(--ink);background:var(--surface)}
.seg-btn[aria-selected="true"]{background:var(--accent);color:#fff}
.seg-btn[aria-selected="true"]:hover{background:var(--accent-d)}
.seg-btn .ico{width:14px;height:14px}
/* 外挂分隔：舆情 ‖ 三维 */
.seg-div{width:1px;height:18px;margin:0 5px;background:var(--border)}
.bar-right{display:flex;align-items:center;gap:10px}
.chip{
  display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 10px;
  border:1px solid var(--border);border-radius:var(--radius-pill);background:var(--surface);
  font-size:11.5px;color:var(--ink-2);
}
.chip-warn{color:var(--warn);border-color:#e8d9ac;background:#fdf8ea}
.chip-xt{color:var(--xt);border-color:#e3d4fb;background:#f7f2ff}
.bar-meta{font-size:11.5px;color:var(--ink-3);font-variant-numeric:tabular-nums}
.bar-meta b{font-weight:500;color:var(--ink)}
#actionRefresh.is-busy .ico{animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}

/* ④ 内容区 */
.board-scroll{overflow-y:auto;min-height:0;padding:24px 24px 30px}
.board{display:none;max-width:1240px;margin:0 auto}
.board.is-active{display:block}

/* ---------------- 视图容器：看板（BI） ↔ 对话（Agent） ---------------- */
.view{display:none;min-height:0}
#viewBoard.is-active{display:grid;grid-template-rows:auto minmax(0,1fr)}
/* 对话视图：滚动区撑满 + 底部 composer（composer 仅存在于本视图） */
#viewChat.is-active{display:grid;grid-template-rows:minmax(0,1fr) auto}

/* 对话视图 · 滚动容器（撑满可用高度，内部不外溢） */
.chat-scroll{display:flex;flex-direction:column;overflow-y:auto;min-height:0;padding:24px 24px 30px}
.chat-scroll::-webkit-scrollbar{width:9px}
.chat-scroll::-webkit-scrollbar-thumb{background:#d8d4cc;border:3px solid transparent;background-clip:padding-box;border-radius:99px}
.chat-inner{flex:1 0 auto;width:100%;max-width:1240px;margin:0 auto;display:flex;flex-direction:column;gap:24px}

/* 空态 hero：巨型衬线字标 + 对象 + 建议问题（默认展示，垂直居中） */
.chat-hero{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;gap:14px;padding:24px 0 40px}
.hero-wordmark{
  margin:0;font-family:var(--font-display);font-weight:400;
  font-size:clamp(46px,8.5vw,104px);line-height:.98;letter-spacing:.16em;
  color:var(--ink);text-transform:uppercase;
}
.hero-sub{font-size:14px;color:var(--ink-2);letter-spacing:.04em}
.hero-obj{display:flex;flex-direction:column;align-items:center;gap:7px;margin-top:6px}
.hero-meta{font-size:11.5px;color:var(--ink-3);font-variant-numeric:tabular-nums}
.suggest{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;max-width:760px;margin-top:10px}
.suggest-pill{
  display:inline-flex;align-items:center;gap:8px;max-width:340px;text-align:left;
  padding:10px 15px;border-radius:var(--radius-pill);border:1px solid var(--border);
  background:var(--panel);color:var(--ink);font-size:12.5px;line-height:1.4;
  transition:background .16s ease,border-color .16s ease,transform .16s ease,box-shadow .16s ease;
}
.suggest-pill .ico{width:14px;height:14px;color:var(--accent);flex:none}
.suggest-pill:hover{background:var(--accent-bg);border-color:var(--accent);transform:translateY(-1px);box-shadow:var(--shadow-md)}
.hero-toggle{margin-top:8px}

/* 有消息态：hero 收缩到顶部，消息流展开（二者同屏可见） */
.chat-scroll.has-thread .chat-hero{flex:0 0 auto;justify-content:flex-start;padding:4px 0 20px}
.chat-scroll.has-thread .hero-wordmark{font-size:clamp(26px,3.6vw,40px);letter-spacing:.14em}
.chat-scroll.has-thread .suggest{display:none}

/* 消息：用户右对齐浅底气泡 / Agent 左对齐编辑式排版（无气泡） */
.chat-thread{display:none;flex-direction:column;gap:22px}
.chat-scroll.has-thread .chat-thread{display:flex}
.msg-user{
  align-self:flex-end;max-width:68ch;background:var(--accent-bg);border:1px solid #f0d8cd;
  border-radius:16px 16px 4px 16px;padding:12px 16px;font-size:13.5px;line-height:1.6;
}
.msg-agent{max-width:74ch;display:flex;flex-direction:column;gap:14px}
.agent-body{font-size:13.5px;line-height:1.75;color:var(--ink);margin:0}
.agent-embed{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px 16px;box-shadow:var(--shadow-hair)}
.agent-embed .card-head{margin-bottom:11px}
.evi-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}

/* 工具活动时间线（可折叠） */
.tools{margin-top:2px}
.tools summary{cursor:pointer;font-size:12px;color:var(--ink-2);list-style:none;display:inline-flex;align-items:center;gap:7px}
.tools summary::-webkit-details-marker{display:none}
.tools summary .ico{width:14px;height:14px;color:var(--ink-3);transition:transform .16s ease}
.tools[open] summary .ico{transform:rotate(90deg)}
.tools-list{margin-top:9px;border-left:2px solid var(--border);padding-left:14px;display:flex;flex-direction:column;gap:8px}
.tool-row{display:flex;align-items:center;gap:10px;font-size:12px;color:var(--ink-2)}
.tool-row .tk-ok{color:var(--pos);font-weight:600}
.tool-row .tk-name{font-variant-numeric:tabular-nums}
.tool-row .tk-time{margin-left:auto;color:var(--ink-3);font-variant-numeric:tabular-nums}

/* scope 锁定 pill（对话态） */
.scope-pill{background:var(--accent-bg);border:1px solid #f0d8cd;color:var(--accent);gap:7px;padding:0 8px 0 11px}
.scope-pill:hover{background:#fbe9e1;color:var(--accent-d)}
.scope-x{display:inline-flex;align-items:center;justify-content:center;width:15px;height:15px;border-radius:99px;background:rgba(184,86,56,.14);font-size:10px;line-height:1}

/* 状态栏两态 */
.st-chat{display:none}
.statusbar.is-chat .st-board{display:none}
.statusbar.is-chat .st-chat{display:inline-flex}
.board-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:18px;flex-wrap:wrap}
.eyebrow{
  font-family:var(--font-display);font-size:11px;letter-spacing:.22em;text-transform:uppercase;
  color:var(--accent);margin-bottom:6px;
}
.board-title{font-size:23px;line-height:1.35;letter-spacing:-.01em}
.board-desc{margin:6px 0 0;max-width:64ch;font-size:13px;color:var(--ink-2)}
.head-ctrl{display:flex;flex-direction:column;gap:5px;align-items:flex-start}
.field-label{font-size:11.5px;color:var(--ink-3)}
.select-wrap{position:relative;display:inline-flex;align-items:center}
.select-wrap select{
  appearance:none;-webkit-appearance:none;height:32px;padding:0 32px 0 12px;
  border:1px solid var(--border);border-radius:9px;background:var(--surface);color:var(--ink);
  font:inherit;font-size:12.5px;cursor:pointer;
}
.select-wrap select:hover{border-color:var(--ink-3)}
.chev{position:absolute;right:9px;width:14px;height:14px;color:var(--ink-3);pointer-events:none}

/* Grid + 卡片 */
.grid{display:grid;gap:14px;margin-bottom:14px}
.kpi-grid{grid-template-columns:repeat(3,minmax(0,1fr))}
.main-grid{grid-template-columns:minmax(0,1.55fr) minmax(0,1fr)}
.two-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
.three-grid{grid-template-columns:repeat(3,minmax(0,1fr))}
.card{
  background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  padding:17px 18px;box-shadow:var(--shadow-hair);transition:box-shadow .18s ease,transform .18s ease;
}
.card.is-hoverable:hover{box-shadow:var(--shadow-md);transform:translateY(-1px)}
.card-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:13px}
.card-title{font-size:13.5px;letter-spacing:.01em}
.card-meta{font-size:11px;color:var(--ink-3);font-variant-numeric:tabular-nums;text-align:right;line-height:1.5}
.card-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:13px;padding-top:11px;border-top:1px solid var(--border)}
.section-title{
  display:flex;align-items:center;gap:9px;margin:26px 0 12px;
  font-size:14px;letter-spacing:.01em;
}
.section-title .eyebrow{margin:0}
.section-title .rule{flex:1;height:1px;background:var(--border)}

/* KPI */
.kpi-label{font-size:11.5px;color:var(--ink-3);letter-spacing:.02em}
.kpi-value{margin-top:6px;font-size:28px;line-height:1.12;font-weight:600;font-variant-numeric:tabular-nums}
.kpi-unit{margin-left:5px;font-size:12.5px;font-weight:400;color:var(--ink-3)}
.kpi-foot{display:flex;align-items:center;gap:8px;margin-top:8px;font-size:11.5px;color:var(--ink-3);flex-wrap:wrap}
.delta{font-variant-numeric:tabular-nums;font-weight:500}
.delta.up{color:var(--pos)}
.delta.down{color:var(--neg)}
.delta.flat{color:var(--ink-3)}
/* 可下钻 KPI */
.kpi[data-ev]{cursor:pointer}
.kpi[data-ev] .kpi-value{border-bottom:1px dashed transparent;transition:border-color .16s ease,color .16s ease;display:inline-block}
.kpi[data-ev]:hover .kpi-value{border-bottom-color:var(--accent);color:var(--accent-d)}
.kpi .drill-hint{font-size:10.5px;color:var(--accent);opacity:0;transition:opacity .16s ease}
.kpi[data-ev]:hover .drill-hint{opacity:1}

/* 图表 */
.chart{display:block;width:100%;height:auto}
.chart-grid{stroke:var(--grid);stroke-width:1;stroke-dasharray:2 5}
.chart-axis{fill:var(--ink-3);font-size:10.5px;font-family:var(--font-ui)}
.chart-area{fill:var(--accent-bg)}
.chart-line{fill:none;stroke:var(--accent);stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.chart-dot{fill:var(--surface);stroke:var(--accent);stroke-width:2.2}
.chart-bar{fill:var(--pos);opacity:.30}
.chart-bar.is-peak{opacity:1}
.chart-bar-xt{fill:var(--xt);opacity:.22}
.chart-line-xt{fill:none;stroke:var(--xt);stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.chart-dot-xt{fill:var(--surface);stroke:var(--xt);stroke-width:2.2}
.chart-line-neg{fill:none;stroke:var(--neg);stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.chart-dot-neg{fill:var(--surface);stroke:var(--neg);stroke-width:2.2}
.legend{display:flex;align-items:center;gap:16px;margin-top:10px;font-size:11.5px;color:var(--ink-3)}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px;vertical-align:-1px}

/* 水平条 */
.hbars{display:flex;flex-direction:column;gap:12px}
.hbar{display:grid;grid-template-columns:80px minmax(0,1fr) 62px;align-items:center;gap:10px}
.hbar-key{font-size:12.5px;color:var(--ink)}
.hbar-track{height:9px;border-radius:99px;background:var(--grid);overflow:hidden}
.hbar-track i{display:block;height:100%;border-radius:99px;background:var(--pos)}
.hbar-track i.is-pos{background:var(--pos)}
.hbar-track i.is-neg{background:var(--neg)}
.hbar-track i.is-neutral{background:var(--ink-3)}
.hbar-track i.is-accent{background:var(--accent)}
.hbar-track i.is-warn{background:var(--warn)}
.hbar-val{font-size:12px;color:var(--ink-2);text-align:right;font-variant-numeric:tabular-nums}

/* 列表 */
.list{display:flex;flex-direction:column}
.list-row{display:flex;align-items:center;gap:14px;padding:11px 0;border-top:1px solid var(--border)}
.list-row:first-child{border-top:0;padding-top:2px}
.list-main{flex:1;min-width:0}
.list-title{font-size:13px;line-height:1.5}
.list-sub{margin-top:2px;font-size:11.5px;color:var(--ink-3)}
.list-right{display:flex;align-items:center;gap:12px;flex:none}
.tag{
  display:inline-flex;align-items:center;height:22px;padding:0 9px;border-radius:6px;font-size:11px;
  border:1px solid var(--border);color:var(--ink-2);background:var(--surface);white-space:nowrap;
}
.tag-pos{color:var(--pos);border-color:#ccd7f2;background:#eef2fc}
.tag-neg{color:var(--neg);border-color:#eccdca;background:#fdf2f2}
.tag-warn{color:var(--warn);border-color:#ecdcb0;background:#fdf8ea}
.tag-xt{color:var(--xt);border-color:#e0d2fb;background:#f7f2ff}
.tag-accent{color:var(--accent);border-color:#f0d8cd;background:var(--accent-bg)}
.heat{display:inline-flex;align-items:center;gap:7px}
.heat-track{display:block;width:58px;height:6px;border-radius:99px;background:var(--grid);overflow:hidden}
.heat-track i{display:block;height:100%;background:var(--accent);border-radius:99px}
.heat b{font-size:11.5px;font-weight:500;color:var(--ink-2);font-variant-numeric:tabular-nums}

/* 表格 */
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--border);white-space:normal}
th{font-size:11.5px;font-weight:500;letter-spacing:.02em;color:var(--ink-3);background:var(--panel)}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover{background:var(--panel)}
.table-scroll{overflow-x:auto}
.matrix-wrap{
  overflow-x:auto;border:1px solid var(--border);border-radius:var(--radius-sm);max-height:520px;
}
.matrix-wrap table{min-width:1080px}
.matrix-wrap th,.matrix-wrap td{white-space:nowrap}
.matrix-wrap .sticky-col{
  position:sticky;left:0;z-index:2;background:var(--surface);
  box-shadow:1px 0 0 var(--border);font-weight:500;
}
.matrix-wrap thead .sticky-col{z-index:3;background:var(--panel)}
.matrix-wrap tbody tr:hover .sticky-col{background:var(--panel)}

/* 棱镜链路（配置→口碑→销量） */
.chain{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;align-items:stretch;gap:10px;margin-bottom:14px}
.chain-card{
  background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);
  padding:16px 17px;box-shadow:var(--shadow-hair);display:flex;flex-direction:column;gap:8px;
}
.chain-card .cc-top{display:flex;align-items:center;justify-content:space-between;gap:8px}
.chain-card .cc-dim{display:flex;align-items:center;gap:8px;font-size:13px}
.chain-card .cc-dim .ico{width:16px;height:16px;color:var(--accent)}
.chain-card .cc-idx{font-family:var(--font-display);font-size:11px;letter-spacing:.2em;color:var(--ink-3)}
.chain-card .cc-concl{font-size:12.5px;color:var(--ink);line-height:1.55;min-height:38px}
.chain-card .cc-foot{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.chain-arrow{display:flex;align-items:center;justify-content:center;color:var(--ink-3);font-size:18px;padding:0 2px}
.evi-badge{
  display:inline-flex;align-items:center;gap:5px;height:20px;padding:0 8px;border-radius:var(--radius-pill);
  font-size:10.5px;border:1px solid var(--border);color:var(--ink-3);background:var(--bg);
}
.evi-badge.strong{color:var(--pos);border-color:#ccd7f2;background:#eef2fc}
.evi-badge.weak{color:var(--warn);border-color:#ecdcb0;background:#fdf8ea}
.evi-badge.none{color:var(--neg);border-color:#eccdca;background:#fdf2f2}

/* CLAIM 结论卡 */
.claim{border-left:3px solid var(--accent)}
.claim-text{font-size:13.5px;line-height:1.65;color:var(--ink)}
.claim-meta{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 18px;margin-top:13px;padding-top:12px;border-top:1px solid var(--border)}
.claim-kv{display:flex;gap:8px;font-size:11.5px;line-height:1.6}
.claim-kv dt{color:var(--ink-3);flex:none;width:78px}
.claim-kv dd{margin:0;color:var(--ink-2);word-break:break-all}

/* 缺口卡 */
.gap{
  border:1px dashed #e3cfa0;background:#fdfaf1;border-radius:var(--radius);
  padding:15px 17px;display:flex;flex-direction:column;gap:8px;
}
.gap-head{display:flex;align-items:center;justify-content:space-between;gap:10px}
.gap-title{display:flex;align-items:center;gap:8px;font-size:13px}
.gap-title .ico{width:16px;height:16px;color:var(--warn)}
.gap-miss{font-size:12.5px;color:var(--ink-2)}
.gap-ask{font-size:12px;color:var(--ink-3);background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:8px 10px}
.gap-ask b{color:var(--ink)}

/* 风险横幅 */
.risk-banner{
  display:flex;align-items:center;gap:14px;padding:13px 16px;margin-bottom:14px;
  background:var(--surface);border:1px solid var(--border);border-left:4px solid var(--neg);
  border-radius:var(--radius-sm);
  background-image:linear-gradient(90deg,#fdf2f2,rgba(255,255,255,0) 60%);
}
.risk-dot{width:12px;height:12px;border-radius:99px;background:var(--neg);flex:none;animation:pulse 1.6s infinite}
.risk-main{flex:1;min-width:0}
.risk-title{font-size:14px;font-weight:600}
.risk-reasons{font-size:12px;color:var(--ink-2);margin-top:2px}
.risk-stats{display:flex;gap:26px;text-align:right;flex:none}
.risk-stats small{display:block;color:var(--ink-3);font-size:10.5px;margin-bottom:2px}
.risk-stats b{display:block;font-size:19px;line-height:1.1;font-variant-numeric:tabular-nums}

/* 渠道 pchip */
.pchips{display:flex;flex-wrap:wrap;gap:8px}
.pchip{
  display:inline-flex;align-items:center;gap:6px;padding:5px 11px;border-radius:var(--radius-pill);
  font-size:12px;background:var(--panel);color:var(--ink-2);border:1px solid var(--border);
}
.pchip .ph-ic{font-size:12px;line-height:1}
.pchip .ph-cnt{background:rgba(0,0,0,.07);padding:0 6px;border-radius:8px;font-size:11px;font-weight:600;font-variant-numeric:tabular-nums}
.pchip.ph-collecting{color:var(--accent);border-color:var(--accent)}
.pchip.ph-collecting .ph-ic{animation:pulse 1.5s infinite}
.pchip.ph-done{color:var(--pos);border-color:var(--pos);background:#eef2fc}
.pchip.ph-done .ph-cnt{background:rgba(35,72,184,.15);color:var(--pos)}
.pchip.ph-error{color:var(--neg);border-color:var(--neg);background:#fdf2f2}
.pchip.ph-error .ph-cnt{background:rgba(156,42,37,.14);color:var(--neg)}

/* 原文样本卡 */
.sample{border-top:1px solid var(--border);padding:12px 0}
.sample:first-child{border-top:0;padding-top:0}
.sample-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.sample-id{font-size:11px;color:var(--ink-3);font-variant-numeric:tabular-nums}
.sample-text{margin-top:6px;font-size:12.5px;line-height:1.6;color:var(--ink)}
.sample-src{margin-top:6px;font-size:11px;color:var(--ink-3)}

/* 骨架 / 错误卡 */
.skel-row{display:flex;flex-direction:column;gap:10px;padding:6px 0}
.skel{height:12px;border-radius:6px;background:linear-gradient(90deg,var(--grid),#f7f4ef,var(--grid));background-size:200% 100%;animation:skel 1.3s linear infinite}
@keyframes skel{to{background-position:-200% 0}}
.errcard{display:flex;align-items:center;gap:12px;padding:14px 16px;border:1px solid #eccdca;background:#fdf2f2;border-radius:var(--radius-sm);margin-bottom:14px}
.errcard .ico{width:18px;height:18px;color:var(--neg);flex:none}
.errcard-main{flex:1;min-width:0}
.errcard-title{font-size:13px;font-weight:600;color:var(--neg)}
.errcard-desc{font-size:11.5px;color:var(--ink-2);margin-top:2px}

/* 按钮 */
.btn{
  display:inline-flex;align-items:center;justify-content:center;gap:8px;height:34px;padding:0 16px;
  border-radius:var(--radius-sm);border:1px solid transparent;font-size:12.5px;
  transition:background .16s ease,color .16s ease,border-color .16s ease,transform .12s ease;
}
.btn-primary{background:var(--accent);color:#fff}
.btn-primary:hover{background:var(--accent-d)}
.btn-primary:active{transform:translateY(1px)}
.btn-ghost{background:transparent;border-color:var(--border);color:var(--ink)}
.btn-ghost:hover{background:var(--panel);border-color:var(--ink-3)}
.btn-sm{height:29px;padding:0 12px;font-size:12px}

/* ⑤ composer（固定，不滚动） */
.composer-row{padding:8px 24px 8px}
.composer{
  display:flex;align-items:center;gap:8px;max-width:980px;margin:0 auto;padding:6px 8px;
  background:var(--surface);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow-lg);
}
.composer:focus-within{border-color:var(--accent)}
.composer input{flex:1;min-width:0;border:0;background:transparent;outline:none;font:inherit;font-size:13.5px;color:var(--ink);height:34px}
.composer input::placeholder{color:var(--ink-3)}
.pill{
  display:inline-flex;align-items:center;gap:6px;height:30px;padding:0 10px;border:0;
  border-radius:var(--radius-pill);background:transparent;color:var(--ink-2);font-size:12px;
  transition:background .16s ease,color .16s ease;
}
.pill:hover{background:var(--panel);color:var(--ink)}
.pill .ico{width:13px;height:13px}
.send{display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;border:0;border-radius:99px;background:var(--ink);color:#fff;transition:background .16s ease}
.send:hover{background:#000}
/* ⑥ 状态栏（发丝，无底色） */
.statusbar{
  display:flex;align-items:center;justify-content:space-between;gap:16px;
  padding:2px 24px 10px;font-size:11.5px;color:var(--ink-3);
}
.status-left,.status-right{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
.status-item{display:inline-flex;align-items:center;gap:6px}
.status-item .ico{width:13px;height:13px}
.dot-ok{width:6px;height:6px;border-radius:99px;background:var(--pos)}
.dot-part{width:6px;height:6px;border-radius:99px;background:var(--warn)}
.dot-none{width:6px;height:6px;border-radius:99px;background:var(--ink-3)}

/* ⑦ 证据抽屉 */
.drawer-scrim{
  position:fixed;inset:0;background:rgba(21,20,15,.18);opacity:0;pointer-events:none;
  transition:opacity .2s ease;z-index:40;
}
.drawer-scrim.is-open{opacity:1;pointer-events:auto}
.drawer{
  position:fixed;top:0;right:0;height:100vh;width:400px;max-width:92vw;z-index:50;
  background:var(--surface);border-left:1px solid var(--border);box-shadow:var(--shadow-lg);
  transform:translateX(102%);transition:transform .24s cubic-bezier(.32,.72,0,1);
  display:flex;flex-direction:column;
}
.drawer.is-open{transform:translateX(0)}
.drawer-head{display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--border)}
.drawer-head .eyebrow{margin:0}
.drawer-title{flex:1;font-size:14px}
.drawer-body{flex:1;overflow-y:auto;padding:16px 18px;display:flex;flex-direction:column;gap:14px}
.drawer-num{font-size:30px;font-weight:600;font-variant-numeric:tabular-nums;line-height:1.1}
.drawer-kv{display:flex;flex-direction:column;gap:10px}
.drawer-kv .row{display:flex;gap:12px;font-size:12px;line-height:1.6}
.drawer-kv dt{color:var(--ink-3);flex:none;width:82px}
.drawer-kv dd{margin:0;color:var(--ink-2);word-break:break-all;font-variant-numeric:tabular-nums}
.drawer-code{background:var(--panel);border:1px solid var(--border);border-radius:var(--radius-sm);padding:10px 12px;font-size:11.5px;line-height:1.7;color:var(--ink-2);overflow-x:auto;white-space:pre-wrap;word-break:break-all}
.drawer-foot{padding:14px 18px;border-top:1px solid var(--border);display:flex;gap:10px}
.drawer-foot .btn{flex:1}

/* 就地问答（看板「选中即问」→ 右抽屉：锁 scope / 单轮 / 不产生会话） */
.ask-block{display:flex;flex-direction:column;gap:10px;border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px;background:var(--panel)}
.ask-head{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}
.ask-lock{display:inline-flex;align-items:center;gap:6px;font-size:11px;color:var(--accent);background:var(--accent-bg);border:1px solid #f0d8cd;border-radius:var(--radius-pill);padding:2px 9px}
.ask-lock .ico{width:12px;height:12px}
.ask-note{font-size:10.5px;color:var(--ink-3)}
.ask-form{display:flex;align-items:center;gap:8px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:0 6px 0 10px}
.ask-form:focus-within{border-color:var(--accent)}
.ask-form input{flex:1;min-width:0;height:32px;border:0;background:transparent;outline:none;font:inherit;font-size:12.5px;color:var(--ink)}
.ask-form .btn{flex:none}
.ask-answer{display:none;font-size:12px;line-height:1.7;color:var(--ink-2);border-left:2px solid var(--accent);padding-left:10px}
.ask-answer.is-on{display:block}

/* toast */
.toast{
  position:fixed;left:50%;bottom:92px;transform:translate(-50%,12px);opacity:0;pointer-events:none;
  padding:10px 18px;border-radius:11px;background:var(--surface);color:var(--ink);border:1px solid var(--border);font-size:13px;
  box-shadow:0 18px 40px -20px rgba(21,20,15,.32);transition:opacity .2s ease,transform .2s ease;z-index:60;
}
.toast.is-on{opacity:1;transform:translate(-50%,0)}

/* ---------------- 响应式（断点真实生效） ---------------- */
@media (max-width:1180px){
  .main-grid,.two-grid{grid-template-columns:minmax(0,1fr)}
  .kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .chain{grid-template-columns:1fr;gap:8px}
  .chain-arrow{transform:rotate(90deg);padding:2px 0}
  .chat-inner{gap:20px}
  .hero-wordmark{letter-spacing:.13em}
}
@media (max-width:900px){
  .app{grid-template-columns:56px minmax(0,1fr)}
  .sidebar{width:56px;overflow:hidden}
  .sb-nav .sb-item span,.sb-item kbd,.sb-tabs,.sb-search,.sb-scroll,.sb-label,.sb-month{display:none}
  .sb-nav{padding:4px 6px}
  .sb-item{justify-content:center;padding:0}
  .sb-foot{flex-direction:column;border-top:0;gap:4px}
  .sb-top{justify-content:center;padding:8px 4px}
  .kpi-grid,.three-grid{grid-template-columns:minmax(0,1fr)}
  .board-bar{padding-left:16px;padding-right:16px}
  .board-scroll,.chat-scroll,.composer-row,.statusbar{padding-left:16px;padding-right:16px}
  .bar-right{width:100%}
  .cmdk{min-width:0;flex:1}
  .claim-meta{grid-template-columns:minmax(0,1fr)}
  /* 对话视图：建议胶囊单列、气泡收窄 */
  .suggest{flex-direction:column;align-items:stretch}
  .suggest-pill{max-width:none}
  .msg-user{max-width:100%}
  .msg-agent{max-width:100%}
  .hero-wordmark{letter-spacing:.11em}
}
@media (max-width:600px){
  .appbar{gap:8px;padding:0 10px}
  .cmdk .cmdk-label{display:none}
  .cmdk{min-width:auto}
  .seg-btn{padding:0 11px;font-size:12.5px}
  .bar-meta{display:none}
  .table-scroll,.matrix-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
  .table-scroll table{min-width:560px}
  .kpi-value{font-size:25px}
  .composer .pill .pill-label{display:none}
  .status-right .hide-sm{display:none}
  /* 对话视图：字标缩一号、内边距收紧 */
  .hero-wordmark{font-size:clamp(28px,11vw,44px);letter-spacing:.1em}
  .chat-scroll{padding:16px}
  .chat-inner{gap:16px}
  .agent-embed{padding:12px 13px}
}
</style>
</head>
<body>

<!-- ============ SVG 图标 sprite（内联，无外部请求） ============ -->
<svg class="sprite" aria-hidden="true">
  <symbol id="ico-plus" viewBox="0 0 24 24"><path d="M12 5.5v13M5.5 12h13"/></symbol>
  <symbol id="ico-sliders" viewBox="0 0 24 24"><path d="M4 7.5h8M16.5 7.5h3.5M4 16.5h3.5M12 16.5h8"/><circle cx="14.2" cy="7.5" r="2.1"/><circle cx="9.7" cy="16.5" r="2.1"/></symbol>
  <symbol id="ico-chat" viewBox="0 0 24 24"><path d="M4.5 5.5h15v10h-8.5l-4 3.5v-3.5H4.5z"/></symbol>
  <symbol id="ico-box" viewBox="0 0 24 24"><path d="M12 3.6 20 7.6v8.8L12 20.4 4 16.4V7.6z"/><path d="M4 7.6l8 4 8-4M12 11.6v8.8"/></symbol>
  <symbol id="ico-clock" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 7.6V12.4l3.2 2"/></symbol>
  <symbol id="ico-kanban" viewBox="0 0 24 24"><rect x="3.8" y="4.6" width="4.6" height="14.8" rx="1.4"/><rect x="9.7" y="4.6" width="4.6" height="9.4" rx="1.4"/><rect x="15.6" y="4.6" width="4.6" height="12.2" rx="1.4"/></symbol>
  <symbol id="ico-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.2"/><path d="M15.6 15.6 20 20"/></symbol>
  <symbol id="ico-home" viewBox="0 0 24 24"><path d="M4.5 11 12 4.6l7.5 6.4v7.4a1.6 1.6 0 0 1-1.6 1.6H6.1a1.6 1.6 0 0 1-1.6-1.6z"/><path d="M9.8 20v-5.6h4.4V20"/></symbol>
  <symbol id="ico-help" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M9.8 9.7a2.3 2.3 0 1 1 3 2.2c-.6.2-.9.7-.9 1.3v.4"/><path d="M12 16.4v.2"/></symbol>
  <symbol id="ico-dots" viewBox="0 0 24 24"><circle cx="6" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="18" cy="12" r="1.4"/></symbol>
  <symbol id="ico-panel" viewBox="0 0 24 24"><rect x="3.8" y="4.6" width="16.4" height="14.8" rx="2.2"/><path d="M9.6 4.6v14.8"/></symbol>
  <symbol id="ico-pin" viewBox="0 0 24 24"><path d="M7.4 4.6h9.2v14.8l-4.6-3.3-4.6 3.3z"/></symbol>
  <symbol id="ico-refresh" viewBox="0 0 24 24"><path d="M19.4 12a7.4 7.4 0 1 1-2.2-5.3"/><path d="M19.6 4.7v4.6h-4.6"/></symbol>
  <symbol id="ico-chev" viewBox="0 0 24 24"><path d="M7.5 10 12 14.5 16.5 10"/></symbol>
  <symbol id="ico-x" viewBox="0 0 24 24"><path d="M7 7l10 10M17 7 7 17"/></symbol>
  <symbol id="ico-unplug" viewBox="0 0 24 24"><path d="M9 3.4v4.2M15 3.4v4.2"/><path d="M6.4 7.6h11.2v3.2a5.6 5.6 0 0 1-5.6 5.6 5.6 5.6 0 0 1-5.6-5.6z"/><path d="M12 16.4v4.2"/></symbol>
  <symbol id="ico-mic" viewBox="0 0 24 24"><rect x="9.4" y="3.6" width="5.2" height="9.6" rx="2.6"/><path d="M6.4 11.4a5.6 5.6 0 0 0 11.2 0M12 17v3.4"/></symbol>
  <symbol id="ico-arrow-up" viewBox="0 0 24 24"><path d="M12 19V5.6M6 11.6 12 5.6l6 6"/></symbol>
  <symbol id="ico-arrow-right" viewBox="0 0 24 24"><path d="M5.5 12h13M13 6.5 18.5 12 13 17.5"/></symbol>
  <symbol id="ico-atom" viewBox="0 0 24 24"><circle cx="12" cy="12" r="2.2"/><ellipse cx="12" cy="12" rx="9" ry="4"/><ellipse cx="12" cy="12" rx="9" ry="4" transform="rotate(60 12 12)"/><ellipse cx="12" cy="12" rx="9" ry="4" transform="rotate(120 12 12)"/></symbol>
  <symbol id="ico-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 3v2.2M12 18.8V21M3 12h2.2M18.8 12H21M5.6 5.6l1.6 1.6M16.8 16.8l1.6 1.6M18.4 5.6l-1.6 1.6M7.2 16.8l-1.6 1.6"/></symbol>
  <symbol id="ico-layers" viewBox="0 0 24 24"><path d="M12 3.8 20.5 8 12 12.2 3.5 8z"/><path d="M3.5 12 12 16.2 20.5 12M3.5 16 12 20.2 20.5 16"/></symbol>
  <symbol id="ico-flask" viewBox="0 0 24 24"><path d="M9.5 3.6h5v4.2l4.2 9.2a2 2 0 0 1-1.8 2.9H7.1a2 2 0 0 1-1.8-2.9l4.2-9.2z"/><path d="M7.6 14.4h8.8"/></symbol>
</svg>

<div class="app">

  <!-- ① 应用栏 -->
  <header class="appbar">
    <span class="brand"><span class="prism-dot"></span>Prism <small>Agent</small></span>
    <button class="obj-chip" id="objChip" title="切换当前分析对象（resolve_series 已核验）">
      <span class="dot-ok"></span><b>银河E5</b><span style="color:var(--ink-3)">· 2026 款</span>
      <svg class="ico"><use href="#ico-chev"/></svg>
    </button>
    <span class="appbar-spacer"></span>
    <button class="cmdk" id="cmdk" title="打开命令面板（Ctrl K）">
      <svg class="ico"><use href="#ico-search"/></svg>
      <span class="cmdk-label">搜索车系 / 跳转看板 / 执行命令</span>
      <kbd>Ctrl K</kbd>
    </button>
    <div class="appbar-tools">
      <button class="icon-btn" id="themeBtn" aria-label="切换主题" title="主题"><svg class="ico"><use href="#ico-sun"/></svg></button>
      <button class="icon-btn" aria-label="窗口" title="窗口"><svg class="ico"><use href="#ico-panel"/></svg></button>
    </div>
  </header>

  <!-- ② 侧栏 -->
  <aside class="sidebar">
    <div class="sb-top">
      <button class="icon-btn" aria-label="收起侧栏"><svg class="ico"><use href="#ico-panel"/></svg></button>
      <div class="sb-tabs" role="tablist" aria-label="侧栏视图">
        <button class="sb-tab is-on" role="tab" aria-selected="true" data-sbtab>会话</button>
        <button class="sb-tab" role="tab" aria-selected="false" data-sbtab>车系</button>
      </div>
      <button class="icon-btn" aria-label="更多"><svg class="ico"><use href="#ico-dots"/></svg></button>
    </div>
    <nav class="sb-nav" aria-label="主导航">
      <button class="sb-item" data-nav="new"><svg class="ico"><use href="#ico-plus"/></svg><span>新建会话</span><kbd>Ctrl N</kbd></button>
      <button class="sb-item is-active" data-nav="workbench"><svg class="ico"><use href="#ico-kanban"/></svg><span>棱镜工作台</span></button>
      <button class="sb-item" data-nav="artifacts"><svg class="ico"><use href="#ico-box"/></svg><span>产物</span></button>
      <button class="sb-item" data-nav="settings"><svg class="ico"><use href="#ico-sliders"/></svg><span>设置</span></button>
    </nav>
    <div class="sb-search"><svg class="ico"><use href="#ico-search"/></svg><input type="search" placeholder="搜索会话 / 车系…" aria-label="搜索"></div>
    <div class="sb-scroll">
      <div class="sb-group">
        <div class="sb-label"><svg class="ico"><use href="#ico-pin"/></svg>已置顶</div>
        <ul class="sb-list">
          <li class="sb-row"><span class="dot"></span><span class="sb-row-title">银河E5 · 三维度齐了吗</span></li>
        </ul>
      </div>
      <div class="sb-group">
        <div class="sb-label"><svg class="ico"><use href="#ico-chat"/></svg>会话</div>
        <div class="sb-month">十月</div>
        <ul class="sb-list">
          <li class="sb-row" data-nav="chat"><span class="sb-row-title">棱镜链路：配置拖后腿了吗</span><span class="sb-row-time">2 小时</span></li>
          <li class="sb-row" data-nav="chat"><span class="sb-row-title">口碑「其他」桶拆解</span><span class="sb-row-time">昨天</span></li>
          <li class="sb-row" data-nav="chat"><span class="sb-row-title">销量环比 -42.9% 复核</span><span class="sb-row-time">2 天</span></li>
        </ul>
        <div class="sb-month">九月</div>
        <ul class="sb-list">
          <li class="sb-row" data-nav="chat"><span class="sb-row-title">舆情外挂与销量交叉验证</span><span class="sb-row-time">6 天</span></li>
          <li class="sb-row" data-nav="chat"><span class="sb-row-title">12 个 spec_id 配置对齐</span><span class="sb-row-time">11 天</span></li>
        </ul>
      </div>
      <div class="sb-group">
        <div class="sb-label"><svg class="ico"><use href="#ico-clock"/></svg>定时任务</div>
        <ul class="sb-list">
          <li class="sb-row"><span class="dot"></span><span class="sb-row-title">舆情日采集 · 08:00</span></li>
        </ul>
      </div>
    </div>
    <div class="sb-foot">
      <button class="icon-btn" aria-label="主页"><svg class="ico"><use href="#ico-home"/></svg></button>
      <button class="icon-btn" aria-label="新建"><svg class="ico"><use href="#ico-plus"/></svg></button>
      <button class="icon-btn" aria-label="帮助"><svg class="ico"><use href="#ico-help"/></svg></button>
      <button class="icon-btn" aria-label="更多"><svg class="ico"><use href="#ico-dots"/></svg></button>
    </div>
  </aside>

  <!-- 主区：两个可切换视图（看板 / 对话），共享同一「当前对象」上下文 -->
  <div class="main">

   <!-- 视图一：看板（BI） -->
   <div class="view is-active" id="viewBoard">

    <!-- ③ 看板栏 -->
    <header class="board-bar" id="boardBar">
      <div class="bar-left">
        <span class="bar-brand"><svg class="ico"><use href="#ico-atom"/></svg>棱镜看板</span>
        <div class="seg" role="tablist" aria-label="棱镜看板切换">
          <button class="seg-btn" id="tab-overview" role="tab" aria-selected="true" aria-controls="board-overview" data-board="overview">棱镜结论</button>
          <button class="seg-btn" id="tab-sentiment" role="tab" aria-selected="false" aria-controls="board-sentiment" data-board="sentiment" tabindex="-1">舆情</button>
          <span class="seg-div" aria-hidden="true"></span>
          <button class="seg-btn" id="tab-config" role="tab" aria-selected="false" aria-controls="board-config" data-board="config" tabindex="-1">车型配置</button>
          <button class="seg-btn" id="tab-reviews" role="tab" aria-selected="false" aria-controls="board-reviews" data-board="reviews" tabindex="-1">口碑</button>
          <button class="seg-btn" id="tab-sales" role="tab" aria-selected="false" aria-controls="board-sales" data-board="sales" tabindex="-1">销量</button>
        </div>
      </div>
      <div class="bar-right">
        <div class="select-wrap">
          <select id="rangeSelect" aria-label="时间范围">
            <option>近 30 天</option><option>近 7 天</option><option>近 24 小时</option><option>近 12 个月</option>
          </select>
          <svg class="ico chev"><use href="#ico-chev"/></svg>
        </div>
        <span class="chip chip-warn" title="本原型全部数值为演示用示例数据">示例数据</span>
        <span class="bar-meta">as_of <b id="barTime">2026-09-30</b></span>
        <button class="icon-btn" id="actionRefresh" aria-label="刷新"><svg class="ico"><use href="#ico-refresh"/></svg></button>
      </div>
    </header>

    <!-- ④ 内容区 -->
    <div class="board-scroll" id="boardScroll">

      <!-- ============ 看板 1 · 棱镜结论（判断层：链路 + 交叉 + CLAIM + 缺口） ============ -->
      <section class="board is-active" id="board-overview" role="tabpanel" aria-labelledby="tab-overview">
        <div class="board-head">
          <div>
            <div class="eyebrow">Prism Overview</div>
            <h2 class="board-title">银河E5 · 棱镜结论</h2>
            <p class="board-desc">配置→口碑→销量 的因果链路与舆情外挂并置，一眼看清本期谁在拖后腿。所有数值均可点击下钻至 supported_by。</p>
          </div>
          <div class="head-ctrl">
            <span class="field-label">当前对象 · resolve_series 已核验</span>
            <div class="select-wrap">
              <select aria-label="车系对象"><option>银河E5（7650）</option><option>银河星愿</option><option>银河L7</option></select>
              <svg class="ico chev"><use href="#ico-chev"/></svg>
            </div>
          </div>
        </div>

        <div class="section-title"><span class="eyebrow">棱镜链路</span><span class="rule"></span><span class="chip">配置 → 口碑 → 销量</span></div>
        <div class="chain">
          <div class="chain-card">
            <div class="cc-top"><span class="cc-dim"><svg class="ico"><use href="#ico-layers"/></svg>配置 · 产品力</span><span class="cc-idx">01</span></div>
            <p class="cc-concl">12 个在售版型中，入门版缺少前排通风与隔音玻璃，是产品力短板。</p>
            <div class="cc-foot"><span class="evi-badge strong">证据 强</span><span class="evi-badge">spec 12 行</span><span class="evi-badge">as_of 09-02</span></div>
          </div>
          <div class="chain-arrow"><svg class="ico" style="width:20px;height:20px"><use href="#ico-arrow-right"/></svg></div>
          <div class="chain-card">
            <div class="cc-top"><span class="cc-dim"><svg class="ico"><use href="#ico-chat"/></svg>口碑 · 需求验证</span><span class="cc-idx">02</span></div>
            <p class="cc-concl">舒适维度净态度 +316，与配置短板形成对照；续航维度负面占比升至 21%。</p>
            <div class="cc-foot"><span class="evi-badge strong">证据 强</span><span class="evi-badge">tags 3,235</span><span class="evi-badge">as_of 09-30</span></div>
          </div>
          <div class="chain-arrow"><svg class="ico" style="width:20px;height:20px"><use href="#ico-arrow-right"/></svg></div>
          <div class="chain-card">
            <div class="cc-top"><span class="cc-dim"><svg class="ico"><use href="#ico-kanban"/></svg>销量 · 市场结果</span><span class="cc-idx">03</span></div>
            <p class="cc-concl">九月零售环比 -12.0%，终端价同版型下探 2.1 万，降幅集中在主销版型。</p>
            <div class="cc-foot"><span class="evi-badge strong">证据 强</span><span class="evi-badge">sales_trim 72 行</span><span class="evi-badge">as_of 09-30</span></div>
          </div>
        </div>

        <div class="grid main-grid">
          <div class="card is-hoverable">
            <div class="card-head">
              <h3 class="card-title">舆情外挂 × 销量交叉</h3>
              <span class="card-meta">声量（紫线）· 零售（蓝柱）<br>近 6 个月 · 单位：条 / 台</span>
            </div>
            <svg class="chart" viewBox="0 0 720 220" role="img" aria-label="舆情声量与月度零售交叉图">
              <line class="chart-grid" x1="40" y1="16" x2="704" y2="16"/>
              <line class="chart-grid" x1="40" y1="103" x2="704" y2="103"/>
              <line class="chart-grid" x1="40" y1="190" x2="704" y2="190"/>
              <rect class="chart-bar" x="69.3" y="87.6" width="52" height="102.4" rx="3"/>
              <rect class="chart-bar" x="180" y="81.3" width="52" height="108.7" rx="3"/>
              <rect class="chart-bar" x="290.7" y="66.7" width="52" height="123.3" rx="3"/>
              <rect class="chart-bar" x="401.3" y="71.7" width="52" height="118.3" rx="3"/>
              <rect class="chart-bar" x="512" y="52.7" width="52" height="137.3" rx="3"/>
              <rect class="chart-bar is-peak" x="622.7" y="38.2" width="52" height="151.8" rx="3"/>
              <path class="chart-line-xt" d="M95.3 76.4 L206 69.2 L316.7 59.5 L427.3 78.8 L538 48.2 L648.7 38.6"/>
              <circle class="chart-dot-xt" cx="95.3" cy="76.4" r="3.2"/>
              <circle class="chart-dot-xt" cx="206" cy="69.2" r="3.2"/>
              <circle class="chart-dot-xt" cx="316.7" cy="59.5" r="3.2"/>
              <circle class="chart-dot-xt" cx="427.3" cy="78.8" r="3.2"/>
              <circle class="chart-dot-xt" cx="538" cy="48.2" r="3.2"/>
              <circle class="chart-dot-xt" cx="648.7" cy="38.6" r="3.2"/>
              <text class="chart-axis" x="95.3" y="208" text-anchor="middle">4 月</text>
              <text class="chart-axis" x="206" y="208" text-anchor="middle">5 月</text>
              <text class="chart-axis" x="316.7" y="208" text-anchor="middle">6 月</text>
              <text class="chart-axis" x="427.3" y="208" text-anchor="middle">7 月</text>
              <text class="chart-axis" x="538" y="208" text-anchor="middle">8 月</text>
              <text class="chart-axis" x="648.7" y="208" text-anchor="middle">9 月</text>
            </svg>
            <div class="legend">
              <span><i style="background:var(--pos);opacity:.45"></i>月度零售（台）</span>
              <span><i style="background:var(--xt)"></i>舆情声量（条）</span>
            </div>
            <div class="card-foot">
              <span class="card-meta" style="text-align:left">9 月声量 188 条 ↔ 零售 11,340 台，同向走高；仅作交叉观察，不构成因果归因</span>
              <button class="btn btn-ghost btn-sm" data-board-goto="sentiment">看舆情明细</button>
            </div>
          </div>

          <div class="card claim is-hoverable">
            <div class="card-head">
              <h3 class="card-title">本期结论 · CLAIM</h3>
              <span class="card-meta">as_of 2026-09-30<br>scope 银河E5 / 近30天</span>
            </div>
            <p class="claim-text">本期短板集中在 <b>入门版型配置</b> 与 <b>续航口碑</b> 两处；销量环比下滑与终端价下探同步出现，但按纪律，市场侧结果不归因到产品力。</p>
            <dl class="claim-meta">
              <div class="claim-kv"><dt>supported_by</dt><dd>spec#79310 ; review_tags#20481 ; sales_trim#11204</dd></div>
              <div class="claim-kv"><dt>as_of</dt><dd>2026-09-30T23:59+08:00</dd></div>
              <div class="claim-kv"><dt>scope</dt><dd>series=7650 · range=近30天</dd></div>
              <div class="claim-kv"><dt>覆盖率</dt><dd>配置 12/12 · 口碑 92.5% · 销量 月末行 100%</dd></div>
            </dl>
            <div class="card-foot">
              <span class="card-meta" style="text-align:left">结论未越界：口碑只下口碑内结论</span>
              <button class="btn btn-ghost btn-sm" id="claimToChat">扩展为会话 ↗</button>
            </div>
          </div>
        </div>

        <div class="section-title"><span class="eyebrow">缺口清单</span><span class="rule"></span><span class="chip chip-warn">2 项待补</span></div>
        <div class="grid two-grid">
          <div class="gap">
            <div class="gap-head">
              <span class="gap-title"><svg class="ico"><use href="#ico-unplug"/></svg>配置 · 非车系级缺失</span>
              <span class="evi-badge weak">证据 弱</span>
            </div>
            <p class="gap-miss">「非车系级缺失」：79312 / 79313 两个 spec_id 缺少部分配置项，无法与车系级口径合并。</p>
            <p class="gap-ask"><b>缺什么能坐实：</b>需 config 源补齐这两个 spec_id 的「车机芯片 / 智驾方案」两列，方可并入矩阵赋分。</p>
          </div>
          <div class="gap">
            <div class="gap-head">
              <span class="gap-title"><svg class="ico"><use href="#ico-unplug"/></svg>口碑 ·「其他」桶待拆解</span>
              <span class="evi-badge weak">证据 弱</span>
            </div>
            <p class="gap-miss">打标覆盖率 92.5%，剩余 7.5% 落入「其他」桶，尚未拆解为具体维度。</p>
            <p class="gap-ask"><b>缺什么能坐实：</b>需对「其他」桶 96 条原文做二次打标，才能纳入维度聚合与净态度计算。</p>
          </div>
        </div>
      </section>

      <!-- ============ 看板 2 · 舆情（外挂） ============ -->
      <section class="board" id="board-sentiment" role="tabpanel" aria-labelledby="tab-sentiment">
        <div class="board-head">
          <div>
            <div class="eyebrow" style="color:var(--xt)">Sentiment · 外挂</div>
            <h2 class="board-title">舆情监测 <span class="tag tag-xt">外挂 · 仅与销量交叉</span></h2>
            <p class="board-desc">汇总公开渠道的声量与情绪。舆情与棱镜三维度外挂，仅与销量做双向交叉，不参与配置→口碑→销量链路。</p>
          </div>
          <div class="head-ctrl">
            <span class="field-label">时间范围</span>
            <div class="select-wrap">
              <select aria-label="舆情时间范围"><option>近 30 天</option><option>近 7 天</option><option>近 24 小时</option></select>
              <svg class="ico chev"><use href="#ico-chev"/></svg>
            </div>
          </div>
        </div>

        <div class="grid kpi-grid">
          <div class="card kpi" data-ev data-num="1,284" data-unit="条" data-name="声量总计"
               data-src="sentiment_daily#8821（channel='all', range='近30天'）" data-asof="2026-09-30T23:59+08:00" data-scope="舆情 · 公开渠道 · 近30天">
            <div class="kpi-label">声量总计 · 近 30 天</div>
            <div class="kpi-value">1,284<span class="kpi-unit">条</span></div>
            <div class="kpi-foot"><span class="delta up">+8.4%</span><span>较上一周期</span><span class="drill-hint">选中即问 · 问这个 ↗</span></div>
          </div>
          <div class="card kpi" data-ev data-num="12.6" data-unit="%" data-name="负面占比"
               data-src="sentiment_daily#8821（polarity='negative' / total）" data-asof="2026-09-30T23:59+08:00" data-scope="舆情 · 负面占比 · 阈值 15%">
            <div class="kpi-label">负面占比</div>
            <div class="kpi-value" style="color:var(--neg)">12.6<span class="kpi-unit" style="color:var(--ink-3)">%</span></div>
            <div class="kpi-foot"><span class="delta up">-1.8 pt</span><span>低于预警阈值 15%</span><span class="drill-hint">选中即问 · 问这个 ↗</span></div>
          </div>
          <div class="card kpi" data-ev data-num="4 / 6" data-unit="已连接" data-name="覆盖渠道"
               data-src="sentiment_channel_status（collecting/done/error 三态聚合）" data-asof="2026-09-30T18:20+08:00" data-scope="舆情 · 渠道覆盖">
            <div class="kpi-label">覆盖渠道</div>
            <div class="kpi-value">4<span class="kpi-unit">/ 6 已连接</span></div>
            <div class="kpi-foot"><span class="delta flat">1 采集中 · 1 失败</span><span class="drill-hint">选中即问 · 问这个 ↗</span></div>
          </div>
        </div>

        <div class="risk-banner">
          <span class="risk-dot"></span>
          <div class="risk-main">
            <div class="risk-title">风险横幅 · 冬季续航争议升温</div>
            <div class="risk-reasons">社交平台近 24h 负面声量环比 +63%，命中「续航 / 冬测」关键词，已跨过负面占比日阈值。</div>
          </div>
          <div class="risk-stats">
            <div><small>24h 负面声量</small><b style="color:var(--neg)">86</b></div>
            <div><small>负面占比</small><b style="color:var(--neg)">12.6%</b></div>
            <div><small>影响账号</small><b>3</b></div>
          </div>
        </div>

        <div class="grid main-grid">
          <div class="card is-hoverable">
            <div class="card-head">
              <h3 class="card-title">声量趋势</h3>
              <span class="card-meta">近 14 天 · 单位：条</span>
            </div>
            <svg class="chart" viewBox="0 0 720 200" role="img" aria-label="近14天声量趋势面积图">
              <line class="chart-grid" x1="36" y1="16" x2="704" y2="16"/>
              <line class="chart-grid" x1="36" y1="94" x2="704" y2="94"/>
              <line class="chart-grid" x1="36" y1="172" x2="704" y2="172"/>
              <path class="chart-area" d="M36 103.7 L87.4 94.7 L138.8 106.6 L190.2 82.9 L241.5 73.9 L292.9 84.3 L344.3 67.3 L395.7 60.6 L447.1 69.5 L498.5 51.7 L549.8 45 L601.2 54.6 L652.6 41.3 L704 32.3 L704 172 L36 172 Z"/>
              <path class="chart-line" d="M36 103.7 L87.4 94.7 L138.8 106.6 L190.2 82.9 L241.5 73.9 L292.9 84.3 L344.3 67.3 L395.7 60.6 L447.1 69.5 L498.5 51.7 L549.8 45 L601.2 54.6 L652.6 41.3 L704 32.3"/>
              <circle class="chart-dot" cx="704" cy="32.3" r="3.4"/>
              <text class="chart-axis" x="36" y="188" text-anchor="start">9/17</text>
              <text class="chart-axis" x="344.3" y="188" text-anchor="middle">9/24</text>
              <text class="chart-axis" x="704" y="188" text-anchor="end">9/30</text>
            </svg>
          </div>
          <div class="card is-hoverable">
            <div class="card-head">
              <h3 class="card-title">情绪分布</h3>
              <span class="card-meta">正面=蓝 / 负面=红<br>近 30 天</span>
            </div>
            <div class="hbars">
              <div class="hbar"><span class="hbar-key">正面</span><span class="hbar-track"><i class="is-pos" style="width:41%"></i></span><span class="hbar-val">41%</span></div>
              <div class="hbar"><span class="hbar-key">中性</span><span class="hbar-track"><i class="is-neutral" style="width:46%"></i></span><span class="hbar-val">46%</span></div>
              <div class="hbar"><span class="hbar-key">负面</span><span class="hbar-track"><i class="is-neg" style="width:13%"></i></span><span class="hbar-val" style="color:var(--neg)">13%</span></div>
            </div>
            <div class="card-foot"><span class="card-meta" style="text-align:left">口径：polarity 三分类</span><span class="evi-badge">sentiment#8821</span></div>
          </div>
        </div>

        <div class="grid two-grid">
          <div class="card">
            <div class="card-head"><h3 class="card-title">渠道采集状态</h3><span class="card-meta">pchip · 三态</span></div>
            <div class="pchips">
              <span class="pchip ph-done"><span class="ph-ic">●</span>微博<span class="ph-cnt">428</span></span>
              <span class="pchip ph-done"><span class="ph-ic">●</span>汽车之家<span class="ph-cnt">312</span></span>
              <span class="pchip ph-done"><span class="ph-ic">●</span>懂车帝<span class="ph-cnt">264</span></span>
              <span class="pchip ph-done"><span class="ph-ic">●</span>新闻聚合<span class="ph-cnt">158</span></span>
              <span class="pchip ph-collecting"><span class="ph-ic">◐</span>小红书<span class="ph-cnt">…</span></span>
              <span class="pchip ph-error"><span class="ph-ic">✕</span>抖音<span class="ph-cnt">失败</span></span>
            </div>
            <div class="card-foot">
              <span class="card-meta" style="text-align:left">仅 GPL / 学习研究 license · 公开内容</span>
              <button class="btn btn-ghost btn-sm" id="retryChannel">重试采集</button>
            </div>
          </div>
          <div class="card">
            <div class="card-head"><h3 class="card-title">热点议题</h3><span class="card-meta">按热度排序</span></div>
            <div class="list">
              <div class="list-row">
                <div class="list-main"><div class="list-title">银河E5 冬季续航实测争议</div><div class="list-sub">社交平台 · 2 小时前</div></div>
                <div class="list-right"><span class="tag tag-neg">负面</span><span class="heat"><span class="heat-track"><i style="width:86%"></i></span><b>86</b></span></div>
              </div>
              <div class="list-row">
                <div class="list-main"><div class="list-title">城市 NOA 推送节奏讨论</div><div class="list-sub">车主论坛 · 6 小时前</div></div>
                <div class="list-right"><span class="tag">中性</span><span class="heat"><span class="heat-track"><i style="width:72%"></i></span><b>72</b></span></div>
              </div>
              <div class="list-row">
                <div class="list-main"><div class="list-title">充电桩兼容性反馈</div><div class="list-sub">科技媒体 · 昨天</div></div>
                <div class="list-right"><span class="tag">中性</span><span class="heat"><span class="heat-track"><i style="width:61%"></i></span><b>61</b></span></div>
              </div>
              <div class="list-row">
                <div class="list-main"><div class="list-title">冬季服务月获车主好评</div><div class="list-sub">新闻媒体 · 昨天</div></div>
                <div class="list-right"><span class="tag tag-pos">正面</span><span class="heat"><span class="heat-track"><i style="width:48%"></i></span><b>48</b></span></div>
              </div>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-head"><h3 class="card-title">事件预警</h3><span class="card-meta">3 条规则 · 2 条生效</span></div>
          <div class="list">
            <div class="list-row">
              <div class="list-main"><div class="list-title">负面占比超过阈值</div><div class="list-sub">当前 12.6% / 阈值 15%</div></div>
              <div class="list-right"><span class="tag tag-pos">已启用</span></div>
            </div>
            <div class="list-row">
              <div class="list-main"><div class="list-title">1 小时内负面声量激增 50%</div><div class="list-sub">近 7 天触发 2 次</div></div>
              <div class="list-right"><span class="tag tag-pos">已启用</span></div>
            </div>
            <div class="list-row">
              <div class="list-main"><div class="list-title">头部账号发布负面内容</div><div class="list-sub">因渠道失败暂不可用</div></div>
              <div class="list-right"><span class="tag">已停用</span></div>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ 看板 3 · 配置 ============ -->
      <section class="board" id="board-config" role="tabpanel" aria-labelledby="tab-config">
        <div class="board-head">
          <div>
            <div class="eyebrow">Config · 产品力</div>
            <h2 class="board-title">配置矩阵</h2>
            <p class="board-desc">产品力主轴。以接口返回的 12 个 spec_id 为行，关键配置项为列；首列冻结，可横向滚动。</p>
          </div>
          <div class="head-ctrl">
            <span class="field-label">对象三级（车系 → 年款 → 版型）</span>
            <div class="select-wrap">
              <select aria-label="年款"><option>全部年款</option><option>2026 款</option><option>2025 款</option></select>
              <svg class="ico chev"><use href="#ico-chev"/></svg>
            </div>
          </div>
        </div>

        <div class="grid kpi-grid">
          <div class="card kpi" data-ev data-num="12" data-unit="个" data-name="在售版型数"
               data-src="config_spec（SELECT DISTINCT spec_id）→ 12 行" data-asof="2026-09-02T10:00+08:00" data-scope="配置 · distinct spec_id">
            <div class="kpi-label">在售版型数</div>
            <div class="kpi-value">12<span class="kpi-unit">个 spec_id</span></div>
            <div class="kpi-foot"><span class="delta up">+2</span><span>较上版快照</span><span class="drill-hint">选中即问 · 问这个 ↗</span></div>
          </div>
          <div class="card kpi" data-ev data-num="2026-09-02" data-unit="" data-name="配置快照版本"
               data-src="config_snapshot#meta（version=2026-09-02）" data-asof="2026-09-02T10:00+08:00" data-scope="配置 · 快照版本">
            <div class="kpi-label">配置快照版本</div>
            <div class="kpi-value" style="font-size:22px">2026-09-02</div>
            <div class="kpi-foot"><span class="delta flat">最近一次同步</span><span class="drill-hint">选中即问 · 问这个 ↗</span></div>
          </div>
          <div class="card kpi" data-ev data-num="2026 / 2025" data-unit="" data-name="年款分布"
               data-src="config_spec（GROUP BY model_year）→ 2026:8 / 2025:4" data-asof="2026-09-02T10:00+08:00" data-scope="配置 · 年款分布">
            <div class="kpi-label">年款分布</div>
            <div class="kpi-value">2026 <span class="kpi-unit">8 版型 · 2025 4 版型</span></div>
            <div class="kpi-foot"><span class="delta flat">接口 GROUP BY</span><span class="drill-hint">选中即问 · 问这个 ↗</span></div>
          </div>
        </div>

        <div class="card">
          <div class="card-head">
            <h3 class="card-title">版型 × 配置项 矩阵</h3>
            <span class="card-meta">首列冻结 · 可横向滚动<br>12 个 spec_id · as_of 2026-09-02</span>
          </div>
          <div class="matrix-wrap">
            <table>
              <thead>
                <tr>
                  <th class="sticky-col">spec_id / 版型</th>
                  <th>年款</th><th>CLTC 续航</th><th>电池容量</th><th>座椅材质</th><th>前排通风</th>
                  <th>隔音玻璃</th><th>轮毂尺寸</th><th>智驾方案</th><th>车机芯片</th>
                </tr>
              </thead>
              <tbody>
                <tr><td class="sticky-col">73702 · 星耀版</td><td>2026</td><td class="num">440 km</td><td class="num">49.5 kWh</td><td>织物</td><td>—</td><td>—</td><td class="num">17″</td><td>基础 L2</td><td>E02</td></tr>
                <tr><td class="sticky-col">73943 · 星享版</td><td>2026</td><td class="num">440 km</td><td class="num">49.5 kWh</td><td>仿皮</td><td>—</td><td>—</td><td class="num">17″</td><td>基础 L2</td><td>E02</td></tr>
                <tr><td class="sticky-col">73944 · 星悦版</td><td>2026</td><td class="num">530 km</td><td class="num">60.2 kWh</td><td>仿皮</td><td>●</td><td>●</td><td class="num">18″</td><td>高速 NOA</td><td>8155</td></tr>
                <tr><td class="sticky-col">73945 · 星耀智驾版</td><td>2026</td><td class="num">530 km</td><td class="num">60.2 kWh</td><td>仿皮</td><td>●</td><td>●</td><td class="num">18″</td><td>高速 NOA</td><td>8155</td></tr>
                <tr><td class="sticky-col">73949 · 星驭版</td><td>2026</td><td class="num">550 km</td><td class="num">62.0 kWh</td><td>真皮</td><td>●</td><td>●</td><td class="num">19″</td><td>城市 NOA</td><td>8155</td></tr>
                <tr><td class="sticky-col">73952 · 星驭四驱版</td><td>2026</td><td class="num">530 km</td><td class="num">62.0 kWh</td><td>真皮</td><td>●</td><td>●</td><td class="num">19″</td><td>城市 NOA</td><td>8155</td></tr>
                <tr><td class="sticky-col">78132 · 星耀版 25 款</td><td>2025</td><td class="num">430 km</td><td class="num">48.0 kWh</td><td>织物</td><td>—</td><td>—</td><td class="num">17″</td><td>基础 L2</td><td>E02</td></tr>
                <tr><td class="sticky-col">79266 · 星悦版 25 款</td><td>2025</td><td class="num">520 km</td><td class="num">59.0 kWh</td><td>仿皮</td><td>●</td><td>—</td><td class="num">18″</td><td>高速 NOA</td><td>8155</td></tr>
                <tr><td class="sticky-col">79310 · 星享版 25 款</td><td>2025</td><td class="num">430 km</td><td class="num">48.0 kWh</td><td>仿皮</td><td>—</td><td>—</td><td class="num">17″</td><td>基础 L2</td><td>E02</td></tr>
                <tr><td class="sticky-col">79311 · 星耀智驾 25 款</td><td>2025</td><td class="num">520 km</td><td class="num">59.0 kWh</td><td>仿皮</td><td>●</td><td>●</td><td class="num">18″</td><td>高速 NOA</td><td>8155</td></tr>
                <tr><td class="sticky-col">79312 · 星驭 25 款 <span class="evi-badge weak">缺失</span></td><td>2025</td><td class="num">540 km</td><td class="num">61.0 kWh</td><td>真皮</td><td>●</td><td>●</td><td class="num">19″</td><td>—</td><td>—</td></tr>
                <tr><td class="sticky-col">79313 · 星驭四驱 25 款 <span class="evi-badge weak">缺失</span></td><td>2025</td><td class="num">520 km</td><td class="num">61.0 kWh</td><td>真皮</td><td>●</td><td>●</td><td class="num">19″</td><td>—</td><td>—</td></tr>
              </tbody>
            </table>
          </div>
          <div class="card-foot">
            <span class="evi-badge weak">非车系级缺失 · 2 个 spec_id 列不全（琥珀）</span>
            <span class="card-meta" style="text-align:right">规范：SPECS 由接口返回 12 个，含 73943 / 73944</span>
          </div>
        </div>

        <div class="grid two-grid">
          <div class="card">
            <div class="card-head"><h3 class="card-title">赋分展示卡</h3><span class="card-meta">来自配置源 tiers<br>总分 55,000 · 档位 2,200</span></div>
            <table>
              <thead><tr><th>赋分项</th><th class="num">得分</th><th>档位</th></tr></thead>
              <tbody>
                <tr><td>A1 舒适性配置</td><td class="num">84</td><td><span class="tag tag-accent">A 档</span></td></tr>
                <tr><td>B1 智能驾驶</td><td class="num">71</td><td><span class="tag">B 档</span></td></tr>
                <tr><td>C1 三电与续航</td><td class="num">78</td><td><span class="tag">B 档</span></td></tr>
                <tr><td>D1 座舱与车机</td><td class="num">66</td><td><span class="tag tag-warn">C 档</span></td></tr>
              </tbody>
            </table>
          </div>
          <div class="card">
            <div class="card-head"><h3 class="card-title">关键配置项覆盖</h3><span class="card-meta">按版型命中数</span></div>
            <div class="hbars">
              <div class="hbar"><span class="hbar-key">仿皮及以上</span><span class="hbar-track"><i class="is-pos" style="width:83%"></i></span><span class="hbar-val">10/12</span></div>
              <div class="hbar"><span class="hbar-key">前排通风</span><span class="hbar-track"><i class="is-pos" style="width:58%"></i></span><span class="hbar-val">7/12</span></div>
              <div class="hbar"><span class="hbar-key">隔音玻璃</span><span class="hbar-track"><i class="is-pos" style="width:50%"></i></span><span class="hbar-val">6/12</span></div>
              <div class="hbar"><span class="hbar-key">8155 芯片</span><span class="hbar-track"><i class="is-pos" style="width:58%"></i></span><span class="hbar-val">7/12</span></div>
              <div class="hbar"><span class="hbar-key">城市 NOA</span><span class="hbar-track"><i class="is-warn" style="width:17%"></i></span><span class="hbar-val">2/12</span></div>
            </div>
            <div class="card-foot"><span class="card-meta" style="text-align:left">城市 NOA 命中率最低，为产品力短板</span></div>
          </div>
        </div>
      </section>

      <!-- ============ 看板 4 · 口碑 ============ -->
      <section class="board" id="board-reviews" role="tabpanel" aria-labelledby="tab-reviews">
        <div class="board-head">
          <div>
            <div class="eyebrow">Reviews · 需求验证</div>
            <h2 class="board-title">用户口碑</h2>
            <p class="board-desc">owner_reviews + review_tags 维度聚合。U 全站正面=蓝、负面=红；净态度 &gt;0 蓝、&lt;0 红。</p>
          </div>
          <div class="head-ctrl">
            <span class="field-label">维度筛选 · 默认「舒适」</span>
            <div class="select-wrap">
              <select aria-label="口碑维度"><option>全部维度</option><option selected>舒适</option><option>续航</option><option>智驾</option></select>
              <svg class="ico chev"><use href="#ico-chev"/></svg>
            </div>
          </div>
        </div>

        <div class="grid kpi-grid">
          <div class="card kpi" data-ev data-num="1,274" data-unit="条" data-name="口碑总数"
               data-src="owner_reviews（COUNT(*)）→ 1,274 行" data-asof="2026-09-30T23:59+08:00" data-scope="口碑 · 全部维度 · 近30天">
            <div class="kpi-label">口碑总数</div>
            <div class="kpi-value">1,274<span class="kpi-unit">条</span></div>
            <div class="kpi-foot"><span class="delta up">+64</span><span>近 30 天新增</span><span class="drill-hint">选中即问 · 问这个 ↗</span></div>
          </div>
          <div class="card kpi" data-ev data-num="3,235" data-unit="条" data-name="标签总数"
               data-src="review_tags（COUNT(*)）→ 3,235 行" data-asof="2026-09-30T23:59+08:00" data-scope="口碑 · 标签 · 全量">
            <div class="kpi-label">标签总数</div>
            <div class="kpi-value">3,235<span class="kpi-unit">条</span></div>
            <div class="kpi-foot"><span class="delta flat">平均 2.5 标签/条</span><span class="drill-hint">选中即问 · 问这个 ↗</span></div>
          </div>
          <div class="card kpi" data-ev data-num="92.5" data-unit="%" data-name="打标覆盖率"
               data-src="review_tags（distinct review_id）/ owner_reviews → 92.5%" data-asof="2026-09-30T23:59+08:00" data-scope="口碑 · 覆盖率">
            <div class="kpi-label">打标覆盖率</div>
            <div class="kpi-value">92.5<span class="kpi-unit">%</span></div>
            <div class="kpi-foot"><span class="delta down">7.5% 落入「其他」</span><span class="drill-hint">选中即问 · 问这个 ↗</span></div>
          </div>
        </div>

        <div class="grid main-grid">
          <div class="card">
            <div class="card-head">
              <h3 class="card-title">维度聚合表</h3>
              <span class="card-meta">pro 蓝 / con 红 · 净态度符号定色<br>as_of 2026-09-30</span>
            </div>
            <div class="table-scroll">
              <table>
                <thead><tr><th>维度</th><th class="num">pro</th><th class="num">con</th><th class="num">con%</th><th class="num">净态度</th></tr></thead>
                <tbody>
                  <tr><td>舒适</td><td class="num" style="color:var(--pos)">412</td><td class="num" style="color:var(--neg)">96</td><td class="num">18.9%</td><td class="num" style="color:var(--pos)">+316</td></tr>
                  <tr><td>空间</td><td class="num" style="color:var(--pos)">368</td><td class="num" style="color:var(--neg)">88</td><td class="num">19.3%</td><td class="num" style="color:var(--pos)">+280</td></tr>
                  <tr><td>续航</td><td class="num" style="color:var(--pos)">224</td><td class="num" style="color:var(--neg)">176</td><td class="num" style="color:var(--neg)">44.0%</td><td class="num" style="color:var(--pos)">+48</td></tr>
                  <tr><td>智驾</td><td class="num" style="color:var(--pos)">286</td><td class="num" style="color:var(--neg)">94</td><td class="num">24.7%</td><td class="num" style="color:var(--pos)">+192</td></tr>
                  <tr><td>车机</td><td class="num" style="color:var(--pos)">198</td><td class="num" style="color:var(--neg)">124</td><td class="num" style="color:var(--neg)">38.5%</td><td class="num" style="color:var(--pos)">+74</td></tr>
                  <tr><td>售后</td><td class="num" style="color:var(--pos)">142</td><td class="num" style="color:var(--neg)">158</td><td class="num" style="color:var(--neg)">52.7%</td><td class="num" style="color:var(--neg)">-16</td></tr>
                </tbody>
              </table>
            </div>
            <div class="card-foot">
              <span class="evi-badge weak">「其他」桶待拆解 · 96 条</span>
              <span class="card-meta" style="text-align:right">净态度 = pro - con</span>
            </div>
          </div>
          <div class="card">
            <div class="card-head"><h3 class="card-title">维度总量分布</h3><span class="card-meta">con% 高 → 红</span></div>
            <div class="hbars">
              <div class="hbar"><span class="hbar-key">舒适</span><span class="hbar-track"><i class="is-pos" style="width:100%"></i></span><span class="hbar-val">508</span></div>
              <div class="hbar"><span class="hbar-key">空间</span><span class="hbar-track"><i class="is-pos" style="width:90%"></i></span><span class="hbar-val">456</span></div>
              <div class="hbar"><span class="hbar-key">智驾</span><span class="hbar-track"><i class="is-pos" style="width:75%"></i></span><span class="hbar-val">380</span></div>
              <div class="hbar"><span class="hbar-key">续航</span><span class="hbar-track"><i class="is-neg" style="width:79%"></i></span><span class="hbar-val">400</span></div>
              <div class="hbar"><span class="hbar-key">车机</span><span class="hbar-track"><i class="is-neg" style="width:63%"></i></span><span class="hbar-val">322</span></div>
              <div class="hbar"><span class="hbar-key">售后</span><span class="hbar-track"><i class="is-neg" style="width:59%"></i></span><span class="hbar-val">300</span></div>
            </div>
            <div class="card-foot"><span class="card-meta" style="text-align:left">红条 = con% ≥ 35% 的维度</span></div>
          </div>
        </div>

        <div class="grid main-grid">
          <div class="card">
            <div class="card-head"><h3 class="card-title">原文样本</h3><span class="card-meta">review_id + 原文 + 情感 + 溯源</span></div>
            <div class="sample">
              <div class="sample-head"><span class="sample-id">owner_reviews#20481</span><span class="tag tag-pos">正面</span><span class="tag tag-accent">舒适</span></div>
              <p class="sample-text">提车三个月，座椅包裹和后排空间都很满意，高速上隔音也超出预期。</p>
              <div class="sample-src">溯源：review_tags#51204（dim=comfort, polarity=positive）· as_of 2026-09-28</div>
            </div>
            <div class="sample">
              <div class="sample-head"><span class="sample-id">owner_reviews#20477</span><span class="tag tag-neg">负面</span><span class="tag tag-accent">续航</span></div>
              <p class="sample-text">冬天开空调续航打折比较明显，标称 530 实际跑高速大概四百出头。</p>
              <div class="sample-src">溯源：review_tags#51188（dim=range, polarity=negative）· as_of 2026-09-27</div>
            </div>
            <div class="sample">
              <div class="sample-head"><span class="sample-id">owner_reviews#20470</span><span class="tag tag-neg">负面</span><span class="tag tag-accent">车机</span></div>
              <p class="sample-text">车机偶尔要重启，导航切换有点卡，希望后续 OTA 能优化。</p>
              <div class="sample-src">溯源：review_tags#51152（dim=hmi, polarity=negative）· as_of 2026-09-26</div>
            </div>
          </div>
          <div class="card">
            <div class="card-head"><h3 class="card-title">口碑趋势</h3><span class="card-meta">近 12 周 · 净态度指数</span></div>
            <svg class="chart" viewBox="0 0 720 200" role="img" aria-label="近12周口碑趋势折线图">
              <line class="chart-grid" x1="36" y1="16" x2="704" y2="16"/>
              <line class="chart-grid" x1="36" y1="94" x2="704" y2="94"/>
              <line class="chart-grid" x1="36" y1="172" x2="704" y2="172"/>
              <path class="chart-line" d="M36 96.1 L97.9 87.4 L159.8 79.4 L221.7 82.6 L283.6 70.9 L345.5 59.1 L407.4 62.3 L469.3 49.2 L531.2 44.2 L593.1 41.0 L655 43.5 L704 46.0"/>
              <circle class="chart-dot" cx="704" cy="46" r="3.4"/>
              <text class="chart-axis" x="36" y="188" text-anchor="start">7/14</text>
              <text class="chart-axis" x="345.5" y="188" text-anchor="middle">8/25</text>
              <text class="chart-axis" x="704" y="188" text-anchor="end">9/30</text>
            </svg>
            <div class="card-foot">
              <span class="card-meta" style="text-align:left">近 4 周净态度回落，与续航负面占比抬升同期</span>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ 看板 5 · 销量 ============ -->
      <section class="board" id="board-sales" role="tabpanel" aria-labelledby="tab-sales">
        <div class="board-head">
          <div>
            <div class="eyebrow">Sales · 市场结果</div>
            <h2 class="board-title">销量与终端价</h2>
            <p class="board-desc">sales_trim 月末行 retail + 同版型 tp 对比。市场侧结果不归因到产品力（相关性当因果）。</p>
          </div>
          <div class="head-ctrl">
            <span class="field-label">口径切换</span>
            <div class="select-wrap">
              <select aria-label="销量口径"><option>月末行 retail</option><option>同版型 tp</option></select>
              <svg class="ico chev"><use href="#ico-chev"/></svg>
            </div>
          </div>
        </div>

        <div class="grid kpi-grid">
          <div class="card kpi" data-ev data-num="96,480" data-unit="台" data-name="累计零售"
               data-src="sales_trim（SUM(retail) where month_end=1）→ 96,480" data-asof="2026-09-30T23:59+08:00" data-scope="销量 · 近12个月 · 月末行 retail">
            <div class="kpi-label">累计零售 · 近 12 个月</div>
            <div class="kpi-value">96,480<span class="kpi-unit">台</span></div>
            <div class="kpi-foot"><span class="delta down">9 月 -12.0%</span><span>环比</span><span class="drill-hint">选中即问 · 问这个 ↗</span></div>
          </div>
          <div class="card kpi" data-ev data-num="-2.1" data-unit="万" data-name="终端价降幅"
               data-src="sales_trim（tp 同版型对比 #11204）→ -2.10 万" data-asof="2026-09-30T23:59+08:00" data-scope="销量 · 同版型 tp 对比">
            <div class="kpi-label">终端价降幅 · 同版型</div>
            <div class="kpi-value" style="color:var(--neg)">-2.1<span class="kpi-unit" style="color:var(--ink-3)">万</span></div>
            <div class="kpi-foot"><span class="delta down">降幅集中在主销版型</span><span class="drill-hint">选中即问 · 问这个 ↗</span></div>
          </div>
          <div class="card kpi" data-ev data-num="12" data-unit="个" data-name="在售版型"
               data-src="sales_trim（distinct spec_id, month_end=1）→ 12" data-asof="2026-09-30T23:59+08:00" data-scope="销量 · 在售版型">
            <div class="kpi-label">在售版型</div>
            <div class="kpi-value">12<span class="kpi-unit">个 spec_id</span></div>
            <div class="kpi-foot"><span class="delta flat">与配置源一致</span><span class="drill-hint">选中即问 · 问这个 ↗</span></div>
          </div>
        </div>

        <div class="grid main-grid">
          <div class="card is-hoverable">
            <div class="card-head"><h3 class="card-title">月度零售</h3><span class="card-meta">近 12 个月 · 峰值高亮<br>单位：台</span></div>
            <svg class="chart" viewBox="0 0 720 220" role="img" aria-label="月度零售柱状图">
              <line class="chart-grid" x1="40" y1="16" x2="704" y2="16"/>
              <line class="chart-grid" x1="40" y1="103" x2="704" y2="103"/>
              <line class="chart-grid" x1="40" y1="190" x2="704" y2="190"/>
              <rect class="chart-bar" x="51.7" y="104.8" width="32" height="85.2" rx="3"/>
              <rect class="chart-bar" x="107" y="113.7" width="32" height="76.3" rx="3"/>
              <rect class="chart-bar" x="162.4" y="89.6" width="32" height="100.4" rx="3"/>
              <rect class="chart-bar" x="217.7" y="94.1" width="32" height="95.9" rx="3"/>
              <rect class="chart-bar" x="273" y="77" width="32" height="113.0" rx="3"/>
              <rect class="chart-bar" x="328.4" y="83.5" width="32" height="106.5" rx="3"/>
              <rect class="chart-bar" x="383.7" y="61.8" width="32" height="128.2" rx="3"/>
              <rect class="chart-bar" x="439.1" y="66.9" width="32" height="123.1" rx="3"/>
              <rect class="chart-bar" x="494.4" y="47.1" width="32" height="142.9" rx="3"/>
              <rect class="chart-bar is-peak" x="549.8" y="32.2" width="32" height="157.8" rx="3"/>
              <rect class="chart-bar" x="605.1" y="52.7" width="32" height="137.3" rx="3"/>
              <rect class="chart-bar" x="660.4" y="68.6" width="32" height="121.4" rx="3"/>
              <text class="chart-axis" x="67.7" y="208" text-anchor="middle">10</text>
              <text class="chart-axis" x="178.4" y="208" text-anchor="middle">12</text>
              <text class="chart-axis" x="289" y="208" text-anchor="middle">2</text>
              <text class="chart-axis" x="399.7" y="208" text-anchor="middle">4</text>
              <text class="chart-axis" x="510.4" y="208" text-anchor="middle">6</text>
              <text class="chart-axis" x="621" y="208" text-anchor="middle">8</text>
              <text class="chart-axis" x="676.4" y="208" text-anchor="middle">9月</text>
            </svg>
            <div class="legend"><span><i style="background:var(--pos);opacity:.30"></i>月度零售（台）</span><span><i style="background:var(--pos)"></i>峰值月</span></div>
          </div>
          <div class="card">
            <div class="card-head"><h3 class="card-title">版型结构</h3><span class="card-meta">9 月零售占比</span></div>
            <div class="hbars">
              <div class="hbar"><span class="hbar-key">星悦版</span><span class="hbar-track"><i class="is-accent" style="width:100%"></i></span><span class="hbar-val">3,420</span></div>
              <div class="hbar"><span class="hbar-key">星驭版</span><span class="hbar-track"><i class="is-accent" style="width:82%"></i></span><span class="hbar-val">2,806</span></div>
              <div class="hbar"><span class="hbar-key">星耀智驾版</span><span class="hbar-track"><i class="is-accent" style="width:63%"></i></span><span class="hbar-val">2,154</span></div>
              <div class="hbar"><span class="hbar-key">星享版</span><span class="hbar-track"><i class="is-accent" style="width:48%"></i></span><span class="hbar-val">1,642</span></div>
              <div class="hbar"><span class="hbar-key">星驭四驱版</span><span class="hbar-track"><i class="is-accent" style="width:31%"></i></span><span class="hbar-val">1,058</span></div>
              <div class="hbar"><span class="hbar-key">星耀版</span><span class="hbar-track"><i class="is-accent" style="width:23%"></i></span><span class="hbar-val">786</span></div>
            </div>
            <div class="card-foot"><span class="card-meta" style="text-align:left">主销版型集中度高</span></div>
          </div>
        </div>

        <div class="grid main-grid">
          <div class="card">
            <div class="card-head"><h3 class="card-title">竞品对比</h3><span class="card-meta">环比涨跌：涨蓝 / 跌红<br>口径 月末行 retail</span></div>
            <div class="table-scroll">
              <table>
                <thead><tr><th>车系</th><th class="num">上月</th><th class="num">本月</th><th class="num">环比</th></tr></thead>
                <tbody>
                  <tr><td>银河E5</td><td class="num">12,880</td><td class="num">11,340</td><td class="num" style="color:var(--neg)">-12.0%</td></tr>
                  <tr><td>竞品 A</td><td class="num">9,420</td><td class="num">10,180</td><td class="num" style="color:var(--pos)">+8.1%</td></tr>
                  <tr><td>竞品 B</td><td class="num">8,760</td><td class="num">8,110</td><td class="num" style="color:var(--neg)">-7.4%</td></tr>
                  <tr><td>竞品 C</td><td class="num">7,650</td><td class="num">7,980</td><td class="num" style="color:var(--pos)">+4.3%</td></tr>
                </tbody>
              </table>
            </div>
            <div class="card-foot"><span class="evi-badge">示例数据 · 竞品行待接接口</span></div>
          </div>
          <div class="card">
            <div class="card-head"><h3 class="card-title">终端价趋势</h3><span class="card-meta">同版型 tp · 单位：万元</span></div>
            <svg class="chart" viewBox="0 0 720 200" role="img" aria-label="终端价趋势折线图">
              <line class="chart-grid" x1="36" y1="16" x2="704" y2="16"/>
              <line class="chart-grid" x1="36" y1="94" x2="704" y2="94"/>
              <line class="chart-grid" x1="36" y1="172" x2="704" y2="172"/>
              <path class="chart-line-neg" d="M36 34.4 L87.4 46.1 L138.8 50.3 L190.2 61.6 L241.5 72.9 L292.9 84.2 L344.3 88.3 L395.7 99.6 L447.1 110.8 L498.5 115.0 L549.8 126.2 L601.2 131.4 L652.6 137.7 L704 145.0"/>
              <circle class="chart-dot-neg" cx="704" cy="145" r="3.4"/>
              <text class="chart-axis" x="36" y="188" text-anchor="start">24/10</text>
              <text class="chart-axis" x="345.5" y="188" text-anchor="middle">25/04</text>
              <text class="chart-axis" x="704" y="188" text-anchor="end">26/09</text>
            </svg>
            <div class="card-foot"><span class="card-meta" style="text-align:left">近 12 个月终端价持续下探，累计 -2.1 万</span></div>
          </div>
        </div>
      </section>

    </div><!-- /board-scroll -->
   </div><!-- /viewBoard -->

   <!-- 视图二：对话（Agent） · 空态 hero + 有消息态示例（同一屏幕可并见） -->
   <div class="view" id="viewChat">
    <div class="chat-scroll" id="chatScroll">
     <div class="chat-inner">

      <!-- 空态（默认展示）：巨型衬线字标 + 对象 chip + 建议问题胶囊 -->
      <section class="chat-hero" id="chatHero">
        <h1 class="hero-wordmark">Prism Agent</h1>
        <p class="hero-sub">棱镜三维度 · 配置 → 口碑 → 销量</p>
        <div class="hero-obj">
          <span class="obj-chip"><span class="dot-ok"></span><b>银河E5</b><span style="color:var(--ink-3)">· 2026 款</span></span>
          <span class="hero-meta">as_of 2026-09-30 · 数据源 就绪 · series=7650（resolve_series 已核验）</span>
        </div>
        <div class="suggest">
          <button type="button" class="suggest-pill" data-suggest="银河E5 近 3 个月口碑为什么下滑？"><svg class="ico"><use href="#ico-chat"/></svg>银河E5 近 3 个月口碑为什么下滑？</button>
          <button type="button" class="suggest-pill" data-suggest="配置侧改了什么，可能影响口碑？"><svg class="ico"><use href="#ico-layers"/></svg>配置侧改了什么，可能影响口碑？</button>
          <button type="button" class="suggest-pill" data-suggest="和竞品比，销量差距在哪？"><svg class="ico"><use href="#ico-kanban"/></svg>和竞品比，销量差距在哪？</button>
          <button type="button" class="suggest-pill" data-suggest="舆情有什么风险信号？"><svg class="ico"><use href="#ico-flask"/></svg>舆情有什么风险信号？</button>
        </div>
        <button type="button" class="btn btn-ghost btn-sm hero-toggle" id="threadToggle">查看示例对话</button>
      </section>

      <!-- 有消息态：点击「查看示例对话」展开 -->
      <section class="chat-thread" id="chatThread" aria-label="示例对话">
        <div class="msg-user">银河E5 近 3 个月口碑为什么下滑？</div>
        <div class="msg-agent">
          <p class="agent-body">近 3 个月口碑净态度回落，主要集中在「续航」与「车机」两个维度：续航维度负面占比升至 44.0%（176 条 con），车机维度 con 占比 38.5%。舒适、空间两维仍为正贡献，说明下滑并非全面性，而是集中在少数维度。</p>

          <!-- b. 嵌一块看板卡片（双模同源的关键证据） -->
          <div class="agent-embed">
            <div class="card-head">
              <h3 class="card-title">口碑维度聚合 · 近 30 天</h3>
              <span class="card-meta">pro 蓝 / con 红<br>as_of 2026-09-30</span>
            </div>
            <div class="hbars">
              <div class="hbar"><span class="hbar-key">续航 con</span><span class="hbar-track"><i class="is-neg" style="width:44%"></i></span><span class="hbar-val" style="color:var(--neg)">44.0%</span></div>
              <div class="hbar"><span class="hbar-key">车机 con</span><span class="hbar-track"><i class="is-neg" style="width:38.5%"></i></span><span class="hbar-val" style="color:var(--neg)">38.5%</span></div>
              <div class="hbar"><span class="hbar-key">舒适 con</span><span class="hbar-track"><i class="is-pos" style="width:18.9%"></i></span><span class="hbar-val">18.9%</span></div>
              <div class="hbar"><span class="hbar-key">空间 con</span><span class="hbar-track"><i class="is-pos" style="width:19.3%"></i></span><span class="hbar-val">19.3%</span></div>
            </div>
          </div>

          <!-- c. 证据徽标行 + 查看证据（复用现有证据抽屉 openDrawer） -->
          <div class="evi-row">
            <span class="evi-badge">supported_by review_tags#51188 · #51152</span>
            <span class="evi-badge">as_of 2026-09-30</span>
            <span class="evi-badge">口径 pro-con · 近30天</span>
            <button type="button" class="btn btn-ghost btn-sm" id="chatEvidenceBtn">查看证据</button>
          </div>

          <!-- d. 工具活动时间线（可折叠） -->
          <details class="tools">
            <summary><svg class="ico"><use href="#ico-arrow-right"/></svg>工具活动 · 3 次调用</summary>
            <div class="tools-list">
              <div class="tool-row"><span class="tk-ok">✓</span><span class="tk-name">query_reviews</span><span>命中 9 行</span><span class="tk-time">312 ms</span></div>
              <div class="tool-row"><span class="tk-ok">✓</span><span class="tk-name">query_config</span><span>命中 12 行</span><span class="tk-time">188 ms</span></div>
              <div class="tool-row"><span class="tk-ok">✓</span><span class="tk-name">query_sales</span><span>命中 12 行</span><span class="tk-time">204 ms</span></div>
            </div>
          </details>

          <!-- e. CLAIM 卡 -->
          <div class="card claim">
            <div class="card-head">
              <h3 class="card-title">CLAIM · 结论</h3>
              <span class="card-meta">scope 银河E5 / 口碑 / 近30天</span>
            </div>
            <p class="claim-text">口碑下滑集中在「续航」与「车机」两维，非全面性下滑；舒适与空间两维仍为正贡献。</p>
            <div class="card-foot">
              <span class="evi-badge strong">证据 强</span>
              <span class="card-meta" style="text-align:right">supported_by review_tags#51188 · as_of 2026-09-30</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 供「查看证据」复用的隐藏数据节点（openDrawer 直接读取其 data-* 属性） -->
      <span id="chatEvNode" hidden data-ev data-num="44.0" data-unit="%" data-name="续航维度负面占比"
            data-src="review_tags（dim='range' AND polarity='negative'）/ dim='range' → 176/400"
            data-asof="2026-09-30T23:59+08:00" data-scope="口碑 · 续航维度 · 近30天"></span>

     </div><!-- /chat-inner -->
    </div><!-- /chat-scroll -->

    <!-- ⑤ composer（**仅对话视图**；看板视图不出现任何输入框，见方案 §5.5.1） -->
    <div class="composer-row">
      <form class="composer" id="composerForm">
        <button type="button" class="icon-btn" aria-label="添加附件"><svg class="ico"><use href="#ico-plus"/></svg></button>
        <button type="button" class="pill scope-pill" id="scopePill" hidden aria-label="移除 scope 锁定">基于：银河E5 · 口碑 <span class="scope-x">✕</span></button>
        <input id="composerInput" type="text" placeholder="向 Prism 提问，或输入指令…" aria-label="提问或指令">
        <button type="button" class="pill"><span class="pill-label">Deepseek V4 Flash</span> <svg class="ico"><use href="#ico-chev"/></svg></button>
        <button type="button" class="pill"><span class="pill-label">推理 High</span> <svg class="ico"><use href="#ico-chev"/></svg></button>
        <button type="button" class="icon-btn" aria-label="语音输入"><svg class="ico"><use href="#ico-mic"/></svg></button>
        <button type="submit" class="send" aria-label="发送"><svg class="ico"><use href="#ico-arrow-up"/></svg></button>
      </form>
    </div>
   </div><!-- /viewChat -->

    <!-- ⑥ 状态栏（发丝，无底色）· 看板态 / 对话态两套内容 -->
    <div class="statusbar" id="statusBar">
      <div class="status-left">
        <span class="status-item st-board"><span class="dot-ok"></span>数据源 就绪</span>
        <span class="status-item st-board">模型 Deepseek V4 Flash</span>
        <span class="status-item st-chat"><span class="dot-ok"></span>数据源就绪</span>
        <span class="status-item st-chat">Deepseek V4 Flash</span>
        <span class="status-item st-chat">当前对象 银河E5</span>
      </div>
      <div class="status-right">
        <span class="status-item st-board">三维度完成度：配置 ✓ · 口碑 ◐ · 销量 ○</span>
        <span class="status-item st-board hide-sm">as_of 2026-09-30T23:59+08:00</span>
        <span class="status-item st-board hide-sm">series=7650</span>
        <span class="status-item st-chat hide-sm">as_of 2026-09-30</span>
      </div>
    </div>

  </div><!-- /main -->
</div><!-- /app -->

<!-- ⑦ 证据抽屉 -->
<div class="drawer-scrim" id="drawerScrim"></div>
<aside class="drawer" id="drawer" aria-label="证据抽屉" aria-hidden="true">
  <div class="drawer-head">
    <div style="flex:1">
      <div class="eyebrow">Evidence</div>
      <div class="drawer-title" id="drawerTitle">证据</div>
    </div>
    <button class="icon-btn" id="drawerClose" aria-label="关闭"><svg class="ico"><use href="#ico-x"/></svg></button>
  </div>
  <div class="drawer-body">
    <div>
      <div class="drawer-num" id="drawerNum">—</div>
      <div class="card-meta" style="text-align:left" id="drawerName">—</div>
    </div>
    <dl class="drawer-kv">
      <div class="row"><dt>supported_by</dt><dd id="drawerSrc">—</dd></div>
      <div class="row"><dt>as_of</dt><dd id="drawerAsof">—</dd></div>
      <div class="row"><dt>口径 / scope</dt><dd id="drawerScope">—</dd></div>
      <div class="row"><dt>覆盖率</dt><dd>见各卡右上角发丝小签</dd></div>
    </dl>
    <div>
      <div class="card-meta" style="text-align:left;margin-bottom:6px">可复算片段（示意）</div>
      <div class="drawer-code" id="drawerCode">SELECT ... FROM ... WHERE as_of = ...</div>
    </div>
    <div class="gap" style="margin-top:2px">
      <div class="gap-head"><span class="gap-title"><svg class="ico"><use href="#ico-flask"/></svg>假设与证据强度</span><span class="evi-badge strong">强</span></div>
      <p class="gap-ask">行 ID 可复算，非通配符；若源表更新，数值可能随 as_of 变化。</p>
    </div>

    <!-- 就地问答：看板「选中即问」的落点（锁 scope / 单轮 / 不产生会话） -->
    <div class="ask-block">
      <div class="ask-head">
        <span class="ask-lock"><svg class="ico"><use href="#ico-atom"/></svg>scope 已锁定 · 单轮</span>
        <span class="ask-note">不产生会话 · 不进侧栏</span>
      </div>
      <form class="ask-form" id="askForm">
        <input id="askInput" type="text" placeholder="就这个数字问一句…" aria-label="就地问答">
        <button type="submit" class="btn btn-primary btn-sm">问这个 ↗</button>
      </form>
      <p class="ask-answer" id="askAnswer"></p>
    </div>
  </div>
  <div class="drawer-foot">
    <button class="btn btn-ghost" id="drawerClose2">关闭</button>
    <button class="btn btn-primary" id="drawerToChat">扩展为会话 ↗</button>
  </div>
</aside>

<div class="toast" id="toast" role="status" aria-live="polite"></div>

<script>
(function(){
  "use strict";
  var $ = function(id){ return document.getElementById(id); };
  var LABEL = { overview:"棱镜结论", sentiment:"舆情", config:"车型配置", reviews:"口碑", sales:"销量" };
  var state = { board: "overview" };

  /* ---------- 看板栏 tab 切换 ---------- */
  var tabs = Array.prototype.slice.call(document.querySelectorAll(".seg-btn"));

  function setBoard(id, focusTab){
    if (!LABEL[id]) id = "overview";
    state.board = id;
    tabs.forEach(function(tab){
      var on = tab.dataset.board === id;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.tabIndex = on ? 0 : -1;
      if (on && focusTab) tab.focus();
    });
    document.querySelectorAll(".board").forEach(function(panel){
      panel.classList.toggle("is-active", panel.id === "board-" + id);
    });
    $("boardScroll").scrollTop = 0;
  }

  tabs.forEach(function(tab, index){
    tab.addEventListener("click", function(){ setBoard(tab.dataset.board, false); });
    tab.addEventListener("keydown", function(event){
      var dir = event.key === "ArrowRight" ? 1 : (event.key === "ArrowLeft" ? -1 : 0);
      if (!dir) return;
      event.preventDefault();
      var next = (index + dir + tabs.length) % tabs.length;
      setBoard(tabs[next].dataset.board, true);
    });
  });

  /* 看板内跳转（cross-link） */
  document.querySelectorAll("[data-board-goto]").forEach(function(btn){
    btn.addEventListener("click", function(){ setBoard(btn.dataset.boardGoto, false); });
  });

  /* ---------- 视图切换：看板（BI） ↔ 对话（Agent） ---------- */
  /* 两视图共享同一「当前对象」上下文；composer 与状态栏固定在底部、不参与滚动 */
  function setView(name, silent){
    var chat = (name === "chat");
    document.getElementById("viewBoard").classList.toggle("is-active", !chat);
    document.getElementById("viewChat").classList.toggle("is-active", chat);
    $("statusBar").classList.toggle("is-chat", chat);
    $("scopePill").hidden = !chat;
    if (chat) {
      $("composerInput").placeholder = "向 Prism 提问，或输入指令…";
      $("composerInput").focus();
      $("chatScroll").scrollTop = 0;
    } else {
      setBoard(state.board, false);
    }
    if (!silent) toast(chat ? "已切到对话视图" : "已切回棱镜工作台");
  }

  /* ---------- 对话视图：建议胶囊 / 示例对话 / scope 锁定 ---------- */
  /* 建议胶囊：把文案填入 composer（不提交） */
  document.querySelectorAll("[data-suggest]").forEach(function(btn){
    btn.addEventListener("click", function(){
      var input = $("composerInput");
      input.value = btn.dataset.suggest;
      input.focus();
      toast("已填入提问（未提交）");
    });
  });

  /* 「查看示例对话」：展开有消息态，hero 收缩到顶部 */
  $("threadToggle").addEventListener("click", function(){
    var on = $("chatScroll").classList.toggle("has-thread");
    this.textContent = on ? "收起示例对话" : "查看示例对话";
    if (on) toast("示例对话：命题 → 证据 → CLAIM");
  });

  /* 「查看证据」复用现有证据抽屉 openDrawer（传入带 data-* 的隐藏节点） */
  $("chatEvidenceBtn").addEventListener("click", function(){ openDrawer($("chatEvNode")); });

  /* scope 锁定 pill：点击 ✕ 移除 */
  $("scopePill").addEventListener("click", function(){
    this.hidden = true;
    toast("已移除 scope 锁定：银河E5 · 口碑");
  });

  /* 侧栏会话行：点击进入对话视图（携带同一对象上下文） */
  document.querySelectorAll('.sb-row[data-nav="chat"]').forEach(function(row){
    row.setAttribute("role", "button");
    row.setAttribute("tabindex", "0");
    row.addEventListener("click", function(){ setView("chat"); });
  });

  /* ---------- 证据抽屉 ---------- */
  var drawer = $("drawer"), scrim = $("drawerScrim");

  function openDrawer(node){
    var num = node.dataset.num || "—";
    var unit = node.dataset.unit || "";
    $("drawerTitle").textContent = (node.dataset.name || "证据") + " · 溯源";
    $("drawerNum").textContent = num + (unit ? " " + unit : "");
    $("drawerName").textContent = node.dataset.name || "";
    $("drawerSrc").textContent = node.dataset.src || "—";
    $("drawerAsof").textContent = node.dataset.asof || "—";
    $("drawerScope").textContent = node.dataset.scope || "—";
    var src = (node.dataset.src || "").split("（")[0];
    $("drawerCode").textContent = "SELECT " + (node.dataset.name || "metric") +
      "\nFROM " + src +
      "\nWHERE as_of = '" + (node.dataset.asof || "") + "'" +
      "\nLIMIT 1;  -- 行 ID 见 supported_by，非通配符";
    drawer.classList.add("is-open");
    drawer.setAttribute("aria-hidden", "false");
    scrim.classList.add("is-open");
  }
  function closeDrawer(){
    drawer.classList.remove("is-open");
    drawer.setAttribute("aria-hidden", "true");
    scrim.classList.remove("is-open");
  }

  document.querySelectorAll("[data-ev]").forEach(function(node){
    node.setAttribute("role", "button");
    node.setAttribute("tabindex", "0");
    node.addEventListener("click", function(){ openDrawer(node); });
    node.addEventListener("keydown", function(event){
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openDrawer(node); }
    });
  });
  $("drawerClose").addEventListener("click", closeDrawer);
  $("drawerClose2").addEventListener("click", closeDrawer);
  scrim.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", function(event){ if (event.key === "Escape") closeDrawer(); });
  /* 「扩展为会话 ↗」：把 scope + 上下文送去对话视图，升格为多轮（单向升级路径） */
  $("drawerToChat").addEventListener("click", function(){
    closeDrawer();
    setView("chat");
    toast("已扩展为会话：scope 已带过去 · 银河E5 · 当前维度（原型演示）");
  });

  /* 就地问答：锁 scope / 单轮 / 不产生会话（看板「选中即问」的落点） */
  $("askForm").addEventListener("submit", function(event){
    event.preventDefault();
    var q = $("askInput").value.trim();
    if (!q) { toast("先输入一句话再问"); return; }
    var ans = $("askAnswer");
    ans.innerHTML = "<b>就地回答</b>（scope 锁定：当前对象 + 本维度）<br>" +
      "该数字由 supported_by 行 ID 复算，口径与 as_of 见上方；" +
      "本问答为单轮、不产生会话。需多轮深挖请用下方「扩展为会话 ↗」。";
    ans.classList.add("is-on");
    toast("单轮问答（原型演示）· 未产生会话");
  });

  /* ---------- toast ---------- */
  var toastTimer;
  function toast(message){
    var node = $("toast");
    node.textContent = message;
    node.classList.add("is-on");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function(){ node.classList.remove("is-on"); }, 2200);
  }

  /* ---------- 顶栏 / 看板栏动作 ---------- */
  $("actionRefresh").addEventListener("click", function(){
    var btn = this;
    btn.classList.add("is-busy");
    setTimeout(function(){
      btn.classList.remove("is-busy");
      toast("已刷新「" + LABEL[state.board] + "」看板数据（示例）");
    }, 620);
  });
  $("rangeSelect").addEventListener("change", function(){ toast("时间范围已切换为 " + this.value + "（示例数据）"); });
  $("objChip").addEventListener("click", function(){ toast("对象已核验（resolve_series 通过）：银河E5 · 7650"); });
  $("cmdk").addEventListener("click", function(){ toast("命令面板（Ctrl K）为原型占位"); });
  $("themeBtn").addEventListener("click", function(){ toast("主题切换为原型占位"); });
  $("retryChannel").addEventListener("click", function(){ toast("已重新发起「抖音」渠道采集"); });
  $("claimToChat").addEventListener("click", function(){
    setView("chat");
    toast("已将本期结论扩展为会话（scope 已带过去）");
  });

  /* ---------- 侧栏导航（设置等为真实可点项） ---------- */
  document.querySelectorAll(".sb-item").forEach(function(btn){
    btn.addEventListener("click", function(){
      var nav = btn.dataset.nav || "";
      if (nav === "workbench") {
        document.querySelectorAll(".sb-item").forEach(function(o){ o.classList.remove("is-active"); });
        btn.classList.add("is-active");
        setView("board");
        return;
      }
      if (nav === "settings") {
        document.querySelectorAll(".sb-item").forEach(function(o){ o.classList.remove("is-active"); });
        btn.classList.add("is-active");
        toast("设置页（原型占位）· 数据源 / 关键词 / 刷新策略");
        return;
      }
      if (nav === "artifacts") { toast("产物列表（原型占位）"); return; }
      if (nav === "new") {
        document.querySelectorAll(".sb-item").forEach(function(o){ o.classList.remove("is-active"); });
        btn.classList.add("is-active");
        setView("chat");
        return;
      }
      toast("已打开会话（原型占位）");
    });
  });
  document.querySelectorAll("[data-sbtab]").forEach(function(tab){
    tab.addEventListener("click", function(){
      document.querySelectorAll("[data-sbtab]").forEach(function(o){
        var on = o === tab;
        o.classList.toggle("is-on", on);
        o.setAttribute("aria-selected", String(on));
      });
    });
  });

  /* ---------- composer ---------- */
  $("composerForm").addEventListener("submit", function(event){
    event.preventDefault();
    var input = $("composerInput");
    if (!input.value.trim()) return;
    input.value = "";
    toast("已加入「" + LABEL[state.board] + "」会话队列（原型演示）");
  });
  document.querySelectorAll(".composer .pill").forEach(function(btn){
    if (btn.id === "scopePill") return; /* scope 锁定按钮单独处理，避免误报 */
    btn.addEventListener("click", function(){ toast("模型 / 推理档位选择（原型占位）"); });
  });
  document.querySelectorAll(".appbar-tools .icon-btn").forEach(function(btn){
    if (btn.id === "themeBtn") return;
    btn.addEventListener("click", function(){ toast("窗口控制（原型占位）"); });
  });
  document.querySelectorAll(".sb-foot .icon-btn").forEach(function(btn){
    btn.addEventListener("click", function(){ toast("侧栏底部图标（原型占位）"); });
  });

  /* ---------- 滚动阴影 ---------- */
  $("boardScroll").addEventListener("scroll", function(){
    $("boardBar").classList.toggle("is-scrolled", $("boardScroll").scrollTop > 4);
  });

  /* ---------- 初始化 ---------- */
  setBoard("overview", false);
  setView("board", true); /* 默认仍停在看板视图，不破坏已验收部分 */
})();
</script>
</body>
</html>
```

</details>

> 回写方法：把原型文件全文替换到上面的 html 围栏代码块内即可（原型内**不含三反引号序列**，可直接内嵌）。