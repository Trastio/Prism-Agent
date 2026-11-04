import asyncio, sys, time, logging
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv(override=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
from src.storage.db import init_db
init_db()

# 5 个新车系（搜索 API 已核实 series_id，2026-09-25）
TARGETS = [
    ('7588', '海豹06'),
    ('8658', '银河TT'),
    ('7207', '问界M9'),     # 用户称"M9"，搜索首个=问界M9
    ('8273', '零跑D19'),
    ('8283', '华境S'),
]

async def main():
    from src.scraper.collector import ReviewCollector
    from src.api.autohome_api import close_autohome_api
    c = ReviewCollector()
    for sid, name in TARGETS:
        print(f'===== 开始采集 {name} (sid={sid}) =====', flush=True)
        t0 = time.time()
        try:
            saved = await c.collect(sid, use_llm=True)
            print(f'===== {name} 采集完成: {saved}条, 用时{time.time()-t0:.0f}s =====', flush=True)
        except Exception as e:
            print(f'===== {name} 采集失败: {e!r} =====', flush=True)
    await close_autohome_api()
    print('ALL DONE', flush=True)

asyncio.run(main())
