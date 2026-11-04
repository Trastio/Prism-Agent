# Pipeline Quality Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复启源Q05 全流程跑通暴露的 7 个采集+分析链路质量问题（P0-P3），让数据可信、看板不空壳、采集不残留浏览器。

**Architecture:** 7 个问题拆成 9 个独立 task。除 Task 2（清洗脚本依赖 Task 1 的白名单常量）外，其余 task 互不依赖，可全部并行。每个 task 走 TDD（写测试→跑失败→实现→跑通过→commit）。涉及一个 vendor submodule 改动（无）和两个运维脚本（清洗旧数据 + 抽样核查）。

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy async / SQLite / pytest-asyncio / GLM-4-Flash API / MediaCrawler (subprocess) / ECharts 前端

**运行环境（关键，非显而易见）：**
- 项目跑在 conda `base` 环境：`C:/Users/<you>/Anaconda3/python.exe`
- 默认 `python` 会解析到错误的 venv（缺 sqlalchemy 等），所有命令必须用上面的完整路径
- 测试命令模板：`C:/Users/<you>/Anaconda3/python.exe -m pytest tests/<file>.py -v`
- 测试基线：404 passed, 0 failed（1 个已知 pytest-asyncio 环境误差可忽略）
- 工作区当前已有 4 个未提交改动（analyzer.py / relevance_filter.py / media_crawler.py / scheduler.py，是 6-14 的并发化修复），本 plan 的改动叠加在其上，最后统一提交时注意区分

---

## File Structure

| 文件 | 责任 | 本 plan 动作 |
|------|------|------------|
| `pipeline/analysis/analyzer.py` | 双模型分析 + API 解析 | Task 1：dim 白名单过滤 + prompt 补"油耗" |
| `pipeline/analysis/local_absa.py` | 本地 ABSA（已有 `ALL_DIMENSIONS`） | 不改，作为白名单 single source |
| `pipeline/analysis/heat_calculator.py` | 4 层热度计算 | Task 4：attention_index fallback |
| `pipeline/scheduler.py` | 采集调度 | Task 3：groupon 接入；Task 8：老帖过滤 |
| `pipeline/collectors/platform_strategy.py` | 平台策略 | Task 5：抖音/快手 fetch_detail=False |
| `pipeline/collectors/media_crawler.py` | MC 封装 | Task 7：_kill_orphan_chrome 匹配放宽 |
| `api/routes/analysis.py` | 分析 trigger 入口 | Task 6：接入 fetch_top_comments |
| `scripts/clean_dim_sentiment.py` | 运维脚本（新建） | Task 2：清洗旧 861 条脏维度 |
| `scripts/audit_irrelevant.py` | 运维脚本（新建） | Task 9：抽样核查 286 条 irrelevant |
| `tests/test_analyzer.py` | analyzer 测试 | Task 1：新增维度过滤测试 |
| `tests/test_heat_calculator.py` | 热度测试 | Task 4：更新 fallback 后的断言 |
| `tests/test_scheduler.py` | 调度测试 | Task 3/8：新增 groupon + 老帖过滤测试 |
| `tests/test_platform_strategy.py` | 策略测试 | Task 5：新增 fetch_detail 断言 |
| `tests/test_media_crawler.py` | MC 测试 | Task 7：新增匹配字符串测试 |
| `tests/test_analysis_api.py` | 分析 API 测试 | Task 6：新增评论接入测试 |

**依赖关系：**
- Task 2 → 依赖 Task 1（复用 `VALID_DIMENSIONS`）
- 其余 task 互不依赖，可并行

---

## Task 1: dim_sentiment 维度白名单过滤（P0-① 代码侧）

**Files:**
- Modify: `pipeline/analysis/analyzer.py:16-24`（import + 常量）、`pipeline/analysis/analyzer.py:255-257`（过滤逻辑）、`pipeline/analysis/analyzer.py:38-42`（prompt 补"油耗"）
- Test: `tests/test_analyzer.py`（新增测试方法）

- [ ] **Step 1: 写失败测试**

在 `tests/test_analyzer.py` 的 `class TestParseResponse` 内追加：

```python
    def test_parse_filters_non_whitelist_dimensions(self):
        """dim_sentiment 必须只保留 15 个标准维度，丢弃 LLM 自创维度。"""
        raw = json.dumps({
            "event_tags": [],
            "opinion_tags": [],
            "sentiment": "positive",
            "dim_sentiment": {
                "外观": 1,
                "砍价技巧": 1,
                "销量": 1,
                "颠簸道路稳定性": -1,
                "售后服务": 0,
            },
            "confidence": 0.9,
        })
        result = AnalysisPipeline._parse_response(raw)
        assert result["dim_sentiment"] == {"外观": 1, "售后服务": 0}

    def test_parse_keeps_all_15_standard_dimensions(self):
        """全部 15 个标准维度都应保留。"""
        from pipeline.analysis.local_absa import ALL_DIMENSIONS
        dims = {d: 1 for d in ALL_DIMENSIONS}
        raw = json.dumps({
            "event_tags": [], "opinion_tags": [],
            "sentiment": "positive",
            "dim_sentiment": dims,
            "confidence": 0.9,
        })
        result = AnalysisPipeline._parse_response(raw)
        assert set(result["dim_sentiment"].keys()) == set(ALL_DIMENSIONS)
        assert len(result["dim_sentiment"]) == 15
```

- [ ] **Step 2: 跑测试确认失败**

Run: `C:/Users/<you>/Anaconda3/python.exe -m pytest tests/test_analyzer.py::TestParseResponse::test_parse_filters_non_whitelist_dimensions tests/test_analyzer.py::TestParseResponse::test_parse_keeps_all_15_standard_dimensions -v`
Expected: FAIL — `assert {'外观': 1, '砍价技巧': 1, ...} == {'外观': 1, '售后服务': 0}`（当前不过滤）

- [ ] **Step 3: 实现——import 白名单 + 过滤逻辑**

`pipeline/analysis/analyzer.py` 顶部 import 区（line 10 附近）追加：

```python
from pipeline.analysis.local_absa import ALL_DIMENSIONS

# dim_sentiment 维度白名单——single source 来自 local_absa.ALL_DIMENSIONS
VALID_DIMENSIONS = frozenset(ALL_DIMENSIONS)
```

`_parse_response`（line 255-257）改为：

```python
        dim_sentiment = data.get("dim_sentiment", {}) or {}
        if not isinstance(dim_sentiment, dict):
            dim_sentiment = {}
        # 只保留 15 个标准维度，丢弃 LLM 自创维度（销量/砍价技巧/颠簸道路稳定性 等）
        dim_sentiment = {k: v for k, v in dim_sentiment.items() if k in VALID_DIMENSIONS}
```

- [ ] **Step 4: 实现——prompt 补"油耗"维度**

`COMBINED_ANALYSIS_PROMPT`（line 38-42）的维度列表当前缺"油耗"。改为与 `local_absa.ALL_DIMENSIONS` 一致（15 个）：

```
   可选维度及分数（-1负面, 0中性, 1正面）：
   动力/加速, 续航里程, 电耗, 充电体验, 智能化/车机, 辅助驾驶/智驾,
   价格/性价比, 舒适性, 操控, 安全性, 内饰, 外观, 空间, 售后服务, 油耗
   文本中未涉及的维度不要输出。
```

（仅在该列表末尾加 `, 油耗`）

- [ ] **Step 5: 跑测试确认通过**

Run: `C:/Users/<you>/Anaconda3/python.exe -m pytest tests/test_analyzer.py -v`
Expected: PASS（含原有 + 2 个新测试）

- [ ] **Step 6: 跑全量确认无回归**

Run: `C:/Users/<you>/Anaconda3/python.exe -m pytest tests/test_analyzer.py tests/test_batch_runner.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add pipeline/analysis/analyzer.py tests/test_analyzer.py
git commit -m "fix(analyzer): filter dim_sentiment to 15-dimension whitelist (reuse local_absa.ALL_DIMENSIONS)"
```

---

## Task 2: 清洗旧 861 条脏 dim_sentiment（P0-① 数据侧）

**Files:**
- Create: `scripts/clean_dim_sentiment.py`

- [ ] **Step 1: 写清洗脚本**

`scripts/clean_dim_sentiment.py`：

```python
"""清洗 analyzed_posts.dim_sentiment——丢弃非 15 标准维度的脏数据。

背景：GLM-4-Flash 早期未过滤，输出了上百个自创维度（销量/砍价技巧/颠簸道路稳定性 等）。
本脚本用 local_absa.ALL_DIMENSIONS 白名单清洗历史数据，让维度雷达/热力图可用。

用法：
    C:/Users/<you>/Anaconda3/python.exe scripts/clean_dim_sentiment.py [vehicle_id]

不带 vehicle_id 则清洗全表。
"""
import json
import sqlite3
import sys

from pipeline.analysis.local_absa import ALL_DIMENSIONS

VALID = set(ALL_DIMENSIONS)
DB = "data/vehicle_sentiment.db"


def main():
    vehicle_id = sys.argv[1] if len(sys.argv) > 1 else None
    conn = sqlite3.connect(DB)
    if vehicle_id:
        rows = conn.execute(
            "SELECT id, dim_sentiment FROM analyzed_posts WHERE vehicle_id=? AND dim_sentiment IS NOT NULL",
            (vehicle_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, dim_sentiment FROM analyzed_posts WHERE dim_sentiment IS NOT NULL"
        ).fetchall()

    cleaned_count = 0
    emptied_count = 0
    for aid, dj in rows:
        try:
            d = json.loads(dj) if dj else {}
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(d, dict):
            continue
        cleaned = {k: v for k, v in d.items() if k in VALID}
        if cleaned != d:
            conn.execute(
                "UPDATE analyzed_posts SET dim_sentiment=? WHERE id=?",
                (json.dumps(cleaned, ensure_ascii=False), aid),
            )
            cleaned_count += 1
            if not cleaned:
                emptied_count += 1
    conn.commit()
    conn.close()
    print(f"清洗完成: 共 {len(rows)} 行，修正 {cleaned_count} 行（其中 {emptied_count} 行清空为 {{}}）")
    print(f"白名单维度({len(VALID)}): {sorted(VALID)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑脚本清洗启源Q05**

Run: `C:/Users/<you>/Anaconda3/python.exe scripts/clean_dim_sentiment.py 67e33f8e-3f37-4855-b705-c83158b77d53`
Expected: 输出 "清洗完成: 共 861 行，修正 N 行（其中 M 行清空为 {}）"

- [ ] **Step 3: 验证清洗结果**

Run:
```bash
C:/Users/<you>/Anaconda3/python.exe -c "import sqlite3,json; c=sqlite3.connect('data/vehicle_sentiment.db'); from collections import Counter; cnt=Counter(); [cnt.update(json.loads(d).keys()) for (d,) in c.execute(\"SELECT dim_sentiment FROM analyzed_posts WHERE vehicle_id='67e33f8e-3f37-4855-b705-c83158b77d53' AND dim_sentiment IS NOT NULL\")] or None; print(sorted(cnt.keys())); print('维度种类数:', len(cnt))"
```
Expected: 维度种类数 == 15，列表为 `['动力/加速', '续航里程', '电耗', '充电体验', '智能化/车机', '辅助驾驶/智驾', '价格/性价比', '舒适性', '操控', '安全性', '内饰', '外观', '空间', '售后服务', '油耗']`

- [ ] **Step 4: Commit**

```bash
git add scripts/clean_dim_sentiment.py
git commit -m "chore: add dim_sentiment cleanup script for legacy dirty dimensions"
```

---

## Task 3: attention_index 接入 gopup 百度指数（P0-② 代码侧）

**Files:**
- Modify: `pipeline/scheduler.py:454`（`_store_index_data` 调用点）
- Test: `tests/test_scheduler.py`（新增测试）

- [ ] **Step 1: 写失败测试**

在 `tests/test_scheduler.py` 的 `class TestCollectVehicle` 内追加：

```python
    @pytest.mark.asyncio
    async def test_goupon_index_collected_and_stored(self, db, vehicle):
        """collect_vehicle 应调用 goupon 采集百度指数并写入 HeatMetric.attention_index。"""
        from pipeline.scheduler import CollectionScheduler
        from models.schemas import HeatMetric
        s = CollectionScheduler(db)
        baidu_data = [
            {"date": "2026-05-20", "keyword": "海豹", "index": 1234, "source": "baidu"},
        ]
        with patch.object(s, "_import_historical", new_callable=AsyncMock, return_value=([], [])), \
             patch.object(s, "_collect_news", new_callable=AsyncMock, return_value=[]), \
             patch.object(s, "_collect_mc_platform", new_callable=AsyncMock, return_value=([], [])), \
             patch.object(s, "_crawl_full_texts", new_callable=AsyncMock, side_effect=lambda p: p), \
             patch.object(s, "_resolve_urls", new_callable=AsyncMock, side_effect=lambda p: p), \
             patch.object(s, "_run_dedup", side_effect=lambda p: p), \
             patch.object(s, "_expand_keywords_if_needed", new_callable=AsyncMock, return_value=["海豹EV"]), \
             patch.object(s._goupon, "collect_baidu_index", new_callable=AsyncMock, return_value=baidu_data):
            await s.collect_vehicle(vehicle.id)
        metrics = (await db.execute(
            select(HeatMetric).where(HeatMetric.vehicle_id == vehicle.id)
        )).scalars().all()
        assert any(m.attention_index == 1234.0 for m in metrics)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `C:/Users/<you>/Anaconda3/python.exe -m pytest tests/test_scheduler.py::TestCollectVehicle::test_goupon_index_collected_and_stored -v`
Expected: FAIL — 没有任何 HeatMetric 的 attention_index == 1234（当前传空列表）

- [ ] **Step 3: 实现——接入 groupon**

`pipeline/scheduler.py` 的 `collect_vehicle` 方法，找到 line 454 附近的 `await self._store_index_data(vehicle_id, [])`，替换为：

```python
            # 采集百度指数（attention_index）—— groupon 依赖 baidu cookie，可能返回空
            core_kw = self._get_core_keyword(vehicle)
            baidu_index: list[dict] = []
            try:
                baidu_index = await self._gopup.collect_baidu_index(core_kw, start_date, end_date)
                logger.info("Goupon baidu index: %d points for '%s'", len(baidu_index), core_kw)
            except Exception as e:
                logger.warning("Goupon baidu index failed: %s", e)
            await self._store_index_data(vehicle_id, baidu_index)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `C:/Users/<you>/Anaconda3/python.exe -m pytest tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/scheduler.py tests/test_scheduler.py
git commit -m "fix(scheduler): actually collect baidu index via gopup instead of passing empty list"
```

---

## Task 4: attention_index fallback（P0-② 兜底，无 cookie 时也有值）

**Files:**
- Modify: `pipeline/analysis/heat_calculator.py:46`（attention_index 赋值逻辑）
- Test: `tests/test_heat_calculator.py`（更新现有 + 新增 fallback 测试）

- [ ] **Step 1: 写失败测试**

在 `tests/test_heat_calculator.py` 的 `class TestAttentionIndex` 内追加：

```python
    @pytest.mark.asyncio
    async def test_fallback_to_interaction_when_no_baidu_index(self, db, vehicle):
        """无百度指数数据时，attention_index 应回退为 interaction_intensity（让热度图有值）。"""
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        await _seed(db, _make_post(vehicle.id, day, source="mediacrawler", likes=10, comments=5, shares=2))
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        # interaction = 10×1 + 5×5 + 2×10 = 55，无百度指数时 attention 回退为 55.0
        assert metric.attention_index == 55.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `C:/Users/<you>/Anaconda3/python.exe -m pytest tests/test_heat_calculator.py::TestAttentionIndex::test_fallback_to_interaction_when_no_baidu_index -v`
Expected: FAIL — `assert 0.0 == 55.0`（当前无 fallback）

- [ ] **Step 3: 实现——fallback 逻辑**

`pipeline/analysis/heat_calculator.py` 的 `calculate_daily` 方法。

当前 line 46：
```python
        attention_index = existing.attention_index if existing and existing.attention_index else 0.0
```

这行保留（初始赋值）。然后在 line 84（`interaction_intensity = float(...)`）之后、line 86（`if discussion_volume == 0 ...`）之前，插入 fallback：

```python
        # Fallback: 无百度指数（cookie 失效/groupon 未返回）时，用 interaction_intensity 作为热度代理
        # 否则热度趋势图的 attention_index 永远是死的 0
        if attention_index == 0.0 and interaction_intensity > 0:
            attention_index = round(interaction_intensity, 1)
```

- [ ] **Step 4: 更新被破坏的现有测试**

`tests/test_heat_calculator.py` 的 `test_default_attention_zero_when_no_scheduler_data`（line 65-73）当前断言 `attention_index == 0.0`，但该测试的 post 是 `_make_post(vehicle.id, day)`（默认 likes=10, comments=5, shares=2 → interaction=55），fallback 后 attention=55.0。更新断言：

```python
    @pytest.mark.asyncio
    async def test_default_attention_falls_back_to_interaction(self, db, vehicle):
        """无 scheduler 数据时 attention 回退为 interaction_intensity（不再死 0）。"""
        from pipeline.analysis.heat_calculator import HeatMetricCalculator
        day = date(2026, 5, 20)
        await _seed(db, _make_post(vehicle.id, day))
        calc = HeatMetricCalculator(db)
        metric = await calc.calculate_daily(vehicle.id, day)
        # 默认 post: likes=10,comments=5,shares=2 → interaction=55 → fallback 55.0
        assert metric.attention_index == 55.0
```

同时检查 `test_full_four_layer_scenario`（line 209-234）：该测试预先设了 `attention_index=1927.0`（有 scheduler 数据），fallback 不触发，断言 `== 1927.0` 不变。✓

- [ ] **Step 5: 跑测试确认通过**

Run: `C:/Users/<you>/Anaconda3/python.exe -m pytest tests/test_heat_calculator.py -v`
Expected: PASS（含更新后的测试）

- [ ] **Step 6: Commit**

```bash
git add pipeline/analysis/heat_calculator.py tests/test_heat_calculator.py
git commit -m "fix(heat): fallback attention_index to interaction_intensity when baidu index unavailable"
```

---

## Task 5: 抖音/快手改 search_lightweight 省 comment（P1-a）

**Files:**
- Modify: `pipeline/collectors/platform_strategy.py:63-83`（DOUYIN/KUAISHOU fetch_detail=False）
- Test: `tests/test_platform_strategy.py`（若无则新建）

- [ ] **Step 1: 写失败测试**

检查 `tests/test_platform_strategy.py` 是否存在；若不存在则新建文件。在合适的测试类内追加：

```python
class TestDouyinKuaishouStrategy:
    def test_douyin_does_not_fetch_detail(self):
        """抖音改 lightweight 后 fetch_detail=False（走 search_lightweight，不白抓评论）。"""
        from pipeline.collectors.platform_strategy import DOUYIN
        assert DOUYIN.fetch_detail is False

    def test_kuaishou_does_not_fetch_detail(self):
        from pipeline.collectors.platform_strategy import KUAISHOU
        assert KUAISHOU.fetch_detail is False

    def test_douyin_kuaishou_routed_to_lightweight(self):
        """fetch_detail=False 且 fetch_comments=False → scheduler else 分支 → search_lightweight。"""
        from pipeline.collectors.platform_strategy import DOUYIN, KUAISHOU
        for s in (DOUYIN, KUAISHOU):
            assert s.fetch_comments is False
            assert s.fetch_detail is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `C:/Users/<you>/Anaconda3/python.exe -m pytest tests/test_platform_strategy.py::TestDouyinKuaishouStrategy -v`
Expected: FAIL — `assert True is False`（当前 fetch_detail=True）

- [ ] **Step 3: 实现——改 strategy**

`pipeline/collectors/platform_strategy.py` 的 `DOUYIN`（line 63-72），`fetch_detail=True` 改为 `fetch_detail=False`：

```python
DOUYIN = PlatformStrategy(
    risk_level="high",
    max_keywords=1,        # core keyword only
    fetch_detail=False,    # lightweight: search 模式返回的 desc 够分析，避免 search_with_comments 白抓评论
    fetch_comments=False,
    comments_per_post=5,
    max_pages=2,
    inter_request_delay=5,
    top_n_for_comments=3,
)
```

`KUAISHOU`（line 74-83）因为 `fetch_detail=DOUYIN.fetch_detail`，自动跟随。无需单独改。

- [ ] **Step 4: 跑测试确认通过**

Run: `C:/Users/<you>/Anaconda3/python.exe -m pytest tests/test_platform_strategy.py -v`
Expected: PASS

- [ ] **Step 5: 跑 scheduler 测试确认无回归**

Run: `C:/Users/<you>/Anaconda3/python.exe -m pytest tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pipeline/collectors/platform_strategy.py tests/test_platform_strategy.py
git commit -m "perf(strategy): douyin/kuaishou use search_lightweight to skip wasted comment fetching"
```

---

## Task 6: 评论摘要接入分析管线（P1-b，激活评论情感差异组件）

**Files:**
- Modify: `api/routes/analysis.py:31-35`（`_run_analysis_pipeline` 评论摘要阶段）
- Test: `tests/test_analysis_api.py`（新增测试）

- [ ] **Step 1: 写失败测试**

在 `tests/test_analysis_api.py` 内新增测试类（若文件结构不允许则参考现有模式追加）：

```python
class TestCommentSummaryIntegration:
    @pytest.mark.asyncio
    async def test_pipeline_calls_fetch_top_comments_then_summaries(self):
        """_run_analysis_pipeline 应先 fetch_top_comments 再 run_comment_summaries。"""
        import asyncio
        from api.routes.analysis import _run_analysis_pipeline
        from unittest.mock import AsyncMock, patch, MagicMock

        call_order = []

        async def fake_run_for_vehicle(self, vid):
            call_order.append("run_for_vehicle")
            return {"analyzed": 5}

        async def fake_fetch_top(self, vid):
            call_order.append("fetch_top_comments")
            return 3

        async def fake_summaries(self, vid):
            call_order.append("run_comment_summaries")
            return 2

        with patch("api.routes.analysis.BatchAnalysisRunner") as MockRunner, \
             patch("api.routes.analysis.HeatMetricCalculator") as MockCalc, \
             patch("api.routes.analysis.pipeline_phases", {}), \
             patch("pipeline.scheduler.CollectionScheduler") as MockSched:

            runner_inst = MagicMock()
            runner_inst.run_for_vehicle = fake_run_for_vehicle
            runner_inst.run_comment_summaries = fake_summaries
            MockRunner.return_value = runner_inst

            MockCalc.return_value.calculate_range = AsyncMock(return_value=[])

            sched_inst = MagicMock()
            sched_inst.fetch_top_comments = fake_fetch_top
            MockSched.return_value = sched_inst

            sf = MagicMock()
            sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            sf.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("api.routes.analysis.async_session", sf):
                await _run_analysis_pipeline("v001")

        assert call_order.index("fetch_top_comments") < call_order.index("run_comment_summaries")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `C:/Users/<you>/Anaconda3/python.exe -m pytest tests/test_analysis_api.py::TestCommentSummaryIntegration -v`
Expected: FAIL — `fetch_top_comments` 不在 call_order 中（当前管线没调它）

- [ ] **Step 3: 实现——接入 fetch_top_comments**

`api/routes/analysis.py` 的 `_run_analysis_pipeline`，找到 line 28-35：

```python
            runner = BatchAnalysisRunner(session)
            result = await runner.run_for_vehicle(vehicle_id)
            analyzed = result.get("analyzed", 0)

            # Comment summaries for Top 5 posts
            try:
                comment_count = await runner.run_comment_summaries(vehicle_id)
            except Exception:
                comment_count = 0
```

替换为：

```python
            runner = BatchAnalysisRunner(session)
            result = await runner.run_for_vehicle(vehicle_id)
            analyzed = result.get("analyzed", 0)

            # 按需抓 Top N 评论 + 生成摘要（激活评论情感差异组件）
            # fetch_top_comments 必须先于 summaries，否则 comment_summary 全空
            comment_count = 0
            try:
                from pipeline.scheduler import CollectionScheduler
                sched = CollectionScheduler(session)
                await sched.fetch_top_comments(vehicle_id)
                comment_count = await runner.run_comment_summaries(vehicle_id)
            except Exception as e:
                log.warning("Comment summary phase failed: %s", e)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `C:/Users/<you>/Anaconda3/python.exe -m pytest tests/test_analysis_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/routes/analysis.py tests/test_analysis_api.py
git commit -m "feat(analysis): wire fetch_top_comments into pipeline to activate comment summaries"
```

---

## Task 7: 浏览器收尾——_kill_orphan_chrome 匹配放宽（P2-a）

**Files:**
- Modify: `pipeline/collectors/media_crawler.py:84`（wmic 匹配条件）
- Test: `tests/test_media_crawler.py`（新增测试）

- [ ] **Step 1: 写失败测试**

在 `tests/test_media_crawler.py` 内新增测试（参考现有测试模式）：

```python
class TestKillOrphanChrome:
    def test_wmic_matches_all_user_data_dirs_not_just_cdp(self):
        """wmic 匹配应覆盖所有 browser_data user_data_dir，而非仅 cdp_ 前缀。"""
        from unittest.mock import patch, MagicMock
        from pipeline.collectors.media_crawler import MediaCrawlerWrapper

        captured_cmd = []
        def fake_run(cmd, **kwargs):
            captured_cmd.append(cmd)
            m = MagicMock()
            m.stdout = "1234\n"
            m.stderr = ""
            return m

        with patch("pipeline.collectors.media_crawler.subprocess.run", side_effect=fake_run):
            MediaCrawlerWrapper._kill_orphan_chrome()

        # wmic 查询命令应在 captured_cmd[0]
        wmic_cmd = " ".join(captured_cmd[0]) if captured_cmd else ""
        assert "browser_data" in wmic_cmd
        assert "user_data_dir" in wmic_cmd
        # 不应再硬编码只匹配 cdp_ 前缀
        assert "cdp_" not in wmic_cmd
```

- [ ] **Step 2: 跑测试确认失败**

Run: `C:/Users/<you>/Anaconda3/python.exe -m pytest tests/test_media_crawler.py::TestKillOrphanChrome -v`
Expected: FAIL — 当前匹配含 `cdp_`，断言 `"cdp_" not in wmic_cmd` 失败

- [ ] **Step 3: 实现——放宽匹配**

`pipeline/collectors/media_crawler.py` 的 `_kill_orphan_chrome`（line 82-87），wmic 查询条件从：

```python
            result = subprocess.run(
                ["wmic", "process", "where",
                 "commandline like '%browser_data\\\\cdp_%' and name='chrome.exe'",
                 "get", "processid"],
                capture_output=True, text=True, timeout=5,
            )
```

改为（去掉 `cdp_` 前缀要求，覆盖 cdp_ 和非 cdp_ 的所有 MC user-data-dir）：

```python
            result = subprocess.run(
                ["wmic", "process", "where",
                 "commandline like '%browser_data%user_data_dir%' and name='chrome.exe'",
                 "get", "processid"],
                capture_output=True, text=True, timeout=5,
            )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `C:/Users/<you>/Anaconda3/python.exe -m pytest tests/test_media_crawler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/collectors/media_crawler.py tests/test_media_crawler.py
git commit -m "fix(media-crawler): broaden orphan Chrome kill to all browser_data user_data_dirs"
```

---

## Task 8: 采集后按 published_at 过滤老帖（P3）

**Files:**
- Modify: `pipeline/scheduler.py:218`（`_store_posts` 签名）、`pipeline/scheduler.py:446`（调用点）
- Test: `tests/test_scheduler.py`（新增测试）

- [ ] **Step 1: 写失败测试**

在 `tests/test_scheduler.py` 的 `class TestCollectVehicle` 内追加：

```python
    @pytest.mark.asyncio
    async def test_filters_posts_outside_collection_range(self, db, vehicle):
        """采集范围外的老帖（如 2018 年历史污染）不应入库。"""
        from pipeline.scheduler import CollectionScheduler
        mock_posts = [
            {"title": "近期帖", "content": "c" * 50, "url": "https://ex.com/1",
             "source": "bocha", "platform": "news", "published_at": "2026-05-20"},
            {"title": "2018老帖", "content": "old" * 50, "url": "https://ex.com/2",
             "source": "bocha", "platform": "news", "published_at": "2018-07-24"},
        ]
        with patch.object(s, "_import_historical", new_callable=AsyncMock, return_value=([], [])), \
             patch.object(s, "_collect_news", new_callable=AsyncMock, return_value=mock_posts), \
             patch.object(s, "_collect_mc_platform", new_callable=AsyncMock, return_value=([], [])), \
             patch.object(s, "_crawl_full_texts", new_callable=AsyncMock, side_effect=lambda p: p), \
             patch.object(s, "_resolve_urls", new_callable=AsyncMock, side_effect=lambda p: p), \
             patch.object(s, "_run_dedup", side_effect=lambda p: p), \
             patch.object(s, "_expand_keywords_if_needed", new_callable=AsyncMock, return_value=["海豹EV"]):
            result = await s.collect_vehicle(vehicle.id)
        rows = (await db.execute(select(RawPost))).scalars().all()
        titles = [r.title for r in rows]
        assert "近期帖" in titles
        assert "2018老帖" not in titles
```

- [ ] **Step 2: 跑测试确认失败**

Run: `C:/Users/<you>/Anaconda3/python.exe -m pytest tests/test_scheduler.py::TestCollectVehicle::test_filters_posts_outside_collection_range -v`
Expected: FAIL — `"2018老帖" not in titles` 失败（当前不过滤）

- [ ] **Step 3: 实现——_store_posts 加 min_date 参数**

`pipeline/scheduler.py` 的 `_store_posts`（line 218）签名改为：

```python
    async def _store_posts(self, vehicle_id: str, posts: list[dict], min_date: str | None = None) -> int:
```

在循环内（line 235-241 解析 published_at 之后、`self._session.add` 之前）插入过滤：

```python
            published_at = None
            raw_date = post.get("published_at", "")
            if raw_date:
                try:
                    published_at = datetime.fromisoformat(raw_date)
                except (ValueError, TypeError):
                    pass

            # 过滤采集范围外的老帖（MC search 模式无日期过滤，会返回 2018 等历史污染）
            if min_date and published_at:
                try:
                    floor = datetime.fromisoformat(min_date + "T00:00:00")
                except ValueError:
                    floor = None
                if floor and published_at < floor:
                    continue
```

- [ ] **Step 4: 实现——调用点传 start_date**

`pipeline/scheduler.py` 的 `collect_vehicle`（line 446）：

```python
            stored = await self._store_posts(vehicle_id, all_posts)
```

改为：

```python
            stored = await self._store_posts(vehicle_id, all_posts, min_date=start_date)
```

- [ ] **Step 5: 跑测试确认通过**

Run: `C:/Users/<you>/Anaconda3/python.exe -m pytest tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pipeline/scheduler.py tests/test_scheduler.py
git commit -m "fix(scheduler): filter posts outside collection date range to drop legacy pollution"
```

---

## Task 9: irrelevant 帖子抽样核查脚本（P2-b）

**Files:**
- Create: `scripts/audit_irrelevant.py`

- [ ] **Step 1: 写抽样脚本**

`scripts/audit_irrelevant.py`：

```python
"""抽样打印 irrelevant 帖子，供人工核查相关性过滤是否误杀（尤其负面帖）。

背景：启源Q05 negative 仅 3.4%，怀疑相关性过滤误剔了吐槽帖。本脚本随机抽样
30 条 irrelevant 帖，打印 title/content/relevance_score，人工判断是否有误杀。

用法：
    C:/Users/<you>/Anaconda3/python.exe scripts/audit_irrelevant.py [vehicle_id] [sample_size]
"""
import random
import sqlite3
import sys

DB = "data/vehicle_sentiment.db"
DEFAULT_VID = "67e33f8e-3f37-4855-b705-c83158b77d53"


def main():
    vehicle_id = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VID
    sample_size = int(sys.argv[2]) if len(sys.argv) > 2 else 30

    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT id, platform, title, substr(content,1,200), relevance_score, published_at "
        "FROM raw_posts WHERE vehicle_id=? AND analysis_status='irrelevant'",
        (vehicle_id,),
    ).fetchall()

    if not rows:
        print(f"vehicle {vehicle_id} 无 irrelevant 帖子")
        return

    total = len(rows)
    print(f"irrelevant 总数: {total}，抽样 {min(sample_size, total)} 条\n" + "=" * 70)
    sample = random.sample(rows, min(sample_size, total))
    for i, (pid, plat, title, content, score, pub) in enumerate(sample, 1):
        print(f"[{i}] platform={plat} score={score} date={pub}")
        print(f"    标题: {title or '(无)'}")
        print(f"    内容: {content}")
        print("-" * 70)
    print(f"\n核查要点：是否有明显讨论启源Q05的吐槽帖被误标 irrelevant？")
    print(f"误杀比例 = (误杀数 / {len(sample)})，若 >20% 需调整 relevance_filter 规则。")
    conn.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑脚本抽样**

Run: `C:/Users/<you>/Anaconda3/python.exe scripts/audit_irrelevant.py`
Expected: 打印 30 条 irrelevant 帖子，供人工阅读判断

- [ ] **Step 3: 人工核查（非自动化，记录结论）**

阅读输出，统计误杀数。结论写入 commit message 或单独记录。若误杀 >20%，需另起 task 调整 `relevance_filter.py` 规则（不在本 plan 范围）。

- [ ] **Step 4: Commit**

```bash
git add scripts/audit_irrelevant.py
git commit -m "chore: add irrelevant posts audit script for manual misclassification check"
```

---

## Self-Review

**1. Spec coverage（对照审查报告 7 项）：**
- P0-① dim 维度过滤 → Task 1（代码）+ Task 2（清洗旧数据）✓
- P0-② attention_index → Task 3（groupon 接入）+ Task 4（fallback）✓
- P1-a 抖音/快手白抓评论 → Task 5 ✓
- P1-b comment_summary 空壳 → Task 6 ✓
- P2-a 浏览器不收尾 → Task 7 ✓
- P2-b 情感偏正面核查 → Task 9 ✓
- P3 2018 老帖 → Task 8 ✓
- 全部 7 项均有 task 覆盖，无遗漏。

**2. Placeholder scan：**
- 无 TBD/TODO/"implement later"。
- 每个代码 step 都有完整代码块。
- 测试 step 都有完整 assert。
- 运行命令都带完整 python 路径和 expected 输出。

**3. Type consistency：**
- `VALID_DIMENSIONS`（Task 1）= `frozenset(ALL_DIMENSIONS)`，Task 2 脚本用 `set(ALL_DIMENSIONS)` —— 一致，都是 local_absa.ALL_DIMENSIONS 派生。
- `_store_posts(self, vehicle_id, posts, min_date=None)`（Task 8）签名在 step 3 定义、step 4 调用一致。
- `fetch_top_comments`（Task 6）调用 `sched.fetch_top_comments(vehicle_id)` —— 与 scheduler.py:496 定义一致。
- `_kill_orphan_chrome`（Task 7）是 staticmethod，测试 `MediaCrawlerWrapper._kill_orphan_chrome()` 调用一致。

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-14-pipeline-quality-fixes.md`. Two execution options:

**1. Subagent-Driven (recommended)** - 每个 task 派一个新 subagent，task 间 review，快速迭代。Task 1-9 除 Task 2 外可并行分派。

**2. Inline Execution** - 在当前 session 用 executing-plans 批量执行，带 checkpoint。

**Which approach?**

> **并行性提示**：Task 1/3/4/5/6/7/8/9 互不依赖可全部并行；Task 2 必须在 Task 1 之后（复用 `VALID_DIMENSIONS`）。建议先并行做 Task 1 + 其余独立 task，Task 2 最后。
