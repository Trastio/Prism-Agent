# 修复 · 看板标签覆盖率显示 >100%（2026-10-18 凌晨）

## 现象（用户报告）
前端口碑看板部分车系显示 200%、部分显示怪概率；实测 8010 页面确实渲染 110%~5000% 的覆盖率。

## 根因（两层）

### ① 标签覆盖率 >100%（如 102%、706.5%）
分子分母**口径错位**：
- 分母（taggable）只认 **best/worst_review_text 短文本**有值的口碑
- 分子（tagged）= 有标签的口碑——**老数据口碑常只有详情页全文**（无短文本），照样被打上标签
- 分子含"无短文本但已打标"的口碑 → tagged > taggable → >100%
- 昨晚孤儿标签（FK 级联未开启）曾加剧过一轮（已清 57+367 行）

### ② 采集覆盖率 >100%（最高 5000%）
`collection_coverage = 库内已采 / 之家壳表 onsell_review_count`——分母是**之家缓存标注，滞后常见**（源站标注 2 条、库内实采 100 → 5000%）。

## 修复（4 处编辑点，2 文件 + 2 函数）
1. `src/tools/reviews.py` `_has_text_filter`：文本口径补入 best_full_text/worst_full_text
2. `src/tools/reviews.py` `_tag_coverage_for_series`：分子改"有标签 ∧ 有文本"交集（join 限定）
3. `src/api/dashboard_routes.py` `_batch_tag_coverage`：taggable/tagged 同口径对齐（全文入分母、分子交集）
4. `collection_coverage` 两处（列表路由 + dashboard_data 下钻）：封顶 min(x, 1.0)，注释说明源站标注滞后语义

## 验证
- 口碑列表页 / 宋Pro(5279) / 元UP(7538) / 银河A7 EV(8666) 下钻页：**全部 max=100.0，无 >100 渲染**
- `pytest tests/`：**183 passed**

## 遗留
- 根因级修复（SQLite PRAGMA foreign_keys=ON 使 CASCADE 生效）在 Step7 清单
- 浏览器旧渲染需强刷（Ctrl+F5）
