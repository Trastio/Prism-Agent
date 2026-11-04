# 迁移收尾修复 · tasks（全部完成 2026-10-11）

- [x] T1 lib/series.ts：pushRecentSeries/getRecentSeries（localStorage，去重 cap 8）
- [x] T2 Sidebar：会话|车系 双 tab 按钮 + onSelectSeries(name, seriesId?)
- [x] T3 App：series 状态三路来源（侧栏/最近/对话检测）+ 写最近 + 选中切看板 + 向 KanbanView/ChatView 传递
- [x] T4 ChatView：tool_call args 提取 series_key → onSeriesDetected（去抖：变化才抛）；hero/SUGGESTIONS/placeholder 文案 PM 化
- [x] T5 看板带参：ReviewsBoard ?q= / ConfigBoard ?series_id=&load=1 / MarketBoard 注记限制
- [x] T6 EmbedBoard+SentimentBoard：reloadKey 支持（重载 iframe + 重探活）
- [x] T7 main.py：GET /dash/as_of（销量最新月末 + 口碑 MAX(post_date)，注册在反代前）+ POST /session/rename 转发
- [x] T8 KanbanView：as_of fetch + 刷新按钮接 reloadTick
- [x] T9 pi_gateway：names.json sidecar（load/save）+ GET /session 合并 custom_name + POST /session/rename + POST /session title 镜像
- [x] T10 datasource.ts：sentimentCoverage 两步新路由 + endpoints 清单更正
- [x] V1 静态：根 tsc 零新增(11=基线) + web build ✓ + node --check + py_compile
- [x] V2 smoke：smoke:all 50/50 + sentimentCoverage 直测（命中带 vehicle_id / 虚构车如实 miss）
- [x] V3 服务实测：prism.py 重启 → as_of 真值(2026-9月末/2026-10-07) + rename 全链 + ../注入被拒 + 三看板带参 200（Python urllib）
- [x] 渲染验证：headless Chrome——双 tab 出现 + as_of 实时值进 DOM + 新旧文案替换确认
- [x] Step6-10：simplify（SeriesSelection 收局部）/ code-review 自查三易错点 / verification.md / archive.md
