# explore · 多轮评估批 change（2026-10-25）

## 背景与范围

方案源：`设计图总览/Prism-Agent-多轮评估批方案-v1.md`（v1.1，10-16 拍板）。
题目内容：`核心文档/05-多轮题卷册-12题-审阅版.md`（10-25 用户过审，锚点全部从快照 snap-20261012-1222 查证落锚）。
范围七件：①挂 12 题 ②runner 三机制 ③Sheet4 接线 ④ask_user 模拟应答 ⑤traceId 补存 ⑥/events 身份焊死 ⑦单测+零回归。

## 代码现状核验（全部实读，非记忆）

### runner 多轮机制——比方案"实施现状注"更全
- `eval/runner.mjs:363-434`：`task.turns=[{message,truth?}]` 依序 POST、session_id 穿线（:340 session_info 事件取 sid）、`abort_after_turn=N`（:386，取消题机制已建）、终轮+逐轮 truth 判分（:417-434，逐轮缺锚封顶 2 分）、**first_error_turn 已在算**（:454）
- **缺**：branch_on（条件分支）/ variants（话术轮换）/ carry_anchor（轮间漂移）——方案 §10 落地清单 ~60 行
- 会话隔离修复已在位（:351 每题首轮显式 POST /session 开新会话）——10-20 串味修复实证过

### Sheet4 穿线占位
- `eval/report_lib.mjs:104-108`：`crossCheckRows()` 占位（全单轮→空 rows+如实注记）；测试 `report_lib.test.mjs:90` 已有"全单轮不编造"断言。接线点=carryCheck 结果进 rows。

### ask_user 自动代答根因（10-20 挂账坐实）
- `prism-api/pi_gateway.mjs:154-169`：`extension_ui_request`（select/confirm/input）——**AUTO_APPROVE=1 时网关立刻抢答**（select→options[0]，:158），ui_request 事件**不进 eventQueue**，runner 无感知；AUTO_APPROVE=0 才转发前端（:162-168）
- 语义：eval 网关 AUTO_APPROVE 必须开（防 permission 弹窗挂死，D7），但开了 ask_user 就被抢答——**现状二选一无解，须加第三态**（见 design）
- 需注意：抢答发生在网关，`POST /ui-response` 通道已存在（:794），runner 侧模拟应答可复用该通道

### traceId 缺口
- `eval/langfuse_binding.ts:200,206`：skippedNoTrace 计数——"当前 runner 未存 per-task traceId"，run 链接全跳过
- ⚠️ 同文件注释自相矛盾：:10 说 "scores 关联字段=datasetRunItemId（200 实证）"，:207 说 "实测名=datasetRunId"——深度绑定 change 10-20 活栈 400 抓回结论是 **datasetRunItemId 正确**，:207 注释是旧转录残留，施工时顺带修正注释
- traceId 获取路径（pi-harness 记忆 10-14 实测）：CH 查 `SELECT trace_id FROM events_core WHERE session_id=? ORDER BY start_time DESC LIMIT 1`，langfuse_writer.ts 已有该能力——runner 每题结束后（sid 已有）调 writer 查询落 results

### /events 身份未焊死
- `prism-api/main.py:267-306`：post_events 直采信请求体 local_id，未过 `resolve_user_id`（token 覆盖）——全站唯一例外（/chat /session 等 6 处都有）
- token=HttpOnly cookie（sendBeacon 同源自动带），服务端可直接解；`resolve_user_id` 在 main.py:531
- 测试参照：`prism-api/tests/test_auth.py:102`（token 用户名优先于自报值）

### 判分扩展面
- `eval/trap_check.mjs:83` switch(trap_type)：已有 skill_must_trigger/must_not/phase1_stop 等；多轮新增 3 类一票否决（附和/串味/残留）需加 case
- `scoring-rules.json` 外置容差：多轮锚点仍是数字锚，预计零 schema 变更（施工时确认 per-turn 容差是否需要独立条目）

## 题库落库面
- `eval/tasks.json` 63 题、0 题带 turns（grep 实证）；新格式与既有 `{message,truth?}` 向后兼容（方案 §10）
- 金标锚已在卷册（14 行锚点总表，快照可复算）；multi-03 t3 快照依赖已标注（九月空窗，快照轮换须重验）

## 待验证项（Step5 施工首步核）
1. eval 网关（9201）spawn pi 是否带 `--approve`（决定关 AUTO_APPROVE 后 permission 弹窗会不会真到达网关层）
2. CH 凭据/连通：traceId 查询在 eval 实例环境可用（langfuse.json clickhouseUrl）
3. `PRISM_LANGFUSE_BINDING` 现值（深度绑定 fail-soft 开关，批跑时确认开）

## 风险
- **批跑烧钱**：12 题×2-4 轮全量跑≈既有 60 题 1/5 体量+多轮 token 累积，冒烟先单题、全量批跑等用户点火（预算帽 12M tokens 方案 §8）
- **快照语义**：m03-t3 依赖"最新=8月末"，若批跑前快照轮换则该题锚点失效——批跑与快照状态绑定检查入验收
- 既有 60 题判分零回归是硬门槛（新机制不得改变单轮题行为——向后兼容是方案 §10 明文）
