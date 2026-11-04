# Subject Tagging & Event Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 AnalyzedPost 加 `subject` 字段（主车型/竞品/其他），让事件检测和看板聚合只统计主车型帖，解决事件碎片化(271组/183单帖)和竞品帖(比亚迪海豚164条)污染。

**Architecture:** subject 在 analyzer 的现有 LLM 调用里一并产出（零额外 API 成本），现有 981 帖用规则脚本回填。事件检测 + 全部看板聚合端点过滤 `subject='self'`。新闻帖在共现图里加权做"软锚点"。

**Tech Stack:** Python / SQLAlchemy async / SQLite / GLM-4-Flash / networkx Louvain / jieba

---

## 背景（为什么这么改）

- 启源Q05 事件检测产出 **271 个 EventGroup，其中 183 个只有 1 帖**（碎片化）。event_tag 排行：比亚迪海豚 9、比亚迪海豹 8、启源Q05 才 5——**竞品帖把事件池撕碎了**。
- 164 条比亚迪海豚帖被标 analyzed，混在启源Q05 分析池里，**污染所有聚合**（健康分/情感趋势/词云/事件）。
- 这些竞品帖是 MC 抓抖音/快手时平台连带返回的（搜 Q05 推了同价位海豚），搜索关键词里没有"海豚"。
- 现有 `Vehicle.competitor_ids` 存的是车型 id 引用，不是名称；海豚不是注册车型，靠它识别不了，所以用 LLM + 规则判断 subject。

## 设计决策

- **subject 三值**：`self`（主车型）/ `competitor`（竞品具体车）/ `other`（行业泛谈）。事件检测和聚合只用 `self`。
- **LLM 产 subject**：改 `COMBINED_ANALYSIS_PROMPT` 和 `EVENT_ONLY_PROMPT`，在现有一次调用里多问一句"主要讨论哪款车"，零额外成本。prompt 传入主车型 name/brand。
- **现有数据回填**：规则脚本（提品牌词频对比），不调 LLM，免费快速。新帖走 LLM。
- **过滤位置**：不重构端点结构，在每个 `select(AnalyzedPost)` 加 `.where(AnalyzedPost.subject == 'self')`。新增 NULL 视为 self（兼容回填前/老数据）。
- **新闻锚点**：软方案——`build_keyword_graph` 给 news 帖的边权重 ×3，让新闻话题成为社区吸引子。不做"新闻先聚类社媒后挂载"的硬锚点（复杂度高，留作未来）。
- **碎片清理**：EventGroup 入库前丢弃单帖组（post_count < 2），它们是噪音非事件。

## File Structure

- **Modify** `models/schemas.py` — AnalyzedPost 加 `subject` 列
- **Modify** `models/database.py` — subject 列轻量迁移（CREATE COLUMN IF NOT EXISTS）
- **Modify** `pipeline/analysis/analyzer.py` — 两个 prompt + 两个 parse 方法产 subject
- **Modify** `pipeline/analysis/batch_runner.py` — run_for_vehicle 存 subject
- **Create** `scripts/backfill_subject.py` — 规则回填现有帖
- **Modify** `pipeline/analysis/event_tracker.py` — 加载帖过滤 subject='self' + build_keyword_graph 新闻加权 + EventGroup 丢弃单帖组
- **Modify** `api/routes/dashboard.py` — ~8 个聚合端点加 subject='self' 过滤
- **Test** `tests/test_subject_labeling.py`（新）+ `tests/test_event_tracker.py`（已有，加用例）

---

## Phase 1: Subject 标注（地基）

### Task 1: AnalyzedPost 加 subject 列 + 迁移

**Files:**
- Modify: `models/schemas.py:61-73`（AnalyzedPost 类）
- Modify: `models/database.py`（轻量迁移函数）

- [ ] **Step 1: 写失败测试——列存在性**

`tests/test_subject_labeling.py`（新建）:

```python
import pytest
from sqlalchemy import inspect
from models.database import init_db, engine


@pytest.mark.asyncio
async def test_analyzedpost_has_subject_column(tmp_path, monkeypatch):
    """AnalyzedPost 表必须有 subject 列。"""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    await init_db()
    insp = inspect(engine.sync_engine)
    cols = [c["name"] for c in insp.get_columns("analyzed_posts")]
    assert "subject" in cols
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_subject_labeling.py -q -k subject_column`
Expected: FAIL（列不存在）

- [ ] **Step 3: 加列到 schema**

`models/schemas.py` AnalyzedPost 类，在 `comment_summary` 之后加：

```python
    comment_summary = Column(Text)
    # subject: self=主车型 / competitor=竞品具体车 / other=行业泛谈
    # NULL 视为 self（兼容回填前数据）。事件检测和聚合只取 self。
    subject = Column(String)
```

- [ ] **Step 4: 加迁移**

`models/database.py` 找到现有的轻量迁移块（`ALTER TABLE ... ADD COLUMN` 模式），加：

```python
    # subject 列迁移（AnalyzedPost）
    cols = [r[1] for r in conn.execute("PRAGMA table_info(analyzed_posts)").fetchall()]
    if "subject" not in cols:
        conn.execute("ALTER TABLE analyzed_posts ADD COLUMN subject VARCHAR")
        logger.info("Migrated: added analyzed_posts.subject")
```

（`conn` 是 init_db 里现有的 sync connection；若变量名不同，对齐现有迁移代码的写法。）

- [ ] **Step 5: 跑测试确认通过**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_subject_labeling.py -q -k subject_column`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add models/schemas.py models/database.py tests/test_subject_labeling.py
git commit -m "feat(schema): add subject column to AnalyzedPost"
```

---

### Task 2: LLM prompt 产 subject + parse

**Files:**
- Modify: `pipeline/analysis/analyzer.py:31-67`（两个 prompt）, `136-176`（analyze_single / API 分支传 vehicle name）, `242-315`（parse 方法）
- Test: `tests/test_subject_labeling.py`

- [ ] **Step 1: 写失败测试——parse 提取 subject**

追加到 `tests/test_subject_labeling.py`:

```python
from pipeline.analysis.analyzer import AnalysisPipeline


def test_parse_response_extracts_subject():
    raw = '{"event_tags": [], "opinion_tags": [], "sentiment": "neutral", "dim_sentiment": {}, "confidence": 0.5, "subject": "competitor", "subject_name": "比亚迪海豚"}'
    result = AnalysisPipeline._parse_response(raw)
    assert result["subject"] == "competitor"
    assert result["subject_name"] == "比亚迪海豚"


def test_parse_response_defaults_subject_to_self():
    raw = '{"event_tags": [], "opinion_tags": [], "sentiment": "neutral", "dim_sentiment": {}, "confidence": 0.5}'
    result = AnalysisPipeline._parse_response(raw)
    assert result["subject"] == "self"
    assert result["subject_name"] == ""


def test_parse_event_response_extracts_subject():
    raw = '{"event_tags": [], "opinion_tags": [], "confidence": 0.5, "subject": "self"}'
    result = AnalysisPipeline._parse_event_response(raw)
    assert result["subject"] == "self"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_subject_labeling.py -q -k parse`
Expected: FAIL（result 无 subject 键 / KeyError）

- [ ] **Step 3: 改 COMBINED_ANALYSIS_PROMPT**

`pipeline/analysis/analyzer.py:31`，在 dim_sentiment（第4点）之后、`帖子文本` 之前，插入 subject 判断项，并在 JSON 模板加字段。改后的完整 prompt：

```python
COMBINED_ANALYSIS_PROMPT = """分析这条汽车相关帖文，完成以下判断：

1. event_tags: 从以下标签池中选最多 3 个最匹配的（可为空列表）：
   {event_tags}
   只能从上面的标签池中选择，不要自创标签。

2. opinion_tags: 提取文本中涉及的观点标签（自由提取，不受标签池限制）

3. sentiment: positive / negative / neutral

4. dim_sentiment: 提取各维度评价，格式为 {{"维度名": 分数}}
   可选维度及分数（-1负面, 0中性, 1正面）：
   动力/加速, 续航里程, 电耗, 充电体验, 智能化/车机, 辅助驾驶/智驾,
   价格/性价比, 舒适性, 操控, 安全性, 内饰, 外观, 空间, 售后服务, 油耗
   文本中未涉及的维度不要输出。

5. subject: 这条帖主要讨论哪款车？
   - 若主要讨论 {vehicle_name}（{vehicle_brand}），回复 "self"
   - 若主要讨论另一款具体车型，回复 "competitor"
   - 若是行业泛谈/无具体车型，回复 "other"
   并在 subject_name 填主要讨论的车名（self 时填 {vehicle_name}，other 填空）。

帖子文本：
{text}

请严格以 JSON 格式回复：
{{"event_tags": ["标签1"], "opinion_tags": ["观点1"], "sentiment": "positive/negative/neutral", "dim_sentiment": {{"维度名": 分数}}, "subject": "self/competitor/other", "subject_name": "车名", "confidence": 0.0-1.0}}"""
```

- [ ] **Step 4: 改 EVENT_ONLY_PROMPT**

`pipeline/analysis/analyzer.py:55`，opinion_tags 之后加 subject 项，JSON 模板加字段：

```python
EVENT_ONLY_PROMPT = """分析这条汽车相关帖文，完成以下判断：

1. event_tags: 从以下标签池中选最多 3 个最匹配的（可为空列表）：
   {event_tags}
   只能从上面的标签池中选择，不要自创标签。

2. opinion_tags: 提取文本中涉及的观点标签（自由提取，不受标签池限制）

3. subject: 这条帖主要讨论哪款车？
   - 若主要讨论 {vehicle_name}（{vehicle_brand}），回复 "self"
   - 若主要讨论另一款具体车型，回复 "competitor"
   - 若是行业泛谈/无具体车型，回复 "other"
   并在 subject_name 填主要讨论的车名（self 时填 {vehicle_name}，other 填空）。

帖子文本：
{text}

请严格以 JSON 格式回复：
{{"event_tags": ["标签1"], "opinion_tags": ["观点1"], "subject": "self/competitor/other", "subject_name": "车名", "confidence": 0.0-1.0}}"""
```

- [ ] **Step 5: 改 _parse_response 提取 subject**

`pipeline/analysis/analyzer.py:242`，在 `opinion_tags` 解析之后、`return {` 之前加：

```python
        subject = data.get("subject", "self")
        if subject not in {"self", "competitor", "other"}:
            subject = "self"
        subject_name = data.get("subject_name", "") or ""
        if not isinstance(subject_name, str):
            subject_name = ""
```

并把 return dict 加两键（在 `"confidence"` 前）：

```python
        return {
            "sentiment": sentiment,
            "event_tags": event_tags,
            "opinion_tags": opinion_tags,
            "dim_sentiment": dim_sentiment,
            "subject": subject,
            "subject_name": subject_name,
            "confidence": max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
        }
```

同步改 `_fallback_result`（:299）加：

```python
    @staticmethod
    def _fallback_result() -> dict:
        return {
            "sentiment": "neutral",
            "event_tags": [],
            "opinion_tags": [],
            "dim_sentiment": {},
            "subject": "self",
            "subject_name": "",
            "confidence": 0.0,
        }
```

- [ ] **Step 6: 改 _parse_event_response 提取 subject**

`pipeline/analysis/analyzer.py:278`，opinion_tags 解析后加：

```python
        subject = data.get("subject", "self")
        if subject not in {"self", "competitor", "other"}:
            subject = "self"
        subject_name = data.get("subject_name", "") or ""
```

return dict 加（在 `"confidence"` 前）：

```python
        return {
            "event_tags": event_tags,
            "opinion_tags": opinion_tags,
            "subject": subject,
            "subject_name": subject_name,
            "confidence": max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
        }
```

同步改 `_fallback_event_result`（:309）加 `"subject": "self", "subject_name": "",`。

- [ ] **Step 7: prompt 传 vehicle_name/brand**

`_analyze_event_api`（:122）签名加参数，format 加字段：

```python
    async def _analyze_event_api(self, text: str, vehicle_name: str = "", vehicle_brand: str = "") -> dict:
        prompt = EVENT_ONLY_PROMPT.format(
            event_tags="、".join(EVENT_TAG_POOL),
            vehicle_name=vehicle_name or "本车型",
            vehicle_brand=vehicle_brand or "",
            text=text,
        )
```

`_analyze_combined_api`（API-only 分支，约 :168）同理加参数 + format 加 `vehicle_name`/`vehicle_brand`。

`analyze_single`（:136）和 `analyze_batch`（:181）/`_analyze_batch_dual`（:195）签名加 `vehicle_name`/`vehicle_brand`，透传到上面的 `_analyze_*_api`。本地 ABSA 分支（dual mode 的 local 部分）不涉及 subject，保持不变。

- [ ] **Step 8: 跑测试确认通过**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_subject_labeling.py -q -k parse`
Expected: PASS（3 个用例全过）

- [ ] **Step 9: Commit**

```bash
git add pipeline/analysis/analyzer.py tests/test_subject_labeling.py
git commit -m "feat(analyzer): produce subject (self/competitor/other) in LLM analysis"
```

---

### Task 3: batch_runner 存 subject + 透传车型名

**Files:**
- Modify: `pipeline/analysis/batch_runner.py:123-171`

- [ ] **Step 1: 写失败测试——AnalyzedPost 存 subject**

`tests/test_subject_labeling.py` 追加：

```python
import json
from unittest.mock import AsyncMock, patch
from models.schemas import AnalyzedPost, RawPost, Vehicle
from pipeline.analysis.batch_runner import BatchAnalysisRunner


@pytest.mark.asyncio
async def test_run_for_vehicle_stores_subject(db, monkeypatch):
    """run_for_vehicle 应把 analysis 的 subject 存进 AnalyzedPost。"""
    veh = Vehicle(id="v1", name="启源Q05", brand="长安")
    db.add(veh)
    post = RawPost(id="p1", vehicle_id="v1", platform="wb", content="比亚迪海豚真香",
                   analysis_status="pending")
    db.add(post)
    await db.commit()

    runner = BatchAnalysisRunner(db)
    # mock analyze_batch 返回 competitor
    runner._pipeline.analyze_batch = AsyncMock(return_value=[{
        "sentiment": "positive", "event_tags": [], "opinion_tags": [],
        "dim_sentiment": {}, "subject": "competitor", "subject_name": "比亚迪海豚",
        "confidence": 0.9,
    }])
    await runner.run_for_vehicle("v1")

    ap = (await db.execute(__import__("sqlalchemy").select(AnalyzedPost))).scalars().first()
    assert ap.subject == "competitor"
    assert ap.sentiment == "positive"
```

（`db` fixture 沿用 tests 现有的 async session fixture；若名称不同，对齐 tests/test_analysis_api.py 的写法。）

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_subject_labeling.py -q -k stores_subject`
Expected: FAIL（subject 为 None）

- [ ] **Step 3: 改 batch_runner 存 subject**

`pipeline/analysis/batch_runner.py:156`，`self._session.add(AnalyzedPost(...))` 块里加 `subject` 行（在 `dim_sentiment=` 之后）：

```python
                self._session.add(AnalyzedPost(
                    id=str(uuid.uuid4()),
                    post_id=post.id,
                    vehicle_id=vehicle_id,
                    sentiment=analysis["sentiment"],
                    event_tags=json.dumps(analysis.get("event_tags", []), ensure_ascii=False),
                    opinion_tags=json.dumps(analysis.get("opinion_tags", []), ensure_ascii=False),
                    confidence=max(0.0, min(1.0, confidence)),
                    model_used=model_name,
                    dim_sentiment=json.dumps(analysis.get("dim_sentiment", {}), ensure_ascii=False),
                    subject=analysis.get("subject", "self"),
                ))
```

同方法里把 vehicle name/brand 传给 analyze_batch。`run_for_vehicle`（:127）开头已 `vehicle = await self._session.get(Vehicle, vehicle_id)`，在 `post_dicts` 构造后、调 `analyze_batch` 前透传：

```python
            analyses = await self._pipeline.analyze_batch(
                post_dicts, vehicle_name=vehicle.name, vehicle_brand=vehicle.brand,
            )
```

`analyze_batch` 签名已在 Task 2 Step 7 加了这两个参数，内部透传给 `_analyze_*_api`。

- [ ] **Step 4: 跑测试确认通过**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_subject_labeling.py -q -k stores_subject`
Expected: PASS

- [ ] **Step 5: 跑现有分析测试确认无回归**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_analysis_api.py tests/test_analyzer.py -q`
Expected: 已有用例全 PASS（除已知 pytest-asyncio 偶发 OSError）

- [ ] **Step 6: Commit**

```bash
git add pipeline/analysis/batch_runner.py tests/test_subject_labeling.py
git commit -m "feat(batch-runner): persist subject + pass vehicle name to analyzer"
```

---

### Task 4: 规则回填现有 981 帖的 subject

**Files:**
- Create: `scripts/backfill_subject.py`

- [ ] **Step 1: 写脚本**

`scripts/backfill_subject.py`（规则：统计主车型词 vs 竞品品牌词的提及频率判定 subject）:

```python
"""规则回填 analyzed_posts.subject（不调 LLM，免费快速）。

判定：统计 title+content 里主车型名/品牌 vs 其他汽车品牌的提及次数，
提及次数最多的类别决定 subject。主车型提及 >=1 且 >= 竞品 → self；
竞品提及 > 主车型 → competitor；都无 → other。

用法：python scripts/backfill_subject.py [--vehicle-id VID] [--dry-run]
"""
import argparse
import re
import sqlite3
import sys
from collections import Counter

# 主车型从 Vehicle 表读；竞品品牌词硬编码（常见电车竞品）
COMPETITOR_BRANDS = {
    "比亚迪": ["比亚迪", "BYD"],
    "海豚": ["海豚"],
    "海豹": ["海豹"],
    "元PLUS": ["元PLUS", "元plus", "元 plus"],
    "特斯拉": ["特斯拉", "Tesla", "TESLA", "Model 3", "Model Y", "model3", "modely"],
    "小鹏": ["小鹏"],
    "蔚来": ["蔚来", "NIO"],
    "理想": ["理想", "L7", "L8", "L9"],
    "埃安": ["埃安", "AION"],
    "五菱": ["五菱", "缤果"],
    "吉利": ["吉利", "银河"],
    "零跑": ["零跑", "C10", "C11", "C01"],
}


def count_mentions(text: str, words: list[str]) -> int:
    return sum(len(re.findall(re.escape(w), text)) for w in words)


def classify(text: str, self_words: list[str]) -> tuple[str, str]:
    """返回 (subject, subject_name)。"""
    self_n = count_mentions(text, self_words)
    comp_counts = {name: count_mentions(text, words) for name, words in COMPETITOR_BRANDS.items()}
    comp_best = max(comp_counts.items(), key=lambda x: x[1])
    if self_n == 0 and comp_best[1] == 0:
        return ("other", "")
    if comp_best[1] > self_n:
        return ("competitor", comp_best[0])
    if self_n > 0:
        return ("self", "")
    # self_n==0 但有竞品提及
    return ("competitor", comp_best[0]) if comp_best[1] > 0 else ("other", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vehicle-id")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect("data/vehicle_sentiment.db")
    where = "WHERE a.subject IS NULL"
    joins = "FROM analyzed_posts a JOIN raw_posts r ON r.id = a.post_id JOIN vehicles v ON v.id = a.vehicle_id"
    if args.vehicle_id:
        where += f" AND a.vehicle_id = '{args.vehicle_id}'"

    rows = con.execute(
        f"SELECT a.id, COALESCE(r.title,'') || ' ' || COALESCE(r.content,''), v.name, v.brand {joins} {where}",
    ).fetchall()
    print(f"待回填: {len(rows)} 条")

    updated = Counter()
    for ap_id, text, vname, vbrand in rows:
        self_words = [w for w in [vname, vbrand] if w]
        subject, sname = classify(text, self_words)
        updated[subject] += 1
        if not args.dry_run:
            con.execute("UPDATE analyzed_posts SET subject=?, WHERE id=?".replace("?,", "?", 1),
                        (subject, ap_id))
    # 上一行 SQL 因 subject_name 无列故只更新 subject；修正写法：
    if not args.dry_run:
        con.commit()
    print("分布:", dict(updated))
    if args.dry_run:
        print("(dry-run，未写入)")


if __name__ == "__main__":
    main()
```

注意：上面 UPDATE 有笔误。最终脚本里用这条干净的：

```python
        if not args.dry_run:
            con.execute("UPDATE analyzed_posts SET subject=? WHERE id=?", (subject, ap_id))
```

（删掉前一个含 `.replace` 的错误版本，用这条。）

- [ ] **Step 2: dry-run 验证分布合理**

Run: `"C:/Users/<you>/Anaconda3/python.exe" scripts/backfill_subject.py --vehicle-id 67e33f8e-3f37-4855-b705-c83158b77d53 --dry-run`
Expected: 输出分布，self 应占多数（~700+），competitor ~150-200（海豚/海豹），other 少量。人工抽查几条 competitor 判定是否合理。

- [ ] **Step 3: 抽查 competitor 判定**

Run（看回填为 competitor 的帖是不是真竞品）:
```bash
"C:/Users/<you>/Anaconda3/python.exe" -c "import sqlite3; con=sqlite3.connect('data/vehicle_sentiment.db'); [print(r[0][:50]) for r in con.execute(\"SELECT r.title FROM analyzed_posts a JOIN raw_posts r ON r.id=a.post_id WHERE a.subject='competitor' LIMIT 8\")]"
```
Expected: 标题多为比亚迪海豚/海豹等竞品车（不是动物海豚、不是启源Q05）。若误判多，调 COMPETITOR_BRANDS 词表后重跑 dry-run。

- [ ] **Step 4: 正式回填**

Run: `"C:/Users/<you>/Anaconda3/python.exe" scripts/backfill_subject.py --vehicle-id 67e33f8e-3f37-4855-b705-c83158b77d53`
Expected: 输出"分布: {'self': N, 'competitor': N, 'other': N}"，写入完成。

- [ ] **Step 5: 验证 DB**

Run:
```bash
"C:/Users/<you>/Anaconda3/python.exe" -c "import sqlite3; con=sqlite3.connect('data/vehicle_sentiment.db'); [print(r) for r in con.execute(\"SELECT subject, COUNT(*) FROM analyzed_posts GROUP BY subject\")]"
```
Expected: 三类都有计数，无 NULL（或 NULL 仅极少）。

- [ ] **Step 6: Commit**

```bash
git add scripts/backfill_subject.py
git commit -m "feat(scripts): rule-based backfill of analyzed_posts.subject"
```

---

## Phase 2: 事件检测质量（解决 #1 碎片化 + #2 事件污染）

### Task 5: 事件检测只取 subject='self'

**Files:**
- Modify: `pipeline/analysis/event_tracker.py:439-442`
- Test: `tests/test_event_tracker.py`

- [ ] **Step 1: 写失败测试——competitor 帖不进事件检测**

`tests/test_event_tracker.py` 追加（若文件不存在则新建，沿用其 fixture 风格）:

```python
from pipeline.analysis.event_tracker import detect_events_from_posts


def test_competitor_posts_excluded_from_event_inputs():
    """detect 应只处理 self 帖；competitor/other 在更上层已过滤。
    这里测 detect_events_from_posts 接收的 posts 都当 self 处理（已是过滤后）。
    上层 detect_events_for_vehicle 的过滤在集成测试覆盖。"""
    posts = [
        {"id": "1", "title": "续航", "content": "续航实测500公里",
         "topic_keywords": ["续航", "实测"], "published_at": "2026-06-01", "likes": 10},
    ]
    events = detect_events_from_posts(posts)
    assert isinstance(events, list)
```

集成测试（需要 DB fixture）追加到 `tests/test_subject_labeling.py`:

```python
@pytest.mark.asyncio
async def test_event_detection_excludes_competitor_posts(db):
    """detect_events_for_vehicle 只用 subject='self' 的帖。"""
    from pipeline.analysis.event_tracker import detect_events_for_vehicle
    veh = Vehicle(id="v1", name="启源Q05", brand="长安")
    db.add(veh)
    # 两条帖关键词不同，一条 self 一条 competitor
    for pid, subj, kw in [("p1", "self", "续航"), ("p2", "competitor", "海豚")]:
        rp = RawPost(id=pid, vehicle_id="v1", platform="wb", content=kw,
                     published_at="2026-06-01", analysis_status="analyzed")
        db.add(rp)
        db.add(AnalyzedPost(id="a"+pid, post_id=pid, vehicle_id="v1", sentiment="neutral",
                            subject=subj))
    await db.commit()

    # mock 掉 LLM 调用，避免真请求
    with patch("pipeline.analysis.event_tracker.annotate_topics_batch", new=AsyncMock(return_value=["续航","海豚"])):
        events = await detect_events_for_vehicle("v1", db)
    used_post_ids = set()
    for e in events:
        used_post_ids |= set(json.loads(e["post_ids"]) if isinstance(e.get("post_ids"), str) else e.get("post_ids", []))
    # competitor 帖 p2 不应出现在任何事件里
    assert "a p2" not in used_post_ids and "p2" not in used_post_ids
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_subject_labeling.py -q -k excludes_competitor`
Expected: FAIL（competitor 帖 p2 当前会被纳入）

- [ ] **Step 3: 加过滤**

`pipeline/analysis/event_tracker.py:439`，把：

```python
    result = await session.execute(
        select(AnalyzedPost).where(AnalyzedPost.vehicle_id == vehicle_id)
    )
```

改为：

```python
    # 只用主车型帖（subject='self'）；NULL 视为 self 兼容老数据
    result = await session.execute(
        select(AnalyzedPost).where(
            AnalyzedPost.vehicle_id == vehicle_id,
            or_(AnalyzedPost.subject == "self", AnalyzedPost.subject.is_(None)),
        )
    )
```

文件顶部 import 加 `from sqlalchemy import select, or_`（若 or_ 未导入）。

- [ ] **Step 4: 跑测试确认通过**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_subject_labeling.py -q -k excludes_competitor`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/analysis/event_tracker.py tests/test_subject_labeling.py tests/test_event_tracker.py
git commit -m "feat(event-tracker): exclude non-self posts from event detection"
```

---

### Task 6: 丢弃单帖事件组（碎片清理）

**Files:**
- Modify: `pipeline/analysis/event_tracker.py:524-548`（入库循环）

- [ ] **Step 1: 写失败测试——单帖组不入库**

`tests/test_event_tracker.py` 追加:

```python
def test_single_post_events_dropped():
    """post_count < 2 的事件不入库（噪音非事件）。"""
    from pipeline.analysis.event_tracker import assemble_events
    posts = [
        {"id": "1", "topic_keywords": ["续航"], "published_at": "2026-06-01", "likes": 1},
        {"id": "2", "topic_keywords": ["完全不同的话题XYZ"], "published_at": "2026-06-02", "likes": 1},
        {"id": "3", "topic_keywords": ["完全不同的话题XYZ"], "published_at": "2026-06-02", "likes": 1},
    ]
    # partition: 续航=0, 孤立话题=1（两条）
    partition = {"续航": 0, "完全不同的话题XYZ": 1}
    events = assemble_events(posts, partition)
    # 社区1有两条→成事件；社区0一条→应被丢弃
    counts = [e["post_count"] for e in events]
    assert all(c >= 2 for c in counts), f"应丢弃单帖组，实际 {counts}"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_event_tracker.py -q -k single_post`
Expected: FAIL（当前单帖组会保留）

- [ ] **Step 3: assemble_events 末尾过滤**

`pipeline/analysis/event_tracker.py` `assemble_events` 函数末尾（return events 前），加最小帖数过滤。找到 `assemble_events` 的 return 语句，改为：

```python
    # 丢弃单帖组（噪音非事件，碎片化主因之一）
    _MIN_EVENT_POSTS = 2
    events = [e for e in events if e.get("post_count", 0) >= _MIN_EVENT_POSTS]
    return events
```

- [ ] **Step 4: 跑测试确认通过**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_event_tracker.py -q -k single_post`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/analysis/event_tracker.py tests/test_event_tracker.py
git commit -m "feat(event-tracker): drop single-post event groups (noise)"
```

---

### Task 7: 新闻帖共现图加权（软锚点，解决 #3）

**Files:**
- Modify: `pipeline/analysis/event_tracker.py:180-205`（build_keyword_graph）, `463-472`（post_dicts 加 platform）

- [ ] **Step 1: 写失败测试——news 帖边权更高**

`tests/test_event_tracker.py` 追加:

```python
def test_news_posts_weighted_higher_in_graph():
    """platform='news' 的帖在共现图里边权 ×3。"""
    import networkx as nx
    from pipeline.analysis.event_tracker import build_keyword_graph
    # 两条帖共享关键词"续航"：一条 news 一条社媒
    posts = [
        {"id": "1", "topic_keywords": ["续航", "实测"], "platform": "news"},
        {"id": "2", "topic_keywords": ["续航", "实测"], "platform": "wb"},
    ]
    G = build_keyword_graph(posts)
    # news×3 + 社媒×1 = 4
    assert G["续航"]["实测"]["weight"] == 4
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_event_tracker.py -q -k news_posts_weighted`
Expected: FAIL（当前权重=2）

- [ ] **Step 3: build_keyword_graph 加权**

`pipeline/analysis/event_tracker.py:180`，改函数（加 `_NEWS_EDGE_WEIGHT` 常量 + 按平台乘权重）:

```python
_NEWS_EDGE_WEIGHT = 3  # 新闻帖边权倍数（软锚点：让新闻话题成为社区吸引子）


def build_keyword_graph(posts: list[dict]) -> nx.Graph:
    """Build a keyword co-occurrence graph from posts.

    Each post's keywords are fully connected (complete subgraph).
    Edge weight = sum over posts of (post_weight), where news posts
    contribute _NEWS_EDGE_WEIGHT (soft anchor) and others 1.
    """
    G = nx.Graph()

    for post in posts:
        keywords = post.get("topic_keywords", [])
        if not keywords:
            continue
        w = _NEWS_EDGE_WEIGHT if post.get("platform") == "news" else 1

        for kw in keywords:
            if not G.has_node(kw):
                G.add_node(kw)

        for i in range(len(keywords)):
            for j in range(i + 1, len(keywords)):
                kw_a, kw_b = keywords[i], keywords[j]
                if G.has_edge(kw_a, kw_b):
                    G[kw_a][kw_b]["weight"] += w
                else:
                    G.add_edge(kw_a, kw_b, weight=w)

    return G
```

- [ ] **Step 4: post_dicts 带 platform**

`pipeline/analysis/event_tracker.py` 的 `detect_events_for_vehicle` 里，构造 post_dicts 时（约 :463）加 platform。把每条 dict 加：

```python
        post_dicts.append({
            "id": ap.id,
            "post_id": ap.post_id,
            "title": title or "",
            "content": (content or "")[:200],
            "sentiment": ap.sentiment,
            "published_at": pub or datetime.now(),
            "likes": raw[4] if raw else 0,
            "comments_count": raw[5] if raw else 0,
            "platform": raw_data_platform.get(ap.post_id, ""),  # 新增
        })
```

为此 raw_data 查询要带上 platform。把 `:448` 的 raw_result select 改为加 `RawPost.platform`：

```python
    raw_result = await session.execute(
        select(RawPost.id, RawPost.published_at, RawPost.title, RawPost.content,
               RawPost.likes, RawPost.comments, RawPost.platform).where(
            RawPost.id.in_(post_ids)
        )
    )
    raw_data = {r[0]: r for r in raw_result.all()}
    raw_data_platform = {r[0]: r[6] for r in raw_data.values()}
```

（注意 raw_data 现在是 {id: (id,pub,title,content,likes,comments,platform)} 七元组，前面用到 raw[4]/raw[5] 的下标不变。）

- [ ] **Step 5: 跑测试确认通过**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_event_tracker.py -q -k news_posts_weighted`
Expected: PASS

- [ ] **Step 6: 跑全部事件检测测试**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_event_tracker.py -q`
Expected: 全 PASS

- [ ] **Step 7: Commit**

```bash
git add pipeline/analysis/event_tracker.py tests/test_event_tracker.py
git commit -m "feat(event-tracker): weight news posts x3 in co-occurrence graph (soft anchor)"
```

---

### Task 8: 端到端验证——重跑事件检测看碎片化下降

**Files:** 无代码改动，验证 Task

- [ ] **Step 1: 重启服务 + 触发分析（只跑事件检测阶段）**

服务需加载新代码。kill 旧服务（`netstat -ano | grep :8000 | grep LISTEN` 找 PID + `taskkill //F //T //PID`），重启：

```bash
cd "C:/Users/<you>/Desktop/Agent项目/Vehicle Sentiment Analysis Board"
"C:/Users/<you>/Anaconda3/python.exe" scripts/backfill_subject.py  # 确保回填已跑
nohup "C:/Users/<you>/Anaconda3/python.exe" -u start.py > run.log 2>&1 &
sleep 9
curl -s -X POST "http://localhost:8000/api/analysis/trigger/67e33f8e-3f37-4855-b705-c83158b77d53"
```

- [ ] **Step 2: 等待事件检测完成（~2-5 分钟）+ 查 EventGroup 数**

```bash
"C:/Users/<you>/Anaconda3/python.exe" -c "import sqlite3; con=sqlite3.connect('data/vehicle_sentiment.db'); rows=con.execute(\"SELECT post_count FROM event_groups WHERE vehicle_id='67e33f8e-3f37-4855-b705-c83158b77d53'\").fetchall(); print('EventGroup 总数:', len(rows), '| 单帖组:', sum(1 for r in rows if r[0]<2))"
```

Expected: 总数从 271 显著下降（目标 <60），单帖组 = 0（Task 6 丢弃）。event_tag 排行不再被比亚迪海豚/海豹主导。

- [ ] **Step 3: 抽查事件质量**

```bash
"C:/Users/<you>/Anaconda3/python.exe" -c "
import sqlite3; con=sqlite3.connect('data/vehicle_sentiment.db')
for r in con.execute(\"SELECT event_tag, post_count, start_date FROM event_groups WHERE vehicle_id='67e33f8e-3f37-4855-b705-c83158b77d53' ORDER BY post_count DESC LIMIT 12\"):
    print(r)
"
```

Expected: 高帖数组 event_tag 是启源Q05 真实事件（新车发布/续航/降价/试驾…），不是竞品。

- [ ] **Step 4: 若碎片化仍高，记录现象供调参**

若 EventGroup 仍 >60，可能是 Louvain 分辨率。记录到本计划末尾"调参备忘"，但不在本计划内调（避免范围蔓延）。

- [ ] **Step 5: Commit 验证记录（可选）**

无代码改动，跳过 commit。

---

## Phase 3: 看板聚合过滤 subject='self'（解决 #2 完整污染）

### Task 9: dashboard 端点加 self 过滤

**Files:**
- Modify: `api/routes/dashboard.py`（overview / sentiment-trend / event-distribution / competitor-comparison / comment-sentiment-diff / posts / top-posts 等约 8 处 select(AnalyzedPost)）

- [ ] **Step 1: 写失败测试——overview 不计 competitor**

`tests/test_subject_labeling.py` 追加:

```python
from fastapi.testclient import TestClient
from api.main import app


@pytest.mark.asyncio
async def test_overview_excludes_competitor_posts(db, monkeypatch):
    """overview 的 sentiment 计数只算 self 帖。"""
    veh = Vehicle(id="v1", name="启源Q05", brand="长安"); db.add(veh)
    # 1 self positive + 1 competitor positive
    for pid, subj, sent in [("p1","self","positive"), ("p2","competitor","positive")]:
        db.add(RawPost(id=pid, vehicle_id="v1", platform="wb", content="x"))
        db.add(AnalyzedPost(id="a"+pid, post_id=pid, vehicle_id="v1", sentiment=sent, subject=subj))
    await db.commit()
    # 让 app 用这个 db（依项目 fixture 注入方式，可能需 override dependency）
    client = TestClient(app)
    resp = client.get("/api/dashboard/overview/v1")
    data = resp.json()
    # 只算 self 的 1 条 positive，competitor 的不计
    pos = next((c["count"] for c in data.get("sentiment_counts", []) if c["sentiment"]=="positive"), 0)
    assert pos == 1, f"应只计 self positive=1，实际 {pos}"
```

（若项目用 dependency override 注入 session，按 tests/test_analysis_api.py 的方式 override get_session 指向测试 db。）

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_subject_labeling.py -q -k overview_excludes`
Expected: FAIL（pos==2，competitor 被计入）

- [ ] **Step 3: 加共享过滤辅助**

`api/routes/dashboard.py` 顶部加模块级常量（避免每处重复）:

```python
# 主车型帖过滤条件：subject='self' 或 NULL（兼容老数据/未回填）
SELF_ONLY = or_(AnalyzedPost.subject == "self", AnalyzedPost.subject.is_(None))
```

import 加 `from sqlalchemy import ..., or_`。

- [ ] **Step 4: 逐端点加过滤**

对以下每个 `select(AnalyzedPost...)`，在 `.where(AnalyzedPost.vehicle_id == vehicle_id)` 后追加 `.where(SELF_ONLY)`（或合并进现有 where 用 `and_`）：

1. `get_overview`（:47-58）—— sentiment 计数 + 总数 + dim_sentiment 三处 select
2. `sentiment-trend`（:199-208）—— join AnalyzedPost 的计数
3. `event-distribution`（:262）—— event_tags 查询
4. `competitor-comparison`（:489）—— 注意此端点本身是竞品对比，**不过滤**（它要的就是多车型对比）
5. `comment-sentiment-diff`（:519）—— comment_summary 查询
6. `posts`（:408）—— post_id 子查询
7. `top-posts`（:368）—— post_id/sentiment 查询

示例改法（overview 第一处）:

```python
        sent_result = await session.execute(
            select(AnalyzedPost.sentiment, func.count(AnalyzedPost.id))
            .where(AnalyzedPost.vehicle_id == vehicle_id)
            .where(SELF_ONLY)
            .group_by(AnalyzedPost.sentiment)
        )
```

`competitor-comparison`（:469）保持不过滤——它语义就是跨车型对比。其余 6 处都加。

- [ ] **Step 5: 跑测试确认通过**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_subject_labeling.py -q -k overview_excludes`
Expected: PASS

- [ ] **Step 6: 跑 dashboard 全部测试**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_dashboard.py -q`（若存在；否则跑 test_analysis_api.py）
Expected: 已有用例全 PASS

- [ ] **Step 7: Commit**

```bash
git add api/routes/dashboard.py tests/test_subject_labeling.py
git commit -m "fix(dashboard): filter aggregations to subject=self posts"
```

---

## Phase 4: comment_summary 覆盖（解决 #4）

### Task 10: 拓宽评论摘要选帖窗口

**Files:**
- Modify: `pipeline/analysis/batch_runner.py:35-56`（select_top_posts_for_comments）, `:140`（run_comment_summaries 的 >=5 阈值）

- [ ] **Step 1: 写失败测试——窗口改为全月**

`tests/test_subject_labeling.py` 追加:

```python
@pytest.mark.asyncio
async def test_select_top_posts_uses_monthly_window(db):
    """选帖窗口从半月改为全月，覆盖更多帖。"""
    from pipeline.analysis.batch_runner import select_top_posts_for_comments
    veh = Vehicle(id="v1", name="X", brand="Y"); db.add(veh)
    # 20天前的帖（半月窗外、全月窗内）
    db.add(RawPost(id="old", vehicle_id="v1", platform="wb", content="x",
                   published_at="2026-05-20", likes=999, comments=10))
    await db.commit()
    posts = await select_top_posts_for_comments(db, "v1")
    ids = [p.id for p in posts]
    assert "old" in ids, "全月窗口应包含 20 天前的帖"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_subject_labeling.py -q -k monthly_window`
Expected: FAIL（当前半月窗不含 5/20）

- [ ] **Step 3: 加全月窗口常量 + 改 select**

`pipeline/analysis/batch_runner.py` 顶部参数区（get_current_period 附近）加:

```python
_COMMENT_WINDOW_DAYS = 30  # 评论摘要选帖窗口（原半月=15天，拓宽到全月增覆盖）
```

`select_top_posts_for_comments`（:35）改窗口计算，把：

```python
    start, end = get_current_period()
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end + timedelta(days=1), datetime.min.time())
```

改为：

```python
    end_dt = datetime.combine(date_type.today() + timedelta(days=1), datetime.min.time())
    start_dt = end_dt - timedelta(days=_COMMENT_WINDOW_DAYS)
```

（去掉对 get_current_period 的依赖；date_type 已在文件顶部 import。）

- [ ] **Step 4: 跑测试确认通过**

Run: `"C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_subject_labeling.py -q -k monthly_window`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/analysis/batch_runner.py tests/test_subject_labeling.py
git commit -m "feat(comments): widen comment-summary selection window to 30 days"
```

---

## Self-Review

**Spec coverage:**
- #1 碎片化 → Task 5（过滤竞品）+ Task 6（丢单帖组）+ Task 8（验证）✓
- #2 竞品污染 → Task 1-4（subject 标注+回填）+ Task 5（事件）+ Task 9（聚合）✓
- #3 新闻稀释 → Task 7（新闻加权软锚点）✓
- #4 comment_summary 覆盖 → Task 10（窗口拓宽）✓

**Placeholder scan:** 无 TBD/TODO；每步都有实际代码。Task 4 脚本里有一处刻意标注的"笔误修正"（已在同 Step 给出干净版本），执行时用干净版本。

**Type consistency:** `subject` 字段全程字符串 `"self"/"competitor"/"other"`；`SELF_ONLY` 过滤常量定义在 Task 9 Step 3，Task 9 Step 4 使用；`_NEWS_EDGE_WEIGHT`/`_COMMENT_WINDOW_DAYS`/`_MIN_EVENT_POSTS` 各自定义处使用；`select_top_posts_for_comments` 签名不变（Task 10 只改内部窗口）。

## 调参备忘（验证后若仍不理想）

- 若 Task 8 验证 EventGroup 仍 >60：调 Louvain resolution（`community_louvain.best_partition(G, weight="weight", resolution=0.5)` 降低分辨率合并小社区）。需新增 Task，不在本计划。
- 若 Task 10 后 comment_summary 仍少：把 `run_comment_summaries` 的 `len(comments) < 5` 阈值降到 3，或把 strategy.comments_per_post 从 5 提到 8。需评估 MC 耗时。
