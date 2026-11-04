# Spec · 2.4 评估体系 v1

> 阶段2 · 7 待办
> 依赖：`prompt-context.md` + `tool-interface.md` + `verification.md`
> 关键瓶颈：30-50 评估问题必须用户写

---

## 待办清单

| ID | 待办 | 优先级 | 依赖 |
|---|---|---|---|
| 2.4.1 | 评估任务集 v1（30-50 题 + 6 trap） | P0 | 2.3.2 |
| 2.4.2 | 六分制评分器（销量/配置数值容差） | P0 | 2.4.1 |
| 2.4.3 | 统计栈（McNemar + Wilcoxon + Cliff's delta + bootstrap CI） | P1 | 2.4.2 |
| 2.4.4 | 批跑环境（pi -p --mode json + 快照库 + 成本4维度） | P0 | 2.4.1 |
| 2.4.5 | EVAL_STATUS.md 门禁台账（人工周审） | P1 | 2.4.4 |
| 2.4.6 | 双评委（GLM/Kimi 与 DeepSeek 异源） | P1 | 2.4.2 |
| 2.4.7 | langfuse 闭环（分数+失败维度+成本写回 trace） | P0 | 2.4.4 |

---

## 2.4.1 评估任务集

### 题量分配（决策⑤）
| 维度 | 题数 | 类型 |
|---|---|---|
| 销量 | 10 | 月度/同比/环比/版型结构/终端价 |
| 配置 | 8 | 版型对比/年款/赋分/缺失项 |
| 口碑 | 10 | 维度聚合/原文溯源/覆盖率 |
| 舆情 | 6 | 数据缺口占位（验范式） |
| 跨维度 | 10 | 棱镜三维度交叉（E5/零跑/铂智 golden） |

### trap 任务（6 个，基于阶段1 复审错误）
1. 诱导"探索型"（应探索版）→ 名称 grounding 拦截
2. 诱导"半月合并"（应只取月末）→ 口径 grounding 拦截
3. 诱导"市场侧归因产品力" → 完成验证器越界检查
4. 诱导"铂智7X 当另一车" → 对象身份映射拦截
5. 诱导"口碑结论不附 supported_by" → 完成验证器拦截
6. 诱导"数据缺口硬下结论" → 数据缺口假设范式拦截

### 分工（Gap 5 明确）
| 题 类 | 数量 | 负责 |
|---|---|---|
| 跨维度 10 题 | 10 | **我转**（基于 E5/零跑D19/铂智7X 三份 golden case） |
| 销量 10 题 | 10 | **你写** |
| 配置 8 题 | 8 | **你写** |
| 口碑 10 题 | 10 | **你写** |
| 舆情 6 题 | 6 | **你写**（数据缺口占位，验范式） |
| trap 6 题 | 6 | 我写（基于阶段1 8 个错误） |

我出模板框架 + 跨维度 10 题 + 6 trap；你填 34 题主干（销量/配置/口碑/舆情）。AI 写会偷工减料——阶段1 D19 口碑互换错误是实证。

### 模板（你填问题主干）
```
question: <PM 真实业务问题>
expected_conclusion_shape: <结论应有的形态>
expected_evidence: <supported_by 行 ID 类型>
trap_type?: <6 类之一>
as_of: <数据时点>
```

### 验收
- 30-50 题就位（我 16 + 你 34）
- 6 trap 100% 被否决
- 跨维度 10 题基于三份 golden case 可复现

---

## 2.4.2 六分制评分器

### 设计
只管销量/配置（数值容差），口碑走 2.3.3 单独一套。
- 0-5 分：5=完全正确 / 4=数值小误差 / 3=口径错 / 2=缺证据 / 1=越界 / 0=编造
- 容差：销量±2%，配置 0 容差

### 验收
- E5 销量题评分可计算
- 越界/编造自动 0-1 分

---

## 2.4.3 统计栈

### 设计（3 个自补项，教材无）
- **McNemar**：二元 veto（trap 是否被否决）
- **Wilcoxon 符号秩**：六分制连续分数（教材只有 McNemar 二值）
- **Cliff's delta**：效应量（教材无）
- **bootstrap CI**：各维度 95% 区间

发版门槛 4 条件：veto 零命中 + Wilcoxon 显著且 delta>0.1 + 保留集 CI 下界>0 + 成本 CI 上界<预算。

### 验收
- 4 脚本可运行
- 发版门槛可计算

---

## 2.4.4 批跑环境

### 设计（决策⑥）
- `pi -p --mode json`（不禁 extensions，护栏保持开启）
- 快照库：每题跑前快照 autohome.db（immutable=1 只读）
- 成本 4 维度：input_tokens / output_tokens / cache_hit / elapsed
- trace 打 `eval_run_id` 便于回放

### 验收
- 30-50 题可批跑
- 成本 4 维度记录
- 护栏在评估场景开启

---

## 2.4.5 EVAL_STATUS.md 门禁台账

人工周审，记每次批跑：通过率 / 失败维度 / 是否过发版门槛。

---

## 2.4.6 双评委

GLM/Kimi 与 DeepSeek 异源（教材判据：judge 与 agent 异源）。
- agent = DeepSeek deepseek-v4-flash
- 评委 = GLM + Kimi
- 评委评分与 agent 自评做差异分析

---

## 2.4.7 langfuse 闭环

### 设计
- 已核实：`@langfuse/pi-observability-plugin@0.1.2` hook `tool_execution_start/end`，自建工具全覆盖
- 写回 trace：验证器分数 + 失败维度 + 成本4维度 + trap 是否被否决 + 名称拦截是否触发
- 评估批跑不禁 langfuse（决策⑥）
- 北极星看 langfuse dashboard

### 验收
- 三份 golden case 跑通，分数写回 trace
- langfuse dashboard 可查失败维度分布
