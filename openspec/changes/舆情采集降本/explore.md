# 舆情采集降本 change · Step 1 explore

> 日期：2026-10-15 · 流程：严格十步（Step1 explore → Step2 propose → Step3.5 自查 → Step5 施工[子代理] → Step6-10）
> 依据：`设计图总览/Prism-Agent-舆情降本与看板简化方案-v1.md`（v2.2 + R1-R42 全部拍板，2026-10-15 定稿）
> 范围：prism-sentiment 采集/刷新/清理/打标管线。前端（change 2）不在本 change。
> 本文所有 file:line 均为本会话实测（2026-10-15），非文档转抄。

## 一、终态口径（施工验收的"应该长什么样"）

15 台 active 车每日自动跑一次，每车单车 ≈96-98 次 TikHub（搜索 18 + 评论 60 页 + 刷新 ~18）+ 指数 2 次（$0.023/车）+ 车质网 0 元；帖子 GLM 15 维保留、评论只判极性（模型直出 1/0/-1）；30 天保留线物理删除（paused 车豁免）；日预算护栏封顶可降级；无任何每周任务；`--all` = 全部 active 无频率跳过。

## 二、代码现状地图（改动锚点）

| # | 现状 | 位置 | 改动归属 |
|---|---|---|---|
| 1 | 关键词截断 `all_keywords[:max_kw]` | scheduler.py:238 | L2（6 词日更） |
| 2 | core/rest 拆分 | scheduler.py:253-254 | L2 |
| 3 | news 阶段 | scheduler.py:261 `_collect_news` + 976-986 阶段块 | L4 停采（删阶段+策略+去重分支+扩词链） |
| 4 | initial 窗 90 天硬编码 | scheduler.py:919 | R40（30 天，建议 env 化） |
| 5 | 增量窗 −2 天缓冲 | scheduler.py:921 | 不动（恢复停摆自动覆盖） |
| 6 | 指数采集（仅核心词 1 次/平台/车） | scheduler.py:1119-1124（`self._index` :179） | R38 保留，不动 |
| 7 | 搜索翻页常量 env 已存在 | tikhub_collector.py（`TIKHUB_SEARCH_PAGES_INCREMENTAL/_INITIAL`）+ platform_strategy.py:43-68 max_pages 死字段 | R33（接上或删死字段，二选一） |
| 8 | 评论选帖：全库互动 top-N + 缺陷词帖全量 + 互动门槛 ≥5 + 顺延补位 | batch_runner.py:28（COMMENT_TOP_N env 已存在）、:62-130 | L1（top10×2 页；负面追加新逻辑） |
| 9 | 评论页数 env 已存在 | COMMENT_MAX_PAGES（post_utils.py:358 附近消费） | L1 |
| 10 | 评论去重 cid+指纹 | scheduler.py:842-870（`_store_comments`） | 不动（重抓只补新评论，实证过） |
| 11 | 互动刷新窗 `_WINDOW_DAYS=30`、逐帖帽 `_TOP_N=30` | scripts/refresh_engagement.py:32-33 | R39（窗 30 不动）/top15（微博快手分支随停采自然失效） |
| 12 | 极性从维度投票推导 | local_absa.py:32 `_VALID_SENTIMENTS`、:35 `parse_absa_output`、:61 `_derive_overall_sentiment` | §四 极性直出改造 |
| 13 | `derive_comment_sentiment` 全链 | post_utils.py:201 → dashboard.py:526/574 + app.js:316-322（翻车帖过滤） | §四 陷阱 4（三端点+帖子级字段+前端归位） |
| 14 | 帖子侧维度常量 | analyzer.py:13-14 `VALID_DIMENSIONS`（:243 消费） | 不动（红线：不能删） |
| 15 | TikHub 请求单点 | tikhub_collector.py:259 `_send`（get/post/post_query 全过此） | L6 预算护栏唯一挂点 |
| 16 | `daily_update --all` 带频率分层跳过 | scripts/daily_update.py:5 注释、128 前 targets 过滤 | **R22：删频率跳过，--all=全部 active**（本 explore 新发现） |
| 17 | daily_update 走 HTTP API 驱动 | daily_update.py:128-160（`_post /api/vehicles/{vid}/collect` + already_running/refreshing 等待逻辑） | 计划任务依赖 :8000 服务存活（startup 顺序） |
| 18 | MAX_INTERACTION_PER_DAY=500k | heat_calculator.py:27 | **与 L6 无关**（热度分异常值帽），不冲突不动 |
| 19 | 微博/快手/新闻停采面 | platform_strategy PLATFORM_MAP + collector `_search_weibo/_search_kuaishou`（tikhub_collector.py:457/...） | R23/R31（策略层摘除，代码保留归档） |

**既有 env 资产**（改参数优先复用，不新造）：`COMMENT_TOP_N`、`COMMENT_MAX_PAGES`、`TIKHUB_SEARCH_PAGES_INCREMENTAL/_INITIAL`、`TIKHUB_STATS_BATCH_SIZE`、`DEFECT_WINDOW_DAYS`、`USE_LOCAL_MODEL`、`ABSA_MODEL`、`MAX_EXPANDED_KEYWORDS`（随 L4 作废）等。

## 三、改动面清单（按方案 L1-L8 映射）

**L1 评论**：`COMMENT_TOP_N=10`、`COMMENT_MAX_PAGES=2`（env 直配）；新增负面追加 `COMMENT_NEGATIVE_EXTRA_N=10`——挂进 batch_runner 选帖（负面词表预筛，词表与缺陷词同源 DEFECT_SEED_KEYWORDS，post_utils）；低互动车跳评论（近 30 天零新增互动）。
**L2 关键词**：`SOCIAL_DAILY_MAX_KW=6` 新 env（或改 :238 max_kw 缺省）；删 `DEFECT_SCAN_SCHEDULE` 概念（R30 周轮已不存在，确认代码里本来就没有独立周轮入口——**待 Step2 核实**：现状"周轮"可能就是 daily_update 的频率分层，若如此 R22 的"删频率跳过"与 R30"删周轮"是同一处改动）。
**L3 刷新**：`_TOP_N` 30→15；窗 30 不动（R39）；删周补（确认现状是否真有周补调度——refresh 是每日跑的独立脚本/阶段，**待 Step2 核实其调度入口**）。
**L4 新闻**：删 `platform_strategy.NEWS` 策略、`_collect_news`、scheduler news 阶段块（:976-986）、`_store_posts` 的 news 去重/OR 过滤分支、`keyword_expander` 链、`MAX_EXPANDED_KEYWORDS` env 作废。
**L5 渠道**：PLATFORM_MAP 摘 weibo/kuaishou（策略层配置，不删 collector 代码）；前端平台档文案（change 2 侧联动）。
**L6 护栏（新组件 A）**：SQLite 单表日计数器（date, calls, by_endpoint 可选）；挂 `_send`（tikhub_collector.py:259）计数+封顶判断；命中→抛特定异常→scheduler 捕获标 `budget_capped` + `skipped_vehicles` 登记（collection_state 扩字段）；env `TIKHUB_DAILY_BUDGET`（初值=15×98×1.5≈2,200，待账单校准）。
**L7**：不动。
**L8 清理（新组件 B）**：新脚本 `scripts/cleanup_posts.py`（或并入 daily_update 尾部）：删 `published_at < today − POST_RETENTION_DAYS(30)` 的 raw_posts + 级联 post_comments；**WHERE 加车辆 status≠'paused'**（R42）；`events`/排行缓存引用审计先行（§八待拍板 7 归入本 change 验收）；跑在每日采集后。
**R40 initial**：scheduler.py:919 `timedelta(days=90)`→30（env `INITIAL_WINDOW_DAYS`）；连带 :657 作者背调 90 天窗**不动**（不同语义，实测确认）。
**R22 全量日更**：daily_update.py 删频率分层跳过。
**计划任务**：schtasks 每日凌晨跑 `daily_update.py --all`（PATH=Anaconda Python；依赖 :8000 服务存活→prism.py 启动链或任务延迟启动；退出码 0/1/2/3 已有）。
**§四 极性直出（新组件 C）**：local_absa 改造（直出 1/0/-1，删投票推导的依赖关系）；`derive_comment_sentiment` 全链改造（输入形态变）；翻车帖判定回归。**口径 stamp：切换日 as_of 断点声明（历史不重标）**。

## 四、验收清单（从方案 §六 搬齐 + 扩展）

1. 单车 dry-run 调用账对比：≈550→≈96-98（−82%），分项与 §3.8 表逐项对上
2. 负面词表命中率回归（负面追加真的抓到 top10 外负面帖）
3. 护栏命中降级演练（故意压低预算值，验证 skip+登记+次日恢复）
4. 翻车帖判定回归（pos2neg/neg2pos 归位正确——derive 链改造后）
5. 清理任务：不误删 7 天窗内帖；**paused 6 台清理前后行数不变（4,281）**；首次清理后全库 13,014→≈5,814
6. 9 词对照实验基线（一天 ~540 次，测被砍缺陷词检出量，兼作 P1 决策依据）
7. `--all` 覆盖车数=15（无频率跳过）；计划任务连续两日自动跑通
8. 出口闸 sentiment_* 在 30 天口径活库上的 E2E 回归（活库变"近 30 天"后闸复算自洽）
9. 新闻/微博/快手零调用（护栏计数器侧面验证）
10. 口径 stamp 落 metadata（采集窗/评论配额/词排班/保留期/切换日 五要素）

## 五、Step 2 需锁定的拍板（承接方案 §八 待拍板 10-14）

1. P1 缺陷词轮换进不进本 change（荐进）
2. initial 首采 6 词 vs 15 词（荐 6）
3. 护栏初值（荐 2,200 次/天，账单到后调）
4. 计划任务时点（凌晨几点、与打标夜跑/服务启动的顺序）
5. 施工顺序内排布（建议：参数 env 批 → 新组件 A/B/C → 停采面摘除 → 联调 dry-run → 计划任务最后挂）

## 六、坑清单（本会话实测/项目史教训）

- **采集服务改库注意**：现状采集停摆（10-08 起），是改 vehicles/上组件的安全窗口；恢复日更后不能再热改
- heredoc 反斜杠折叠（项目史四犯）——代码编辑一律 Edit 工具
- Windows netstat/GBK、中文路径 sqlite（chdir+文件名）老坑适用
- daily_update 撞 refreshing 的等待逻辑（P2-4 已修）——计划任务时点避开互动刷新窗口
- `MAX_INTERACTION_PER_DAY` 是热度异常帽非调用预算，勿混淆
- 切换首日效应：首轮增量窗覆盖停摆期（≈10 天窗），首日调用量会偏高，护栏初值要含此余量
- 两个"待 Step2 核实"：周轮的真实代码入口（疑=频率分层）；refresh 的调度入口与"周补"是否实际存在

> **结论：explore 完成，可进 Step 2 propose。** 改动面全部锚定到 file:line，三个新组件（护栏/清理/极性直出）边界清晰，无未知技术风险；最大的开放点是 §五 的 5 个拍板。
