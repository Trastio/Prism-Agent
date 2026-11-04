# 线B-工具截断 · explore（2026-10-12 实测）

> 起源：出口闸方案 v1.5 §十线 B（D5 拍板"做，与出口闸并行"）；出口闸线 A 已归档（10-08），本 change 承接线 B。
> 本 explore 全部结论来自 2026-10-11~12 两天实测（工具体积逐端点测量 + extension/pi 文档/tikhub.ts 读码 + 服务探活），非纸面推导。

## 1. 工具体积实测（超标点 4 个）

| 工具 | 后端端点 | 实测体积 | 判定 |
|---|---|---|---|
| search_cars | /dash/market/api/series-list | **99.7 KB** | 超标×5 |
| get_config_detail | /dash/config/compare-horizontal | **32.1 KB** | 超标（2 版型对比即 32KB，更多更大） |
| score_models | /dash/config/concept-configs | **24.0 KB** | 超标 |
| get_review_analysis / get_model_detail / search_reviews / get_dimension_reviews | /dash/koubei/series/{id}/data | **38.0 KB** | 超标 |
| sentiment_posts | top-posts?limit=20 | 21.3 KB | 压线 |
| query_config | /dashboard/config | 15.0 KB | OK（正当载荷上限参照） |
| 其余（query_reviews 1.6K / query_sales 2.4K / trims 1.5K / sentiment 其余 0.4-8K / retail 1.3K / peer-compare 7K） | — | <10 KB | OK |

**事发历史**（出口闸 explore 实录）：自建工具不截断 → 事发会话 446KB（pi extensions.md:144 明确要求扩展工具自截断，未遵守）。

## 2. search_cars 参数失效（真 bug）
工具声明 `keyword/brand/min_price/max_price` 四参，makeAutohomeTool 原样透传给 series-list——**该端点不接受任何参数**（market_routes.py:91-93 无参签名）→ agent 每次查车全量 100KB 拉回，过滤形同虚设。

## 3. tool_result hook 现状（.pi/extensions/prism-guardrails/index.ts L1072-1130）
- 单 handler 三分支：①business 台账采集（全量 text）②social_* 名称采集后**提前 return** ③query_/sentiment/resolve 的 _meta 校验（已有 patch 先例：缺 as_of → 返回 `_warning` 改写）+ 名称真值集
- **pi 链式中间件语义**（extensions.md:842-858）：同扩展可注册多个 tool_result handler，按注册顺序执行，后注册的看到前者改写后的结果，返回 `{content}` 部分补丁替换——**截断层作为第二个 handler 注册在采集 handler 之后，天然满足"台账先抽后截"（v1.5 §十交点约束），零侵入现有分支**

## 4. 工具全景（32 个，2026-10-12 盘上实测）
- business 21（query_*3 + sentiment 6 + dashboards 10 + resolve_series + submit_conclusion）
- web 8（pi-web-access 4 + **social_* 4 TikHub 直连**，社媒包 M1 新增，归 web tier）
- utility 3（ask_user_question + load_skill + export_document）
- 探活结果：**31 可用；sentiment_trend 坏**（工具传 `days`，prism-sentiment trend 端点必填 `start/end` 日期 → agent 调必 422）；/tikhub/status 有 data1 未定义 bug（2026-10-12 已修，但暴露 429 时状态灯仍显绿的展示盲区）
- 轨迹证实 social_search/load_skill 已有真实调用记录（社媒包施工时验证）

## 5. social_* 已有第一道截断（tikhub.ts，不收编内部）
tikhub.ts 自带 truncateOutput（50KB/2000 行头截断，pi 规范自截），且该文件由并行会话活跃开发中（M5 TODO-verify 待实测校准）。**决策：不动其内部**——tikhub 自截防网络层爆炸（第一道），本 change 的 hook 统一截断管上下文预算（第二道，20KB 更严 + JSON 感知 + 保 url）。两道职责不同，非重复实现。

## 6. 验证基建现状
- 门禁：eval/ci.sh = `npm run smoke:all` + `node eval/runner.mjs`（16 题）+ `node eval/runner.mjs --gate`（**E1-E9 出口闸门禁，不绿不合档**）
- 单测：tests/ 目录 node:test 模式（identity_api 4 + tool_call 17 + …）
- 根 tsc 历史基线 11 条（零新增标准）
- 网关重启即加载新 extension（spawn pi 子进程时读盘）；prism.py 统一重启（PRISM_AUTO_APPROVE_UI=1 已内置）

## 7. 环境注意
- 并行会话正在开发社媒包（M4 前端状态灯今日新增/M5 待做）——extension index.ts 与 tikhub.ts 是共享文件，施工以盘上最新代码为准，改动区域避开 social 注册段
- TikHub 当前 429 限流（探测与业务共享配额）——E1-E9 不依赖 TikHub，不受影响

## 8. 施工前补充实测（2026-10-12）
- **series-list 行形态**：`{series: 名称, latest_retail, has_retail, has_weighted}`，1,149 行（市场口径）——search_cars 工具描述（"返回 series_id/名称/级别"）与实际数据**不符**，且无 brand/level/price 字段可过滤 → B2 修正为：描述对齐真实字段、参数只留 keyword（其余参数删除，防模型传无效参）。
- 具体车系→series_id 的查找职责本就在 resolve_series（identity/resolve 查 series_summaries），search_cars 定位=市场车系浏览/筛选，两者不重叠。
