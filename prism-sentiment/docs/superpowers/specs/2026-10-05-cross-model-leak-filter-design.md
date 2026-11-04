# 同品牌不同车型混入过滤 — 设计文档

> 日期：2026-10-05
> 状态：设计已批准，待 writing-plans

## 背景

海狮06 看板混入"海狮07ev 动力电池异常"等海狮07 帖子。举一反三全库扫描发现 **310 条混入帖子，覆盖 17 辆车**——系统性问题，非个案。

### 三类混入模式

| 模式 | 典型案例 | 数量 | 严重度 |
|---|---|---|---|
| A. 同品牌不同车型 | 海狮07→海狮06、银河A7→银河E5、零跑A10→零跑B01、风云A9→风云T11 | ~250 | 🔴 严重 |
| B. 同品牌纯品牌词 | "特斯拉"→特斯拉model 3（95 条只含"特斯拉"不含"model 3"）| 95 | 🔴 严重 |
| C. 竞品对比帖（误报） | "海狮06 vs Model Y"、"风云A9 vs T7" | ~30 | 🟢 应保留 |

### 严重案例

| 车型 | 混入数 | 主要来源 |
|---|---|---|
| 特斯拉model 3 | 95 | "特斯拉"品牌词（269 条只含"特斯拉"不含"model 3"）|
| 零跑B01 | 47 | 零跑A10、零跑B10 |
| 风云T11 | 30 | 风云A9、风云A9L |
| 银河E5 | 14 | 星愿、银河A7 |
| 零跑D19 | 11 | 零跑A10 |

## 根因

`pipeline/analysis/relevance_filter.py` 两层过滤都有漏洞：

### Rule engine（Stage 1）漏洞

Rule 4：`含汽车语境词 → PASS`——太宽。"海狮07ev 动力电池异常"含"电池"→直接 PASS，跳过 LLM。没检查帖子是否真的含**本车名**。

### LLM Checker（Stage 2）漏洞

Prompt 只校验"撞名"（同名不同事物，如星愿游戏 vs 车），**没校验"同品牌不同车型"**（海狮06 vs 海狮07、风云A9 vs T11）。没告诉 LLM "单独讨论其他车型的帖子判不相关"。

### 搜索关键词（无法控制）

搜"海狮06"但平台模糊匹配返回"海狮07"的帖子——这是平台行为，无法在搜索层拦截，必须在过滤层处理。

## 目标

1. Rule engine 加"本车名必含"校验：不含本车名 → 不 PASS
2. LLM prompt 加"同品牌不同车型"排除规则
3. 竞品对比帖（含本车名 + 其他车名）保留——不能一刀切
4. 特斯拉 model 3 必须含型号词（"特斯拉"不是别名）
5. 存量 310 条混入帖子软删除（标记 irrelevant）

## 非目标

- 不改搜索关键词（平台模糊匹配无法控制）
- 不改看板层 `RELEVANT_ONLY` 过滤（已正确）
- 不改 `_EXCLUDE_PATTERNS`（撞名排除）和 `_CAR_CONTEXT_RE`（汽车语境词）
- 不物理删除混入帖子（软删除可回滚）

## 设计

### 决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 过滤层级 | Rule + LLM 都改 | 双重保险：规则拦大多数，LLM 处理边界 |
| 对比帖处理 | 含本车名就保留 | 简单明确，~30 条对比帖全保留 |
| 特斯拉混入 | 必须含型号 | "特斯拉"不是 model 3 别名，只含品牌词 → REJECT |
| 存量处理 | 标记 irrelevant | 软删除，看板自动排除，可回滚 |

### 改动 1：Rule engine 加"本车名必含"校验

`relevance_filter.py` RuleBasedFilter.check（约 line 140），改 Rule 4：

现状：
```python
# Rule 4: Contains car context keyword → PASS
if _CAR_CONTEXT_RE.search(text):
    return Relevance.PASS
```

改为：
```python
# Rule 4: 含本车名/别名 + 汽车语境词 → PASS（对比帖含本车名+其他车名也保留）
has_self = profile.name in text or any(a in text for a in profile.aliases)
if has_self and _CAR_CONTEXT_RE.search(text):
    return Relevance.PASS
# 不含本车名 → 不直接 PASS，进 LLM 判断（可能是同品牌混入）
```

效果：
- "海狮07ev 动力电池异常"（不含"海狮06"）→ 不 PASS → 进 LLM → LLM 判不相关
- "海狮06 vs Model Y"（含"海狮06"）→ PASS ✅
- "特斯拉销量..."（不含"model 3"）→ 不 PASS → 进 LLM → REJECT

### 改动 2：LLM prompt 加"同品牌不同车型"排除规则

`relevance_filter.py` `_RELEVANCE_PROMPT`（约 line 163），在撞名校验后加：

```
⚠ 同品牌不同车型校验（重要）：
本车是"{vehicle_name}"({brand}品牌)。如果帖子单独讨论同品牌的其他车型
（如"{vehicle_name}"的兄弟车型/后续车型），而不涉及"{vehicle_name}"本身，
判不相关。例：本车="海狮06"，帖讲"海狮07ev 动力电池异常"→ 不相关。
但竞品对比帖（如"海狮06 vs Model Y"）判相关。
```

### 改动 3：别名表精细化

`VehicleProfile.from_vehicle` 的 `_KNOWN` 别名表（约 line 55）补充：
- 特斯拉 model 3：别名 `["Model 3", "model 3", "model3", "Tesla Model 3"]`，**"特斯拉"不是别名**
- 海狮06：别名 `["海狮06", "BYD Sea Lion 06"]`
- 其他车型按需补充

### 改动 4：存量清理脚本 `scripts/clean_cross_model_leak.py`

扫描全库，对每辆车的帖子：
- 若帖子不含本车名（或别名）+ 含其他车名 → `analysis_status = "irrelevant"`
- 备份 DB 后执行（`data/*.bak.20261005*`）
- 输出清理报告（每辆车清了多少条）

```python
# 伪代码
for vehicle in vehicles:
    for post in raw_posts.where(vehicle_id=vehicle.id):
        text = post.title + post.content
        has_self = vehicle.name in text or any(a in text for a in vehicle.aliases)
        if not has_self:
            # 检查是否含其他车名（确认是混入）
            has_other = any(m in text for m in all_model_names if m != vehicle.name)
            if has_other:
                post.analysis_status = "irrelevant"
session.commit()
```

### 不变

- `_EXCLUDE_PATTERNS` / `_URL_BLACKLIST` / `_CAR_CONTEXT_RE` 不动
- 看板层 `RELEVANT_ONLY` 过滤不动（已正确排除 irrelevant）
- 采集搜索关键词不动

## 测试

新增测试到 `tests/test_relevance_filter.py`：

1. **`test_rule_rejects_cross_model_leak`**：海狮06 车下，"海狮07ev 动力电池异常"帖 → 不 PASS（进 LIMBO/LLM）
2. **`test_rule_passes_comparison_post`**：海狮06 车下，"海狮06 vs Model Y"帖 → PASS
3. **`test_tesla_brand_only_rejected`**：特斯拉 model 3 车下，只含"特斯拉"不含"model 3"→ 不 PASS
4. **`test_llm_prompt_has_cross_model_rule`**：prompt 字符串含"同品牌不同车型校验"
5. **`test_clean_script_marks_irrelevant`**：脚本测试（mock DB，验证标记逻辑）

## 验证

- pytest 全套绿（717 + 5 新增 = 722）
- 存量清理后重扫：混入帖 310 → 0
- 海狮06 看板确认"海狮07ev"消失
- 抽查特斯拉model 3、零跑B01、风云T11 看板无混入

## 风险

- **Rule 4 收紧可能误伤**：个别真讲本车但没写车名的帖子会被拦。但这类帖原本就少，且进 LLM 判断而非直接 REJECT，LLM 可救回。
- **LLM 判断成本**：原本 Rule 4 PASS 的帖子现在进 LLM，调用增加。但混入帖本就该被 LLM 拦，成本可接受。
- **存量清理误判**：可能误标个别应保留的帖。备份后执行可回滚，且 `irrelevant` 是软删除可恢复。
- **别名表不全**：若车型别名没补全，可能漏拦。需在测试中覆盖主要车型。
