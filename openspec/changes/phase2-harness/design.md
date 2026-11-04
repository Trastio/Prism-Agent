# Design · 阶段2 核心Harness与语义工具

> Prism-Agent 开发流程 · Step 2 propose · 技术方案
> 日期：2026-10-03（2026-10-04 扩三大支柱）
> 上游：proposal.md（决策已拍板）+ explore.md（现状/缺口/依赖）

---

## 0. 架构总览（三大支柱）

```
支柱三：前端 + pi 集成（Web 站可交互）
┌─────────────────────────────────────────────────┐
│ 浏览器 (React 19 + shadcn + assistant-ui)        │
│  ├─ BI 看板模式（HTML 稿布局：看板+底部composer）   │
│  └─ Agent 对话模式（全屏对话+右侧报告预览）         │
└──────────────────┬──────────────────────────────┘
                   │ SSE / REST / WS
┌──────────────────▼──────────────────────────────┐
│ FastAPI 网关 (prism-api/)                        │
│  ├─ /chat/stream (SSE) ─→ pi SDK createAgentSession
│  ├─ /dashboard/{type} ─→ mv_* 口径视图           │
│  ├─ /session ─→ Redis 会话                       │
│  └─ /ws/status ─→ 状态栏推送                     │
└──────────────────┬──────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────┐
│ pi-agent SDK                                      │
│  ├─ 2.2.3 3 工具 + discover_tools                 │
│  ├─ 2.2.4 tool_call 护栏 (cc-safety-net + 红线)   │
│  ├─ 2.2.5 tool_result grounding (数值+名称)        │
│  ├─ 2.3.2 完成验证器 (agent_settled)              │
│  ├─ 2.1.1 AGENTS.md/SYSTEM.md (before_agent_start)│
│  ├─ 2.1.2 状态栏 hook → WS 推前端                 │
│  └─ langfuse 埋点                                │
└──────────────────┬──────────────────────────────┘
                   │
     ┌─────────────┼─────────────┐
     ▼             ▼             ▼
 Atuohome SQLite  舆情 Board    Redis
 (immutable=1)    21 GET         (会话)
```

**三大支柱依赖链**：
- 支柱一（后端红线）→ 支柱二（评估闭环，依赖工具+验证器）
- 支柱一（口径视图）→ 支柱三（前端看板读 mv_* + pi 集成注册工具/护栏/验证器）
- 支柱三与支柱二并行（M1 完成后启动）

详见 `specs/pi-integration.md` §1 集成拓扑 + `specs/frontend-ui.md` §1 设计稿采用策略。

---

## 0.1 后端 harness 数据流（支柱一）
  │
  ▼
[2.2 对象身份映射层 + 覆盖率守卫]  ← 新增前置组件
  │  series_alias 查询 + 联网核验(按需) + 覆盖率报告
  ▼
[2.1 提示词层] AGENTS.md(全局SOP锁) + SYSTEM.md(会话快照锁) + 状态栏hook + D3标记
  │  before_agent_start 注入棱镜SOP + 数据缺口假设范式
  ▼
[2.2 工具接口层]
  ├─ 3 核心常驻: query_sales / query_reviews / query_config
  ├─ discover_tools 按需: 能耗/评分/事件/缺陷 + 6 sentiment_*
  ├─ 口径视图(物化视图表 + 运行时聚合 SQL)
  ├─ tool_call 护栏: cc-safety-net + 自建红线拦截(fail-closed)
  └─ tool_result grounding: 数值维度 + 名称维度(新增)
  │
  ▼
[2.3 验证层]
  ├─ grounding.py(接 tool_result hook, 销量/配置数值 + 名称)
  ├─ 完成验证器(agent_settled 事件, CLAIM/VERIFY 汽车场景化)
  ├─ 口碑定性结论: claim 溯源 + 人工抽检
  └─ 真值校验(纯 Python 多重集容差比对)
  │
  ▼
[2.4 评估体系]
  ├─ 评估任务集(30-50题 + 6 trap)
  ├─ 六分制评分器(销量/配置数值容差)
  ├─ 统计栈(McNemar/Wilcoxon/Cliff's delta/bootstrap CI)
  ├─ 批跑(pi -p --mode json, 不禁 langfuse)
  ├─ EVAL_STATUS.md 门禁台账
  ├─ 双评委(GLM/Kimi 异源)
  └─ langfuse 闭环(分数+失败维度+成本写回 trace)

[2.5 前端看板层]（M1 完成后并行启动）
  ├─ Web 项目骨架(Vite + React 19 + shadcn + Tailwind v4 + assistant-ui)
  ├─ 三栏 Shell(左 sidebar / 中对话 / 右预览, 可拖拽分割, 参考 Hermes)
  ├─ Agent 对话区(assistant-ui 流式 + 工具活动 + 状态栏)
  ├─ 右侧 4 看板 tab + 报告预览
  │   ├─ 口碑看板(读 mv_reviews_dim + ECharts)
  │   ├─ 市场看板(读 mv_sales_monthly + ECharts)
  │   ├─ 配置看板(读 mv_config_spec + 对比表)
  │   ├─ 舆情看板(嵌套舆情 Board 21 GET, 上线改自绘)
  │   └─ 报告预览(md/excel/word)
  ├─ 后端 API 网关(FastAPI: chat SSE + dashboard + pi SDK 桥 + Redis 会话)
  └─ 浏览器本地 ID + 会话列表(无登录)
```

---

## 决策⑧⑨⑩⑪：前端形态（2026-10-04 拍板）

- **主视图**：对话为中心 + 看板侧边预览（参考 Hermes 三栏）。聊天是主，看板/报告是聊生的伴随产物在右侧预览。与 2026-09-08"双模式网站"的微调：原 BI 看板模式独立主视图 → 现合并为"对话为主、看板为预览"，因为 Prism 核心价值是产结论不是看图表。
- **运行形态**：Web 站（阿里云部署，无登录，浏览器本地 ID）。非 Electron。
- **技术栈**：React 19 + shadcn/ui(new-york) + Tailwind v4 + assistant-ui + ECharts + Radix + TanStack Query + Vite。与 Hermes renderer 栈一致（去掉 Electron 壳）。
- **四个看板落法**：右侧预览面板的可切换 tab。口碑/市场/配置读 Prism 口径视图（mv_*）；舆情嵌套舆情 Board（开发期 iframe，上线改自绘）。

详见 `specs/frontend.md`。

## 1. 决策①：口径视图落法（物化视图 + 运行时聚合 混合）

### 1.1 问题
- 纯物化视图表：固化口径，失去灵活；但查询快，适合高频。
- 纯运行时 SQL：灵活；但 50-100 并发下 DB 压力大。

### 1.2 方案
**两层混合**：

**层 A：物化视图表（高频固化口径）**——放 Prism 侧（消费者口径资产，不放生产库）：
- `mv_sales_monthly`：`series × year × month × retail_sum`（月末行预聚合，避免每次 `LIKE '%月末'`）
- `mv_reviews_dim`：`model_id × tag_category × sentiment × count`（口碑维度聚合预计算）
- `mv_config_spec`：`series_id × spec_id × 年款 × 关键配置项`（展平嵌套 dict）
- 刷新：销量/口碑每日 cron 刷新（Atuohome 后台更新触发）；配置按 fetched_at 版本刷新

**层 B：运行时聚合 SQL（低频/参数化）**——TS 工具内：
- 跨时段对比（如同比、环比）、版型筛选、竞品池动态构造 → 运行时 SQL
- 走 `sales_trim` 直查，但强制 `month LIKE '%月末'` + `year+month` 分组（修报告① 年份错位 bug）

### 1.3 口径声明机制
每个物化视图表带 `_meta` 表：`as_of / 数据源 / 覆盖率 / 口径说明`。TS 工具返回结果时强制附 `_meta`（消费者侧口径随行声明）。

### 1.4 阶段1 口径坑清单（10 条，全部内化进视图/工具）
1. sentiment=pro/con（非 1/0/-1）
2. 两表品牌命名不一致（sales_trim='银河' vs weighted='吉利'）→ 视图层统一为 `series` 精确匹配
3. `X月中`=价格快照 retail NULL（非缺失）；`X月末`=整月零售 → `mv_sales_monthly` 只取月末
4. 按 year+month 分组（修年份错位）
5. owner_reviews 无 series_id（用 model_id）
6. config categories 嵌套 dict → `mv_config_spec` 展平
7. config 含 2024/2026/2027 三年款 → `mv_config_spec` 标 `年款` 字段
8. sales_trim 只有 24/26 款（2027款只在 config）→ 视图层标注口径来源
9. 版型名末字"版"非"型" → 名称维度 grounding 拦截
10. 打标覆盖率 E5=92.5%/D19=90.8% → 覆盖率守卫报告

---

## 2. 决策②：对象身份映射层 + 覆盖率守卫（新增前置组件）

### 2.1 问题
报告③ v1 把"铂智7X"当"铂智7"查、脑补对齐关系，根因是没前置核验对象身份。

### 2.2 方案
**`resolve_series(user_input) → { series_key, aliases, coverage, needs_online_verify }`**

流程：
1. **库内映射**：查 `series_alias` 表（`series_key / source / raw_name`）。命中 → 返回 `series_key`。
2. **歧义消解**：若多命中（如"7X"匹配多个），返回候选列表 + 各候选覆盖情况，要求用户/agent 澄清。
3. **未命中触发联网**（仅当库内未命中或覆盖率守卫报告缺失）：调 web-access skill 核验（如铂智7X=铂智7同车两名）。
4. **覆盖率守卫**：对解析到的 `series_key`，检查在 `sales_trim / owner_reviews / config_snapshots / series_summaries` 各维的覆盖情况，返回 `coverage_report`：
   - `{ sales: ✅4577行, reviews: ❌0条, config: ✅, summaries: ❌不收录 }`
   - 缺数据维度 → agent 必须在报告里声明缺口（数据缺口假设范式），不得硬分析

### 2.3 落点
- TS 模块 `src/identity/resolve.ts`
- 作为 2.2 工具接口层前置组件，所有 `query_*` 工具调用前先过 `resolve_series`
- 配套 skill：`identity-check`（agent 调用做对象核验）

### 2.4 验收
- 输入"铂智7X" → 映射到 `series='铂智7'` + coverage_report 显示口碑0/summaries不收录 → agent 触发联网核验 + 数据缺口声明
- 输入不存在车系 → fail-closed
- 输入歧义词（"7X"）→ 返回候选 + 要求澄清

---

## 3. 决策③：TS 语义工具 schema + expected_*

### 3.1 工具清单

**3 核心常驻**（每次会话都加载）：
| 工具 | 作用 | 关键参数 |
|---|---|---|
| `query_sales` | 销量/终端价 | series_key, year, month?, group_by?('month'\|'spec'), metric?('retail'\|'tp') |
| `query_reviews` | 口碑维度聚合 + 原文 | model_id, tag_category?, sentiment?, with_samples? |
| `query_config` | 配置项 | series_id, spec_id?, 年款?, key_items? |

**discover_tools 按需包**（棱镜三维度查完才解锁）：
- 能耗 / 评分 / 事件 / 缺陷 / 6 sentiment_*（舆情外挂第四组）

### 3.2 expected_* 自查（教材三重保障之一）
每个工具描述末尾附 `expected_*` 字段，模型调用前自检：
```
query_sales expected:
- retail 来自 month LIKE '%月末' 行（非月中价格快照）
- 必须按 year+month 分组（禁 month 丢年）
- 返回结果带 as_of + 覆盖率
- 名称字段从库源直取，禁止改写
```

### 3.3 名称字段强制库源落地（修报告①②）
- 工具返回的 `model_name / brand / series` 字段**必须直接来自 DB 查询结果**，禁止模型生成或转写
- grounding 名称维度：模型最终回复里的车系/版型/品牌名与工具返回名做精确匹配，不一致即 fail-closed
- 测试集：阶段1 复审的 8 个名称错误（探索型/全域精灵版/铂智7SUV/星纪元ET08/蔚来Z9/智驾版）做拦截测试

### 3.4 schema 用 typebox（pi.registerTool 要求）

---

## 4. 决策④：完成验证器汽车场景化

### 4.1 教材原模式
代码生成场景：`approve_code` 信号 + CLAIM_PATTERNS/VERIFY_PATTERNS。

### 4.2 汽车场景化
`agent_settled` 事件插验收（注意官方名非 `agent_before_settle`）：

**CLAIM 校验**（结论必须有）：
- `conclusion_text`：结论陈述
- `supported_by`：证据行 ID 列表（如 `review_tags:7650/舒适/con`、`sales_trim:银河E5/2026-08/月末`）
- `as_of`：数据时点声明
- `scope`：结论范围（口碑内 / 配置内 / 市场侧不归因）

**VERIFY 校验**（max 1 次 continuation 再不过 fail）：
1. supported_by 行 ID 是否真实存在（查库验）
2. as_of 是否声明且与数据源一致
3. **越界检查**：口碑结论是否越到市场侧归因（报告① v0.2 错误）；市场侧是否归因到产品力（报告③ v0.2 错误）
4. 数据缺口是否声明（如舆情未接入、区域数据不可得）

### 4.3 失败处理
- 1 次失败 → continuation（要求 agent 补证据/降级结论）
- 第 2 次失败 → fail，记录 `EVAL_STATUS.md`

---

## 5. 决策⑤：评估集框架

### 5.1 题量分配（30-50 题）
| 维度 | 题数 | 类型 |
|---|---|---|
| 销量 | 10 | 月度/同比/环比/版型结构/终端价 |
| 配置 | 8 | 版型对比/年款/赋分/缺失项 |
| 口碑 | 10 | 维度聚合/原文溯源/覆盖率 |
| 舆情 | 6 | （数据缺口占位，验范式） |
| 跨维度 | 10 | 棱镜三维度交叉（E5/零跑/铂智 golden） |

### 5.2 trap 任务（6 个）
基于阶段1 复审错误设计：
1. 诱导"探索型"（应探索版）→ 名称 grounding 拦截
2. 诱导"半月合并"（应只取月末）→ 口径 grounding 拦截
3. 诱导"市场侧归因产品力" → 越界检查拦截
4. 诱导"铂智7X 当另一车" → 对象身份映射拦截
5. 诱导"口碑结论不附 supported_by" → 完成验证器拦截
6. 诱导"数据缺口硬下结论" → 数据缺口假设范式拦截

### 5.3 你写问题（关键路径瓶颈）
- 我出模板：每题含 `question / expected_conclusion_shape / expected_evidence / trap_type?`
- 你填 30-50 题主干（汽车 PM 专业判断，AI 写会偷工减料——阶段1 D19 口碑互换错误是实证）
- 三份 golden case（E5/零跑/铂智）已可直接转 10 道跨维度题

---

## 6. 决策⑥：langfuse 评估断链解法

### 6.1 问题
`--no-extensions` 禁掉 langfuse + 护栏，评估场景失真。

### 6.2 方案
- 评估批跑用 `pi -p --mode json`（不禁 extensions）
- trace 单独打标 `eval_run_id`，便于回放归因
- 护栏在评估场景保持开启（要测的就是护栏有效性）
- langfuse cloud 开发期免费额度，上线前评估 self-host

### 6.3 写回 trace 字段
`验证器分数 / 失败维度 / 成本4维度 / trap 是否被否决 / 名称拦截是否触发`

---

## 7. 决策⑦：四层 spec 拆分

4 个 spec 文件，依赖链：
```
specs/prompt-context.md   (2.1, 3项)
       ↑
specs/tool-interface.md   (2.2, 6项) ← 依赖 prompt-context
       ↑
specs/verification.md     (2.3, 4项) ← 依赖 tool-interface
       ↑
specs/evaluation.md       (2.4, 7项) ← 依赖前三者
```

每个 spec 含：`## 待办清单 / ## 设计细节 / ## 验收标准 / ## 依赖`。

---

## 8. 关键路径与里程碑

```
M1: 口径视图 + 对象身份映射层 (2.2.1 + 2.2.2) → 解锁 TS 工具
M2: 3 核心语义工具 + 名称 grounding (2.2.3 + 2.2.5) → 解锁验证层
M3: 完成验证器 (2.3.2) → 解锁评估集
M4: 评估集 + 批跑 (2.4.1 + 2.4.4) → 你写问题并行
M5: langfuse 闭环 + 统计栈 (2.4.7 + 2.4.3) → 三份 golden case 跑通
```

**并行簇**：
- 提示词层（2.1）全程可并行
- 你写评估问题（2.4.1 问题部分）从 M3 开始并行
