# Step5 施工报告 · langfuse 深度绑定（施工子代理，2026-10-19）

## 做了什么

### T1 `eval/langfuse_binding.ts`（新建）
- `loadBindingCreds()`：读 `.pi/agent-minimal/langfuse.json`（LANGFUSE_* env 优先），复刻 writer 口径不导出改造；缺字段/解析失败返回 null，**凭证不进日志/异常消息**
- `diffDatasetItems(existing, tasks)`：纯函数幂等 diff，幂等键 = `item.metadata.taskId` ↔ `task.id`；无 metadata（或 taskId 非字符串）的存量 item 视为不可匹配
- `buildDatasetItemBody(datasetName, task)`：`input={question, dimension, set, as_of, trap_type(若有)}`、`expectedOutput={golden_digest: judge_rubric||expected_evidence 截断500}`、`metadata={taskId, group: set}`（字段名已对照 tasks.json 实际结构：60 题全量 keys = id/dimension/question/expected_evidence/as_of/source/snapshot_id/set/judge_rubric/trap_type/requires_tikhub/trap_params/truth/rubric_params/requires）
- `syncDatasetItems(tasks, {datasetName='prism-eval-60'})`：GET datasets(单页 limit=50) 先查后建 → GET dataset-items 按 `meta.totalPages` 翻页（>100 页熔断防呆）→ diff → 逐题 POST（单题失败记 failed 继续）
- `linkRun(runName, results, opts)`：列 items 建 taskId→item.id 映射 → 每题 POST dataset-run-items `{runName, datasetItemId, traceId}` 取返回 `datasetRunId` → POST scores `{name:'task-pass', value: pass?1:0, traceId, datasetRunId, comment:'auto: prism eval run', dataType:'NUMERIC'}`；traceId 空跳过计数；同 taskId 去重取最后一条（--repeat 语义：每 run 每题只建一次，proposal 契约）
- `postScore(body)`：导出，linkRun 与 annotate.mjs 共用（内部 postScoreWith(creds,...) 免重复读凭证文件）
- HTTP 统一 `getJson/postJson`：Basic pk:sk + `AbortSignal.timeout(15_000)` + 非 2xx 抛 `langfuse <METHOD> <path> HTTP <status>`（只带路径+状态码，不带响应体/请求头）
- `bindEvalRun(tasks, runName, results, opts)`：fail-soft 总出口，整体 try/catch → `console.warn('[langfuse_binding] 绑定降级…')` 一条后返回 null

### T2 `eval/runner.mjs`（修改，2 处追加）
- 顶部静态 import `bindEvalRun`（紧邻既有 `langfuse_writer.ts` import，同风格）
- mainEval 报告写盘段（"归档副本"日志之后、函数收尾前）挂接：`PRISM_LANGFUSE_BINDING !== '0'` 才执行（缺省开）；`runName = ${reportId}-${(PROMPT_FP.hash||'nogate').slice(0,8)}`（复用既有 PROMPT_FP 变量）；`results.map(r => ({taskId: r.task, traceId: null, pass: r.score >= 4}))`（及格线与 runner 既有 passCount 同口径）；结果打一行汇总日志。dry-run 与 --gate 路径天然不经过（提前 return）

### T3 `eval/annotate.mjs`（新建）
- CLI：`node eval/annotate.mjs <traceId> <名称> <分值> [--note "备注"]`；`humanizeScoreName()` 强制 `human-` 前缀（无则补/有不重复/trim），导出供单测；POST scores `dataType:'NUMERIC'`，成功打印 score id；帮助文案 3 行；入口守卫 `import.meta.url === pathToFileURL(process.argv[1]).href`（被 import 不执行 CLI）

### T4 `eval/langfuse_binding.test.mjs`（新建）
- `node --test` 风格（对齐 gen_attribution_pack.test.mjs）；**零触网**：monkeypatch `globalThis.fetch`；`LANGFUSE_*` env 假值优先（不读真凭证文件、不打印密钥）；每测 try/finally 还原 fetch
- 7 用例：diff 幂等（含 metadata:null / 无 metadata / metadata 空对象 / taskId 非字符串 四种不可匹配形态）、buildDatasetItemBody（500 截断+及格线省略+字段透传）、sync 只补缺 POST 3 次+payload 形态+dataset 已存在不重建、sync dataset 不存在先建+单题 500 失败继续、linkRun 2+2 POST+datasetRunId/NUMERIC 断言+noTrace 跳过计数、bindEvalRun fetch 抛错返回 null 不抛、human- 前缀

## 自验输出贴片（全绿）

```
$ node --test eval/langfuse_binding.test.mjs
[langfuse_binding] 绑定降级（不阻塞评估）: ECONNREFUSED (mock)   ← fail-soft 警告实证（恰好一条）
✔ diffDatasetItems: 已有 taskId 的不进新建列表；无 metadata 的存量 item 不匹配任何题
✔ buildDatasetItemBody: golden_digest 截断 500 / 及格线缺省省略 / 简短字段透传
✔ syncDatasetItems: GET 返回 2 个已有 item + 5 题 → 只 POST 3 次
✔ syncDatasetItems: dataset 不存在 → 先 POST 创建再建 item；单题失败继续其余
✔ linkRun: 2 条 results → 2 次 dataset-run-items POST + 2 次 scores POST；noTrace 跳过计数
✔ bindEvalRun fail-soft: fetch 抛错 → console.warn 一条后返回 null，不抛
✔ humanizeScoreName: 无前缀补 human-，有则不重复，空白 trim
ℹ tests 7  pass 7  fail 0

$ node -e "import('./eval/langfuse_binding.ts').then(...)"
exports: bindEvalRun,buildDatasetItemBody,diffDatasetItems,linkRun,loadBindingCreds,postScore,syncDatasetItems

$ node --check eval/runner.mjs && node --check eval/annotate.mjs
runner.mjs syntax OK / annotate.mjs syntax OK

$ node -e "import('./eval/annotate.mjs')…"
annotate IMPORT_OK_NO_CLI        ← 入口守卫生效

$ node eval/runner.mjs --dry-run --only=trap   （离线回归）
[dry-run] run_id=eval-2026-10-19T15-58-08-423Z git=d811c75 … exit=0
                                   ← 新增静态 import 不破坏模块图；dry-run 不触发绑定

$ node eval/annotate.mjs（无参）→ 3 行帮助，exit=2

$ git status：AGENTS.md/SYSTEM.md/skills×4/verifier-prefix.ts 零触碰（grep 无命中）
```

## 偏差与理由（共 5 项，其中 1 项为预先授权的降级）

1. **traceId 传 null（预先授权的降级）**：runner 未存 per-task traceId（writer 在 `postEvalScore` 内部按 sessionId 解析，`resolveTraceId` 私有未导出，红线③禁改 writer）。linkRun 收到 null 即跳过并计 `skippedNoTrace`，**dataset run-item 链路暂不产生数据**；题库同步（syncDatasetItems）不受影响照常全量生效。runner 挂接处与 linkRun 注释均已标注"trace 关联待 writer 补存 per-task traceId 后启用"。
2. **score 关联字段用 `datasetRunId`**（施工令实测口径），非 proposal 契约表里的 `datasetRunItemId`——按施工令优先，代码注释留了实证出处。
3. **`dataType: 'NUMERIC'`（单数）**：按施工令；writer 自己的路径用 `dataTypes: ['NUMERIC']`，两路互不干扰（writer 零改动）。
4. **expectedOutput.pass 省略**：tasks.json 60 题实测无及格线字段（keys 全集已核对），施工令"及格线若存在"条件不满足；实现了 `pass_line` 前向兼容透传，字段出现即自动带上。
5. **超出最低要求的增项**（均不扩大风险面）：`buildDatasetItemBody` 导出供 payload 直测；linkRun 同 taskId 去重（--repeat 下每 run 每题只建一次，proposal 契约）；listDatasetItems 100 页熔断；测试 5 要求 → 实交 7 用例；runner 离线 dry-run 回归验证。

## 工具面备注（fork 型重试协议相关）

本会话第 0 步守卫首轮误报 NO-TOOLS：ToolSearch 的 regex 交替模式（`bash|read|…`）静默返回无匹配（`WebSearch` 明明存在却未命中），`select:Bash,Read,…` 精确语法才可靠——与 memory 已记录的"select: 语法才可靠"一致，再次实证。守卫复跑通过后全程正常施工，无工作损失。

## 未做（按边界）
- 活栈冒烟（3 题同步/假 run 链路/60 题幂等双跑）——主会话职责，本代理禁真实 API 调用
- T5 文档（explore.md 契约终表）——不在本施工令 T1-T4 范围
- tasks.json / langfuse.json 零写入；7 个 prompt-gate 红线文件零触碰；无新增 npm 依赖
