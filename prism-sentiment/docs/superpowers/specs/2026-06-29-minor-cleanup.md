# 主题 G：Minor 清理 — 设计 + 计划（合并，minor 主题）

> 日期：2026-06-29
> 治根主题 G（共 7 主题）：零散 minor 问题清理。非 minor 项拆出后续。

## 侦察结论 — 问题分级

### 明确可修（本主题）
1. **`groupRadarChart` min:-1**（`app.js:1012`）：dim_sentiment 分数范围 0-1（dashboard dimChart `min:0,max:1`），雷达图 `min:-1` 错误 → 负区间永远无数据、图形偏移。改 `min:0`。
2. **废弃调试脚本**（`scripts/`）：`test_scrapling.py`/`test_scrapling2.py`/`test_scrapling_v3.py` —— 项目已弃用 scrapling 改 CDP（记忆 [[cdp-replaces-mc]]），这 3 个是无用历史试验。删。一次性 `verify_*`/`diagnose_*` 保留（可能仍有用）。
3. **`posts_stored` 误导**（`scheduler.py:513-515`）：每个平台 `pp.posts_stored = stored`（total），注释自嘲"approximate, total not per-platform"。前端进度卡片每平台都显示 total（一样）。修正为真实 per-platform 计数。

### 拆出后续（非 minor，需设计/决策）
- **`confidence` 漏用**：AnalyzedPost.confidence 生成了但前端不展示/不过滤。"怎么用"是产品决策（展示？过滤低置信帖？），不塞本主题。
- **`EventGroup.post_ids` 语义**：`event_tracker:328` 存 `[p["id"] for p in group]`，需核实 p 来源是 AnalyzedPost.id 还是 RawPost.id（深层语义，需追踪 group 构建），不塞本主题。
- **donut anchor 不匹配**：`sentimentDonut` 点击传 `{sentiment}`（app.js:394）但 dialog anchor 走 "trend" 类型（认 `{date}`）→ 点击情感环拿不到 sentiment 数据。修需 dialog 新增 sentiment anchor 分支，属功能补全（归 Theme E 前端补全范畴）。

## 设计

### G1 groupRadarChart min:0
`app.js:1012` `indicator: dims.map(d => ({ name: d, max: 1, min: -1 }))` → `min: 0`。与 dimChart（`xAxis min:0,max:1`）对齐。

### G2 删废弃脚本
`git rm scripts/test_scrapling.py scripts/test_scrapling2.py scripts/test_scrapling_v3.py`。
（保留 verify_*/diagnose_* —— 这些是 bug 修复后的验证脚本，有复用价值。）

### G3 posts_stored per-platform
`_store_posts` 返回 per-platform 计数 dict；scheduler 用它填 `pp.posts_stored`，total 单独算。
- plan 阶段读 `_store_posts`（231-）确认返回值改法
- `posts_collected`（total）不变

## Task 清单
1. G1 radar min:0（app.js）
2. G2 删 3 个 test_scrapling 脚本
3. G3 posts_stored per-platform（scheduler + _store_posts）

## 完成标准
- [ ] groupRadarChart min:0
- [ ] test_scrapling* 删除
- [ ] posts_stored 每平台真实计数
- [ ] code-review + pytest（scheduler/batch）

## 非目标
- confidence / EventGroup.post_ids 语义 / donut anchor → 后续主题（已记录）
- 文案"四平台"（index.html:253 描述准确，非 bug）
