# 硬编码清理与车系动态化 · Archive

> 2026-10-06 · 十步流程走完归档

## 十步完成
- Step1 explore ✅
- Step2 propose ✅（proposal/design/tasks）
- Step3.5 自查 ✅（5 Gap）
- Step5 施工 ✅（防0+B+Z1+D+E+F）
- Step6 simplify ✅（P0+P1 4默认参数+死分支+合并读取+抽变量+modelId外提）
- Step7 code-review ✅（1 P1+13 P2）
- Step8 receiving-review ✅（P1-1+P2-2/3/7/10/12 修）
- Step9 verification ✅（8 验收全达成）
- Step10 archive ✅

## 成果
- 删 17 幽灵 .js（主修复，A/C 自动生效）
- series prop 全链路（App→KanbanView→四 Board）
- CLAIM 动态化（supported_by/scope 抽变量，series_id 从 /identity/resolve）
- ReviewsBoard model_id 动态化
- 默认空 series + 真阻断 setActiveTools([])（红线#7）
- 车系 tab 实装（搜索+最近+高亮）
- SYSTEM.md 合并读取（修 no-op bug）
- 4 处默认参数 '银河E5' → ''

## 留下一轮
P2-1/4/6/8/11/13 数据健壮性 + mapEvent（观测域留v2）
