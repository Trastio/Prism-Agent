# 评估迭代 langfuse 深度绑定 · 归档（Step10，2026-10-20）

> 大 change 严格十步走完。施工=Step5 fork 型子代理（报告 eval/reports/subagent-step5-report-langfuse-binding.md）；
> 隔离审查=Step7 子代理（报告 subagent-step7-review-langfuse-binding.md，0P0/1P1/6P2）；主会话验货+Step8 修+Step9 活栈冒烟。

## 交付
1. **题库→Datasets**：`eval/langfuse_binding.ts` syncDatasetItems——tasks.json(60题)→dataset `prism-eval-60`，先查后建（幂等键 metadata.taskId），**活栈实证：首跑 created=60，二跑 created=0**（幂等成立）
2. **批跑→Dataset Run**：linkRun（runName=reportId+prompt 指纹短码）+ task-pass score 挂 datasetRunItemId；runner.mjs 报告写盘后挂接（PRISM_LANGFUSE_BINDING=0 可关，fail-soft）
3. **人工判读**：`eval/annotate.mjs` CLI——human- 前缀强制，与 judge 分并存（拍板③）
4. 单测 9/9（diff 幂等/先查后建/翻页/结构校验 fail-loud/fail-soft 恰一条警告/payload 形态/pass_line 分支）

## 两处关键纠错（本 change 的方法论产出）
1. **P1（审查抓出）**：响应结构零校验——200 但 body 异常时静默当"空库"→全量 POST→item 翻倍且公共 API 无删除不可恢复。修=getJson 非 JSON 即抛 + data/meta.totalPages 结构校验（宁拒不猜），附回归测试（异常形状下 POST 计数必须为 0）
2. **score 关联字段转录颠倒（活栈冒烟抓出）**：探针实证 200 的是 `datasetRunItemId`（值=run-item id），我转录进施工令写成 `datasetRunId`——mock 测试随错契约假绿，活栈 400 一眼打回。**教训：契约转录必须回贴原始探针输出核对；mock 测试验不了契约本身，活栈冒烟是唯一裁判**

## 审查处置（Step8）
- P1 ✅修（结构校验三处+回归测试）；P2-1 ✅（pass_line 测试）；P2-2 ✅（warn 断言+翻页测试）；P2-3 ✅（loadBindingCreds 文件缺失不连坐 env）；P2-5 ✅（annotate id=null 不打 ✓）；P2-4 记录（--note 缺参静默空串，无害小疣）；P2-6 ✅（commit 分拆：归因工具包独立提交，runner.mjs 混行在 B 提交注明）

## 验收对账（proposal 四条）
1. 单测四组 ✅（9/9）2. 活栈冒烟 ✅（60 题同步+幂等二连+假 run linked=2+human score 200）3. fail-soft ✅（fetch 抛错返回 null 恰一条警告；runner dry-run exit=0 施工子代理证）4. 全量同步幂等 ✅（60→0）

## 遗留（不阻塞）
- **traceId=null 降级**：runner 未存 per-task traceId（writer 按 sessionId 内部解析未导出，红线禁改 writer 已验证路径）→ 现状 link 全部 noTrace 跳过；题库同步/趋势不受影响。**启用条件=writer 补存 per-task traceId**（下个评估侧 change 顺手做）
- experiments 对象公共 API 只读（POST 405）→ runName 趋势在 UI Datasets 页看；标注队列公共 API 无路径 → annotate CLI 落 human 分（上游支持后再接 UI 队列）
- 活栈残留：smoke-run-20261020-fix（2 run-item+2 score）+ human-smoke 分+探针 dataset `explore-probe-delete-me`（2 items）——量小无害，UI 可核对
- 全量 58/60 题真实批跑的端到端（含 per-task trace）= 用户下轮批跑自然回归

## 面试三讲
1. **解决什么**：评估迭代从"本地报告+人工对指纹台账"升级为"langfuse 工作台"——题库/趋势/人工判读三视图，且栈挂掉评估照跑（fail-soft 判据）
2. **用户角色**：三条件拍板（真源不搬家/范围收敛/不用 prompt 管理）+ 免审阅授权十步直做；当天栈被清事件反成"真源不搬家"的活论据
3. **追问点**：为什么 mock 测试没抓住字段名错误？（mock 验逻辑不验契约——契约错误只有活栈能裁）；为什么先查后建？（v4 建 item 不幂等+无删除 API，污染不可逆——fail-closed 思维用在评估基建上）
