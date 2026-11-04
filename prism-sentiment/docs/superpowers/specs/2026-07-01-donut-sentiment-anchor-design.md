# Donut Sentiment Anchor — 设计文档

> 日期：2026-07-01
> 遗留项（出自 2026-06-29 全栈治根 minor-cleanup 拆出）：sentiment donut 点击走错 anchor 分支，dialog 拿不到情感上下文。新增独立 sentiment anchor 分支。

## 1. 背景与根因

`frontend/static/js/app.js:401` 情感分布甜甜圈图（sentimentDonut）点击：
```js
this.sentimentDonutChart.on("click", (params) => {
    if (params.name) openDialog("trend", { sentiment: params.name });
});
```

两个错配：
1. **anchor 类型错**：传 `"trend"`，但 `dialog.py:_build_context` 的 trend 分支（:35-69）只认 `anchor_data["date"]`，收到 `{sentiment: ...}` 时拿不到 date → 跳过所有数据查询，返回空上下文。
2. **中英文未映射**：`params.name` 是 donut data 的中文 name（"正面/负面/中性"，app.js:415-417），而 DB `AnalyzedPost.sentiment` 存英文（positive/negative/neutral）。即使走对分支，中文值也查不到。

结果：点情感扇区 → 对话框"用户点击了趋势图上 的数据点"（date 空），无任何情感数据。

## 2. 目标

1. 新增独立 `sentiment` anchor 分支，与现有 trend/platform/event/opinion 并列，不污染 trend 语义。
2. 点击情感扇区 → 对话显示该情感的帖子占比 + 维度画像 + 典型帖。
3. 中文情感名在前端映射成英文再传后端，UI 文案不渗入后端查询。
4. 治根判据：点负面扇区，对话 context 含负面占比、负面维度 Top、负面热门帖标题。

## 3. 设计

### 3.1 改动点（2 处代码）

**改动 1 — `app.js:400-402` donut click**：加中文→英文映射 + 改 anchor 类型

```js
const SENTIMENT_CN2EN = { "正面": "positive", "负面": "negative", "中性": "neutral" };
this.sentimentDonutChart.on("click", (params) => {
    const s = SENTIMENT_CN2EN[params.name];
    if (s) openDialog("sentiment", { sentiment: s });
});
```

`SENTIMENT_CN2EN` 作为模块级常量（与 `CHART_COLORS` 同位置，app.js 顶部常量区）。donut data name（"正面"等）保持不变（UI 显示中文），仅 click 时映射。

**改动 2 — `dialog.py` 新增 `elif anchor_type == "sentiment"` 分支**（接在 platform 分支后，:95 附近）：

```python
elif anchor_type == "sentiment":
    sentiment = anchor_data.get("sentiment", "")
    sent_cn = {"positive": "正面", "negative": "负面", "neutral": "中性"}.get(sentiment, sentiment)
    context_parts.append(f"用户点击了情感分布图上的「{sent_cn}」情感")
    if sentiment in ("positive", "negative", "neutral"):
        # 1. 帖子数 + 占比（SELF_ONLY 主车型帖口径）
        total = (await session.execute(
            select(func.count(AnalyzedPost.id)).where(
                AnalyzedPost.vehicle_id == vehicle_id, SELF_ONLY)
        )).scalar() or 0
        sent_count = (await session.execute(
            select(func.count(AnalyzedPost.id)).where(
                AnalyzedPost.vehicle_id == vehicle_id, SELF_ONLY,
                AnalyzedPost.sentiment == sentiment)
        )).scalar() or 0
        pct = round(sent_count / total * 100, 1) if total else 0
        context_parts.append(f"{sent_cn}帖子数: {sent_count}（占主车型帖 {pct}%）")

        # 2. 维度分布 Top5（平均口径，复用 _compute_dim_sentiment 的 sum/len 逻辑 + sentiment 过滤）
        dim_rows = await session.execute(
            select(AnalyzedPost.dim_sentiment).where(
                AnalyzedPost.vehicle_id == vehicle_id, SELF_ONLY,
                AnalyzedPost.sentiment == sentiment)
        )
        dim_agg: dict[str, list[float]] = {}
        for (dim_json,) in dim_rows.all():
            try:
                dims = json.loads(dim_json) if dim_json else {}
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(dims, dict):
                for k, v in dims.items():
                    if isinstance(v, (int, float)):
                        dim_agg.setdefault(k, []).append(float(v))
        if dim_agg:
            dim_sorted = sorted(
                [{"dim": k, "score": round(sum(v)/len(v), 3)} for k, v in dim_agg.items()],
                key=lambda r: r["score"],
                reverse=(sentiment == "positive"),  # 正面取最高、负面/中性取最低
            )
            top_dims = dim_sorted[:5]
            context_parts.append(
                f"{sent_cn}帖子维度Top5: " + ", ".join(f"{d['dim']}({d['score']:+.1f})" for d in top_dims)
            )

        # 3. 热门帖 3 条（按互动数）
        top = await session.execute(
            select(RawPost).join(AnalyzedPost, AnalyzedPost.post_id == RawPost.id)
            .where(AnalyzedPost.vehicle_id == vehicle_id, SELF_ONLY,
                   AnalyzedPost.sentiment == sentiment)
            .order_by((RawPost.likes + RawPost.comments + RawPost.shares).desc()).limit(3)
        )
        posts = top.scalars().all()
        if posts:
            context_parts.append(
                f"{sent_cn}热门帖: " + " | ".join(f"「{p.title or p.content[:30]}」" for p in posts)
            )
```

### 3.2 关键设计决策

- **独立分支而非扩展 trend**：trend 语义是"日期"，混入 sentiment 破坏单一职责。独立 sentiment 分支与现有 4 分支并列，语义清晰。
- **维度分布用平均（sum/len）**：与 `_compute_dim_sentiment`（reports.py:173）和全局维度雷达图同口径，只是限定 sentiment，直观可比。不做"相对全局差值"（YAGNI）。
- **Top5 取向随情感翻转**：正面取 score 最高（最满意维度），负面/中性取 score 最低（最不满/最弱维度）。这样每个情感的 Top5 都指向"该情感最显著的维度"。实现：`reverse=(sentiment == "positive")`。
- **聚合逻辑内联而非 import**：`_compute_dim_sentiment` 是 reports.py 私有函数（下划线前缀），跨模块 import 不洁；dialog 分支内联 ~15 行聚合（参考 reports.py:160-176），避免改 reports.py 影响深报。短期可接受重复，长期可重构提取到 utils。
- **前端映射**：UI 文案（中文）→ DB 值（英文）的映射属于 UI 层职责，放 app.js。后端用标准英文值查询，不掺杂文案。
- **SELF_ONLY 口径**：与 dashboard/event_tracker 一致，只统计主车型帖（subject='self' 或 NULL），避免竞品帖污染。

### 3.3 不改（已核实）

- `dialog.js openDialog`（:85-97）：通用函数，`vm.dialogAnchorType = anchorType` 不限类型 → 新 "sentiment" 自动支持，无需改。
- donut data name：保持中文（UI 显示不变）。
- `_compute_dim_sentiment` 签名：不动 reports.py。

## 4. 改造范围

| 文件 | 改动 |
|------|------|
| `frontend/static/js/app.js` | `:400-402` donut click 改 anchor 类型 + 映射；顶部加 `SENTIMENT_CN2EN` 常量 |
| `api/routes/dialog.py` | `_build_context` 新增 `elif anchor_type == "sentiment"` 分支（:95 附近） |
| `tests/test_dialog_api.py` | 加 sentiment anchor 测试（占比 + 维度Top + 热门帖） |

## 5. 验证

pytest（`tests/test_dialog_api.py`）：
1. 插 `AnalyzedPost(sentiment="negative", dim_sentiment='{"续航":-1,"动力":-0.5,"空间":0.2}', vehicle_id=vid)` + 对应 RawPost（互动数已知）+ 几条其他 sentiment 帖。
2. 调 `_build_context(vid, "sentiment", {"sentiment":"negative"})`。
3. 断言返回 context 含：
   - "负面帖子数" + 占比正确
   - "续航" 出现在维度Top5（且排在"空间"前，因 negative 取最低）
   - 热门帖标题（互动最高的那条）
4. 反向用例：`{"sentiment":"正面"}`（中文未映射）→ context 不含维度/热门帖数据（只含"点击了情感分布图"提示），验证后端对非法 sentiment 值的安全降级。

前端（`tests/test_dialog_frontend.py`）：
- 现有测试检查 app.js 源码含 `bindChartClick`/`getZr`；补一条检查 donut click 调 `openDialog("sentiment", ...)`（确认 anchor 类型不再是 "trend"）。

集成验证（可选，CDP 或手动）：
- 启动服务，打开看板，点 donut 负面扇区，确认对话框显示负面占比 + 维度 + 热门帖（非空）。

## 6. 涉及文件

- `frontend/static/js/app.js`、`api/routes/dialog.py`
- `tests/test_dialog_api.py`、`tests/test_dialog_frontend.py`

## 7. 非目标（YAGNI）

- 不做"相对全局差值"的维度分析（进阶，本次只要绝对画像）。
- 不改 donut 视觉/布局（只改 click 行为）。
- 不动 reports.py / `_compute_dim_sentiment`（避免影响深报）。
- 不加 sentiment anchor 的 LLM 特别提示词（context 注入后走现有 dialog LLM 流程）。
- 不处理 source='news' 维度（SELF_ONLY + 情感口径，与 dashboard 一致）。
