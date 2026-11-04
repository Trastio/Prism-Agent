# Prism-Agent · "他是谁"根因 + UI 改造需求清单（对标 HERMES）

> 审查日期：2026-10-05
> 审查根目录：`c:\Users\<you>\Desktop\Prism-Agent`
> 触发：① 前端提问「他是谁」却回出「当前会话上下文：对象：银河E5…」，用户判定不合理；② 前端 UI 需对标 HERMES（新建会话大字、左侧栏实装、SKILLS 库、会话重命名、删顶部元素、图表须有真实数据源、卢浮宫抽象成 logo）
> 性质：**只读审查，未改动任何代码**；本文为需求/根因分析，不含实现
>
> **文档关系**：本文为**子报告**，其全部要点已并入主报告《[Prism-Agent-PM推理能力与Harness成熟度评估-2026-10-05.md](file:///c:/Users/<you>/Desktop/Prism-Agent/文档/Prism-Agent-PM推理能力与Harness成熟度评估-2026-10-05.md)》§3；**优先级一律以主报告 §5 统一收敛清单为准**，本文 §6 已对齐。

---

## 0. 结论摘要（TL;DR）

| 议题 | 结论 |
|---|---|
| 「他是谁」为何答非所问 | **根因确证**：`SYSTEM.md` 的「当前会话上下文」块被**每轮无条件注入**，且变量全部**硬编码**为「银河E5/7650/as_of=今天/无」。模型把这段后台元数据**当正文复述**出来 |
| 侧栏「产物/设置」 | **空壳按钮**（无 onClick、无对应视图），确为不合理 |
| SKILLS 库 | **完全缺失**（前端无入口；后端也没有 skills 清单接口） |
| 会话重命名 | 后端**有** `set_session_name`（仅建会话时可传 title），但**前端无 UI**，且列表接口**不用自定义名**（用文件名），改了也不显示 |
| 图表数据 | **半数面板是硬编码「示例数据」**（销量·版型结构/竞品对比、口碑·原文样本/趋势、配置·赋分展示、顶部 as_of 2026-10-04、对象银河E5 全部写死） |
| 顶部元素 | 银河E5 对象 chip / 搜索车系 cmdk / 日夜切换 **均为无功能死元素**，可整体删除 |

---

## 1. 「他是谁」根因分析（P0 · 证据链完整）

### 1.1 机制

`before_agent_start` 钩子在**每一轮**把 `AGENTS.md`（PM 长 SOP）+ `SYSTEM.md`（角色约束）拼到 systemPrompt 末尾：

- 位置：[.pi/extensions/prism-guardrails/index.ts L377-L395](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L377-L395)
- 填充逻辑（**硬编码**）：

```ts
const filled = systemMd
  .replace('{series_key}', '银河E5')      // ← 写死
  .replace('{series_id}', '7650')         // ← 写死
  .replace('{mode}', '对话模式')
  .replace('{as_of}', new Date().toISOString().slice(0, 10))
  .replace('{warnings}', '无');
prompt += '\n\n' + filled;
```

- `SYSTEM.md` 对应块（[SYSTEM.md L23-L28](file:///c:/Users/<you>/Desktop/Prism-Agent/SYSTEM.md#L23-L28)）：

```
## 当前会话上下文
- **对象**: {series_key}（series_id={series_id}）
- **模式**: {mode}（对话模式 / 看板模式）
- **as_of**: {as_of}
- **数据缺口**: {warnings}
```

### 1.2 为什么会"复述"出来

三个叠加因素：

1. **无条件注入**：不论用户问"他是谁"还是"银河E5销量"，都塞同一段"对象=银河E5"。纯闲聊也被强绑到银河E5 上下文。
2. **没有"元数据禁止复述"指令**：该块以普通 Markdown 正文形态出现在 system prompt 里，模型无法区分"这是给我的后台参数"还是"这是要输出的内容"，于是照抄。
3. **PM 长 SOP 加重**：同一钩子还追加了 `AGENTS.md`（棱镜三维度 + 报告纪律六条 + CLAIM 结构），强化了"必须声明上下文/口径"的行为倾向。

> **旁证**：同批会话日志（[14-59-42Z 会话](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/sessions/usr_g5r6h5ye)）显示"你好，你是谁"时模型 thinking 明确在按 SYSTEM.md 定位自己为 Prism-Agent，说明 SYSTEM.md 已被读到；"当前会话上下文"随之被复述。

### 1.3 与"角色/模式"缺陷同源

同一钩子是**唯一的上下文/角色入口**，因此同时承担了本应拆开的 4 件事——对象身份、模式、as_of、角色分流，且**全用常量**。修「他是谁」不能只改文案，要一并解决：

- 上下文**动态化**：对象由会话真实目标（`resolve_series` / 前端所选）决定，而非常量 `银河E5`；
- **条件注入**：无对象语境（纯闲聊）时不注入该块；
- **元数据隔离**：显式声明"以下为后台元数据，仅在相关时引用，禁止整段复述"；
- **角色分流**：PM 走棱镜 SOP，普通用户走轻量助手提示词。

---

## 2. 前端 UI 深审（对标 HERMES）

参考资源（仓库已有）：[hermes-agent-kanban.html](file:///c:/Users/<you>/Desktop/Prism-Agent/UI设计/hermes-agent-kanban.html)、[brand-spec.md](file:///c:/Users/<you>/Desktop/Prism-Agent/UI设计/brand-spec.md)（含 oklch 色板、Didone 字体栈、对比度实测）。

### 2.1 需求逐条映射（用户反馈 → 现状 → 缺口）

| # | 用户诉求 | 现状（文件·行） | 缺口 |
|---|---|---|---|
| U1 | 新建会话界面复刻 HERMES「大字」效果 | 空会话态即 [ChatView.tsx](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/ChatView.tsx)，无 hero 空白态 | 缺：Didone 衬线大字 hero（brand-spec 已定义 `Bodoni Moda/Didot`）+ 引导语/示例问 |
| U2 | 左侧栏「产物」空白不合理 | [Sidebar.tsx L42](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L42) 无 onClick、无视图 | 需实装「产物」视图（分析报告/结论/导出物）或先移除 |
| U3 | 左侧栏「设置」空白不合理 | [Sidebar.tsx L43](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L43) 无 onClick、无视图 | 需实装设置页（模型/权限/偏好）或先移除 |
| U4 | 左侧栏加「SKILLS 库」，点击展开 | **无任何入口** | 需新增：侧栏项 + 展开面板 + **后端 skills 清单接口**（当前无） |
| U5 | 会话可自定义名称（像 HERMES） | [Sidebar.tsx L63-L67](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L63-L67) 仅展示，无重命名 | 需：行内重命名 UI + 后端 rename 接口（见 §5） |
| U6 | 删顶部：银河E5 / 搜索车系 / 日夜切换 | [App.tsx L37-L49](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.tsx#L37-L49) 三者皆**无功能**死元素 | 直接删除；对象选择改由 §U7/会话管理承担 |
| U7 | 图表必须有对应数据 | 见 §3 对照表，**半数硬编码** | 每个图表须绑定真实接口或显式标注"演示" |
| U8 | 卢浮宫抽象成 logo | [App.tsx L35](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.tsx#L35) 现为 `<span className="prism-dot">` 圆点 | 见 §4 设计方向 |

### 2.2 侧栏其余问题（同批审查发现）

- **会话点击无跳转**：`sb-row`（[L63-L67](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L63-L67)）无 onClick → 列出来的会话**打不开**。
- **「新建会话」不新建**：`onClick={() => onNavigate('chat')}`（[L36-L38](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L36-L38)）**只切视图**，未调 `POST /session`（后端其实支持，见 §5）。
- **「已置顶」永远为空**：`<ul className="sb-list" />`（[L56](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L56)）无数据源。
- **「车系」Tab 是假列表**：银河E5/零跑D19/铂智7X 硬编码（[L76-L78](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L76-L78)）。
- **会话名取文件名**：`{s.name || s.id.slice(0,12)}`（[L66](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L66)），而后端列表返回的 `name` 就是文件名（见 §5），因此**即使重命名也不会显示**。

### 2.3 视图切换的隐藏问题

- `KanbanView` 内用 `useState<Board>` 切换 5 个看板（[KanbanView.tsx L14-L45](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.tsx#L14-L45)），**每次切换重新挂载** → 已取数据的缓存靠 react-query 顶着，但滚动位置/局部状态丢失。
- 主区 `view==='kanban'?…:…`（[App.tsx L60-L75](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.tsx#L60-L75)）切换看板↔对话**卸载另一个**，对话内存态丢失。

---

## 3. 图表数据真实性对照表（U7 核心）

> 判据：是否 `fetch` 真实接口 vs 硬编码常量数组。

| 视图 · 面板 | 数据来源 | 真实/假 | 证据 |
|---|---|---|---|
| 舆情（Board 外挂） | iframe 反代 `:8000` | **真实** | [SentimentBoard.tsx](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/SentimentBoard.tsx) |
| 销量 · 月度走势 | `GET /dashboard/sales` | **真实** | [MarketBoard.tsx L11](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/MarketBoard.tsx#L11) |
| 销量 · 版型结构 | 硬编码 `2047/1854/…` | **假（示例数据）** | [MarketBoard.tsx L43-L51](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/MarketBoard.tsx#L43-L51) |
| 销量 · 竞品对比 | 硬编码 理想L6/零跑D19/问界M7/岚图Free | **假（示例数据）** | [MarketBoard.tsx L54-L66](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/MarketBoard.tsx#L54-L66) |
| 车型配置 · 配置矩阵 | `GET /dashboard/config` | **真实** | [ConfigBoard.tsx L13](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ConfigBoard.tsx#L13) |
| 车型配置 · 赋分展示 | 硬编码 `55000元/2200元` | **假（示例数据）** | [ConfigBoard.tsx L69-L74](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ConfigBoard.tsx#L69-L74) |
| 口碑 · 维度聚合 | `GET /dashboard/reviews` | **真实** | [ReviewsBoard.tsx L15](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ReviewsBoard.tsx#L15) |
| 口碑 · 原文样本 | 硬编码 review_id | **假（示例数据）** | [ReviewsBoard.tsx L71](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ReviewsBoard.tsx#L71) |
| 口碑 · 趋势 | 硬编码 `[28,35,30,…]` | **假（示例数据）** | [ReviewsBoard.tsx L79](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/dashboards/ReviewsBoard.tsx#L79) |
| 棱镜结论 · 三链卡片 | 数字真实 fetch，**结论文案硬编码** | **半真** | [KanbanView.tsx L99/L105/L111](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.tsx#L99-L111) |
| 棱镜结论 · CLAIM | 硬编码文案 + **假 supported_by 行号**（`review_tags#7650… config#79311…`） | **假** | [KanbanView.tsx L115-L131](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.tsx#L115-L131) |
| 看板栏 · as_of | 硬编码 `2026-10-04` | **假** | [KanbanView.tsx L32](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.tsx#L32) |
| 全局 · 分析对象 | 硬编码 `'银河E5'`（4 处） | **假** | [App.tsx L19](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.tsx#L19)、KanbanView L54/L61/L68 等 |

**结论**：`示例数据` 仅靠一个灰色小 chip 标注，与真实数据**并排同款渲染**，汽车 PM 极易误读——与全局红线#1（数据真实性）冲突。

---

## 4. Logo：卢浮宫抽象方向（设计指引，非实现）

- **意象**：贝聿铭玻璃金字塔（三角棱面 / 折射）——与品牌名 **Prism**（棱镜）天然同源：三角棱面 = 光的折射 = 棱镜。
- **抽象建议**：
  - 取**正三角**为骨架，内部 2–3 条棱线切成多面（金字塔的玻璃格），交点汇聚于顶点，形成"折射"暗示；
  - 单色 `--accent`（`#0053FC`）描边，**1.7px 线宽、currentColor、无填充**，与 [brand-spec.md](file:///c:/Users/<you>/Desktop/Prism-Agent/UI设计/brand-spec.md) 视觉规则第 4 条一致；
  - 极小尺寸（16–20px）时降为**实心单三角**保证可识别；可与 `P` 字负形结合做 monogram；
  - 主蓝每屏配额（brand-spec 规则 2）下，logo 作为品牌位不计入"图表填充"。
- **替换点**：现 [App.tsx L35](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.tsx#L35) 的 `<span className="prism-dot">`、看板栏 `<Icon name="atom">`（[KanbanView.tsx L21](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/KanbanView.tsx#L21)）若都换成该 logo，可统一品牌。

---

## 5. 后端需配套的接口（UI 需求的前置依赖）

| UI 需求 | 后端现状 | 需要补 |
|---|---|---|
| 新建会话 | ✅ `POST /session` 支持 `new_session` + `title`（[main.py L185-L190](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L185-L190)、[pi_gateway.mjs L385-L407](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L385-L407)） | 前端接上即可（当前未调用） |
| 会话重命名 | ⚠️ 仅建会话时可传 `title`（走 `set_session_name`） | 补 **rename 接口**（对已有会话）；且 **list 必须返回自定义名**（当前 list 的 `name` = 文件名，[pi_gateway.mjs L373](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L373)） |
| SKILLS 库 | ❌ 无任何接口 | 新增 `GET /skills`（返回 prism 业务工具/能力清单：名称/说明/所属维度/启用状态） |
| 产物 | ❌ 无接口/无存储 | 需定义"产物"数据模型（结论/报告/导出）与 `GET /artifacts` |
| 图表版型结构 | ✅ `/dashboard/sales?group_by=spec` 已可用（[main.py L88-L102](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L88-L102)） | 前端接上即可（当前用硬编码） |
| 竞品对比 | ❌ 未见接口 | 需 `get_competitors` 类接口或复用 search_cars |
| 口碑原文/趋势 | ⚠️ reviews 接口有聚合 | 需补"原文样本 + 时间趋势"字段 |
| 顶部对象/主题 | — | 删除即可，无需后端 |

---

## 6. 收敛清单（已对齐主报告）

> 本节优先级**已与主报告《Prism-Agent-PM推理能力与Harness成熟度评估-2026-10-05.md》§5 统一收敛清单对齐**，两者不得冲突；如遇不一致，以主报告为准。

| 优先级 | 本报告相关项 | 对应主报告条目 |
|---|---|---|
| **P0** | 上下文注入去硬编码/条件化（§1.3）；删顶部三个死元素 + 侧栏空壳处置（U2/U3/U6）；图表接真数据/演示态隔离（§3） | 主报告 §5 第 3 / 4 / 5 条 |
| **P1** | SKILLS 库 + `GET /skills`（U4）；会话重命名 + 点击可打开（U5） | 主报告 §5 第 13 / 14 条 |
| **P2** | 新建会话 hero 大字态（U1）；Logo 卢浮宫抽象（U8）；视图切换保活；「产物」视图数据模型 | 主报告 §5 第 17 / 18 / 19 / 20 条 |

---

## 附录 A · 证据索引

| 编号 | 证据 | 位置 |
|---|---|---|
| A1 | SYSTEM.md「当前会话上下文」块 | [SYSTEM.md L23-L28](file:///c:/Users/<you>/Desktop/Prism-Agent/SYSTEM.md#L23-L28) |
| A2 | 变量硬编码 + 每轮注入 | [index.ts L377-L395](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/extensions/prism-guardrails/index.ts#L377-L395) |
| A3 | 同源角色/模式缺陷（同钩子、无分流） | 同上 L377-L395 |
| A4 | 侧栏空壳项/假列表/无重命名 | [Sidebar.tsx L36-L88](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/components/Sidebar.tsx#L36-L88) |
| A5 | 顶部死元素 | [App.tsx L33-L50](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-web/src/App.tsx#L33-L50) |
| A6 | 硬编码"示例数据"面板 | MarketBoard L43/L54 · ConfigBoard L69 · ReviewsBoard L71/L79 · KanbanView L32/L99-L131 |
| A7 | 后端已有 new/rename 能力（list 不用自定义名） | [main.py L185-L190](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/main.py#L185-L190)、[pi_gateway.mjs L373/L385-L407](file:///c:/Users/<you>/Desktop/Prism-Agent/prism-api/pi_gateway.mjs#L373-L407) |
| A8 | HERMES 参考与品牌契约 | [hermes-agent-kanban.html](file:///c:/Users/<you>/Desktop/Prism-Agent/UI设计/hermes-agent-kanban.html)、[brand-spec.md](file:///c:/Users/<you>/Desktop/Prism-Agent/UI设计/brand-spec.md) |
| A9 | 会话日志（含"你是谁"轨迹） | [.pi/sessions/usr_g5r6h5ye](file:///c:/Users/<you>/Desktop/Prism-Agent/.pi/sessions/usr_g5r6h5ye) |