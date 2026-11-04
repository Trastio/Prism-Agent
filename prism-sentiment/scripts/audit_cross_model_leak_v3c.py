# -*- coding: utf-8 -*-
"""只读审计 v3c：真实看板污染计数（修正口径）。

污染 = analysis_status != 'irrelevant'（RELEVANT_ONLY 通过）
      AND COALESCE(subject,'self') = 'self'（SELF_ONLY 通过，NULL 视 self）
      AND 帖文含外部车型 AND 帖文不含本车名（排除对比帖）。
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DB = Path(__file__).resolve().parents[1] / "data" / "vehicle_sentiment.db"
con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
cur = con.cursor()

vehicles = {name: vid for vid, name in cur.execute("SELECT id, name FROM vehicles").fetchall()}

CASES = [
    ("银河A7", ["%星舰7%", "%奥迪%", "%索尼a7v%", "%索尼a7r%", "%银河e5%", "%银河m9%", "%银河tt%", "%星愿%"], "银河a7"),
    ("Model Y", ["%model 3%", "%model3%"], "model y"),
    ("特斯拉model 3", ["%model y%", "%modely%"], "特斯拉model 3"),
    ("海狮06", ["%海狮05%", "%海狮07%"], "海狮06"),
    ("银河E5", ["%星愿%", "%星舰7%", "%银河a7%"], "银河e5"),
    ("星愿", ["%星舰7%", "%银河a7%", "%银河e5%"], "星愿"),
    ("零跑B10", ["%c10%", "%b01%", "%a10%", "%d19%"], "b10"),
    ("零跑B01", ["%b10%", "%c10%", "%a10%"], "b01"),
    ("零跑D19", ["%d99%", "%a10%", "%b01%"], "d19"),
    ("风云A9", ["%a9l%"], "风云a9"),
    ("风云T9", ["%t9l%"], "风云t9"),
    ("风云T7", ["%t9%", "%a9%"], "风云t7"),
    ("风云T11", ["%t7%", "%t9%", "%a9%"], "风云t11"),
]

grand = 0
print(f"{'车名':<12}{'污染帖数':>6}  样本（真实上看板的异车帖）")
for name, patterns, own in CASES:
    if name not in vehicles:
        continue
    vid = vehicles[name]
    leaks = []
    for pat in patterns:
        rows = cur.execute("""
            SELECT r.id, r.title, r.analysis_status, COALESCE(a.subject,'self')
            FROM raw_posts r LEFT JOIN analyzed_posts a ON a.post_id = r.id
            WHERE r.vehicle_id=? AND (lower(r.title) LIKE ? OR lower(r.content) LIKE ?)
              AND (lower(r.title || ' ' || r.content) NOT LIKE ?)
              AND r.analysis_status != 'irrelevant'
              AND COALESCE(a.subject,'self') = 'self'
        """, (vid, pat, pat, f"%{own}%")).fetchall()
        leaks += rows
    # 去重（一帖可命中多模式）
    uniq = {r[0]: r for r in leaks}
    if uniq:
        grand += len(uniq)
        s = " | ".join((r[1] or "")[:22] for r in list(uniq.values())[:3])
        print(f"{name:<12}{len(uniq):>6}  {s}")
print(f"\n合计（抽查明细的 13 车）：{grand} 帖真实污染看板")
con.close()
