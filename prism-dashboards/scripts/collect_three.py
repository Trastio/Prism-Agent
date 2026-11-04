import asyncio, sys, time
sys.path.insert(0, '.')
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
from src.storage.db import init_db
init_db()

async def main():
    from src.scraper.collector import ReviewCollector
    from src.api.autohome_api import close_autohome_api
    targets = [('8087','海狮06'),('8006','零跑B01'),('6998','小鹏MONA M03')]
    c = ReviewCollector()
    for sid, name in targets:
        print(f'===== 开始采集 {name} (sid={sid}) =====', flush=True)
        t0 = time.time()
        try:
            saved = await c.collect(sid, use_llm=False)
            print(f'===== {name} 采集完成: {saved}条, 用时{time.time()-t0:.0f}s =====', flush=True)
        except Exception as e:
            print(f'===== {name} 采集失败: {e!r} =====', flush=True)
    await close_autohome_api()
    print('ALL DONE', flush=True)

asyncio.run(main())
