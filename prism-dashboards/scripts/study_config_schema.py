"""研究汽车之家配置表 categories 结构 —— 跨 车型×能源形式 对比。
拉取代表车系的 get_full_config，只输出类别名 + 每类参数项数 + 前几个参数名，
用于设计 v5 概念配置表（8 类 ~39 项）的归类映射。
"""
import asyncio, sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.api.autohome_api import get_autohome_api, close_autohome_api
from src.scraper.collector import ReviewCollector

# 代表矩阵：车型 × 能源。sid 先用已知常见值，未知走搜索。
REPS = [
    ("纯电轿车", "海豚", "6139"),
    ("纯电SUV",  "海狮06", "8087"),
    ("燃油轿车", "朗逸", None),
    ("燃油SUV",  "哈弗H6", None),
    ("插混轿车", "秦PLUS", None),
    ("插混SUV",  "宋PLUS DM-i", None),
    ("增程SUV",  "理想L9", None),
    ("燃油MPV",  "别克GL8", None),
    ("插混MPV",  "腾势D9", None),
]

async def resolve(name, c):
    res = await c.resolve_target(name)
    return res["series_id"]

async def main():
    api = await get_autohome_api()
    c = ReviewCollector()
    report = {}
    for label, name, sid in REPS:
        if not sid:
            try:
                sid = await resolve(name, c)
            except Exception as e:
                print(f"\n##### {label} ({name}) 搜索失败: {e!r}", flush=True)
                continue
        print(f"\n##### {label} | {name} | sid={sid} —— 拉配置...", flush=True)
        try:
            cfg = await api.get_full_config(sid)
        except Exception as e:
            print(f"  拉取失败: {e!r}", flush=True)
            continue
        cats = cfg.get("categories") or {}
        if not cats:
            print(f"  无 categories，keys={list(cfg.keys())[:8]}", flush=True)
            continue
        total = sum(len(v) for v in cats.values())
        print(f"  类别 {len(cats)} 个 / 参数 {total} 项:", flush=True)
        report[label] = {"name": name, "sid": sid, "total_params": total, "categories": {}}
        for cat, params in cats.items():
            sample = list(params.keys())[:6]
            print(f"    [{cat}] {len(params)}项  样例: {sample}", flush=True)
            report[label]["categories"][cat] = {"count": len(params), "sample": sample}
    await close_autohome_api()

    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "docs", "v5配置表结构研究-2026-09-25.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n===== 报告已存 {out} =====", flush=True)

asyncio.run(main())
