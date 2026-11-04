# 评估基建小包 · 提案

> 2026-10-15 ｜ 设计依据：`设计图总览/Prism-Agent-多轮评估批方案-v1.md`（§5 表格产物）+ 教材代码仓留痕对照（EXPERIMENT_LEDGER/manifest 三件套）
> Step1 explore 已完成（2026-10-15，主会话实测 runner 报告结构）

## 为什么做

①多轮机制空转的前置基建（渲染器/明细/abort）；②判分数据可追溯性三缺口（教材对照实锤）；③下一波 badcase L1-2 提示词层修之前，账要先能对。

## Step1 探查结论（比方案估计更薄）

- runner 报告单题行**已含** `perTurnTruth` + `turnVerdicts`（eval-2026-10-14T02-02-14-418Z.json 实测 16 字段）——四 sheet 数据地基已在，runner 侧改动收窄为：逐轮分派生 + abort 支持 + 哈希 + boundary。
- 报告写盘点：runner.mjs:545-577（eval-report.json + reports/{id}.json 双写）。

## 改动面

| 件 | 内容 | 位置 |
|---|---|---|
| 渲染器（主新件） | report JSON → 四 sheet md+xlsx（总览含首错轮/逐轮衰减/恢复成功率/穿线验证） | eval/ 新脚本 |
| abort 支持 | 取消题跑中调 /chat/abort | runner.mjs |
| **洞1** calibration_log | 回填 v1.1 四类校准 3-4 条 + 立规矩"改容差必写日志" | eval/scoring-rules.json |
| **洞2** 产物哈希 | 批跑收尾对报告 json/xlsx 算 SHA-256 写侧车 manifest | runner.mjs:545-577 |
| **洞3** acceptance boundary | 报告顶层结构化字段（snapshot_ids/tasks_git_hash/dev_frozen 构成/适用声明模板），渲染进成绩单页脚 | runner.mjs + 渲染器 |
| 单测 | 渲染器四 sheet 生成 + 首错轮判定 + 哈希/boundary 字段 | eval/*.test.mjs |

## 验收

1. 用 v1.1 既有报告（eval-2026-10-14T02-02-14-418Z.json）离线渲染出四 sheet md+xlsx 各一份，逐轮衰减表数字与成绩单对账
2. 首错轮列有值（低分题 6 道逐个核对）
3. 哈希 sidecar 生成且复算一致；boundary 字段含快照 ID + 题集 git 哈希 + 适用声明
4. calibration_log 回填后 scoring-rules.json 解析合法，truth 判分行为零变化
5. 既有 60 题判分零回归（rerun 判分路径不触发实跑——用 --dry-run + 单测覆盖）
6. 门禁 + smoke 全绿

## 边界（不入本包）

多轮 12 题**题目本身**（等用户追问话术）；多轮 E2E 实跑（随题目入库后）；登录门（并行 change A）。
