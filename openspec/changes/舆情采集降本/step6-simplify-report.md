# Step6 · simplify 施工报告（舆情采集降本 change）

> 子代理：step6-simplify（fork 型）· 2026-10-16 · 红线全守：零 commit / 零服务重启 / 零付费 API / 生产库只读 / 未动计划任务

## S1 · max_pages 死字段接线（R33 遗留）✅

- **落法**：新增模块级 `_search_max_pages(platform, mode)`（tikhub_collector.py:104 附近）——incremental 消费 `get_strategy(platform).max_pages`（xhs=1/dy=2），**initial 维持 env `TIKHUB_SEARCH_PAGES_INITIAL`（默认 3）**：30 天回补窗需要 ≥3 页深度，策略 max_pages 是增量口径。
- **接线范围裁决（偏差①）**：只接活跃平台 xhs/dy。**weibo/kuaishou（停采归档路径）不接线**——保持 env 常量原样、行为零变化；否则 get_strategy 回落 _DEFAULT(max_pages=1) 会打破 4 个既有测试对归档路径的断言（test_page_counts_initial_3_vs_incremental_2 等），首跑前夜不值得为归档码动测试面（同 T1 保留 _collect_news 的先例）。
- 效果：xhs 增量 2 页→1 页，**省 6 次/车/天**（方案 §L2 的"接上后 18 次"口径至此兑现：xhs 6×1 + dy 6×2 = 18）。
- 测试：`TestSearchMaxPagesWiring` 4 用例（纯函数值/initial 用 env/xhs 增量单页截断/initial 翻页能力不损）+ 1 个既有夹具更新（test_zero_comment_notes_not_selected_for_comments 按单页现实重排 side_effect——其本意是评论选帖非翻页）。

## S2 · 停采归档死码处置 ✅

| 项 | 处置 | 理由 |
|---|---|---|
| `pipeline/collectors/keyword_expander.py` + `tests/test_keyword_expander.py` | **删除**（Bash rm） | 零生产引用（T1 已断 scheduler 调用链），纯孤儿模块+其专属测试，删除零缝 |
| `_collect_news` 方法体 + `news_collector.py` | **保留归档**（已有 docstring 警告 + scheduler:17 注释） | 10 处测试引用（4 个测试文件把它当注入 seam 而非测 news）；首跑前夜不大动测试面。**建议后续独立清理轮处置**（连同下项） |
| `_crawl_full_texts` + `full_text_crawler.py` | **保留归档** | 生产侧门控（source ∈ bocha/anspire/news）已证 no-op（车质网 source="chezhiwang" 实证），但 4+ 处测试 seam 引用；同上理由 |
| `MAX_EXPANDED_KEYWORDS` | 确认零残留（T1 已清） | grep 实证 |

## S3 · event_groups 悬空修剪（T3 遗留议项）✅

- 新增 `prune_event_groups(con, post_ids)`（cleanup_posts.py）：**live 删除事务内**剔除 event_groups.post_ids 中已删 id；**空组保留**（组=话题记录，成员归零不清行）；paused 帖不在删除集内天然不修剪。
- watch_items 维持只警告不自动动（用户手动清单）；dry-run 仍走引用审计报"将悬空"供过目。
- result 新增 `event_groups_pruned` 字段 + 报告行同步。
- 测试：`TestEventGroupPruning` 2 用例（混删组修剪/paused 组不动/全删组空保留/无交集组原样/dry-run 零触碰+审计仍报）。
- **生产库未跑**（指令遵守）；注意：今晚首跑的 daily_update 钩子是 dry-run 默认，修剪随 PRISM_CLEANUP_LIVE=1 的 live 清理一并生效。

## S4 · 简化扫描 ✅（1 修正 + 1 发现）

- **env 接线对账全一致**：DEFECT_ROTATE_DAYS / INITIAL_WINDOW_DAYS / COMMENT_NEGATIVE_EXTRA_N / REFRESH_TOP_N / PRISM_CLEANUP_LIVE / TIKHUB_DAILY_BUDGET / POST_RETENTION_DAYS 全部在位；方案侧死名（SOCIAL_DAILY_MAX_KW/DEFECT_SCAN_SCHEDULE）代码零残留。
- **发现并修正 docstring 矛盾（偏差②，待主会话知悉）**：`rotate_defect_words` 原注释称"搜索调用面 6 词→4 词/天"——**与实现矛盾**：轮换换的是构成（哪 3 个缺陷词）不换数量（仍 6 词/天 ≈18 次搜索/车）。**P1 提案文中"18→12 次、省 ≈650 元/月"的算式不由该机制实现**——若要该节省需另行拍板（pick=1 或社媒 max_keywords=4）；且 10-16 判别实验实证词近可互换，缩量收益本就存疑。docstring 已改写为如实表述。
- scheduler.py 的 POST_RETENTION_DAYS 两处引用均为注释（口径对齐说明），无功能残留。
- 注：scheduler.py 磁盘上有并行会话改动（Edit 应用干净，未覆盖他人内容）。

## 自验证据

- `python -m pytest tests/ -q` → **900 passed / 1 failed**（唯一失败 test_cache_bust 为 T1 已证存量失败，与本步无关；902→900 的差值 = 删 keyword_expander 测试 8 个 − 新增 6 个，账目吻合）
- 导入冒烟：`_search_max_pages('xiaohongshu','incremental')==1 / ('douyin','incremental')==2` ✓
- 红线：未 commit / 未重启服务 / 未调付费 API / 未注册计划任务 / 生产库零写入

## 移交

1. **P1 成本口径**：轮换不省搜索量（见 S4 发现）——主会话决定是否缩量（pick=1/max_keywords=4）或接受现状并把"650 元/月"从方案账里改掉
2. **归档码独立清理轮**：_collect_news/news_collector/_crawl_full_texts/full_text_crawler（首跑稳定后做，改动面=10+ 测试 seam 重写）
3. Step7 隔离审查可将本报告 S1"接线范围裁决"与 S4"P1 矛盾"列为重点复核项
