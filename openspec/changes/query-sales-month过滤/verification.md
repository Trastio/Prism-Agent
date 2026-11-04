# verification · query_sales month 实装（2026-10-15）

## 验证矩阵（全部主会话实跑）

| 项 | 结果 | 证据 |
|---|---|---|
| api 单测 | **12/12 绿**（month 7 例含 null 语义锁+config 对称测；export 5 例零回归） | `pytest prism-api/tests/` |
| 活端点 month=8 | 恰 1 行 retail_sum=4436（金标锚） | 重启后 curl 复测 |
| 活端点 month=0/13 | 400 fail-loud | curl 复测 |
| spec 分支 | 15 行全 '8月末'（施工轮实测） | step5-notes |
| 服务重启 | 六服务冷启动全绿，网关载入新 schema | prism.py stop/start |
| E2E 真对话 | HTTP 200 / settled verdict=pass（扩展加载+工具链健康） | user_id=eval_step9_smoke |

## Step7 审查

month-param-review 子代理：**可过 P0=0 / P1=0 / P2=6** → 修 5 / 核实补注释 1，见 review-response.md。
要点裁决：月末口径红线两分支安全（并列 AND 语义 + spec 原口径限定未动）；400 顶部校验保留（fail-loud 精神）；null 行=第二种如实缺失语义。

## 遗留（记录不修，非本 change 义务）

1. **sales as_of 恒空（既有疣，本轮发现）**：`_live_meta` sales 分支查 `sales_trim.fetched_at`，但该表无此列 → SQL 异常被 except 吞 → as_of=''。工具契约"返回带 as_of"在 sales 维度从未兑现过。建议后续小修：sales 分支改用最新 year+month 组合口径（如 "2026-8月末"）
2. 行 102 `import re as _re` 重复导入语义（合并属可选）
3. 工具 schema/falsy 修复已随网关冷重启生效（每用户新 pi 进程即新版）

## 归档结论

B1-6 记名债务（guardrails index.ts:270）清账：month 参数从"静默丢弃"变"实装过滤 + fail-loud"。月度聚合与 spec 两分支口径安全，真值锚入测。
