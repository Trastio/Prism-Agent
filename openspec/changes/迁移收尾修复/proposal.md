# 迁移收尾修复 · proposal

## WHY
数据源自给化迁移（10-08）修通主链路后残留五处断链：三看板车系入口不可达（产品级断点）、看板 as_of 硬编码过期、会话重命名前端调后端 404、数据源注册表舆情探活用旧路由形态。均为"组件在、线没接"级别，集中一个 change 收口。

## WHAT（五项）

### C2 series 全链接线（iframe 形态方案）
1. `lib/series.ts` 新增：`pushRecentSeries/getRecentSeries`（localStorage `prism_recent_series`，去重、unshift、cap 8）——修"只读不写"。
2. `Sidebar`：补"会话|车系"双 tab 切换按钮（当前车系 tab 无 UI 出口）；`onSelectSeries` 签名扩为 `(name, seriesId?)`（核验命中带 id，最近车系/歧义候选不带）。
3. `App`：提升 series 状态 `{name, id?}`；三路来源——侧栏核验选中、最近车系点击、**对话工具调用检测**（ChatView 从 tool_call args 提取 series_key 上抛 `onSeriesDetected`）；任何一路更新都写最近车系；侧栏选中即切看板视图。
4. 看板带参：口碑 `/dash/koubei?q={name}`；配置 `/dash/config?series_id={id}&load=1`（有 id 时）；市场页无参数支持→不带（记录限制）。
5. **单向流动**：series 状态不回传 chat（对话重构后 agent 自主 resolve_series，回传会重新引入跨轮污染）。

### C3 as_of 实时化 + 刷新 + ChatView 文案
1. main.py 新增 `GET /dash/as_of`：直读 AUTOHOME_DB——销量 `最新(year, 月末)` + 口碑 `MAX(post_date)`；注册在 `/dash/{path:path}` 反代之前。
2. `KanbanView`：as_of 改 fetch 该端点；刷新按钮 → `reloadTick+1`（EmbedBoard/SentimentBoard 重载 iframe + 重探活）+ as_of 重取。
3. `ChatView` 文案 PM 化：hero 副标、SUGGESTIONS 改业务问题（带/不带 series 两态）、composer placeholder。

### B4 rename 后端（names.json sidecar 方案）
- pi_gateway：`names.json` 读写 helper；GET /session 合并 `custom_name`；新增 POST /session/rename（校验 user_id/session_id/name + 文件存在）；POST /session 带 title 镜像进 sidecar。不动 RPC（切会话竞态）。
- main.py：POST /session/rename 转发网关（vite `/session` 前缀代理已覆盖）。

### C1 sentimentCoverage 修正
- datasource.ts：两步探测——`GET /api/vehicles/search?q=` 取 id → `GET /api/dashboard/overview/{id}`；registry endpoints 清单更正为 `/api/dashboard/*`。

### E EvidenceDrawer：报不接线（沿死码清理裁决）

## 决策记录
| # | 决策 | 理由 |
|---|---|---|
| 1 | series 经 URL 参数进 iframe，非 prop 下传 | 三看板已 iframe 化，prop 方案失效；子服务口碑/配置页原生支持 query |
| 2 | series 状态单向（chat→App→看板），不回传 chat | 保持对话重构"agent 自主核验身份"设计，防跨轮污染回潮 |
| 3 | rename 走 sidecar 非 RPC set_session_name | RPC 仅作用于活跃会话，切来切去与在途对话竞态；列表显示只认 sidecar 单一真值 |
| 4 | as_of 新增端点而非前端算 | iframe 无数据上抛通道；main.py 直读主库与 /dashboard 同源同口径 |
| 5 | 市场看板不带车系参数 | 子服务市场页无 query 支持；改子服务模板超出收尾范围 |

## 影响范围
prism-web：App/Sidebar/KanbanView/ChatView/EmbedBoard/SentimentBoard/ConfigBoard/ReviewsBoard/MarketBoard + 新 lib/series.ts；prism-api：main.py/pi_gateway.mjs；src/registry/datasource.ts。不碰红线层（extension/verify/工具白名单）。

## 验收
1. 侧栏"车系"tab 可达；搜索核验命中 → 自动切看板且口碑/配置看板带该车系参数加载；最近车系出现且高亮。
2. 对话里分析某车系后，"最近车系"出现该车系；切到看板带参。
3. 看板顶部 as_of 为实时值（销量最新月末 + 口碑最新日期），非 2026-10-04；刷新按钮重载当前看板。
4. 会话双击重命名生效：列表显示新名（custom_name）。
5. `node src/registry/smoke.ts` 舆情 coverage 探测走新路由（服务在跑时 hit/miss 如实返回，不 crash）。
6. 根 tsc 零新增 + web tsc 0 错 + vite build 通过 + smoke:all 通过。

## 不做
- 市场看板车系外链（子服务模板改造，另立项）
- EvidenceDrawer 接线（方式未定）
- 对话 series_key 回传（架构决策，见决策 2）
- pi RPC set_session_name 对已有会话（决策 3）
