"""Prism Dashboards · 自包含只读看板子服务（口碑 / 配置 / 市场）。

由 Atuohome_Agent 的三个看板迁移而来（模板 + 路由 + 数据层 + 本地 SQLite）：
- 路由前缀统一为 /dash（避免与 prism-api 的 /dashboard、Prism 前端的 /static 冲突）
- 静态资源挂在 /dash/static（模板内的绝对路径已同步改写）
- 默认监听 127.0.0.1:8010，由 prism-api 反代 /dash/* → 本服务，供 prism-web iframe 嵌入
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# 与本服务同目录的 .env（迁移自 Atuohome_Agent，含 LLM key / 搜索 key）
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=True)
except ImportError:
    pass

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 初始化本地 SQLite（默认 <本目录>/data/autohome.db，由 src/storage/db.py 计算）
from src.storage.db import init_db

app = FastAPI(title="Prism Dashboards", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

from src.api.dashboard_routes import router as dashboard_router
from src.api.market_routes import router as market_router

app.include_router(dashboard_router)
app.include_router(market_router)

_static_dir = ROOT / "src" / "web" / "static"
if _static_dir.exists():
    app.mount("/dash/static", StaticFiles(directory=str(_static_dir)), name="dash-static")


@app.get("/health")
def health():
    return {"status": "ok", "service": "prism-dashboards"}


if __name__ == "__main__":
    # 容器内需绑 0.0.0.0 才能被同网络访问；默认仍 127.0.0.1，本机启动行为不变
    uvicorn.run(app, host=os.environ.get("DASH_HOST", "127.0.0.1"), port=int(os.environ.get("DASH_PORT", "8010")))
