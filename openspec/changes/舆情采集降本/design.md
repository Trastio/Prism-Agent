# 舆情采集降本 change · design

> 与 explore.md 的锚点表对照读。锚点均为 2026-10-15 实测。

## 总体分层

```
T1 参数批（env/配置，全部可逆） ──► T5 停采面摘除（依赖 T1 词序定型）
T2 预算护栏（新）      ┐
T3 清理任务（新）      ├─ 三组件并行，互不依赖
T4 极性直出（改造）    ┘
T6 调度（--all 全量 + schtasks）──► T7 联调验收（最后）
```

## D1 词数 15→6 + P1 轮换（scheduler.py + platform_strategy.py）

**关键发现（explore 核实）**：`_build_collection_keywords`（scheduler.py:240-258）拼序 = `core + defect_unique + rest`——缺陷词紧贴核心词。若直接 `[:6]`，选出的 6 词 = 核心 1 + 缺陷前 5，**双关键词被挤出**（与拍板"核心1+双2+缺陷top3"不符）。

**设计**：改拼序为 `core + rest[:2] + defect_wordlist`，`_select_keywords` 仍取 `strategy.max_keywords`（社媒 15→6，platform_strategy.py 配置改）。这样 `[:6]` = 核心1+双关键词2+缺陷前3，与拍板构成一致。注释同步更新（旧注释描述的是"缺陷帖采不到"的老问题，改拼序后缺陷词仍在选区内——排第 4-6 位）。

**P1 轮换（D4）**：缺陷词进入选择时，取 `DEFECT_SEED_KEYWORDS`（post_utils，12 词，按表序确定性）做 `(today.toordinal() // DEFECT_ROTATE_DAYS) % 4` 错位切片取 3 个——隔天换一组，4 组轮一圈（env `DEFECT_ROTATE_DAYS=2`；设 1 = 回到"永远 top3"）。纯函数 + 单测（同一日期必出同组）。

**initial 首采 6 词（D3）**：同通道自动生效（首采与增量共用 `_select_keywords`）；窗 90→30：scheduler.py:919 `timedelta(days=90)` 改读 `INITIAL_WINDOW_DAYS`（默认 30）。注意 :657 的作者背调 90 天窗**不动**（语义不同）。

## D2 预算护栏（新组件 A）

- 表：`tikhub_daily_usage(date TEXT PK, calls INT)`，同库（vehicle_sentiment.db）建表幂等
- 计数挂点：`TikHubClient._send`（tikhub_collector.py:259——get/post/post_query 唯一通路）。每请求前 `calls+1`；超 `TIKHUB_DAILY_BUDGET` 抛 `TikHubBudgetExceeded`（新异常类）
- 捕获：`collect_vehicle`（scheduler.py:936）最外层 catch → 该车标 `budget_capped` + 未跑完的车登记 `collection_state.skipped_vehicles`（JSON 列，`{"date": "...", "vehicles": [...]}`；当日已采车不受影响）
- as_of 语义：L6 v2 要求——agent 侧消费 stale 声明留 change 2，本 change 只负责**登记不丢**
- 指数采集（IndexCollector 走同一 client）自然计入——次数口径统一，美元差异忽略

## D3 清理任务（新组件 B）

- 新文件 `scripts/cleanup_posts.py`：删 `raw_posts WHERE published_at < today - POST_RETENTION_DAYS AND vehicle.status != 'paused'`，级联删 `post_comments`；输出统计（删帖/评论数、各车明细）
- **`--dry-run` 模式**：只列清单不删——首次运行与验收用
- 引用审计（§八待拍板 7 归位）：删除前查 `event_groups`/排行缓存对将删帖的引用（`events` 表 post 引用形态待实现时确认，AnalyzedPost.post_id 为外键主体——级联时同步处理 analyzed_posts 行）
- 挂点：`daily_update.py` 尾部（全部车完成后）调用；独立可跑（手动补清）
- 首次真删前置：库备份（change/snapshots/vehicle_sentiment-pre-cleanup.db）+ dry-run 清单人工过目

## D4 极性直出（组件 C，双轨设计）

**列设计（关键决策）**：新列 `post_comments.comment_polarity TEXT`（"1"/"0"/"-1"）。**不动 `dim_sentiment` 老列**——老评论保持维度 JSON，读侧回退推导，天然区分新旧，无迁移。

- 写侧：`local_absa.py` 增极性直出模式（`USE_LOCAL_MODEL` 路径内）：prompt 改判 1/0/-1，`parse_absa_output` 旁新增 `parse_polarity_output`（复用 `_VALID_SENTIMENTS`）；`_derive_overall_sentiment` 保留（老数据回退用，不删）
- 读侧：`derive_comment_sentiment`（post_utils.py:201）改为：`comment_polarity` 非空直用；否则老逻辑从 `dim_sentiment` 推导——**三端点（dashboard.py:526/574）与帖子级 comment_sentiment、翻车帖过滤（app.js:316-322）全部经此函数，单点改造全链生效**
- 打标队列：batch_runner 现按 `dim_sentiment IS NULL` 选待打标评论（:367-369）——改为 `comment_polarity IS NULL AND dim_sentiment IS NULL`（老评论不重标）
- **空极性口径（自查 G4 补）**：新评论采集后、夜跑打标前 `comment_polarity` 为空——derive 双轨返回 None，与现状"未打标评论"同口径（端点本就容忍 None，22% 覆盖率时代如此），翻车帖判定跳过该评论属预期行为；T4 单测加"两列皆空"用例钉死
- 口径 stamp：切换日写入（CHANGELOG 式落 DB 或方案文档 R43 已载）；切换后新评论全走直出

## D5 停采面摘除（platform_strategy.py + scheduler.py）

- `PLATFORM_MAP` 摘 `weibo/kuaishou/news` 三项（文件保留 collector 代码与策略定义，注释"2026-10-15 停采"）——社媒仅剩 xhs/douyin
- scheduler：删 news 阶段块（:976-986）+ `_collect_news`（:261-）+ `_store_posts` 内 news 去重/OR 过滤分支；`keyword_expander` 调用点与 `expanded_keywords` 写入（:225-232）下线
- 车质网阶段（Step 1b）**保留**——**自查 G6 补**：动 `_store_posts` 分支时车质网入库同路，任务单自验必须含"车质网帖入库回归"（dry-run 或 mock 各一帖）

## D6 调度（daily_update.py + schtasks）

- `--all` 删频率跳过：`_select_by_frequency`（daily_update.py:42-48）改为全量 active 直通（frequency.py 保留给展示排序用，不删）
- schtasks：`schtasks /create /tn "PrismSentimentDaily" /tr "<anaconda python> daily_update.py --all" /sc daily /st 03:00`（cwd=prism-sentiment；**依赖 :8000 存活**——start.py supervisor 常驻已满足；任务内加重试：服务未起时 `_post` 失败即整体退出码 1，Windows 侧不自动重试，靠次日自愈+当日手动补）
- 撞 refreshing 等待逻辑（P2-4）原样保留

## D7 验收编排（T7）

1. 基线先行：9 词对照实验（一天，~540 次，独立小脚本）→ 基线卡片落 `eval/` 或 `data/`
2. dry-run 调用账：单车（荐银河E5）按新参数跑一轮，护栏计数器读数 vs §3.8 表逐项对
3. 清理 dry-run 清单人工过目 → 备份 → 首次真删 → paused 断言（4,281 不变）+ 全库 ≈5,814
4. 出口闸 E2E：30 天口径活库上跑一条舆情题（sentiment_* 引用过闸）
5. 计划任务连续两日观察（3am 自动跑+退出码+skipped_vehicles 空）
6. 翻车帖回归：构造 pos2neg/neg2pos 用例（新列直出路径）

## 明确不做（本 change 边界，防蔓延）

agent 工具层零改动；stale 用户文案（change 2）；免费 API 替代验证（独立排期）；微博/快手/新闻 collector 代码删除（只摘配置）；frequency.py 删除（展示排序仍用）；前端（change 2）。
