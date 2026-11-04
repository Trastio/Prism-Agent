# 北极星看板与badcase四象限 · Step2 proposal（2026-10-13）

## WHY

- 采集管道已通（tracker.ts 8 类事件 → prism_events.db → /events/stats 实时 SQL），但**零消费者**：北极星四个代理指标的 SQL 躺在裸 API 里，没有任何页面展示。设计指定的"北极星看 langfuse dashboard"当前不可用（栈停着、插件未装回、且 langfuse 不收前端行为事件，DAU 类指标它做不了）。
- badcase 界定目前只有两条官方渠道（trajectories verdict=fail 每周翻 + 👎 点踩），**两条都没被交叉使用**；且 explore 实测 trajectories fail 率 68%（675/990，含回灌/保底/闲聊轮）——不归一就直接用，每周翻 fail 会被淹没。
- 本 change 把"分析我们自己产品用户"的埋点闭环收口：**采（已通）→ 看（北极星页）→ 挖（四象限+回放入口）**。

## WHAT

四块：
1. **后端指标扩展**（main.py）：ts 窗口修复 + stats 扩展（总 DAU/采纳率/人均结论数/轮时长）+ 新端点 /events/trends（逐日趋势）+ /badcases/quadrant（四象限聚合+明细）
2. **前端北极星页**（prism-web）：第三视图 + 侧栏入口 + KPI 行 + DAU 双线趋势 + 周结论柱图 + 四象限块 + 明细表（点开抽屉回放）
3. **采集小加固**：tracker.ts 加 60s 兜底 flush
4. **badcase 台账**：eval/badcases.md 初始化（空台账+格式+处置流程，种子不填——现有 fail 多为开发期测试会话，无分析价值）

## 决策（D1-D10，按推荐执行，可否决）

| # | 决策 | 推荐 | 理由 |
|---|---|---|---|
| D1 | 页面命名与可见性 | 侧栏入口"北极星看板"，全员可见 | 内部工具期无敏感数据（纯计数）；纯 GET 不过 manager_auth；页脚注口径说明；上云前再收口 |
| D2 | ts 窗口修复 | **查询侧 `julianday(ts)` 统一转换**，存量不动 | 两种格式（ISO+Z / 空格式）julianday 都能解析；7k 行规模索引牺牲可接受 |
| D3 | 四象限终轮归一 | 每 session 取**最后一条 chat_settled 的 verdict** | events 库内自洽，无需碰 trajectories；重试轮 settled 也会发事件，最后一条=终轮结果 |
| D4 | 采纳口径 | 展示原始计数 + 三比率：采纳率 up/settled₇d、点踩率 down/settled₇d、净采纳 (up−down)/settled₇d；"成功结论数"=settled₇d−down（近似，页面注明） | 对齐北极星定义"被采纳未点踩的结论数"的最近可行口径 |
| D5 | 逐日分桶时区 | `date(ts,'localtime')` 本地日 | 中国用户直觉；UTC 日会把晚 8 点后算次日 |
| D6 | 系统自报信号 | 轻量版：只做**轮数信号**（session 内 settled ≥3 标"多次重试"）；保底触发/verifyNames 自纠留 v2 | events 表无 reason 列，扩埋点超本 change 范围 |
| D7 | badcase 台账 | 建空台账+格式模板+处置流程，不填种子 | 原设计"轮2启动时建"；本 change 顺带立骨架，四象限页是其数据入口 |
| D8 | 轮时长口径 | 每 settled 配对其之前最近的 chat_start，ts 差=轮时长；展示中位数+P90；abort 轮无 settled 不计 | 免新埋点；重试轮无新 start 会配到更早的 start → 时延偏大，页面注明"含验证重试"（诚实口径） |
| D9 | 回放形态 | 明细行点击 → 右抽屉（复用 EvidenceDrawer 样式）拉 /trajectory/{sid} 渲染：结论全文+verdict_reason+工具列表+轮次摘要 | 摘要级够用；完整逐消息 JSON 已有 API 兜底 |
| D10 | tracker 兜底 | setInterval 60s flush | 把普通事件最坏 2.5min 压到 60s，覆盖"心跳被空闲判定暂停"边缘情况 |

## 影响范围

- **prism-api/main.py**：/events/stats 扩展 + 新增 /events/trends、/badcases/quadrant（纯 GET，不碰 WRITE_ENDPOINTS_PREFIXES）
- **prism-web**：App.tsx（View 联合类型+view-stack）、Sidebar.tsx（入口+Props 扩）、新 MetricsView.tsx、新 BadcaseDrawer.tsx、tracker.ts（+60s flush）、vite.config.ts（+/trajectory /attribution /badcases 三条代理）
- **eval/badcases.md**：新建
- **不动**：extension index.ts、pi_gateway.mjs、AGENTS.md、trajectories 写入逻辑、工具面

## 风险

- R1 **并行会话共用门禁栈**（人工题集转金标 Step9 未完）：跑 smoke/门禁前先查 logs/ 网关重启记录，错峰执行
- R2 手造脏数据（usr_test1/s1 等 4 行）污染指标：页面脚注标"含开发期测试数据，2026-10-06 起"；不做过滤（过度设计）
- R3 DAU 语义边界（local_id 自报、清缓存重计）：页面口径脚注说明，鉴权留上云前
- R4 时延配对误差（abort 轮/重试轮）：D8 已注口径，best-effort
- R5 _shared.tsx 图表组件是否支持双序列未知：Step5 按实际 props 适配（必要时两条单序列图替代），不新造图表库

## 验收标准（Step9 用）

1. **ts 修复可复算**：任选一个日期边界，stats/trends 数字与手工 SQL（julianday 口径）对账一致
2. 北极星页 7 指标渲染真数据：看板 DAU / 对话 DAU / 总 DAU / 周结论数 / 采纳率 / 人均结论数 / 轮时长中位+P90
3. **四象限聚合数=手工 SQL 对账一致**；终轮归一生效（同 session 多轮只计最后一条）；明细可点开抽屉回放（结论+verdict_reason+工具列表）
4. 空态优雅：feedback 0 条、trends 全 0、latency 无样本（NaN 防护）三种情况不崩
5. 60s 兜底 flush 生效（浏览器验证：不发满 5 条的事件 ≤60s 可见于 /events）
6. smoke:all 全绿 + web tsc 零新增错 + build 通过
7. UI 走查通过（tabbit/CDP：入口可达、视图切换不丢状态、30s 轮询+手动刷新）

## 不做边界

- langfuse 接线（独立 change，方案已定稿半天，管评估 trace 侧）
- 弹窗两问/周访谈/种子群（提纲阶段⑤，上线后）
- user_id 鉴权（上云前风险清单）
- token 成本聚合（pi session jsonl 的 usage 未入行为库，v2）
- 保底触发/verifyNames 自纠信号（需 events 加列，v2）
- LLM 语义归因（现有 /attribution 规则归因够初筛，v2）
