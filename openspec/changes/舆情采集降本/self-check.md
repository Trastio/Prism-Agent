# 舆情采集降本 change · Step 3.5 自查（2026-10-15）

## 逐项过检

| # | 检查项 | 结论 |
|---|---|---|
| G1 | 6 词构成 vs `_build_collection_keywords` 现拼序 | **gap 已修**（design D1）：现拼序 core+defect+rest，[:6] 会挤出双关键词——改拼序 core+rest[:2]+defect；并加注释义务：max_keywords 若回调 <6 缺陷词又出选区 |
| G2 | rest[:2]=双关键词的来源 | ✅ base_keywords=车辆表 search_keywords 拆分，core=base[:1]（scheduler.py:253 实证） |
| G3 | comment_polarity 列迁移幂等 | ✅ PRAGMA 查列再 ADD COLUMN（SQLite 无 IF NOT EXISTS） |
| G4 | 新评论两列皆空的读侧行为 | **gap 已修**（design D4 补）：空极性=未打标，与现状同口径端点容忍；T4 单测钉死 |
| G5 | 出口闸 E2E 与清理顺序 | ✅ 无死锁：闸逻辑不依赖清理先行，dry-run 期在存量库上测亦成立 |
| G6 | 删 news 分支误伤车质网入库 | **防护已补**（design D5）：同路入库，自验含车质网回归 |
| G7 | schtasks 不实际注册 | ✅ 留 T6 用户点头（tasks T5 已注） |
| G8 | T0 git commit | **流程调整**：项目规矩"用户点头才 commit"——T0 改为只做库备份（必做），git commit 列为待用户确认项 |
| G9 | max_keywords 每平台独立 | ✅ dataclass 实例字段，摘除后只剩 xhs/douyin 两处改 6 |
| G10 | "连续两日观察"拖归档 | 调整：注册+首日观察即达验收主项，次日复核作归档后置核对 |

## 依赖与并行校验

- T1→T5（词序定型后才摘停采面）✅；T2/T3/T4 互不依赖 ✅；T6 全合后 ✅
- 派单波次与 fork 型守卫纪律已入 tasks.md 头部 ✅

## 验收可验性

explore §四 10 项全部可执行：调用账有护栏计数器实测（非估算）、清理有 dry-run 对账、翻车帖有双轨单测、计划任务有退出码。9 词实验有独立脚本位。

## 结论

**3 gap 全部处置（2 修 design + 1 流程调整），可进 Step 5 施工派单。**波次 1 = T1（参数批+停采面）。
