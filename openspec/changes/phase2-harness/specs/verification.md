# Spec · 2.3 验证层【红线#1】

> 阶段2 · 4 待办
> 依赖：`tool-interface.md`（2.2，尤其 2.2.5 grounding）
> 被依赖：`evaluation.md`

---

## 待办清单

| ID | 待办 | 优先级 | 依赖 |
|---|---|---|---|
| 2.3.1 | grounding.py 移植（数值 + 名称） | P0 | 2.2.5 |
| 2.3.2 | 完成验证器（agent_settled，CLAIM/VERIFY 汽车场景化） | P0 | 2.2.3 |
| 2.3.3 | 口碑定性结论单独一套（claim 溯源 + 人工抽检） | P0 | 2.3.2 |
| 2.3.4 | 真值校验（纯 Python 多重集容差比对） | P1 | 2.3.1 |

---

## 2.3.1 grounding.py 移植

### 设计
教材 §3.1 chapter1/grounding.py 直接搬 + 名称维度扩展（已在 2.2.5 设计）。
- 数值：QUANTITY_FLOOR=1000，_SCALES 加"万/亿"，容差比对
- 名称：series/brand/model_name/tag_category 精确匹配
- 接 `pi.on('tool_result')` 改写 + `agent_settled` 终验

### 验收
- 阶段1 复审 8 个名称错误 100% 拦截
- 数值容差通过

---

## 2.3.2 完成验证器

### 设计（决策④，教材 §3.5 chapter8/premature-completion-dpo）

`agent_settled` 事件插验收（官方名非 `agent_before_settle`）：

**CLAIM 校验**（结论必须有）：
- `conclusion_text`
- `supported_by`：证据行 ID 列表（`review_tags:7650/舒适/con` 等）
- `as_of`：数据时点
- `scope`：结论范围（口碑内 / 配置内 / 市场侧不归因）

**VERIFY 校验**（max 1 次 continuation 再不过 fail）：
1. supported_by 行 ID 真实存在（查库验）
2. as_of 声明且与数据源一致
3. **越界检查**：口碑结论越到市场侧（报告① v0.2 错误）/ 市场侧归因产品力（报告③ v0.2 错误）→ fail
4. 数据缺口是否声明

### 失败处理
- 1 次失败 → continuation（补证据/降级结论）
- 2 次失败 → fail，记 `EVAL_STATUS.md`

### 验收
- 报告① v0.2 "市场侧印证舒适性" → 越界 fail
- 报告③ v0.2 无 supported_by → fail
- 合规结论通过

---

## 2.3.3 口碑定性结论单独一套

### 设计
六分制对口碑失效（定性结论非数值），单独一套：
- **claim 溯源**：每个口碑结论附 supported_by 行 ID + 原文样本（如 `review_id=k_5789427 '颠簸'`）
- **人工抽检**：教材 human-benchmark 模式，抽样 10% 口碑结论人工核对
- 不进六分制评分，单独记 `koubei_claims_audit.md`

### 验收
- 口碑结论必附原文样本（review_id + source_text）
- 人工抽检：每批抽样 10% 口碑结论（最少 5 条），填 `koubei_claims_audit.md` 记录核对结果（pass/fail/边界），可追溯到 review_id

---

## 2.3.4 真值校验

### 设计
教材 reference.py 模式，纯 Python 多重集容差比对：
- 构造 `expected_multiset`（从物化视图取真值）
- 与 agent 回复提取的数值多重集比对
- 容差：销量±2%（口径差异），配置 0 容差（精确）

### 验收
- E5 销量序列真值校验通过（3028/1823/...）
- 配置项精确匹配
