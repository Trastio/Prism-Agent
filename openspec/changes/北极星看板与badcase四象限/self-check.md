# 北极星看板与badcase四象限 · Step3.5 自查收敛（2026-10-13）

> 方法：不空想，10 个疑点全部真库/真代码实测后裁决。SQL 均在 prism_events.db（7088 行）上跑过。

## Gap 清单与裁决

| # | 疑点 | 实测结果 | 裁决 |
|---|---|---|---|
| G1 | _shared.tsx 图表组件是否可用（proposal R5） | **不存在**——dashboards/_shared.tsx 仅 Header/Card/GapCard/Loading；AreaChart/KpiGrid/HBars/BarChart 全仓 grep 零命中（死码清理已移除，与记忆偏差）；archive/ 仅 SeriesCombobox | MetricsView **自写轻量 SVG**（双线 area+柱图），复用 styles.css 现成令牌（.kpi-grid/.kpi-value/.chart/.chart-grid，27 处确认在）；手写 SVG 参考设计图/UI设计/hermes-agent-kanban.html 原型。R5 风险升级为既定事实，工作量微增 |
| G2 | latency 配对是否有脏数据 | 实测抓到 27h 跨天配对（settled 10-07 06:38 ← start 10-06 03:09，无新 start 的重试/旧会话场景） | T1.2 latency 加 **15 分钟 sanity cap**：超时距对不计入，响应带 excluded 计数（诚实口径，页面不展示被排除的） |
| G3 | 图标存量 | 无 chart 类图标；refresh 现成 | 北极星入口用 **atom**；刷新按钮 refresh ✅ |
| G4 | 抽屉样式可否复用 | EvidenceDrawer className 模式（drawer/drawer-scrim/drawer-head/drawer-title/drawer-body/drawer-kv）确认 | BadcaseDrawer 直接复用 ✅ |
| G5 | 三条核心 SQL 真库可行性 | julianday 双格式解析 ✅；total_dau 并集=2（近24h）；终轮归一近14天 7 session（fail 1/pass 6）；retry_heavy 候选存在（3-8 轮/session） | SQL 形态定稿，直接进施工 |
| G6 | 脏 session id（usr_*/复合时间戳）进四象限怎么办 | 终轮归一结果确实混入；/trajectory 对非 UUID id 无匹配 | 不过滤（proposal R2 口径）；BadcaseDrawer 对无轨迹显示空态"无轨迹（旧格式/测试会话）"，明细表正常显示 |
| G7 | settled_count 语义 | ChatView:388 对每个 settled 事件 track（重试轮也发）→ session 内 settled 计数含重试轮 | 明细表列名用"settled 轮数（含验证重试）"，retry_heavy 阈值 ≥3 照旧 |
| G8 | trends 空日期补零 | 需日期序列生成 | WITH RECURSIVE 生成日序列 LEFT JOIN（sqlite 原生支持）✅ |
| G9 | 路由/代理冲突 | main.py 现有 22 路由无 /badcases* 前缀；vite /events 前缀代理天然覆盖 /events/trends ✅ | 施工时 grep 复核一次即可；新增代理三条（/trajectory /attribution /badcases） |
| G10 | 30s 轮询模式 | Sidebar useQuery 10s refetchInterval 同款 | MetricsView 照搬（30s）+ 手动刷新 invalidate ✅ |

## 收敛结论

- 端点契约（tasks.md 关键路径节）与前端组件清单无悬空依赖；G1 图表自写方案替代后仍零新依赖（纯 SVG+现有 CSS）
- 验收标准 7 条全部可验（对账 SQL 已在 G5 预演）
- **可进 Step5 施工**。施工协议：先探针子代理自报工具面（本 harness 子代理曾无文件工具空转），可用→派施工子代理按 tasks.md；不可用→主会话代行，Step7 一律代码内嵌隔离审查
