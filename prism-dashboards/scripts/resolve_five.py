"""一次性：核实 5 个车系名 -> series_id 候选，供用户确认后采集。"""
import asyncio, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.scraper.collector import ReviewCollector
from src.api.autohome_api import close_autohome_api

NAMES = ["海豹06", "银河TT", "M9", "零跑D19", "华境S"]


async def main():
    c = ReviewCollector()
    for name in NAMES:
        print(f"\n===== 搜索: {name} =====", flush=True)
        try:
            res = await c.resolve_target(name)
            sid = res["series_id"]
            method = res["method"]
            cands = res.get("results") or []
            if cands:
                for r in cands[:5]:
                    print(f"  - {r.get('series_id')}  {r.get('name')}  ({r.get('level_name','')}/{r.get('min_price','')}-{r.get('max_price','')})", flush=True)
            print(f"  >>> 选定: sid={sid} method={method}", flush=True)
        except Exception as e:
            print(f"  !!! 未找到: {e!r}", flush=True)
    await close_autohome_api()


asyncio.run(main())
