# 评估基建小包 · Step5 施工自检小结（2026-10-15）

> 施工子代理：fork 型（第 0 步工具面守卫："."全量列举未见 Bash/Read/Write，select: 精确语法拉取成功——实况再次坐实"."正则漏检，未误报 NO-TOOLS）
> 纪律遵守：只改 eval/ 目录；未碰 prism-api/prism-web/.pi；未重启服务；未 git commit；判分器（trap/truth/rubric_check.mjs）一行未动

## 改动文件

| 文件 | 类型 | 内容 |
|---|---|---|
| `eval/report_lib.mjs` | 新增 | 共享派生库：firstErrorTurn（首错轮）/ deriveBoundary（洞3）/ aggregateDecay（Sheet2）/ classifyRecovery+recoverySubset（Sheet3）/ crossCheckRows（Sheet4）/ sha256File+buildManifest（洞2）/ buildSheets+renderMd（四 sheet 同源组装） |
| `eval/render_report.mjs` | 新增 | CLI：report JSON → 四 sheet md+xlsx；--out 前缀；--with-manifest 回填旧报告哈希；旧报告缺 boundary/首错轮自动派生 |
| `eval/render_xlsx.py` | 新增 | openpyxl 四 sheet 写出（复用 prism-api 同款依赖，**零新增 npm 依赖**）；sheet 名 31 字符截断；粗略中文列宽 |
| `eval/report_lib.test.mjs` | 新增 | 12 测：首错轮 4 态 / 衰减聚合 / 恢复三档 / 穿线如实注记 / boundary 计数 / 哈希复算 / 四 sheet 组装 / calibration_log 六字段守卫 |
| `eval/runner.mjs` | 修改 4 处 | ①import report_lib ②runTask 轮循环加 abort_after_turn 机制（仅显式设置触发，fetch POST /chat/abort {user_id}，失败静默注记 abortedAfter/abortOk）③行级 first_error_turn 注记 + 报告顶层 acceptance_boundary（洞3）④写盘后 SHA-256 sidecar manifest（洞2，try/catch 不阻塞） |
| `eval/scoring-rules.json` | 修改 | calibration_log 回填 4 条（容差表初始化/verdict 豁免放宽/trap 三假阴修复/truth 7 不稳锚摘除，各带 before/after/reason/evidence）+ _calibration_policy 规矩；tolerance_overrides 等既有键零触碰 |

## 测试结果（原样）

- 新增：`node --test eval/report_lib.test.mjs` → **12/12 pass**
- 全量回归：`node --test trap_check truth_check rubric_check report_lib` → **63/63 pass**（既有 51 + 新 12，判分零回归）
- runner 完好性：`node eval/runner.mjs --dry-run` → 60 题正常列出（report_lib import 无副作用）
- scoring-rules.json：python json.load OK，calibration_log 4 条

## T8 离线渲染对账（v1.1 报告 eval-2026-10-14T02-02-14-418Z.json）

- 产物：`eval/reports/样本-四sheet-v1.1-四sheet.md` + `.xlsx`（5 sheet=四 sheet+适用边界）+ `eval-2026-10-14T02-02-14-418Z.manifest.json`
- **对账全中**：60 题 / 满分 54 / 低分 6（cross-09:1 sales-06:1 sales-07:2 sales-09:1 sales-10:1 config-07:2）= 成绩单-v1.1 逐题一致
- Sheet2 逐轮衰减 t1：题数 60 / truth 查锚 17 / 命中 16（94%）/ 越界 4 —— 与 EVAL_STATUS"17 题查 16 锚 fail 1"+越界集群 4 题（cross-09/sales-06/09/10）完全吻合
- 首错轮：6/60 有值，低分 6 题全部=1（单轮批失败均落末轮，符合预期）；Sheet3/Sheet4 如实注记"本批无纠正原型/全部单轮"（不编造）
- 哈希复算：manifest 侧车 sha256 重算 MATCH

## 未尽项 / 移交主会话

1. **T9 Step7 隔离审查 + T10 归档**：主会话流程（本包代码全文可从上述 6 文件磁盘提取）
2. **abort / boundary / manifest 的真实批跑演练**：机制已单测+dry-run 加载验证，真值演练随下次批跑（或 --only 单题冒烟）自然发生；取消题真题不入本包（等 multi 题族）
3. **门禁（ci.sh）+ smoke 全量**：属 Step9，且需服务编排（prism.py eval start），主会话执行
4. 渲染器 Sheet4 穿线验证目前为占位（"待轨迹分析"）——接 langfuse/trajectories 分析属后续迭代，proposal 边界内
