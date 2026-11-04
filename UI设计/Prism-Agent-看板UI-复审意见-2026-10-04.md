# Prism-Agent 看板 UI · 复审意见与决策记录

> 生成：2026-10-04 ｜ 状态：诊断完成，待开工
> 范围：`prism-web` 前端（Kanban 看板栏 + 四看板）
> 参照基准：`UI设计/hermes-agent-kanban.html`（hermes 原型稿，实体文件，非凭印象）
> 规格基准：`openspec/changes/phase2-harness/specs/frontend-ui.md`
> 方法：浏览器实测渲染 + 逐文件比对（只读，本轮未改任何代码）

---

## 0. 一句话结论

用户意图（**点 Kanban → 右侧出四个看板 → 点 tab 出内容**）**功能链路已达成**；
但"照抄 hermes"只抄了**骨架**（grid + 4 tab + 输入框），**没搬 hermes 的"设计系统"**（组件 CSS / 手写 SVG 图表 / 图标 / 字体 / 状态栏）——这正是"特别丑"的根因，而非看板栏本身的问题。

---

## 1. 背景与诉求

| 项 | 内容 |
|---|---|
| 原诉求 | 在 hermes-agent 的 UI 上加入看板栏，**四个**：舆情、市场、配置、口碑 |
| 交互意图 | 点击 Kanban → 右侧出现这四个看板；点 tab 切换内容 |
| 视觉基准 | **基本照抄 hermes**，但按项目实际裁剪（如 hermes 的"机器人"功能本项目不存在，去掉） |
| 反馈 | 结果"特别丑" |

---

## 2. 已锁定决策（本轮拍板）

| # | 决策 | 说明 / 影响 |
|---|---|---|
| 1 | **模式切换保持"侧栏切换"** | 不做顶部模式切换条。**与 spec §1.4"顶部模式切换"冲突 → 以本决定为准，spec 该条需改注** |
| 2 | **整份搬 hermes 设计系统** | 组件 CSS + 手写 SVG 图表 + 图标 sprite + 状态栏，再按项目裁剪 |
| 3 | **保留"配置" Tab** | 标签维持 **"车型配置"**（与 spec §1.2 图一致），避免与"系统配置"混淆 |

---

## 3. "配置 Tab"澄清（本轮讨论重点）

### 3.1 它是什么
= 棱镜三维度里的 **"配置 = 产品力"** 那一维 = **车型配置**（座椅材质 / 侧窗隔音玻璃 / 轮胎规格 / CLTC 续航 / 智驾 / 车机芯片）。

### 3.2 与 hermes 的"配置"不是一回事

| | hermes 参照稿的"配置" | Prism 的"配置" |
|---|---|---|
| 实质 | **看板设置 / 系统配置**（数据源连接开关、监测关键词、刷新预警、Agent 行为） | **棱镜维度：车型配置 / 产品力** |
| 归属 | 产品设置页 | 业务分析维度 |

Prism 已按 spec §1.3 把"系统配置"挪到**左侧齿轮"设置"页**，看板栏第 3 格腾给"车型配置"。

### 3.3 为什么它必须存在（沿用三角模型）
```
配置 = 产品力（厂商投了什么、改了什么）
口碑 = 需求验证（用户感知成什么、痛点在哪）
销量 = 市场结果（市场买不买账）
舆情 = 外挂第四组（仅与销量双向交叉，不进三维主轴）
```
4 格 = **3 个棱镜维度 + 1 个外挂**。配置 Tab 的理由是"**棱镜不能缺一条边**"——没有配置就无法做"配置→口碑→销量"的因果倒推（E5 案例：配置侧仿皮/无隔音玻璃 ↔ 口碑侧舒适吐槽 ↔ 销量侧下滑，三者交叉才有诊断意义）。

**存在依据（两条）**：
1. 是**用户自己定的**——原话"加上看板栏（有四个，分别是舆情、市场、配置、口碑）"。
2. hermes 原稿本就有这 4 格，只是其"配置"=看板设置，被 Prism 换成"车型配置"。

### 3.4 该 Tab 应有的内容（spec §2.3，目前实现不全）
- KPI 3：在售版型数 / 配置快照版本 / 年款分布
- **横排版型对比表**：12 个 spec_id × 关键配置项（**现实现为竖排 EAV，需改横排**）
- 赋分展示卡（A1/B1 赋分）
- "非车系级缺失"提示 badge

---

## 4. 意图达成度：✅ 功能链路已通

- 点侧栏 Kanban → 右区渲染 `KanbanView`（`src/App.tsx`）
- 看板栏四 tab 顺序 `舆情 | 市场 ‖ 车型配置 | 口碑`，与 hermes 稿完全一致（含分隔线位置）
- 浏览器实测：四个 tab 点击均能切换出内容，无空白/报错

---

## 5. 问题清单：与 hermes 参照稿的结构差异（8 条）

以 `UI设计/hermes-agent-kanban.html` 逐块比对：

| # | hermes 有 | 当前实现 | 严重度 |
|---|---|---|---|
| 1 | **~200 行组件 CSS**（table/chart/hbars/list/card/kpi/btn/switch/select/empty + 全部 hover/focus/transition） | `src/styles.css` 仅 59 行，只有色板变量 + body，**零组件样式** | **致命** |
| 2 | **6 处图表**（声量趋势 / 关键词热度 / 口碑趋势 + 4 组 hbars） | 四个看板 **0 个图表** | 大 |
| 3 | 4 个 list（议题/预警/竞品/评价，带 tag + 热度条）+ `.empty` 空态 | 无 list、无 tag、无空态 | 大 |
| 4 | **状态栏**（网关/模型/GPU/版本） | **完全没有**（App 布局注释里本有 statusbar，未实现） | 大 |
| 5 | 侧栏每项带 **SVG 图标 + kbd 角标**，含顶部收起/更多、底部图标按钮、真实会话列表 | 纯文字、零图标、写死占位 | 大 |
| 6 | board-bar 右侧（数据源 chip / 更新于 / 刷新）+ 左侧"看板"**带图标** | 右侧全空，"看板"无图标 | 中 |
| 7 | composer：附件 + 模型 pill + 推理 pill + 语音 + 圆形发送图标 | 只有输入框 + 矩形"发送" | 中 |
| 8 | config 看板整套控制组件（switch/range/select/chips） | 无（系统配置已挪走，但车型配置看板也缺其应有组件） | 中 |

---

## 6. 与 spec `frontend-ui.md` §七验收的差距

| spec 验收项 | 现状 | 判定 |
|---|---|---|
| 1 brand-spec 色彩/字体/视觉规则落地 | 色板✓；但 **Bodoni Moda 未加载**（hermes 引了 Google Fonts，React 没有）→ kicker 回退宋体；图标规则未落地 | 部分 |
| 2 三栏布局与 HTML 稿视觉一致 | 缺状态栏 / 图表 / 图标，表格无样式 | ✗ |
| 3 四看板字段对齐实际数据 | 见 §6.1 | ✗ |
| 4 顶部模式切换（BI/Agent）可切换 | 实现改为**侧栏切换**，与 spec §1.4 冲突（**决策 1 已拍板保留侧栏**） | ✗（已决） |
| 5 composer **scope 锁定**生效 | 只 `preventDefault()`，不带 scope、不锁工具白名单 | ✗ |
| 6 车系 tab 调 `resolve_series` 刷新看板 | 写死 3 个车系文字，无切换 | ✗ |
| 7 系统配置在齿轮入口 | ✓ | ✓ |

### 6.1 spec 明确要求、但实现缺失的字段
- **口碑（§2.1）**：缺「原文样本卡」「口碑趋势图」「其他桶待拆解 badge」（6 项只做 3 项）
- **市场（§2.2）**：缺「月度销量对比图」「版型结构 hbars」「终端价趋势图」；且现表为"月度零售"，spec 要的是"**竞品对比表**"
- **车型配置（§2.3）**：缺「赋分展示卡」「非车系级缺失 badge」；表为**竖排 EAV**，spec 要**横排 12 spec_id × 配置项**

---

## 7. 上一轮问题复核（含两处自我更正）

| 上轮问题 | 现状 |
|---|---|
| 表格零样式 / `.num` 未定义 | **未修**（实测 padding 0、无边框、数字未右对齐） |
| Bodoni 字体未加载 | **未修** |
| KPI 硬编码（ReviewsBoard / MarketBoard） | **未修** |
| 死按钮 / 占位文案 | **未修** |
| ~~分隔线间距错~~ | **更正：hermes 原样就是 `margin:0 5px`，实现忠实照抄，上轮判错** |
| ~~看板栏宽度不均~~ | **部分更正**：根因是 hermes 用"配置"(2字)、实现用"车型配置"(4字)；而 spec §1.2 图写的就是"车型配置" —— **是参照稿与 spec 本身不一致，实现没错** |

---

## 8. 浏览器实测新发现

- `/dashboard/reviews?series_key=银河E5` 返回 **`net::ERR_ABORTED`**（后端 8002 未起/代理异常）→ 口碑表数据拉不到
- 舆情 tab 的 `127.0.0.1:8000` **iframe 在 DOM 中未找到** → 显示为空白
- **全站无任何 hover / focus 态**（hermes 处处有 transition）→ 交互"死"
- 看板栏按钮实测：高 34px、`padding 0 16px`、`border-radius 999px`、未激活透明 / 激活蓝底
- 表格实测：`th/td` padding 0、border 0、`text-align` center/start、字号 12.5px；正文 PingFang SC / Microsoft YaHei

---

## 9. 根因定性

当前实现 = **只搭了骨架**（grid + 4 tab + 输入框），**没搬 hermes 的设计系统**——图标、图表、组件 CSS、字体、状态栏**五样一样没来**。
hermes 稿的好看来自其**组件 CSS 库 + 手写 SVG 图表**，这两样正是缺失项。

---

## 10. 开工顺序（已确认方向，待执行）

| 步 | 内容 | 主要产出 |
|---|---|---|
| 1 | **设计系统底座**：搬 hermes 的 CSS 变量 + 组件 CSS（table/chart/hbars/list/card/kpi/btn/switch/select/empty + hover/focus/transition）到 `src/styles.css`；**加载 Bodoni Moda**；补**图标 sprite** | 表格/字体立即不丑 |
| 2 | 侧栏升级：导航项补图标 + kbd、真实会话/车系列表、foot 图标 | 侧栏不再裸 |
| 3 | board-bar 补右半（数据源 chip / 更新于 / 刷新） | 栏平衡 |
| 4 | 四看板按 spec §2.x 补**手写 SVG 图表 + hbars + list + empty 空态**（口碑 3 图、市场 3 图、配置赋分卡 + 横排表） | 内容不再单调 |
| 5 | composer 补齐（附件 / 模型 pill / 推理 pill / 圆形发送）+ **scope 锁定** | 交互完整 |
| 6 | 补**状态栏**（数据源就绪 / 当前模型 / token / 三维度完成度 + as_of） | PM 性落点 |
| 7 | 清硬编码 KPI → 接口取数；修 `/dashboard/reviews` **ERR_ABORTED** | 数据可信 |

> 注意：第 1 步会**大幅新增/改写 `src/styles.css`**（新增整套组件样式）。

---

## 11. 关键文件索引

| 用途 | 路径 |
|---|---|
| hermes 参照稿（实体） | `UI设计/hermes-agent-kanban.html` |
| UI 规格 | `openspec/changes/phase2-harness/specs/frontend-ui.md` |
| 布局与模式切换 | `prism-web/src/App.tsx` |
| 侧栏 | `prism-web/src/components/Sidebar.tsx` |
| 看板栏 + composer | `prism-web/src/components/KanbanView.tsx` |
| 四看板 | `prism-web/src/components/dashboards/{ReviewsBoard,MarketBoard,ConfigBoard,SentimentBoard}.tsx` |
| 全局样式 | `prism-web/src/styles.css` |
| 入口 HTML（字体缺失点） | `prism-web/index.html` |

---

## 12. 待决 / 后续

1. spec §1.4"顶部模式切换"与决策 1 冲突 → **spec 需改注**（保持侧栏切换）。
2. spec §1.2 标签"车型配置" vs hermes"配置" → 已定用"**车型配置**"。
3. 侧栏第二 tab 保留"**车系**"（替代 hermes 的"机器人"，spec §4.1 要求）。
4. 第 4 步图表需**手写 SVG**（与设计稿一致），不引第三方图表库。

---

# 二轮复审（迁移后）· 2026-10-04

> 触发：用户反馈"改造后还是很怪，你再看看"（重复不满信号，须重新取证而非沿用上轮结论）
> 方法：浏览器实测（计算样式 / 网络 / 控制台取证）+ 逐文件比对 + 与 hermes 参照稿并排对比页
> 状态：诊断完成，**未改任何业务代码**；修复范围待用户拍板

## 13. 本轮讨论与决策

| # | 事项 | 结论 |
|---|---|---|
| 1 | 用户反馈 | "改造后还是很怪"——重复不满，需重新取证 |
| 2 | 取证目标 | 判定"怪"来自**半迁移**还是**照抄本身与 Prism 信息架构不匹配** |
| 3 | 交付对比工具 | 生成并排对比页 `UI设计/compare.html`（左 hermes / 右当前实现，两侧可交互、可切内层视口宽度），用 python 静态服务托管于 8899 端口 |
| 4 | 用户选择 | **"先给我看对比图再定"**——暂不动代码 |
| 5 | 修复范围（三档，**待决**） | ① P0 只修响应式+页头；② P0+P1 再还原底部并补舆情 tab；③ 全含数据取数 |

## 14. 迁移已完成项（本轮确认到位）

- 组件 CSS：table / list / tag / hbars / empty / btn / chart / kpi / badge / pill / send 等（`styles.css` 已 198 行）
- 手写 SVG 图表：`AreaChart` / `BarChart` / `HBars`（`_shared.tsx`）
- 图标 sprite：`Icons.tsx`（19 个 symbol）
- 状态栏 `StatusBar`、composer 结构、board-bar 右半（数据源 chip / 更新于 / 刷新）
- Bodoni Moda 已在 `index.html` 引入
- 四 tab 切换正常；`/dashboard/reviews|sales|config` 三个接口均返回 200

## 15. 上一轮 4 条结构 gap 的现状

| # | 上一轮问题 | 现状 |
|---|---|---|
| 1 | 全站无 `@media` 响应式 | **仍未修**（确认为"怪"的主因，见 §16.1） |
| 2 | 看板页头右半边（`.head-ctrl`/车系选择器）缺失 | **仍未修**（实测 `.head-ctrl`=0、`.select-wrap`=0） |
| 3 | 底部 composer/statusbar 未照 hermes 还原 | **仍未修**（见 §16.3） |
| 4 | 舆情 tab 空壳 | **仍未修**（实测 `iframe`=0、`svg.chart`=0） |

## 16. 本轮新增问题

### 16.1 响应式缺失（致命）
- `prism-web/src` 全目录 grep `@media` = **0 命中**；hermes 参照稿同一套 CSS 带 3 组断点：
  - `@media (max-width:1180px){.main-grid,.config-grid{grid-template-columns:minmax(0,1fr)}}`
  - `@media (max-width:900px){.app{grid-template-columns:minmax(0,1fr)} .sidebar{display:none} .kpi-grid{…} …}`
- 实测后果：`svg.chart`（viewBox 720×190）被压成 **167×44px**；并排对比页切到 1180/860 时，hermes 双栏塌单栏、侧栏隐藏，当前实现毫无变化。

### 16.2 对话视图布局塌陷（实测真 bug）
- 实测：`.main` 高 687px，ChatView 内容区仅 **257px**，下方大片空白。
- 根因：`App.tsx` 的 `.main{grid-template-rows:auto minmax(0,1fr) auto auto}` 四行专为 KanbanView 设计；ChatView 只返回**单个**子元素且用 `flex:1`（在 grid 内无效）→ 落 auto 行塌陷。

### 16.3 底部未照 hermes 还原
- hermes：`.composer` 为**整体圆角软容器**（border + radius14 + shadow + focus-within，max-width 980，padding 6/8），`.pill` 无边框透明、`.send` 32px 黑底、`.statusbar` 无边框无底色。
- 当前：带框输入 + 一圈白底带边框 pill + 38px 蓝底圆钮；`.composer-row`/`.statusbar` 各加 `border-top` + 底色 → 底部偏厚偏花。

### 16.4 字体依赖（国内环境风险）
- 实测 `fonts.googleapis.com` 的 Bodoni Moda 请求 **duration 2640ms、responseStatus=0（失败/超时）** → `.kicker` 退化宋体。
- 建议自托管或换镜像源（用户规则：下载用清华/阿里镜像）。

### 16.5 数据真实性（触 AGENTS.md 红线 1）
- `ReviewsBoard`：`1274 / 3235 / 92.5%` 写死
- `MarketBoard`：`-42.9%` 写死；竞品对比表 4 行疑似写死
- `ConfigBoard`：赋分卡 `55000 / 2200 / 仅最低配无` 写死
- `SentimentBoard`：KPI 全 `—`；`StatusBar` 的 `as_of` 写死

### 16.6 车型配置表少 2 个版型（硬编码 vs 真实数据不一致）
- 接口实测返回 **12 个 distinct spec_id**：`73702, 73943, 73944, 73945, 73949, 73952, 78132, 79266, 79310, 79311, 79312, 79313`
- `ConfigBoard.tsx` 的 `SPECS` 只硬编码 10 个，**漏 73943、73944**；同页 KPI 却写"版型数 12" → 自相矛盾。

### 16.7 死交互 / 占位（实测）
- `bar-meta` = `更新于 --:--` 永不更新；刷新按钮无 handler
- `statusbar` = `配置☐ 口碑☐ 销量☐` + `as_of: 2026-10-04` 写死
- 侧栏：`设置`、`产物` 死按钮；`Ctrl N` 无快捷键；会话/车系列表写死；搜索框无功能；车系 tab 未接 `resolve_series`（spec §6.6）
- **无 `Settings` 组件** → spec「系统配置在齿轮入口」**实际未实现**（上轮判 ✓ 有误，本轮更正）

### 16.8 细节一致性
- 无障碍：`.seg-btn` 有 `aria-selected` 却缺 `role="tab"`；`.board` 缺 `role="tabpanel"`
- `Icons.tsx` 首帧返回 `null`（`useEffect` 注入 sprite）→ 图标闪一帧
- `index.html` 声明 `color-scheme light dark` 但无暗色样式

## 17. 已复查排除（防误报）
- 后端中文乱码：字节实为 UTF-8（`E9 93 B6…` = 银河），仅 PowerShell 显示问题 → **排除**
- 分隔线间距、看板栏宽度不均：上轮已更正为 hermes 原样 → **排除**

## 18. 完整问题清单（两轮汇总）

| # | 问题 | 严重度 | 状态 |
|---|---|---|---|
| 1 | 全站无响应式 `@media` | 致命 | 未修 |
| 2 | 对话视图布局塌陷 | 高 | 本轮新发现 |
| 3 | 舆情 tab 空壳（无内容 / 无 iframe） | 高 | 未修 |
| 4 | 车型配置表少 2 版型（硬编码） | 高 | 本轮新发现 |
| 5 | 无 Settings 组件 / 设置入口死链 | 高 | 本轮新发现 |
| 6 | 看板页头右半边空（无车系选择器） | 中 | 未修 |
| 7 | 底部 composer/statusbar 未照 hermes | 中 | 未修 |
| 8 | 字体 CDN 国内不可达 | 中 | 本轮新发现 |
| 9 | KPI / 数字硬编码（红线 1） | 中 | 未修 |
| 10 | 死交互 / 占位（更新于、刷新、Ctrl N…） | 中 | 本轮新发现 |
| 11 | a11y role 缺失 / 图标闪帧 / color-scheme | 低 | 本轮新发现 |

## 19. 对比工具使用说明
- 页面：`UI设计/compare.html`
- 托管：在 `UI设计` 目录执行 `python -m http.server 8899 --bind 127.0.0.1`（本轮已启动；进程随会话结束会停止，需重启）
- 访问：http://127.0.0.1:8899/compare.html
- 功能：左右分别嵌 hermes 参照稿与 localhost:5173，两侧均可交互；顶部可切内层视口 1440 / 1180 / 860 / 760，用于直观看响应式差异。

## 20. 待决 / 下一步
1. 修复范围三档（P0 / P0+P1 / 全含数据）——**用户尚未拍板**
2. 字体改自托管 / 镜像源（需选源）
3. 舆情 tab 落地方式（开发期 iframe 嵌 127.0.0.1:8000，还是先按 hermes 结构自绘）
4. spec §1.4、§1.2 改注（沿用上轮 §12）