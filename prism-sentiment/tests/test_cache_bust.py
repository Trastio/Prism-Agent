"""cache-bust 自动化回归：/ 返回的 index.html 资源版本号 = 静态文件 mtime。

背景（2026-10-07 诊断）：?v= 靠人手 bump，v40 滞留 10 个前端 commit，
浏览器缓存旧 JS 表现为"跑旧代码"。自动化后版本号无人维护。
"""
import os
import re
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"

_ASSET_RE = re.compile(r'(?P<path>/static/[\w./-]+\.(?:js|css))\?v=(?P<ver>\d+)')


@pytest_asyncio.fixture
async def client():
    from api.main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_index_serves_mtime_versions(client):
    """/ 返回的每个 /static 资源 ?v= 都等于对应文件的 mtime（int 秒）。"""
    resp = await client.get("/")
    assert resp.status_code == 200
    matches = list(_ASSET_RE.finditer(resp.text))
    assert len(matches) >= 4, f"index.html 应至少 4 个带版本静态引用，实际 {len(matches)}"
    for m in matches:
        fs = FRONTEND / m.group("path").lstrip("/")
        assert fs.exists(), f"{m.group('path')} 应存在"
        assert m.group("ver") == str(int(fs.stat().st_mtime)), (
            f"{m.group('path')} 版本号应等于文件 mtime（自动化重写失效？）"
        )


async def test_version_changes_when_file_changes(client):
    """文件 mtime 变 → 下次 / 返回新版本号（"忘 bump"从机制上不可能）。"""
    resp1 = await client.get("/")
    ver1 = re.search(r'app\.js\?v=(\d+)', resp1.text).group(1)

    app_js = FRONTEND / "static" / "js" / "app.js"
    real_mtime = app_js.stat().st_mtime
    try:
        os.utime(app_js, (real_mtime + 5, real_mtime + 5))  # 模拟保存
        resp2 = await client.get("/")
        ver2 = re.search(r'app\.js\?v=(\d+)', resp2.text).group(1)
        assert ver2 != ver1, "mtime 变了版本号应跟着变"
        assert ver2 == str(int(app_js.stat().st_mtime))
    finally:
        os.utime(app_js, (real_mtime, real_mtime))  # 还原（utime 不改内容，git 无感）


async def test_missing_asset_returns_none():
    """引用的本地文件不存在 → _asset_version 返回 None（标签原样保留，不 500）。"""
    from api.main import _asset_version
    assert _asset_version("/static/js/__no_such__.js") is None
    assert _asset_version("/static/js/app.js") is not None
