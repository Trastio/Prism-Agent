"""dashboards-tri-polish：全量回填口碑完整原文。

从之家详情页 k.autohome.com.cn/detail/view_{Koubeigid}.html 抓 <p class="kb-item-msg">
前两个（最满意/最不满意完整原文），写回 owner_reviews.best_full_text/worst_full_text。

用法：.venv/Scripts/python.exe scripts/backfill_full_reviews.py [--limit N] [--batch-size 50]
控速：asyncio + semaphore(3)，断点续传（跳过 best_full_text IS NOT NULL），失败重试 3 次。
"""
import asyncio
import io
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# 与 main.py / backfill_tags.py 同款 .env 加载：脚本独立运行时也需要环境变量
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

# 编码守卫：GBK 控制台（cp936）下中文会 UnicodeEncodeError，才需要 utf-8 包装；
# 已是 utf-8（含 pytest 捕获）则不再重复包裹——重复包裹会在 GC 时关闭底层缓冲。
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import httpx
from sqlalchemy import text

from src.storage.db import init_db, session_scope
from src.models.orm import OwnerReview

DETAIL_URL = "https://k.autohome.com.cn/detail/view_{kid}.html"
# 详情页 SSR：每条口碑维度用 <p class="kb-item-msg">…</p>，前两个 = 最满意/最不满意
MSG_RE = re.compile(r'<p class="kb-item-msg">([\s\S]*?)</p>')


def _koubeigid_from_review_id(rid: str) -> str | None:
    """review_id 去 k_ 前缀 = Koubeigid；k_api_ 等非 k_{id} 格式返回 None。"""
    if rid and rid.startswith("k_") and not rid.startswith("k_api_"):
        return rid[2:]
    return None


def _clean(s: str) -> str:
    """去 HTML 标签 + 规范空白。"""
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _extract_full_texts(html: str) -> tuple[str | None, str | None]:
    """从详情页 HTML 提取最满意/最不满意完整原文（<p class="kb-item-msg"> 前两个）。

    无 kb-item-msg → (None, None)；仅 1 条 → (clean, None)。
    """
    msgs = MSG_RE.findall(html)
    if not msgs:
        return (None, None)
    if len(msgs) == 1:
        return (_clean(msgs[0]), None)
    return (_clean(msgs[0]), _clean(msgs[1]))


async def _fetch_one(client: httpx.AsyncClient, kid: str, retries: int = 3) -> tuple[str | None, str | None]:
    """抓单条详情页，重试 3 次。返回 (best_full, worst_full)。"""
    url = DETAIL_URL.format(kid=kid)
    for attempt in range(retries):
        try:
            r = await client.get(url, timeout=15)
            if r.status_code == 200 and "kb-item-msg" in r.text:
                return _extract_full_texts(r.text)
        except Exception:
            pass
        await asyncio.sleep(1)
    return (None, None)


async def backfill(limit: int = 0, batch_size: int = 50, sem: int = 3):
    """全量回填。limit=0 表示全量。断点续传：跳过 best_full_text IS NOT NULL。"""
    init_db()
    failures: list[str] = []

    with session_scope() as s:
        q = s.query(OwnerReview.review_id).filter(
            OwnerReview.review_id.like("k_%"),
            ~OwnerReview.review_id.like("k_api_%"),
            OwnerReview.best_full_text.is_(None),
        )
        if limit:
            q = q.limit(limit)
        rids = [r[0] for r in q.all()]

    print(f"待回填 {len(rids)} 条（已跳过 best_full_text 非空）", flush=True)
    if not rids:
        return

    semaphore = asyncio.Semaphore(sem)
    processed = 0
    async with httpx.AsyncClient(headers={"User-Agent": "Mozilla/5.0"}) as client:
        for i in range(0, len(rids), batch_size):
            batch = rids[i:i + batch_size]

            async def _process(rid):
                async with semaphore:
                    kid = _koubeigid_from_review_id(rid)
                    if not kid:
                        return None
                    best, worst = await _fetch_one(client, kid)
                    if best is None and worst is None:
                        failures.append(rid)
                        return None
                    return (rid, best, worst)

            results = await asyncio.gather(*[_process(rid) for rid in batch])
            with session_scope() as s:
                for r in results:
                    if r:
                        rid, best, worst = r
                        s.execute(text(
                            "UPDATE owner_reviews SET best_full_text=:b, worst_full_text=:w WHERE review_id=:r"
                        ), {"b": best, "w": worst, "r": rid})
                s.commit()
            processed += len(batch)
            print(f"进度 {processed}/{len(rids)}（失败 {len(failures)}）", flush=True)

            if failures:
                with open(ROOT / "data" / "backfill_failures.json", "w", encoding="utf-8") as f:
                    json.dump(failures, f, ensure_ascii=False)

    print(f"完成。失败 {len(failures)} 条 → data/backfill_failures.json", flush=True)


def _parse_args(argv: list[str]) -> dict:
    args = {"limit": 0, "batch_size": 50, "sem": 3}
    for i, a in enumerate(argv):
        if a == "--limit" and i + 1 < len(argv):
            args["limit"] = int(argv[i + 1])
        elif a == "--batch-size" and i + 1 < len(argv):
            args["batch_size"] = int(argv[i + 1])
        elif a == "--sem" and i + 1 < len(argv):
            args["sem"] = int(argv[i + 1])
    return args


if __name__ == "__main__":
    _args = _parse_args(sys.argv[1:])
    asyncio.run(backfill(limit=_args["limit"], batch_size=_args["batch_size"], sem=_args["sem"]))
