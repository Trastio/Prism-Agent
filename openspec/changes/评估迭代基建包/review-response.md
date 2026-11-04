# 评估迭代基建包 · Step8 receiving-review（2026-10-14）

> Step7 隔离审查：1 P0 + 4 P1 + 8 P2 + 4 简化。逐条处置如下（主线执行）。

## P0（全修）
- **P0-1 stats 条件4 读错字段** → ✅ `cost.duration_s` 嵌套取值修复+预算语义注明（duration 兜底口径=时长预算）。验证：真形态报告配对不再"无成本数据"崩溃，合法输出"配对 0"结果。

## P1（全修）
- **P1-1 rubric 零挂载** → ✅ `_backfill_rubric.py`（幂等）：ranking 4 题（sales-08/09/10、config-07，top3 从金标提取+尾数字清洗+hard_first）/ sentiment_pattern 5 题（sentiment-03..07）/ gap 3 题（config-03/04/10 仅 web-缺口题）= **12 题挂载**；真实条目冒烟双绿。**决策记录**：纯库内缺口题（sales-04/11/12、reviews-11）不挂 gap——gap 要素含 URL+不可复算，对"声明无数据即可"的题过度惩罚；要素子集能力留 P2（首跑后视分布定）。
- **P1-2 _backfill_truth 残留 trap-09** → ✅ 条目摘除+决策注释（防复跑复活双罚）；复跑验证 truth=17 题/forbid=0 与 tasks.json 一致。
- **P1-3 锁两缺口** → ✅ 判据改 `pidAlive && age<STALE`（PID 死即放行）+ 任务循环逐题 touch 心跳（长批跑不误判 stale）。
- **P1-4 证据正则压平 85%** → ✅ verdict=pass 且 evidence_ids>0 时豁免 hasEvidence/hasAsOf 正文封顶（正则退居无 verdict 兜底——与文件头 T-9.1"验证器优先"对齐）。

## P2（修 5 / 记 3）
- ✅ P2-1 INJECT_RESIST 摘除 无法/不能/拒绝（假阴实证词）；既有 24 测试不破。
- ✅ P2-3 fixture 按当前任务过滤（专属录制件存在时只装它的目录）。
- ✅ P2-4 stats 同题多行 first-wins（防 repeat 后写覆盖）。
- ✅ P2-7 prism.py eval start 打印 web 三态命令提示（双侧 env 生效说明）。
- ✅ P2-8 重复行删除（runner 逐轮 truth 封顶）。
- 记录：P2-2 trap-10 阈值（首跑看分布再校准≥3）/ P2-5 trap n=0 空真加 note / P2-6 writeEvalTrace cost 死字段+批跑尾截断风险（langfuse 侧首跑观察）。

## Simplification（修 3 / 记 1）
- ✅ summarizeRun 删除（零调用方，grep 证实零残留）/ default_tolerance 删（scoring-rules.json）/ 重复行删。
- 记录：runGateStep 与 streamChat 近重复、readLastTrajectory userId 死路径（预存）——留下一轮。

## 终验
trap 24/24 / truth 9/9 / rubric 15/15 / 语法检查全过 / _backfill_truth+rubric 双幂等 / rubric 真实挂载冒烟双绿 / stats P0 修复实证 / EVAL_STATUS dry-run 记账行清理（D6 机制本身验证可用）。

## Step9 提醒
- 生产网关 9200 统一重启（吃 mapEvent auto_retry+web 三态+evalToday）
- 验收总表 10 项 + **60 题首跑（v1 基线）**；首跑后校准位：trap-10 阈值/gap 要素子集/证据正则残余面
