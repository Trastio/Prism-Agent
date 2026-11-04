"""清洗 analyzed_posts.dim_sentiment——丢弃非 15 标准维度的脏数据。

背景：GLM-4-Flash 早期 _parse_response 未做白名单过滤，输出了上百个自创维度
（销量/砍价技巧/颠簸道路稳定性 等）。本脚本用 local_absa.ALL_DIMENSIONS
白名单清洗历史数据，让维度雷达/热力图可用。

Task 1 修复了 _parse_response（新分析的帖子自动干净），本脚本清洗历史存量。

用法（在项目根目录运行）：
    C:/Users/<you>/Anaconda3/python.exe scripts/clean_dim_sentiment.py [vehicle_id]

不带 vehicle_id 则清洗全表。
"""
import json
import os
import sqlite3
import sys

# 把项目根加入 sys.path，让 pipeline 包可 import（脚本从 scripts/ 运行）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.analysis.local_absa import ALL_DIMENSIONS

VALID = set(ALL_DIMENSIONS)
DB = "data/vehicle_sentiment.db"


def main():
    vehicle_id = sys.argv[1] if len(sys.argv) > 1 else None
    conn = sqlite3.connect(DB)
    if vehicle_id:
        rows = conn.execute(
            "SELECT id, dim_sentiment FROM analyzed_posts "
            "WHERE vehicle_id=? AND dim_sentiment IS NOT NULL",
            (vehicle_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, dim_sentiment FROM analyzed_posts "
            "WHERE dim_sentiment IS NOT NULL"
        ).fetchall()

    cleaned_count = 0
    emptied_count = 0
    for aid, dj in rows:
        try:
            d = json.loads(dj) if dj else {}
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(d, dict):
            continue
        cleaned = {k: v for k, v in d.items() if k in VALID}
        if cleaned != d:
            conn.execute(
                "UPDATE analyzed_posts SET dim_sentiment=? WHERE id=?",
                (json.dumps(cleaned, ensure_ascii=False), aid),
            )
            cleaned_count += 1
            if not cleaned:
                emptied_count += 1
    conn.commit()
    conn.close()
    print(f"清洗完成: 共 {len(rows)} 行，修正 {cleaned_count} 行（其中 {emptied_count} 行清空为 {{}}）")
    print(f"白名单维度({len(VALID)}): {sorted(VALID)}")


if __name__ == "__main__":
    main()
