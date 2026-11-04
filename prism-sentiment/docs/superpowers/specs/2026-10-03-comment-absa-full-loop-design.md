# 评论 ABSA 全量循环清零 — 设计文档

> 日期：2026-10-03
> 状态：设计已批准，待 writing-plans

## 背景

风云A9（vehicle_id `a30dba4e-...`）采集到 5178 条评论，但看板"负面声量趋势"图为空。

根因链：
1. 负面声量趋势数据源 = `GET /api/dashboard/comment-sentiment-trend/{vehicle_id}`
2. 该端点从 `PostComment.dim_sentiment` 派生情感（`derive_comment_sentiment`，阈值 ±0.3）
3. **`run_comment_analysis`（`batch_runner.py:325`）单次只 `LIMIT 500` 处理 NULL 评论，无循环**
4. A9 有 5178 条评论，pipeline 只跑 1 轮 500 条 → 4678 条 `dim_sentiment` 仍为 NULL
5. `derive_comment_sentiment(NULL)` 返回 `"neutral"` → 30 天窗口 1631 条评论：56 正 / **0 负** / 1575 中性
6. 负面声量曲线全 0，图看起来"没内容"

对比：分析帖子的 `run_for_vehicle`（`batch_runner.py:235`）用 `while analyzed < self._max_posts` 循环，直到 `pending` 帖清零才退出。评论分析函数缺这个循环。

## 目标

让 `run_comment_analysis` 全量清零所有 `dim_sentiment IS NULL` 的评论，与 `run_for_vehicle` 的循环模式一致。

## 非目标

- 不改 `fetch_top_comments`（评论抓取与评论分析解耦）
- 不改 `derive_comment_sentiment`（NULL→neutral 语义保留，分析后自然不再是 neutral）
- 不改 `run_for_vehicle`
- 不加进度回调（A9 全量 ~10 批，本地模型几分钟内完成；进度可见性是 YAGNI，未来万级再考虑）

## 设计

### 决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 处理范围 | 全量清零（无上限） | 与 `run_for_vehicle` 一致；本次目标就是清零 |
| 出错处理 | 出错即停 | `predict_batch` 抛错自然向上传播，调用方 catch；已 commit 批次保留 |
| 方案 | 方案 A（最小改动） | ~10 行，模式一致，风险低，不破坏层次边界 |

### 改动

**单文件 `pipeline/analysis/batch_runner.py`，`run_comment_analysis` 方法（line 325-361）**

现状（单批，无循环）：
```python
result = await self._session.execute(
    select(PostComment).where(
        PostComment.vehicle_id == vehicle_id,
        or_(PostComment.dim_sentiment.is_(None), PostComment.dim_sentiment == ""),
    ).limit(500)
)
comments = result.scalars().all()
if not comments:
    return 0
texts = [c.content for c in comments if c.content and c.content.strip()]
valid = [c for c in comments if c.content and c.content.strip()]
batch_results = local_model.predict_batch(texts)
for comment, result in zip(valid, batch_results):
    dims = result.get("dim_sentiment", {})
    comment.dim_sentiment = json.dumps(dims, ensure_ascii=False) if dims else "{}"
await self._session.commit()
return len(valid)
```

改为（while 循环清零）：
```python
total_analyzed = 0
while True:
    result = await self._session.execute(
        select(PostComment).where(
            PostComment.vehicle_id == vehicle_id,
            or_(PostComment.dim_sentiment.is_(None), PostComment.dim_sentiment == ""),
        ).limit(500)
    )
    comments = result.scalars().all()
    if not comments:
        break
    texts = [c.content for c in comments if c.content and c.content.strip()]
    valid = [c for c in comments if c.content and c.content.strip()]
    batch_results = local_model.predict_batch(texts)
    for comment, res in zip(valid, batch_results):
        dims = res.get("dim_sentiment", {})
        comment.dim_sentiment = json.dumps(dims, ensure_ascii=False) if dims else "{}"
    await self._session.commit()
    total_analyzed += len(valid)
    logger.info("Comment ABSA: vehicle=%s batch=%d total=%d", vehicle_id, len(valid), total_analyzed)
return total_analyzed
```

### 错误处理语义

- `predict_batch` 抛错时异常自然向上传播（不 try/catch）
- `_run_analysis_pipeline`（`analysis.py:47-50`）和 `collection.py:62` 的 `try/except Exception` 会 catch 并 log warning
- **已 commit 的批次不会回滚**（commit 在抛错前完成）
- 下次 `daily_update` 或 reanalyze 会接住剩下的 NULL 评论（`where dim_sentiment IS NULL` 自然跳过已分析的）

### 接口兼容

`run_comment_analysis` 返回值从"单批数"升级为"总数"。调用方：
- `analysis.py:47`：`cmt_analyzed = await runner.run_comment_analysis(vehicle_id)` → 写入 `pipeline_phases["comments_analyzed"]`
- `collection.py:62`：同上

接口签名不变，语义升级（数字更大更准确），无需改调用方。

### 副变量名修正

原代码 `for comment, result in zip(...)` 里 `result` 变量名遮蔽了外层 `result = await self._session.execute(...)`。改为 `res` 避免遮蔽（已在上方"改为"代码块中体现）。

## 测试

新增测试到 `tests/test_batch_runner.py`（若无则创建）：

1. **`test_run_comment_analysis_loops_until_empty`**：mock `LocalABSAModel`，喂 1200 条 NULL 评论（验证 2 批 + 收尾），断言全部 `dim_sentiment` 非 NULL、返回 1200
2. **`test_run_comment_analysis_stops_on_error`**：mock `predict_batch` 第 2 批抛 `RuntimeError`，断言第 1 批 500 条已 commit（`dim_sentiment` 非 NULL）、异常向上传播

## 验证

- pytest 全套绿（713 基线，新增 2 测试 → 715）
- A9 实跑：触发 reanalyze，确认 5178 条评论全分析完、`comment-sentiment-overview` 的 `negative > 0`、负面声量趋势图有数据

## 风险

- **本地模型推理耗时**：A9 4678 条 NULL × Qwen3-4B 推理，预计 5-15 分钟。pipeline 期间前端看板显示 `calculating`，可接受。
- **OOM**：`predict_batch` 一次 500 条，单批内存可控。循环不增加单批内存。
- **并发**：若两次 `run_comment_analysis` 并发跑同一车，`where dim_sentiment IS NULL` + commit 后另一会话的查询会自动排除已分析项，不会重复分析（事务隔离 + 状态过滤）。
