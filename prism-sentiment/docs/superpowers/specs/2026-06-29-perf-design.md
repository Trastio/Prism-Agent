# 主题 D：性能 + dialog anchor 修复 — 设计文档

> 日期：2026-06-29
> 治根主题 D（共 7 主题）：dialog event anchor 正确性 bug + 三处性能治根

## 1. 背景与根因

侦察确认三处问题，其中 **#1 是正确性 bug**（不只是性能）：

### #1 dialog event anchor 重复迭代 bug（正确性，高优先级）
`api/routes/dialog.py` event 分支（124-139）：
```python
all_analyzed = await session.execute(select(AnalyzedPost).where(...))
matched_post_ids = []
for ap in all_analyzed.scalars().all():      # 第1次消费 Result
    if event in json.loads(ap.event_tags): matched_post_ids.append(...)
...
for ap in all_analyzed.scalars().all():      # 第2次 — Result 已耗尽，返回空！
    if event in tags: sent_counts[ap.sentiment] += 1   # 恒不执行
```
SQLAlchemy `Result.scalars().all()` 第二次调用返回空（cursor 已消费）→ **无 EventGroup 时 event anchor 的 sentiment 分布恒为 0**。

附加性能问题：`select(AnalyzedPost).where(vehicle_id)` 拉全表到内存，Python 侧 `json.loads` + `in` 过滤（O(N) 全表每行解析 JSON）。opinion 分支（153-172）同样全表扫描（但单次遍历，无 bug）。

### #2 heat_calculator 逐天串行（性能）
`heat_calculator.calculate_range`（165-173）：`while current <= end: await calculate_daily(...)`。90 天首次采集 = 90 次 `calculate_daily`，每次内含 **5 个串行 DB 查询**（existing/discussion/media/interaction/percentile-range）+ commit = **~450 roundtrip**。

### #3 run_comment_summaries 串行 LLM（性能）
`batch_runner.run_comment_summaries`（202-219）：`for post in top_posts: await summarize_comments(...)`。top_posts = 每平台 top-N（4 平台 × N），逐个串行调 LLM——LLM 是瓶颈，串行累加耗时。

**共同根因**：N+1 模式——循环内逐项查/调，未用聚合查询或并行。

## 2. 目标

1. **修 #1 正确性 bug**：dialog event anchor sentiment 不再恒 0；同时去掉全表 Python 遍历。
2. **#2 heat 聚合**：`calculate_range` 用聚合查询替代逐天 N+1，把 ~450 roundtrip 降到个位数。
3. **#3 评论摘要并行**：`run_comment_summaries` 用 `gather` 并行 LLM 调用。
4. **治根判据**：dialog anchor 单次遍历正确计数；heat 不再有逐天循环；评论摘要 LLM 并行。

## 3. 设计

### 3.1 dialog event/opinion anchor — 单次遍历 + 收窄查询
置信度：高。

合并双循环为单次，且收窄查询（只取需要的列）：
```python
rows = await session.execute(
    select(AnalyzedPost.post_id, AnalyzedPost.sentiment, AnalyzedPost.event_tags)
    .where(AnalyzedPost.vehicle_id == vehicle_id)
)
matched_ids, sent_counts = [], {"positive":0,"negative":0,"neutral":0}
for pid, sentiment, tags_json in rows.all():   # 单次消费 Result
    if event in (json.loads(tags_json) if tags_json else []):
        matched_ids.append(pid)
        sent_counts[sentiment] = sent_counts.get(sentiment, 0) + 1
```
- 单次遍历：同时收集 matched_ids + sent_counts（修 bug + 去重复迭代）
- 收窄列：只取 post_id/sentiment/event_tags（不全表 ORM 实例化）
- opinion 分支同样改造（单次遍历，已无 bug 但同样全表 → 收窄）

> 不用 SQL `LIKE '%event%'`：event_tags 是 JSON 数组，LIKE 会误匹配子串（如 "降价" 匹配 "大降价"）。Python 精确 `in` 更对。

### 3.2 heat_calculator — 聚合查询替代逐天
置信度：中高（聚合 GROUP BY date 是标准优化；需重构 calculate_daily/calculate_range 分工）。

核心思路：**一次聚合查询拿全周期每日 discussion/media/interaction**，而非每天 3 查询。
```python
# discussion: SELECT date(published_at) d, count(*) FROM raw_posts
#   WHERE vehicle_id=? AND source IN cdp AND published_at IN [start,end] GROUP BY d
# 同理 media(platform=news)、interaction(sum likes/comments/shares GROUP BY d)
```
3 条聚合查询（discussion/media/interaction）+ 1 条已有 HeatMetric（attention_index）覆盖全周期，替代 90×3。

重构：
- 新增 `calculate_range_aggregated`：聚合查询 + Python 按天组装 HeatMetric + 批量 percentile（一次查 30 天 range，Python 算所有天的 percentile）
- `calculate_daily` 保留（单日精确场景/测试用），但 `calculate_range` 改调聚合版
- commit：批量（一次）而非每天一次

权衡：聚合重构较大。若风险高，**退而求其次**：保留 calculate_daily 但 `calculate_range` 内部不逐天 commit（攒最后一次 commit）——仍串行但减 90 次 commit 开销。spec 主推聚合，plan 阶段评估。

### 3.3 run_comment_summaries — 并行 LLM
置信度：高。

LLM 调用（`summarize_comments`）是瓶颈且独立。结构改为：串行查 comments（session 约束）→ **并行 LLM** → 串行写回。
```python
# 1. 串行收集每个 post 的 comment_dicts（DB，session 串行）
tasks = []  # [(post, comment_dicts), ...]
for post in top_posts:
    comments = (await session.execute(...)).scalars().all()
    if len(comments) >= _MIN: tasks.append((post, [...]))
# 2. 并行 LLM（无 DB，安全并发）
summaries = await asyncio.gather(*[summarize_comments(cd, ...) for _, cd in tasks])
# 3. 串行写回（session）
for (post, _), summary in zip(tasks, summaries):
    if summary: ...update ap.comment_summary...
```
Semaphore 可选（限并发防 LLM 限流；analyzer 用过 Semaphore(5)）。

## 4. 改造范围

| 文件 | 改动 |
|------|------|
| `api/routes/dialog.py` | event/opinion anchor 单次遍历 + 收窄列 |
| `pipeline/analysis/heat_calculator.py` | `calculate_range` 聚合版 |
| `pipeline/analysis/batch_runner.py` | `run_comment_summaries` 并行 LLM |
| `tests/test_dialog_api.py` | 加 event anchor sentiment 非 0 断言（修 bug 验证） |
| `tests/test_heat_calculator.py` | 聚合版测试 |

## 5. 验证

pytest：
1. dialog event anchor：插 EventGroup-less 数据 + 匹配 event 的 AnalyzedPost → 断言 sentiment_counts 非 0（直接验证 bug 修复）
2. heat：calculate_range 聚合结果 == 逐天结果（等价性）
3. comment_summaries：并行后摘要数 == 串行（mock LLM 验证调用数/结果）

## 6. 涉及文件

- `api/routes/dialog.py`、`pipeline/analysis/heat_calculator.py`、`pipeline/analysis/batch_runner.py`
- `tests/test_dialog_api.py`、`tests/test_heat_calculator.py`、`tests/test_batch_runner.py`

## 7. 非目标（YAGNI）

- 不引入缓存层（当前规模无需）
- 不改 HeatMetric schema
- 不并行化 dialog 的多个 anchor（用户单次点击一个 anchor）
- heat 聚合若风险过高，plan 阶段降级为"逐天但单 commit"
