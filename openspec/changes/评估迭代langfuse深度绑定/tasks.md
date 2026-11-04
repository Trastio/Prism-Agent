# tasks · langfuse 深度绑定（Step3 计划 + 3.5 自查）

## 3.5 自查收敛（Gap 检查，2026-10-19）
- Gap1 loadCreds 未导出（langfuse_writer.ts:60 私有）→ binding 自带 loader 读同一 `.pi/agent-minimal/langfuse.json`（不导不改 writer，避免碰已验证路径）
- Gap2 runName 唯一性 → `{ts}-{prompt_files_hash 前 8 位}`；同 hash 重跑天然分 run，不覆盖
- Gap3 分页 → GET dataset-items 带 page/limit 循环到 meta.totalPages（60 题一页够，但按分页写）
- Gap4 评分语义 → 总分 score 用六分制原值（name=task-score, value=0-6）+ 另发 task-pass(0/1)？**收敛：只发一个 `task-pass`(1/1|0)**，六分制已挂 trace 的 131 断言分，不重复
- Gap5 fail-soft 边界 → 同步/链接全程 try/catch，单题失败继续其余，汇总一条警告日志；退出码不受影响
- Gap6 annotate.mjs 幂等 → 人工分可重打（langfuse score append-only，同名多值=历史轨迹，符合"判读可回溯"语义，文档说明）
- Gap7 测试不触网 → monkeypatch global fetch；活栈冒烟独立脚本不进单测

## 任务
- **T1 `eval/langfuse_binding.ts`**：loadCreds 复刻 / syncDatasetItems(tasks) / linkRun(runName, results) / 内部 postJson 助手；导出可单测纯逻辑（diff 计算等）
- **T2 runner.mjs 挂接**：报告写盘后（:632-648 段）调 syncDatasetItems+linkRun（env PRISM_LANGFUSE_BINDING=0 可关，缺省开）；runName 规则见 Gap2；results 映射=每题 {taskId, traceId, pass}
- **T3 `eval/annotate.mjs` CLI**：`node eval/annotate.mjs <traceId> <name> <value> [--note ...]` → POST scores（human- 前缀强制）；凭证同 Gap1 路径
- **T4 `eval/langfuse_binding.test.mjs`**：node --test；fetch mock；四组用例见验收 1
- **T5 文档**：explore.md 补 API 契约终表；README 级说明（用法 3 行）进 proposal 归档时

## 红线（施工令）
1. tasks.json 只读；langfuse.json 只读（凭证不进代码/日志/异常栈）
2. prompt-gate 7 文件零改动（AGENTS.md/SYSTEM.md/skills×4/verifier-prefix.ts）
3. fail-soft：绑定路径任何异常不得让 runner 非 0 退出（除非 runner 本身已败）
4. 遵循 eval/ 现有代码风格（ESM、无新依赖、Node 25 type-strip 兼容——.ts 直接 import）
