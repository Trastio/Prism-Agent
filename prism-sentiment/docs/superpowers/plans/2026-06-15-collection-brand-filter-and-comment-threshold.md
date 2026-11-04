# Collection Brand Filter + Comment Threshold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 根治竞品采集污染（采集层品牌关键词白名单过滤）+ 降低评论摘要阈值从 5→3 以提升覆盖率。

**Architecture:** 在 `_store_posts()` 入库前检查帖子是否包含目标车型的品牌关键词（从 Vehicle.name + brand 提取），不含则跳过。comment_summary 阈值集中到常量 `_MIN_COMMENTS_FOR_SUMMARY = 3`，两处同步降低。

**Tech Stack:** Python / SQLAlchemy async / SQLite

---

## 背景

- **竞品污染根因**：MC 搜索"启源Q05"时平台算法连带返回同价位竞品帖（比亚迪海豚/海豹/元），64% analyzed 帖不是启源Q05。当前靠 subject='self' 在分析/聚合层过滤，但采集层仍在入库竞品帖——每次新采集或加新车型都会复现。
- **comment_summary 不足**：30 天窗口已生效（`_COMMENT_WINDOW_DAYS = 30`），但选中的热帖评论 < 5 被跳过，仅 11 条摘要产出。根因是社媒热帖的评论抓取量本身有限（微博/小红书风控限制），降低阈值可让更多帖子生成摘要。

---

## File Structure

- **Modify** `pipeline/scheduler.py` — `_store_posts()` 加品牌关键词过滤 + 新增 `_extract_brand_keywords()` 辅助函数
- **Modify** `pipeline/analysis/batch_runner.py` — `_MIN_COMMENTS_FOR_SUMMARY` 常量 + `summarize_comments()` 和 `run_comment_summaries()` 阈值降低
- **Modify** `tests/test_scheduler.py` — 品牌关键词提取 + 入库过滤测试
- **Modify** `tests/test_comment_summary.py` — 阈值降低测试

---

## Phase 1: 采集层品牌关键词过滤（竞品根治）

### Task 1: 品牌关键词提取函数 + 测试

**Files:**
- Modify: `pipeline/scheduler.py`（文件顶部，`DEALER_PATTERNS` 附近加新函数）
- Modify: `tests/test_scheduler.py`（追加测试类）

- [ ] **Step 1: 写失败测试——关键词提取**

`tests/test_scheduler.py` 末尾追加：

```python
class TestBrandKeywords:
    def test_extract_chinese_and_alphanumeric(self):
        """中英文混合车型名应正确拆分为独立关键词。"""
        from pipeline.scheduler import _extract_brand_keywords
        kw = _extract_brand_keywords("启源Q05", "长安")
        assert "启源" in kw
        assert "Q05" in kw
        assert "长安" in kw
        # 不应包含太短的 token
        assert all(len(k) >= 2 for k in kw)

    def test_pure_chinese_name(self):
        """纯中文车型名 + 同品牌不应重复。"""
        from pipeline.scheduler import _extract_brand_keywords
        kw = _extract_brand_keywords("比亚迪海豚", "比亚迪")
        assert "比亚迪海豚" in kw or "比亚迪" in kw
        # 去重
        assert kw.count("比亚迪") <= 1

    def test_english_name(self):
        """英文车型名应正确提取。"""
        from pipeline.scheduler import _extract_brand_keywords
        kw = _extract_brand_keywords("Model 3", "Tesla")
        assert "Model" in kw
        assert "Tesla" in kw
        # "3" 长度 < 2 不应出现
        assert "3" not in kw

    def test_single_char_not_included(self):
        """单字关键词不应出现（如'元'从'元PLUS'提取）。"""
        from pipeline.scheduler import _extract_brand_keywords
        kw = _extract_brand_keywords("元PLUS", "比亚迪")
        # "元" 是单汉字，但正则 [一-鿿]+ 会匹配连续汉字
        # "元PLUS" 中 "元" 是独立汉字连续段，长度=1，应被过滤
        assert "元" not in kw
        assert "PLUS" in kw
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_scheduler.py -q -k BrandKeywords`
Expected: FAIL（`_extract_brand_keywords` 未定义，ImportError）

- [ ] **Step 3: 实现 _extract_brand_keywords**

`pipeline/scheduler.py` 文件顶部，`DEALER_PATTERNS` 之后（`PlatformName = ...` 之前）加：

```python
def _extract_brand_keywords(name: str, brand: str) -> list[str]:
    """Extract brand-specific keywords from vehicle name and brand.

    Splits on Chinese/alphanumeric boundaries so "启源Q05" yields ["启源","Q05"].
    Tokens shorter than 2 chars are discarded (avoids single-char false positives
    like "元" from "元PLUS"). Brand tokens are included to catch industry news
    that mentions the brand without the model name.

    Returns deduplicated list (case-insensitive).
    """
    tokens: list[str] = []
    # Split on boundaries between Chinese runs and alphanumeric runs
    for text in (name, brand):
        if not text:
            continue
        parts = re.findall(r'[一-鿿]+|[A-Za-z0-9]+', text)
        tokens.extend(p for p in parts if len(p) >= 2)
    # Deduplicate case-insensitively, preserving order
    seen: set[str] = set()
    result: list[str] = []
    for t in tokens:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result
```

- [ ] **Step 4: 跑测试确认通过**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_scheduler.py -q -k BrandKeywords`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/scheduler.py tests/test_scheduler.py
git commit -m "feat(scheduler): add _extract_brand_keywords helper for collection filtering"
```

---

### Task 2: _store_posts 加品牌关键词过滤

**Files:**
- Modify: `pipeline/scheduler.py:218-273`（`_store_posts` 方法签名 + 循环内过滤逻辑）
- Modify: `pipeline/scheduler.py:458`（`collect_vehicle` 中调用 `_store_posts` 传参）
- Modify: `tests/test_scheduler.py`（追加集成测试）

- [ ] **Step 1: 写失败测试——采集入库过滤竞品帖**

`tests/test_scheduler.py` 末尾追加（在 TestBrandKeywords 类之后）：

```python
class TestBrandFilter:
    @pytest.mark.asyncio
    async def test_store_posts_filters_non_brand_posts(self, db, vehicle):
        """不含品牌关键词的帖子不应入库。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        posts = [
            {"title": "比亚迪海豚真香", "content": "海豚续航真不错",
             "url": "http://a.com/1", "platform": "dy", "source": "mediacrawler",
             "likes": 10, "comments": 2, "shares": 1, "author": "u1",
             "published_at": "2026-06-01T10:00:00"},
            {"title": "启源Q05试驾体验", "content": "Q05驾驶感受很好",
             "url": "http://a.com/2", "platform": "dy", "source": "mediacrawler",
             "likes": 20, "comments": 5, "shares": 3, "author": "u2",
             "published_at": "2026-06-01T10:00:00"},
        ]
        # vehicle fixture: name="海豹", brand="比亚迪"
        # 品牌关键词: ["海豹", "比亚迪"]
        count = await s._store_posts(
            vehicle.id, posts,
            vehicle_name=vehicle.name, vehicle_brand=vehicle.brand,
        )
        # post 1 "比亚迪海豚" 不含 vehicle 的品牌关键词 "海豹" → 应过滤
        # post 2 是"启源Q05"也不含 "海豹"/"比亚迪" → 应过滤
        # 两者都不含此 vehicle 的品牌关键词 → 均被过滤
        assert count == 0

    @pytest.mark.asyncio
    async def test_store_posts_keeps_brand_matching_posts(self, db, vehicle):
        """含品牌关键词的帖子应正常入库。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        posts = [
            {"title": "海豹降价了", "content": "比亚迪海豹最新优惠",
             "url": "http://a.com/3", "platform": "wb", "source": "mediacrawler",
             "likes": 30, "comments": 8, "shares": 2, "author": "u3",
             "published_at": "2026-06-01T10:00:00"},
        ]
        count = await s._store_posts(
            vehicle.id, posts,
            vehicle_name=vehicle.name, vehicle_brand=vehicle.brand,
        )
        assert count == 1
        # 验证入库的帖子是正确的那条
        from sqlalchemy import select
        from models.schemas import RawPost
        result = await db.execute(select(RawPost).where(RawPost.vehicle_id == vehicle.id))
        stored = result.scalars().all()
        assert len(stored) == 1
        assert "海豹" in stored[0].title

    @pytest.mark.asyncio
    async def test_store_posts_logs_filtered_count(self, db, vehicle, caplog):
        """过滤时应输出 info 日志记录过滤数量。"""
        from pipeline.scheduler import CollectionScheduler
        s = CollectionScheduler(db)
        posts = [
            {"title": "竞品车评测", "content": "其他品牌",
             "url": "http://a.com/4", "platform": "dy", "source": "mediacrawler",
             "likes": 1, "comments": 0, "shares": 0, "author": "u4",
             "published_at": "2026-06-01T10:00:00"},
        ]
        import logging
        with caplog.at_level(logging.INFO, logger="pipeline.scheduler"):
            await s._store_posts(
                vehicle.id, posts,
                vehicle_name=vehicle.name, vehicle_brand=vehicle.brand,
            )
        assert "brand filter" in caplog.text.lower() or "filtered" in caplog.text.lower()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_scheduler.py -q -k BrandFilter`
Expected: FAIL（`_store_posts` 不接受 `vehicle_name`/`vehicle_brand` 参数，TypeError）

- [ ] **Step 3: 改 _store_posts 签名 + 加过滤逻辑**

`pipeline/scheduler.py:218`，把方法签名从：

```python
    async def _store_posts(self, vehicle_id: str, posts: list[dict], min_date: str | None = None) -> int:
```

改为：

```python
    async def _store_posts(self, vehicle_id: str, posts: list[dict], min_date: str | None = None,
                           vehicle_name: str = "", vehicle_brand: str = "") -> int:
```

在 `seen_urls` 初始化之后、`count = 0` 之前加过滤关键字提取：

```python
        # 品牌关键词过滤（采集层竞品根治）
        brand_keywords = _extract_brand_keywords(vehicle_name, vehicle_brand) if vehicle_name else []
```

在 `for post in posts:` 循环体内，`url` 去重检查之后、`published_at` 解析之前，加品牌关键词检查：

```python
            # 品牌关键词白名单：不含目标车型关键词的帖跳过（根治竞品污染）
            if brand_keywords:
                post_text = f"{post.get('title', '')} {post.get('content', '')}"
                if not any(kw.lower() in post_text.lower() for kw in brand_keywords):
                    filtered += 1
                    continue
```

在 `count = 0` 之后加 `filtered = 0`：

```python
        count = 0
        filtered = 0
```

在 `await self._session.commit()` 之前加日志：

```python
        if filtered:
            logger.info("Brand filter: %d posts filtered out (keywords=%s), %d stored for %s",
                        filtered, brand_keywords, count, vehicle_id)
```

完整改动后的 `_store_posts` 方法头部 + 循环体关键部分如下：

```python
    async def _store_posts(self, vehicle_id: str, posts: list[dict], min_date: str | None = None,
                           vehicle_name: str = "", vehicle_brand: str = "") -> int:
        seen_urls: set[str] = set()
        existing = await self._session.execute(
            select(RawPost.url).where(RawPost.vehicle_id == vehicle_id)
        )
        for (url,) in existing:
            if url:
                seen_urls.add(url)

        # 采集范围下限（min_date 不变，循环外算一次，避免每个 post 重复 parse）
        floor = None
        if min_date:
            try:
                floor = datetime.fromisoformat(min_date + "T00:00:00")
            except ValueError:
                floor = None

        # 品牌关键词过滤（采集层竞品根治）
        brand_keywords = _extract_brand_keywords(vehicle_name, vehicle_brand) if vehicle_name else []

        count = 0
        filtered = 0
        for post in posts:
            url = post.get("url", "")
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)

            # 品牌关键词白名单：不含目标车型关键词的帖跳过
            if brand_keywords:
                post_text = f"{post.get('title', '')} {post.get('content', '')}"
                if not any(kw.lower() in post_text.lower() for kw in brand_keywords):
                    filtered += 1
                    continue

            published_at = None
            raw_date = post.get("published_at", "")
            if raw_date:
                try:
                    published_at = datetime.fromisoformat(raw_date)
                except (ValueError, TypeError):
                    pass

            # 过滤采集范围外的老帖（floor 已在循环外算好）
            if floor and published_at and published_at < floor:
                continue

            self._session.add(RawPost(
                id=str(uuid.uuid4()),
                vehicle_id=vehicle_id,
                source=post.get("source", "unknown"),
                platform=post.get("platform", ""),
                title=post.get("title", ""),
                content=post.get("content", ""),
                author=post.get("author", ""),
                url=url,
                published_at=published_at,
                likes=post.get("likes", 0),
                comments=post.get("comments", 0),
                shares=post.get("shares", 0),
                full_content=post.get("full_content"),
            ))
            count += 1

        if filtered:
            logger.info("Brand filter: %d posts filtered out (keywords=%s), %d stored for %s",
                        filtered, brand_keywords, count, vehicle_id)
        await self._session.commit()
        return count
```

- [ ] **Step 4: 改 collect_vehicle 调用传参**

`pipeline/scheduler.py:458`，把调用：

```python
            stored = await self._store_posts(vehicle_id, all_posts, min_date=start_date)
```

改为：

```python
            stored = await self._store_posts(vehicle_id, all_posts, min_date=start_date,
                                             vehicle_name=vehicle.name, vehicle_brand=vehicle.brand)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_scheduler.py -q -k BrandFilter`
Expected: 3 PASS

- [ ] **Step 6: 跑 scheduler 全部已有测试无回归**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_scheduler.py -q`
Expected: 已有用例全 PASS（加上新增共 ~19 PASS）

- [ ] **Step 7: Commit**

```bash
git add pipeline/scheduler.py tests/test_scheduler.py
git commit -m "feat(scheduler): filter collected posts by brand keywords to prevent competitor pollution"
```

---

## Phase 2: comment_summary 阈值降低

### Task 3: 降低评论摘要阈值 5→3

**Files:**
- Modify: `pipeline/analysis/batch_runner.py:16`（加常量）, `:97`（`summarize_comments` 阈值）, `:199`（`run_comment_summaries` 阈值）
- Modify: `tests/test_comment_summary.py:78-86`（改现有测试）, `:128-140`（改边界测试）, 追加新测试

- [ ] **Step 1: 写失败测试——3 条评论应生成摘要**

`tests/test_comment_summary.py` 中，把 `test_summarize_comments_exactly_5` 改为：

```python
@pytest.mark.asyncio
async def test_summarize_comments_exactly_3():
    """Exactly 3 comments should NOT be skipped (new threshold is 3)."""
    comments = [{"content": f"评论{i}", "likes": i} for i in range(3)]
    with patch("pipeline.analysis.batch_runner.AnalysisPipeline") as MockPipeline:
        instance = MockPipeline.return_value
        instance._call_api = AsyncMock(
            return_value='{"is_argumentative": false, "argument_detail": "", '
                         '"genuine_themes": [], "genuine_sentiment": "mixed", '
                         '"genuine_sentiment_score": 0.0, "summary": "test"}'
        )
        result = await summarize_comments(comments, title="标题", content_snippet="内容")
        assert result is not None
```

追加新测试到文件末尾：

```python
@pytest.mark.asyncio
async def test_summarize_comments_skips_2_comments():
    """2 comments (< 3 threshold) should be skipped."""
    result = await summarize_comments(
        [{"content": "评论1", "likes": 5}, {"content": "评论2", "likes": 3}],
        title="标题",
        content_snippet="内容",
    )
    assert result is None


@pytest.mark.asyncio
async def test_summarize_comments_3_comments_not_skipped():
    """3 comments (== threshold) should be processed."""
    comments = [{"content": f"评论{i}", "likes": i} for i in range(3)]
    with patch("pipeline.analysis.batch_runner.AnalysisPipeline") as MockPipeline:
        instance = MockPipeline.return_value
        instance._call_api = AsyncMock(
            return_value='{"is_argumentative": false, "argument_detail": "", '
                         '"genuine_themes": ["续航"], "genuine_sentiment": "positive", '
                         '"genuine_sentiment_score": 0.8, "summary": "正面讨论续航"}'
        )
        result = await summarize_comments(comments, title="标题", content_snippet="内容")
        assert result is not None
        assert result["genuine_sentiment"] == "positive"
```

同时更新 `test_summarize_comments_skips_low_count`（:78）的注释和断言说明：

```python
@pytest.mark.asyncio
async def test_summarize_comments_skips_low_count():
    """Posts with < 3 comments should be skipped."""
    result = await summarize_comments(
        [{"content": "评论1", "likes": 5}, {"content": "评论2", "likes": 3}],
        title="标题",
        content_snippet="内容",
    )
    assert result is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_comment_summary.py -q -k "exactly_3 or skips_2 or 3_comments_not_skipped"`
Expected: `test_summarize_comments_exactly_3` FAIL（5 条通过但 3 条被当前阈值拒绝）；`test_summarize_comments_3_comments_not_skipped` FAIL（3 条被拒绝返回 None）

- [ ] **Step 3: 加常量 + 改两处阈值**

`pipeline/analysis/batch_runner.py:16`，在 `_COMMENT_WINDOW_DAYS` 之后加：

```python
_MIN_COMMENTS_FOR_SUMMARY = 3  # 降低阈值（原5→3）提升评论摘要覆盖率
```

`pipeline/analysis/batch_runner.py:97`，把：

```python
    if len(comments) < 5:
        return None
```

改为：

```python
    if len(comments) < _MIN_COMMENTS_FOR_SUMMARY:
        return None
```

`pipeline/analysis/batch_runner.py:199`，把：

```python
            if len(comments) < 5:
                continue
```

改为：

```python
            if len(comments) < _MIN_COMMENTS_FOR_SUMMARY:
                continue
```

- [ ] **Step 4: 跑测试确认通过**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_comment_summary.py -q`
Expected: 全 PASS（~9 tests）

- [ ] **Step 5: 跑 batch_runner 全部测试无回归**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_batch_runner.py -q`
Expected: 已有用例全 PASS

- [ ] **Step 6: Commit**

```bash
git add pipeline/analysis/batch_runner.py tests/test_comment_summary.py
git commit -m "fix(comments): lower min-comment threshold from 5 to 3 for broader summary coverage"
```

---

## Self-Review

**1. Spec coverage:**
- 竞品采集层根治 → Task 1（关键词提取）+ Task 2（_store_posts 过滤）✓
- comment_summary 阈值降低 → Task 3（常量 + 两处阈值）✓

**2. Placeholder scan:** 无 TBD/TODO；所有 Step 都有完整代码；caplog fixture 是 pytest 内置 fixture（`pip install pytest` 自带），无需额外导入 fixture。

**3. Type consistency:**
- `_extract_brand_keywords(name: str, brand: str) -> list[str]` — 签名在三处一致（定义、Task 1 测试调用、Task 2 _store_posts 调用）
- `_store_posts(..., vehicle_name: str = "", vehicle_brand: str = "")` — 默认空串向后兼容（其他调用点如测试可不传）
- `_MIN_COMMENTS_FOR_SUMMARY = 3` — 一处定义，`summarize_comments` 和 `run_comment_summaries` 两处引用；`summarize_comments` 是模块级函数直接引用模块常量，`BatchAnalysisRunner.run_comment_summaries` 是类方法同理。
- `caplog` — pytest 内置 fixture（`_store_posts` 用 `logger.info` 打日志，caplog 捕获）

## 调参备忘

- 若品牌关键词过滤误杀（false positive 过滤了真相关帖）：调 `_extract_brand_keywords` 加更多 token，或对 news source 跳过过滤（news API 本身按关键词搜索）
- 若过滤力度不够（竞品帖仍大量入库）：在 `_extract_brand_keywords` 中加品牌特有修饰词（如"长安启源"），或加竞品品牌黑名单反向过滤
- 若 comment_summary 阈值 3 仍产出少：检查 PostComment 表实际评论数，可能需要重跑 `fetch_top_comments` 或检查各平台评论抓取成功率
