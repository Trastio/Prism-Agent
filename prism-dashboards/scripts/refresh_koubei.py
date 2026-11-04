"""全车系口碑数据刷新（看板数据滞后时手动跑）。

对 series_summaries 内全部车系跑 ReviewCollector.collect(use_llm=False)：
- upsert 去重（on_conflict_do_update），重复跑安全
- 顺带刷新 series_summaries（指导价区间/口碑总数等汇总）
- 不做 LLM 标签提取（花钱；新口碑需另行补标，见 reviews._background_tag_only）

用法：.venv/Scripts/python.exe scripts/refresh_koubei.py [model_id ...]
不传参数 = 全部车系。
"""
import asyncio
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 与 main.py 同款 .env 加载：脚本独立运行时也需要 LLM_API_KEY 等环境变量
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass  # 无 python-dotenv 时退回裸环境变量（容器/CI 场景）

# 编码守卫：GBK 控制台（cp936）下中文会 UnicodeEncodeError，才需要包 utf-8 包装；
# 已是 utf-8（含 pytest 捕获）则不再重复包裹——重复包裹会在 GC 时关闭底层缓冲。
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from src.scraper.collector import ReviewCollector
from src.storage.db import init_db, session_scope
from src.models.orm import SeriesSummary


async def main(only: list[str] | None = None):
    init_db()
    with session_scope() as s:
        mids = [r[0] for r in s.query(SeriesSummary.series_id).all()]
    if only:
        mids = [m for m in mids if m in only]
    print(f"[refresh] {len(mids)} 个车系待刷新", flush=True)

    collector = ReviewCollector()
    t0 = time.time()
    ok, fail = [], []
    for i, mid in enumerate(mids, 1):
        try:
            saved = await collector.collect(mid, use_llm=False)
            ok.append(mid)
            print(f"[refresh {i}/{len(mids)}] {mid}: 新增/更新 {saved} 条 "
                  f"(累计 {time.time()-t0:.0f}s)", flush=True)
        except Exception as e:
            fail.append(mid)
            print(f"[refresh {i}/{len(mids)}] {mid}: 失败 {e!r}", flush=True)
    print(f"[refresh] 完成。成功 {len(ok)}，失败 {len(fail)} {fail}", flush=True)
    return ok, fail


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or None))
