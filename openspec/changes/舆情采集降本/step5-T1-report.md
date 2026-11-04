# Step5 · T1 施工报告（参数批 + 停采面摘除）

> 子代理：t1-params（fork 型）· 日期：2026-10-15 深夜 · 依据 explore.md 锚点表 + design.md D1/D3/D5
> 红线遵守：未 git commit、未重启任何服务、未调任何付费 API（TikHub/GLM 零调用）、只改 prism-sentiment 下文件

## 一、改动清单（源码 7 文件）

| 文件 | 改动 |
|---|---|
| pipeline/platforms.py:20-23 | `SOCIAL_PLATFORMS` 4→2 平台（xhs/dy），停采注释；身份常量/ALL_PLATFORMS/标签保留 |
| pipeline/collectors/platform_strategy.py:43-68,82-90 | xhs/dy `max_keywords` 15→**6**（注释含 ⚠️<6 挤出缺陷词警告）；`PLATFORM_STRATEGIES` 注册表摘 news/weibo/kuaishou（策略对象保留归档，get_strategy 回落 _DEFAULT） |
| pipeline/scheduler.py | ① `_build_collection_keywords` 拼序 `core+rest[:2]+rotated_defect+rest[2:]`（:240-262）② 新增模块级纯函数 `rotate_defect_words`（P1 轮换，`DEFECT_ROTATE_DAYS=2` 分组错位、确定性，:176-204）③ `_expand_keywords_if_needed` 简化为直返 search_keywords（LLM 扩词链下线，:220-227）④ initial 窗 90→`INITIAL_WINDOW_DAYS`（默认 30，:37-39 + :919）⑤ news 阶段块摘除（:976-978 留注释；`_collect_news` 方法体归档保留供测试 patch，docstring 加勿调用警告）⑥ `_store_posts` 三处 news 分支摘除（标题去重 preload/同稿拦截/OR 过滤门，:668-700 区域）⑦ env_warning 文案"news 仍正常采集"→"车质网仍正常采集" ⑧ fetch_top_comments docstring 默认值注释 30→10 ⑨ import 清理（keyword_expander/_MAX_EXPANDED_KEYWORDS 删除） |
| pipeline/analysis/batch_runner.py:23-29 | `_COMMENT_TOP_N_DEFAULT` 30→**10**；`_COMMENT_PLATFORMS` 4→2 平台 |
| pipeline/collectors/post_utils.py:355-363 | `_COMMENT_MAX_PAGES_DEFAULT` 3→**2** |
| scripts/refresh_engagement.py:27,32 | `_TOP_N` 30→**15**（env `REFRESH_TOP_N`；补 env_int import）；窗 30 维持（R39）+ 停采注释 |
| api/pipeline_state.py:46-53 | `init_platforms` 六平台→三平台（xhs/dy/chezhiwang），进度面板随调度面收敛 |

## 二、测试改动（10 文件）

- **断言对齐**：test_platforms（2 平台集合）、test_platform_strategy（词数 6/注册表 3 平台/停采回落 _DEFAULT）、test_batch_runner（默认 10、停采平台配额 0、fixtures weibo→douyin）、test_engagement_refresh（top30→top15 + wb20 边界）、test_scheduler TestDateRanges（initial 30 天）
- **news 流转改道**（news 已不被调度，mock 注入换活通道）：test_scheduler ×5（stores/dedup/filters→社媒通道+resolve_collector 放行；CrawlFullTexts 改单元级直测归档门控；DedupInPipeline→社媒）、test_collection_api ×4（注入换社媒/车质网）、test_e2e ×1（社媒通道）、test_audit_p2（失败注入换车质网——社媒在无 key 测试环境会被 resolve 先 skip，车质网无条件执行）
- **目的已死用例改写**：TestExpandKeywords（改测直返行为）、test_keyword_expansion_failure（同）、TestNewsTitleDedup news 用例删（留社媒侧守护）、test_news_keeps_brand_or_gate（改守护"news 帖如今走 AND 门"）、test_news_receives_defect_combos（改反向守护"news 不被调用"）
- **新增**：tests/test_t1_cost_reduction.py（8 用例：轮换确定性/同周期同组/跨周期换组/4 组并集=全词表/env 生效/回退档/短表；initial 窗默认 30+env 覆盖）；test_defect_keywords 前六构成断言+轮换感知接线断言

## 三、自验证据

- **全量**：`python -m pytest tests/ -q` → **852 passed / 1 failed**；唯一失败 `test_cache_bust.py::test_index_serves_mtime_versions` 经 **git stash 基线复跑实证为存量失败**（与本 change 无关，stash 往返无丢失）
- **残留 grep**：`_collect_news`/`expand_keywords`/`keyword_expander` 在 pipeline/ 运行时路径零残留——仅存 ①归档方法体内部 ②keyword_expander.py 模块本体 ③注释；`get_strategy("news")` 仅在归档方法体内
- **导入冒烟**：scheduler/platform_strategy 可导入；SOCIAL_PLATFORMS=('xiaohongshu','douyin')；comment_top_n(dy)=10/weibo=0；comment_max_pages()=2；refresh _TOP_N=15；xhs/dy max_kw=6/6

## 四、偏差与决策记录

1. **"PLATFORM_MAP 摘条目"的落法偏离字面**：PLATFORM_MAP 实为名字→短码身份映射（platforms.py 单一真理源派生），摘它会破坏历史数据名称归一。实际停采杠杆=①`SOCIAL_PLATFORMS`（scheduler 调度遍历）②`PLATFORM_STRATEGIES` 注册表 ③`_COMMENT_PLATFORMS`（评论通道）——三处已全部收敛，PLATFORM_MAP 保持身份语义不动。
2. **`_collect_news` 方法体保留**（不删）：约 20 处既有测试 patch 该方法，全删会炸测试面；调度已摘除+docstring 警告，生产行为等效停采。news_collector.py 文件保留归档（含其测试文件）。
3. **audit_p2 失败注入点换车质网**而非社媒：无 TIKHUB_KEY 的测试环境社媒平台在 `_resolve_collector` 即被 skip，社媒 mock 不执行；车质网阶段无条件执行，是测试环境下唯一可靠的"采集进行中"注入点。
4. **explorer "周轮=频率分层"存疑项已间接证伪**：代码中无任何 weekday/周日逻辑（grep 实证），词数逐日同值由 max_keywords 决定——R30 确为零代码动作，频率分层（R22 范畴）在 daily_update.py，属 T5。
5. **`_crawl_full_texts` 发现为停采后死路径**（门只放 bocha/anspire/news 源）：按"归档保留"处理未删函数，测试改单元级直测。

## 五、遗留项（移交 T2-T7）

- `--all` 频率分层跳过删除（T5，daily_update.py:42-48）
- 负面追加 `COMMENT_NEGATIVE_EXTRA_N`（T2 波次，batch_runner——注意与 T1 已改的选帖函数衔接）
- `TIKHUB_DAILY_BUDGET` 护栏、清理任务、极性直出（T2/T3/T4）
- 车质网入库回归用例（design G6）：本波以既有车质网测试（test_chezhiwang_collector 21 用例）全绿佐证，T7 验收补一条 mock 全链路用例
- stash 往返验证法在共享工作区有风险（曾短暂收起并行会话改动）——后续用 `git stash push -- <指定文件>` 或分支对比替代
