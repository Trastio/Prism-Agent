# 双模式看板（监控 | 传播点报）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 看板拆成双模式（监控看板=产品经理 / 传播点报=传播团队日扫行动点），新增 InsightPoint 混合挖掘管线（规则骨架+GLM 大脑），监控看板砍事件标签分布图、争议帖预警重做为口碑反转卡。

**Architecture:** 后端新增 `InsightPoint` 表 + `pipeline/analysis/point_miner.py`（素材圈定→规则兜底→LLM 提点→Jaccard 证据锚定匹配→纯规则状态机），挂服务管线 Phase 9（`collection.py:_run_full_pipeline`）；API 加 `GET /points/{vid}`、增强 `comment-sentiment-diff`、dialog 加 `point` 锚点。前端零构建：`viewMode` 状态切换双视图，点报逻辑独立 `points.js`。

**Tech Stack:** FastAPI + SQLAlchemy async + SQLite / GLM-4-Flash（utils/llm_client.call_llm）/ Vue 3 CDN 全局构建 + ECharts

**Spec:** `openspec/changes/dual-mode-points-dashboard/`（proposal/design/specs/tasks）
**约定：** conda base 全路径 python = `C:/Users/<you>/Anaconda3/python.exe`（下文简写 `$PY`）；测试命令均在项目根执行；项目直接在 master 工作（无 worktree 惯例）。

---

## 背景知识（给零上下文的实施者）

- **口径常量**（models/schemas.py）：`RELEVANT_ONLY`（排除无关帖）、`SELF_ONLY`（主车型帖）、`AUTHENTIC_AUTHOR`（排除官方/经销商作者）。点挖掘素材**三口径全挂**。
- **JSON 列惯例**：SQLAlchemy 模型用 `Text` 列存 JSON 字符串，读写 `json.loads/dumps`，空值兜底 `or "{}"` / `or "[]"`。
- **时间窗陷阱**：weibo/douyin 帖 `published_at` 常 NULL——素材圈定必须用 `func.coalesce(RawPost.published_at, RawPost.collected_at) >= since`，否则静默丢帖。
- **LLM 客户端**：`utils/llm_client.call_llm(prompt, timeout) -> str`，失败不 raise 而是返回 `"生成失败: ..."` / `"API 未配置..."` 字符串——降级判定靠前缀。
- **管线挂点**：`api/routes/collection.py:_run_full_pipeline` Phase 1-8 已有（采集→分析→热度→评论摘要→评论ABSA→事件→top评论），Phase 9 插点挖掘，包 try/except（失败不断管线）。
- **前端缓存纪律**：改 app.js/style.css 必须递增 `?v=`（当前 21/14 → 本次 22/15），新文件 points.js 用 `?v=1`；index.html 由后端 no-store 返回无需 bump。
- **dialog.js 先例**：零构建下多 `<script>` 全局共享——points.js 定义全局 `PointsUI` 对象，app.js 的 methods/computed 委托调用。

---

### Task 1: InsightPoint 数据模型

**Files:**
- Modify: `models/schemas.py`（文件末尾 VehicleGroup 类之后、Pydantic schemas 之前插入）
- Test: `tests/test_points.py`（新建）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_points.py`：

```python
"""InsightPoint 挖掘管线测试（openspec: insight-point-mining）。"""
import json
import uuid
from datetime import date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from models.schemas import (
    AnalyzedPost, InsightPoint, PostComment, RawPost, Vehicle,
)


@pytest_asyncio.fixture
async def vehicle(db_session):
    v = Vehicle(name="测试车", brand="测试品牌")
    db_session.add(v)
    await db_session.commit()
    return v


def _mk_post(vehicle_id, *, sentiment="positive", platform="weibo", likes=10,
             comments=5, shares=0, author_type="organic",
             analysis_status="analyzed", published_at=None, dim=None):
    """造一对 RawPost+AnalyzedPost，返回 (raw, analyzed)。"""
    raw = RawPost(
        vehicle_id=vehicle_id, source="test", platform=platform,
        title=f"帖子-{uuid.uuid4().hex[:6]}", content="内容内容",
        author="u", likes=likes, comments=comments, shares=shares,
        analysis_status=analysis_status, author_type=author_type,
        published_at=published_at or datetime(2026, 9, 18, 12, 0),
    )
    ap = AnalyzedPost(
        post_id=raw.id, vehicle_id=vehicle_id, sentiment=sentiment,
        subject="self", subject_name="测试车",
        dim_sentiment=json.dumps(dim or {"空间": 0.8}),
    )
    return raw, ap


async def _seed(session, vehicle_id, n=3, **kw):
    pairs = [_mk_post(vehicle_id, **kw) for _ in range(n)]
    session.add_all([o for p in pairs for o in p])
    await session.commit()
    return pairs


@pytest.mark.asyncio
async def test_insight_point_table_created(db_session, vehicle):
    """新表自动建好（create_all），字段齐。"""
    p = InsightPoint(
        vehicle_id=vehicle.id, type="defend", title="测试点", origin="dim",
        status="new", metrics=json.dumps({"volume": 5}),
        evidence_post_ids=json.dumps([]), suggestion="建议",
        detail=json.dumps({}), first_seen=date.today(), last_seen=date.today(),
    )
    db_session.add(p)
    await db_session.commit()
    got = (await db_session.execute(
        select(InsightPoint).where(InsightPoint.vehicle_id == vehicle.id)
    )).scalar_one()
    assert got.type == "defend" and got.status == "new"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$PY -m pytest tests/test_points.py -v`
Expected: FAIL — `ImportError: cannot import name 'InsightPoint'`

- [ ] **Step 3: 加模型**

在 `models/schemas.py` 的 `class VehicleGroup` 之后、`# Pydantic schemas` 注释之前插入：

```python
class InsightPoint(Base):
    """可行动舆情点（2026-09-20 双模式看板）。

    传播团队日扫的「点」：amplify=宣传机会 / defend=防守风险。
    生命周期纯规则（point_miner 状态机）：new→active(发酵)→cooling(降温)
    →archived(3日未匹配)。evidence_post_ids 存 RawPost.id（锚定匹配键，
    Jaccard≥50% 视为同点）。metrics/detail 为 JSON 快照。
    """
    __tablename__ = "insight_points"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vehicle_id = Column(String, nullable=False)
    type = Column(String, nullable=False)          # amplify | defend
    title = Column(String, nullable=False)
    origin = Column(String)                        # comment_theme | viral_post | dim | event | surge
    status = Column(String, default="new")         # new | active | cooling | archived
    metrics = Column(Text)                         # JSON: {volume, cool_streak, ...}
    evidence_post_ids = Column(Text)               # JSON: [RawPost.id]
    suggestion = Column(Text)
    detail = Column(Text)                          # JSON: {rep_comments: [{content, likes, author}]}
    first_seen = Column(Date, nullable=False)
    last_seen = Column(Date, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `$PY -m pytest tests/test_points.py -v`
Expected: PASS（新表由 conftest 的 create_all 自动建，无需 ALTER 迁移）

- [ ] **Step 5: Commit**

```bash
git add models/schemas.py tests/test_points.py
git commit -m "feat(points): InsightPoint 模型——可行动舆情点数据底座"
```

---

### Task 2: point_miner 素材圈定 + 规则兜底点

**Files:**
- Create: `pipeline/analysis/point_miner.py`
- Test: `tests/test_points.py`（追加）

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_points.py`：

```python
from pipeline.analysis.point_miner import _collect_materials, _rule_points


@pytest.mark.asyncio
async def test_collect_materials_caliber(db_session, vehicle):
    """irrelevant / 官方 / 竞品帖不进素材。"""
    vid = vehicle.id
    good = await _seed(db_session, vid, n=2, likes=100)
    await _seed(db_session, vid, n=1, likes=999, analysis_status="irrelevant")
    await _seed(db_session, vid, n=1, likes=999, author_type="brand_official")
    await _seed(db_session, vid, n=1, likes=999, sentiment="positive")
    # 竞品帖：subject=competitor——_mk_post 默认 self，这里手工改
    raws = await _seed(db_session, vid, n=1, likes=999)
    for raw, ap in raws:
        ap.subject = "competitor"
    await db_session.commit()

    m = await _collect_materials(db_session, vid)
    ids = [p["id"] for p in m["posts"]]
    assert all(r.id in ids for r, _ in good)
    assert len(ids) == 2  # 4 类污染帖全部排除


@pytest.mark.asyncio
async def test_collect_materials_coalesce_published_at(db_session, vehicle):
    """published_at NULL 的帖按 collected_at 兜底，不丢。"""
    raw, ap = _mk_post(vehicle.id, likes=50, published_at=None)
    raw.collected_at = datetime(2026, 9, 19, 8, 0)
    db_session.add_all([raw, ap])
    await db_session.commit()
    m = await _collect_materials(db_session, vehicle.id)
    assert raw.id in [p["id"] for p in m["posts"]]


def test_rule_points_dim_thresholds():
    """负面率≥15%且≥3帖 → defend(dim)；0.75 分且≥5帖 → amplify(dim)。"""
    materials = {
        "dim_stats": {
            "售后": {"neg": 3, "total": 20, "avg": -0.2, "neg_posts": ["p1", "p2", "p3"], "pos_posts": []},
            "空间": {"neg": 2, "total": 40, "avg": 0.86, "neg_posts": [], "pos_posts": ["a", "b"]},
        },
        "events": [],
        "posts": [],
        "neg_wow": None,
        "reversals": [],
    }
    pts = _rule_points(materials)
    kinds = {(p["type"], p["origin"], p["title"][:2]) for p in pts}
    assert ("defend", "dim", "售后") in kinds
    assert ("amplify", "dim", "空间") in kinds


def test_rule_points_below_threshold_no_point():
    materials = {
        "dim_stats": {"售后": {"neg": 3, "total": 21, "avg": -0.1, "neg_posts": [], "pos_posts": []}},  # 14.3% < 15%
        "events": [], "posts": [], "neg_wow": None, "reversals": [],
    }
    assert _rule_points(materials) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$PY -m pytest tests/test_points.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.analysis.point_miner'`

- [ ] **Step 3: 写实现**

创建 `pipeline/analysis/point_miner.py`：

```python
"""舆情点挖掘管线（openspec: insight-point-mining，2026-09-20 拍板方案 3 混合）。

规则圈素材+兜底点保下限（维度/事件阈值），GLM-4-Flash 提点拔上限（重点捞
评论区跨帖主题=「索尼8扬」型），证据帖 id Jaccard≥50% 锚定匹配去重，
生命周期状态机纯规则（new/active/cooling/archived）。LLM 失败降级纯兜底。
"""
import json
import logging
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.schemas import (
    AUTHENTIC_AUTHOR, AnalyzedPost, EventGroup, InsightPoint, PostComment,
    RawPost, RELEVANT_ONLY, SELF_ONLY,
)

logger = logging.getLogger(__name__)

MATERIAL_DAYS = 7
TOP_POSTS = 30
TOP_COMMENTS_PER_POST = 3
# 兜底阈值（spec: insight-point-mining）
DIM_NEG_RATE_MIN = 0.15
DIM_NEG_COUNT_MIN = 3
EVENT_NEG_SHARE_MIN = 0.40
DIM_POS_SCORE_MIN = 0.75
DIM_POS_COUNT_MIN = 5
# 匹配与状态机
JACCARD_SAME_POINT = 0.5
ACTIVE_GROWTH = 1.2
COOLING_DROP = 0.8
ARCHIVE_DAYS = 3


async def _collect_materials(session: AsyncSession, vehicle_id: str) -> dict:
    """圈 LLM 视野素材：口径三挂 + coalesce 时间窗。"""
    since = datetime.combine(date.today() - timedelta(days=MATERIAL_DAYS), datetime.min.time())
    window = func.coalesce(RawPost.published_at, RawPost.collected_at) >= since

    rows = await session.execute(
        select(RawPost, AnalyzedPost.sentiment)
        .join(AnalyzedPost, AnalyzedPost.post_id == RawPost.id)
        .where(
            RawPost.vehicle_id == vehicle_id,
            RELEVANT_ONLY, SELF_ONLY, AUTHENTIC_AUTHOR, window,
        )
        .order_by((RawPost.likes + RawPost.comments * 5 + RawPost.shares * 10).desc())
        .limit(TOP_POSTS)
    )
    posts = []
    post_ids = []
    for rp, sentiment in rows.all():
        post_ids.append(rp.id)
        cmt = await session.execute(
            select(PostComment).where(PostComment.post_id == rp.id)
            .order_by(PostComment.likes.desc()).limit(TOP_COMMENTS_PER_POST)
        )
        posts.append({
            "id": rp.id,
            "title": rp.title or (rp.content or "")[:40],
            "platform": rp.platform, "sentiment": sentiment,
            "likes": rp.likes or 0, "comments": rp.comments or 0, "shares": rp.shares or 0,
            "top_comments": [
                {"content": (c.content or "")[:120], "likes": c.likes or 0, "author": c.author}
                for c in cmt.scalars()
            ],
        })

    # 维度统计（负帖数/总出现数/均分 + 证据帖池）
    dim_rows = await session.execute(
        select(AnalyzedPost.sentiment, AnalyzedPost.dim_sentiment, AnalyzedPost.post_id)
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == vehicle_id, SELF_ONLY,
               AUTHENTIC_AUTHOR, RELEVANT_ONLY, window)
    )
    dim_stats: dict[str, dict] = {}
    for sentiment, dim_json, pid in dim_rows.all():
        try:
            dims = json.loads(dim_json) if dim_json else {}
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(dims, dict):
            continue
        for k, v in dims.items():
            if not isinstance(v, (int, float)):
                continue
            s = dim_stats.setdefault(k, {"neg": 0, "total": 0, "score_sum": 0.0,
                                         "neg_posts": [], "pos_posts": []})
            s["total"] += 1
            s["score_sum"] += float(v)
            if sentiment == "negative":
                s["neg"] += 1
                if len(s["neg_posts"]) < 5:
                    s["neg_posts"].append(pid)
            elif sentiment == "positive":
                if len(s["pos_posts"]) < 5:
                    s["pos_posts"].append(pid)
    for s in dim_stats.values():
        s["avg"] = round(s["score_sum"] / s["total"], 3) if s["total"] else 0.0

    # 活跃事件 top5
    ev_rows = await session.execute(
        select(EventGroup).where(
            EventGroup.vehicle_id == vehicle_id,
            EventGroup.end_date >= date.today() - timedelta(days=MATERIAL_DAYS),
        ).order_by(EventGroup.post_count.desc()).limit(5)
    )
    events = []
    for e in ev_rows.scalars():
        try:
            dist = json.loads(e.sentiment_distribution or "{}")
        except (json.JSONDecodeError, TypeError):
            dist = {}
        events.append({
            "tag": e.event_tag, "source": e.source, "post_count": e.post_count,
            "start": str(e.start_date), "end": str(e.end_date),
            "neg": dist.get("negative", 0),
            "post_ids": json.loads(e.post_ids or "[]")[:10],
        })

    # 负面环比（本周 vs 上周）
    week_ago = datetime.combine(date.today() - timedelta(days=7), datetime.min.time())
    two_weeks = datetime.combine(date.today() - timedelta(days=14), datetime.min.time())
    async def _neg_count(lo, hi):
        return (await session.execute(
            select(func.count(AnalyzedPost.id))
            .join(RawPost, AnalyzedPost.post_id == RawPost.id)
            .where(AnalyzedPost.vehicle_id == vehicle_id, SELF_ONLY,
                   AUTHENTIC_AUTHOR, RELEVANT_ONLY,
                   AnalyzedPost.sentiment == "negative", window & (RawPost.published_at >= lo))
        )).scalar() or 0 if hi is None else (await session.execute(
            select(func.count(AnalyzedPost.id))
            .join(RawPost, AnalyzedPost.post_id == RawPost.id)
            .where(AnalyzedPost.vehicle_id == vehicle_id, SELF_ONLY,
                   AUTHENTIC_AUTHOR, RELEVANT_ONLY,
                   AnalyzedPost.sentiment == "negative",
                   func.coalesce(RawPost.published_at, RawPost.collected_at) >= lo,
                   func.coalesce(RawPost.published_at, RawPost.collected_at) < hi)
        )).scalar() or 0
    this_week = await _neg_count(week_ago, None)
    prev_week = await _neg_count(two_weeks, week_ago)
    neg_wow = None
    if prev_week > 0:
        neg_wow = round((this_week - prev_week) / prev_week * 100, 1)
    elif this_week > 0:
        neg_wow = 100.0

    # 口碑反转帖（帖情感 vs 评论真实情感不一致，复用 diff 逻辑）
    reversals = []
    ap_rows = await session.execute(
        select(AnalyzedPost, RawPost).join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == vehicle_id, SELF_ONLY,
               AUTHENTIC_AUTHOR, RELEVANT_ONLY,
               AnalyzedPost.comment_summary.isnot(None))
    )
    for ap, rp in ap_rows.scalars().all() if hasattr(ap_rows, "scalars") else []:
        pass  # 兼容写法占位——见下方真实实现
    for ap, rp in (await session.execute(
        select(AnalyzedPost, RawPost).join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == vehicle_id, SELF_ONLY,
               AUTHENTIC_AUTHOR, RELEVANT_ONLY,
               AnalyzedPost.comment_summary.isnot(None))
    )).all():
        try:
            cs = json.loads(ap.comment_summary) if ap.comment_summary else {}
        except (json.JSONDecodeError, TypeError):
            continue
        gs = cs.get("genuine_sentiment", "")
        if gs and gs != ap.sentiment:
            reversals.append({
                "post_id": rp.id, "title": rp.title or (rp.content or "")[:40],
                "post_sentiment": ap.sentiment, "comment_sentiment": gs,
                "themes": cs.get("genuine_themes", []),
                "summary": (cs.get("summary") or "")[:150],
            })

    return {"posts": posts, "dim_stats": dim_stats, "events": events,
            "neg_wow": neg_wow, "reversals": reversals}
```

**注意**：上面 `_neg_count` 的实现别照抄第一段占位写法——直接采用最终简洁版：

```python
    async def _neg_between(lo, hi):
        q = (
            select(func.count(AnalyzedPost.id))
            .join(RawPost, AnalyzedPost.post_id == RawPost.id)
            .where(
                AnalyzedPost.vehicle_id == vehicle_id, SELF_ONLY,
                AUTHENTIC_AUTHOR, RELEVANT_ONLY,
                AnalyzedPost.sentiment == "negative",
                func.coalesce(RawPost.published_at, RawPost.collected_at) >= lo,
            )
        )
        if hi is not None:
            q = q.where(func.coalesce(RawPost.published_at, RawPost.collected_at) < hi)
        return (await session.execute(q)).scalar() or 0

    this_week = await _neg_between(week_ago, None)
    prev_week = await _neg_between(two_weeks, week_ago)
```

同文件继续追加规则兜底：

```python
def _rule_points(materials: dict) -> list[dict]:
    """结构性兜底点（保下限；LLM 只负责润色，不负责存在性）。"""
    pts = []
    for dim, s in materials["dim_stats"].items():
        if s["total"] and s["neg"] / s["total"] >= DIM_NEG_RATE_MIN and s["neg"] >= DIM_NEG_COUNT_MIN:
            pts.append({
                "type": "defend", "origin": "dim",
                "title": f"{dim}口碑承压：负面率 {s['neg'] / s['total']:.0%}",
                "evidence_post_ids": s["neg_posts"],
                "suggestion": f"关注{dim}真实口碑，评估是否需业务侧跟进",
                "metrics": {"dim_neg_rate": round(s["neg"] / s["total"], 3)},
                "detail": {},
            })
        if s["avg"] >= DIM_POS_SCORE_MIN and s["total"] >= DIM_POS_COUNT_MIN:
            pts.append({
                "type": "amplify", "origin": "dim",
                "title": f"{dim}是口碑亮点：正向分 {s['avg']:.2f}",
                "evidence_post_ids": s["pos_posts"],
                "suggestion": f"可将{dim}作为传播主打角度",
                "metrics": {"dim_avg": s["avg"], "dim_posts": s["total"]},
                "detail": {},
            })
    for e in materials["events"]:
        if e["post_count"] and e["neg"] / e["post_count"] >= EVENT_NEG_SHARE_MIN:
            pts.append({
                "type": "defend", "origin": "event",
                "title": f"事件「{e['tag']}」负面主导（{e['neg']}/{e['post_count']}帖）",
                "evidence_post_ids": e["post_ids"],
                "suggestion": "准备回应口径，跟踪事件走向",
                "metrics": {"event_neg": e["neg"], "event_total": e["post_count"]},
                "detail": {},
            })
    return [p for p in pts if p["evidence_post_ids"]]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `$PY -m pytest tests/test_points.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/analysis/point_miner.py tests/test_points.py
git commit -m "feat(points): 素材圈定(口径三挂+coalesce窗) + 规则兜底点三阈值"
```

---

### Task 3: LLM 提点（含降级与证据校验）

**Files:**
- Modify: `pipeline/analysis/point_miner.py`
- Test: `tests/test_points.py`（追加）

- [ ] **Step 1: 写失败测试**

追加：

```python
from pipeline.analysis.point_miner import _llm_points


def _materials_with_posts(post_ids):
    return {
        "posts": [{"id": pid, "title": "t", "platform": "weibo", "sentiment": "positive",
                   "likes": 10, "comments": 5, "shares": 0,
                   "top_comments": [{"content": "调校后音质好", "likes": 30, "author": "a"}]}
                  for pid in post_ids],
        "dim_stats": {}, "events": [], "neg_wow": None, "reversals": [],
    }


@pytest.mark.asyncio
async def test_llm_points_valid_and_fake_evidence(monkeypatch):
    """正常点保留；伪造 evidence id 的点丢弃。"""
    ids = ["aaa", "bbb", "ccc"]
    fake_payload = {"points": [
        {"type": "amplify", "title": "车机调校攻略热议", "origin": "comment_theme",
         "evidence_post_ids": ["aaa", "bbb"], "suggestion": "出官方设置指南",
         "rep_comment": "调校后音质提升"},
        {"type": "amplify", "title": "伪造点", "origin": "viral_post",
         "evidence_post_ids": ["not-exist"], "suggestion": "x", "rep_comment": ""},
    ]}
    async def fake_llm(prompt, timeout=60):
        return "```json\n" + json.dumps(fake_payload, ensure_ascii=False) + "\n```"
    monkeypatch.setattr("pipeline.analysis.point_miner.call_llm", fake_llm)

    pts, err = await _llm_points(_materials_with_posts(ids))
    assert err is None and len(pts) == 1
    assert pts[0]["evidence_post_ids"] == ["aaa", "bbb"]
    assert pts[0]["detail"]["rep_comments"][0]["content"] == "调校后音质好"


@pytest.mark.asyncio
async def test_llm_points_failure_degrades(monkeypatch):
    """call_llm 失败串 → 空点列表 + 错误信息，不 raise。"""
    async def broken_llm(prompt, timeout=60):
        return "生成失败: timeout"
    monkeypatch.setattr("pipeline.analysis.point_miner.call_llm", broken_llm)
    pts, err = await _llm_points(_materials_with_posts(["a"]))
    assert pts == [] and err and "生成失败" in err
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$PY -m pytest tests/test_points.py -v`
Expected: FAIL — `ImportError: cannot import name '_llm_points'`

- [ ] **Step 3: 写实现**

`point_miner.py` 顶部加 import：

```python
from utils.llm_client import call_llm
```

文件追加：

```python
_LLM_PROMPT = """你是汽车品牌的舆情分析师。以下是某车型近 7 天的舆情素材，请提炼「可行动舆情点」——
传播团队能直接拿去宣传（amplify，好点）或防守（defend，坏点）的话题。

重点发现评论区里的跨帖主题：同一玩法/吐槽/技巧在多篇帖子的评论区反复出现（origin=comment_theme），
这类点最有行动价值。也可从爆帖（viral_post）、事件（event）里提点。

只输出 JSON，不要多余文字：
{{"points": [
  {{"type": "amplify|defend",
    "title": "一句话主张（≤30字，说清是什么点+为什么现在动）",
    "origin": "comment_theme|viral_post|event",
    "evidence_post_ids": ["素材里的帖子id"],
    "suggestion": "建议动作一句话",
    "rep_comment": "最有代表性的评论原文（≤60字，没有就空串）"}}
]}}

素材：
{materials}"""


def _materials_digest(materials: dict) -> str:
    parts = []
    for p in materials["posts"]:
        cmts = " / ".join(f"{c['content']}(▲{c['likes']})" for c in p["top_comments"])
        parts.append(f"帖[{p['id']}] {p['platform']} {p['sentiment']} ▲{p['likes']} 💬{p['comments']} "
                     f"「{p['title']}」 评论: {cmts or '无'}")
    dims = ", ".join(f"{k}(负{v['neg']}/{v['total']}, 均{v['avg']:+.2f})"
                     for k, v in materials["dim_stats"].items())
    if dims:
        parts.append(f"维度统计: {dims}")
    for e in materials["events"]:
        parts.append(f"事件「{e['tag']}」{e['source']} {e['post_count']}帖 负{e['neg']}")
    if materials["neg_wow"] is not None:
        parts.append(f"负面周环比: {materials['neg_wow']:+}%")
    for r in materials["reversals"][:5]:
        parts.append(f"反转帖[{r['post_id']}] 帖{r['post_sentiment']}→评{r['comment_sentiment']} 「{r['title']}」")
    return "\n".join(parts)


async def _llm_points(materials: dict) -> tuple[list[dict], str | None]:
    """GLM 提点。返回 (候选点列表, 错误信息)。失败不 raise。"""
    valid_ids = {p["id"] for p in materials["posts"]}
    prompt = _LLM_PROMPT.format(materials=_materials_digest(materials))
    raw = await call_llm(prompt, timeout=90)
    if raw.startswith("生成失败") or raw.startswith("API 未配置"):
        return [], raw
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("point_miner: LLM 输出非 JSON: %s", raw[:200])
        return [], "LLM 输出不可解析"
    comment_map = {p["id"]: p["top_comments"] for p in materials["posts"]}
    out = []
    for p in payload.get("points", []):
        if p.get("type") not in ("amplify", "defend"):
            continue
        ev = [i for i in p.get("evidence_post_ids", []) if i in valid_ids]
        if not ev or not p.get("title"):
            continue  # 证据必须可回溯
        rep = p.get("rep_comment") or ""
        detail = {}
        if rep:
            top = (comment_map.get(ev[0]) or [{}])[0]
            detail["rep_comments"] = [{"content": rep, "likes": top.get("likes", 0),
                                       "author": top.get("author", "")}]
        out.append({
            "type": p["type"], "origin": p.get("origin", "viral_post"),
            "title": p["title"][:60], "evidence_post_ids": ev,
            "suggestion": (p.get("suggestion") or "")[:120],
            "metrics": {}, "detail": detail,
        })
    return out, None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `$PY -m pytest tests/test_points.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/analysis/point_miner.py tests/test_points.py
git commit -m "feat(points): GLM 提点——comment_theme 发现/JSON 校验/伪造证据丢弃/失败降级"
```

---

### Task 4: 证据锚定匹配 + 生命周期状态机 + 主管线

**Files:**
- Modify: `pipeline/analysis/point_miner.py`
- Test: `tests/test_points.py`（追加）

- [ ] **Step 1: 写失败测试**

追加：

```python
from pipeline.analysis.point_miner import mine_points_for_vehicle


async def _add_point(session, vehicle_id, ev_ids, *, status="new", volume=10,
                     last_seen=None, streak=0):
    p = InsightPoint(
        vehicle_id=vehicle_id, type="defend", title="在榜点", origin="dim",
        status=status, metrics=json.dumps({"volume": volume, "cool_streak": streak}),
        evidence_post_ids=json.dumps(ev_ids), suggestion="", detail="{}",
        first_seen=date.today() - timedelta(days=5),
        last_seen=last_seen or date.today(),
    )
    session.add(p)
    await session.commit()
    return p


@pytest.mark.asyncio
async def test_merge_same_point_updates_not_creates(db_session, vehicle, monkeypatch):
    """证据 Jaccard≥50% → 更新在榜点，不新建。"""
    p = await _add_point(db_session, vehicle.id, ["a", "b", "c", "d"], volume=10)
    async def no_llm(prompt, timeout=60):
        return "API 未配置"
    monkeypatch.setattr("pipeline.analysis.point_miner.call_llm", no_llm)
    # 兜底维度点造证据重叠：seed 负面帖 4 条全带"售后"维
    await _seed(db_session, vehicle.id, n=4, sentiment="negative", dim={"售后": -0.5})
    raws = (await db_session.execute(
        select(RawPost).where(RawPost.vehicle_id == vehicle.id)
    )).scalars().all()
    p.evidence_post_ids = json.dumps([r.id for r in raws])
    await db_session.commit()

    stats = await mine_points_for_vehicle(db_session, vehicle.id)
    total = (await db_session.execute(
        select(func.count(InsightPoint.id)).where(InsightPoint.vehicle_id == vehicle.id)
    )).scalar()
    # 4 负面帖 / 售后维度 100% 负面率 → 兜底点与在榜点证据完全重叠 → 只更新
    assert stats["created"] == 0
    assert total == 1
```

（测试文件顶部 import 补 `from sqlalchemy import func`——若 Task 1 已有则跳过）

```python
@pytest.mark.asyncio
async def test_status_transitions(db_session, vehicle, monkeypatch):
    async def no_llm(prompt, timeout=60):
        return "API 未配置"
    monkeypatch.setattr("pipeline.analysis.point_miner.call_llm", no_llm)
    # active: 昨 volume 10，今日 seed 8 帖（volume ≥ 12）
    await _add_point(db_session, vehicle.id, ["x1"], volume=10)
    await _seed(db_session, vehicle.id, n=8, sentiment="negative", dim={"售后": -0.5})
    await mine_points_for_vehicle(db_session, vehicle.id)
    pts = (await db_session.execute(
        select(InsightPoint).where(InsightPoint.vehicle_id == vehicle.id)
    )).scalars().all()
    assert any(p.status == "active" for p in pts)


@pytest.mark.asyncio
async def test_archive_after_stale_days(db_session, vehicle, monkeypatch):
    async def no_llm(prompt, timeout=60):
        return "API 未配置"
    monkeypatch.setattr("pipeline.analysis.point_miner.call_llm", no_llm)
    # 在榜点 4 天没被匹配且今日无该维度素材 → archived
    await _add_point(db_session, vehicle.id, ["old1", "old2"],
                     last_seen=date.today() - timedelta(days=4))
    await mine_points_for_vehicle(db_session, vehicle.id)
    p = (await db_session.execute(
        select(InsightPoint).where(InsightPoint.vehicle_id == vehicle.id)
    )).scalar_one()
    assert p.status == "archived"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$PY -m pytest tests/test_points.py -v`
Expected: FAIL — `ImportError: cannot import name 'mine_points_for_vehicle'`

- [ ] **Step 3: 写实现**

`point_miner.py` 追加：

```python
def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _volume_of(cand: dict, materials: dict) -> int:
    """点声量 = 证据帖数 + 证据帖评论数（当日素材口径）。"""
    cmt = {p["id"]: p["comments"] for p in materials["posts"]}
    return len(cand["evidence_post_ids"]) + sum(cmt.get(i, 0) for i in cand["evidence_post_ids"])


async def _merge_points(session: AsyncSession, vehicle_id: str,
                        candidates: list[dict], today: date) -> dict:
    stats = {"updated": 0, "created": 0, "archived": 0}
    open_pts = (await session.execute(
        select(InsightPoint).where(InsightPoint.vehicle_id == vehicle_id,
                                   InsightPoint.status != "archived")
    )).scalars().all()

    used: set[int] = set()
    for pt in open_pts:
        if (today - pt.last_seen).days >= ARCHIVE_DAYS:
            pt.status = "archived"
            stats["archived"] += 1
            continue
        ev = set(json.loads(pt.evidence_post_ids or "[]"))
        best, best_j = None, 0.0
        for c in candidates:
            j = _jaccard(set(c["evidence_post_ids"]), ev)
            if j >= JACCARD_SAME_POINT and j > best_j:
                best, best_j = c, j
        if best is None:
            continue  # 今日无素材命中：last_seen 不动，向归档自然老化
        used.add(id(best))
        old_m = json.loads(pt.metrics or "{}")
        vol_new, vol_old = best["volume"], old_m.get("volume", best["volume"])
        streak = old_m.get("cool_streak", 0)
        if vol_new >= max(vol_old, 1) * ACTIVE_GROWTH:
            pt.status, streak = "active", 0
        elif vol_new < vol_old * COOLING_DROP:
            streak += 1
            if streak >= 2:
                pt.status = "cooling"
        else:
            streak = 0
        pt.evidence_post_ids = json.dumps(sorted(ev | set(best["evidence_post_ids"])))
        if best.get("suggestion"):
            pt.suggestion = best["suggestion"]
        if best.get("origin") == "comment_theme":  # LLM 命名优先于模板标题
            pt.title = best["title"]
        m = {**best.get("metrics", {}), "volume": vol_new, "cool_streak": streak}
        pt.metrics = json.dumps(m, ensure_ascii=False)
        pt.detail = json.dumps(best.get("detail", {}), ensure_ascii=False)
        pt.last_seen = today
        stats["updated"] += 1

    for c in candidates:
        if id(c) in used:
            continue
        session.add(InsightPoint(
            vehicle_id=vehicle_id, type=c["type"], title=c["title"],
            origin=c.get("origin", "dim"), status="new",
            metrics=json.dumps({**c.get("metrics", {}), "volume": c["volume"],
                                "cool_streak": 0}, ensure_ascii=False),
            evidence_post_ids=json.dumps(c["evidence_post_ids"]),
            suggestion=c.get("suggestion", ""),
            detail=json.dumps(c.get("detail", {}), ensure_ascii=False),
            first_seen=today, last_seen=today,
        ))
        stats["created"] += 1
    await session.commit()
    return stats


async def mine_points_for_vehicle(session: AsyncSession, vehicle_id: str,
                                  use_llm: bool = True) -> dict:
    """点挖掘主管线：素材 → 兜底 + LLM → 匹配合并 → 状态机。"""
    materials = await _collect_materials(session, vehicle_id)
    candidates = _rule_points(materials)
    llm_error = None
    if use_llm:
        llm_pts, llm_error = await _llm_points(materials)
        candidates += llm_pts
    for c in candidates:
        c["volume"] = _volume_of(c, materials)
    stats = await _merge_points(session, vehicle_id, candidates, date.today())
    if llm_error:
        logger.warning("point_miner LLM 降级(%s): %s", vehicle_id, llm_error)
    return {**stats, "llm_error": llm_error}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `$PY -m pytest tests/test_points.py -v`
Expected: 10 PASS

- [ ] **Step 5: Commit**

```bash
git add pipeline/analysis/point_miner.py tests/test_points.py
git commit -m "feat(points): Jaccard 证据锚定匹配 + 生命周期状态机 + 挖掘主管线"
```

---

### Task 5: 管线挂载 Phase 9 + regen_points 脚本

**Files:**
- Modify: `api/routes/collection.py`（`_run_full_pipeline` Phase 8 之后）
- Create: `scripts/regen_points.py`

- [ ] **Step 1: 挂载管线**

在 `api/routes/collection.py` 的 `_run_full_pipeline` 中，Phase 8（`fetch_top_comments`）的 try/except 块之后、`pipeline_phases[vehicle_id] = {"phase": "completed", ...}` 之前插入：

```python
            # Phase 9: Insight point mining（双模式点报；失败不断管线）
            try:
                from pipeline.analysis.point_miner import mine_points_for_vehicle
                pstats = await mine_points_for_vehicle(vehicle_id, session)
                pipeline_phases[vehicle_id]["points_created"] = pstats.get("created", 0)
            except Exception as e:
                logger.warning("Point mining failed: %s", e)
```

- [ ] **Step 2: 写 regen 脚本**

创建 `scripts/regen_points.py`：

```python
"""手动重跑舆情点挖掘（reanalyze.py 模式）。

用法:
    python scripts/regen_points.py --vehicle 星愿          # 名称子串匹配
    python scripts/regen_points.py --vehicle 星愿 --no-llm # 只出规则兜底点
"""
import argparse
import asyncio
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.database import async_session, init_db          # noqa: E402
from models.schemas import Vehicle                          # noqa: E402
from sqlalchemy import select                                # noqa: E402


async def main() -> int:
    ap = argparse.ArgumentParser(description="手动重跑舆情点挖掘")
    ap.add_argument("--vehicle", required=True, help="车型名称子串")
    ap.add_argument("--no-llm", action="store_true", help="跳过 LLM，只出规则兜底点")
    args = ap.parse_args()

    await init_db()
    async with async_session() as session:
        vs = (await session.execute(
            select(Vehicle).where(Vehicle.name.contains(args.vehicle),
                                  Vehicle.status == "active")
        )).scalars().all()
        if not vs:
            print(f"[WARN] 无匹配车辆: {args.vehicle!r}")
            return 1
        from pipeline.analysis.point_miner import mine_points_for_vehicle
        for v in vs:
            stats = await mine_points_for_vehicle(session, v.id, use_llm=not args.no_llm)
            print(f"[{v.name}] 新增 {stats['created']} / 更新 {stats['updated']} / "
                  f"归档 {stats['archived']}"
                  + (f" / LLM降级: {stats['llm_error']}" if stats.get("llm_error") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 3: 验证**

Run: `$PY -m pytest tests/test_points.py tests/test_collection*.py -q 2>/dev/null || $PY -m pytest tests/test_points.py -q`
Expected: PASS（管线改动为纯追加 try/except 块）

Run: `$PY scripts/regen_points.py --vehicle 不存在的车`
Expected: `[WARN] 无匹配车辆: '不存在的车'`，退出码 1

- [ ] **Step 4: Commit**

```bash
git add api/routes/collection.py scripts/regen_points.py
git commit -m "feat(points): 管线 Phase 9 挂载 + regen_points 手动重跑脚本"
```

---

### Task 6: points 端点 + 口径横扫

**Files:**
- Modify: `api/routes/dashboard.py`（文件末尾附近，negative-radar 端点之后）
- Modify: `tests/test_caliber.py`（补横扫行）
- Test: `tests/test_points.py`（追加）

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_points.py`：

```python
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_points_endpoint_excludes_archived_and_filters(db_session, vehicle, monkeypatch):
    """端点默认排 archived；type 过滤生效。"""
    import api.main
    from models.database import get_session

    async def _override():
        yield db_session
    monkeypatch.setattr(api.main.app.dependency_overrides, "__setitem__", lambda *a: None)
    app = api.main.app
    app.dependency_overrides[get_session] = _override
    try:
        await _add_point(db_session, vehicle.id, ["z1"], status="new")
        await _add_point(db_session, vehicle.id, ["z2"], status="archived")
        await _add_point(db_session, vehicle.id, ["z3"], status="new")
        p4 = await _add_point(db_session, vehicle.id, ["z4"], status="new")
        p4.type = "amplify"
        await db_session.commit()

        client = TestClient(app)
        r = client.get(f"/api/dashboard/points/{vehicle.id}")
        assert r.status_code == 200
        body = r.json()
        assert all(p["status"] != "archived" for p in body)
        assert len(body) == 3
        r2 = client.get(f"/api/dashboard/points/{vehicle.id}?type=amplify")
        assert len(r2.json()) == 1 and r2.json()[0]["type"] == "amplify"
        # evidence 字段存在（列表形态）
        assert "evidence" in body[0]
    finally:
        app.dependency_overrides.pop(get_session, None)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$PY -m pytest tests/test_points.py::test_points_endpoint_excludes_archived_and_filters -v`
Expected: FAIL — 404（端点不存在）

- [ ] **Step 3: 写实现**

`api/routes/dashboard.py` 顶部 import 块的 `from models.schemas import (` 中加入 `InsightPoint`（按字母序插入）。文件追加端点：

```python
@router.get("/points/{vehicle_id}")
async def get_insight_points(
    vehicle_id: str,
    type: str | None = Query(None),
    status: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    """传播点报：可行动舆情点列表（openspec: points-report-frontend）。

    默认排除 archived；type=amplify|defend、status=new|active|cooling 可选过滤。
    evidence 为证据帖摘要（RELEVANT_ONLY 口径），一次 join 返回免前端 N+1。
    """
    await _get_vehicle_or_404(vehicle_id, session)
    q = select(InsightPoint).where(
        InsightPoint.vehicle_id == vehicle_id,
        InsightPoint.status != "archived",
    )
    if type in ("amplify", "defend"):
        q = q.where(InsightPoint.type == type)
    if status in ("new", "active", "cooling"):
        q = q.where(InsightPoint.status == status)
    q = q.order_by(InsightPoint.last_seen.desc(), InsightPoint.created_at.desc())
    pts = (await session.execute(q)).scalars().all()

    ids = {pid for p in pts for pid in json.loads(p.evidence_post_ids or "[]")}
    posts_map = {}
    if ids:
        rows = await session.execute(
            select(RawPost).where(RawPost.id.in_(ids), RELEVANT_ONLY)
        )
        for rp in rows.scalars():
            posts_map[rp.id] = {
                "id": rp.id, "title": rp.title or (rp.content or "")[:40],
                "platform": rp.platform, "likes": rp.likes or 0, "comments": rp.comments or 0,
            }
    out = []
    for p in pts:
        ev_ids = json.loads(p.evidence_post_ids or "[]")
        out.append({
            "id": p.id, "type": p.type, "title": p.title, "origin": p.origin,
            "status": p.status, "metrics": json.loads(p.metrics or "{}"),
            "suggestion": p.suggestion or "",
            "detail": json.loads(p.detail or "{}"),
            "first_seen": str(p.first_seen), "last_seen": str(p.last_seen),
            "evidence": [posts_map[i] for i in ev_ids if i in posts_map],
        })
    return out
```

- [ ] **Step 4: 补口径横扫行**

`tests/test_caliber.py`：找到现有横扫测试（种 14639 赞无关帖的那个），在其出口列表中追加一行对 `/api/dashboard/points/{vid}` 的断言（照抄同文件其他端点的写法，断言 irrelevant 帖 id 不出现在任何点的 evidence 中）。

- [ ] **Step 5: 跑测试确认通过**

Run: `$PY -m pytest tests/test_points.py tests/test_caliber.py -v`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add api/routes/dashboard.py tests/test_points.py tests/test_caliber.py
git commit -m "feat(points): GET /points 端点（排 archived/type 过滤/evidence 摘要 join）+ 口径横扫补行"
```

---

### Task 7: comment-sentiment-diff 增强（口碑反转卡数据）

**Files:**
- Modify: `api/routes/dashboard.py:597-647`（`get_comment_sentiment_diff`）
- Test: `tests/test_points.py`（追加）

- [ ] **Step 1: 写失败测试**

追加：

```python
@pytest.mark.asyncio
async def test_diff_endpoint_enhanced_fields(db_session, vehicle, monkeypatch):
    import api.main
    from models.database import get_session

    async def _override():
        yield db_session
    app = api.main.app
    app.dependency_overrides[get_session] = _override
    try:
        raw, ap = _mk_post(vehicle.id, sentiment="positive", comments=34)
        ap.comment_summary = json.dumps({
            "genuine_sentiment": "negative",
            "genuine_themes": ["续航虚标"],
            "summary": "评论区吐槽续航", "is_argumentative": True,
        })
        c1 = PostComment(post_id=raw.id, vehicle_id=vehicle.id, content="续航打七折",
                         author="车主A", likes=56, platform="weibo")
        c2 = PostComment(post_id=raw.id, vehicle_id=vehicle.id, content="一般般",
                         author="车主B", likes=2, platform="weibo")
        db_session.add_all([raw, ap, c1, c2])
        await db_session.commit()

        client = TestClient(app)
        r = client.get(f"/api/dashboard/comment-sentiment-diff/{vehicle.id}")
        body = r.json()
        assert len(body) == 1
        d = body[0]
        assert d["direction"] == "pos2neg"
        assert d["comment_count"] == 34
        assert d["top_comment"]["content"] == "续航打七折"
        assert d["top_comment"]["likes"] == 56
    finally:
        app.dependency_overrides.pop(get_session, None)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$PY -m pytest tests/test_points.py::test_diff_endpoint_enhanced_fields -v`
Expected: FAIL — `KeyError: 'direction'`

- [ ] **Step 3: 写实现**

在 `get_comment_sentiment_diff` 的 `return diff_items` 之前插入（并保留原循环不动）：

```python
    # 口碑反转卡增强（2026-09-20 openspec monitor-slimdown）：
    # direction + 评论总数 + 热门评论摘录（按 likes top1）
    all_ids = [d["post_id"] for d in diff_items]
    top_by_post: dict[str, dict] = {}
    if all_ids:
        crows = await session.execute(
            select(PostComment).where(PostComment.post_id.in_(all_ids))
            .order_by(PostComment.likes.desc())
        )
        for c in crows.scalars():
            top_by_post.setdefault(c.post_id, {
                "content": (c.content or "")[:120], "likes": c.likes or 0, "author": c.author,
            })
    for d in diff_items:
        d["direction"] = ("pos2neg" if d["post_sentiment"] == "positive"
                          else "neg2pos" if d["post_sentiment"] == "negative" else "other")
        d["comment_count"] = 0
        if (p := posts_map.get(d["post_id"])) is not None:
            d["comment_count"] = p.comments or 0
        d["top_comment"] = top_by_post.get(d["post_id"])
```

同时把 `api/routes/dashboard.py` 顶部 schemas import 中补 `PostComment`（若尚未导入）。

- [ ] **Step 4: 跑测试确认通过**

Run: `$PY -m pytest tests/test_points.py -v`
Expected: 全 PASS（含既有 test_negative_radar / dashboard 相关回归：`$PY -m pytest tests/ -q` 全绿后进下一步）

- [ ] **Step 5: Commit**

```bash
git add api/routes/dashboard.py tests/test_points.py
git commit -m "feat(monitor): comment-sentiment-diff 增强——direction/comment_count/top_comment"
```

---

### Task 8: dialog 锚点 point 分支

**Files:**
- Modify: `api/routes/dialog.py:154`（`elif anchor_type == "event":` 之前插入分支）
- Test: `tests/test_points.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_dialog_point_context(db_session, vehicle, monkeypatch):
    from api.routes.dialog import _build_context

    p = await _add_point(db_session, vehicle.id, ["e1"], status="active")
    p.title = "换电体验差持续发酵"
    p.type = "defend"
    p.suggestion = "准备回应口径"
    p.detail = json.dumps({"rep_comments": [{"content": "排队一小时", "likes": 45, "author": "u"}]},
                          ensure_ascii=False)
    await db_session.commit()
    ctx = await _build_context(vehicle.id, "point", {"point_id": p.id}, db_session)
    assert "换电体验差持续发酵" in ctx
    assert "排队一小时" in ctx
```

- [ ] **Step 2: 跑测试确认失败**

Run: `$PY -m pytest tests/test_points.py::test_dialog_point_context -v`
Expected: FAIL（point 分支不存在，上下文为空/缺关键词）

- [ ] **Step 3: 写实现**

`api/routes/dialog.py` 的 `_build_context` 中，`elif anchor_type == "event":` 之前插入：

```python
    elif anchor_type == "point":
        point_id = anchor_data.get("point_id", "")
        context_parts.append("用户在传播点报中就某个舆情点点击了「问 AI」")
        pt = (await session.execute(
            select(InsightPoint).where(InsightPoint.id == point_id)
        )).scalar_one_or_none()
        if pt:
            type_cn = "宣传机会" if pt.type == "amplify" else "防守风险"
            context_parts.append(
                f"舆情点「{pt.title}」 类型={type_cn} 来源={pt.origin} 状态={pt.status}")
            m = json.loads(pt.metrics or "{}")
            if m:
                context_parts.append(f"指标: {json.dumps(m, ensure_ascii=False)}")
            if pt.suggestion:
                context_parts.append(f"已有建议: {pt.suggestion}")
            ev_ids = json.loads(pt.evidence_post_ids or "[]")
            if ev_ids:
                rows = await session.execute(
                    select(RawPost).where(RawPost.id.in_(ev_ids), RELEVANT_ONLY)
                )
                evs = [f"「{p.title or (p.content or '')[:30]}」({p.platform}, ▲{p.likes or 0})"
                       for p in rows.scalars()]
                if evs:
                    context_parts.append("证据帖: " + " | ".join(evs[:5]))
            detail = json.loads(pt.detail or "{}")
            for rc in (detail.get("rep_comments") or [])[:3]:
                context_parts.append(f"代表评论: 「{rc.get('content', '')}」▲{rc.get('likes', 0)}")
```

顶部 schemas import 补 `InsightPoint`、`RELEVANT_ONLY`（按现有 import 列表字母序）。

- [ ] **Step 4: 跑测试确认通过**

Run: `$PY -m pytest tests/test_points.py -v` → PASS；`$PY -m pytest tests/test_dialog*.py -q` → 既有对话测试不回归

- [ ] **Step 5: Commit**

```bash
git add api/routes/dialog.py tests/test_points.py
git commit -m "feat(dialog): 锚点对话 point 分支——点详情+证据帖+代表评论注入上下文"
```

---

### Task 9: 前端骨架——viewMode 双模式 + 删事件标签分布图

**Files:**
- Modify: `frontend/index.html`（chrome 区 + 全部监控 section 的 v-if + script 标签）
- Modify: `frontend/static/js/app.js`（data/methods/computed + 删 eventTagsDist）
- Create: `frontend/static/js/points.js`（占位骨架，Task 10 填充）
- Modify: `frontend/static/css/style.css`（view-switch 样式）

- [ ] **Step 1: index.html chrome 加模式切换**

在 `<div class="time-presets">` 之前插入：

```html
        <div class="view-switch">
            <button :class="['view-pill', viewMode==='monitor' ? 'pill-active' : '']"
                    @click="switchView('monitor')">监控看板</button>
            <button :class="['view-pill', viewMode==='points' ? 'pill-active' : '']"
                    @click="switchView('points')">传播点报</button>
        </div>
```

- [ ] **Step 2: 监控 section 全部改 v-if**

把以下 section 的 `v-if="currentVehicleId"` 改为 `v-if="currentVehicleId && viewMode==='monitor'"`：
分组对比两个 section（`v-if="groups.length"` → `v-if="groups.length && viewMode==='monitor'"`；`v-if="currentGroupId"` 同理加）、01~06 六个 section、方法论 section、全部帖子 section、历史报告 section（后两个原本是 `v-if="currentVehicleId && showAllPosts"` → `v-if="currentVehicleId && showAllPosts && viewMode==='monitor'"`）。

**删除**：05 区的「事件标签分布」整块（`<div class="card" v-if="eventTagsDist.length" ...>` 到对应 `</div>`，含 `#event-tags-chart`）。

- [ ] **Step 3: script 标签 + 缓存版本**

`</body>` 前改为：

```html
<script src="/static/js/dialog.js?v=9"></script>
<script src="/static/js/points.js?v=1"></script>
<script src="/static/js/app.js?v=22"></script>
```

head 里 `style.css?v=14` → `?v=15`。

- [ ] **Step 4: app.js 改动**

data() 返回对象加：`viewMode: "monitor", points: [], pointsFilter: "all",`

methods 加（放在 `selectVehicle` 附近）：

```javascript
        switchView(mode) {
            if (this.viewMode === mode) return;
            this.viewMode = mode;
            if (mode === "points") PointsUI.load(this);
        },
        async loadPoints() {
            this.points = await this.apiFetch(`/api/dashboard/points/${this.currentVehicleId}`) || [];
        },
        switchPointsFilter(f) {
            this.pointsFilter = f;
        },
```

**删除**：`onVehicleChange` 的 Promise.all 里的 `this.loadEventTagsDist(),` 一行；`loadEventTagsDist` 方法整体（`app.js:659-661` 附近）；`renderEventTagsChart` 方法整体（`app.js:663` 起）；data 里 `eventTagsDist: [],` 一行。

`onVehicleChange` 末尾（renderAllCharts 之后）加：

```javascript
            if (this.viewMode === "points") PointsUI.load(this);
```

- [ ] **Step 5: points.js 占位 + style.css**

创建 `frontend/static/js/points.js`：

```javascript
// 传播点报视图逻辑（dialog.js 同模式：全局对象，app.js 委托调用）
// Task 10 填充完整实现
const PointsUI = {
    async load(vm) {
        vm.points = await vm.apiFetch(`/api/dashboard/points/${vm.currentVehicleId}`) || [];
    },
};
```

`style.css` 末尾追加：

```css
/* --- view switch（双模式） --- */
.view-switch { display: flex; gap: 2px; background: #f0f1f4; border-radius: 8px; padding: 3px; }
.view-pill { border: 0; background: transparent; padding: 6px 14px; border-radius: 6px;
  font-size: 13px; color: #666; cursor: pointer; }
.view-pill.pill-active { background: #1a1d24; color: #fff; font-weight: 600; }
```

- [ ] **Step 6: 手动验证 + Commit**

重启服务（taskkill uvicorn 进程，supervisor 3s 自动拉起新代码；或直接跑 `start.py` 所在进程重启），浏览器打开 http://127.0.0.1:8000 → 选星愿 → 点「传播点报」→ 页面只剩 header（点报区 Task 10 才有）→ 点回「监控看板」→ 六区完整且 05 区无事件标签分布图。console 无报错。

```bash
git add frontend/index.html frontend/static/js/app.js frontend/static/js/points.js frontend/static/css/style.css
git commit -m "feat(frontend): viewMode 双模式骨架 + 删事件标签分布图（cache-bust v22/v15）"
```

---

### Task 10: 前端点报页（页头摘要 + 筛选 + 点卡片 + 问 AI）

**Files:**
- Modify: `frontend/index.html`（监控 sections 之后插入点报 section）
- Modify: `frontend/static/js/points.js`（完整实现）
- Modify: `frontend/static/js/app.js`（computed）
- Modify: `frontend/static/css/style.css`（点卡样式）

- [ ] **Step 1: index.html 点报 section**

在「方法论」section 之后（`</div><!-- .wrap -->` 之前）插入：

```html
    <!-- 传播点报（viewMode=points） -->
    <section v-if="currentVehicleId && viewMode==='points'" class="sec">
        <h2 class="sec-title">传播点报<span class="sec-sub">{{ pointsSummaryText }}</span></h2>
        <div class="points-filter">
            <button v-for="f in pointsFilterOptions" :key="f.key" class="points-chip"
                    :class="{active: pointsFilter === f.key, [f.cls]: true}"
                    @click="switchPointsFilter(f.key)">{{ f.label }}</button>
        </div>
        <div class="points-list">
            <div v-for="p in filteredPoints" :key="p.id" class="point-card" :class="'point-' + p.type">
                <div class="point-head">
                    <span class="point-type" :class="'pt-' + p.type">{{ p.type === 'amplify' ? '🟢 宣传' : '🔴 防守' }}</span>
                    <span class="point-status" :class="'ps-' + p.status">{{ statusLabel(p.status) }}</span>
                    <span class="point-origin">{{ originLabel(p.origin) }} · 在榜 {{ daysOnBoard(p) }} 天</span>
                </div>
                <div class="point-title">{{ p.title }}</div>
                <div class="point-metrics" v-if="p.metrics">
                    <span>涉及 <b>{{ p.evidence.length }}</b> 帖</span>
                    <span>评论 <b>{{ p.metrics.volume - p.evidence.length || 0 }}</b></span>
                    <span v-if="p.metrics.dim_neg_rate">负面率 <b class="neg-num">{{ (p.metrics.dim_neg_rate * 100).toFixed(0) }}%</b></span>
                    <span v-if="p.metrics.dim_avg">正向分 <b>{{ p.metrics.dim_avg }}</b></span>
                </div>
                <div class="point-evidence" v-if="p.evidence.length">
                    <div v-for="rc in (p.detail.rep_comments || [])" :key="rc.content" class="point-repcomment">
                        💬 「{{ rc.content }}」▲{{ rc.likes }}
                    </div>
                    <div class="point-ev-posts">
                        <span v-for="e in p.evidence.slice(0, 3)" :key="e.id" class="point-ev-post"
                              @click="openPostDetail(e)">「{{ e.title }}」{{ platformLabel(e.platform) }} ▲{{ e.likes }}</span>
                    </div>
                </div>
                <div class="point-suggestion" v-if="p.suggestion">→ <b>建议</b>：{{ p.suggestion }}</div>
                <div class="point-ask" @click="askPointAI(p)">💬 问 AI 深挖这个点 →</div>
            </div>
            <div v-if="!filteredPoints.length" class="empty">暂无舆情点</div>
        </div>
    </section>
```

- [ ] **Step 2: points.js 完整实现**

替换 `frontend/static/js/points.js` 全文：

```javascript
// 传播点报视图逻辑（dialog.js 同模式：全局对象，app.js 委托调用）
const PointsUI = {
    async load(vm) {
        vm.points = await vm.apiFetch(`/api/dashboard/points/${vm.currentVehicleId}`) || [];
    },
    filtered(vm) {
        return vm.pointsFilter === "all"
            ? vm.points
            : vm.points.filter(p => p.type === vm.pointsFilter);
    },
    summary(vm) {
        const n = vm.points.length;
        const a = vm.points.filter(p => p.type === "amplify").length;
        const s = { new: 0, active: 0, cooling: 0 };
        vm.points.forEach(p => { if (s[p.status] !== undefined) s[p.status]++; });
        return `今日 ${n} 个点：${a} 宣传 · ${n - a} 防守 ｜ 🆕${s.new} · 🔥${s.active} · ❄️${s.cooling}`;
    },
};

const POINTS_STATUS_CN = { new: "🆕 新增", active: "🔥 发酵中", cooling: "❄️ 降温中" };
const POINTS_ORIGIN_CN = {
    comment_theme: "评论区主题", viral_post: "爆帖", dim: "维度口碑", event: "事件", surge: "突增",
};
```

- [ ] **Step 3: app.js computed/methods 接线**

computed 块加：

```javascript
        filteredPoints() { return PointsUI.filtered(this); },
        pointsSummaryText() { return PointsUI.summary(this); },
        pointsFilterOptions() {
            const a = this.points.filter(p => p.type === "amplify").length;
            return [
                { key: "all", label: `全部 ${this.points.length}`, cls: "" },
                { key: "amplify", label: `🟢 宣传 ${a}`, cls: "chip-amplify" },
                { key: "defend", label: `🔴 防守 ${this.points.length - a}`, cls: "chip-defend" },
            ];
        },
```

methods 加：

```javascript
        statusLabel(s) { return POINTS_STATUS_CN[s] || s; },
        originLabel(o) { return POINTS_ORIGIN_CN[o] || o; },
        daysOnBoard(p) {
            const d = (new Date(p.last_seen) - new Date(p.first_seen)) / 86400000;
            return Math.max(1, Math.round(d));
        },
        askPointAI(p) { openDialog("point", { point_id: p.id }); },
```

（`openPostDetail` 已存在——evidence 对象缺 content 时它内部已有兜底，勿改。）

- [ ] **Step 4: style.css 点卡样式**

追加：

```css
/* --- 传播点报 --- */
.sec-sub { font-size: 13px; font-weight: 400; color: var(--muted); margin-left: 12px; }
.points-filter { display: flex; gap: 8px; margin-bottom: 14px; }
.points-chip { border: 1px solid #e0e0e8; background: #fff; border-radius: 14px;
  padding: 4px 14px; font-size: 12px; cursor: pointer; color: #555; }
.points-chip.active { background: #1a1d24; color: #fff; border-color: #1a1d24; }
.points-chip.chip-amplify.active { background: #2e8b57; border-color: #2e8b57; }
.points-chip.chip-defend.active { background: #c0392b; border-color: #c0392b; }
.points-list { display: flex; flex-direction: column; gap: 12px; }
.point-card { background: #fff; border: 1px solid #e8e8ee; border-radius: 10px;
  padding: 14px 16px; border-left: 3px solid #ccc; }
.point-card.point-amplify { border-left-color: #2e8b57; }
.point-card.point-defend { border-left-color: #c0392b; }
.point-head { display: flex; gap: 10px; align-items: center; font-size: 12px; }
.point-type { font-weight: 600; }
.point-status { color: #888; }
.point-origin { color: #999; font-size: 11px; margin-left: auto; }
.point-title { font-size: 15px; font-weight: 700; margin: 8px 0 6px; }
.point-metrics { display: flex; gap: 16px; font-size: 12px; color: #666; }
.point-metrics .neg-num { color: #c0392b; }
.point-evidence { margin-top: 8px; border-left: 2px solid #e0e0e8; padding-left: 10px; }
.point-repcomment { font-size: 12px; color: #555; margin-bottom: 4px; }
.point-ev-posts { display: flex; flex-wrap: wrap; gap: 8px; }
.point-ev-post { font-size: 12px; color: #1a5fb4; cursor: pointer; }
.point-ev-post:hover { text-decoration: underline; }
.point-suggestion { margin-top: 8px; font-size: 12px; color: #333; }
.point-ask { margin-top: 8px; font-size: 12px; color: #2e8b57; cursor: pointer; }
.point-ask:hover { text-decoration: underline; }
```

- [ ] **Step 5: 手动验证 + Commit**

重启服务 → 点报模式：`$PY scripts/regen_points.py --vehicle 星愿 --no-llm` 先造几条规则点 → 刷新页面 → 点报显示卡片（摘要行/筛选/卡片/证据/建议）→ 点证据帖开 Modal → 点「问 AI」右侧滑出对话。console 无错。

```bash
git add frontend/index.html frontend/static/js/app.js frontend/static/js/points.js frontend/static/css/style.css
git commit -m "feat(frontend): 传播点报页——页头摘要/筛选/点卡片/证据下钻/问 AI"
```

---

### Task 11: 前端口碑反转卡

**Files:**
- Modify: `frontend/index.html`（03 区「争议帖预警」块整块替换）
- Modify: `frontend/static/css/style.css`（反转卡样式）
- Modify: `frontend/static/js/app.js`（direction 排序 computed）

- [ ] **Step 1: 替换争议帖区块**

把 03 区 `<div class="card controversial-area" ...>` 整块替换为：

```html
        <div class="card controversial-area" v-if="reversalPosts.length">
            <div class="card-title">口碑反转<span class="card-sub">帖子看着正面但评论区在吐槽（翻车），或反过来（车主护车）</span></div>
            <div class="reversal-list">
                <div v-for="p in reversalPosts" :key="p.post_id" class="reversal-item" :class="'rv-' + p.direction"
                     @click="openPostDetail({ id: p.post_id, title: p.title })">
                    <div class="reversal-head">
                        <span class="reversal-badge" :class="'rb-' + p.direction">
                            {{ p.direction === 'pos2neg' ? '🔴 好评翻车' : p.direction === 'neg2pos' ? '🟢 差评反转' : '⚪ 情感错位' }}
                        </span>
                        <span class="reversal-title">{{ stripHtml(p.title) }}</span>
                        <span class="reversal-meta">{{ p.comment_count }} 评论</span>
                    </div>
                    <div class="reversal-body">
                        <span v-for="t in (p.genuine_themes || []).slice(0, 3)" :key="t"
                              class="tag-chip" :class="p.direction === 'pos2neg' ? 'tag-pain' : 'tag-good'">#{{ t }}</span>
                    </div>
                    <div v-if="p.top_comment" class="reversal-quote">💬 「{{ p.top_comment.content }}」▲{{ p.top_comment.likes }}</div>
                    <div class="reversal-action">
                        {{ p.direction === 'pos2neg' ? '→ 慎转此帖；真实痛点需关注' :
                           p.direction === 'neg2pos' ? '→ 车主自发护车 = 可放大素材' : '→ 结合评论区判断真实口碑' }}
                    </div>
                </div>
            </div>
        </div>
```

- [ ] **Step 2: app.js**

data 的 `controversialPosts` 改名逻辑不动（loader 沿用），computed 加：

```javascript
        reversalPosts() {
            const order = { pos2neg: 0, neg2pos: 1, other: 2 };
            return [...this.controversialPosts]
                .sort((a, b) => (order[a.direction] ?? 3) - (order[b.direction] ?? 3)
                    || (b.comment_count || 0) - (a.comment_count || 0));
        },
```

- [ ] **Step 3: style.css**

追加：

```css
/* --- 口碑反转卡 --- */
.reversal-list { display: flex; flex-direction: column; gap: 10px; }
.reversal-item { border: 1px solid #e8e8ee; border-radius: 8px; padding: 10px 12px;
  cursor: pointer; border-left: 3px solid #ccc; }
.reversal-item.rv-pos2neg { border-left-color: #c0392b; }
.reversal-item.rv-neg2pos { border-left-color: #2e8b57; }
.reversal-head { display: flex; gap: 10px; align-items: center; }
.reversal-badge { font-size: 12px; font-weight: 600; white-space: nowrap; }
.reversal-title { font-size: 13px; font-weight: 600; flex: 1;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.reversal-meta { font-size: 11px; color: #999; white-space: nowrap; }
.reversal-body { margin-top: 6px; display: flex; gap: 6px; flex-wrap: wrap; }
.tag-chip.tag-pain { background: #fdecea; color: #c0392b; }
.tag-chip.tag-good { background: #e8f5e9; color: #2e7d32; }
.reversal-quote { margin-top: 6px; background: #f8f9fa; border-radius: 6px;
  padding: 6px 10px; font-size: 12px; color: #666; }
.reversal-action { margin-top: 6px; font-size: 12px; color: #333; }
```

- [ ] **Step 4: 手动验证 + Commit**

重启 → 星愿 → 03 区：若库里有反转帖（`SELECT count(*) FROM analyzed_posts WHERE comment_summary IS NOT NULL` 且 diff 非空）则显示新卡片且 pos2neg 在前；无则确认该卡不渲染、无 console 错。

```bash
git add frontend/index.html frontend/static/js/app.js frontend/static/css/style.css
git commit -m "feat(frontend): 争议帖预警重做为口碑反转卡——方向分型/热门评论/动作行"
```

---

### Task 12: 全量验证 + 实弹 + 视觉核实 + 文档同步

**Files:**
- Modify: `docs/舆情看板-前端设计.md`（骨架/数据流/缓存版本/双模式说明）

- [ ] **Step 1: 全量测试**

Run: `$PY -m pytest -q`
Expected: 全 PASS（646 + 新增 ~14 = ~660）

- [ ] **Step 2: 实弹点挖掘**

```bash
$PY scripts/regen_points.py --vehicle 星愿
```
Expected: `[星愿] 新增 N / 更新 0 / 归档 0`，N ≥ 1；`curl http://127.0.0.1:8000/api/dashboard/points/819a7d92-7c58-4a89-81b6-d42403db841b` 返回点列表，人工核对：应出现「售后/价格」类防守点与「空间」类宣传点（对照库内数据）。

- [ ] **Step 3: Edge headless 双模式截图核实**

复用会话内已验证的 Playwright UI 路径方法学（搜索框输「星愿」→ 点下拉项 → 等 `.chrome-time` → 截整页）；另截 viewMode=points 一张。人工看图：点报卡片渲染完整、监控六区无事件标签分布图、口碑反转卡方向正确。注意 Read 工具对相同图片 CDN 去重——不同文件名即可。

- [ ] **Step 4: 更新前端设计文档**

`docs/舆情看板-前端设计.md`：§3 骨架加 viewMode 切换与点报 section；§8 数据流加 PointsUI.load；缓存版本号改 v22/v15/v1；§4 增「传播点报」小节（卡片结构/口径=RELEVANT_ONLY+SELF_ONLY+AUTHENTIC）；「已知取舍」补：点报无时间窗（生命周期即时间语义）。

- [ ] **Step 5: Commit**

```bash
git add docs/舆情看板-前端设计.md
git commit -m "docs: 前端设计文档同步双模式/点报/口碑反转卡"
```

---

## Self-Review 记录

- **Spec 覆盖**：insight-point-mining 8 条 requirement → Task 2/3/4/5/6；points-report-frontend 6 条 → Task 6/9/10；monitor-slimdown 3 条 → Task 7/9/11。tasks.md T1.1-T5.5 全映射。
- **占位符**：无 TBD/TODO；Task 2 中 `_neg_count` 草稿已明确标注"采用最终简洁版"避免实施者困惑。
- **类型一致性**：候选点 dict 字段（type/origin/title/evidence_post_ids/suggestion/metrics/detail/volume）在 Task 2/3/4 三处签名一致；端点返回 `evidence` 数组与 Task 10 模板 `p.evidence.length`/`p.metrics.volume` 一致；`detail.rep_comments` Task 3 写入、Task 10 读取一致。
- **已知风险标注**：① 管线挂载在 `_run_full_pipeline`（服务内）而非 daily_update.py——daily_update 经 /collect 触发同一管线，语义等价且手动采集也覆盖（对 design §3 的实现精化）② Task 9/10/11 前端验证依赖服务重启，supervisor 自动拉起约 3s。
