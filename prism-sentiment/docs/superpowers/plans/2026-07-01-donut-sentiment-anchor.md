# Donut Sentiment Anchor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 sentiment donut 点击走错 anchor 分支——新增独立 `sentiment` anchor，点情感扇区显示该情感的帖子占比+维度画像+热门帖。

**Architecture:** 后端 dialog.py `_build_context` 新增 `elif anchor_type=="sentiment"` 分支（占比+维度Top5平均+热门帖）；前端 app.js donut click 加中文→英文映射、改 anchor 类型为 "sentiment"。TDD：先写后端失败测试（照 test_dialog_api.py:162 模板）→ 实现 → 前端改动。

**Tech Stack:** Python + SQLAlchemy（dialog 后端）、原生 JS + Vue3 + Echarts（前端）、pytest。

**Spec:** `docs/superpowers/specs/2026-07-01-donut-sentiment-anchor-design.md`

---

## File Structure

| 文件 | 责任 | 本次改动 |
|------|------|---------|
| `api/routes/dialog.py` | anchor 对话上下文构建 | `_build_context` 新增 sentiment 分支（platform 分支后，:95 附近） |
| `frontend/static/js/app.js` | 前端图表 + click | 顶部加 `SENTIMENT_CN2EN` 常量 + :400-402 donut click 改 anchor 类型 |
| `tests/test_dialog_api.py` | 后端对话测试 | 加 `test_sentiment_anchor_context`（照 :162-197 模板） |
| `tests/test_dialog_frontend.py` | 前端源码检查 | 加 donut 用 sentiment anchor 的检查 |

**关键复用**：`test_dialog_api.py:162-197` 的 `test_event_anchor_sentiment_not_zero_without_eventgroup` 是直接测 `_build_context` 的模板（自建 engine/session + 插 RawPost/AnalyzedPost + 调 `_build_context(vid, type, data, session)` + 断言 ctx 文本）。sentiment 测试照此模式。`_build_context(vehicle_id, anchor_type, anchor_data, session)` 4 参数。

---

### Task 1: 后端 sentiment anchor 分支（TDD）

**Files:**
- Modify: `tests/test_dialog_api.py`（末尾追加新测试）
- Modify: `api/routes/dialog.py`（`_build_context` 新增 sentiment 分支）

- [ ] **Step 1: 写失败测试 `test_sentiment_anchor_context`**

在 `tests/test_dialog_api.py` 末尾（:197 `test_event_anchor_sentiment_not_zero_without_eventgroup` 之后）追加：

```python
async def test_sentiment_anchor_context():
    """sentiment anchor：点情感扇区 → context 含占比+维度Top+热门帖。

    donut anchor 修复验证：原 app.js 把 {sentiment} 传给只认 {date} 的 trend 分支，
    context 恒空。新增独立 sentiment 分支后应返回完整情感画像。
    """
    from datetime import datetime
    from api.routes.dialog import _build_context
    from models.schemas import AnalyzedPost, RawPost

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        session.add(Vehicle(id="v1", name="海豹", brand="比亚迪"))
        ts = datetime(2026, 5, 15)
        # 2 负面帖（含 dim_sentiment）+ 1 正面帖
        session.add(RawPost(id="r0", vehicle_id="v1", source="cdp", platform="weibo",
                            content="续航太差", published_at=ts, likes=100, comments=10, shares=5))
        session.add(AnalyzedPost(id="a0", post_id="r0", vehicle_id="v1", sentiment="negative",
                                 dim_sentiment=json.dumps({"续航": -1.0, "动力": -0.5, "空间": 0.2})))
        session.add(RawPost(id="r1", vehicle_id="v1", source="cdp", platform="weibo",
                            content="异响严重", published_at=ts, likes=50, comments=5, shares=2))
        session.add(AnalyzedPost(id="a1", post_id="r1", vehicle_id="v1", sentiment="negative",
                                 dim_sentiment=json.dumps({"续航": -0.8, "异响": -1.0})))
        session.add(RawPost(id="r2", vehicle_id="v1", source="cdp", platform="weibo",
                            content="很满意", published_at=ts, likes=10))
        session.add(AnalyzedPost(id="a2", post_id="r2", vehicle_id="v1", sentiment="positive",
                                 dim_sentiment=json.dumps({"外观": 1.0})))
        await session.commit()
        ctx = await _build_context("v1", "sentiment", {"sentiment": "negative"}, session)
    await engine.dispose()

    assert "负面帖子数: 2" in ctx        # 2 负面帖
    assert "占主车型帖 66.7" in ctx       # 2/3 = 66.7%
    assert "续航" in ctx                  # 维度Top 含续航（负面取最低 score）
    assert "续航太差" in ctx              # 热门帖（r0 互动 115 最高）
```

- [ ] **Step 2: 跑新测试，确认 FAIL**

Run: `PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_dialog_api.py::test_sentiment_anchor_context -v`
Expected: FAIL — sentiment 分支不存在，`_build_context` 走完所有 elif 都不匹配 → context 只含末尾的 EventGroup 注入（无"负面帖子数"），`assert "负面帖子数: 2" in ctx` 失败。

- [ ] **Step 3: 实现 sentiment 分支**

在 `api/routes/dialog.py` 的 `_build_context` 里，**platform 分支结束后、event 分支（`elif anchor_type == "event":`）之前**，插入新分支：

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

            # 2. 维度分布 Top5（平均口径 sum/len，加 sentiment 过滤；正面取最高、负面/中性取最低）
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
                    [{"dim": k, "score": round(sum(v) / len(v), 3)} for k, v in dim_agg.items()],
                    key=lambda r: r["score"],
                    reverse=(sentiment == "positive"),
                )
                context_parts.append(
                    f"{sent_cn}帖子维度Top5: " + ", ".join(f"{d['dim']}({d['score']:+.1f})" for d in dim_sorted[:5])
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

注意：`SELF_ONLY` 已在 `models/schemas.py` 定义（dialog.py 应已 import 或可从 models.schemas 引用——检查 dialog.py 顶部 import，若未引入 SELF_ONLY 则加 `from models.schemas import ..., SELF_ONLY`）。

- [ ] **Step 4: 跑新测试，确认 PASS**

Run: `PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_dialog_api.py::test_sentiment_anchor_context -v`
Expected: PASS

- [ ] **Step 5: 回归 test_dialog_api.py 全文件**

Run: `PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_dialog_api.py -v`
Expected: 全 PASS（含原有 trend/event/platform/opinion anchor 测试 + 新 sentiment 测试，确认新分支没破坏既有分支）。

- [ ] **Step 6: Commit**

```bash
git add api/routes/dialog.py tests/test_dialog_api.py
git commit -m "feat(dialog): sentiment anchor 分支（占比+维度Top5+热门帖，TDD 守护）"
```

---

### Task 2: 前端 donut click 改 anchor 类型 + 中英文映射

**Files:**
- Modify: `frontend/static/js/app.js`（顶部常量 + :400-402 donut click）
- Modify: `tests/test_dialog_frontend.py`（加 donut anchor 检查）

- [ ] **Step 1: 加 `SENTIMENT_CN2EN` 常量**

在 `frontend/static/js/app.js` 顶部 `CHART_COLORS` 常量定义（:3）之后，加：

```js
const SENTIMENT_CN2EN = { "正面": "positive", "负面": "negative", "中性": "neutral" };
```

- [ ] **Step 2: 改 donut click handler**

把 `frontend/static/js/app.js` 的 `renderSentimentDonut` 里 donut click（约 :400-402）：

```js
                this.sentimentDonutChart.on("click", (params) => {
                    if (params.name) openDialog("trend", { sentiment: params.name });
                });
```

改为：

```js
                this.sentimentDonutChart.on("click", (params) => {
                    const s = SENTIMENT_CN2EN[params.name];
                    if (s) openDialog("sentiment", { sentiment: s });
                });
```

- [ ] **Step 3: 加前端源码检查测试**

在 `tests/test_dialog_frontend.py` 末尾（:38 后）追加：

```python
def test_app_js_donut_uses_sentiment_anchor():
    """donut 点击应走 sentiment anchor（非旧的 trend 错配），且经中英文映射。"""
    path = os.path.join(FRONTEND_DIR, "static", "js", "app.js")
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    assert 'openDialog("sentiment"' in source        # 新 anchor 类型
    assert 'SENTIMENT_CN2EN' in source                # 中英文映射常量
    assert 'openDialog("trend", { sentiment' not in source  # 旧错配已移除
```

- [ ] **Step 4: 跑前端测试**

Run: `PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_dialog_frontend.py -v`
Expected: 全 PASS（含新 test_app_js_donut_uses_sentiment_anchor + 原 4 个）。

- [ ] **Step 5: Commit**

```bash
git add frontend/static/js/app.js tests/test_dialog_frontend.py
git commit -m "fix(frontend): donut click 改走 sentiment anchor + 中英文映射"
```

---

### Task 3: 集成验证（手动/CDP）

**Files:** 无代码改动，仅验证。

- [ ] **Step 1: 跑相关测试套件兜底**

Run: `PYTHONIOENCODING=utf-8 "C:/Users/<you>/Anaconda3/python.exe" -m pytest tests/test_dialog_api.py tests/test_dialog_frontend.py -v`
Expected: 全 PASS。

- [ ] **Step 2: 真实点 donut 验证（可选，需服务运行）**

启动 `uvicorn api.main:app --port 8000`，浏览器打开看板，点情感甜甜圈的"负面"扇区，确认对话框内容含：
- "负面帖子数: X（占主车型帖 Y%）"
- "负面帖子维度Top5: ..."（含具体维度+score）
- "负面热门帖: ..."（含帖标题）

若点后 context 仍空或报错，回 Task 1 排查分支是否正确接入。

> Task 3 无 commit。若 Step 2 无法执行（无数据/无 LLM 配置），Step 1 测试套件兜底即可证明逻辑正确。

---

## Self-Review

**Spec coverage**：
- spec 改动 1（app.js donut click + 映射）→ Task 2 Step 1-2 ✓
- spec 改动 2（dialog.py sentiment 分支）→ Task 1 Step 3 ✓
- spec 测试（test_dialog_api.py）→ Task 1 Step 1 ✓
- spec 前端测试（test_dialog_frontend.py）→ Task 2 Step 3 ✓
- spec 集成验证 → Task 3 ✓
- spec Top5 取向（reverse=(sentiment=="positive")）→ Task 1 Step 3 代码 ✓，Task 1 Step 1 测试用 negative 验证取最低（续航 -0.9 排前）✓
- spec SELF_ONLY 口径 → Task 1 Step 3 代码 ✓

**Placeholder scan**：无 TBD/TODO；每个 code step 有完整代码；测试断言有精确期望值（"负面帖子数: 2"、"占主车型帖 66.7"）✓

**Type consistency**：`_build_context(vid, type, data, session)` 4 参数在 Task 1 Step 1 测试与现有 :193 一致；`SENTIMENT_CN2EN` 在 Task 2 Step 1 定义、Step 2 使用、Step 3 检查，命名一致 ✓

**数值核算**（Task 1 Step 1 断言依据）：
- 负面帖 a0(dim:续航-1.0,动力-0.5,空间0.2) + a1(dim:续航-0.8,异响-1.0)；正面 a2(外观1.0)
- 负面维度平均：续航=(-1.0+-0.8)/2=-0.9、动力=-0.5、空间=0.2、异响=-1.0；negative 升序 Top5=异响,续航,动力,空间 → ctx 含"续航" ✓
- total=3（NULL subject 视为 self），negative=2 → 66.7% ✓
- 热门帖互动：r0=115 > r1=57 → r0 "续航太差"排前 ✓
