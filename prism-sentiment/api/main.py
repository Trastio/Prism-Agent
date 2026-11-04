import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse

# 应用日志可见化（remove-oneapi T2.2 根因之一）：uvicorn 默认只配置自身三个
# logger（uvicorn/uvicorn.error/uvicorn.access），root 无 handler 且 level=
# WARNING——应用代码全部 logger.info（采集/分析/Phase 进度）在服务控制台被
# 静默丢弃，实采"0 条 defect 日志"里既看不到 Phase 9 执行、也看不到任何
# INFO 证据。uvicorn 的 dictConfig 先于 app import 执行且不动 root，此处
# basicConfig 生效且不冲突；LOG_LEVEL 可覆盖（如生产要安静设 WARNING）。
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from api.routes.vehicle import router as vehicle_router
from api.routes.collection import router as collection_router
from api.routes.analysis import router as analysis_router
from api.routes.dashboard import router as dashboard_router
from api.routes.reports import router as reports_router
from api.routes.watchlist import router as watchlist_router
from api.routes.fleet import router as fleet_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    from models.database import init_db  # noqa: inline-import
    await init_db()
    # 预热汽车之家车系索引（加车型 suggest 用；启动时建一次常驻内存，避免首次输入卡 2s+）
    try:
        from utils.autohome_api import get_autohome_api  # noqa: inline-import
        api = await get_autohome_api()
        idx = await api.build_series_index()
        print(f"[lifespan] 车系索引预热完成: {len(idx)} 车系", flush=True)
    except Exception as e:
        print(f"[lifespan] 车系索引预热失败: {e}", flush=True)
    yield


app = FastAPI(title="Vehicle Sentiment Agent", lifespan=lifespan)

app.include_router(vehicle_router)
app.include_router(collection_router)
app.include_router(analysis_router)
app.include_router(dashboard_router)
app.include_router(reports_router)
app.include_router(watchlist_router)
app.include_router(fleet_router)

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")


# ── cache-bust 自动化（2026-10-08）─────────────────────────────────────
# 静态资源版本号 = 文件 mtime，服务 / 时动态重写 index.html 里的 ?v=N。
# 文件一保存 mtime 变 → URL 变 → 浏览器强制重下；没变 → 缓存照常生效。
# 根治"忘 bump v"（10-07 诊断：v40 滞留 10 个前端 commit，浏览器跑旧代码）。
# index.html 保持 no-store（每次拉新），里面的字面 ?v=N 只是兜底占位，
# 实际以下方服务端重写为准。
# 2026-10-08 迁移 Prism：index.html 内资源引用改为相对路径（static/...，供
# /sentiment-board/ 挂载下解析），故正则的 path 前导斜杠改为可选，两种写法都能
# 命中 mtime 重写；_asset_version 内 lstrip("/") 已兼容两种形式，其余逻辑不变。
_ASSET_VER_RE = re.compile(r'(?P<path>/?static/[\w./-]+\.(?:js|css))\?v=\d+')


def _asset_version(url_path: str) -> str | None:
    """资源 URL 路径 → mtime 版本号（int 秒）。

    路径含 ..（越界探测，输入源是开发者手写的 index.html，纯防御）或文件
    不存在 → None，标签原样保留。
    """
    if ".." in url_path:
        return None
    fs_path = Path("frontend") / url_path.lstrip("/")
    try:
        return str(int(fs_path.stat().st_mtime))
    except OSError:
        return None


@app.get("/")
async def index():
    # no-store: index.html must always be re-fetched so per-asset ?v= works.
    # 返回前把 /static/**.(js|css)?v=N 重写为文件 mtime 版本号；本地文件缺失
    # 或非 static 引用（CDN）原样保留，不影响渲染。
    html = Path("frontend/index.html").read_text(encoding="utf-8")

    def _sub(m: re.Match) -> str:
        ver = _asset_version(m.group("path"))
        return f"{m.group('path')}?v={ver}" if ver else m.group(0)

    return HTMLResponse(_ASSET_VER_RE.sub(_sub, html),
                        headers={"Cache-Control": "no-store"})


@app.get("/health")
async def health():
    """#32：健康检查端点——DB 连通 + 车系索引预热状态。"""
    from sqlalchemy import select, func  # noqa: inline-import
    from models.database import async_session  # noqa: inline-import
    from models.schemas import Vehicle  # noqa: inline-import
    try:
        async with async_session() as session:
            cnt = await session.scalar(select(func.count()).select_from(Vehicle))
        return {"status": "ok", "db": "ok", "vehicles": cnt or 0}
    except Exception as e:
        return {"status": "error", "db": str(e)[:200], "vehicles": 0}
