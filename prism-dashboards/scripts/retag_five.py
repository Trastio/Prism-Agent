"""补跑 5 车系 LLM 标签提取（口碑已入库，仅缺标签）。
修复：加载 .env 让 LLM_API_KEY 生效。
"""
import asyncio, sys, os, time, logging
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv(override=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# 5 个新车系（口碑已入库，补标签）
TARGETS = [
    ('7588', '海豹06'),
    ('8658', '银河TT'),
    ('7207', '问界M9'),
    ('8273', '零跑D19'),
    ('8283', '华境S'),
]

async def main():
    import sqlite3
    from src.scraper.collector import ReviewCollector
    from src.api.autohome_api import close_autohome_api
    c = ReviewCollector()
    from pathlib import Path as _Path
    # 绝对派生（不依赖 CWD）：<prism-dashboards>/data/autohome.db
    db = sqlite3.connect(str(_Path(__file__).resolve().parent.parent / 'data' / 'autohome.db'))
    db.row_factory = sqlite3.Row
    for sid, name in TARGETS:
        rows = db.execute(
            "SELECT review_id, owner_id, model_full_name, model_id, best_review_text, worst_review_text "
            "FROM owner_reviews WHERE model_id=?",
            (sid,),
        ).fetchall()
        if not rows:
            print(f'===== {name} (sid={sid}) 库内无口碑，跳过（先采集口碑） =====', flush=True)
            continue
        reviews = [dict(r) for r in rows]
        print(f'===== {name} (sid={sid}) 开始补标签，n={len(reviews)} =====', flush=True)
        t0 = time.time()
        try:
            await c._llm_extract_all_tags(reviews, sid)
            print(f'===== {name} 标签完成，用时{time.time()-t0:.0f}s =====', flush=True)
        except Exception as e:
            print(f'===== {name} 标签失败: {e!r} =====', flush=True)
    db.close()
    await close_autohome_api()
    print('ALL DONE', flush=True)

asyncio.run(main())
