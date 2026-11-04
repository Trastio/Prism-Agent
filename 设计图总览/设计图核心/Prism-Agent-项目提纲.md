# Prism-Agent 项目提纲

> 生成：2026-09-07 ｜ 更新：2026-10-02 v2.4（① E5 数据盘点复审重核（P0：118=重名车系加总，银河E5 实测 1274口碑/286销量/20加权/version=5）；② 商业北极星改 DAU（看板/对话分开）；③ 补"不跳步 vs 双向交叉验证"分层规则；④ v8→v11 同步、20+→21 同步）。
> 前次更新 2026-10-01（峰值并发 50-100 → 40 单机起步 + §5.1.1 PM 性六层落点）。
> 本文是"大方向"层面的统一视图与唯一事实源；原 `汽车PM竞品分析系统-规划.md` 已删除，内容并入本文（其被推翻的旧决策仅作历史记录）。
> 具体实现逐步收口。

---

## 0. 一句话

给**汽车产品经理**的 data agent：让 **配置 / 口碑 / 销量** 三个维度互相印证、倒推因果，帮助产品决策。

**三角模型 = 产品棱镜理论**（已确认，无额外维度）。核心不是"查数"，是"给结论"。

---

## 1. 产品理论（棱镜 / 三角模型）

```
配置 = 产品力（厂商投了什么、改了什么）
口碑 = 需求验证（用户感知成什么、痛点在哪）
销量 = 市场结果（市场买不买账）
三者双向交叉验证：任何一维的疑问，去另外两维找答案。
```

- **"不跳步"与"双向交叉验证"的分层规则**（2026-10-02 补，调和 L24 与 §5.1.1/运行流程 Stage1 的张力）：默认按 配置→口碑→销量 顺序推进（不跳步）；查完一维后允许带疑问回查另一维（双向交叉）；但**禁止某维没查完就用别的维度下结论**。即：交叉验证是"查完之后回查"，不是"跳过未查维度"。

- **舆情在三角之外**，只和销量双向挂钩（营销变量，不是产品力）。
- **不是 chatbi，是 data agent**：chatbi 只答"E5 舒适性差评几条"，data agent 才给"舒适性是结构性短板"。
- 已用真实数据验证过：银河 E5 改款——续航/操控修好了、舒适性原地踏步、车机卡顿恶化 4 倍 → 舒适性是底盘/座椅结构性短板 = 竞品差异化窗口。

---

## 2. 产品形态：一个产品，两种模式（2026-09-08 定稿）

**最终形态是交互式网站（不是报告交付物）**。底层同一套数据层；智能层按模式分化。

### 模式 A — BI 看板
- **图表**：直读库做展现（固定图表 / 参数化视图，开发者定义），**不需要语义工具**。
- **内嵌 AI 对话小界面**（独立于看板）：**只基于当前筛选条件筛出来的数据**做回答和总结——
  用户筛了什么，AI 就只看得见什么；服务端把数据访问范围锁死在筛选状态上（不是小号全库 agent）。
  用户想自己看数据、直观筛选 → 用这个模式。

### 模式 B — Agent 对话
- 表现形式是 AI 对话；**全库**访问走**语义工具**（受控参数化查询，不写裸 SQL）。
- **可输出各种文件**（excel / word 等交付物）→ 需要文件输出工具，同样受护栏约束。
  用户只想问问题、要结论和成品 → 用这个模式。

### 分工与边界
- **一句话分工**：BI 模式回答"我看到的是什么"，Agent 模式交付"结论与成品"。
- **护栏压力集中在 Agent 模式**（全库入口，红线 #1/#2 靠语义工具 + 护栏兜底）；BI 内嵌对话被筛选锁死，越权面天然小。
- **口径一致**：两条数据通道读同一套库/视图，两个模式的数字必须对得上。
- 对话（两种模式）**不写库**：读-only 语义工具 + 文件输出产物区，守住数据真实性。
- 交叉跳转（远期增强）：Agent 结论卡 → 下钻 BI 筛选视图；BI 异象 → 带筛选上下文转问 Agent。

### 2.1 看板能力工具化 + UI 借鉴（2026-10-01 增补，2026-10-02 两项目重摸校准）

**核心约束（用户拍板）**：agent 具备看板的所有能力（舆情/市场/口碑/配置），但**只允许使用，不允许增删减改数据**。这同时满足红线#1（数据真实性）和红线#3（权限：管理者唯一可写）。

**为什么必须工具化（不是提示词约束）**：
- 看板模式是"直读库渲染图表"（无 agent），agent 模式是"语义工具调用"。同一份数据能力，两种消费方式。
- "只许用不许改"不能靠提示词自觉——in-context agent 不可靠地自检注入（红线#5）。必须让 agent 调用能力时**结构上不可能写**：工具函数体根本没有写操作代码，SQLite 只读连接，REST 端点 GET only。
- 工具化还带来：tool_call 护栏能拦截（cc-safety-net + 自建红线 fail-closed）、tool_result 能改写做 grounding、langfuse 能记录轨迹（已核实，见 §5.7 L6）。

**四类看板能力 → agent 工具映射**（2026-10-02 校准：Atuohome 已到 v11、舆情 47 端点）：

| 看板能力 | agent 语义工具 | 数据来源 | 只读保证 | 看板模式的等价端点（2026-10-02 实测） |
|---|---|---|---|---|
| 口碑 | `query_reviews`（维度聚合/全文检索/维度原文/竞品对比） | autohome.db 只读 | SQLite 只读连接 + 工具体无写代码 | Atuohome `/dashboard/koubei` + `/dashboard/koubei/series/{id}` + `/peer-compare` + `/export` |
| 配置 | `query_config`（车型/年款/阶梯/概念赋分/版型结构） | autohome.db 只读 | 同上 | Atuohome `/dashboard/config` + `/trims/{id}` + `/ladder` + `/year-compare` + `/concept-configs` + `/concept-scores/{id}` + `/workshop` |
| 市场/销量 | `query_sales`（销量趋势/零售/同级对比/散点/级别汇总/版型结构/洞察） | autohome.db 只读 | 同上 | Atuohome `/dashboard/market` + `/api/series-list`/`trend`/`retail`/`compare`/`scatter`/`level-summary`/`months`/`trim-structure`/`insight`（9 个 GET API） |
| 舆情（外挂第四组·按需触发） | `sentiment_*`（见下"舆情工具组拆分"） | 舆情 REST 只读端点 | HTTP GET only + 端点本身只读 | 舆情 Board `/api/dashboard/*` **21 个 GET**（详见下） |

**舆情工具组拆分**（舆情 Board 实测 47 端点 = 35 GET 只读 + 12 写；Prism 对接 21 个 dashboard GET，按 PM 视角分 6 个语义工具）：
- `sentiment_overview`：overview/fleet-overview/increment-overview（声量+热度+7日增量）
- `sentiment_trend`：trend/sentiment-trend/comment-sentiment-trend/platform-distribution/event-distribution（趋势+平台分布）
- `sentiment_dimension`：dim-sentiment/dim-examples/word-cloud/negative-radar/defect-themes（维度+原文+缺陷话题，**dim-examples 是幻觉溯源证据链核心**）
- `sentiment_posts`：top-posts/posts/post-comments（帖+评论原文，**post-comments 单帖评论**）
- `sentiment_competitive`：competitor-comparison/comment-sentiment-diff（竞品对比+评论情感差异）
- `sentiment_events`：vehicles/{id}/events/top-events/top-opinions（事件时间线+舆论标签）

**写端点全清单 + 隔离策略**（2026-10-02 校准，之前只列 3 个，实际 Atuohome 6 + 舆情 12）：

| 端点 | 类别 | Prism 处理 |
|---|---|---|
| Atuohome `POST /config/prices`（选配价） | 管理者写 | 移入管理者后台，弹密码解锁 |
| Atuohome `POST /config/policy-prices`（政策价） | 管理者写 | 同上 |
| Atuohome `POST /config/refresh-snapshot/{id}`（配置快照刷新） | 管理者写 | 同上 |
| Atuohome `POST /koubei/series/{id}/insight`（AI 口碑洞察，落 insight_cache） | LLM 缓存写 | 移入管理者后台（消耗 LLM 成本，需授权） |
| Atuohome `POST /config/year-compare/{id}/confirm`（配置差集计算确认） | 计算确认 | 不工具化（看板内功能，agent 不需要） |
| Atuohome `POST /config/workshop`（作战室 what-if） | 计算确认 | 不工具化（看板内功能） |
| Atuohome `POST /dashboard/market/import`（CAM Excel 导入销量） | 管理者写 | 移入管理者后台，弹密码解锁 |
| 舆情 `POST /collect`/`trigger`/`reports/*`/`vehicle CRUD`/`watchlist` 等 12 个 | 舆情侧 cron+管理 | **Prism 完全不碰**——舆情采集/分析/报告由它自己 cron 承担，Prism 只消费 dashboard GET 结果 |

**关键设计点**：
- **看板的"图表渲染"能力 agent 不需要**——agent 产出结论+证据行 ID，不是图表。两种模式共享数据层，分化在表现层（看板渲染图表 / agent 输出结论与文件）。
- **口径一致**：agent 工具和看板直读查同一套口径视图（§5.7 L3），两个模式数字必须对得上。
- **写能力三层隔离**：① 普通用户=只读工具白名单（结构上不可写）；② 管理者=弹密码解锁 Atuohome 7 个写端点；③ 舆情 12 个写端点 Prism 完全不碰（舆情侧自管）。对齐红线#3。
- **BI 内嵌对话的受限上下文**：模式 A 的内嵌 AI 不走全库语义工具，服务端把数据范围锁死在当前筛选态（§2 模式 A），越权面天然小。

**UI 借鉴（Atuohome_Agent v11 现状，2026-10-02 探子核实）**：
- Atuohome 栈 = FastAPI + Jinja2 SSR + 原生 CSS + 本地 vendor Chart.js（无前端构建、无模板继承、每页独立）。Prism 的 pi 是 TS，前端自建——**借鉴的是视觉/布局/交互模式，不搬代码**。
- 可复用要素：① CSS 变量系统（`--line`/`--accent` 等）；② Chart.js 图表 helper 模式（`fetchJSON`+`paint`+`renderFallbackTable` 降级表格，见 Atuohome `dash_market.html`）；③ 布局约定（max-width 居中容器 + `.panel`/`.module` 卡片 + `.tiles` KPI 行）；④ SSR 首屏 + JSON API 交互的混合数据通道。
- Prism 双模式网站的页面结构（参照 Atuohome 看板 + 新增 agent 对话）：BI 看板页（口碑/配置/市场，舆情嵌口碑下钻）+ Agent 对话页（独立，全语义工具）。
- 写端点（7 个管理者写 + Excel 导入）在 Prism 侧移入"管理者后台"，不对普通用户暴露。

---

## 3. 功能范围

| # | 功能 | 说明 | 已有资产 |
|---|------|------|---------|
| ① | 配置对比 | 版型阶梯 / 年款对比 / 跨车型对比 + 配置赋值 + 政策价格；赋值可由用户设定 | `配置研究skills运营/README.md`（已定稿）+ `Atuohome_Agent/src/tools/config.py` |
| ② | 口碑研究 | 基于汽车之家口碑数据，BI 看板，按维度下钻 | `Atuohome_Agent`（标签体系 + 护栏 + koubei skill + 22 个 MCP 工具） |
| ③ | 销量 | 由管理者（用户本人）提供，做成 BI 看板 | 无（新增，录入方式/颗粒度待定） |
| ④ | 舆情 | 基于自有项目，采集抖音/小红书/快手/微博等评价并展示 | `Vehicle Sentiment Analysis Board`（MediaCrawler + 情感模型） |
| — | RAG 知识库 | 行业报告/文档检索，作为 skills 底层检索能力 | `汽车知识库RAG`（MinerU + FAISS + BM25 + rerank） |
| — | 文件输出 | agent 输出 excel/word 报告 | 无（新增，openpyxl / python-docx） |

---

## 4. 已拍板的架构决策（不可推翻）

### 4.1 来自 `配置研究skills运营/README.md`
1. **描述层不走 LLM**：阶梯 / diff / 对比是确定性查询 + 渲染，秒回、零编造风险、埋点干净。
2. **赋分主体是人，不是 LLM**：默认赋分表是人工专业知识（版本化、全局运营资产）；分数是确定性算术；LLM 只做解读叙述，**绝不产生分数**。
3. **默认表 + 用户覆盖层（Override）**：用户不直接改默认表，改的是 session/用户维度 override，计算时合并。→ 这回答了"配置赋值由用户设定" vs "其他人不能改数据"的冲突：**默认表是全局资产（只有管理者能改），override 是用户私有层（各自设定）**。
4. **配置项归一化**：跨车型/年款对比前，原始配置名必须过归一化映射表（最大脏活）。
5. **数据真实性红线**（继承 Atuohome_Agent）：分数可追溯、未赋值标注"不计分"、数据缺失如实说缺失。

### 4.2 历史决策（原规划文档，已并入本文并删除）
6. **数据真实性护栏下沉执行层**：护栏放在 pi 的 `tool_call` / `tool_result` 钩子（核心层 `before_tool`/`after_tool` + fail-closed），**不是提示词**。理论依据：同一上下文里的 agent 无法可靠判断自己是否被注入。
7. **模型栈**：远端 DeepSeek + 本地 Qwen3-4B（仅舆情离线情感打标，微调模型，不在 agent loop 内）。

### 4.3 架构演进决策
8. **部署**：**阿里云，单机起步，峰值并发 40 设计**（2026-10-01 修正：原 50-100 多实例方案过度设计，40 是单机舒适区；工位机单机方案仍出局，上云不变）。规格：**单台 ECS 4c16g（ecs.g9i.xlarge）+ Alibaba Cloud Linux 3 + 50GB 数据盘 + 5Mbps 带宽，1 个月包月起步**；1–2 个 pi SDK 进程异步并发 + 本地 Nginx 反代，不上 SLB/不建多实例（留作远期扩展项）；Redis 从"必须上"降为"建议上"（容错+扩展余量，非 P0 阻塞项）。详见 §5.7。
9. **一个站点多页面**，共享一套埋点。
10. **最终形态是交互式网站**（推翻原规划"报告即产品/企微分发"旧方向）：Web 前端自建，pi 只做引擎藏在 API 后（pi 本身无 web UI 模式，见 §5.5）。
11. **认证方案（2026-09-30 拍板）**：**不做登录系统**。普通用户浏览器 localStorage 生成本地 ID（`usr_xxx`）零登录打开就用；管理者操作（采集触发等）单独弹密码。理由：基本无商业敏感数据、点反馈不需要知道用户是谁、badcase 评估靠完整轨迹（session_id 回放）不需要关联真实人。三层隔离：DeepSeek user_id（KVCache/调度/内容安全隔离）+ pi SessionManager.inMemory per-user（会话状态隔离）+ per-user 工具白名单（数据访问隔离）。详见 §9.2。

---

## 5. 技术底座与 harness 选型

### 5.1 harness 的作用边界（关键澄清）
- **harness 只服务于 Agent 入口**：对话循环、三角交叉验证、口碑/销量/舆情的 data-agent 查询、文件输出。
- **配置研究是确定性管线**（REST 直查直渲染），不依赖 harness，只有 NL 兜底时用。
- **BI 看板不经过 harness**：直读库展现（§2 模式 A）；BI 内嵌对话也不走全库语义工具，走筛选锁定的受限上下文。

### 5.1.1 PM 性落点：让 agent 像汽车产品经理思考（2026-10-01 增补）

**核心原则**：PM 性不是给 agent 戴"你是汽车PM"的帽子（身份扮演会让它"说"像而"做"不像），而是让 agent **按 PM 的思维流程推进**——配置（产品力）→ 口碑（需求验证）→ 销量（市场结果）三角交叉，输出结论（"舒适性是结构性短板"）不是计数。教材原则：信息组织一乱降 30% 成功率，所以 PM 性首先是**流程骨架**，不是知识堆砌。提示词是骨架，工具/口径/验证/评估才是血肉——只写提示词，模型可提议结论却不能保证结论对，真正的 PM 性压在执行层。

**PM 性六层落点**（对应 harness 五层，提示词只是其一）：

| 层 | 落点 | PM 性承载 | 机制 |
|---|---|---|---|
| ① 提示词层 | 棱镜 SOP 作为流程骨架 | 三层推进纪律（配置→口碑→销量不跳步）+ 结论定义（结论=结构性判断+证据行ID+as_of，计数不是结论）+ 两层提示词（全局层永不动锁 SOP+红线 / 会话层锁快照绑当前车型过滤态）+ 失败模式预防（数据缺失如实说缺失，不许用相邻车型补） | `before_agent_start` 动态注入（非静态 AGENTS.md），BI 嵌入会话注入受限子集 |
| ② 上下文层 | 状态栏挂三维度完成度 | agent 自己看得见哪维没查（PM 的 checklist 习惯） | 状态栏 hook + compaction 保留完成度标记 |
| ③ 工具接口层 | 三核心常驻工具 = 棱镜三维度物化 + 舆情按需第四组 | PM 不会没看产品力就谈市场结果——工具门控（`setActiveTools`）按阶段解锁，没查配置时销量工具不给；舆情 sentiment_* 是外挂第四组，三个时机触发（销量波动/口碑销量背离/用户主动问） | 3 核心常驻 query_config/reviews/sales + 6 个 sentiment_* 按需 + 阶段化 tool 白名单 + tool_call 护栏 |
| ④ 验证层 | 完成验证器替 agent 做 PM 的"复核" | PM 会复查自己的判断，agent 自己不会——独立验证器管这件事 | `agent_before_settle` 拦收尾：每结论必带 evidence:[row_id]+as_of；grounding 管销量/配置数值；口碑定性结论走 claim 溯源+人工抽检 |
| ⑤ 编排层 | 三维度并行 = PM 多源交叉习惯 | 复刻 PM 同时看三张报表交叉验证的工作方式，非为并行而并行 | pi-subagents 三维度独立并行调查 + 结构化摘要回传 + 主 agent 综合判断 |

**PM 性的两个外围支柱**（不在 harness 五层内，但同等关键）：
- **口径视图 + 口径说明书 = PM 的类型系统**：PM 算错数字多半是口径错（提及率=标签次数÷已打标条数，不是÷总口碑）。口径视图放 Prism 侧，每个数字带口径元数据，agent 拿到的不是裸数字而是"带口径标签的数字"——它不用懂口径，工具返回时口径已钉死（消费者口径资产不放生产库，§5.7 L3/L5）。
- **评估集 = PM 专业判断的活资产**：30–50 个问题**必须用户写**（教材实战：AI 写测试会偷工减料，"AI不会自己停下来"是 AI PM 核心价值）。问题的"标准答案"就是用户的 PM 判断，trap tasks 是 PM 才会踩的坑（如"用相邻车系数据补缺"——AI 易犯、PM 不会犯）。agent 像不像 PM，跑一遍评估集就知道（§8 评估体系）。golden case 银河E5 端到端报告（工作⓪）= PM 会怎么分析一台车的 in-context 范例，是 agent 学习 PM 思维的 few-shot 范本。

**一句话**：提示词管"怎么想"，工具门控管"流程纪律"，口径视图管"数字正确"，验证器管"结论可靠"，评估集管"持续校准"——五层合起来才是 PM 性，缺一就退化成"会聊车的 chatbi"。

### 5.2 候选对比（2026-09-07 GitHub 实测）

| 底座 | 语言 | License | Stars | 定位 | 适配判断 |
|------|------|---------|-------|------|---------|
| **pi / pi-mono** | TypeScript | MIT | ~103k | 原版 Pi，monorepo（agent/server/telemetry/evals/session-backends） | ✅ **已选**：server=多用户并发、telemetry=埋点、evals=评测、hooks fail-closed=护栏 |
| tau | Python | MIT | ~2.6k | Pi 的 Python 版，`AgentHarness = 可复用脑` | 最小骨架：钩子+skills 有，但 server/telemetry/evals 全要自己造 |
| deepseek-harness | TypeScript | MIT | ~215k | 官方，everything-is-a-plugin（Cordis） | ❌ developer preview 会 breaking change，不稳 |
| pydantic-ai | Python | MIT | ~20k | 类型化、模型无关 | 备选：成熟但偏"库"，无 server/telemetry/evals |
| agno | Python | Apache-2.0 | ~42k | 平台（auth / 多租户 / 可观测） | 备选：平台能力内置但重、绑定 |
| smolagents | Python | Apache-2.0 | ~29k | CodeAgent（think in code） | ❌ LLM 写代码路线，撞数据真实性 + RCE |

### 5.3 结论：选 pi-agent（2026-09-07 定稿）

**底座 = pi / pi-mono（TypeScript）**。核心理由（均已核实源码）：

1. **`packages/server`** → 多用户 HTTP 服务，对应峰值并发 40 单机起步部署（远期多实例 + SLB）。
2. **`packages/telemetry`** → 轨迹监测 + 埋点内建（managing 清单第 6 条）。
3. **`packages/evals`** → agent 评测内建（managing 清单第 2 条）。
4. **`hooks.ts` 的 `before_tool` 返回 `block: { reason, terminate }` + `invokeAllFailClosed`（fail-closed）** → 数据真实性护栏比 tau 更强：能拦截、能终止、钩子出错按拦截处理。
5. **`session-worker-manager` / `session-backends`** → worker 级并发会话隔离。

**唯一代价**：TypeScript。22 个 Python 工具要搬成 TS；但舆情管线 / RAG / 爬虫作为独立 Python 服务不动，pi 通过共享 DB / HTTP 调用。

### 5.4 spike 验证清单（0.5–1 天，验证 pi 是否真合脚）
1. `server` 模式跑起来 + 开多个并发会话（验证 40 峰值并发）。
2. 写一个 TS 数据工具查口碑/销量库（验证工具迁移成本）。
3. 用 `before_tool` 拦住"标签未就绪"并 `terminate`（验证护栏）。
4. 舆情 Python 管线 → 共享 DB → pi 工具读库（验证解耦接入）。

### 5.7 部署架构（2026-10-01 修正 · 云 + 峰值并发 40 · 单机起步）

**形态**：阿里云，**单台 ECS 单机起步**，1–2 个 pi SDK 进程异步并发 + 本地 Nginx 反代。原 50-100 多实例 + SLB 方案降级为远期扩展项（用户量起来再加第二台挂 SLB，本地 Nginx 可平滑过渡）。

**为什么从 50-100 改 40**：40 是单机舒适区。DeepSeek 是远程 API，pi 进程 I/O bound（主要等 DeepSeek 流式返回），40 在途并发实际只占 4c16g 的 1/4 资源，瓶颈是带宽不是算力。原 10-20 pi + SLB 是为 50-100 真并发设计的水平扩展，40 人用不上。

**单机配置清单（1 个月包月·对照购买页）**：
- 规格：ecs.g9i.xlarge，4 vCPU / 16 GiB（扛 40 在途富余 3 倍，8GB 都够，留余量）
- 镜像：**Alibaba Cloud Linux 3**（不用 Windows Server——Redis 无 Windows 原生版，docker/Node 全是 Linux 原生）
- 系统盘：ESSD AutoPL 40GB
- 数据盘：**+50GB ESSD，挂 `/data`**（轨迹/运行时 SQLite/日志，和生产库隔离，方便扩容备份）
- 带宽：按流量计费 ¥0.72/GB，**峰值 5 Mbps**（1 Mbps ≈ 128KB/s 是整机上行共享，40 路 SSE 流式 ≈ 1.6Mbps，1Mbps 不够；流量量很小贵在峰值不在量）
- 时长：1 个月包月（验证期够跑 P0 + 工作⓪ + 早期试用，比按量划算，不锁长周期）

**分层**：
- **L1 表现层**：ECS + 本地 Nginx，双模式网站（BI看板 + Agent对话），HTTPS 终止。前端 localStorage 生成本地 ID。
- **L2 编排层**：**1–2 个 pi SDK 进程异步并发**（不是 40 个进程，node 单进程异步处理多会话）；本地 ID → DeepSeek `user_id` 贯穿（KVCache/调度/内容安全隔离）；Guardrail Hooks + 完成验证器（`agent_settled` 事件，注意官方名非 `agent_before_settle`）+ 三维度并行（DeepSeek 2500 并发配额宽裕，40 离它差 60 倍）。
- **L3 语义层**：TS 语义工具直读库。**MCP 桥退役**——stdio 每会话一进程在并发下进程数炸，直接走 TS 工具直读库（原 P0 gate 验证取消）。
- **L4 供给层**：Atuohome SQLite 只读直连（主，autohome.db 1.07GB / 口碑 12.3万 / 标签 29.4万 / 销量 19.7万行 / 配置快照 244 系）+ 舆情 REST 单通道（21 个 dashboard GET）。黑盒不动内部。**两项目服务都监听 127.0.0.1 本机、无鉴权、CORS 仅本机**——上云时必须改造（见 L6 三个上云风险）。
- **L5 数据层（读写分离·关键改动）**：生产库 autohome.db 只读直连（数据真实性红线不破）；运行时写（会话/trace/记忆/反馈）拆到独立 SQLite（起步）/ Redis（建议加）——避免污染生产库。
- **L6 安全/监控**：API key 用阿里云 KMS/加密环境变量注入（不裸进镜像）；APM + 错误聚合（不上 Prometheus/ELK 全套）；无登录系统（本地 ID + 管理者弹密码）；DeepSeek user_id API 侧隔离 + per-user 工具白名单；**langfuse 已装并已核实监测能力**（见下）。

**供给端上云三个必解风险（2026-10-02 两项目重摸发现）**：
1. **Atuohome 服务无鉴权 + 127.0.0.1 + CORS 本机**：上云时不能直接暴露。解法：作为 sidecar 服务只对内网/VPC 开放，Prism 通过内网调用；或加鉴权改 CORS。舆情 Board 同样监听 127.0.0.1:8000，同问题。
2. **写端点限流穿透**：Atuohome 写端点统一 `_rate_limited` 每 IP 10次/分钟。40 用户共享 ECS 出口 IP 时限流会穿透。解法：Prism 调写端点集中在管理者后台单点（管理者操作本就低频），不走多用户路径。
3. **TikHub 单点依赖（舆情数据源）**：舆情 Board 2026-09-27 OneAPI 退役，社媒全量（微博/小红书/快手/抖音）切 TikHub 一个源。TikHub 余额/可用性=舆情生命线。红线#4 合规要重审 TikHub 协议（不是 Prism 直接采集，但舆情数据流入 Prism，需确认数据使用许可）。bocha 仍待充值状态未变。

**Langfuse 监测能力核实（2026-10-01 npm registry + 源码核实）**：包 `@langfuse/pi-observability-plugin@0.1.2`（Langfuse 官方维护，MIT）。hook 事件：`session_start`/`before_agent_start`/`before_provider_request`/`message_update`/`message_end`/**`tool_execution_start`**/**`tool_execution_end`**/`session_before_compact`/`session_compact`/`session_tree`/`agent_settled`/`session_shutdown`。**自建工具（`pi.registerTool`）完整覆盖**——插件 hook 的是执行层 `tool_execution_*` 事件，对所有工具（内置/自建 TS 语义工具/MCP 转发）一视同仁。**trace 记录字段**：工具名(`tool_name`) + 调用 ID(`tool_id`) + **参数(`input`，脱敏+截断 20K)** + **返回值(`output`，截断 20K)** + `is_error` + `usage`/成本(独立 `Tool LLM Usage` observation，自建工具内部若调 LLM 成本也可捕获) + 耗时(span duration)。配置：`~/.pi/agent/langfuse.json` 放 `publicKey`/`secretKey`/`baseUrl`（chmod 600），或环境变量 `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_SECRET_KEY`/`LANGFUSE_BASE_URL`；kill switch `LANGFUSE_TRACING_ENABLED=false`。**对评估闭环意义**：验证器分数+失败维度+成本 4 维度写回 trace 完全可行，badcase 归因可拿到完整参数/返回值。

**DeepSeek 限流事实（官方文档核实）**：deepseek-flash 单账号并发限制 **2500**、v4-pro 500；超限返 HTTP 429 不排队；可提扩容工单（不额外收费）。40 真并发会话离 2500 差 60 倍——**限流不是瓶颈，连扩容工单都不需要**。`user_id` 参数实现同账号下用户级隔离（KVCache + 内容安全 + 调度隔离），扩容账号下每 user_id 也限 2500（flash）。三维度并行限流压力顾虑消除，可保留激进用法。

**读写分离理由**：生产库与运行时写必须拆——生产库纯只读（红线保留），运行时写（轨迹/mem0记忆/langfuse trace/反馈点踩）走独立 SQLite/Redis。原"50-100 真并发下 SQLite 单写锁必炸"的强度顾虑在 40 人下降档，但读写分离的**隔离红线意义不变**（不污染生产库只读红线），仍必须拆。

**会话状态：Redis 建议上，非 P0 阻塞**（2026-10-01 修正）：原"多实例+SLB 下用户落不同实例会丢会话，Redis 必须上"的理由在单机单进程下消失。Redis 仍有两个残留价值：① 进程崩溃恢复（pi 进程挂了会话不丢，能从 Redis 续上）；② 后续加第二台机器时不用重构。工作⓪ 阶段先用 pi `SessionManager.inMemory()` 内存会话跑通端到端，Redis 留到阶段3 上线基建加。若要"崩了不丢会话"容错但不想现在上 Redis，可用 `SessionManager.inMemory()` + 定期落独立 SQLite 快照（pi 支持从 DB 条目恢复会话）。

### 5.5 pi 的能力核实（2026-09-07/08 已核实）

| 能力 | 结论 | 依据 |
|------|------|------|
| 护栏 hooks | ✅ 有，扩展层 `pi.on("tool_call")`（`{block,reason,terminate}`）+ `tool_result`（改结果/信封）；核心层 `before_tool`/`after_tool` + `invokeAllFailClosed`（fail-closed） | `docs/extensions.md`（Tool Events）+ `packages/agent/src/harness/hooks.ts` |
| 并发 / 多用户 | ✅ 有 server + session-worker | `packages/server`、`session-worker-manager.ts` |
| 轨迹监测 / 埋点 | ✅ 有 telemetry 包 | `packages/telemetry` + `harness/telemetry.ts` |
| 评测 | ✅ 有 evals 包 | `packages/evals` |
| Skills（SKILL.md） | ✅ 同 spec | `.pi/skills/` + `harness/skills.ts` |
| subagent | ⚠️ 是 TS extension 示例，非核心 | `examples/extensions/subagent/`（agents.ts） |
| MCP | ❌ 无内置 | 全仓 grep `mcp` 零结果；用共享 DB / HTTP 替代 |
| Web UI 模式 | ❌ 无 | 四种模式：interactive TUI / `-p`/`--mode json` / `--mode rpc` / SDK；只有静态 `/export` HTML、`/share` gist → **Web 前端自建，pi 只做引擎** |
| DeepSeek provider | ✅ 内置（无需写扩展） | `DEEPSEEK_API_KEY` 或 auth.json `deepseek` 条目；目录仅对已有凭证的 provider 刷新（`pi update --models`） |

**舆情接入结论**：采集 + 情感打标（Python 管线）独立跑、产出入库；pi 的 TS 工具读共享库或调 HTTP。不重写数据管线，只重写查询/展示层。

**2026-09-15 定稿：舆情经 REST 接入，不做 MCP**（2026-10-02 校准端点数）。决策依据：① pi-mcp-adapter 的定位是 Atuohome 存量 15 工具的过渡桥，其对 MCP 转发调用的护栏拦截未验证——红线 #1 不押在最不确定的组件上；② 工具面 ≠ API 面，精选语义工具必须做在 TS 原生侧（hooks/telemetry/evals 看得见、tool_result 钩子能改写）；③ 40 人并发下 stdio 传输每会话拉起一个 MCP 进程 × SQLite 单写锁；④ HTTP 是最可移植协议，换/自研 harness 只需一个 fetch 层。协议选择跟着已存在的访问层走：MCP 桥已退役（Atuohome 改 TS 直读库），舆情 REST 直接对接 21 个 dashboard GET（分 6 个 sentiment_* 工具组，见 §2.1）。

> **2026-09-30 修正**：上述③的进程模型顾虑在并发下放大——stdio 每会话一进程峰值进程数炸，**MCP 桥直接退役，不走过渡验证，Atuohome 也改 TS 语义工具直读库**（原 P0 gate 验证取消）。详见 §5.7。

**对接契约**：Prism 语义工具薄封装 `http://<舆情服务>/api/dashboard/*`（只读）：overview / trend / sentiment-trend / platform-distribution / event-distribution / top-posts / posts / events / dim-sentiment / word-cloud / competitor-comparison / comment-sentiment-diff / **dim-examples**（维度→帖+评论原话实例，幻觉溯源证据链）/ **post-comments**（单帖评论）。舆情管线独立运行，调度层 cron 调 `daily_update.py`（退出码 0/1/2/3）。上云时舆情成 sidecar 服务 + DB 迁 PostgreSQL，pi 工具不变。口径注意：舆情侧情感/健康分/维度自 2026-09-15 起排除官方与经销商作者（author_type 分层），热帖/声量保留全部。

### 5.6 社区包清单（2026-09-08 定稿，2026-10-01 装齐 11 个）

**项目级（`.pi/settings.json`，3 个）：**

| 包 | 用途 | 状态 |
|---|------|------|
| `pi-web-access` | web 搜索/URL 抓取/PDF 提取——Agent 模式的联网能力（收口待定项 #5） | ✅ 已装，实测：agent 成功调用搜索并返回带来源结果（比亚迪 2026-08 销量查询） |
| `pi-mcp-adapter` | MCP 客户端——**已退役**（stdio 进程模型在并发下炸），留作参考不卸 | ✅ 已装，退役 |
| `pi-subagents` | 会话内子 agent 并行（362K/月下载，生态最大） | ✅ 已装，留给棱镜三维交叉验证（配置/口碑/销量并行调查） |

**全局级（`~/.pi/agent/settings.json`，8 个）：**

| 包 | 用途 | 状态 |
|---|------|------|
| `pi-memory` | 显性记忆 | ✅ 已装 |
| `@amaster.ai/pi-memory-mem0` | 隐性记忆（mem0） | ✅ 已装 |
| `@gotgenes/pi-permission-system` | 权限系统 | ✅ 已装 |
| `@juicesharp/rpiv-ask-user-question` | 结构化问卷（需求澄清） | ✅ 已装 |
| `@langfuse/pi-observability-plugin@0.1.2` | 埋点+评估数据底座（Langfuse 官方，已核实监测自建工具，见 §5.7 L6） | ✅ 已装 |
| `@juicesharp/rpiv-todo` | 任务清单面板 | ✅ 已装 |
| `cc-safety-net@2.4.15` | 红线#3 护栏——拦破坏命令/SSH/.env（兼容 pi，有 pi 扩展入口） | ✅ 2026-10-01 装齐 |
| `@narumitw/pi-usage` | DeepSeek 余额/成本监控——喂评估闭环成本4维度 | ✅ 2026-10-01 装齐 |

**明确不装的（2026-10-01 核实）：**
- 并发/多用户隔离包——**不需要**：SDK 原生（每用户一个 `createAgentSession`，对象边界即隔离；`tools` 按会话定制 = 权限落地）。要自建的是用户↔会话映射、生命周期管理（属于我们 Web 服务层）
- `pi-web-ui`——MIT+插件系统可改，但它是暴露终端（xterm+node-pty）/文件树/Git 的**开发者个人控制台**，单 token 认证，与"49 人只读"安全模型相反。定位：SDK+WebSocket 接线的参考实现 + 管理者私人调试台，**不做产品前端**
- 记忆/观测/权限类包——pi 内置 session/telemetry 够用，权限长在自己服务层
- **pi 官方 Redis session backend**——npm 不存在（`@earendil-works/pi-session-backends`/`pi-session-manager` 均未注册）。Redis 外置自建适配 SessionManager 接口，或用内存会话+落盘快照替代（见 §5.7）
- **`pi-guardrails`**——只管 GitHub 读写控制，不符红线#3 需求（拦破坏命令/SSH/.env 用 cc-safety-net）
- Auth/APM 包——无登录系统 + 阿里云 APM，不需要

**社区没有、必须自写**：语义数据工具、完成验证器、grounding 改写、状态栏 hook、文件输出（exceljs + docx）、Redis 会话适配（如上 Redis）。

**安装纪律与技巧（实测）：**
- pi 包全系统权限运行，装前过一眼源码；项目级装用 `-l`，试用用 `-e`
- ⚠️ 国内网络实测：`pi install` 调 npm 解析元数据极慢（可挂 5 分钟+）。**解法：先在 `.pi/npm/` 里用系统 npm 装一遍预热缓存（npmmirror 镜像，~1 分钟），再跑 `pi install`（秒过）**。2026-10-01 装 cc-safety-net/pi-usage 用此法，分别 539ms / 2s 完成
- 非交互模式（`-p` / `--mode json`）加载项目级包需 `--approve`；交互 TUI 首次会弹项目信任提示，`/trust` 保存后不再询问
- `pi list` 查看项目包也要 `--approve`


---

## 6. 权限与隔离（峰值并发 40 · 2026-10-01 更新）

- **管理者 = 你本人**，唯一可改数据（销量、默认赋分表等）。
- **其余 ~49 人只读**。
- 配置赋值 = 默认表（全局，只有你改）+ override（per-user，各自设）。
- **登录体系（2026-09-30 拍板）**：**不做登录系统**。普通用户浏览器 localStorage 本地 ID 零登录；管理者操作弹密码。详见 §4.3 决策 11 + §9.2。

---

## 7. MVP 竖切片（待拍板）

**原则：竖着打通一条，不横切铺四层。** 两条候选：

| 切片 | 说明 | 优点 | 代价 |
|------|------|------|------|
| **口碑研究 agent 最小闭环** | "问一句 → 调工具 → 返回真实结论"，跑通 harness + 护栏 | 是 data agent 灵魂、harness 用武之地、资产最厚 | 需 harness 先立起来 |
| **配置研究 M0/M1** | 阶梯表 + 赋分 + override + 埋点（已有完整设计） | 确定性管线快、埋点闭环清晰、不依赖 harness | agent 味弱，展示不了 data agent |

**倾向**：先做口碑 agent 最小闭环（de-risk harness，兑现"data agent"叙事），配置研究可并行或紧随（风险低、已有设计）。

---

## 8. 评估与迭代体系（2026-09-08 设计定稿，MVP 后落地）

> 方法论来源：《AI Agents in Depth》第 7 章 + 本项目落地设计。评估对象 = **模型 + Harness 组合体**（不是只测模型）。

### 8.1 原则与实验设计
- **model swap**（v4-flash ↔ v4-pro，固定 Harness）：换强模型分数大涨 = 瓶颈在模型；不动 = 瓶颈在工具/提示词设计
- **消融**（关掉某个组件看整体变化）：护栏 on/off、单个工具增删
- **一轮只改一个变量**；看到分数下降**先查评测系统本身**，再动 agent

### 8.2 指标：Pass^k 思维 + 幻觉一票否决
供产品决策的结论要求稳定（Pass^k：多次运行全对），不是"偶尔能对"（Pass@k）。四个维度：

| 维度 | 判定方式 | 备注 |
|------|---------|------|
| **幻觉检测** | 结论里每个数字/事实必须能溯源到工具返回 | **veto 一票否决** = 红线 #1 的评估落地 |
| 数字事实正确 | 确定性断言：agent 答的数字 vs SQL 直查金标准 | 便宜、稳定、进回归 |
| 结论质量 | Rubric 四档（优秀/良好/及格/不及格）+ LLM-as-a-Judge | Rubric 按四准则：专家知识（管理者本人写）、覆盖+陷阱、加权、自包含 |
| 缺数据如实报缺 | 库里没有 → 正确行为 = 报告缺失 | 红线 #1 |

Judge 防坑：长度偏差（显式惩罚冗长）、防关键词堆砌、多源评判（将来换族评判模型）。

### 8.3 用例集（20-30 个起步，三来源）
1. **银河 E5 案例** = 第一条天然金标准（已知正确结论：续航/操控修好、舒适性原地踏步、车机恶化 4 倍）
2. **参数化模板**批量生成（"对比 [车型A] 和 [车型B] 的 [维度]"），换参数防死记硬背
3. **陷阱题**（仿 τ²-bench）：库里只有 A 偏问"对比 A 和 B"——正确=报缺，编造=veto，专测红线
4. 上线后：**生产轨迹回流**（用户纠正/点踩 → 回归用例）——成本最高、价值最高，长期主体

统计纪律：30 用例只够筛方向（±十几个百分点波动正常）；模型对比用配对分析；预期收益 2-3 个百分点时先扩样本。

### 8.4 评估环境与跑批（对 pi 零改装）
- **环境五要素**：用例集（任务文件）/ 口碑库 **SQLite 锁快照**（可重置）/ 语义工具（固定版本）/ 评分标准 / 执行协议（轮数上限+停止条件）
- **轨迹白送**：pi session JSONL = 完整对话+工具调用记录；telemetry = 埋点
- **受控参数跑批**：`pi -p --mode json --no-session --no-extensions -e ./semantic-tools.ts --no-context-files --append-system-prompt "..." --model deepseek/deepseek-v4-flash`
- 薄跑批脚本（~100 行 Python）：逐用例调 → 解析事件流（答复文本/工具序列/usage成本）→ 验证器 → 分数表
- 多 seed = 同题跑 3 次；swap = 换 `--model`；消融 = 去掉一个 `-e`；成本从 usage 抽（v4-flash 便宜到可忽略）
- MVP 时埋的钩子（本来就在计划内）：工具/护栏写成**独立扩展文件**（可插拔=可消融）；口碑库 SQLite + 快照机制

### 8.5 迭代闭环：归因 → 回归 → 改一层 → 不退化才发布
- **失败归因**：找**首个错误**（后续错误是连锁反应）；pi `/tree` 可回放用户报告的现场
- **归因分类决定改哪层**：工具描述/schema（选错工具）→ 语义工具本身（能力缺失）→ 护栏+SYSTEM.md（编造/口径）→ 数据层（缺数据/归一化映射脏）→ 产品层（预期错位，不改 agent）
- **两层回归**：端到端（整题重跑）+ **轨迹前缀**（截到首错前只测决策边界，便宜）——每次改提示词/工具后跑，像 CI
- 修过的每个问题沉淀为回归用例，评估集从静态考卷长成活资产

### 8.6 用户反馈闭环（上线后运营）
- **三路信号**：①显式（👍/👎 按钮 + **对话内自然纠正检测**："不对/我说的是"自动打标）；②隐式埋点（追问率/改写重问/中途放弃/结论被复制/结论卡下钻 + 工具层空结果率）；③事后审计（离线幻觉扫描：全量轨迹数字溯源 + 抽样 LLM 评审）
- **规则先筛、LLM 再看**（省钱）；40 人规模**人肉归因优于平台**——一张表 + 管理者的眼睛，这是面试叙事（§10-6）的素材
- 上线后钩子：反馈按钮组件；events 表把"问题→工具调用→结论→反馈标记"串起来（复用配置研究的 events 埋点设计）

### 8.7 路线图
| 阶段 | 动作 |
|------|------|
| MVP 时 | 生产会话全量保存（默认即有）+ events 表串联 |
| MVP 后 1-2 天 | 评估 v0：20-30 用例 + veto 验证器 + Rubric → 基线分数 + 首份失败归因报告 |
| 随后 | swap（flash vs pro）+ 护栏消融 → "瓶颈在哪"的证据 |
| 上线后 | 反馈三路信号 → 周度归因 → 回归用例 +1 |
| 持续 | 每次改动跑回归（像 CI），不退化才发布 |

---

## 9. 待定项清单

| # | 待定项 | 优先级 | 备注 |
|---|--------|--------|------|
| 1 | BI 看板技术选型 | 高 | 复用 Sentiment Board 前端？Streamlit？Metabase？自研？（供给端看板已迭代到 v11，需基于 v11 现状重新切分） |
| 2 | ~~登录体系~~ | ✅ **已拍板（2026-09-30）** | 不做登录系统，本地 ID + 管理者弹密码，详见 §4.3 决策 11 + §9.2 |
| 3 | 销量数据录入方式 + 颗粒度 | 高 | 谁录、Excel 导入还是表单、月度/车型/年款 |
| 4 | skills 清单 | 中 | 复用 config/decision/market/koubei + 新增，还是按三角模型重设计 |
| 5 | web 搜索工具范围 | 中 | 通用搜索 vs 汽车垂类 |
| 6 | 舆情采集频率 + 合规 | 中 | 登录态脆、GPL/学习研究许可风险 |
| 7 | 评测体系 | ✅ **已设计定稿（§8）**，MVP 后落地 | 幻觉 veto / 确定性断言 / Rubric+Judge / 陷阱题 / 两层回归 |
| 8 | ~~成功指标~~ | ✅ **已拍板（2026-10-02 商业北极星改 DAU；2026-10-06 增列在线时长）** | 北极星三层（§9.8）：商业北极星=**日活量DAU（看板DAU+对话DAU分开）+ 在线时长（活跃时长）**/产品北极星=周成功交付结论数/输入指标=Pass^1×(1−幻觉率)÷单次成本等 |
| 9 | 模型评测范围（远端各家） | 中 | 选最佳主模型 |
| 10 | 部署形态 | ✅ **已拍板（2026-10-01 修正）** | 阿里云 + 峰值并发 40 + 单台 ECS 4c16g 单机起步 + 数据盘 + 5Mbps，详见 §5.7 |
| 11 | DeepSeek 并发配额 | ✅ **已核实（2026-09-30）** | flash 单账号 2500 并发，40 真并发够用，不需扩容工单，详见 §5.7 |

### 9.2 认证/隔离方案（2026-09-30 拍板）

**不做登录系统**——基本无商业敏感数据、点反馈不需要知道用户是谁、badcase 评估靠完整轨迹不需要关联真实人。

**会话身份**：浏览器 localStorage 生成本地 ID（`usr_xxx`，随机串），零登录体验，用户打开就用。稳定标识贯穿全链路。

**管理者操作**：仅采集触发等管理者操作时弹密码（最小化，普通查询不挡）。若后续放弃"采集需管理者授权"红线，连这也可省。

**三层隔离**：
- **L1 DeepSeek 侧**：本地 ID → API `user_id` 参数 → KVCache 隔离 + 内容安全隔离 + 调度隔离（DeepSeek 官方提供，零成本）。
- **L2 pi 侧**：`SessionManager.inMemory()` per-user 会话状态隔离，会话 key = 本地 ID。
- **L3 工具侧**：per-user 工具白名单（普通用户锁只读，管理者解锁采集）+ PEDO 权限 + tool_call 护栏。

**badcase 轨迹埋点（核心需求）**：`trajectories.jsonl` 按 session_id 记录完整对话历史 + 每轮 tool_call/tool_result + 状态栏快照（车型/三维度完成度）+ final conclusion + evidence 行 ID + **as_of 数据时点**。用户点踩带 session_id 入库，评估时按 session_id 拉轨迹回放归因（数据源过期 vs 推理错 vs 工具选错），不需要关联真实人。as_of 是关键——区分"数据过期"vs"推理错"。

**会话状态：Redis 建议上，非 P0 阻塞**（2026-10-01 修正）：单机单进程下原"多实例会丢会话"理由消失。Redis 残留价值=进程崩溃恢复 + 后续扩展余量。工作⓪ 先用 `SessionManager.inMemory()` 内存会话跑通，阶段3 上线再加 Redis（或用内存会话+定期落独立 SQLite 快照作容错替代）。详见 §5.7。

**密钥保密**：API key（DEEPSEEK_API_KEY 等）不裸进镜像，用阿里云 KMS 或加密环境变量注入。

### 9.8 北极星指标三层（2026-09-30 拍板 · 2026-10-02 商业北极星改 DAU + 推导链重写）

原"单位成本正确率"是输入指标不是北极星——它驱动 agent 质量迭代但讲不清"Prism 成了没"。问题 6 三处公式不一致的根源就是把它当北极星用了，现分清三层。2026-10-02 用户拍板：商业北极星从"决策数/月"改为"日活量 DAU"（看板 DAU 和对话 DAU 分开算），因为内部工具的存续判断标准=有多少人每天在用——日活是可观测、可日度量的存续信号，比"有效决策数"（难测、需定性退化）更直接。2026-10-06 用户拍板：**商业北极星增列"在线时长"一项**——DAU 只量"来没来"（广度），在线时长量"待多久/用多深"（厚度/粘性），单看 DAU 会把"打开即走"误判为健康，两者合看才是完整的存续信号。

| 层 | 指标 | 用途 | 度量难度 |
|---|---|---|---|
| **商业北极星** | **日活量 DAU**（看板 DAU + 对话 DAU 分开算）+ **在线时长**（活跃时长，看板/对话分开算） | 项目存续判断 | 易（埋点可算） |
| **产品北极星** | **周成功交付结论数**（被采纳未点踩的结论绝对量） | 日常驱动迭代 | 中（埋点可算） |
| **输入指标** | Pass^1×(1−幻觉率)÷单次成本 · WAU · 人均结论数 · 采纳率 · 响应时延 | 工程师可操作 | 易 |

**DAU 口径**（2026-10-02 定）：看板 DAU = 每天至少打开一个 BI 看板页的独立本地 ID 数（含只看图表不对话的用户）；对话 DAU = 每天至少发起一次 agent 对话的独立本地 ID 数。两个 DAU 分开算——因为看板是"被动消费数据"，对话是"主动要结论"，使用深度不同，分开才能看清"谁在用工具/谁在要结论"。总 DAU = 看板 DAU ∪ 对话 DAU（去重）。

**在线时长口径**（2026-10-06 定）：看板在线时长 = 每个本地 ID 每天在前端"页面可见且活跃"状态下的累计秒数（看板页）；对话在线时长 = 同口径累计于对话页。采集手段 = 前端 Page Visibility API + 心跳：页面可见时每 30s 写入一次心跳位点累加，`visibilitychange`（切后台）与 `pagehide/beforeunload`（关闭）时用 `navigator.sendBeacon` 补记最后一段，避免丢失。**刻意不用"会话时长"**（一次 SSE 连接存活时长）作口径——长分析单轮可达 25min 会让"时长"虚高失真；活跃时长更贴近"真的在用"。在线时长与 DAU 同源（同一本地 ID），看板/对话分开算，作为 DAU 的厚度维度并列入商业北极星。

**推导链（2026-10-02 重写·回答"为什么是这三个、怎么因果传导"）**：

起点（第一性原理）：Prism 是内部工具，存在的唯一理由 = 被汽车 PM 团队**日常使用**。内部工具不赚钱，价值锚=融入日常工作流；没人在用=项目已死。所以商业北极星=DAU（日活）。

```
商业层：日活量 DAU（看板 DAU + 对话 DAU 分开）+ 在线时长（活跃时长，看板/对话分开）
  ↑ 为什么是"日活"而非"决策数"？内部工具价值=融入日常工作流，"每天在用"=存活的最直接信号
  ↑ "有效决策数"难测需定性退化，DAU 可日度量、可对比、可设阈值
  ↑ DAU 只看广度（来没来）不够——2026-10-06 补"在线时长"量厚度（待多久/用多深）；单看 DAU 会把"打开即走"误判为健康
  ↑ DAU 拆看板/对话两类——看板=被动消费数据，对话=主动要结论，使用深度不同
  ↑ DAU 要健康需要：① 人来（拉新+留存）② 人待得住（在线时长）③ 人用得深（不只是看，还要产出结论）
  ↓
产品层：周成功交付结论数（被采纳未点踩的结论绝对量）
  ↑ 为什么"被采纳结论"是 DAU 的质量维度？光有人来用不够——来的用户得拿到有价值结论才会持续用
  ↑ "被采纳"=结论进入 PM 判断体系=使用价值兑现 → 兑现多 → DAU 留得住
  ↑ "未点踩"过滤编造结论（采纳假结论会反噬留存）
  ↑ "绝对量非比率"——40人工具，规模是第一位，比率看不出深度
  ↑ "成功交付"依赖 agent 质量 → 需要质量指标驱动
  ↓
输入层：Pass¹×(1−幻觉率)÷单次成本 + WAU + 人均结论数 + 采纳率 + 响应时延
  ↑ Pass¹×(1−幻觉率)÷成本 = 单位成本能拿到多少正确结论（效率+质量合一）
  ↑ WAU/人均结论数 = 使用深度（喂 DAU 的质 + 产品北极星的量）
  ↑ 采纳率 = 结论可信度（喂产品北极星的质 → 反哺 DAU 留存）
  ↑ 响应时延 = 使用体验（直接影响 DAU 留存）
```

**四个关键推导节点**（重写）：
1. **商业=DAU + 在线时长**：内部工具价值=融入日常工作流，"每天在用"=存活最直接信号；可日度量、可设阈值，比"有效决策数"可操作得多。2026-10-06 补"在线时长"——DAU 量广度（来没来）、在线时长量厚度（待多久），单看 DAU 会把"打开即走"误判为健康，两者合看才是完整存续信号。
2. **商业←产品**：DAU 健康需要"来的人用得深、拿到有价值结论"——周成功交付结论数是 DAU 的质量维度（结论兑现价值→用户留存→DAU 稳住）。
3. **产品←输入**："成功交付"依赖 agent 质量，输入指标度量并驱动质量迭代。
4. **绝对量←比率**：40 人内部工具，规模是第一位，比率看不出使用深度。

**产品北极星定义**：一周内 agent/看板产出的、被用户采纳（未点踩、未撤销）的结论数量。看板和 agent 双模式都计入。绝对量非比率——40 人工具型产品，用的人多不多是第一位，比率看不出使用深度。同时绑采纳和价值——"被采纳"过滤编造结论，"结论数"绑定使用深度。

**过渡方案**：产品北极星起步度量成本高（什么算"一条结论""被采纳"需定义），可先用"周活 × 平均结论采纳率"过渡，跑通后升级到绝对量。DAU 起步即可直接埋点（页面打开/对话发起事件）。

**成本分母修正**：原"÷单次成本"在小规模时担心成本可忽略致分母无区分度；上线后 API 费用随使用量上升，成本分母有区分度，保留在输入指标层。

---

## 10. 0→N managing 专题研究清单（每项在对应阶段做专题研究）

> **定位（2026-09-08 修正）**：这不是"为面试准备的材料清单"，而是**七个真实工作专题**——每个都要在对应阶段认真做专题研究，面试叙事只是副产品。

| # | 专题 | 阶段 | 状态 / 落点 |
|---|------|------|------------|
| 1 | 产品逻辑：架构设计 + 技术方案选型 + 产品逻辑 | 起步期，持续演进 | ✅ 进行中：提纲 §1–§5 即本专题的持续产出 |
| 2 | agent 的评测与迭代 | MVP 后落地 | ✅ 已设计（§8）；评估 v0 落地时做本专题 |
| 3 | agent 方案对比 | 选型期 + 事后复盘 | ✅ 第一轮已完成（§5.2 harness 六候选对比）；假设变化（换底座/换形态）时复盘 |
| 4 | 不同模型在 agent 上的表现 → 选最佳模型 | 评估 v0 之后 | ⏳ 待启动：model swap 起步（v4-flash vs v4-pro），跑 §8 评估集，可扩 GLM / Qwen 等 |
| 5 | 功能说明与演示（manus 早期式宣发） | MVP 跑通后 | ⏳ 待启动 |
| 6 | 落地后的用户运营与反馈 + 埋点 | 上线后 | ✅ 闭环已设计（§8.6 三路信号）；届时做运营专题 |
| 7 | 项目反思与复盘 | 每个大节点收尾 + 项目总结 | 贯穿：每阶段写复盘（本提纲的更新记录即雏形） |

---

## 11. 进度与下一步（2026-09-08 更新）

**phase3-convergence change（2026-10-06，十步流程走完归档）：**
- 红线机制化：completion.ts 移植（行ID查库+越界+缺口+max1 continuation）+ grounding verifyNames（8 名称错误拦截）+ fail-closed 未知业务工具（24 工具白名单）
- 红线#7 身份核验：resolve_series 强制前置（before_agent_start fetch /identity/resolve，未命中 fail-closed）+ series_key 全链路（前端→FastAPI→gateway 拼 prompt 前缀→extension 解析）
- 观测层：verdict.json（按 sessionId 分目录）+ mapEvent verdict 事件 + trajectories.jsonl（badcase 回放）+ /attribution 五维归因
- 北极星可算：/events + SQLite 事件库 + /events/stats（DAU/周结论/反馈）+ 前端 tracker（sendBeacon 30s 心跳 + 点踩按钮）
- 评测门禁：runner 读 trajectories verdict 评分（非正则）+ CI 骨架（发版门槛 veto零+通过率≥70%）+ 单测 4 模块 + 动态评测集（badcase 自动转题）
- M3 补漏：/health 就绪探针 + 进程崩溃 respawn + /ui-response 转发 + 鉴权中间件 + 密钥移出源码 + 可配超时 + exclude-tools 补全 + scope setActiveTools
- Step7 code-review 修 6 红线 bug：runner 重复 import / tracker 脱敏被覆盖 / verdict 路径错 / series_key 不传对话 / identity fail-OPEN / retry 不流客户端 / sales_trim+config_snapshots 列名错
- 详见 `openspec/changes/phase3-convergence/`（explore/proposal/design/specs×7/tasks/self-check/review-response/verification/archive）

**已完成：**
- ✅ pi 0.85.1 就位（`pi-windows-x64/pi.exe`）
- ✅ **DeepSeek 配通**（2026-09-08）：内置 provider，key 已入 `~/.pi/agent/auth.json`（无需写扩展，原计划第 1 步作废）；模型 **`deepseek-v4-flash`**（1M 上下文 / 384K 输出 / 思考模式 / 工具调用；¥1/M 输入、¥2/M 输出、缓存命中 ¥0.02/M）；`pi -p` 冒烟测试通过。TUI 内 `/model` 选定后 **Ctrl+S** 存为启动默认。
- ✅ 表现层双模式定稿（§2）
- ✅ 社区包三个已装并实测（§5.6）：pi-web-access（搜索可用）/ pi-mcp-adapter（待护栏验证）/ pi-subagents（备用）
- ✅ 评估与迭代体系设计定稿（§8）：Pass^k + 幻觉 veto + 两层回归 + 用户反馈闭环
- ✅ **部署/并发/认证/北极星四项拍板**：阿里云 + **峰值并发 40 单机起步**（2026-10-01 修正，原 50-100 多实例方案降级为远期扩展项，§5.7）；无登录 + 本地 ID（§9.2）；**北极星三层·商业北极星=DAU（看板/对话分开，2026-10-02 改）+ 在线时长（活跃时长，2026-10-06 增列）**（§9.8）；DeepSeek flash 2500 并发够用（§5.7）；E5 三维数据实测落地（工作⓪，2026-10-02 复审重核）。

**下一步：**
1. **工作⓪ E5 端到端案例**（立即开跑·纯 Python 直读 SQLite·不被任何 gate 阻塞）：跑通 E5 三维度（**2026-10-02 复审重核**：销量 sales_trim 286 行 + sales_series_weighted 20 行 / 配置 config_snapshots version=5 / 口碑 owner_reviews 1274 条 + review_tags 3235 标签；车系锚点 `银河E5` 防重名禁 LIKE '%E5%'）→ markdown 报告（每个数字带数据源行 ID + as_of）。这是第一行 Prism 代码、第一份交付物。配置维度补赋分体系对接，销量维度核 sales_trim 口径来源（CAM vs 之家）+ 统一两表 month 粒度/品牌命名。
2. **阶段3 上线基建**（云单机倒推·提前成独立块）：会话状态 Redis（建议上，非阻塞）/内存会话+落盘快照 + 生产库读写分离 + API key KMS/加密环境变量 + 本地 ID 体系 + 管理者弹密码 + badcase 轨迹埋点 + 轻量监控。详见八项工作稿阶段3。
3. **harness spike**（§5.4）：TS 语义工具直读库（不走 MCP 桥，已退役）；`pi.on("tool_call")` 护栏；40 并发验证。
4. **拍板剩余 §9 待定项**：BI 看板技术（基于供给端 v11 现状）、销量录入方式。
