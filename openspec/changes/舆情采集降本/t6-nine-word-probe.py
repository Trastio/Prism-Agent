"""T6 · 9 词对照实验：被砍缺陷词的独占检出测量（方案 §3.7 基线 + P1 轮换实证）。

测量什么：15 台 active 车各搜"今日轮换组之外的 9 个缺陷词"（问题/质量/售后/维修/
退车/召回/异响/卡死/黑屏，车名+词组合与采集同源），统计各词命中的帖量与
"库里尚无"的新帖量——即砍掉这些词每天会漏掉的社媒检出。

纪律：只测量不落库（结果独立成 JSON）；调用走 TikHubCollector.search（与生产
同路径，内部翻页 xhs/dy 各 2 页 → 底层请求 ≈270×2=540 次，计入 T2 护栏计数器）。

用法：cd prism-sentiment && python ../openspec/changes/舆情采集降本/t6-nine-word-probe.py
"""
import asyncio
import io
import json
import os
import re
import sqlite3
import sys
from datetime import date, datetime

_SENT = r"C:\Users\<you>\Desktop\Prism-Agent\prism-sentiment"
sys.path.insert(0, _SENT)
os.chdir(_SENT)  # DB_PATH/.env 均为相对路径（T3 教训：仍以显式 chdir 兜底）

# .env → TIKHUB_KEY（整行取值防截断，401 乌龙旧坑）
_env = io.open(".env", encoding="utf-8").read()
_m = re.search(r"^TIKHUB_KEY\s*=\s*(.+)$", _env, re.M)
if _m and not os.environ.get("TIKHUB_KEY"):
    os.environ["TIKHUB_KEY"] = _m.group(1).strip().strip('"').strip("'")

from pipeline.collectors.post_utils import DEFECT_SEED_KEYWORDS, expand_defect_keywords  # noqa: E402
from pipeline.scheduler import rotate_defect_words  # noqa: E402

TODAY3 = set(rotate_defect_words(list(DEFECT_SEED_KEYWORDS), date.today()))
DROPPED = [w for w in DEFECT_SEED_KEYWORDS if w not in TODAY3]  # 今日组之外（期望 9 词）
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t6-nine-word-baseline.json")


def _usage_today() -> int:
    try:
        con = sqlite3.connect(os.path.join(_SENT, "data", "vehicle_sentiment.db"))
        r = con.execute("SELECT calls FROM tikhub_daily_usage WHERE date=?",
                        (date.today().isoformat(),)).fetchone()
        con.close()
        return r[0] if r else 0
    except Exception:
        return -1


async def run() -> list[dict]:
    from pipeline.collectors.tikhub_collector import TikHubCollector
    try:
        col = TikHubCollector()
    except TypeError:
        from pipeline.collectors.tikhub_collector import TikHubClient
        col = TikHubCollector(TikHubClient())
    if not await col.is_available():
        raise SystemExit("TIKHUB_KEY 未配置")

    con = sqlite3.connect(os.path.join(_SENT, "data", "vehicle_sentiment.db"))
    vehicles = con.execute(
        "SELECT id, name, brand FROM vehicles WHERE status='active' ORDER BY name").fetchall()
    known = {vid: {r[0] for r in con.execute(
        "SELECT url FROM raw_posts WHERE vehicle_id=? AND url IS NOT NULL", (vid,))}
        for vid, _n, _b in vehicles}
    con.close()

    sem, results = asyncio.Semaphore(3), []

    async def one(vid: str, name: str, brand: str):
        combos = expand_defect_keywords(name, brand or "")
        by_word = {w: next((c for c in combos if w in c), None) for w in DROPPED}
        for w, kw in by_word.items():
            if not kw:
                continue
            for plat in ("xiaohongshu", "douyin"):
                async with sem:
                    try:
                        posts, _ = await col.search(kw, plat, window_days=3, mode="incremental")
                        newn = sum(1 for p in posts
                                   if not (p.get("url") and p["url"] in known[vid]))
                        results.append({"car": name, "word": w, "platform": plat,
                                        "posts": len(posts), "new": newn})
                    except Exception as e:  # noqa: BLE001 单点失败不中断实验
                        results.append({"car": name, "word": w, "platform": plat,
                                        "error": repr(e)[:140]})
                    await asyncio.sleep(0.3)  # 温和限速

    await asyncio.gather(*(one(v[0], v[1], v[2]) for v in vehicles))
    return results


def main() -> int:
    usage0 = _usage_today()
    results = asyncio.run(run())
    ok = [r for r in results if "posts" in r]
    err = [r for r in results if "error" in r]
    agg: dict[str, dict] = {}
    for r in ok:
        a = agg.setdefault(r["word"], {"posts": 0, "new": 0, "calls": 0})
        a["posts"] += r["posts"]; a["new"] += r["new"]; a["calls"] += 1
    total_new = sum(a["new"] for a in agg.values())
    out = {"date": date.today().isoformat(), "today_group": sorted(TODAY3),
           "dropped_words": DROPPED, "cars": 15,
           "usage_before": usage0, "usage_after": _usage_today(),
           "per_word": agg, "errors": err,
           "summary": {"total_posts": sum(a["posts"] for a in agg.values()),
                       "total_new_to_db": total_new, "error_count": len(err)}}
    io.open(OUT, "w", encoding="utf-8").write(
        json.dumps(out, ensure_ascii=False, indent=2))
    print(f"=== 9 词对照实验 @ {date.today()} ===")
    for w, a in sorted(agg.items(), key=lambda kv: -kv[1]["new"]):
        print(f"  {w:>4}: 命中 {a['posts']:>4} 帖 | 库外新帖 {a['new']:>4} | {a['calls']} 次搜索")
    print(f"合计: 命中 {out['summary']['total_posts']} | 新帖 {total_new} | 错误 {len(err)}")
    print(f"护栏计数器: {usage0} -> {out['usage_after']}（本实验消耗 {out['usage_after']-usage0}）")
    print(f"结果已写 {OUT}")
    return 0 if len(err) < len(results) // 4 else 1  # 错误超 1/4 视为实验无效


if __name__ == "__main__":
    sys.exit(main())
