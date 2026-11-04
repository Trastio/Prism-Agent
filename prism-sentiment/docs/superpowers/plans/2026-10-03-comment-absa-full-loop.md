# 评论 ABSA 全量循环清零 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `run_comment_analysis` 用 while 循环清零所有 `dim_sentiment IS NULL` 的评论，修复 A9 负面声量趋势图全 0 的问题。

**Architecture:** 镜像 `run_for_vehicle` 的循环模式——单文件 `batch_runner.py` 的 `run_comment_analysis` 方法加 `while True` 循环，每批 500 条 commit + 累加，NULL 清零即退出，`predict_batch` 抛错自然向上传播（出错即停，已 commit 批次保留）。

**Tech Stack:** Python asyncio, SQLAlchemy 2.0 async, pytest + pytest-asyncio, unittest.mock

**Spec:** `docs/superpowers/specs/2026-10-03-comment-absa-full-loop-design.md`

---

## File Structure

| 文件 | 责任 | 改动类型 |
|---|---|---|
| `pipeline/analysis/batch_runner.py` | `run_comment_analysis` 方法加 while 循环 | Modify (line 325-361) |
| `tests/test_batch_runner.py` | 新增 2 个测试：循环清零 + 出错即停 | Extend |

不改：`api/routes/analysis.py`、`api/routes/collection.py`（调用方接口不变，返回值语义从单批数升级为总数）、`fetch_top_comments`、`derive_comment_sentiment`、`run_for_vehicle`。

---

## Task 1: 新增测试 — 循环清零 NULL 评论

**Files:**
- Test: `tests/test_batch_runner.py` (extend)

- [ ] **Step 1: 在 `tests/test_batch_runner.py` 末尾追加测试**

在文件末尾追加（使用现有 `db` fixture 和 `_no_op_filter` helper，复用同款 in-memory sqlite + StaticPool 模式）：

```python
async def test_run_comment_analysis_loops_until_empty(db, monkeypatch):
    """run_comment_analysis 应循环处理所有 NULL 评论直到清零（>1 批）。"""
    from pipeline.analysis.batch_runner import BatchAnalysisRunner
    from models.schemas import PostComment, RawPost, Vehicle
    import uuid

    vid = "v-comment-loop"
    db.add(Vehicle(id=vid, name="测试车", brand="测试品牌"))
    # 一个 RawPost 作为 PostComment 的父（外键约束）
    db.add(RawPost(id="p-loop", vehicle_id=vid, source="test", platform="weibo",
                   content="父帖", analysis_status="analyzed"))
    # 喂 1200 条 NULL 评论 → 验证 2 批 + 收尾（每批 500）
    for i in range(1200):
        db.add(PostComment(
            id=str(uuid.uuid4()), post_id="p-loop", vehicle_id=vid,
            content=f"评论{i} 续航不错", author="用户",
        ))
    await db.commit()

    runner = BatchAnalysisRunner(db)

    # mock LocalABSAModel.get() 返回已加载 + predict_batch 返回固定 dim_sentiment
    from pipeline.analysis.local_absa import LocalABSAModel
    class FakeModel:
        _loaded = True
        def predict_batch(self, texts, batch_size=16):
            return [{"dim_sentiment": {"续航": 1}} for _ in texts]
    monkeypatch.setattr(LocalABSAModel, "get", lambda cls=LocalABSAModel: FakeModel())

    result = await runner.run_comment_analysis(vid)

    # 全部 1200 条应被分析
    assert result == 1200
    # 验证 NULL 评论已清零
    from sqlalchemy import func
    null_count = (await db.execute(
        select(func.count()).select_from(PostComment).where(
            PostComment.vehicle_id == vid,
            (PostComment.dim_sentiment.is_(None)) | (PostComment.dim_sentiment == ""),
        )
    )).scalar()
    assert null_count == 0
```

- [ ] **Step 2: 运行测试验证它失败**

Run: `python -m pytest tests/test_batch_runner.py::test_run_comment_analysis_loops_until_empty -v`
Expected: FAIL — 返回 500 而非 1200（当前无循环只跑 1 批），NULL 评论剩余 700。

---

## Task 2: 实现 while 循环清零

**Files:**
- Modify: `pipeline/analysis/batch_runner.py:325-361`

- [ ] **Step 1: 替换 `run_comment_analysis` 方法体**

把 `batch_runner.py` 第 325-361 行的 `run_comment_analysis` 方法替换为：

```python
    async def run_comment_analysis(self, vehicle_id: str) -> int:
        """Analyze comments with local ABSA model for dimension sentiment.

        全量循环清零：每批 500 条 NULL 评论，commit + 累加，直到无 NULL 为止。
        predict_batch 抛错自然向上传播（出错即停，已 commit 批次保留）；
        下次调用会接住剩下的 NULL 评论。镜像 run_for_vehicle 的循环模式。
        """
        import os
        from pipeline.analysis.local_absa import LocalABSAModel
        from utils.config import load_api_config

        local_model = LocalABSAModel.get()
        if not local_model._loaded:
            config = load_api_config()
            local_cfg = config.get("local_model", {})
            local_path = local_cfg.get("path", "") or os.environ.get("LOCAL_MODEL_PATH", "")
            if local_path and os.path.exists(os.path.join(local_path, "adapter_config.json")):
                local_model.load(local_path)
            else:
                logger.warning("Local ABSA model path not configured, skipping comment analysis")
                return 0

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

关键改动：
1. 加 `total_analyzed = 0` + `while True` 循环
2. `if not comments: break` 退出条件
3. 每批 `commit` + `total_analyzed += len(valid)`
4. 循环内 `for comment, result in zip(...)` 的 `result` 改名为 `res`（避免遮蔽外层 `result` 查询变量）
5. 加每批日志

- [ ] **Step 2: 运行 Task 1 的测试验证通过**

Run: `python -m pytest tests/test_batch_runner.py::test_run_comment_analysis_loops_until_empty -v`
Expected: PASS — 返回 1200，NULL 评论 0。

- [ ] **Step 3: 提交**

```bash
git add pipeline/analysis/batch_runner.py tests/test_batch_runner.py
git commit -m "feat(absa): run_comment_analysis while 循环全量清零 NULL 评论

单次 LIMIT 500 无循环，导致 A9 5178 条评论只分析 500 条，4678 条 NULL
被 derive_comment_sentiment 判为 neutral，负面声量趋势图全 0。改为 while
循环清零，镜像 run_for_vehicle 模式；predict_batch 抛错即停，已 commit
批次保留，下次调用接住剩余。result 改名 res 避免遮蔽查询变量。"
```

---

## Task 3: 新增测试 — 出错即停

**Files:**
- Test: `tests/test_batch_runner.py` (extend)

- [ ] **Step 1: 在 `tests/test_batch_runner.py` 追加出错即停测试**

```python
async def test_run_comment_analysis_stops_on_error(db, monkeypatch):
    """predict_batch 第 2 批抛错时，第 1 批已 commit 的保留，异常向上传播。"""
    from pipeline.analysis.batch_runner import BatchAnalysisRunner
    from models.schemas import PostComment, RawPost, Vehicle
    from sqlalchemy import func, select as sa_select
    import uuid

    vid = "v-comment-err"
    db.add(Vehicle(id=vid, name="测试车", brand="测试品牌"))
    db.add(RawPost(id="p-err", vehicle_id=vid, source="test", platform="weibo",
                   content="父帖", analysis_status="analyzed"))
    # 1200 条评论 → 第 1 批 500 成功，第 2 批抛错
    for i in range(1200):
        db.add(PostComment(
            id=str(uuid.uuid4()), post_id="p-err", vehicle_id=vid,
            content=f"评论{i}", author="用户",
        ))
    await db.commit()

    runner = BatchAnalysisRunner(db)

    from pipeline.analysis.local_absa import LocalABSAModel
    call_count = {"n": 0}
    class FlakyModel:
        _loaded = True
        def predict_batch(self, texts, batch_size=16):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("模拟推理 OOM")
            return [{"dim_sentiment": {"续航": 1}} for _ in texts]
    monkeypatch.setattr(LocalABSAModel, "get", lambda cls=LocalABSAModel: FlakyModel())

    import pytest
    with pytest.raises(RuntimeError, match="模拟推理 OOM"):
        await runner.run_comment_analysis(vid)

    # 第 1 批 500 条应已 commit（dim_sentiment 非 NULL）
    analyzed_count = (await db.execute(
        sa_select(func.count()).select_from(PostComment).where(
            PostComment.vehicle_id == vid,
            PostComment.dim_sentiment.is_not(None),
            PostComment.dim_sentiment != "",
        )
    )).scalar()
    assert analyzed_count == 500
    # 第 2 批未 commit，剩余 700 条仍 NULL
    null_count = (await db.execute(
        sa_select(func.count()).select_from(PostComment).where(
            PostComment.vehicle_id == vid,
            (PostComment.dim_sentiment.is_(None)) | (PostComment.dim_sentiment == ""),
        )
    )).scalar()
    assert null_count == 700
```

- [ ] **Step 2: 运行测试验证通过**

Run: `python -m pytest tests/test_batch_analysis_stops_on_error -v` （用全名）
实际命令：`python -m pytest tests/test_batch_runner.py::test_run_comment_analysis_stops_on_error -v`
Expected: PASS — RuntimeError 抛出，500 条已 commit，700 条仍 NULL。

- [ ] **Step 3: 提交**

```bash
git add tests/test_batch_runner.py
git commit -m "test(absa): 验证 run_comment_analysis 出错即停语义

predict_batch 第 2 批抛错时，第 1 批 500 条已 commit 保留，异常向上传播，
剩余 700 条 NULL 留待下次调用接住。"
```

---

## Task 4: 回归 + A9 实跑验证

**Files:** 无代码改动

- [ ] **Step 1: 运行 batch_runner 全套测试**

Run: `python -m pytest tests/test_batch_runner.py -v`
Expected: 全 PASS（原有 13 测试 + 新增 2 = 15）。

- [ ] **Step 2: 运行相关评论测试无回归**

Run: `python -m pytest tests/test_comment_analysis.py tests/test_comment_sentiment.py tests/test_local_absa.py tests/test_analysis_api.py -v`
Expected: 全 PASS。

- [ ] **Step 3: 运行全量测试套件**

Run: `python -m pytest tests/ -q`
Expected: 715 passed（713 基线 + 2 新增）。

- [ ] **Step 4: A9 实跑验证**

A9 vehicle_id: `a30dba4e-af6b-4f14-8384-b3e3757cb7f6`

1. 确认 A9 当前 NULL 评论数：
```bash
python -c "
import sqlite3
con=sqlite3.connect('data/vehicle_sentiment.db'); cur=con.cursor()
vid='a30dba4e-af6b-4f14-8384-b3e3757cb7f6'
print('NULL:', cur.execute('SELECT COUNT(*) FROM post_comments WHERE vehicle_id=? AND (dim_sentiment IS NULL OR dim_sentiment=\"\")', (vid,)).fetchone()[0])
print('analyzed:', cur.execute('SELECT COUNT(*) FROM post_comments WHERE vehicle_id=? AND dim_sentiment IS NOT NULL AND dim_sentiment!=\"\"', (vid,)).fetchone()[0])
"
```
Expected before: NULL=4678, analyzed=500

2. 触发 reanalyze（调 API）：
```bash
python -c "
import urllib.request
req=urllib.request.Request('http://127.0.0.1:8000/api/analysis/trigger/a30dba4e-af6b-4f14-8384-b3e3757cb7f6', method='POST')
print(urllib.request.urlopen(req).read()[:100])
"
```

3. 轮询 pipeline-status 直到 `comments_analyzed` 稳定（循环结束）：
```bash
python -c "
import json, urllib.request, time
vid='a30dba4e-af6b-4f14-8384-b3e3757cb7f6'
for i in range(60):
    r=json.load(urllib.request.urlopen(f'http://127.0.0.1:8000/api/vehicles/{vid}/pipeline-status'))
    print(f'[{i}] phase={r[\"phase\"]} analyzed={r[\"analyzed\"]} comments_analyzed={r.get(\"comments_analyzed\",0)}')
    if r['phase'] in ('completed','idle') and r.get('comments_analyzed',0) >= 5000:
        break
    time.sleep(15)
"
```
Expected: `comments_analyzed` 持续增长到 ~5178，phase 最终 completed。

4. 验证负面声量趋势有数据：
```bash
python -c "
import json, urllib.request
from datetime import date, timedelta
vid='a30dba4e-af6b-4f14-8384-b3e3757cb7f6'
end=date(2026,10,3); start=end-timedelta(days=30)
r=json.load(urllib.request.urlopen(f'http://127.0.0.1:8000/api/dashboard/comment-sentiment-overview/{vid}?start={start}&end={end}'))
print('comment-sentiment-overview:', r)
neg_days=[d for d in json.load(urllib.request.urlopen(f'http://127.0.0.1:8000/api/dashboard/comment-sentiment-trend/{vid}?start={start}&end={end}')) if d.get('negative',0)>0]
print('有负面的天数:', len(neg_days))
"
```
Expected: `negative > 0`，有负面的天数 > 0。

- [ ] **Step 5: 提交验证记录（可选）**

如果 A9 实跑数据有变化，记录到 memory。代码无改动无需 commit。

---

## Self-Review

**1. Spec coverage:**
- ✅ while 循环清零 NULL 评论 → Task 2
- ✅ 出错即停（predict_batch 抛错向上传播，已 commit 保留）→ Task 2 实现 + Task 3 测试
- ✅ 接口兼容（返回值从单批数升级为总数，调用方不改）→ Task 2（签名不变）
- ✅ result 改名 res 避免遮蔽 → Task 2 Step 1
- ✅ 测试覆盖（循环清零 + 出错即停）→ Task 1 + Task 3
- ✅ A9 实跑验证 → Task 4

**2. Placeholder scan:** 无 TBD/TODO/省略。所有测试代码完整可运行。

**3. Type consistency:**
- `run_comment_analysis(vehicle_id: str) -> int` 签名不变 ✓
- `LocalABSAModel.get()` / `predict_batch(texts, batch_size=16)` 与源码一致 ✓
- `PostComment.dim_sentiment` 字段名一致 ✓
- 测试中 `sa_select` 别名避免与 `from sqlalchemy import select` 冲突 ✓

**4. 风险提示：**
- Task 1/3 的 `monkeypatch.setattr(LocalABSAModel, "get", ...)` —— `get()` 是 classmethod，lambda 不接 cls 参数用默认参数 `cls=LocalABSAModel` 兜底。需验证 mock 生效（Step 2 的测试失败会暴露）。
- Task 4 A9 实跑依赖本地 Qwen3-4B 模型已加载，若模型路径未配置 `run_comment_analysis` 返回 0（不抛错），需先确认 `LOCAL_MODEL_PATH` 或 config 已配。当前 A9 已分析 500 条说明模型可用 ✓。
