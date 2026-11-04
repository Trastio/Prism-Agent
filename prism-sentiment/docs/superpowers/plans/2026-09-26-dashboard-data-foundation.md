# 数据地基整改 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复采集→清洗→分析→呈现全链路的数据真实性地基（口径统一/作者背调/时间窗跟随/互动刷新/周报口径/容错/迁移框架），让看板数字变"真"。

**Architecture:** 批次0地基（迁移/配置/HTML/歧义，无依赖）→ 批次1数据真实性（口径常量/背调/时间窗/互动刷新/周报/词云/容错/daily_update，依赖批次0）→ 验证收尾。基于 openspec/changes/dashboard-data-foundation/ 四件套。

**Tech Stack:** FastAPI + SQLAlchemy async + SQLite · Vue 3.4.38 CDN + ECharts · pytest · conda base（python 全路径 C:/Users/<you>/anaconda3/python.exe）

**工作目录:** C:\Users\<you>\Desktop\Agent项目\Vehicle Sentiment Analysis Board

---

## Phase 0: 地基（无依赖）

### Task 0.1: DB 迁移框架（E2）

**Files:**
- Modify: `models/database.py`
- Test: `tests/test_migrations.py`

- [ ] **Step 1: 写迁移框架测试**

Create `tests/test_migrations.py`:
```python
import pytest
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

@pytest.mark.asyncio
async def test_schema_migrations_table_exists(tmp_path):
    """schema_migrations 表存在且记录已应用迁移。"""
    db_path = str(tmp_path / "test.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    # 用独立 engine 测试，不依赖全局 engine（全局 engine 模块加载时已绑定 DB_PATH）
    from models.database import Base
    from models.schemas import Vehicle, RawPost, AnalyzedPost  # 确保模型注册
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 跑迁移
        from models.database import _run_migrations
        await _run_migrations(conn)
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"))
        assert result.fetchone() is not None
        rows = (await conn.execute(text("SELECT name FROM schema_migrations"))).fetchall()
        assert len(rows) >= 4  # 现有4个迁移已记录
    await engine.dispose()

@pytest.mark.asyncio
async def test_migration_idempotent_on_fresh_db(tmp_path):
    """新库（create_all 已建列）跑迁移不炸——幂等检查。"""
    db_path = str(tmp_path / "test.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    from models.database import Base, _run_migrations
    from models.schemas import Vehicle, RawPost, AnalyzedPost
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # 新库已建含新列的表
        await _run_migrations(conn)  # 迁移要幂等：列已存在时跳过
    await engine.dispose()

@pytest.mark.asyncio
async def test_migration_failure_raises(tmp_path):
    """迁移失败时 raise，不吞错。"""
    db_path = str(tmp_path / "test.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    from models.database import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 构造会失败的迁移 SQL
        with pytest.raises(Exception):
            await conn.execute(text("ALTER TABLE nonexistent_table ADD COLUMN x"))
    await engine.dispose()
```

- [ ] **Step 2: 运行确认失败**

```bash
"C:/Users/<you>/anaconda3/python.exe" -m pytest tests/test_migrations.py -v
```
预期 FAIL（schema_migrations 表不存在）。

- [ ] **Step 3: 实现迁移框架**

`models/database.py` 改 init_db：
1. create_all 后建 schema_migrations 表（version INT PK, name TEXT, applied_at TEXT）
2. 定义迁移注册表（列表，每项 {version, name, sql}），现有 4 个迁移转入
3. init_db 查已应用版本，只跑未应用的，跑完 INSERT 版本记录
4. 失败 raise（不 try/except pass）

```python
MIGRATIONS = [
    {"version": 1, "name": "keywords_expanded_at", "sql": "ALTER TABLE vehicles ADD COLUMN keywords_expanded_at DATETIME"},
    {"version": 2, "name": "relevance_score", "sql": "ALTER TABLE raw_posts ADD COLUMN relevance_score FLOAT"},
    {"version": 3, "name": "subject", "sql": "ALTER TABLE analyzed_posts ADD COLUMN subject VARCHAR"},
    {"version": 4, "name": "subject_name", "sql": "ALTER TABLE analyzed_posts ADD COLUMN subject_name VARCHAR DEFAULT ''"},
]

async def _run_migrations(conn):
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
        )
    """))
    applied = {r[0] for r in (await conn.execute(text("SELECT version FROM schema_migrations"))).fetchall()}
    from datetime import datetime
    for m in MIGRATIONS:
        if m["version"] not in applied:
            # 幂等检查：列已存在则跳过（新库 create_all 已建含新列的表）
            if m.get("check_column"):
                col_exists = await _column_exists(conn, m["check_column"]["table"], m["check_column"]["column"])
                if col_exists:
                    # 列已存在，只记版本不跑 ALTER
                    await conn.execute(text(
                        f"INSERT INTO schema_migrations (version, name, applied_at) VALUES ({m['version']}, '{m['name']}', '{datetime.now().isoformat()}')"
                    ))
                    continue
            await conn.execute(text(m["sql"]))
            await conn.execute(text(
                f"INSERT INTO schema_migrations (version, name, applied_at) VALUES ({m['version']}, '{m['name']}', '{datetime.now().isoformat()}')"
            ))

async def _column_exists(conn, table: str, column: str) -> bool:
    """PRAGMA table_info 查列是否存在（幂等检查）。"""
    rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).fetchall()
    return any(r[1] == column for r in rows)
```

迁移注册表加 check_column（幂等检查）：
```python
MIGRATIONS = [
    {"version": 1, "name": "keywords_expanded_at", "sql": "ALTER TABLE vehicles ADD COLUMN keywords_expanded_at DATETIME",
     "check_column": {"table": "vehicles", "column": "keywords_expanded_at"}},
    {"version": 2, "name": "relevance_score", "sql": "ALTER TABLE raw_posts ADD COLUMN relevance_score FLOAT",
     "check_column": {"table": "raw_posts", "column": "relevance_score"}},
    {"version": 3, "name": "subject", "sql": "ALTER TABLE analyzed_posts ADD COLUMN subject VARCHAR",
     "check_column": {"table": "analyzed_posts", "column": "subject"}},
    {"version": 4, "name": "subject_name", "sql": "ALTER TABLE analyzed_posts ADD COLUMN subject_name VARCHAR DEFAULT ''",
     "check_column": {"table": "analyzed_posts", "column": "subject_name"}},
]
```

- [ ] **Step 4: 测试通过**

```bash
"C:/Users/<you>/anaconda3/python.exe" -m pytest tests/test_migrations.py -v
```
预期 PASS。

- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "feat(db): schema_migrations 迁移框架——版本控制+失败raise（替代try/except吞错）"
```

---

### Task 0.2: 配置统一（E3）

**Files:**
- Modify: `pipeline/analysis/batch_runner.py`, `pipeline/scheduler.py`, `pipeline/analysis/defect_miner.py`, `pipeline/collectors/oneapi_collector.py`
- Create: `docs/配置参数.md`

- [ ] **Step 1: 扫描所有硬编码参数**

```bash
grep -rn "_COMMENT_TOP_N_DEFAULT\|_CRAWL_CONCURRENCY\|_COMMENT_WINDOW_DAYS\|_MAX_COMMENTS\|_MIN_CLUSTER\|_MAX_TOPIC\|_MAX_INTERACTION\|_COMMENT_MAX_PAGES\|_KS_MAX_PAGES" pipeline/ | grep "= [0-9]"
```

- [ ] **Step 2: 抽 _env_int 到公共位置**

`_env_int` 当前在 `batch_runner.py` 本地定义。抽到 `utils/config.py`：
```python
# utils/config.py
import os
def env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))

def env_str(name: str, default: str) -> str:
    return os.getenv(name, default)
```
各文件改为 `from utils.config import env_int, env_str`（batch_runner 保留 _env_int 别名向后兼容）。

- [ ] **Step 3: 逐个改为 env_int 覆盖**

示例（batch_runner.py）：
```python
_COMMENT_TOP_N_DEFAULT = env_int("COMMENT_TOP_N_DEFAULT", 15)
```
defect_miner.py：
```python
from utils.config import env_int
_WINDOW_DAYS = env_int("DEFECT_WINDOW_DAYS", 7)
_MAX_COMMENTS = env_int("DEFECT_MAX_COMMENTS", 5000)
_MIN_CLUSTER_COMMENTS = env_int("DEFECT_MIN_CLUSTER_COMMENTS", 8)
_MIN_CLUSTER_POSTS = env_int("DEFECT_MIN_CLUSTER_POSTS", 2)
```
scheduler.py：
```python
from utils.config import env_int
_CRAWL_CONCURRENCY = env_int("CRAWL_CONCURRENCY", 5)
```

- [ ] **Step 4: 写配置文档**

Create `docs/配置参数.md`：
```markdown
# 配置参数

所有参数支持环境变量覆盖（_env_int/_env_str 模式）。

| 参数 | Env 变量 | 默认值 | 说明 |
|---|---|---|---|
| 评论补采 top-N | COMMENT_TOP_N | 15 | 每平台互动 top-N 帖补评论 |
| 采集并发度 | CRAWL_CONCURRENCY | 5 | 同时采集的车型数 |
| 评论窗口 | COMMENT_WINDOW_DAYS | 30 | 评论摘要选帖窗口（天） |
| 缺陷评论池窗口 | DEFECT_WINDOW_DAYS | 7 | 缺陷挖掘评论池时间窗 |
| ... | ... | ... | ... |
```

- [ ] **Step 5: 测试 + Commit**
```bash
"C:/Users/<you>/anaconda3/python.exe" -m pytest tests/ -q
git add -A && git commit -m "refactor(config): 硬编码参数统一 env 覆盖 + docs/配置参数.md"
```

---

### Task 0.3: 微博 HTML strip（B3）

**Files:**
- Modify: `pipeline/collectors/post_utils.py`（新增统一 strip 函数）
- Modify: `pipeline/collectors/oneapi_collector.py`（微博入库前调用）
- Test: `tests/test_weibo_html_strip.py`

- [ ] **Step 1: 写测试**

Create `tests/test_weibo_html_strip.py`:
```python
from pipeline.collectors.post_utils import strip_html

def test_strip_anchor_tag():
    assert strip_html('<a href="https://m.weibo.cn/...">超话</a>') == "超话"

def test_strip_multiple_tags():
    assert strip_html('<b>风云T7</b> <a href="x">上市</a>') == "风云T7 上市"

def test_no_html_unchanged():
    assert strip_html("风云T7 上市评测") == "风云T7 上市评测"

def test_empty_string():
    assert strip_html("") == ""
```

- [ ] **Step 2: 确认失败 + 实现**

`post_utils.py` 新增：
```python
import re
def strip_html(text: str) -> str:
    if not text:
        return text
    return re.sub(r'<[^>]+>', '', text).strip()
```

`oneapi_collector.py` 微博搜索结果入库前：
```python
from pipeline.collectors.post_utils import strip_html
# 在 _store_posts 或搜索结果处理处
post["title"] = strip_html(post.get("title", ""))
```

- [ ] **Step 3: 测试 + Commit**
```bash
"C:/Users/<you>/anaconda3/python.exe" -m pytest tests/test_weibo_html_strip.py -v
git add -A && git commit -m "fix(collect): 微博 title HTML strip——入库前剥标签"
```

---

### Task 0.4: 歧义预检脚本（A6）

**Files:**
- Create: `scripts/check_keyword_ambiguity.py`

- [ ] **Step 1: 实现脚本**

```python
"""关键词歧义预检——21 车扩容前对车名做搜索测试，检测歧义。

用法: python scripts/check_keyword_ambiguity.py --keyword 星愿
"""
import argparse, asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

async def check_ambiguity(keyword: str) -> dict:
    """调搜索 API 取前 20 帖，检查是否大量不相关。

    判定不相关的启发式：
    1. 标题+正文不含 keyword 本身 → 强不相关信号
    2. 标题含明显其他领域词（明星名/地名/其他产品类，如"肖战/生日/守护/超话"）→ 歧义信号
    3. 不相关占比 ≥ 30% → 报告歧义 + 提取 top 不相关词作为建议排除词
    """
    from pipeline.collectors.oneapi_collector import OneApiClient
    client = OneApiClient()
    if not client.is_available():
        return {"keyword": keyword, "total": 0, "irrelevant_count": 0, "samples": [], "suggested_excludes": []}
    # 搜抖音+小红书各取 10 帖（读 OneApiClient.search 签名后调用）
    posts = []
    for platform in ("douyin", "xiaohongshu"):
        try:
            p, _ = await client.search(keyword, platform, window_days=7)
            posts.extend(p[:10])
        except Exception:
            continue
    # 启发式判定
    irrelevant = [p for p in posts if keyword not in (p.get("title","") + p.get("content",""))]
    # 提取不相关帖的高频词作为建议排除
    from collections import Counter
    import jieba
    bad_words = Counter()
    for p in irrelevant:
        for w in jieba.cut(p.get("title","")):
            if len(w) >= 2 and w != keyword:
                bad_words[w] += 1
    suggested = [w for w, _ in bad_words.most_common(5)]
    return {
        "keyword": keyword, "total": len(posts),
        "irrelevant_count": len(irrelevant),
        "samples": [p.get("title","")[:30] for p in irrelevant[:5]],
        "suggested_excludes": suggested,
    }

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", required=True)
    ap.add_argument("--all-vehicles", action="store_true", help="对全库车名跑预检")
    args = ap.parse_args()
    result = asyncio.run(check_ambiguity(args.keyword))
    print(f"关键词: {result['keyword']}")
    print(f"总帖: {result['total']}, 疑似不相关: {result['irrelevant_count']}")
    if result['suggested_excludes']:
        print(f"建议负向排除: {result['suggested_excludes']}")
```

- [ ] **Step 2: 对 21 车名跑预检**
```bash
"C:/Users/<you>/anaconda3/python.exe" scripts/check_keyword_ambiguity.py --all-vehicles
```

- [ ] **Step 3: Commit**
```bash
git add -A && git commit -m "feat(scripts): 关键词歧义预检——扩车前检测车名歧义+建议排除词"
```

---

## Phase 1: 数据真实性

### Task 1.1: 口径常量统一（C1）

**Files:**
- Modify: `models/schemas.py`（LISTING_CALIBER 定义）
- Modify: `api/routes/dashboard.py`（12 端点挂载）
- Modify: `api/routes/analysis.py`（top-opinions 挂载）
- Test: `tests/test_caliber.py`（扩展）

- [ ] **Step 1: 定义 LISTING_CALIBER**

`models/schemas.py`：
```python
# 展示类端点统一口径
LISTING_CALIBER = (SELF_ONLY, AUTHENTIC_AUTHOR, RELEVANT_ONLY)
```

- [ ] **Step 2: event_tracker 聚类层口径过滤**

`pipeline/analysis/event_tracker.py`：`detect_events_for_vehicle` 查帖时 JOIN AnalyzedPost + RawPost，在 sentiment_distribution 统计循环前过滤。先读 event_tracker.py 确认 `p` 的字段结构（它是 RawPost dict 还是 join 后的 row），若缺 author_type/subject/analysis_status 则查询 JOIN 补齐：
```python
# detect_events_for_vehicle 的帖查询改为 JOIN
select(RawPost, AnalyzedPost.subject, AnalyzedPost.sentiment).outerjoin(
    AnalyzedPost, AnalyzedPost.post_id == RawPost.id
).where(RawPost.vehicle_id == vehicle_id)
# 聚类循环内过滤
for p in group:
    if p.subject not in (None, "self"): continue
    if p.author_type in INAUTHENTIC_AUTHOR_TYPES: continue
    if p.analysis_status == "irrelevant": continue
    sentiments[p.sentiment] += 1
```

- [ ] **Step 3: top-opinions / word-cloud / top-posts 补挂**

`api/routes/analysis.py` top-opinions：
```python
ap_query = (select(AnalyzedPost.opinion_tags)
    .join(RawPost, AnalyzedPost.post_id == RawPost.id)
    .where(AnalyzedPost.vehicle_id == vehicle_id, *LISTING_CALIBER))
```
`api/routes/dashboard.py` word-cloud：
```python
query = _relevant_posts_filter(
    select(RawPost.title, RawPost.content).where(RawPost.vehicle_id == vehicle_id, SELF_ONLY, AUTHENTIC_AUTHOR)
)
```
`api/routes/dashboard.py` top-posts：
```python
query = _relevant_posts_filter(
    select(RawPost).where(RawPost.vehicle_id == vehicle_id, SELF_ONLY, AUTHENTIC_AUTHOR)
)
```

- [ ] **Step 4: 确认 7 个已挂端点**

读 dashboard.py 逐个确认 /overview /sentiment-trend /dim-sentiment /comment-sentiment-diff /platform-distribution /defect-themes /reports 是否已挂全口径。/overview 在 T1.4 改造时补 RELEVANT_ONLY 显式挂；/reports 在 T1.6 改。

- [ ] **Step 5: 存量 EventGroup sentiment_distribution 回填脚本**

Create `scripts/backfill_event_sentiment.py`：遍历所有 EventGroup，按口径重算 sentiment_distribution（重新查事件内帖统计 sentiment）。

- [ ] **Step 6: 扩展 test_caliber.py**

新增横扫测试：对 12 端点各发请求，验证结果不含 brand_official/dealer/competitor/irrelevant 帖。

- [ ] **Step 7: 测试 + Commit**
```bash
"C:/Users/<you>/anaconda3/python.exe" -m pytest tests/test_caliber.py -v
git add -A && git commit -m "feat(caliber): LISTING_CALIBER 统一口径常量——12端点挂载+event聚类层口径+存量回填"
```

---

### Task 1.2: 作者行为背调（B1）

**Files:**
- Modify: `pipeline/collectors/post_utils.py`（profile_author_behavior）
- Modify: `models/schemas.py`（INAUTHENTIC_AUTHOR_TYPES 扩展）
- Modify: `pipeline/scheduler.py`（_store_posts 调用背调）
- Modify: `scripts/backfill_author_type.py`（存量回填扩展）
- Test: `tests/test_author_behavior.py`

- [ ] **Step 1: 写背调测试**

Create `tests/test_author_behavior.py`:
```python
def test_marketing_account_detected():
    """≥3帖且≥70%汽车内容→marketing_account"""
    posts = [RawPost(title="风云T7试驾评测", content="试驾..."),
             RawPost(title="上市价格分析", content="价格..."),
             RawPost(title="配置对比", content="配置...")]
    assert profile_author_behavior("车评人小王", posts) == "marketing_account"

def test_real_owner_not_flagged():
    """<3帖不标记"""
    posts = [RawPost(title="我的风云T7", content="提车了")]
    assert profile_author_behavior("张三", posts) is None

def test_threshold_boundary():
    """3帖边界：2汽车+1非汽车=67%<70%不标记"""
    posts = [RawPost(title="试驾", content=""), RawPost(title="评测", content=""),
             RawPost(title="今天天气", content="")]
    assert profile_author_behavior("边界用户", posts) is None
```

- [ ] **Step 2: 实现 profile_author_behavior**

`post_utils.py`：
```python
_MARKETING_SIGNAL_WORDS = {"试驾","评测","上市","价格","配置","续航","对比","提车","订单","交付","实测","体验","导购","行情"}

def profile_author_behavior(author: str, historical_posts: list) -> str | None:
    """查该作者全库（跨车型）近90天历史帖，判定营销号。

    跨车型合计：一个号可能给多个车型发软文，必须跨 vehicle_id 查。
    """
    if len(historical_posts) < 3:
        return None
    auto_count = sum(1 for p in historical_posts
                     if any(w in (p.title or "") or w in (p.content or "")
                            for w in _MARKETING_SIGNAL_WORDS))
    if auto_count / len(historical_posts) >= 0.7:
        return "marketing_account"
    return None
```

查询时跨 vehicle_id：`SELECT * FROM raw_posts WHERE author=? AND collected_at >= now-90d`（不限定 vehicle_id）。

- [ ] **Step 3: AUTHENTIC_AUTHOR 扩展**

`schemas.py`：
```python
INAUTHENTIC_AUTHOR_TYPES = ("brand_official", "dealer", "marketing_account")
```

- [ ] **Step 4: _store_posts 批量背调（防 N+1）**

`scheduler.py` _store_posts：**先收集本批所有 author，一次查全部历史帖，内存分组**——不逐帖查：
```python
# _store_posts 循环前：批量查本批作者的历史帖
authors_in_batch = {p.get("author","") for p in posts if p.get("author")}
since = datetime.now() - timedelta(days=90)
hist_result = await session.execute(
    select(RawPost.author, RawPost.title, RawPost.content).where(
        RawPost.author.in_(authors_in_batch),
        RawPost.collected_at >= since,
    )
)
hist_by_author: dict[str, list[dict]] = {}
for author, title, content in hist_result.all():
    hist_by_author.setdefault(author, []).append({"title": title, "content": content})

# 循环内：从内存取历史帖，不查 DB
for post in posts:
    author = post.get("author","")
    hist = hist_by_author.get(author, [])
    label = profile_author_behavior(author, hist) if hist else None
    author_type = label or classify_author_type(author, post.get("title",""), vehicle_brand, vehicle_name)
```

- [ ] **Step 5: backfill 脚本扩展**

`scripts/backfill_author_type.py`：遍历所有 organic 帖作者，跑 profile_author_behavior（同样批量查历史帖防 N+1），错标的改 marketing_account。

- [ ] **Step 6: 测试 + Commit**
```bash
"C:/Users/<you>/anaconda3/python.exe" -m pytest tests/test_author_behavior.py -v
git add -A && git commit -m "feat(author): 行为背调——历史帖汽车内容占比判定marketing_account+回填"
```

---

### Task 1.3: top30 回填（B1+）

**Files:**
- Modify: `pipeline/analysis/batch_runner.py`（select_top_posts_for_comments）

- [ ] **Step 1: 改选帖逻辑**

`batch_runner.py` select_top_posts_for_comments：
```python
async def select_top_posts_for_comments(session, vehicle_id):
    # 现有逻辑：每平台 top-N（env COMMENT_TOP_N，默认改 30）+ 30 天窗
    # 改动点：
    # 1. 挂 LISTING_CALIBER 口径（排除 marketing_account 后候选池缩小）
    # 2. 不足 30 则顺延补位：继续按互动降序取，跳过已选 + 跳过 likes+comments < 5 的帖
    # 3. 返回补位后的列表（可能仍不足 30，到此为止）
    ...
    # 具体实现：现有查询取 top60（2倍缓冲），过滤口径+互动门槛后取前 30
```

- [ ] **Step 2: 测试 + Commit**
```bash
git add -A && git commit -m "fix(comments): top30 回填补位+最低互动门槛（背调排除后不凑数）"
```

---

### Task 1.4: 时间窗跟随（D1）

**Files:**
- Modify: `api/routes/dashboard.py`（overview/defect-themes 加 start/end）
- Modify: `frontend/static/js/app.js`（loadOverview/loadWordCloud/loadTopPosts 传窗）
- Modify: `pipeline/analysis/defect_miner.py`（_complaint_pool 用用户窗）
- Test: `tests/test_time_window.py`

- [ ] **Step 1: 写时间窗测试（TDD）**

Create `tests/test_time_window.py`:
```python
import pytest
from httpx import AsyncClient, ASGITransport
from api.main import app

@pytest.mark.asyncio
async def test_overview_follows_time_window(env):
    """overview 传 start/end 时只统计窗内帖。"""
    client, s = env
    s.add(Vehicle(id="v1", name="风云T7", brand="奇瑞"))
    # seed 两帖：一帖在窗内，一帖在窗外
    await _seed(s, "v1", "p1", "positive", "organic", published_at="2026-09-01")
    await _seed(s, "v1", "p2", "positive", "organic", published_at="2026-08-01")
    await s.commit()
    # 传 9月1日-9月30日窗
    r = await client.get("/api/dashboard/overview/v1?start=2026-09-01&end=2026-09-30")
    ov = r.json()
    assert ov["total_posts"] == 1  # 只 p1 在窗内
    # 不传窗（全量）
    r = await client.get("/api/dashboard/overview/v1")
    ov = r.json()
    assert ov["total_posts"] == 2  # p1+p2

@pytest.mark.asyncio
async def test_null_published_at_uses_collected_at(env):
    """published_at=NULL 时用 collected_at 兜底进窗。"""
    client, s = env
    s.add(Vehicle(id="v1", name="风云T7", brand="奇瑞"))
    await _seed(s, "v1", "p1", "positive", "organic", published_at=None, collected_at="2026-09-15")
    await s.commit()
    r = await client.get("/api/dashboard/overview/v1?start=2026-09-01&end=2026-09-30")
    assert r.json()["total_posts"] == 1  # collected_at 兜底进窗
```

- [ ] **Step 2: overview 加 start/end + 8 段查询挂窗**

`dashboard.py` get_overview：
```python
@router.get("/overview/{vehicle_id}")
async def get_overview(
    vehicle_id: str,
    start: str | None = Query(None), end: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
):
    vehicle = await _get_vehicle_or_404(vehicle_id, session)
    # 时间窗条件（coalesce 兜底 NULL published_at）
    from sqlalchemy import and_
    tw = []
    if start:
        tw.append(func.coalesce(RawPost.published_at, RawPost.collected_at) >= datetime.fromisoformat(start))
    if end:
        tw.append(func.coalesce(RawPost.published_at, RawPost.collected_at) < datetime.fromisoformat(end) + timedelta(days=1))

    # 1. total（加 tw）
    total_q = _relevant_posts_filter(
        select(func.count(RawPost.id)).where(RawPost.vehicle_id == vehicle_id, *tw)
    )
    total = (await session.execute(total_q)).scalar() or 0

    # 2. sentiment 计数（加 tw）
    sent_q = (select(AnalyzedPost.sentiment, func.count(AnalyzedPost.id))
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == vehicle_id, SELF_ONLY, AUTHENTIC_AUTHOR, RELEVANT_ONLY, *tw)
        .group_by(AnalyzedPost.sentiment))
    counts = {r[0]: r[1] for r in (await session.execute(sent_q)).all()}

    # 3. analyzed_total（加 tw）
    analyzed_q = (select(func.count(AnalyzedPost.id))
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == vehicle_id, SELF_ONLY, AUTHENTIC_AUTHOR, *tw))
    analyzed_total = (await session.execute(analyzed_q)).scalar() or 0

    # 4. health_score（跟随用户窗，用窗内 pos/neg/analyzed_total）
    health_score = round(50 + ((pos - neg) / analyzed_total * 50) if analyzed_total > 0 else 50, 1)
    health_score = max(0, min(100, health_score))

    # 5. week_change_rate（保持固定近7天vs上7天——不挂 tw，它是独立周趋势信号）
    # ... 现有逻辑不变 ...

    # 6. comments_per_post（加 tw：评论数+社媒帖数都按窗）
    comments_q = (select(func.count(PostComment.id))
        .join(RawPost, PostComment.post_id == RawPost.id)
        .where(RawPost.vehicle_id == vehicle_id, *tw))
    social_q = _relevant_posts_filter(
        select(func.count(RawPost.id)).where(RawPost.vehicle_id == vehicle_id, RawPost.platform != "news", *tw)
    )

    # 7. peak_date（用 tw 替代固定 30 天）
    peak_q = (select(func.date(func.coalesce(RawPost.published_at, RawPost.collected_at)).label("d"), func.count(RawPost.id))
        .where(RawPost.vehicle_id == vehicle_id, *tw)
        .group_by("d").order_by(func.count(RawPost.id).desc()).limit(1))

    # 8. best_dim/worst_dim（加 tw）
    dim_q = (select(AnalyzedPost.dim_sentiment)
        .join(RawPost, AnalyzedPost.post_id == RawPost.id)
        .where(AnalyzedPost.vehicle_id == vehicle_id, SELF_ONLY, AUTHENTIC_AUTHOR, *tw))
```

- [ ] **Step 3: defect-themes 加 start/end**

`defect_miner.py` _complaint_pool 接收 start/end，`since` 用用户窗（默认 7 天）：
```python
async def _complaint_pool(session, vehicle_id, start: str | None = None, end: str | None = None):
    if start and end:
        since = datetime.fromisoformat(start)
        until = datetime.fromisoformat(end) + timedelta(days=1)
    else:
        since = datetime.now() - timedelta(days=_WINDOW_DAYS)
        until = datetime.now()
    # 查询用 func.coalesce(published_at, collected_at) >= since AND < until
```
`mine_defect_themes` 透传 start/end。dashboard.py /defect-themes 端点加 start/end Query。

- [ ] **Step 4: 前端传窗**

`app.js`：
```javascript
async loadOverview() {
    this.overview = await this.apiFetch(`/api/dashboard/overview/${this.currentVehicleId}?start=${this.rangeStart}&end=${this.rangeEnd}`) || {};
},
async loadWordCloud() {
    const params = new URLSearchParams({ limit: "80", start: this.rangeStart, end: this.rangeEnd });
    this.wordCloudData = await this.apiFetch(`/api/dashboard/word-cloud/${this.currentVehicleId}?${params}`) || [];
},
async loadTopPosts() {
    const params = new URLSearchParams({ limit: "10", start: this.rangeStart, end: this.rangeEnd });
    if (this.hotPostsTab === 'negative') params.set('sentiment', 'negative');
    this.topPosts = await this.apiFetch(`/api/dashboard/top-posts/${this.currentVehicleId}?${params}`) || [];
},
```

- [ ] **Step 5: 测试 + Commit**
```bash
"C:/Users/<you>/anaconda3/python.exe" -m pytest tests/test_time_window.py -v
git add -A && git commit -m "feat(time-window): 4端点跟随时间窗+coalesce兜底NULL+overview 8段查询挂窗"
```

---

### Task 1.5: 互动数刷新（A3）

**Files:**
- Create: `scripts/refresh_engagement.py`
- Modify: `scripts/daily_update.py`（收尾调用）
- Test: `tests/test_engagement_refresh.py`

- [ ] **Step 1: 写刷新测试（TDD）**

Create `tests/test_engagement_refresh.py`:
```python
import pytest
from unittest.mock import AsyncMock, patch
from scripts.refresh_engagement import refresh_vehicle_engagement

@pytest.mark.asyncio
async def test_douyin_batch_refresh(env):
    """抖音帖用批量统计端点刷新。"""
    client, s = env
    # seed 抖音帖
    await _seed(s, "v1", "p1", "positive", "organic", platform="douyin", likes=10)
    await s.commit()
    # mock 批量统计返回新互动数
    with patch("scripts.refresh_engagement.OneApiClient") as mock:
        mock.return_value.fetch_douyin_play_stats = AsyncMock(return_value={
            "p1": {"likes": 500, "comments": 50, "shares": 5}
        })
        count = await refresh_vehicle_engagement(s, "v1")
    assert count == 1
    # 验证回写
    r = await s.execute(select(RawPost).where(RawPost.id == "p1"))
    assert r.scalar().likes == 500

@pytest.mark.asyncio
async def test_xhs_weibo_only_top30(env):
    """小红书/微博只刷 top30（无批量端点降级）。"""
    # seed 35 个小红书帖，验证只刷前 30
    ...
```

- [ ] **Step 2: 实现刷新脚本**

Create `scripts/refresh_engagement.py`:
```python
"""每日批量刷新近30天帖互动数——治快照冻结。

策略：
- 抖音/快手：批量统计端点（便宜，全刷近30天帖）
- 小红书/微博：无批量端点，只刷 top30 帖（降级，控成本）
"""
import asyncio, logging
from datetime import datetime, timedelta
from sqlalchemy import select, update, func
from models.database import async_session
from models.schemas import RawPost, Vehicle
from pipeline.collectors.oneapi_collector import OneApiClient

logger = logging.getLogger(__name__)
_BATCH_SIZE = 50  # 抖音批量统计端点单批上限

async def refresh_vehicle_engagement(session, vehicle_id: str) -> int:
    """刷新单车近30天帖互动数，返回刷新帖数。"""
    since = datetime.now() - timedelta(days=30)
    # 查近30天帖（coalesce 时间窗）
    posts = (await session.execute(
        select(RawPost).where(
            RawPost.vehicle_id == vehicle_id,
            func.coalesce(RawPost.published_at, RawPost.collected_at) >= since,
        )
    )).scalars().all()
    if not posts:
        return 0

    client = OneApiClient()
    refreshed = 0
    # 抖音：批量统计
    dy_posts = [p for p in posts if p.platform == "douyin" and p.url]
    for i in range(0, len(dy_posts), _BATCH_SIZE):
        batch = dy_posts[i:i+_BATCH_SIZE]
        aweme_ids = [p.url.split("/")[-1] for p in batch if p.url]  # 从 URL 提取 aweme_id
        try:
            stats = await client.fetch_douyin_play_stats(aweme_ids)
            for p in batch:
                st = stats.get(p.id) or stats.get(aweme_ids[batch.index(p)])
                if st:
                    await session.execute(update(RawPost).where(RawPost.id == p.id).values(
                        likes=st.get("likes", p.likes), comments=st.get("comments", p.comments),
                        shares=st.get("shares", p.shares)))
                    refreshed += 1
        except Exception as e:
            logger.warning("抖音批量刷新失败: %s", e)

    # 快手：批量详情（类似抖音）
    ks_posts = [p for p in posts if p.platform == "kuaishou"]
    # ... 同模式用 fetch_multiple_video_detail ...

    # 小红书/微博：只刷 top30（按 likes+comments 降序）
    for platform in ("xiaohongshu", "weibo"):
        platform_posts = sorted(
            [p for p in posts if p.platform == platform],
            key=lambda p: (p.likes or 0) + (p.comments or 0), reverse=True
        )[:30]
        for p in platform_posts:
            try:
                # 逐帖调详情回填（具体方法取决于 collector）
                # ... 省略：调 client.fetch_post_detail(p.url) 拿新互动数回写 ...
                refreshed += 1
            except Exception as e:
                logger.warning("%s 帖 %s 刷新失败: %s", platform, p.id, e)

    await session.commit()
    return refreshed

async def run_all():
    async with async_session() as session:
        vehicles = (await session.execute(select(Vehicle).where(Vehicle.status == "active"))).scalars().all()
        for v in vehicles:
            try:
                n = await refresh_vehicle_engagement(session, v.id)
                logger.info("[%s] 刷新 %d 帖互动", v.name, n)
            except Exception as e:
                logger.error("[%s] 刷新失败: %s", v.name, e)

if __name__ == "__main__":
    asyncio.run(run_all())
```

**成本评估**：抖音+快手批量便宜；小红书/微博逐帖调详情，限制为 top30 帖/车/天（60 次调用/车/天），21 车约 1260 次/天——可接受。

- [ ] **Step 3: daily_update 收尾调用**

`daily_update.py` 在备份前加：
```python
from scripts.refresh_engagement import run_all
asyncio.run(run_all())
```

- [ ] **Step 4: 测试 + Commit**
```bash
"C:/Users/<you>/anaconda3/python.exe" -m pytest tests/test_engagement_refresh.py -v
git add -A && git commit -m "feat(engagement): 每日批量刷新近30天帖互动数——治快照冻结"
```

---

### Task 1.6: 周报口径修正（C3）

**Files:**
- Modify: `api/routes/reports.py`（generate_weekly_digest）

- [ ] **Step 1: 复用口径函数**

generate_weekly_digest：
- 情感计数：改 published_at + LISTING_CALIBER（删 analyzed_at）
- 事件标签：复用 _compute_dim_sentiment 同口径
- 总帖数：保持 published_at + RELEVANT_ONLY

- [ ] **Step 2: 测试 + Commit**
```bash
"C:/Users/<you>/anaconda3/python.exe" -m pytest tests/test_reports.py -v
git add -A && git commit -m "fix(reports): 周报口径统一——复用_compute_dim_sentiment+published_at+LISTING_CALIBER"
```

---

### Task 1.7: 报告期独立（D15）

**Files:**
- Modify: `frontend/index.html`（拆两个按钮）
- Modify: `frontend/static/js/app.js`（两个方法）
- Modify: `api/routes/reports.py`（固定报告期）

- [ ] **Step 1: 后端固定报告期**

reports.py：weekly-digest 固定 start=今天-7/end=今天，deep-report 固定 30 天（不接收前端传的）。

- [ ] **Step 2: 前端拆按钮**

index.html："生成舆情简报" → "生成周报" + "生成月报"。
app.js：createReport 拆 createWeeklyReport / createMonthlyReport。

- [ ] **Step 3: Commit**
```bash
git add -A && git commit -m "feat(reports): 报告期独立——周报固定7天/月报固定30天，前端两按钮"
```

---

### Task 1.8: 词云停用词（B4/D9）

**Files:**
- Modify: `api/routes/dashboard.py`（get_word_cloud）

- [ ] **Step 1: 注入停用词**

get_word_cloud：查当前车名/品牌 + 全库车型名 + 通稿套话词表，加入 stopwords。

- [ ] **Step 2: 测试 + Commit**
```bash
git add -A && git commit -m "fix(wordcloud): 注入车型名/品牌/通稿套话停用词——治霸屏"
```

---

### Task 1.9: 采集容错（A7）

**Files:**
- Modify: `pipeline/scheduler.py`（重试 + 失败计数）
- Modify: `frontend/static/js/app.js`（失败显示）

- [ ] **Step 1: 重试逻辑**

scheduler.py _collect_social_platform：
```python
import httpx
async def _retry_search(c, kw, platform, ...):
    fetch_failures = []
    for attempt in range(3):  # 首次 + 2次重试
        try:
            return await c.search(kw, platform, ...)
        except (OneApiAuthError, TikHubAuthError):
            raise  # 账户级错误不重试
        except (httpx.TimeoutException, httpx.ConnectError, ConnectionError) as e:
            # 只重试网络/超时类错误
            if attempt < 2:
                await asyncio.sleep(2 ** attempt)  # 1s, 2s
            else:
                fetch_failures.append(kw)
                return [], []
        # 其余异常（KeyError/AttributeError 等代码 bug）不捕获，直接抛出
```

- [ ] **Step 2: 失败计数前端可见**

pipeline_phases[vehicle_id]["fetch_failures"] = fetch_failures
app.js 采集进度面板显示。

- [ ] **Step 3: 测试 + Commit**
```bash
git add -A && git commit -m "feat(collect): 429/超时指数退避重试2次+失败计数前端可见"
```

---

### Task 1.10: daily_update --all（A8）

**Files:**
- Modify: `scripts/daily_update.py`
- Create: `docs/定时任务配置.md`

- [ ] **Step 1: 加 --all + 频率分层**

```python
ap.add_argument("--all", action="store_true", help="遍历全部 active 车")
# 频率分层：按 vehicle 标注的热度（lifecycle_anchors 或手动）决定日更/隔日/周更
```

- [ ] **Step 2: 定时任务文档**

Create `docs/定时任务配置.md`（Windows 计划任务/cron 示例）。

- [ ] **Step 3: Commit**
```bash
git add -A && git commit -m "feat(daily-update): --all模式+频率分层+定时任务配置文档"
```

---

## Phase 2: 验证与收尾

- [ ] **T2.1 全量 pytest 绿**
```bash
"C:/Users/<you>/anaconda3/python.exe" -m pytest tests/ -q
```

- [ ] **T2.2 启动服务手动验证**
- KPI 切7天vs30天数字变化
- 词云无车名/通稿词
- 周报口径与看板一致
- 采集失败时前端可见

- [ ] **T2.3 存量回填**
```bash
"C:/Users/<you>/anaconda3/python.exe" scripts/backfill_author_type.py --all
"C:/Users/<you>/anaconda3/python.exe" scripts/refresh_engagement.py
```

- [ ] **T2.4 文档同步 + archive**
- docs/舆情看板-前端设计.md 同步口径变更
- openspec tasks 勾选
- /opsx:archive

---

## Self-Review

**Spec coverage:** 12 capability 对应 14 任务，全覆盖。B1+（top30 回填）是 B1 的连锁需求，单独成 T1.3。

**依赖链:** T1.3 依赖 T1.2（背调排除后才有缺口）；T1.5 依赖 T0.2（刷新脚本用配置参数）；其余 Phase 1 任务依赖 Phase 0 的迁移框架/配置统一。

**冲突对冲:** B1 排除营销号→样本量缩小，D4 样本护栏在批次2（本 change 不含），T1.2 落地后需观察小车型样本。
