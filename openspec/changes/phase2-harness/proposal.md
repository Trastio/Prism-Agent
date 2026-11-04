# Proposal · 阶段2 核心Harness与语义工具

> Prism-Agent 开发流程十步骤 · Step 2 propose
> 日期：2026-10-03
> 范围：阶段2「核心 harness 与语义工具」（任务清单 D2.1–D2.4，19 待办 + 阶段1 复审新增 2 项 = 21 项）
> 上游输入：`explore.md`（2026-10-03 更新版，含阶段1 两轮复审教训）

---

## 一、为什么要做（WHY）

阶段1 用三份手工报告证明了"PM 想要什么结论"以及"哪里会翻车"。两轮复审打中两类系统性根因：

1. **数据真实性红线#1 在手工阶段就守不住**：报告① 销量年份错位（整条 2026 序列实为 2025 数据）、报告② 口碑表续航/舒适整行互换 + 用纯电跌论证增程归因（自相矛盾）、报告③ 把对象查错（铂智7X 当铂智7、形态判错、厂商错）。**8 个名称错误（含形态/厂商/品牌）**，全是人工转写出错。
2. **对象身份不前置核验**：报告③ v1 脑补"用户称7X、库里叫7"的对齐关系，根本没核验。联网核实才发现铂智7X=铂智7 同车两名，但形态/厂商/排位全错。

**结论**：靠人盯守不住红线#1，必须靠 harness 机制化。阶段2 要把这些教训固化成**执行层护栏 + 验证层拦截 + 评估层闭环**，让 agent 跑出来的报告天然带这些纪律，而不是靠 prompt 劝说。

---

## 二、做什么（WHAT）

**三大支柱**（后端红线 + 评估闭环 + 前端pi集成），七层 spec，43 项交付：

### 支柱一：后端红线（agent 能跑对报告）
| 层 | spec | 项 | 核心交付 |
|---|---|---|---|
| 2.1 提示词与上下文 | prompt-context.md | 3 | AGENTS.md + SYSTEM.md + 状态栏 hook + D3 标记 + 数据缺口假设范式 |
| 2.2 工具接口【红线核心】 | tool-interface.md | 6 | 数据源注册表 + 对象身份映射层 + 口径视图 + 3核心语义工具 + tool_call 护栏 + tool_result grounding（数值+名称） |
| 2.3 验证【红线#1】 | verification.md | 4 | grounding 移植 + 完成验证器 + 口碑定性结论 + 真值校验 |

### 支柱二：评估闭环（能量化 agent 好不好）
| 层 | spec | 项 | 核心交付 |
|---|---|---|---|
| 2.4 评估体系 | evaluation.md | 7 | 评估任务集 + 六分制 + 统计栈 + 批跑 + EVAL_STATUS + 双评委 + langfuse 闭环 |

### 支柱三：前端 + pi 集成（Web 站可交互）
| 层 | spec | 项 | 核心交付 |
|---|---|---|---|
| 2.5a 前端 UI 设计 | frontend-ui.md | — | brand-spec + HTML 稿布局 + 四看板字段对齐 + 模式切换（视觉契约） |
| 2.5 前端工程 | frontend.md | 11 | Web 骨架 + 三栏 Shell + 对话区 + 看板实现 + 报告预览 |
| 2.5b pi 集成 | pi-integration.md | 11 | FastAPI 网关 + pi SDK 桥 + SSE 流式 + scope 锁定 + Redis 会话 + 状态栏 WS + langfuse 埋点 |

**关键产出**：
- 后端：golden case（E5/零跑D19/铂智7X）跑通，trap 100% 被否决，名称错误 100% 被 grounding 拦截。
- 前端：输入"分析银河E5" → BI 看板/Agent 对话双模式 + 流式响应 + 看板实时联动 + 报告预览。
- 集成：SSE 流式 + scope 锁定 + 多实例 Redis 会话 + 验证器结果前端可见。

---

## 三、关键决策（已拍板，详见 design.md）

| # | 决策点 | 方案 |
|---|---|---|
| ① | 口径视图落法 | 运行时聚合 SQL + 物化视图表（混合） |
| ② | 对象身份映射层 + 覆盖率守卫 | 2.2 前置组件（原 D3 升级） |
| ③ | TS 语义工具 schema + expected_* | 3 常驻 + discover_tools 按需 + 名称字段强制库源落地 + 名称维度阈值 |
| ④ | 完成验证器汽车场景化 | CLAIM/VERIFY = 结论+supported_by行ID+as_of+越界检查 |
| ⑤ | 评估集框架 | 30-50题（销10/配8/口10/舆6/跨10）+ 6 trap，我出模板你填问题 |
| ⑥ | langfuse 评估断链 | 评估批跑不禁 langfuse（`--mode json` 非 `--no-extensions`），trace 单独打标 |
| ⑦ | spec 拆分 | 5 spec 文件对应五层，依赖：tool-interface←prompt-context；verification←tool-interface；evaluation←前三者；frontend←2.2 口径视图 |
| ⑧ | **前端主视图形态** | 对话为中心 + 看板侧边预览（参考 Hermes 三栏：左 sidebar / 中对话 / 右预览） |
| ⑨ | **前端运行形态** | Web 站（阿里云部署，无登录，浏览器本地 ID；非 Electron） |
| ⑩ | **前端技术栈** | React 19 + shadcn/ui(new-york) + Tailwind v4 + assistant-ui + ECharts + Radix + TanStack Query + Vite |
| ⑪ | **四个看板落法** | 右侧预览面板的可切换 tab；口碑/市场/配置读 Prism 口径视图，舆情嵌套舆情 Board |

---

## 四、影响范围

**新建**：
- `openspec/changes/phase2-harness/`：proposal.md / design.md / specs/*.md / tasks.md（本变更）
- 项目根：`AGENTS.md` + `SYSTEM.md`（pi 提示词层）
- `src/`（TS 语义工具 + 对象身份映射 + 口径视图 + grounding + 完成验证器）
- `prism-web/`（前端 React 站，Vite + shadcn）
- `prism-api/`（FastAPI 网关 + pi SDK 桥）
- `eval/`（评估集 + 批跑脚本 + 统计栈）

**不动**：
- `e5_report.py`（Python 原型保留作翻译参考，已知 v0.2 bug 不修，以报告 v0.3 真实序列为准翻译 TS）
- Atuohome_Agent / 舆情 Board 源项目内部（黑盒供给端，只接插座不进内部）
- pi-mcp-adapter（已退役留参考，TS 工具直读库）

**依赖外部**：
- 你写 30-50 评估问题（关键路径瓶颈，AI 写会偷工减料——阶段1 D19 口碑互换错误是实证）
- Hermes UI 作为参考样本（`C:\Users\<you>\AppData\Local\hermes\hermes-agent\apps\desktop\`，只读参考不搬代码）

---

## 五、风险与缓解

1. **口径视图是最大阻塞**：TS 工具/grounding/评估集都依赖它。缓解：阶段1 已趟清 10 个口径坑，可直接落 SQL；物化视图表先建最小集（车系×维度×极性聚合）。
2. **对象身份映射需联网**：非主流车系（铂智7X）库源不收录时需联网核验，引入 web-access 依赖与延迟。缓解：仅当 `series_alias` 未命中或覆盖率守卫报告缺失时触发联网，常规车系走库内映射。
3. **3.5 自查收敛**：之前跳过导致子代理执行时方法签名丢失/测试假阳性。本步 propose 写完后即进入 3.5 自查（每层 spec 反复审查到无新问题）再交付 Step5。
4. **评估问题用户写瓶颈**：30-50 题卡你时间。缓解：我出模板框架 + 维度分配 + trap 设计，你只需填问题主干。
5. **langfuse self-host 合规**：评估闭环依赖 langfuse，自建部署有合规成本。缓解：开发期用 langfuse cloud 免费额度，上线前评估迁移。
6. **前端与后端并行耦合**：前端对话区依赖 pi SDK 桥（2.5.10）就绪才能联调，但 API 网关又依赖 TS 工具（2.2.3）。缓解：M1 完成即启动前端 Shell + 静态看板（读口径视图），对话联调等 M2。
7. **舆情 Board 嵌套上云风险**：舆情服务无鉴权 + 127.0.0.1 + CORS 本机，开发期 iframe 嵌入可行，上线需 sidecar 或自绘。缓解：开发期 iframe，上线期改 Prism 自绘 ECharts 读舆情 REST。
8. **Hermes UI 照搬误区**：Hermes 是 Electron 通用 agent，Prism 是 Web 数据看板产品，直接抄会带入不需要的复杂度（多 pane 分割/文件浏览器/voice）。缓解：只参考三栏布局 + shadcn 栈 + assistant-ui，砍掉 Hermes 的桌面专属功能（见 frontend spec 末尾差异表）。

---

## 六、验收标准

阶段2 完成 = 满足以下全部：
1. **三份 golden case 跑通**：E5/零跑D19/铂智7X 在评估系统批跑出分数，验证器分数 + 失败维度 + 成本写回 trace。
2. **红线#1 验收**：trap 任务 100% 被否决；名称张冠李戴类错误 100% 被 grounding 拦截（用阶段1 复审的 8 个名称错误做测试集）。
3. **对象身份映射验收**：输入"铂智7X"能正确映射到 `series='铂智7'` + 报告覆盖情况；输入不存在车系能 fail-closed。
4. **报告纪律六条机制化**：每条数字带可复算 SQL、口径逐维 as_of、结论不越界、数据缺口假设清单、分层规则、对象身份前置核验——全部由 harness 强制而非 prompt 劝说。
5. **统计栈完整**：McNemar + Wilcoxon + Cliff's delta + bootstrap CI 四个脚本可运行，发版门槛 4 条件可计算。
6. **前端验收**：输入"分析银河E5" → 流式对话 + 右侧口碑看板自动切 + 销量数据实时显示；四个看板可手动切换；报告 md 可预览下载；浏览器本地 ID 生效。

---

## 七、不做（边界）

- 不做后训练 / 语音 / ComputerUse / 多agent辩论 / 裸SQL Artifact 模式（提纲§9 待定项排除）
- 不做 K8s / Vault / canary / 10道发布门（单机+SQLite+49人读不需要，2026-09-30 已砍）
- 不做登录系统（2026-09-30 拍板，浏览器本地ID）
- 不改源项目内部（Atuohome/舆情黑盒供给端）
- 不修 e5_report.py（保留作翻译参考）
