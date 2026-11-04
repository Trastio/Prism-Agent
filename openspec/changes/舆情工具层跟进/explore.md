# 舆情工具层跟进 · Step1 explore（2026-10-20）

## 起因

舆情项目三连改（采集降本 9f25c27 / 前端收敛 b09160b / 缺陷簇闭环 3feca8b）后，核验 Prism 工具/harness 对接面是否需要跟随。结论：harness 主体（护栏/验证/出口闸协议）不受影响，工具层三处跟进（①口径真实性 ②能力缺口 ③文案），立项本 change。

## 核验事实（全部当日实测，行号可查）

### 对接面健在
- Prism 6 个 sentiment 工具 → 舆情 :8000 的 7 个端点，路由全部存在、签名未动：
  overview(dashboard.py:55) / trend(:584) / dim-sentiment(:1431) / top-posts(:777) /
  competitor-comparison(:963) / vehicles-events(:1399) / fleet-overview(:263)
- 出口闸 sentiment_* 溯源分支（prism-api/main.py:1036-1121）不依赖帖子保留线，口径未破
- eval 走快照实例（数据冻结 10-07），舆情三连改不碰快照 → 题库稳定

### 问题①：paused 车口径失真（红线#1）
- fleet-overview 只返回 `status=="active"`（dashboard.py:277）→ extension resolveVehicleId（index.ts:333-346）解析不到 paused 车 → 工具返回"车系 X 不在舆情系统收录范围"——**不真实**。
- 实况：Model Y paused，591 帖冻结存量在库（R42 paused 豁免保留）；4 台 inactive（元PLUS/元UP/华境s/零跑A10）0 帖。
- `_get_vehicle_or_404`（dashboard.py:28-33）不筛 status → paused 车按 UUID 直查数据端点可 200。
- 全量车名单可用：`GET /api/vehicles`（vehicle.py:85，prefix=/api/vehicles，VehicleResponse 含 status 字段，models/schemas.py:303）。
- 出口闸 `_sent_vehicle_exists`（main.py:1051）查全量 vehicles 表不筛 status → paused 车引用本来就能过闸，只有工具层解析断链。

### 问题②：缺陷簇端点未对接（能力缺口）
- `GET /defect-themes/{vehicle_id}`（dashboard.py:1611）：缺陷话题簇（中低互动帖聚类），PM 高价值信号，10-20 缺陷簇闭环 change 的核心产物。
- **TTL/窗口机制（关键）**：TTL 24h，命中条件 `age<86400 && row.window_start==start && row.window_end==end`（窗口字符串精确比对）；采集侧 Phase8（collection.py:111-125）每日落**显式 30 天窗**行（today−29~today，isoformat，archive.md:11 三入口同算法）。
- **坑（若不处理会复发窗口互踩）**：调用不传 start/end → 回退 `_WINDOW_DAYS` 默认 7 天窗（defect_miner.py:43，.env 未设 DEFECT_WINDOW_DAYS）→ 与 Phase8 行窗口不匹配 → TTL 不命中 → 重算（7 天窗）+ 全量覆盖权威行 → 正是 10-20 change 治的"互踩"复活。
- **正解：工具显式传 `today−29 ~ today` 同算法窗** → 与 Phase8 行字符串一致 → TTL 命中零 LLM；当日 Phase8 未跑时触发一次同算法自愈重算（与"端点自愈"设计一致）。
- LLM 失败保旧载荷（degraded 语义），judge 带车型锚——10-20 已治，Prism 透传即可。

### 问题③：trend 口径注记（文案）
- R40 30 天保留线后，trend 传 days>30 只返回保留线内数据且无告知；工具描述（index.ts:412）未提保留线。

### 车池实况（当日直查）
21 active（含**铂智3X 298 帖**——新题库 cross-08/09/10 用车，舆情侧有数据可锚）+ Model Y paused + 4 inactive 0 帖。

## 影响面与红线

- 全部改动落在 Prism 侧两个文件：extension index.ts + main.py（+测试），**零接触舆情仓库**（其工作树有用户未提交改动）。
- 红线#1（数据真实性）：①的直接依据——"未收录"是假话，真实是"收录但冻结"。
- 红线#3（权限）：defect 端点 GET 会触发"重算+落库"（读时自愈设计），Prism 调用属查询缓存刷新语义，非采集触发；成本由 TTL 24h 封顶。

## 风险

1. defect 首调可能触发一次重算（烧 GLM）——与端点自愈设计一致，可接受。
2. **eval 快照实例带新工具的风险**：快照 defect_themes 行 computed_at 老化 >24h → agent 调用会在快照库上重算+写+烧 LLM，判分不稳定。缓解：eval 网关（9201）**不随本 change 重启**（工具面隔离，eval 实例看不到新工具）；不放 defect 题；记录在案。
3. 30 天线滚动删除帖子 → agent 引用的帖 ID 后续被删 → 闸正确拒（fail-closed 语义自洽，同轮内不发生）。
