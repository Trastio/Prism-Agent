# Step7 隔离审查报告 · 「评估迭代 langfuse 深度绑定」change

- 审查人：隔离审查子代理（未参与设计/施工）
- 日期：2026-10-20
- 模式：**在线模式**（第 0 步守卫：ToolSearch `select:` 精确语法确认 Read/Bash/Write/Grep/Glob 可用，全部结论基于磁盘原文 + git diff + 实跑测试，未使用内嵌副本）
- 审查对象：
  - `eval/langfuse_binding.ts`（新建，289 行）
  - `eval/annotate.mjs`（新建，60 行）
  - `eval/langfuse_binding.test.mjs`（新建，165 行）
  - `eval/runner.mjs` 挂接段（import :27；挂接 :651-662，diff +11 行）
- 实跑验证：`node --test eval/langfuse_binding.test.mjs` → **7/7 pass**（Node v25.2.1，type-strip 直载 .ts 实证可用）；fail-soft warn 路径实跑可见输出。

## 逐项结论（A-H）

### A. fail-soft 真伪 — PASS
- bindEvalRun（langfuse_binding.ts:281-288）：syncDatasetItems + linkRun 两个 await **全部在 try 内**，catch 后 warn 一条返回 null，无 try 外 await。
- 挂接段（runner.mjs:655-662）作用域变量逐一核实，全部有定义：`ALL_TASKS`（:78 模块级 const）、`PROMPT_FP`（:25，`.hash` 在 :604 报告字段已实证存在）、`reportId`（:632 函数级 const，先于挂接段）、`results`（:519 const，元素由 runTask 主 return :440-445 `{task: task.id, score: finalScore}` 与异常 return :388 `{task: task.id, score: 0}` 构造——**两条路径都有 task/score 字段**）。
- 挂接段自身无抛点：`r.score >= 4` 对 undefined 不抛（得 false）；模板串与 console.log 不抛。唯一理论逃逸 = import 加载失败（:27）会在 runner 启动期崩，但与 :26 writer.ts 同模式且活栈/本次实跑已验证，非新增风险。

### B. 幂等正确性 — P1（一处静默失效路径）
- diffDatasetItems（:66-73）：metadata 为 null/缺失/空对象/taskId 非字符串（:69-70 `typeof tid === 'string' && tid`）一律不进 seen → **不据此跳过任何题**，测试 1 覆盖全部 4 种形态。PASS。
- skipped 算式（:177）`tasks.length - missing.length` 恒等成立，语义正确。PASS。
- linkRun dedup（:210-211）Map 后写覆盖 = 取最后一条，符合"每 run 每题只建一次"；--repeat 多条取末次，与代码注释自洽。PASS。
- 同 runName 重跑：runName = reportId + PROMPT_FP.hash[:8]（runner :656），reportId 基于 EVAL_RUN_ID（runner :96，缺省 `eval-` + ISO-ms 时间戳）→ 每次 run 天然唯一，"不重"由 EVAL_RUN_ID 承担。仅当用户手动设相同 PRISM_EVAL_RUN_ID 重跑才会重复 dataset-run-item，属可接受边缘。PASS。
- **P1**：listDatasetItems（:127-142）对响应结构**零校验**——`r?.data ?? []`（:137）+ `r?.meta?.totalPages ?? 1`（:138）+ getJson 的 `res.json().catch(() => null)`（:106）。当 GET 200 但 body 非 JSON / data 缺失 / totalPages 缺失（多页 dataset 只拉首页）时，**静默当作"dataset 空或单页"** → syncDatasetItems 全量 POST → 契约明示 POST dataset-items 不幂等 → **dataset 条目翻倍污染且不可自动恢复**。这是"先查后建幂等"承诺的唯一静默失效路径。修复一行：`if (!r || !Array.isArray(r.data)) throw`。触发概率低（活栈形状已实测稳定），但后果不可逆，判 P1。
- 已声明限制（非缺陷，记录）：runner 挂接传 `traceId: null`（runner :657）→ 生产路径上 linkRun 恒 skippedNoTrace、linked=0，dataset-run-items 与 task-pass score 实际不写——"run 链接"半边空转。代码注释 :653-654 已声明"待 writer 补存 per-task traceId 后启用（可接受降级）"，与注释一致。本 change 实际交付 = dataset 同步半边。

### C. 凭证泄漏 — PASS
- 全部 throw 消息只含 路径+状态码（:105/:116 `langfuse GET/POST ${path} HTTP ${status}`），path 为代码常量 + encodeURIComponent(datasetName)，无凭证、无响应体。
- `res.json().catch(() => null)`（:106/:117）：解析失败吞 null，body 不外泄。比参照物 writer 更干净（writer :140 会把 res.text() slice 200 放进错误消息，binding 未沿用该习惯）。
- Basic 头（:97）只进 fetch headers；failed[]（:174/:242）与 console.warn（:286）只拼 e.message（fetch/TimeoutError 消息不含凭证）。Buffer 拼接无泄漏面。
- annotate.mjs:52 console.error(e.message) 同口径。测试用假凭证 env（test:20-22）。无泄漏路径。

### D. runner 集成字段核对 — PASS
- `r.task`：runTask 主 return runner:441，异常 return runner:388。
- `r.score`：runner:445（finalScore）/ :388（0）；:562 `results.map(r => r.score)` 佐证。
- `pass: r.score >= 4`（runner:657）vs passCount = `scores.filter(s => s >= 4).length`（runner:564，scores=:562 同一 results）——**同口径，对质一致**。
- runName 变量 reportId/PROMPT_FP 均在作用域（见 A）。ALL_TASKS 带 SET/ONLY 过滤（runner:78-79）→ 绑定只同步本次跑的题集，与 results 的 taskId 全对齐，不产生 failed 误报。

### E. 测试假阳性 — 无假阳性；覆盖缺口 P2×3
- mock 响应形状与真实 API 契约一致：GET dataset-items `{data, meta:{totalPages}}`（test:80-83）、POST dataset-run-items `{id, datasetRunId}`（test:122）、scores `{id}`（test:123）、GET datasets `{data:[{id,name}]}`（test:79）。PASS。
- 断言真数了 POST 次数（test:87-88 `posts.length===3`；test:133-136 runItems/scores 各 2），非"不抛即过"。PASS。
- mock 路由正则无互相误配（GET datasets 正则不会吃掉 dataset-items：`dataset-` 无 s）。PASS。
- 实跑 7/7 绿 + warn 路径真实触发。
- **P2-1**：buildDatasetItemBody 的 pass_line 分支（binding:84）零覆盖——只测"缺省省略"（test:70），无"存在→透传 expectedOutput.pass"正向测试。
- **P2-2**：fail-soft 测试（test:151-156）未断言 console.warn 被调用（描述与断言不对应）；listDatasetItems 翻页（totalPages>1）与 guard 熔断零覆盖（P1 对应路径也无测试）。
- **P2-3**：测试对磁盘 `.pi/agent-minimal/langfuse.json` 存在性有隐式依赖——loadBindingCreds（binding:37）对象字面量先求值 readFileSync，**文件不存在时 catch 直接 return null，env 假值不生效**（env 只做字段级覆盖，非独立短路）。本机有文件故 7/7 过；无该文件的环境（CI/异机）4 个触网测试会因"凭证缺失"假失败。test:5-6 注释"测试不读真凭证 / env 优先"与实现不符（文件确实被读，只是值未使用未打印——泄漏面无）。

### F. annotate.mjs — PASS（2 个 P2 记录）
- 入口守卫（:58）`process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href` 正确：Node 对 argv[1] 给绝对路径、pathToFileURL 归一 Windows 路径；测试 import 时守卫拦住 main（实跑验证无 CLI 触发）。PASS。
- humanizeScoreName（:13-16）：trim + 前缀去重正确；''/undefined → 'human-' 不可达（:37 `!rawName` 先拦），纯防御。PASS。
- exit 码语义清晰：2=用法错（缺参/非数字）、1=写入失败、0=成功。PASS。
- **P2-4**：--note 缺参（:22 `argv[i+1] || ''`）静默空串继续写（不报错不退 2）——宽容语义无实害，记录。
- **P2-5**：postScore 200 但 json 解析失败 → 返回 id=null（binding:117/:265）→ annotate:49 仍打 `✓ score 已写入: id=null`——成功误报，无法确认写入（与 P1 同根：json 吞 null）。

### G. 超时与资源 — PASS
- AbortSignal.timeout(15s)（:103/:114）每次 fetch 新建信号不复用（无复用失效问题）；Node≥22 环境支持。
- 翻页熔断（:140）`while (page <= totalPages && ++guard < 100)`：短路序保证 ++guard 仅在 page 条件真时发生（无空转副作用）；上限 100 页×50=5000 items（60 题 dataset 实际 2 页）；最坏阻塞 100×15s=25min 属纯理论上限，fail-soft 不崩。PASS。
- json 吞 null 的资源面后果归入 B 的 P1。

### H. 越界改动 — PASS（1 个 P2 记录）
- git status/diff 实证（eval/ 视角）：本 change 面 = `langfuse_binding.ts` + `annotate.mjs` + `langfuse_binding.test.mjs`（新建）+ `runner.mjs` +20 行 + 报告文件。**符合"4 文件+报告"**。
- runner.mjs 的 +20 行中混有并行「归因工具包（2026-10-16）」未提交改动（writeEvalTrace 的 truth_missing 等字段 + reply_full，约 9 行），本 change 实际 +11 行（import 1 + 挂接段）——**P2-6**：commit 时需分拆或在 message 中说明，否则改动面不可单一归因。非本 change 违规。
- `eval/langfuse_writer.ts` 的 M（+10 行）= 归因工具包字段增补（diff 注释时间戳 2026-10-16 实证），**非本 change 所为**；binding 注释"红线③禁改 writer"与本 change 行为一致（binding 对 writer 只读参考）。
- 只读红线核对：`eval/prompt_gate.mjs`、`eval/tasks.json`、`.pi/agent-minimal/langfuse.json` git status 为空（未动）；`src/verify/grounding.ts` 的 M 属其他 change，不在本 change 面。零新依赖：三新文件仅 import node:* 内建 + 相互 import，无 package.json 改动。

## 分级汇总

| 级别 | 编号 | 内容 | 位置 |
|---|---|---|---|
| P0 | 0 | — | — |
| P1 | 1 | listDatasetItems 响应结构零校验（json-catch-null / data??[] / totalPages??1）→ 空/半量列表静默触发全量重建，dataset-items 不幂等 → dataset 翻倍污染不可自动恢复。修复≈一行结构校验 throw | langfuse_binding.ts:106,117,137-138 |
| P2 | 1 | buildDatasetItemBody pass_line 正向分支零测试覆盖 | binding:84 / test:70 |
| P2 | 2 | fail-soft 测试未断言 warn 调用；翻页+熔断零覆盖 | test:151-156 |
| P2 | 3 | 测试隐式依赖 langfuse.json 存在；"env 优先/不读真凭证"注释与实现不符；无文件环境 4 测试假失败 | binding:35-48 / test:4-6 |
| P2 | 4 | annotate --note 缺参静默空串（宽容语义，记录） | annotate.mjs:22 |
| P2 | 5 | postScore id=null 仍打"✓已写入"成功误报 | binding:265 / annotate:48-49 |
| P2 | 6 | runner.mjs 工作树混并行归因 change 改动（+9 行），commit 需分拆说明 | runner.mjs diff |

## 总体判断

**需修 1 项 P1 后可归档**（一行响应结构护栏，守住"先查后建"幂等承诺的唯一静默失效路径）；6 项 P2 无阻塞，建议随手同修 P2-5（同根）与 P2-1（一行断言）。测试无假阳性、fail-soft 无逃逸、凭证无泄漏面、改动面合规。
