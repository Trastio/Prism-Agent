# EventGroup.post_ids 语义统一 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `EventGroup.post_ids` 的语义从 AnalyzedPost.id 改为 RawPost.id，与全项目统一，消除命名相同语义不同的误用隐患。

**Architecture:** 改 `assemble_events` 写入端（`event_tracker.py:328`）取 `p["post_id"]`；消费端 `post_by_id`（:522）键同步改 `post_id` 保持自洽；测试 helper `_make_post` 加 `post_id` 键以支持 id≠post_id 的区分测试。TDD：先写区分测试（FAIL）→ 改写入端（PASS）→ 对齐消费端+注释+回归。

**Tech Stack:** Python + SQLAlchemy（纯函数 `assemble_events` 为单测切入点，无需 DB/LLM）；pytest。

**Spec:** `docs/superpowers/specs/2026-07-01-eventgroup-post-ids-semantics-design.md`

---

## File Structure

| 文件 | 责任 | 本次改动 |
|------|------|---------|
| `pipeline/analysis/event_tracker.py` | 事件检测管线 | `:328` 写入改 post_id；`:522` 消费键改 post_id；`:286-289` docstring |
| `models/schemas.py` | ORM 模型 | `:178` EventGroup.post_ids 加注释 |
| `tests/test_event_tracker.py` | 单测 | `_make_post` 加 post_id 键；升级 `:225` 断言；新增区分测试 |

**关键约束**：`assemble_events` 是纯函数（不碰 DB/LLM），是 TDD 最佳切入点。它有两个调用方都传 post dict：`detect_events_for_vehicle`（post_dicts 已含 `post_id` 键，:480）和 `detect_events_from_posts`（posts 来自测试 helper）。因此 helper `_make_post` 必须同步加 `post_id` 键，否则改 `:328` 后两条路径都 KeyError。

**确认不需改**：`test_event_tracker.py:245` 的 `"post_ids": '["p1","p2"]'` 是手构 event dict 喂给 `name_events_sync` 的 fixture，不经 assemble_events，不依赖 id 语义——回归即可。

---

### Task 1: TDD — assemble_events 改存 RawPost.id

**Files:**
- Modify: `tests/test_event_tracker.py:6-14`（`_make_post` helper）
- Modify: `tests/test_event_tracker.py`（新增测试函数，插在 `test_assemble_events` 之后，约 :230）
- Modify: `pipeline/analysis/event_tracker.py:328`

- [ ] **Step 1: 升级 `_make_post` helper 加 `post_id` 键**

把 `tests/test_event_tracker.py:6-14` 替换为：

```python
def _make_post(post_id, title="", content="", published_at=None, sentiment="neutral", raw_id=None):
    """Helper to create a post dict for testing.

    raw_id: RawPost.id（= AnalyzedPost.post_id），默认与 post_id 相同。
    测试 EventGroup.post_ids 语义时传不同值，以区分 AnalyzedPost.id 与 RawPost.id。
    """
    return {
        "id": post_id,
        "post_id": raw_id or post_id,
        "title": title,
        "content": content,
        "sentiment": sentiment,
        "published_at": published_at or datetime(2026, 5, 15, 12, 0),
    }
```

`raw_id` 放参数表末尾且默认 None → 现有调用 `_make_post("p1", "海豚降价", "...", datetime(...))` 位置参数不变、向后兼容（post_id 默认等于 id）。

- [ ] **Step 2: 写失败测试 `test_assemble_events_stores_raw_post_id`**

在 `test_assemble_events`（约 :230 `assert event["post_count"] > 0` 之后、`# ── Event naming tests` 之前）插入：

```python
def test_assemble_events_stores_raw_post_id():
    """EventGroup.post_ids 必须存 RawPost.id（post_id），不是 AnalyzedPost.id（id）。

    回归守护：全项目 post_ids 语义统一为 RawPost.id。id 与 post_id 取不同值，
    才能抓住"存错 id"的回归。
    """
    from pipeline.analysis.event_tracker import (
        extract_keywords, build_keyword_graph, detect_communities,
        assemble_events,
    )
    posts = [
        _make_post("ap-1", raw_id="raw-1", title="海豚降价",
                   content="海豚降价后性价比很高", published_at=datetime(2026, 5, 10)),
        _make_post("ap-2", raw_id="raw-2", title="海豚大降价",
                   content="终于等到了海豚降价", published_at=datetime(2026, 5, 11)),
    ]
    for p in posts:
        p["topic_keywords"] = extract_keywords(f"{p['title']} {p['content']}")

    G = build_keyword_graph(posts)
    partition = detect_communities(G)
    events = assemble_events(posts, partition)

    assert len(events) >= 1
    all_post_ids = []
    for event in events:
        all_post_ids.extend(json.loads(event["post_ids"]))
    # 必须是 RawPost.id，不是 AnalyzedPost.id
    assert "raw-1" in all_post_ids
    assert "raw-2" in all_post_ids
    assert "ap-1" not in all_post_ids
    assert "ap-2" not in all_post_ids
```

（`json` 已在 test 文件 :2 import。）

- [ ] **Step 3: 跑新测试，确认 FAIL**

Run: `conda run -n base python -m pytest tests/test_event_tracker.py::test_assemble_events_stores_raw_post_id -v`

Expected: FAIL — `assert "raw-1" in all_post_ids` 失败（当前 :328 存的是 `p["id"]`="ap-1"/"ap-2"）。

- [ ] **Step 4: 改 `assemble_events` 写入端**

把 `pipeline/analysis/event_tracker.py:328`：

```python
                "post_ids": json.dumps([p["id"] for p in group]),
```

改为：

```python
                "post_ids": json.dumps([p["post_id"] for p in group]),
```

- [ ] **Step 5: 跑新测试，确认 PASS**

Run: `conda run -n base python -m pytest tests/test_event_tracker.py::test_assemble_events_stores_raw_post_id -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_event_tracker.py pipeline/analysis/event_tracker.py
git commit -m "fix(event_tracker): EventGroup.post_ids 改存 RawPost.id（TDD 区分测试守护）"
```

---

### Task 2: 消费端 post_by_id 对齐 + docstring + schema 注释 + 回归

**Files:**
- Modify: `pipeline/analysis/event_tracker.py:522`
- Modify: `pipeline/analysis/event_tracker.py:286-289`（assemble_events docstring）
- Modify: `models/schemas.py:178`
- Modify: `tests/test_event_tracker.py:224-229`（升级 `test_assemble_events` 断言）

- [ ] **Step 1: 改消费端 `post_by_id` 键**

把 `pipeline/analysis/event_tracker.py:522`：

```python
    post_by_id = {p["id"]: p for p in post_dicts}
```

改为：

```python
    post_by_id = {p["post_id"]: p for p in post_dicts}
```

理由：`:524` 的 `pids = json.loads(event["post_ids"])` 现在是 RawPost.id（Task 1 改动），`:526` `post_by_id[pid]` 要匹配，键必须是 post_id。若不改，`if pid in post_by_id` 守卫静默失败 → representative_posts 为空 → 事件命名退化。

- [ ] **Step 2: 更新 assemble_events docstring**

把 `pipeline/analysis/event_tracker.py:286-290`：

```python
    """Assemble events from posts using community partition + time splitting.

    Returns list of event dicts with: post_ids, start_date, end_date,
    keywords, post_count, sentiment_distribution.
    """
```

改为：

```python
    """Assemble events from posts using community partition + time splitting.

    Returns list of event dicts with: post_ids (RawPost.id 的 JSON 数组,
    = AnalyzedPost.post_id), start_date, end_date, keywords, post_count,
    sentiment_distribution.
    """
```

- [ ] **Step 3: 加 `EventGroup.post_ids` 列注释**

把 `models/schemas.py:178`：

```python
    post_ids = Column(Text)
```

改为：

```python
    # JSON 数组，存 RawPost.id（= AnalyzedPost.post_id）；全项目 post_ids 语义统一为 RawPost.id
    post_ids = Column(Text)
```

- [ ] **Step 4: 升级 `test_assemble_events` 断言**

把 `tests/test_event_tracker.py:223-229`：

```python
    assert len(events) >= 1
    for event in events:
        assert "post_ids" in event
        assert "start_date" in event
        assert "end_date" in event
        assert "keywords" in event
        assert event["post_count"] > 0
```

改为：

```python
    assert len(events) >= 1
    for event in events:
        assert "post_ids" in event
        pids = json.loads(event["post_ids"])
        assert isinstance(pids, list)              # post_ids 是合法 JSON 数组
        assert len(pids) == event["post_count"]    # 数量与 post_count 一致
        assert "start_date" in event
        assert "end_date" in event
        assert "keywords" in event
        assert event["post_count"] > 0
```

（该测试 posts 用 `_make_post` 默认 raw_id=None → post_id==id，无区分价值；区分语义由 Task 1 的 `test_assemble_events_stores_raw_post_id` 专门覆盖。此处仅做结构断言升级。）

- [ ] **Step 5: 跑全 test_event_tracker.py，确认全 PASS**

Run: `conda run -n base python -m pytest tests/test_event_tracker.py -v`

Expected: 全部 PASS（含 test_assemble_events、test_assemble_events_stores_raw_post_id、test_detect_events_from_posts 等回归）。

- [ ] **Step 6: Commit**

```bash
git add pipeline/analysis/event_tracker.py models/schemas.py tests/test_event_tracker.py
git commit -m "fix(event_tracker): post_by_id 消费键对齐 RawPost.id + docstring/schema 注释"
```

---

### Task 3: 集成验证（DB 层确认语义）

**Files:**
- Run: 验证脚本（inline，不落库）

- [ ] **Step 1: 单车型重跑事件检测 + DB 校验 post_ids 语义**

Run（项目根，conda base）:

```bash
PYTHONPATH=. PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -c "
import asyncio, json
from sqlalchemy import select
from models.schemas import AnalyzedPost, EventGroup, RawPost
from pipeline.database import async_session_maker
from pipeline.analysis.event_tracker import detect_events_for_vehicle

async def main():
    async with async_session_maker() as s:
        # 取一个有数据的车型
        row = (await s.execute(select(AnalyzedPost.vehicle_id).limit(1))).first()
        if not row:
            print('SKIP: 无 AnalyzedPost 数据'); return
        vid = row[0]
        await detect_events_for_vehicle(vid, s)
        # 校验：EventGroup.post_ids 的值必须在 RawPost.id 集合里
        egs = (await s.execute(select(EventGroup).where(EventGroup.vehicle_id==vid))).scalars().all()
        raw_ids = {r[0] for r in (await s.execute(select(RawPost.id))).all()}
        ap_ids  = {r[0] for r in (await s.execute(select(AnalyzedPost.id))).all()}
        bad = []
        for eg in egs:
            for pid in json.loads(eg.post_ids or '[]'):
                if pid in ap_ids and pid not in raw_ids:
                    bad.append((eg.id, pid, 'looks-like-AnalyzedPost.id'))
        print(f'车型={vid} EventGroup={len(egs)} 校验{\"PASS\" if not bad else \"FAIL: \"+str(bad)}')

asyncio.run(main())
"
```

Expected: 输出 `校验PASS`（EventGroup.post_ids 的值都在 RawPost.id 集合里，且没有"在 AnalyzedPost.id 里但不在 RawPost.id 里"的值）。

- [ ] **Step 2: 若集成验证 SKIP（无数据），则跑相关回归测试套件兜底**

Run: `conda run -n base python -m pytest tests/test_event_tracker.py tests/test_group_api.py -v`

Expected: 全 PASS（test_group_api 含 EventGroup 相关 API 回归）。

> 注：Task 3 为验证步骤，不产生 commit。若 Step 1 发现 post_ids 仍是 AnalyzedPost.id 语义（FAIL），说明 detect_events_for_vehicle 路径有遗漏改动，回 Task 1/2 排查。

---

## Self-Review

**Spec coverage**：
- spec 改动 1（:328）→ Task 1 Step 4 ✓
- spec 改动 2（:522）→ Task 2 Step 1 ✓
- spec 改动 3（docstring :288）→ Task 2 Step 2 ✓
- spec 改动 4（schema :178 注释）→ Task 2 Step 3 ✓
- spec 测试升级（:225）→ Task 2 Step 4 ✓
- spec 新增区分测试 → Task 1 Step 2 ✓
- spec 回归（:245）→ 确认不需改，Task 2 Step 5 回归覆盖 ✓
- spec 集成验证 → Task 3 ✓

**Placeholder scan**：无 TBD/TODO；每个 code step 都有完整代码；命令都有 expected output ✓

**Type consistency**：`_make_post(raw_id=...)` 参数名在 Task 1 Step 1/Step 2 一致；`p["post_id"]` 键在 Task 1 Step 4 / Task 2 Step 1 一致 ✓
