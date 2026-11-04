# spec · 评估回归门（M4）

## 待办清单

1. `eval/tasks_gate.json`：E1-E9 九题（D8 独立文件；E7 用 mock 上游或停服务模拟）
2. `eval/runner.mjs`：`--gate` 模式（只跑 gate 集）；断言扩展——settled 事件计数（NDJSON 流内计）、toolCalls 中 bash 计数、trajectory.submission 字段
3. `index.ts` appendTrajectory：增 `submission: { count, pass, lastReject }`（从 entries/branch 统计）
4. `eval/ci.sh`：挂 `--gate` 门槛（E1-E9 全绿 + 现有 16 题门禁并存）
5. E1 场景构造：≥5 轮含数字（至少一轮派生结论提交 + 一轮 get_sales_detail 来源）再问"你是谁"；E8 与 E1 同批跑

## 设计细节

- E7 断言"该轮 bash=0"依赖 EXCLUDE_TOOLS 生效（C0 前置）
- submission 字段供 E2/E3/E9 断言（拒绝原因进 lastReject）

## 验收标准

- N7：ci.sh（含 --gate）全绿
- E1 与 E8 同批通过（同一判据两侧）
- 现有 16 题报告格式不破坏
