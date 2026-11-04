# 硬编码清理 · Step8 Receiving Code Review

## 已修
- P1-1 Sidebar localStorage JSON.parse 未包 try/catch → 包 try/catch 回退 []
- P2-2 KanbanView retail_sum NaN → s + (r.retail_sum ?? 0)
- P2-3 con_ratio NaN% → comfort?.con_ratio != null 判空
- P2-7 Sidebar seriesResult.error 无 UI → 加 error 分支渲染
- P2-10 extension 早返回写空 claim 覆盖好 verdict → 不重写直接 return
- P2-12 setActiveTools 异常静默 → catch 加 console.error

## 留下一轮（非阻塞）
- P2-1 KanbanView queryKey 撞车（OverviewBoard 与 ReviewsBoard ['reviews',series] 共享）
- P2-4 series 空"1-0月累计0台"（enabled 已挡，边界文案）
- P2-6 ChatView initialMessage 三脆弱点
- P2-8 App localStorage catch 静默
- P2-11 appendCustomMessageEntry 不被 lastUserMessageText 识别
- P2-13 ReviewsBoard con_ratio undefined 误判 pos
