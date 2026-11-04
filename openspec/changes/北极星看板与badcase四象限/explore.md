# 北极星看板与badcase四象限 · Step1 explore（2026-10-13）

> 目标：①北极星指标可视化页面（现状=裸 API 零 UI）②badcase 界定扩层——verdict×👎 四象限 + 系统自报信号。全部结论为当日文件级/运行时实测，file:line 或 SQL 可复验。
> 定位澄清：本 change 是"分析我们自己产品用户"的埋点闭环收口（采集已通→看板+badcase 入口）。langfuse 接线是**独立 change**（方案已定稿半天，管评估 trace 侧），不并入。

## 1. 数据层实况（prism_events.db，项目根，2026-10-06 起 7 天）

- **7088 行 / 8 类事件**：active_tick 6137（86%，心跳是体积大头也是"活跃时长"原料）/ page_view 795 / session_switch 63 / chat_start 40 / chat_settled 35 / session_rename 15 / feedback 2 / chat_abort 1
- 9 local_id / 10 session_id，**多为测试号**（usr_test1/usr_v/s1/sess1 为手造行）；chat_settled 自带 verdict 值（pass 26 / fail 9）——机器判定已入行为库
- 活探活：`GET /events/stats` 返回真数据（dau 4 / chat_dau 1 / weekly_conclusions 35 / feedback 0up 2down），服务在跑

### 实测发现的坑
- **坑① ts 格式混用**：7084 行 ISO+Z+毫秒（len 24）vs 4 行手造 len 19。stats 里 `ts >= datetime('now','-1 day')` 是**字符串比较**：datetime() 返回空格分隔格式，与 'T' 分隔的 ISO 串比较时同日恒成立（'T'0x54 > ' '0x20）→ **DAU/周结论数是近似值**。修法二选一：入库时归一格式，或查询侧 `julianday(ts)` 转换（不动存量数据，推荐）
- **坑② feedback 全是测试行**：真用户点踩 0 条（2 条 down 均为手造）——四象限上线前数据是空的，页面要能优雅展示空态

## 2. 四象限数据源验证（join 实测）

- **events 库内可自洽**：feedback(session_id+ts+value) × chat_settled(session_id+ts+verdict)——👎 对齐"同 session 内 ts 早于 feedback 的最近一次 settled"即可定象限，**无需碰 trajectories**（trajectories 只在点开回放时用）
- join 现状：events 10 session ∩ trajectories 200 session = **5**。不匹配原因：手造行 + 旧格式 id（`usr_ccim9hzf`、复合时间戳前缀 id）+ 埋点 10-06 才上线而 trajectories 覆盖更早
- **坑③ fail 率口径爆炸**：trajectories 990 条中 fail 675（68%）vs events settled fail 9/35（26%）。trajectories 每轮一条（含回灌轮/保底轮/闲聊轮），"verdict=fail 即 badcase 候选"**不可直接用**——必须终轮归一（每 session 取最后一轮，或排除 isVerifierRetryTurn/保底轮）。这是四象限列表的前置清洗，方案在 Step2 定
- 轮对齐：feedback 无 turn 标识，只有 ts——用"最近前置 settled"对齐（同上），设计时写明误差（点的是上一轮还是上上轮无法区分，接受）

## 3. API 层现状（prism-api/main.py）

| 端点 | 位置 | 现状 | 缺口 |
|---|---|---|---|
| POST /events | :120-159 | 批量入库+双道脱敏 ✅ | — |
| GET /events/stats | :162-194 | 4 指标快照（dau/chat_dau/weekly_conclusions/feedback） | 无趋势序列、无采纳率分母、无人均结论数、无响应时延；ts 坑① |
| GET /trajectory 列表 | :626-649 | session 去重+verdict+结论预览 ✅ | O(n) 全扫（990 行无压力） |
| GET /trajectory/{sid} | :605-623 | 逐条回放 ✅（注释标"人工消费面"） | — |
| GET /attribution/{sid} | :657+ | 五维归因=**规则推断**（resolve_series 有无/顺序/工具集），非 LLM 归因 | 初筛够用，语义归因留 v2 |

- **/events/stats 零消费者**（grep 证实：前端只有 tracker.ts 写 /events，无任何读方）——"裸 API"实锤
- manager_auth 中间件（:61-70）只拦写端点（WRITE_ENDPOINTS_PREFIXES）：北极星页纯 GET 不受影响；若 badcase 状态标记要写库会过密码门（开发期未设密码放行）
- **响应时延免新埋点**：chat_start 与 chat_settled 成对（同 session），ts 差=轮时长，查询侧派生即可
- 成本（token）指标：pi session jsonl 有 usage 但未聚合到行为库——标 v2，本 change 不做

## 4. 前端挂点（prism-web）

- View 类型 `'kanban' | 'chat'`（App.tsx:20）+ view-stack display:none 保活（App.tsx:116-119）→ 加第三视图 `'metrics'` 顺势
- Sidebar sb-nav 现有三项（新建会话/棱镜工作台/能力总览，Sidebar.tsx:81-92）→ 加"北极星/运营"入口，模式现成
- 图表组件 _shared.tsx（KpiGrid/AreaChart/BarChart/HBars/Card）现成可复用，DAU 双线/周结论柱图零新依赖
- vite proxy：`/events` 前缀已代理（vite.config.ts:29，**stats 免改**）；`/trajectory`、`/attribution` 未代理需加两行

## 5. langfuse 实况（今日实测，独立 change 素材）

- **:3000 当前不可达**（curl 000）——Docker Desktop 未运行；10-13 曾拉起又停；"开机自启"仍是留用户决策项
- 插件未装回（.pi/agent-minimal/settings.json 仅 4 包）；langfuse_writer.ts（eval/）writeEvalTrace=console.log 占位
- **定位确认**：langfuse_writer 的 EvalTraceFields 设计的是评估字段（eval_run_id/score/failure_dims/cost），非业务指标；page_view/心跳类前端事件 langfuse 不收 → **北极星不能唯一押 langfuse，自建页为主、langfuse 为评估侧补充**（与之前双轨推荐一致）

## 6. badcase 台账与并行会话

- eval/badcases.md 不存在（设计=轮2启动时建）；EVAL_STATUS.md 在（门禁台账）
- **另一会话并行施工"人工题集转金标"change**（Step5 双施工完、活端点留 Step9）——本 change 动的文件（main.py 加端点 / prism-web 加视图）与其无重叠，但**共用 smoke 门禁栈**：跑门禁前先查网关重启记录（并行碰撞历史教训×2）

## 7. 差距汇总（Step2 输入）

| # | 差距 | 归属 |
|---|---|---|
| G1 | 北极星页：第三视图+侧栏入口+4 KPI+DAU 双线+周结论趋势 | 前端 |
| G2 | /events/stats 扩展：N 天趋势序列、采纳率（up/settled）、人均结论数、轮时长派生；ts 归一（坑①） | 后端 |
| G3 | /badcases 四象限列表端点：events 库 join+终轮归一（坑③）+回放跳转 | 后端 |
| G4 | 前端四象限表+点开跳 /trajectory 回放+空态（坑②） | 前端 |
| G5 | vite 代理 /trajectory /attribution 两行 | 前端 |
| G6 | 系统自报信号（保底触发/回灌轮数）入列表：verdict.json/trajectories 派生 | 后端（可标 v2 先做数据可得性确认） |
| G7 | eval/badcases.md 台账初始化 | 流程（种子=现有 fail 样本，或按原设计留轮2） |

## 8. 不做边界

- langfuse 接线（独立 change，方案定稿）
- 弹窗两问/周访谈/种子群（提纲阶段⑤，上线后）
- user_id 鉴权（上云前风险清单已有）
- token 成本聚合（v2）
- LLM 语义归因（v2，现有规则归因够初筛）
