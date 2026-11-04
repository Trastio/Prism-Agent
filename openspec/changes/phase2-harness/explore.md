# 阶段 2 · explore 探索报告

> Prism-Agent 开发流程十步骤 · Step 1 explore
> 日期：2026-10-02
> 范围：阶段 2「核心 harness 与语义工具」（任务清单 D2.1–D2.4，19 个待办）
> 目的：探索现状、识别缺口与依赖、定位可并行任务，为 Step 2 propose 提供 input。

---

## 一、阶段 2 要建什么（WHAT 的轮廓）

阶段 2 是 Prism 的"灵魂注入"——把 pi 的空壳 + Atuohome 的数据 + 棱镜理论拼成可运行的 agent。19 个待办分四层：

| 子层 | 待办数 | 核心交付 | pi 提供 / 自建 / 不建 |
|---|---|---|---|
| 2.1 提示词与上下文层 | 3 | AGENTS.md + SYSTEM.md + 状态栏 hook + D3 来源标记 | 自建（pi 提供 hook 机制） |
| 2.2 工具接口层【红线核心】 | 5 | 数据源注册表 + 口径视图 + 3 核心语义工具 + tool_call 护栏 + tool_result grounding | 自建（pi 提供 registerTool + on hook） |
| 2.3 验证层【红线#1】 | 4 | grounding 移植 + 完成验证器 + 口碑定性结论单独一套 + 真值校验 | 完全自建（pi 没有） |
| 2.4 评估体系 v1 | 7 | 评估任务集 + 六分制评分器 + 统计栈 + 批跑环境 + EVAL_STATUS + 双评委 + langfuse 闭环 | 自建批跑脚本（pi 提供 `pi -p --mode json`） |

**关键产出**：golden case（E5）在评估系统跑通，trap 任务 100% 被否决（红线验收）。

---

## 二、现状盘点（已有资产 vs 缺口）

### 2.1 提示词与上下文层

| 项 | 现状 | 缺口 |
|---|---|---|
| AGENTS.md / SYSTEM.md | ❌ 不存在（工作⓪ 故意不建） | 需写棱镜 SOP：`<prism_dimensions>` + `<red_lines>` + `<sop>`，两层提示词（全局锁 SOP / 会话锁快照），分层规则（不跳步 vs 双向交叉验证），`before_agent_start` 动态注入 |
| 状态栏 hook | ❌ 不存在 | 需建 SystemState 模式：当前车型 / 三维度完成度 / 工具调用计数(≥3告警) / 剩余 token / max_iterations 硬闸门。教材有照抄片段：`文档/教材学习笔记.md` §3.2 chapter2/system-hint/agent.py:858-862 |
| D3 来源标记 | ❌ 不存在 | 口碑/销量/配置全包 `<external_content source>` |
| 3 个 skill | ❌ 不存在 | config/decision/market/koubei 复用 Atuohome Skills 文本但不搬代码 |

### 2.2 工具接口层

| 项 | 现状 | 缺口 |
|---|---|---|
| 数据源注册表 | ❌ 不存在 | 连接方式 / as_of / 覆盖率守卫 / 健康状态，RAG 预留第四口 |
| 口径视图 v1 | ❌ 不存在 | 车系×维度×极性聚合 + n 随行。BI 与 agent 共用。**工作⓪ 已验口径坑**：两表 month 粒度/品牌命名不一致、retail 50% 缺失、sentiment=pro/con、owner_reviews 无 series_id |
| TS 语义工具直读库 | ❌ 不存在 | 3 核心常驻 query_config/reviews/sales + discover_tools 按需 + 6 个 sentiment_*（舆情外挂第四组）。typebox schema + expected_* 自查。**工作⓪ e5_report.py 已是 Python 原型，可作 TS 翻译参考** |
| tool_call 护栏 | ❌ 不存在 | cc-safety-net 已装（全局）+ 自建红线拦截（fail-closed）。教材 §3.4 chapter5/airline_env.py 三重保障照抄 |
| tool_result 改写（grounding） | ❌ 不存在 | 分维度配阈值。教材 §3.1 chapter1/grounding.py 照抄（QUANTITY_FLOOR=1000，_SCALES 加"万/亿"） |

### 2.3 验证层

| 项 | 现状 | 缺口 |
|---|---|---|
| grounding.py 移植 | ❌ 不存在 | 接 tool_result hook，销量/配置数值维度。教材 §3.1 直接搬 |
| 完成验证器 | ❌ 不存在 | `agent_settled` 事件插验收核对（注意官方名非 `agent_before_settle`）。CLAIM_PATTERNS/VERIFY_PATTERNS 改汽车场景。max 1 次 continuation 再不过 fail。教材 §3.5 chapter8/premature-completion-dpo |
| 口碑定性结论单独一套 | ❌ 不存在 | claim 溯源(supported_by 行ID) + 人工抽检（六分制对口碑失效） |
| 真值校验 | ❌ 不存在 | 纯 Python 多重集容差比对（reference.py 模式） |

### 2.4 评估体系 v1

| 项 | 现状 | 缺口 |
|---|---|---|
| 评估任务集 v1 | ❌ 不存在 | E5 golden case 扩展 + 参数化模板 + trap 任务。**30-50 问题必须用户写**（AI 偷工减料）。工作⓪ 报告可直接转 golden case |
| 六分制评分器 | ❌ 不存在 | 只管销量/配置（数值容差） |
| 完整统计栈 | ❌ 不存在 | McNemar + Wilcoxon + Cliff's delta + bootstrap CI（3 个自补项，教材无） |
| 批跑环境 | ❌ 不存在 | `pi -p --mode json` + 快照库 + 成本 4 维度记录 |
| EVAL_STATUS.md 门禁台账 | ❌ 不存在 | 人工周审 |
| 双评委 | ❌ 不存在 | GLM/Kimi 与 DeepSeek 异源 |
| langfuse 评估闭环 | 🟡 插件已装+核实 | 验证器分数+失败维度+成本写回 trace。**已核实**：hook tool_execution_start/end，自建工具全覆盖，trace 含参数/返回值/usage/耗时。待解：评估场景 `--no-extensions` 断链 + self-host 部署合规 |

---

## 三、依赖关系（关键路径）

```
2.2.1 数据源注册表 ─┐
2.2.2 口径视图 v1 ──┼─→ 2.2.3 TS 语义工具 ─→ 2.3.1 grounding ─→ 2.3.2 完成验证器
                    │                                          ↓
2.1.1 AGENTS.md ────┼─────────────────────────────────→ 2.4.1 评估任务集 ─→ 2.4.2 评分器 ─→ 2.4.3 统计栈
2.1.2 状态栏 hook ──┘                                                                      ↓
2.1.3 D3 来源标记                                                       2.4.4 批跑环境 ─→ 2.4.7 langfuse 闭环
                                                                                    ↓
                                                                        2.4.5 EVAL_STATUS + 2.4.6 双评委
```

**关键路径**：数据源注册表 → 口径视图 → TS 语义工具 → 评估任务集 → 批跑 → langfuse 闭环

**阻塞点**：
- **2.2.2 口径视图** 是最大阻塞——TS 工具、grounding、评估集都依赖它。工作⓪ 已趟清口径坑，可直接落 SQL。
- **2.4.1 评估任务集** 卡在"30-50 问题用户写"——AI 写会偷工减料，必须你写。这是阶段 2 的关键路径瓶颈。

---

## 四、可并行任务

并行簇 1（提示词侧，可同时进行）：
- 2.1.1 AGENTS.md（我写）
- 2.1.2 状态栏 hook（我写）
- 2.4.1 评估任务集**问题部分**（你写 30-50 题，我出模板框架）

并行簇 2（工具侧，依赖口径视图）：
- 2.2.3 TS 语义工具 query_config（我）
- 2.2.3 TS 语义工具 query_reviews（我）
- 2.2.3 TS 语义工具 query_sales（我）
- 6 个 sentiment_* 工具（我）

并行簇 3（验证侧，依赖工具就位）：
- 2.3.1 grounding（我）
- 2.3.2 完成验证器（我）
- 2.3.3 口碑定性结论（我）
- 2.3.4 真值校验（我）

---

## 五、风险与待解

1. **3.5 自查收敛（Step 4）**：之前跳过导致子代理执行时方法签名丢失、测试假阳性。本次必须做——每层 spec 写完后反复审查到无新问题。
2. **口径视图是 SQL 落库还是运行时计算？** 设计稿说"放 Prism 侧"，但具体是建物化视图表 / 运行时聚合 SQL / 还是 TS 工具内聚合？需 Step 2 propose 拍板。
3. **TS 语义工具的 expected_* 怎么写？** 教材三重保障之一是"工具描述带 expected_* 自查"，但具体 schema 要 Step 2 设计。
4. **完成验证器的 CLAIM_PATTERNS 汽车场景化**：教材是代码生成场景（approve_code 信号），汽车场景要改成"结论+证据行ID+as_of"校验，需 Step 2 设计。
5. **评估集 30-50 问题分配**：销量/配置/口碑/舆情/跨维度各多少题？trap 任务设计？需 Step 2 拍板框架，你填问题。
6. **langfuse 评估场景断链**：`--no-extensions` 会禁掉 langfuse。解法：评估批跑不禁 langfuse，或单独开 trace。Step 2 决定。
7. **两项目服务无鉴权 + 127.0.0.1**：开发期可在本地跑，上线才需改造。阶段 2 先用本地 Atuohome（127.0.0.1:8001）+ 舆情（127.0.0.1:8000）。

---

## 六、与阶段1 三份报告的衔接（2026-10-03 更新）

阶段1 产出三份报告样本（`工作⓪-E5端到端/Prism-Agent-阶段1报告样本合订本.md`）+ 两轮复审，可复用资产已扩容：

- **e5_report.py**：Python 原型，TS 语义工具翻译参考（取数逻辑/口径统一/证据溯源）。⚠️ v0.2 销量硬编码+年份错位 bug 未修，翻译 TS 时**以报告 v0.3 的真实序列为准，不以脚本为准**。
- **三份 golden case**：E5（产品力诊断）+ 零跑D19（销量异动归因）+ 铂智7X（数据缺口假设输出），覆盖三种典型场景，可转评估集。
- **口径坑清单扩容**（v0.2 的 6 个 + v0.3 新增）：
  - sentiment=pro/con（非 1/0/-1）
  - 两表 month 粒度/品牌命名不一致（sales_trim brand='银河' vs weighted brand='吉利'）
  - **`X月中`行=价格快照 retail 全 NULL（非缺失）；`X月末`行=整月零售**——不存在"半月销量"
  - **整条 2026 序列曾因 month 丢年分组错位成 2025 数据**——必须按 year+month 分组
  - owner_reviews 无 series_id（用 model_id）
  - config categories 嵌套 dict（spec_id≠model_code）
  - **config_snapshots 含 2024/2026/2027 三年款 12 版型，不能当"当前在售"**
  - **`sales_trim` 实际只有 24款/26款两个年款**，2027款只在 config_snapshots（两套口径不可混）
  - **版型名末字是"版"非"型"**（探索版非探索型，LIKE '%探索型%' 返回 0 行）
  - **打标覆盖率 E5=92.5%、D19=90.8%**（非记忆里全库旧数据 22%）
- **赋分链路**已验：A1/B1 通过 concept_configs.json tiers 计算

### 阶段1 两轮复审的新教训（必须进阶段2 设计）

1. **对象身份映射层（新增 P0 设计项）**：报告③ v1 把"铂智7X"当"铂智7"查、脑补对齐关系，根因是没前置核验对象身份。阶段2 必须建**对象身份映射层**：
   - 用户输入车系名 → 查 `series_alias` + 联网核验 → 确认唯一 series_key → 再分析
   - 非主流车系（铂智7X/铂智7）`series_summaries` 不收录、口碑 0 条 → **覆盖率守卫**：分析前先报告"该对象在数据底座的覆盖情况"，缺数据主动声明
   - 这条原属 D3 数据源注册表，**升级为 2.2 工具接口层的前置组件**
2. **名称字段禁止人工转写（红线#1 方法论）**：两轮复审共发现 8 个名称错误（含形态/厂商/品牌）（探索型/全域精灵版/铂智7SUV/星纪元ET08/蔚来Z9/智驾版），全是人工转写出错。阶段2 agent 必须：**名称字段直接从库/官方源落地，禁止模型生成或人工转写**。这是 harness 验证层（tool_result 改写 grounding）要拦的——名称维度配阈值，模型输出名与库源名不一致即 fail-closed。
3. **数据缺口下假设清单范式**：报告③ 是阶段1 第三类样本——数据不全时输出"假设+证据强度+缺什么能坐实"，不硬下结论也不干脆不答。阶段2 system prompt 要内化这套范式。
4. **报告纪律六条**（已固化，阶段2 system prompt 素材）：每个数字带可复算SQL / 口径逐维声明as_of / 结论不越界 / 数据缺口如实标注+证据强度 / 分层规则 / 对象身份前置核验。

---

## 七、explore 结论

阶段 2 是 19 个待办的大变更，分四层，关键路径=口径视图→语义工具→评估集→批跑→langfuse。最大瓶颈是"30-50 评估问题必须用户写"。阶段1 三份报告已为工具层和评估层铺好底（Python 原型 + 3 个 golden case + 口径坑清单扩容 + 对象身份映射/名称禁转写两条新设计项）。

**两轮复审触发的 explore 增补**：
- 2.2 工具接口层新增前置组件：**对象身份映射层 + 覆盖率守卫**（原 D3 升级到 2.2）
- 2.3 验证层 grounding 扩展：**名称维度配阈值**（不只数值维度）
- 2.1 提示词层补：**数据缺口假设清单范式**写进 SYSTEM.md

**下一步 Step 2 propose**：产出 proposal.md + design.md + specs/*.md + tasks.md，覆盖：
1. 口径视图落法（物化视图 vs 运行时聚合）
2. **对象身份映射层 + 覆盖率守卫**（新增，原 D3 升级到 2.2 前置）
3. TS 语义工具 schema + expected_* 设计（名称字段落地策略）
4. 完成验证器汽车场景化的 CLAIM/VERIFY 模式
5. 评估集框架（题量分配 + trap 设计 + 你写问题的模板）
6. langfuse 评估场景断链解法
7. 四层的 spec 与 tasks 拆分（含依赖标记）
