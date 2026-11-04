"""全车系 LLM 标签补标（看板 Top 买点/槽点数据缺口时手动跑）。

对 series_summaries 内全部车系按"未打标数升序"跑增量标签提取：
- 直接调 ReviewCollector._llm_extract_all_tags（无 _background_tag_only 的 300s 超时）
- 增量：已打标的口碑自动跳过，重复跑安全、可断点续跑
- 升序 = 小缺口车系先完成（看板先点亮），海豚/T03 等大头殿后
- 依赖 deepseek API（tagger），失败按 chunk 跳过不中断

用法：.venv/Scripts/python.exe scripts/backfill_tags.py [model_id ...]
不传参数 = 全部车系（按缺口升序）。
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

from sqlalchemy import text

from src.scraper.collector import ReviewCollector
from src.storage.db import init_db, session_scope
from src.tools.reviews import _get_all_reviews_for_model


def _untagged_map() -> dict[str, int]:
    with session_scope() as s:
        rows = s.execute(text("""
            SELECT r.model_id, COUNT(*) FROM owner_reviews r
            WHERE ((r.best_review_text IS NOT NULL AND TRIM(r.best_review_text) != '')
                OR (r.worst_review_text IS NOT NULL AND TRIM(r.worst_review_text) != ''))
              AND NOT EXISTS (SELECT 1 FROM review_tags t WHERE t.review_id = r.review_id)
            GROUP BY r.model_id
        """)).fetchall()
    return dict(rows)


async def main(only: list[str] | None = None):
    init_db()
    gap = _untagged_map()
    if only:
        mids = [m for m in only if gap.get(m)]
    else:
        mids = sorted(gap, key=lambda m: gap[m])  # 缺口升序：小先快跑
    total = sum(gap[m] for m in mids)
    print(f"[tags] {len(mids)} 个车系待补标，合计 {total} 条未打标", flush=True)

    from src.nlp.tagger import get_tagger, close_tagger
    from src.storage.db import session_scope
    from src.models.orm import ReviewTag
    from sqlalchemy import text as sa_text

    tagger = await get_tagger()
    t0 = time.time()
    ok: dict[str, int] = {}
    fail = []
    for i, mid in enumerate(mids, 1):
        try:
            reviews = _get_all_reviews_for_model(mid)
            text_reviews = [r for r in reviews if r.get("_has_text")]
            # 跳过已有标签的
            with session_scope() as s:
                tagged_ids = {r[0] for r in s.query(ReviewTag.review_id).filter(
                    ReviewTag.model_id == mid).distinct().all()}
            untagged = [r for r in text_reviews if r["review_id"] not in tagged_ids]
            if not untagged:
                print(f"[tags {i}/{len(mids)}] {mid}: 全部已打标，跳过", flush=True)
                continue

            print(f"[tags {i}/{len(mids)}] {mid}: {len(untagged)} 条待打标，单条模式提取 "
                  f"(累计 {time.time()-t0:.0f}s)", flush=True)

            saved = 0
            failed = 0
            for j, r in enumerate(untagged):
                try:
                    tags = await tagger.extract_tags(
                        r.get("best_review_text", "") or "",
                        r.get("worst_review_text", "") or "",
                    )
                    if tags:
                        # 去重：同 review_id + tag_name + sentiment 只保留一条
                        seen = set()
                        deduped = []
                        for tag in tags:
                            key = (tag.get("tag_name", ""), tag.get("sentiment", ""))
                            if key not in seen:
                                seen.add(key)
                                deduped.append(tag)
                        with session_scope() as s:
                            for tag in deduped:
                                s.add(ReviewTag(
                                    review_id=r["review_id"],
                                    owner_id=r.get("owner_id", ""),
                                    model_full_name=r.get("model_full_name", ""),
                                    model_id=mid,
                                    tag_name=tag.get("tag_name", ""),
                                    sentiment=tag.get("sentiment", "pro"),
                                    source_text=tag.get("source_text", ""),
                                    confidence=tag.get("confidence", 0.8),
                                    tag_category=tag.get("tag_category", ""),
                                ))
                            try:
                                s.commit()
                                saved += 1
                            except Exception as ce:
                                s.rollback()
                                failed += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    if failed <= 3:
                        print(f"  fail {r['review_id'][:20]}: {e}", flush=True)

                if (j + 1) % 20 == 0:
                    print(f"  {j+1}/{len(untagged)} (ok={saved} fail={failed}) "
                          f"{time.time()-t0:.0f}s", flush=True)

            ok[mid] = saved
            print(f"[tags {i}/{len(mids)}] {mid}: 补标 {saved} 条 (失败 {failed})", flush=True)
        except Exception as e:
            fail.append(mid)
            print(f"[tags {i}/{len(mids)}] {mid}: 失败 {e!r}", flush=True)

    await close_tagger()
    print(f"[tags] 完成。成功 {len(ok)}，失败 {len(fail)} {fail}，"
          f"总耗时 {time.time()-t0:.0f}s", flush=True)
    return ok, fail


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or None))
