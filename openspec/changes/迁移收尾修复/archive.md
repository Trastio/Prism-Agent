# 迁移收尾修复 · archive（2026-10-11 完成归档）

## 落地内容（对齐死码清理 change 划定的 C1/C2/C3/B4/E）
- **C2 series 全链接线**：Sidebar 补"会话|车系"双 tab（新发现：车系 tab 此前无 UI 出口，比原记录断链更深）；App 提升 series 状态三路来源（侧栏核验/最近车系/对话 tool_call 检测）；新增 `lib/series.ts` 写 `prism_recent_series`（此前只读不写，列表恒空）；看板经 URL 参数进 iframe——口碑 `?q=`、配置 `?series_id=&load=1`、市场页无参支持（限制记入 MarketBoard 注释）。**series 单向流动（chat→App→看板），不回传对话上下文**（决策 2，防跨轮污染回潮）。
- **C3**：main.py 新增 `GET /dash/as_of`（直读主库：销量最新月末批 + 口碑 MAX(post_date)；注册在 `/dash/{path:path}` 反代前）；KanbanView as_of 实时化 + 刷新按钮接 reloadTick（EmbedBoard/SentimentBoard 同源 reload 内页）；ChatView 文案 PM 化（hero/SUGGESTIONS/placeholder，query_* 工程指令清零）。
- **B4 rename**：pi_gateway names.json sidecar（`SESSIONS_DIR/{userId}/names.json`，列表显示单一真值）+ POST /session/rename（会话文件存在性校验天然挡路径注入）+ 建 title 镜像；main.py POST /session/rename 转发。**不走 RPC set_session_name**（仅作用活跃会话，切换与在途对话竞态——决策 3）。
- **C1**：datasource.ts sentimentCoverage 改两步 `/api/vehicles/search?q=` → `/api/dashboard/overview/{id}`；registry endpoints 清单更正为 `/api/dashboard/*` 真实形态。
- **E**：EvidenceDrawer 报不接线（沿死码清理裁决，iframe 化后接线方式未定）。

## 验证结论
见 verification.md：根 tsc 零新增（11=基线）、web build ✓、smoke:all 50/50、服务级 6 项实测全过（as_of 真值/rename 链/注入拒绝/三看板带参 200）、headless 渲染 4 项确认（双 tab/as_of 进 DOM/新文案/旧文案零残留）。

## 留下一轮（非阻塞）
- 点击级端到端用户走查（对话检测链路未跑真实 agent 对话）
- 市场看板车系外链（需改子服务 market_page 模板，另立项）
- main.py rename 404/502 语义未区分（统一固定文案，fail-closed 不受影响）
