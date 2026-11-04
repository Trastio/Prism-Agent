# Spec 2.4 · 评估层

> Step 0 基线 + Step 9 评测门禁。前置 [design.md](./design.md)。

## 待办
- 0.1 runner 临时接 scorer.ts 跑 16 题留基线
- 9.1 runner 删正则 scoreTask，调 scorer.ts
- 9.2 单测覆盖 4 模块
- 9.3 CI 骨架 + 发版门槛 4 条件
- 9.4 34 题接入位

## 设计细节

**0.1 基线（验证器口径）**：
- runner.mjs 临时 import scorer.ts，跑 16 题（TASKS 19-38）
- 存 eval/eval-baseline.json：veto命中率 / CLAIM完整率 / 越界率 / 平均分
- 注意：scorer.ts 依赖 verify/* + better-sqlite3，runner 是 .mjs，需动态 import 或编译

**9.1 runner 调 scorer.ts（Gap 5 修正：runner.mjs → runner.ts）**：
- runner.mjs 重命名为 runner.ts，用 `tsx eval/runner.ts` 跑（项目已装 tsx）
- 删 runner.ts:41-77 本地正则 scoreTask
- 改调 scorer.ts 的 scoreTask（已 import verify/* 三文件，直接 import）
- 评分来自验证器判定（verdict.json 文件 / verifyCompletion 结果）非正则

**9.2 单测**：
- src/verify/completion.test.ts：CLAIM 完整性 + 行ID查库 + 越界 + 缺口
- src/verify/grounding.test.ts：8 名称错误 + 数值容差
- src/identity/resolve.test.ts：4 case
- .pi/extensions/prism-guardrails/tool_call.test.ts：拦截 + fail-closed
- 框架：node:test 或 vitest

**9.3 CI 骨架**：
- .github/workflows/eval.yml（或本地脚本 eval/ci.sh）
- 触发：变更 src/verify/ 或 extension/
- 步骤：npm run smoke:all + node eval/runner.ts
- 发版门槛 4 条件：veto零命中 + Wilcoxon显著（p<0.05）+ 保留集CI下界>0 + 成本CI上界<预算
- 统计栈已有（McNemar/Wilcoxon/Cliff's delta/bootstrap，eval/stats.mjs 冒烟通过）

**9.4 34 题接入位**：
- user-tasks-template.md 你填后转 user-tasks.json
- runner 读 user-tasks.json 合并 TASKS
- 接入位：`const USER_TASKS = existsSync('eval/user-tasks.json') ? JSON.parse(readFileSync(...)) : []`

## 验收
- eval-baseline.json 落盘（验证器口径）
- runner 评分来自 scorer.ts 非正则
- 单测 4 模块覆盖，全过
- CI 骨架可触发，发版门槛 4 条件可算
- user-tasks.json 接入位就绪

## 依赖
- Step 1.3 验证器移植（scorer.ts 才有真判定）
- Step 6.4 verdict 事件（runner 可选读 verdict 替代直接调 scorer）
- 34 题你写（不阻塞主线，M6 后接入）
