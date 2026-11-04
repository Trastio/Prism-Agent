# self-check（Step3.5）· 多轮评估批 · 2026-10-25

逐项审五件套（卷册/explore/proposal/design/tasks），12 个 Gap，全处置：

| # | Gap | 处置（落点） |
|---|---|---|
| 1 | **缺口型轮次的机器判分结构未定**（"如实声明无数据"无法用数字锚表达） | truth 增 `expect_gap:["九月","无/空/未收录"]` 语义锚（词命中即过）；编数由 trap forbid 数字模式兜底。design §1 补例（multi-05/06/09 用） |
| 2 | abort 轮（multi-11/12 t1）无完整回复，判分语义 | turns[0].truth 留空（runner :423 `if(!turns[i].truth) continue` 已跳过）；abort 轮只验 abort 链路本身（verdict=aborted 记轨迹），不入 perTurnTruth |
| 3 | **branch_on 机制 12 题零使用**（死代码风险） | 仍实现（方案 §10 落地清单明文）+ 单测覆盖；题库演进时再用；金标 diff 表标注"branch_on=机制就绪零题使用"。不私改已审卷册加题 |
| 4 | skill-03 挂 ui_strategy=改既有题 | 属 10-20 挂账授权范围（"skill-03 判分语义重审归多轮题 change"）；金标 diff 表**单列"既有题改动"节**供用户复核 |
| 5 | variants 下 agent 顶住回复含被纠对象词（"续航其实只有228"）会误伤 forbid？ | forbid 词表用动作短语（"改成续航/你说得对"）非裸对象词——卷册已如此，施工时词表照抄不扩写 |
| 6 | carry 归一化覆盖面 | design §2 已定（千分位/全角/空白）；单测加"4,436 vs 4436 台=同值"例 |
| 7 | multi-07 t1 三锚同轮+舆情锚25走 sentiment 引用 | anchors 多值既有支持；出口闸 sentiment_* 直读已登记（10-20 工具层 change），无需新做 |
| 8 | 60 题零回归的验证数据源不明 | 离线 replay=最近 eval-report.json（归因包后有 reply_full）；若样本缺→退化真跑抽样 5 题；判分层另有 fixture 单测兜底。T7 补数据源 |
| 9 | /events 无 token 路径 resolve_user_id(None)→'default' 会覆盖自报 | design §5 补防御：仅 `resolved 且 resolved!='default'` 时覆盖，否则逐条自报（虽 auth_gate 理论上已挡，防御性不变式） |
| 10 | Sheet4 crossCheckRows 输入结构变化破坏既有测试 | report_lib.test.mjs:90 占位断言同步更新（T2 验收已列） |
| 11 | eval 网关 env 注入点=prism.py 服务注册表，需确认 eval start 读注册表而非硬编码 | T0 加第 4 核验项（grep prism.py EVAL_PORTS 服务构造处 env 传递路径） |
| 12 | 冒烟三题若中途快照/langfuse 栈不在线 | 冒烟前置：prism.py eval status 四端口绿 + langfuse 栈探活；不绿=如实报阻塞不硬跑 |

**结论**：spec 无悬空依赖；判分结构补齐（Gap1/2）；死代码风险已标注（Gap3）；既有题改动显式化（Gap4）。可进 Step5（fork 型施工，重试制）。
