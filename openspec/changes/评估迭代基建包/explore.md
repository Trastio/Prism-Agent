# 评估迭代基建包 · Step1 explore（2026-10-14）

> 起因：用户拍板"先把基础设施做好（含 langfuse 提前）"再首跑。本 change = 方案 §10.0.1 的 L1-0+L1-3+L1-4+L1-6 全部工程 + langfuse 接线全包。
> 本文事实全部为 2026-10-13/14 实测（含代码级核验），防重复推导。

## 1. 现状：就绪 vs 缺口（全栈盘点结论）

**已就绪（不动）**：60 题卷子+金标 131 断言+生成器裁决覆盖层（幂等）/快照哈希指纹+eval 四实例/trap 六类正则+12 单测/verdict 判分（E2E 实证）/smoke 七模块/stats.py 四条件引擎（代码完整）/北极星+ops:8020/git 版本控制。

**本 change 要补的缺口（12 项，全部有代码级定位）**：

| # | 缺口 | 定位 | 证据 |
|---|---|---|---|
| 1 | langfuse 全链未接 | 栈停（3000 不通）；packages 4 个无 langfuse 插件（.pi/agent-minimal/settings.json）；writer=console.log 占位（eval/langfuse_writer.ts:43）；release 停 phase2-m5 | 10-13/14 两轮实测 |
| 2 | eval 与生产共用 trajectories.jsonl | extension index.ts:781 `resolve(cwd,'.pi/sessions/trajectories.jsonl')` 写死；runner.mjs:44 同路径读 | 303MB 且批跑会混入北极星统计 |
| 3 | trap-07/08 value_grounding 判分未接 | trap_check.mjs switch 六类无此类别→default fail-closed 0 分 | 10-13 trap 批跑 2 个假 0 |
| 4 | runner 无 --set 过滤 | runner.mjs:32 仅 --only | 冻结侵蚀风险 |
| 5 | 判分链无金标数字比对 | runner.mjs scoreTask 只查合规要素（evidence/as_of/越界/trap），不比数字 | r3 72%=合规率非正确率 |
| 6 | 中间档/六分制/8态未落 | scoreTask 5 分起步降档制，无 rubric 机器化 | 方案 §十一 契约在、代码无 |
| 7 | 条件题仅社媒特判 | runner.mjs:90 isSocialTask 硬编码；config-03/04 PTC 真打 web 且计分母 | 不可复现 |
| 8 | 无 per-题超时/成本台账 | runner fetch 无 timeout（仅 tikhub 探测 5s）；无 token/时长记录 | 卡死题拖垮批跑；四条件之四无原料 |
| 9 | 舆情题时间保质期 | extension sentiment_trend：`new Date()` 算窗口，快照数据止 2026-10-07 | ~11-06 后 30 天窗脱锚 |
| 10 | query_sales month 参数摆设 | /dashboard/sales 两分支静默忽略；工具描述仍写 month(1-12) | Block1 金标已实测 |
| 11 | 多轮题无 runner 基建 | 任务 schema 无 turns；runner 单消息；无逐轮判分形态 | 60 题全单轮 |
| 12 | stats↔ci 脱节 + verifyNames 误报 + mapEvent 缺 auto_retry | ci.sh 文案停"16 题"、四条件从未跑真数据；verifyNames 普通词撞维度名（改阈值破 8 case）；mapEvent 无 auto_retry | 历次 change 留下一轮 |

## 2. langfuse 关键事实（10-13 验证，接线依据）

- 栈：Desktop\langfuse 官方 compose（langfuse:4 web3000/worker3030+clickhouse+postgres+redis+minio），镜像全本地；**（10-14 sub-A 实测修正：真评分路由=POST /api/public/scores+Basic pk:sk→200；早前"legacy 201"记忆过时；public traces 404→writer 直查 ClickHouse）**；**pi 插件原生 OTLP（@langfuse/otel）→ v4 直通**，trace 自动流入，无需 dual 桥
- key：langfuse.json pk/sk 有效（差分实证：错 key 401/真 key 201）
- 接线四件：①settings.json packages 装回插件 ②writer 真实现=score 走 legacy API 挂插件 traceId+eval_run_id ③实例标签（生产 9200 vs eval 9201 environment 区分，防混流）④release phase2-m5→代际化（跟 agent_version 0.3.0/change 代际）
- 存活：需容器 restart 策略 + Docker Desktop 自启拍板（10-13 栈死过一次的根因）
- **排序修正依据**：trace 不可回溯——判分可事后补算，观测错过即失；轮 1 归因阶段即可受益（UI 过滤/回放/annotation）

## 3. 已定决策与待拍板

- 消融不做（触发条件留档）；保留集=frozen（L1-6 落文）；判分规则外置可调（首跑后微调不动架构）
- **待用户拍板（不阻塞 Step1-3）**：①舆情保质期 A（eval 固定今天=快照 as_of，荐）/B（金标相对窗口）②Docker Desktop 自启 ③首跑改基建后是否接受
- 出题分工：多轮业务题=用户出 3-5 道（L1-5，本 change 只做基建）

## 4. 风险与注意

- 并行会话活跃（配置赋值/北极星两 change 同期），prism-api 行号已漂两次（731→885）——**每次编辑前 grep 锚定**；评估资产变更走 git
- trap_check 契约：改实现必须先改测试（trap_check.test.mjs 头注）；L1-0 第一件曾开工被并（测试追加了一半未落盘，Block B 重做）
- 批跑纪律不变：冻结服务/单进程；本 change 完工前不跑正式首跑
- writer 联调依赖真实跑一题看 UI trace 带评分（两阶段联调第二步）——安排在 Block A 验收
