# Phase 1 实施计划：数据底座

基于 OpenSpec tasks.md T1.1-T1.8，拆解为可执行的原子任务。

---

## T1.1 初始化项目结构

### T1.1.1 Git 初始化
- **文件**: 项目根目录
- **操作**: `git init` → `.gitignore` 已创建 → `git add .` → `git commit -m "init: save old code snapshot"`
- **验证**: `git log` 显示一条 commit

### T1.1.2 清理旧代码目录
- **操作**: 删除 `graph/`、`agent/`（旧）、`crawler/`、`collectors/`、`static/`、`logs/`、`report_templates/`、`docs/superpowers/`
- **保留**: `openspec/`、`docs/brainstorming-design.md`、`.gitignore`、`.secrets`、`requirements.txt`、`db/`
- **验证**: `ls` 根目录只剩保留的文件/目录

### T1.1.3 创建新目录结构
- **文件**: 根目录下新建
```
pipeline/
├── __init__.py
├── collectors/
│   ├── __init__.py
│   ├── gopup_collector.py
│   ├── media_crawler.py
│   └── news_collector.py
├── analyzers/
│   ├── __init__.py
│   └── sentiment_analyzer.py
├── scheduler.py
└── models.py
agent/
├── __init__.py
├── research.py
└── dialog.py
api/
├── __init__.py
├── main.py
├── routes/
│   ├── __init__.py
│   ├── dashboard.py
│   ├── dialog.py
│   ├── report.py
│   └── vehicle.py
models/
├── __init__.py
├── schemas.py
└── database.py
frontend/
├── index.html
├── app.js
├── components/
│   └── .gitkeep
└── static/
    ├── css/
    │   └── style.css
    └── js/
        └── .gitkeep
```
- **验证**: 所有 `__init__.py` 文件存在

### T1.1.4 更新 requirements.txt
- **文件**: `requirements.txt`
- **内容**:
```
fastapi>=0.115.0
uvicorn>=0.30.0
sqlalchemy>=2.0.0
aiosqlite>=0.20.0
httpx>=0.27.0
pydantic>=2.0.0
langgraph>=0.2.0
langchain-core>=0.3.0
gopup>=0.3.0
playwright>=1.40.0
sse-starlette>=2.0.0
python-dotenv>=1.0.0
```
- **验证**: `pip install -r requirements.txt` 成功

### T1.1.5 创建 FastAPI 入口
- **文件**: `api/main.py`
- **内容**: 最小 FastAPI app，挂载路由，lifespan 管理 DB 连接
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化数据库
    from models.database import init_db
    await init_db()
    yield

app = FastAPI(title="Vehicle Sentiment Agent", lifespan=lifespan)

# 挂载前端
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

@app.get("/")
async def index():
    return FileResponse("frontend/index.html")
```
- **验证**: `uvicorn api.main:app --reload` 启动成功，访问 `http://localhost:8000` 返回页面

### T1.1.6 创建前端最小页面
- **文件**: `frontend/index.html`
- **内容**: HTML 骨架，引入 Vue 3 CDN + ECharts CDN
```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>车型舆情监控</title>
    <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <div id="app">
        <h1>车型舆情监控</h1>
        <p>系统加载中...</p>
    </div>
    <script type="module" src="/frontend/app.js"></script>
</body>
</html>
```
- **文件**: `frontend/app.js`
- **内容**:
```javascript
const { createApp } = Vue;
createApp({
    data() { return { message: '系统已就绪' }; }
}).mount('#app');
```
- **验证**: 浏览器访问 `http://localhost:8000` 显示"系统已就绪"

### T1.1.7 Commit 项目结构
- **操作**: `git add .` → `git commit -m "feat: init project structure with FastAPI + Vue 3"`
- **验证**: `git log` 显示新 commit

---

## T1.2 数据库 Schema

### T1.2.1 数据库连接管理
- **文件**: `models/database.py`
- **内容**: SQLAlchemy async engine + session factory + init_db()
```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
import os

DB_PATH = os.getenv("DB_PATH", "data/vehicle_sentiment.db")
engine = create_async_engine(f"sqlite+aiosqlite:///{DB_PATH}", echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
```
- **验证**: `python -c "import asyncio; from models.database import init_db; asyncio.run(init_db())"` 无报错，`data/vehicle_sentiment.db` 文件生成

### T1.2.2 ORM 模型 - vehicles 表
- **文件**: `models/schemas.py`
- **内容**: Vehicle SQLAlchemy model + Pydantic schema
```python
from sqlalchemy import Column, String, Text, DateTime, Integer, Float, Boolean, Date
from sqlalchemy.sql import func
from models.database import Base
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class Vehicle(Base):
    __tablename__ = "vehicles"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    brand = Column(String, nullable=False)
    search_keywords = Column(Text)        # JSON array
    lifecycle_anchors = Column(Text)      # JSON
    competitor_ids = Column(Text)         # JSON array
    status = Column(String, default="active")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

class VehicleCreate(BaseModel):
    name: str
    brand: str
    search_keywords: Optional[list[str]] = None
    lifecycle_anchors: Optional[dict] = None
    competitor_ids: Optional[list[str]] = None

class VehicleResponse(BaseModel):
    id: str
    name: str
    brand: str
    search_keywords: Optional[list[str]]
    lifecycle_anchors: Optional[dict]
    competitor_ids: Optional[list[str]]
    status: str
    created_at: datetime
    updated_at: datetime
```
- **验证**: import 无报错

### T1.2.3 ORM 模型 - 其余所有表
- **文件**: `models/schemas.py`（追加）
- **内容**: CollectionStatus, RawPost, AnalyzedPost, HeatMetric, AnomalyEvent, Report, DialogConversation, DialogMessage
- 按 `specs/database-schema/spec.md` 中的 SQL 定义逐一转为 SQLAlchemy model
- **验证**: `init_db()` 后用 SQLite 工具查看所有表已创建

### T1.2.4 数据库初始化脚本
- **文件**: `models/init_db.py`
- **内容**: 独立脚本，可直接运行创建所有表
```python
import asyncio
from models.database import init_db

async def main():
    await init_db()
    print("Database initialized successfully.")

if __name__ == "__main__":
    asyncio.run(main())
```
- **验证**: `python -m models.init_db` 成功，`sqlite3 data/vehicle_sentiment.db ".tables"` 显示所有表
- **Commit**: `git commit -m "feat: database schema with all tables"`

---

## T1.3 车型管理模块

### T1.3.1 车型 CRUD API
- **文件**: `api/routes/vehicle.py`
- **内容**: FastAPI router，实现 POST/GET/PUT/DELETE + 搜索
- 端点：
  - `POST /api/vehicles` — 添加车型
  - `GET /api/vehicles` — 车型列表
  - `GET /api/vehicles/{id}` — 车型详情
  - `PUT /api/vehicles/{id}` — 更新车型
  - `DELETE /api/vehicles/{id}` — 删除车型
  - `GET /api/vehicles/search?q=keyword` — 搜索车型
  - `PUT /api/vehicles/{id}/lifecycle` — 更新生命周期
  - `PUT /api/vehicles/{id}/competitors` — 更新竞品
- **验证**: Swagger UI (`http://localhost:8000/docs`) 显示所有端点

### T1.3.2 车型管理注册到主应用
- **文件**: `api/main.py`（修改）
- **内容**: `app.include_router(vehicle_router, prefix="/api")`
- **验证**: curl POST 创建车型成功，GET 返回列表

### T1.3.3 车型管理测试
- **文件**: `tests/test_vehicle_api.py`
- **内容**: pytest + httpx AsyncClient，测试 CRUD 全流程
- **验证**: `pytest tests/test_vehicle_api.py` 全部通过
- **Commit**: `git commit -m "feat: vehicle management CRUD API with tests"`

---

## T1.4 数据采集引擎 - gopup

### T1.4.1 gopup 百度指数采集器
- **文件**: `pipeline/collectors/gopup_collector.py`
- **内容**:
  - `GopupCollector` 类，async 方法
  - `collect_baidu_index(keyword, start_date, end_date)` → 返回日级指数数据
  - `collect_weibo_index(keyword, start_date, end_date)`
  - Cookie 通过 Playwright 自动获取（调用 T1.4.2）

### T1.4.2 Playwright 自动登录获取 Cookie
- **文件**: `pipeline/collectors/cookie_manager.py`
- **内容**:
  - `CookieManager` 类
  - `get_baidu_cookie()` → Playwright 自动登录百度，返回 Cookie
  - Cookie 缓存到本地文件，有效期 7 天
  - 从 `.secrets` 读取账号密码
  - 登录失败 fallback 到手动模式
  - 登录频率控制（24h 最多 3 次）

### T1.4.3 gopup 采集器测试
- **文件**: `tests/test_gopup_collector.py`
- **内容**: mock gopup API，测试日期范围分批、Cookie 获取流程
- **验证**: `pytest tests/test_gopup_collector.py` 通过
- **Commit**: `git commit -m "feat: gopup collector with Playwright cookie manager"`

---

## T1.5 数据采集引擎 - MediaCrawler

### T1.5.1 MediaCrawler 集成封装
- **文件**: `pipeline/collectors/media_crawler.py`
- **内容**:
  - `MediaCrawlerWrapper` 类
  - `search(keyword, platform, max_pages)` → 搜索帖子
  - 支持：小红书/B站/知乎/微博/抖音
  - 封装 MediaCrawler 的调用和结果解析

### T1.5.2 MediaCrawler 测试
- **文件**: `tests/test_media_crawler.py`
- **内容**: mock MediaCrawler API，测试搜索和结果解析
- **验证**: `pytest tests/test_media_crawler.py` 通过
- **Commit**: `git commit -m "feat: MediaCrawler integration wrapper"`

---

## T1.6 数据采集引擎 - 新闻源

### T1.6.1 新闻搜索采集器
- **文件**: `pipeline/collectors/news_collector.py`
- **内容**:
  - `NewsCollector` 类，async 方法
  - `search_tavily(keyword, start_date, end_date)` → Tavily 新闻搜索
  - `search_bocha(keyword, start_date, end_date)` → Bocha 新闻搜索
  - `search_anspire(keyword, start_date, end_date)` → Anspire 新闻搜索
  - 三个源并行搜索（asyncio.gather），结果去重

### T1.6.2 新闻采集器测试
- **文件**: `tests/test_news_collector.py`
- **内容**: mock 三个新闻 API，测试并行搜索和去重逻辑
- **验证**: `pytest tests/test_news_collector.py` 通过
- **Commit**: `git commit -m "feat: news collector with Tavily/Bocha/Anspire"`

---

## T1.7 采集调度器

### T1.7.1 采集调度器核心
- **文件**: `pipeline/scheduler.py`
- **内容**:
  - `CollectionScheduler` 类
  - `collect(vehicle_config)` → 判断 initial/incremental → 调度各采集器 → 写入 raw_posts → 更新 collection_status
  - 首次采集：按月分 3 批（asyncio.gather 并行）
  - 增量采集：只拉 last_collected_at 之后的数据
  - 单源失败不阻塞，记录错误

### T1.7.2 采集调度器测试
- **文件**: `tests/test_scheduler.py`
- **内容**: mock 各采集器，测试首次/增量/失败场景
- **验证**: `pytest tests/test_scheduler.py` 通过
- **Commit**: `git commit -m "feat: collection scheduler with initial/incremental modes"`

---

## T1.8 采集触发

### T1.8.1 采集触发 API
- **文件**: `api/routes/vehicle.py`（追加端点）
- **内容**:
  - `POST /api/vehicles/{id}/collect` — 手动触发采集
  - 车型创建时自动触发首次采集（异步后台任务）
- **验证**: curl 触发采集，查看 collection_status 表状态变化

### T1.8.2 采集状态查询 API
- **文件**: `api/routes/vehicle.py`（追加端点）
- **内容**:
  - `GET /api/vehicles/{id}/collection-status` — 查询采集状态
  - 返回各数据源的采集进度、帖子数、最后采集时间
- **验证**: curl 查询返回 JSON 格式的采集状态

### T1.8.3 端到端测试
- **文件**: `tests/test_collection_e2e.py`
- **内容**: 创建车型 → 触发采集（mock 采集器）→ 查询状态 → 验证 raw_posts 有数据
- **验证**: `pytest tests/test_collection_e2e.py` 通过
- **Commit**: `git commit -m "feat: collection trigger API with e2e tests"`

---

## 任务依赖图

```
T1.1.1 → T1.1.2 → T1.1.3 → T1.1.4 → T1.1.5 → T1.1.6 → T1.1.7
                                    ↘
T1.2.1 → T1.2.2 → T1.2.3 → T1.2.4
                                    ↘
T1.3.1 → T1.3.2 → T1.3.3
                          ↘
T1.4.1 → T1.4.2 → T1.4.3  ┐
T1.5.1 → T1.5.2             ├→ T1.7.1 → T1.7.2 → T1.8.1 → T1.8.2 → T1.8.3
T1.6.1 → T1.6.2            ┘
```

**Phase 1 预计 26 个原子任务，4 个主要 commit。**
