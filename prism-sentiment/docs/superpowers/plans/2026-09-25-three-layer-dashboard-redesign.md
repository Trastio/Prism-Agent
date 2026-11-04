# 舆情看板三分法重设计 + 手动关注清单 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现役"监控看板 + 传播点报双视图"重设计为"三分法看板（热度层/风险层/发酵层）+ 顶部手动关注清单"，删除传播点报自动挖掘与状态机，缺陷话题监控归位发酵层。

**Architecture:**
- **后端**：删除 `InsightPoint` 表、`mine_points_for_vehicle`、`/points` 端点；新增 `WatchItem` 表 + CRUD 端点（纯手动标记，无状态机）；缺陷话题监控按既有 OpenSpec `defect-theme-monitoring` 落地，产 `defect_theme` 点汇入新端点 `/defect-themes/{vehicle_id}`。
- **前端**：`viewMode` 从 `monitor|points` 二选一改为单一 `monitor`（删 points 视图与切换 pill）；6 个区重组为三分法三层；chrome 顶部新增"我的关注"入口（modal/drawer）；每个可标记信号旁加"关注"按钮。
- **数据取向分层**：第一层热度（高互动快照）· 第二层风险（已发酵负面）· 第三层发酵（中低互动帖聚类，缺陷话题住此）。

**Tech Stack:** FastAPI + SQLAlchemy async + SQLite · Vue 3.4.38 (CDN) + ECharts · GLM-4-Flash LLM · pytest

**关键决策（用户已拍板）：**
1. 传播点报自动挖掘全删（`mine_points_for_vehicle` / `InsightPoint` / amplify-defend / 状态机）
2. 关注清单 = 纯手动标记，**无状态**（只存首次发现 + 涉及帖数 + 来源信号）
3. 关注清单入口 = chrome 顶部"我的关注"（modal，不占主视图）
4. 缺陷簇可标记关注
5. 三分法分层（热度/风险/发酵）

---

## 文件结构总览

### 删除
- `pipeline/analysis/point_miner.py` — 整文件删（自动点挖掘 + 状态机）
- `frontend/static/js/points.js` — 整文件删（PointsUI 视图逻辑）
- `api/routes/dashboard.py` 中 `get_insight_points`（`/points/{vehicle_id}`，约 935-991 行）— 删
- `api/routes/collection.py:80-86` Phase 9 调用块 — 删
- `models/schemas.py` 中 `InsightPoint` 类（235-256 行）— 删（保留表迁移见 Task 1）
- `frontend/index.html` 传播点报视图 section（409-460+ 行）+ view-switch pill（36-41 行 points pill）— 删
- `frontend/static/js/app.js` 中 points 相关 state/loader/computed（55-58, 299-306, 507, 1110-1130 等）— 删

### 新增
- `models/schemas.py` 新增 `WatchItem` 类
- `api/routes/watchlist.py` — 新路由文件，WatchItem CRUD
- `pipeline/analysis/defect_miner.py` — 缺陷话题挖掘（按 OpenSpec design.md 四步）
- `api/routes/dashboard.py` 新增 `/defect-themes/{vehicle_id}` 端点
- `frontend/static/js/watchlist.js` — 关注清单 UI 逻辑
- `frontend/static/js/defect.js` — 缺陷话题区渲染（第三层）

### 修改
- `api/routes/collection.py` — Phase 9 换成 defect mining
- `api/routes/dashboard.py` — `get_top_posts` 补 `AUTHENTIC_AUTHOR`（修第 1 问 bug）
- `api/main.py` — 注册 watchlist router
- `frontend/index.html` — 6 区重组为三层 + chrome 关注入口 + 各信号关注按钮
- `frontend/static/js/app.js` — 删 points、加 watchlist/defect loader
- `scripts/daily_update.py` — 调用从 mine_points 换成 defect mining

---

## Task 0: 采集层数据治理（先修脏数据，独立于重设计）

**Why first:** 第 4 问极狐T7 串味 + 第 1 问 `/top-posts` 漏 AUTHENTIC_AUTHOR 是脏数据源，必须先治，否则新看板还是假的。此任务可独立 commit。

**Files:**
- Modify: `api/routes/dashboard.py:383`（`get_top_posts` 的 query 补 AUTHENTIC_AUTHOR）
- Modify: 采集关键词逻辑（`pipeline/collectors/` 下风云T7 的 search_keywords）
- DB: 清理 5 条重复 vehicle 记录 + 1 条极狐 self 帖

- [ ] **Step 1: `get_top_posts` 补 AUTHENTIC_AUTHOR**

`api/routes/dashboard.py:382-385` 当前：
```python
    await _get_vehicle_or_404(vehicle_id, session)
    query = _relevant_posts_filter(
        select(RawPost).where(RawPost.vehicle_id == vehicle_id)
    )
```
改为（与 `/negative-radar` 口径对齐）：
```python
    await _get_vehicle_or_404(vehicle_id, session)
    query = _relevant_posts_filter(
        select(RawPost).where(RawPost.vehicle_id, RawPost.vehicle_id == vehicle_id)
    ).where(RawPost.id.in_(
        select(RawPost.id).select_from(RawPost)
        .outerjoin(AnalyzedPost, AnalyzedPost.post_id == RawPost.id)
    ))
```
注意：`get_top_posts` 是按 RawPost 查、sentiment 过滤走子查 AnalyzedPost.post_id。AUTHENTIC_AUTHOR 作用在 RawPost.author_type 上，可直接挂主 query：
```python
    query = _relevant_posts_filter(
        select(RawPost).where(RawPost.vehicle_id == vehicle_id, AUTHENTIC_AUTHOR)
    )
```
确认 `AUTHENTIC_AUTHOR` 已在 dashboard.py 顶部 import（第 11 行已 import）。

- [ ] **Step 2: 采集关键词精确化**

查 `pipeline/collectors/` 风云T7 的 search_keywords 配置。若为裸 `"T7"`，改为 `"风云T7"`（避免命中极狐阿尔法T7）。若 keywords 存 vehicles 表 search_keywords 字段，用 SQL 更新该车型记录。

- [ ] **Step 3: 清理重复 vehicle + 极狐 self 帖**

```bash
"C:/Users/<you>/anaconda3/python.exe" -c "
import sqlite3, glob, os
db=max(glob.glob('data/*.db'),key=os.path.getmtime)
c=sqlite3.connect(db)
# 备份
import shutil; shutil.copy(db, db+'.bak.preserve')
# 删 4 条空风云T7 重复记录（保留 306be9ad）
c.execute(\"DELETE FROM vehicles WHERE name LIKE '%风云T7%' AND id != '306be9ad-b6ab-4729-aeb0-262b91e1530d'\")
# 把漏标的极狐 self 帖改回 competitor
c.execute(\"UPDATE analyzed_posts SET subject='competitor' WHERE post_id='7501a2e2'\")  # 用实际 id
c.commit()
print('cleaned:', c.total_changes)
"
```
实际 post_id 在执行时从 DB 查（子代理报告里的 `7501a2e2…`）。

- [ ] **Step 4: 回归测试**

```bash
cd "C:/Users/<you>/Desktop/Agent项目/Vehicle Sentiment Analysis Board"
"C:/Users/<you>/anaconda3/python.exe" -m pytest tests/ -x -q
```
预期：全绿（426→672 现有测试不应被破坏）。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "fix(dashboard): get_top_posts 补 AUTHENTIC_AUTHOR + 风云T7 采集关键词精确化 + 清理重复vehicle/极狐串味帖"
```

---

## Task 1: 删除传播点报自动挖掘系统

**Files:**
- Delete: `pipeline/analysis/point_miner.py`
- Delete: `frontend/static/js/points.js`
- Modify: `models/schemas.py:235-256`（删 InsightPoint 类）
- Modify: `api/routes/dashboard.py:935-991`（删 get_insight_points）
- Modify: `api/routes/collection.py:80-86`（删 Phase 9）
- Modify: `frontend/index.html`（删 points 视图 section + points pill）
- Modify: `frontend/static/js/app.js`（删 points state/loader）
- Modify: `scripts/daily_update.py`（删 mine_points 调用）

- [ ] **Step 1: 删 point_miner.py 与 points.js**

```bash
cd "C:/Users/<you>/Desktop/Agent项目/Vehicle Sentiment Analysis Board"
git rm pipeline/analysis/point_miner.py
git rm frontend/static/js/points.js
```

- [ ] **Step 2: 删 InsightPoint 模型**

`models/schemas.py` 删除 235-256 行整个 `class InsightPoint(Base):` 块。
**保留表不迁移**——存量 insight_points 表数据无价值（自动算的），删表在 Task 1 Step 5 用脚本 drop。

- [ ] **Step 3: 删 /points 端点**

`api/routes/dashboard.py` 删除 935-991 行 `get_insight_points` 整个函数。

- [ ] **Step 4: 删 collection.py Phase 9**

`api/routes/collection.py:80-86` 当前：
```python
            # Phase 9: Insight point mining（双模式点报；失败不断管线）
            try:
                from pipeline.analysis.point_miner import mine_points_for_vehicle
                pstats = await mine_points_for_vehicle(vehicle_id, session)
                pipeline_phases[vehicle_id]["points_created"] = pstats.get("created", 0)
            except Exception as e:
                logger.warning("Point mining failed: %s", e)
```
整块删除。Phase 8（fetch_top_comments）后直接接 completed。

- [ ] **Step 5: drop insight_points 表**

```bash
"C:/Users/<you>/anaconda3/python.exe" -c "
import sqlite3, glob, os
db=max(glob.glob('data/*.db'),key=os.path.getmtime)
c=sqlite3.connect(db)
c.execute('DROP TABLE IF EXISTS insight_points')
c.commit(); print('dropped insight_points')
"
```

- [ ] **Step 6: 删前端 points 视图**

`frontend/index.html`：
- 删 36-41 行 view-switch 里 `viewMode==='points'` 的 pill（保留 monitor pill，或整组删，因为只剩一个视图无需切换——见 Task 4）
- 删 409-460+ 行 `<section v-if="currentVehicleId && viewMode==='points'">` 整块

`frontend/static/js/app.js`：
- 删 55-58 行 `points/pointsLoading/pointsFilter` state
- 删 299-306 行 `filteredPoints/pointsSummaryText/pointsFilterOptions` computed
- 删 507 行 `if (this.viewMode === "points") PointsUI.load(this);`
- 删 1110-1130 行 `switchView`/`switchPointsFilter` 相关
- 删 index.html 底部 `<script src="/static/js/points.js">` 引用

- [ ] **Step 7: 删 daily_update.py 调用**

`scripts/daily_update.py` 搜 `mine_points` 删除调用块。

- [ ] **Step 8: 回归测试**

```bash
"C:/Users/<you>/anaconda3/python.exe" -m pytest tests/ -x -q
```
预期：删 `tests/test_points.py`（若存在）或调整其引用。搜 `grep -rl "InsightPoint\|mine_points\|points" tests/` 逐个处理。

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor: 删除传播点报自动挖掘系统（InsightPoint/point_miner/points视图）— 为手动关注清单让路"
```

---

## Task 2: WatchItem 模型 + CRUD 端点

**Files:**
- Modify: `models/schemas.py`（新增 WatchItem 类）
- Create: `api/routes/watchlist.py`
- Modify: `api/main.py`（注册 router）

- [ ] **Step 1: WatchItem 模型**

`models/schemas.py` 在 Vehicle 类后新增：
```python
class WatchItem(Base):
    """手动关注清单条目（纯人工标记，无状态机）。

    用户在看板上对某条信号（热帖/吐槽/缺陷簇/事件）点"关注"后落库。
    只存线索元数据 + 来源信号锚点，不存状态（舆情不会"平息"）。
    """
    __tablename__ = "watch_items"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    vehicle_id = Column(String, nullable=False)
    title = Column(String, nullable=False)          # 信号标题（人工可编辑，默认取源标题）
    source_type = Column(String, nullable=False)    # hot_post | complaint | defect_cluster | event
    source_ref = Column(String)                     # 源锚点 id（post_id / cluster_id / event_id）
    post_count = Column(Integer, default=0)         # 涉及帖数（快照）
    first_seen = Column(Date, nullable=False)       # 首次发现日期
    note = Column(Text)                             # 用户备注（可选）
    created_at = Column(DateTime, server_default=func.now())
```

- [ ] **Step 2: 建表**

`models/database.py` 的 `init_db` 已用 `Base.metadata.create_all`，新表自动建。验证：
```bash
"C:/Users/<you>/anaconda3/python.exe" -c "
import asyncio
from models.database import init_db
asyncio.run(init_db())
print('init_db ok')
"
```

- [ ] **Step 3: 写 watchlist 路由测试**

Create `tests/test_watchlist.py`：
```python
import pytest
from httpx import AsyncClient, ASGITransport
from api.main import app

@pytest.mark.asyncio
async def test_watchitem_crud():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 先确保有车型（用现有 fixture 或建一个）
        vid = "306be9ad-b6ab-4729-aeb0-262b91e1530d"  # 风云T7
        # create
        r = await ac.post(f"/api/watchlist/{vid}", json={
            "title": "仪表盘车道线消失",
            "source_type": "defect_cluster",
            "source_ref": "cluster_xxx",
            "post_count": 12,
            "first_seen": "2026-09-20",
        })
        assert r.status_code == 200
        item_id = r.json()["id"]
        # list
        r = await ac.get(f"/api/watchlist/{vid}")
        assert r.status_code == 200
        assert any(i["id"] == item_id for i in r.json())
        # delete
        r = await ac.delete(f"/api/watchlist/{vid}/{item_id}")
        assert r.status_code == 200
```

- [ ] **Step 4: 运行测试确认失败**

```bash
"C:/Users/<you>/anaconda3/python.exe" -m pytest tests/test_watchlist.py -v
```
预期：FAIL（路由不存在）。

- [ ] **Step 5: 实现 watchlist 路由**

Create `api/routes/watchlist.py`：
```python
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from models.database import get_session
from models.schemas import WatchItem
from api.routes.dashboard import _get_vehicle_or_404

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class WatchItemCreate(BaseModel):
    title: str
    source_type: str          # hot_post | complaint | defect_cluster | event
    source_ref: str | None = None
    post_count: int = 0
    first_seen: date
    note: str | None = None


@router.post("/{vehicle_id}")
async def add_watchitem(
    vehicle_id: str, body: WatchItemCreate,
    session: AsyncSession = Depends(get_session),
):
    await _get_vehicle_or_404(vehicle_id, session)
    item = WatchItem(
        vehicle_id=vehicle_id,
        title=body.title,
        source_type=body.source_type,
        source_ref=body.source_ref,
        post_count=body.post_count,
        first_seen=body.first_seen,
        note=body.note,
    )
    session.add(item)
    await session.commit()
    return {"id": item.id, "title": item.title}


@router.get("/{vehicle_id}")
async def list_watchitems(vehicle_id: str, session: AsyncSession = Depends(get_session)):
    await _get_vehicle_or_404(vehicle_id, session)
    rows = await session.execute(
        select(WatchItem).where(WatchItem.vehicle_id == vehicle_id)
        .order_by(WatchItem.first_seen.desc())
    )
    return [
        {
            "id": w.id, "title": w.title, "source_type": w.source_type,
            "source_ref": w.source_ref, "post_count": w.post_count,
            "first_seen": str(w.first_seen), "note": w.note or "",
        }
        for w in rows.scalars().all()
    ]


@router.delete("/{vehicle_id}/{item_id}")
async def delete_watchitem(
    vehicle_id: str, item_id: str,
    session: AsyncSession = Depends(get_session),
):
    await session.execute(
        delete(WatchItem).where(WatchItem.id == item_id, WatchItem.vehicle_id == vehicle_id)
    )
    await session.commit()
    return {"ok": True}
```

- [ ] **Step 6: 注册 router**

`api/main.py` 加：
```python
from api.routes.watchlist import router as watchlist_router
# ...
app.include_router(watchlist_router)
```

- [ ] **Step 7: 运行测试通过**

```bash
"C:/Users/<you>/anaconda3/python.exe" -m pytest tests/test_watchlist.py -v
```
预期：PASS。

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: WatchItem 手动关注清单模型 + CRUD 端点（无状态机）"
```

---

## Task 3: 缺陷话题挖掘落地（发酵层数据源）

**依据：** OpenSpec `openspec/changes/defect-theme-monitoring/design.md` 四步。本任务实现后端挖掘管线 + 端点，前端在 Task 4 接入。

**Files:**
- Create: `pipeline/analysis/defect_miner.py`
- Modify: `api/routes/dashboard.py`（新增 `/defect-themes/{vehicle_id}`）
- Modify: `api/routes/collection.py`（Phase 9 改调 defect mining）
- Modify: `scripts/daily_update.py`
- Test: `tests/test_defect_miner.py`

- [ ] **Step 1: 读 OpenSpec design.md 确认四步契约**

```bash
cat openspec/changes/defect-theme-monitoring/design.md
cat openspec/changes/defect-theme-monitoring/specs/defect-theme-mining/spec.md
```
四步：`_complaint_pool`（近7天全量评论，口径三挂+coalesce，上限5000按likes截断）→ `_cluster_complaints`（jieba+停用词+共现边+连通分量，簇准入≥8评论且≥2帖，score=评论数×(0.5+负面占比) 取top5）→ `_judge_defect_clusters`（LLM一次判≤5簇 is_defect/name/severity/suggestion）→ 落库/端点。

- [ ] **Step 2: 写 defect_miner 测试**

Create `tests/test_defect_miner.py`：
```python
import pytest
from pipeline.analysis.defect_miner import _complaint_pool, _cluster_complaints

@pytest.mark.asyncio
async def test_complaint_pool_filters_recent_and_caps():
    # 验证：只取近7天、按 likes 截断、上限5000、口径三挂
    pool = await _complaint_pool(vehicle_id="306be9ad-b6ab-4729-aeb0-262b91e1530d", session=test_session)
    assert len(pool) <= 5000
    assert all(c.likes is not None for c in pool)

def test_cluster_admission_threshold():
    # 簇准入 ≥8 评论且 ≥2 帖
    clusters = _cluster_complaints([fake_comments])
    for cl in clusters:
        assert cl.comment_count >= 8
        assert cl.post_count >= 2
```
（具体 fixture 按 design.md 字段补全）

- [ ] **Step 3: 运行确认失败**

```bash
"C:/Users/<you>/anaconda3/python.exe" -m pytest tests/test_defect_miner.py -v
```
预期：FAIL（模块不存在）。

- [ ] **Step 4: 实现 defect_miner.py**

Create `pipeline/analysis/defect_miner.py`，按 design.md 四步实现。关键点：
- `_complaint_pool`：查 `PostComment` join `RawPost`，`RawPost.vehicle_id == vid` + `SELF_ONLY` + `AUTHENTIC_AUTHOR` + `published_at >= now-7d`，order by likes desc，limit 5000
- `_cluster_complaints`：jieba 分词 + 停用词 + 同评论共现边 → networkx 连通分量（不用 Louvain）→ 簇准入过滤
- `_judge_defect_clusters`：调 `utils.llm_client` 一次判 ≤5 簇，失败静默返回空
- `mine_defect_themes(vehicle_id, session)`：编排四步，返回 list[dict]

参考 `pipeline/analysis/point_miner.py`（已删，但 git 历史可查 LLM 调用模式）或 `pipeline/analysis/event_tracker.py` 的 LLM 调用范式。

- [ ] **Step 5: 实现 /defect-themes 端点**

`api/routes/dashboard.py` 新增：
```python
@router.get("/defect-themes/{vehicle_id}")
async def get_defect_themes(
    vehicle_id: str,
    session: AsyncSession = Depends(get_session),
):
    """发酵层：缺陷话题簇（中低互动帖聚类，非热度榜）。"""
    await _get_vehicle_or_404(vehicle_id, session)
    from pipeline.analysis.defect_miner import mine_defect_themes
    return await mine_defect_themes(vehicle_id, session)
```

- [ ] **Step 6: collection.py Phase 9 改调 defect mining**

`api/routes/collection.py`（原 Phase 9 位置）改为：
```python
            # Phase 9: 缺陷话题挖掘（发酵层；失败不断管线）
            try:
                from pipeline.analysis.defect_miner import mine_defect_themes
                dstats = await mine_defect_themes(vehicle_id, session)
                pipeline_phases[vehicle_id]["defect_themes"] = len(dstats)
            except Exception as e:
                logger.warning("Defect mining failed: %s", e)
```

- [ ] **Step 7: daily_update.py 同步**

`scripts/daily_update.py` 把 mine_points 调用换为 mine_defect_themes。

- [ ] **Step 8: 测试通过**

```bash
"C:/Users/<you>/anaconda3/python.exe" -m pytest tests/test_defect_miner.py tests/test_watchlist.py -v
```
预期：PASS。

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: 缺陷话题挖掘（发酵层）— 全量评论聚类+LLM簇判定，替代传播点报Phase9"
```

---

## Task 4: 前端三分法重组 + 关注清单入口

**Files:**
- Modify: `frontend/index.html`（6 区→3 层 + chrome 关注入口 + 各信号关注按钮）
- Modify: `frontend/static/js/app.js`（删 viewMode/points、加 watchlist+defect loader、关注按钮方法）
- Create: `frontend/static/js/watchlist.js`
- Create: `frontend/static/js/defect.js`

- [ ] **Step 1: chrome 顶部加"我的关注"入口**

`frontend/index.html` 在 view-switch 区（36-41 行，现已删 points pill）位置改为"我的关注"按钮：
```html
        <button class="chrome-btn" @click="showWatchlist = true">
            ★ 关注 <span v-if="watchItems.length" class="badge">{{ watchItems.length }}</span>
        </button>
```
（viewMode 切换整组删，因为只剩 monitor 单视图，不再需要切换 pill）

- [ ] **Step 2: 关注清单 modal**

`frontend/index.html` 在 dialog panel 前（约 620 行前）加：
```html
    <div v-if="showWatchlist" class="modal-overlay" @click.self="showWatchlist = false">
        <div class="modal watchlist-modal">
            <div class="modal-head">
                <h3>我的关注 · {{ currentVehicleName }}</h3>
                <button class="icon-btn" @click="showWatchlist = false">×</button>
            </div>
            <div class="watchlist-body">
                <div v-for="w in watchItems" :key="w.id" class="watch-item">
                    <div class="watch-item-title">{{ w.title }}</div>
                    <div class="watch-item-meta">
                        <span>{{ sourceTypeLabel(w.source_type) }}</span>
                        <span>涉及 {{ w.post_count }} 帖</span>
                        <span>首发现 {{ w.first_seen }}</span>
                    </div>
                    <button class="btn btn-ghost" @click="removeWatch(w.id)">移除</button>
                </div>
                <div v-if="!watchItems.length" class="empty">暂无关注项 · 在看板信号旁点"关注"添加</div>
            </div>
        </div>
    </div>
```

- [ ] **Step 3: 6 区重组为三层**

`frontend/index.html` 现役 6 section（01-06）重组：
- **第一层 · 热度全景**（合并原 01+02+04 的热度部分）：KPI + 情感分布 donut + 情感趋势 + 正向得分 + 搜索热度 + 讨论声量 + 平台声量 + 热帖TOP5
- **第二层 · 风险信号**（原 03）：风险横幅 + 吐槽榜TOP10 + 负面维度 + 负面事件 + 负面声量趋势 + 口碑反转
- **第三层 · 话题发酵**（原 05 + 缺陷簇）：事件脉搏 + 观点标签 + **缺陷话题簇（新）**

section 标题改为：
```html
<h2 class="sec-title">第一层 · 热度全景</h2>
<h2 class="sec-title">第二层 · 风险信号</h2>
<h2 class="sec-title">第三层 · 话题发酵</h2>
```
原 06 内容洞察（词云+简报）并入第一层底部或保留为独立收尾区（用户审美决定，先保留）。

- [ ] **Step 4: 各信号旁加"关注"按钮**

在热帖 TOP5、吐槽榜 TOP10、缺陷簇、事件卡片旁加：
```html
<button class="watch-btn" @click="addWatch({
    title: p.title,
    source_type: 'hot_post',  // 或 complaint/defect_cluster/event
    source_ref: p.id,
    post_count: 1,
    first_seen: (p.published_at || '').slice(0,10) || todayStr(),
})">★</button>
```

- [ ] **Step 5: app.js 加 state 与方法**

`frontend/static/js/app.js` data 加：
```javascript
    showWatchlist: false,
    watchItems: [],
    defectThemes: [],
```
methods 加：
```javascript
    async loadWatchItems() {
        if (!this.currentVehicleId) return;
        this.watchItems = await this.apiFetch(`/api/watchlist/${this.currentVehicleId}`) || [];
    },
    async addWatch(payload) {
        await this.apiFetch(`/api/watchlist/${this.currentVehicleId}`, {
            method: "POST", body: JSON.stringify(payload),
            headers: {"Content-Type": "application/json"},
        });
        await this.loadWatchItems();
        this.toast("已加入关注", "ok");
    },
    async removeWatch(id) {
        await this.apiFetch(`/api/watchlist/${this.currentVehicleId}/${id}`, {method: "DELETE"});
        await this.loadWatchItems();
    },
    sourceTypeLabel(t) {
        return {hot_post:"热帖", complaint:"吐槽", defect_cluster:"缺陷簇", event:"事件"}[t] || t;
    },
    async loadDefectThemes() {
        if (!this.currentVehicleId) return;
        this.defectThemes = await this.apiFetch(`/api/dashboard/defect-themes/${this.currentVehicleId}`) || [];
    },
```
在 `selectVehicle`/数据加载流程里调 `loadWatchItems()` 和 `loadDefectThemes()`（与 loadOverview 同位置）。

- [ ] **Step 6: defect.js 渲染第三层缺陷簇**

Create `frontend/static/js/defect.js`（全局对象 DefectUI，模式同 dialog.js）：
```javascript
const DefectUI = {
    render(vm) {
        // 在 #defect-themes 容器里渲染簇列表（severity=high 带⚠前缀）
    },
};
```
`frontend/index.html` 第三层加容器：
```html
<div class="card">
    <div class="card-title">缺陷话题簇<span class="card-sub">中低互动帖聚类 · 早期预警</span></div>
    <div id="defect-themes" class="defect-list"></div>
</div>
```

- [ ] **Step 4.7: 引入新 js + 删 points.js 引用**

`frontend/index.html` 底部：
```html
<script src="/static/js/watchlist.js"></script>
<script src="/static/js/defect.js"></script>
```
（points.js 引用在 Task 1 已删）

- [ ] **Step 8: CSS（关注按钮、modal、缺陷簇样式）**

`frontend/static/css/style.css?v=21`（版本号 +1 cache-bust）加 `.watch-btn`、`.watchlist-modal`、`.watch-item`、`.defect-list`、`.badge` 样式。

- [ ] **Step 9: 手动验证**

```bash
# 启动服务（Start-Process 分离）
powershell.exe -NoProfile -Command "Start-Process 'C:\Users\<you>\anaconda3\python.exe' 'start.py' -WorkingDirectory 'C:\Users\<you>\Desktop\Agent项目\Vehicle Sentiment Analysis Board'"
# 打开 127.0.0.1:8000 核对：三分法三层、关注按钮、关注 modal、缺陷簇区
```

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat(frontend): 三分法看板（热度/风险/发酵）+ 顶部关注清单 + 缺陷簇区"
```

---

## Task 5: 文档与收尾

**Files:**
- Modify: `docs/舆情看板-前端设计.md`
- Update: `openspec/changes/defect-theme-monitoring/`（archive 标记）
- Update: memory

- [ ] **Step 1: 更新前端设计文档**

`docs/舆情看板-前端设计.md` 同步三分法结构、关注清单、缺陷簇归位发酵层、传播点报删除说明。

- [ ] **Step 2: OpenSpec 收尾**

`openspec/changes/defect-theme-monitoring/` 若实施完成，按 dual-mode 流程归档（移至 archived/ 或标记 completed）。

- [ ] **Step 3: memory 落盘**

写 memory：三分法重设计完成 + 传播点报删除 + 手动关注清单 + 缺陷簇归位发酵层。

- [ ] **Step 4: 全量回归**

```bash
"C:/Users/<you>/anaconda3/python.exe" -m pytest tests/ -q
```
预期：全绿（删 test_points.py 后总数应降，新增 test_watchlist/test_defect_miner 补回）。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs: 三分法重设计文档 + defect-theme OpenSpec 收尾"
```

---

## Self-Review

**Spec coverage:**
- 第1问（吐槽榜软文）：Task 0 修 `/top-posts` AUTHENTIC_AUTHOR；genuine_sentiment 反向筛作为后续小需求（用户未拍板，先不进本计划，避免范围膨胀）
- 第2问（采集关系）：Task 1 删自动挖掘后，看板与点报"一起采集"语义变为"看板单一采集管线，无点报"
- 第3问（正向得分）：公式不变（已实证 auto_media 未灌水），无需改
- 第4问（极狐T7）：Task 0 Step 2-3 根治
- 第5问（整体设计）：三分法 + 关注清单全计划覆盖
- 缺陷话题监控：Task 3 后端 + Task 4 前端接入

**Placeholder scan:** defect_miner.py 的四步实现引用 design.md（已存在文件，非 placeholder）；测试 fixture 标注"按 design.md 字段补全"——执行时需读 design.md 落实具体字段，这是合理的外部引用而非占位。

**Type consistency:** WatchItem 字段（source_type/source_ref/post_count/first_seen）在模型、Pydantic、端点、前端 addWatch payload 中一致。source_type 枚举四值（hot_post/complaint/defect_cluster/event）前后端一致。

**已知风险：**
- Task 3 defect_miner 是本计划体量最大、最依赖 LLM 实弹的部分；若 TikHub 余额未恢复（见 memory `tikhub-balance-ops-2026-09-22`），`_complaint_pool` 评论不足会导致簇准入不达标→空结果。执行时需先确认有评论数据。
- Task 4 前端重组涉及大量 index.html 行号变动，建议执行时按当前文件实际行号重新定位。
