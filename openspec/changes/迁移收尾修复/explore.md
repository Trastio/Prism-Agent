# 迁移收尾修复 · explore（2026-10-11 实测）

> 前置：死码清理与归档搬移 change 划定的 C1/C2/C3/B4/E 五项，本 change 施工前逐条实测核实。
> 结论：**两项实况与原记录不一致**（C2 断链更深 + iframe 化推翻旧方案），一项范围扩大（C3 的 as_of 需新端点），B4/C1 实况与记录一致。

## 逐项实况

### C1 sentimentCoverage URL（实况一致）
- `src/registry/datasource.ts:182` 用老形态 `/dashboard/overview?vehicle_name=xxx`。
- prism-sentiment 真实路由：`api/routes/dashboard.py:55` `@router.get("/overview/{vehicle_id}")`，router prefix `/api/dashboard`（dashboard.py:20）→ 正确形态 **`/api/dashboard/overview/{vehicle_id}`**。
- 名称→ID 解析可用：`GET /api/vehicles/search?q=`（vehicle.py:91，name/brand contains，返回 `{id, name, brand,…}`）。
- 引用面：datasource.ts 仅被 `src/registry/smoke.ts` 引用（全仓 grep 确证零生产引用）——修复保持 smoke 语义有效，不删（数据源注册表是 spec §2.2.1 资产）。
- registry `endpoints` 清单（datasource.ts:232-235）同批更正为 `/api/dashboard/*` 真实形态。

### C2 三看板 series 断链（实况比记录更深，旧方案已过时）
- **旧方案过时**：原记录设想"App.tsx 传 series prop 给三看板组件"——10-08 数据源自给化迁移后三看板已 **iframe 化**（ReviewsBoard/ConfigBoard/MarketBoard 均为 EmbedBoard 壳，`series`/`onEvidence` props 被无视）。
- **断链更深一层**：`Sidebar.tsx:70-71` 只有"会话"一个 tab 按钮，`tab` state 与 `setTab`（L24）无 UI 出口 → **车系 tab 整体不可达**（不止 App 没接 onSelectSeries）。
- **"最近车系"只读不写**：`prism_recent_series` 仅 Sidebar.tsx:178 读，全仓无写入 → 列表恒空。
- App.tsx：不传 `onSelectSeries`/`series` 给 Sidebar（L49-55）、不传 `series` 给 KanbanView（L61）、不传 `series` 给 ChatView（ChatView 已有该 prop，L51/hero chip）。
- KanbanView 已接 `series` prop 并向下传（L13/L40-42），但下游是 iframe 壳，接不住。
- **子服务外链能力实测**（prism-dashboards）：
  - 口碑页 `/dash/koubei`：支持 `?q=` 车系名包含预筛（dashboard_routes.py:147-155，筛选/排序进 URL 设计）✅
  - 配置页 `/dash/config`：支持 `?series_id=` + `?load=1`（L317-342，load=1 允许空 spec_id 自动补首个版型）✅
  - 市场页 `/dash/market`：页面路由无 query 参数（market_routes.py:72-89，series 只在内部 API）❌ 不接，记录限制
- `sendChat` 已不带 series_key（对话重构后 agent 自主 resolve）——**保持不回传**，series 状态单向流动（chat 检测 → App → 看板），不污染对话上下文。

### C3 as_of 硬编码 + 刷新死按钮 + ChatView 文案（实况一致）
- `KanbanView.tsx:31` `as_of <b>2026-10-04</b>` 硬编码；L32 刷新 icon-btn 无 onClick。
- iframe 化后看板数据无 `_meta` 上抛通道 → 顶部 as_of 需新数据源：main.py 直读 AUTOHOME_DB 计算（销量最新月末 + 口碑最新 post_date）。
- ChatView 残留：hero 副标"棱镜三维度因果链路"（工程视角）、SUGGESTIONS 全是 `query_*` 工程指令（L37-49）、composer placeholder"输入分析指令…"。
- vite proxy `/dash` 前缀已覆盖 → 新增 `/dash/as_of` 自动可达。

### B4 /session/rename 后端（实况一致，方案微调）
- 前端在调：`Sidebar.tsx:51` POST `/session/rename` {session_id, name, user_id}，列表读 `custom_name || name || id`（L38/L102）。
- 后端 404：main.py 只有 GET/POST `/session`；pi_gateway.mjs 只有 GET/POST `/session`（L519/L542）。
- pi RPC 有 `set_session_name`（仅作用于 RPC 客户端**当前活跃会话**）；网关 GET /session 列表直接 readdir，`name` 恒等于文件名 id（L530）。
- **方案决策**：rename 走 **names.json sidecar**（`SESSIONS_DIR/{userId}/names.json`，网关读写），列表合并 `custom_name`。不动 RPC switch_session（重命名非活跃会话需切来切去，与在途对话有竞态）；POST /session 建 title 时同步镜像进 sidecar。pi 自身 sessionName 仅创建路径继续用（保持 export/pi UI 一致，best-effort）。

### E EvidenceDrawer 断链（沿死码清理裁决：报不接线）
- EmbedBoard iframe 化后，看板内数字无法上抛 onEvidence（跨文档边界）→ 维持"报告不接线"，接线方式待子服务侧方案。

## 附：环境事实
- AUTOHOME_DB 默认 `prism-dashboards/data/autohome.db`（main.py:28），main.py 已有只读直连模式（`file:...?mode=ro` uri）。
- 网关 SESSIONS_DIR = PROJECT_ROOT/.pi/sessions（pi_gateway.mjs:32）；fs 函数已 import。
- 舆情 search 端点响应 id 字段名 = `id`（vehicle.py:53）。
