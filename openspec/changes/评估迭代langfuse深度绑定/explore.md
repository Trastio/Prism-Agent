# 评估迭代 langfuse 深度绑定 · Step1 explore（2026-10-19 开档，进行中）

> 大 change 严格十步。本文档=Step1 事实底稿：栈修复过程实测到的 v4 API/运维事实 + 待探索清单。
> 范围拍板（用户 10-19）：三条件=①真源不搬家（tasks.json/本地报告/prompt-gate 台账为唯一真源，langfuse=视图+工作台，判据=删掉 langfuse 评估照跑）②只做 Datasets/Experiments/标注队列三件，badcase 回流等上云+轮2 ③不用 langfuse 管 prompt。

## A. 栈修复实录（2026-10-19，今日完成）——v4 运维事实

| # | 事实 | 出处 |
|---|---|---|
| A1 | 栈曾半死：Docker Desktop 端口转发层未物化（HostConfig 有绑定但 NetworkSettings 空） | docker inspect 对比 |
| A2 | **Postgres 数据丢失**（10-14 后某时点，原地清；卷对象 CreatedAt 不变=取证仅此） | ApiKey/Project 表不存在 |
| A3 | **ClickHouse/MinIO 幸存**：4,484 事件 + 131 分数（10-05→10-14 全史） | default.events_core/scores |
| A4 | 恢复法：`LANGFUSE_INIT_*` 9 变量**钉回原 keys**（.pi/agent-minimal/langfuse.json 零改动，writer 兼容）；管理员密码落 Desktop/langfuse/admin-credentials.txt | .env + INIT job |
| A5 | **9000 在 Windows NAT 保留段 8961-9060**（同 9100 坑）→ compose 摘除 127.0.0.1:9000:9000，容器网内部不受影响 | netsh excludedportrange |
| A6 | **CH 表在 `default` 库非 `langfuse` 库**；writer SQL 不带库名查 events_core 正好命中 default | system.tables |
| A7 | 旧轨迹 UI 不可见（挂旧 project_id cmuv8…；CH UPDATE 键列被禁 CANNOT_UPDATE_COLUMN）；备选=postgres 侧按旧 id 重建 Project+ApiKey 行，未做 | recovery-note |
| A8 | pk 实际尾号 ...3e3a（记忆 ...dfaa 过时）——keys 以 langfuse.json 文件为准 | 文件实读 |
| A9 | OTLP 摄取 200→events_core 落库链路验证通过（探针 trace 命中） | 15:38 |

## B. v4 公共 API 实测（终表，10-19 沙盒全链路验证）

| 操作 | 端点 | 实测语义 |
|---|---|---|
| 列/建 dataset | GET/POST `/api/public/datasets` | GET 分页 {data,meta}；POST {name} 200 建重复=两条（按名先查） |
| 删 dataset | DELETE `/api/public/datasets/{id}` | 405 只能 UI 删 |
| 列 items | GET `/api/public/dataset-items?datasetName=X&page=&limit=` | **按 datasetName 寻址（非 datasetId！）**；metadata/input/expectedOutput 回读✅ |
| 建 item | POST `/api/public/dataset-items` | 必填仅 datasetName；**不幂等**（重复=两条）；externalId 传入不回显（弃用）；幂等键=自管 metadata.taskId |
| 建 run-item | POST `/api/public/dataset-run-items` | 必填 runName+datasetItemId；返回 {id, datasetRunId}；**同 runName 归并同一 datasetRunId**（run 按名幂等）；run-item 本身追加式（每 run 每题只建一次） |
| 建 score | POST `/api/public/scores` | 必填 name+value(union string/number)；**关联字段=datasetRunItemId（值=run-item 的 id）→ 200 实证；datasetRunId（run 的 id）→ 400 被拒**（Step9 活栈冒烟纠错：早前探针结论转录颠倒，mock 随错契约假绿，活栈一眼打回） |
| experiments | GET `/api/public/experiments?fromStartTime=...` | 必填 fromStartTime（时间窗强制）；POST 405=只读，experiment 对象不可公共 API 建——**降级：dataset runs（runName）在 UI Datasets 页出 per-item 跨 run 趋势，experiments 对象留上游** |
| 标注队列 | `/api/annotation-queues` 等 | 公共 API 无路径（404/HTML）；**降级：annotate CLI 发 human-* score 落账，UI 队列等上游** |

沙盒链路验证（explore-probe-delete-me dataset 上）：建 item ×2 → run-item ×2（同 runName 同 datasetRunId）→ score 挂 datasetRunId 200 全通。

## C. 待探索清单（Step1 继续）

1. datasets items：POST /api/public/datasets/{id}/items 的 payload 形态（input/expectedOutput/metadata）+ 幂等性（重复同步会不会翻倍）
2. experiments：正确参数形态；experiment run 创建（POST /api/public/experiment-runs?）与 dataset run item 挂接方式
3. 标注队列：公共 API 是否暴露（不暴露则走 UI 手动+web UI 自动化边界拍板）
4. runner 挂接点：eval/runner.mjs 批跑结束处（现有 writeEvalTrace/summarizeRun 之后）加 dataset run 写入的最小切口
5. 60 题→dataset item 的映射 schema（taskId 作 item key；金标 expectedOutput 放哪里——注意金标真源在 tasks.json，dataset item 只是拷贝视图）
6. 分数挂 dataset run item：postEvalScore 现挂 trace_id，需加 dataset run item 关联（langfuse score 的 dataTypes?）
7. 环境标记：experiment run metadata 带 prompt_files_hash（与本地报告对齐——prompt-gate 指纹进 langfuse 视图层）

## D. 风险与边界（已定）

- 真源不搬家（判据见头部）；tasks.json 单向同步、禁 UI 改题（拍板②）
- human score 与 judge score 并存不覆盖（拍板③）
- langfuse 留本地不上云（既有拍板），生产监控走 prism-ops，轮2 再修回流桥
- 栈半死/被清是真实运维风险：INIT 钉 keys 已把"重置后恢复"变成 .env 一条命令——但 datasets/experiments 定义在 Postgres，**wipe 会连它们一起丢** → 同步逻辑必须可重放（从 tasks.json 重建），这本身就是"真源不搬家"的又一论据
