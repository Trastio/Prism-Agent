# 评估迭代 langfuse 深度绑定 · Step2 proposal（2026-10-19）

## WHY
评估迭代当前是"半绑定"：trace/score 已进 langfuse（writer 已接线），但题库、run 分组、人工判读全在本地文件——langfuse 只当仓库没当工作台。半绑定=两头维护零视图价值。用户拍板（10-19）：深度绑定，三条件（真源不搬家/范围三件/不用 prompt 管理）+ 免审阅直做。

## WHAT（交付面）
1. **题库→Datasets 单向同步**：tasks.json(60题) → langfuse dataset `prism-eval-60`，item=题（input=问题，expectedOutput=要点摘要，metadata.taskId=幂等键）；先查后建（v4 建 item 不幂等，实测重复=两条）
2. **批跑→Dataset Run**：每次 eval run 以 runName（含 prompt_files_hash 短码+时间戳）注册；每题建 dataset-run-item（挂当题 traceId）+ 一个挂 datasetRunItemId 的总分 score（task-pass）
3. **人工判读落账**：`eval/annotate.mjs` CLI——人工对指定 traceId 打 human-* score（与 judge score 并存不覆盖，拍板③）。标注队列公共 API 无此路径（探针实证），UI 队列留上游支持后接入（边界记录）
4. **fail-soft 铁律**：绑定任何失败（栈停/401/网络）只打警告不中断评估——判据=删掉 langfuse 后批跑照常出报告（拍板①的机械化验证）

## API 契约（10-19 全实测，v4 self-host）
| 操作 | 端点 | 语义 |
|---|---|---|
| 列/建 dataset | GET/POST /api/public/datasets | 建重复=两条（按名先查） |
| 列 items | GET /api/public/dataset-items?datasetName=X&page= | metadata 回读✅（taskId 可作幂等键） |
| 建 item | POST /api/public/dataset-items {datasetName, input, expectedOutput, metadata} | **不幂等**；externalId 不回显（弃用） |
| 建 run-item | POST /api/public/dataset-run-items {runName, datasetItemId, traceId} | run 按 runName 归并（同 runName 同 datasetRunId）；run-item 重复=追加（每 run 每题只建一次） |
| 建 score | POST /api/public/scores {name, value, traceId, datasetRunItemId} | 200 实证 |
| experiments | GET /api/public/experiments（要 fromStartTime）| POST 405=只读；dataset runs 在 UI Datasets 页看趋势（experiments 对象不可公共 API 建，降级可接受） |

## 边界（不做）
- 不动 tasks.json 金标（只读）；不在 langfuse UI 改题（单向同步）
- 不碰 prompt-gate 7 文件；不用 langfuse prompt 管理
- 不迁移历史轨迹（旧 project 键列改挂被 CH 禁止，已记录）
- 60 题批量同步的 UI 删除依赖（公共 API 无 DELETE）

## 验收
1. 单测：dedup（存在 taskId 不重建）/缺题补建/fail-soft（fetch 抛错不冒泡）/payload 形态断言
2. 活栈冒烟：3 题同步→dataset 3 items；假 run 链路（run-item+score 挂探针 trace）全 200
3. 批跑回归：绑定挂接后 runner 干跑（无 langfuse 场景=设错 key）不崩、报告照出
4. 全量 60 题同步幂等：连跑两次，item 数不翻倍
