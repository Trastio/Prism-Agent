# tasks · 多轮评估批 change（Step5 施工单）

> 施工者须知（fork 型）：第 0 步先 ToolSearch 全量列举工具面——**无 Bash+Read+Write/Edit 则立即报 NO-TOOLS 退出**（不尝试用 web 工具绕路，主会话会重派）。全程绝对路径写文件。红线：判分主干不动；生产网关(9200)/生产行为零变化；既有 60 题零回归；测试红绿先行。交付双保险：结果写 `openspec/changes/多轮评估批/施工报告.md` + 返回文本摘要（fork 会话无 SubagentHandback）。

## T0 施工首步核验（explore 待验证 3 项，结论写进施工报告）
1. eval 网关 9201 spawn pi 是否带 `--approve`（grep pi_gateway.mjs spawn 参数）→ 决定 ui 超时兜底是否必须；
2. `.pi/agent-minimal/langfuse.json` 含 clickhouseUrl/clickhouseAuth（traceId 查询可用性）；
3. `PRISM_LANGFUSE_BINDING` 当前值（冒烟时开）。

## T1 挂题（12 题落库）
- 卷册 `核心文档/05-多轮题卷册-12题-审阅版.md` → tasks.json 新 12 条（schema 见 design §1：multi-01~12，dimension=多轮，set=dev，turns/variants/branch_on 如卷册，new_session 标 multi-09/10 t2，abort_after_turn 标 multi-11 t1=1/multi-12 t1=1，ui_strategy 挂 skill-03）
- 金标 diff 表落 `openspec/changes/多轮评估批/金标diff表.md`（12 题逐锚 vs 卷册，含快照 SQL 口径）
- 验收：`node --check` + 总数 63→72 + diff 表零差异 + m03-t3 带 snapshot_dependence 标注

## T2 runner 三机制 + Sheet4（design §2）
- resolveMessage/branch_on 选支/carryCheck（归一化：去千分位+全角）+ crossCheckRows 接实值
- 验收：单测（分支选择 2 例/话术轮换 2 例/漂移判定 3 例：同值/漂移/不复现）+ Sheet4 测试更新（占位注记→实值断言）

## T3 ask_user 第三态（design §3）
- pi_gateway：`PRISM_EVAL_UI_SIM=1` 分支（不抢答，推 eventQueue）；eval 服务注册表（prism.py eval start）注入该 env
- runner：ui_request 事件消费 + ui_strategy 响应 + 无策略默认代答 + 30s 超时兜底 + 事件/响应记 turnResults
- 验收：单测（默认代答等价性/策略响应/超时兜底）+ 生产网关无 env 行为逐行不变（diff 证明）

## T4 traceId 补存（design §4）
- runner 末尾 CH 查询（复用 writer 函数）→ results.traceId；binding.ts:207 注释修正
- 验收：CH 不可达 fail-soft 单测 + 注释 diff

## T5 /events 焊死（design §5）
- main.py post_events 请求级 resolve_user_id 覆盖；test_auth.py 加"自报被覆盖"用例
- 验收：pytest auth 组全绿 + 未登录 401 行为不变

## T6 trap 3 类 + scoring-rules 词表（design §6）
- trap_check 3 新 case + scoring-rules.json `multi_trap_lexicon`
- 验收：3 类各红绿一例（构造附和/串味/残留样本 reply）

## T7 全量回归 + 冒烟（真跑，烧少量 token）
- 判分单测全套 + 60 题判分零回归（离线 replay 判分，不真跑 60 题）+ smoke:all
- 冒烟真跑：multi-05（双轮缺口）+ multi-11（abort 链路）+ skill-03 复跑（ui_strategy 生效，问询事件入轨迹）
- 验收：三题 verdict/判分输出落施工报告；traceId 冒烟非空

## 并行簇与顺序
T0→T1→T2→T6（判分层）串行；T3/T4/T5 相互独立可并行；T7 收口。全绿后 Step6 simplify → Step7 隔审 → Step8 处置 → Step9 总验证 → Step10 归档。
