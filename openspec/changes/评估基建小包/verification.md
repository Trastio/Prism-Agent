# verification · 评估基建小包（2026-10-15）

## 验证矩阵（全部主会话实跑）

| 项 | 结果 | 证据 |
|---|---|---|
| 单测 | **16/16 绿**（12 施工 + 4 审查补测） | `node --test eval/report_lib.test.mjs` |
| eval 全套 | **67/67 绿**（report_lib 16 + trap/truth/rubric 51——判分器零回归） | `node --test eval/*.test.mjs` 四件 |
| 离线渲染对账 | 60题/54满分/6低分与成绩单-v1.1 逐题一致；首错轮 6/6 有值 | 样张 `eval/reports/样本-四sheet-v1.1-四sheet.{md,xlsx}` |
| calibration_log | 解析合法、六字段齐全、判分键未动（单测锁） | report_lib.test 末测 |
| 60 题 dry-run | 全量列出+元数据齐（git=06edb7c / snap-20261012-1222） | `node eval/runner.mjs --dry-run` |
| 服务重启 | 六服务冷启动全绿 | prism.py stop/start |
| E2E 真对话 | HTTP 200，回复正常，settled verdict=pass | user_id=eval_step9_smoke |

## Step7 审查

eval-infra-review 子代理（磁盘提取内嵌）：P0=0 / P1=4 / P2=7 → 修 8 / 裁决 1 / 记录 2，见 review-response.md。
"既有 60 题判分零改动"经 diff 级确证（循环改写等价 / abort undefined 短路 / spread 保字段 / 注记字段无判分消费）。

## 偏差与遗留（如实）

- P1-4（_calibration_policy 严格解析分支）：truth_check 按键取值已核实宽松，**真实批跑实跑确认留待下轮**（v1.2 批跑读写该文件即最终兜底）
- Sheet4 穿线验证为如实占位（全单轮批无穿线数据）——多轮题入库后生效
- abort/boundary/manifest 的批跑真值演练随下轮批跑

## 归档结论

基建交付：渲染器（md+xlsx 四 sheet）/ 首错轮 / 三洞（calibration_log+SHA-256 侧车+acceptance_boundary）/ abort 机制。判分路径零改动。下游消费：多轮题入库后 v1.2 批跑即用。
