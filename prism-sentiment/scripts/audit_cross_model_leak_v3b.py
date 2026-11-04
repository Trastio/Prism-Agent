# -*- coding: utf-8 -*-
"""只读审计 v3b：精确泄漏计数。

泄漏定义（污染看板的充要条件）：
  subject='self'（或无 analyzed 行=视作 self）AND 帖文含外部车型模式 AND 帖文不含本车名。
对比帖（含本车名+外部车名）按设计是相关的，不计泄漏。
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DB = Path(__file__).resolve().parents[1] / "data" / "vehicle_sentiment.db"
con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
cur = con.cursor()

vehicles = {name: vid for vid, name in cur.execute("SELECT id, name FROM vehicles").fetchall()}

# (车名, 外部车型模式列表, 本车名排除)
CASES = [
    ("银河A7",     ["%星舰7%", "%星舰 7%"],                    "银河a7"),
    ("银河A7",     ["%奥迪%", "%索尼a7%", "%a7v%", "%a7l%"],   "银河a7"),
    ("银河A7",     ["%银河e5%", "%银河m9%", "%银河tt%", "%星愿%"], "银河a7"),
    ("Model Y",    ["%model 3%", "%model3%"],                   "model y"),
    ("特斯拉model 3", ["%model y%", "%modely%"],                "特斯拉model 3"),
    ("海狮06",     ["%深蓝l06%", "%海狮05%", "%海狮07%"],       "海狮06"),
    ("银河E5",     ["%星愿%", "%星舰7%", "%银河a7%"],           "银河e5"),
    ("星愿",       ["%星舰7%", "%银河a7%", "%银河e5%"],         "星愿"),
    ("零跑B10",    ["%c10%", "%b01%", "%a10%", "%d19%"],        "b10"),
    ("零跑B01",    ["%b10%", "%c10%", "%a10%"],                 "b01"),
    ("零跑D19",    ["%d99%", "%a10%", "%b01%"],                 "d19"),
    ("风云A9",     ["%a9l%"],                                   "风云a9"),
    ("风云A9L",    [],                                          "x"),  # 占位，单独处理
    ("风云T9L",    [],                                          "x"),
    ("风云T9",     ["%t9l%"],                                   "风云t9"),
    ("风云T7",     ["%t9%", "%t11%", "%a9%"],                   "风云t7"),
    ("风云T11",    ["%t7%", "%t9%", "%a9%"],                    "风云t11"),
    ("小鹏MONA M03", ["%m05%", "%mona 03%"],                    "m03"),
    ("小米SU7",    ["%y u 7%", "%yu7%", "%尚界%"],              "su7"),
    ("MG4X",       ["%mg4 %", "%mg4三%", "%cyberster%"],        "mg4x"),
    ("铂智3X",     [],                                          "x"),
    ("QQ3",        ["%qq5%", "%qq冰淇淋%"],                     "qq3"),
]


def leak_count(vid, own_name, patterns):
    """subject=self（或无行）+ 含外部模式 + 不含本车名（大小写统一 lower 比较）。"""
    total = 0
    samples = []
    for pat in patterns:
        rows = cur.execute("""
            SELECT r.title, COALESCE(a.subject, 'NULL'), r.platform
            FROM raw_posts r LEFT JOIN analyzed_posts a ON a.post_id = r.id
            WHERE r.vehicle_id = ?
              AND (lower(r.title) LIKE ? OR lower(r.content) LIKE ?)
        """, (vid, pat, pat)).fetchall()
        for title, subj, plat in rows:
            if subj in ("competitor",):
                continue  # 已标竞品，被 SELF_ONLY 排除，不污染
            # 排除对比帖：含本车名
            row_full = cur.execute(
                "SELECT lower(title || ' ' || content) FROM raw_posts WHERE id = ?",
                (cur.execute("SELECT id FROM raw_posts WHERE vehicle_id=? AND title=? LIMIT 1",
                             (vid, title)).fetchone()[0],) if False else (None,)
            ) if False else None
            samples.append((title, subj, plat, pat))
            total += 1
    return total, samples


print(f"{'车名':<12}{'外部模式':<28}{'候选帖':>5}  其中 subject=self/NULL（看板可见）样本")
for name, patterns, own in CASES:
    if not patterns or name not in vehicles:
        continue
    vid = vehicles[name]
    for pat in patterns:
        n, sub = cur.execute("""
            SELECT COUNT(*), SUM(CASE WHEN COALESCE(a.subject,'self') != 'competitor'
                                 AND COALESCE(a.subject,'self') != 'other' THEN 1 ELSE 0 END)
            FROM raw_posts r LEFT JOIN analyzed_posts a ON a.post_id = r.id
            WHERE r.vehicle_id=? AND (lower(r.title) LIKE ? OR lower(r.content) LIKE ?)
        """, (vid, pat, pat)).fetchone()
        if n:
            # 排除对比帖：帖文同时含本车名的不算泄漏
            n_own = cur.execute("""
                SELECT COUNT(*) FROM raw_posts r
                LEFT JOIN analyzed_posts a ON a.post_id = r.id
                WHERE r.vehicle_id=? AND (lower(r.title) LIKE ? OR lower(r.content) LIKE ?)
                  AND (lower(r.title) LIKE ? OR lower(r.content) LIKE ?)
            """, (vid, pat, pat, f"%{own}%", f"%{own}%")).fetchone()[0]
            # subject 为 competitor 的不算
            n_comp = cur.execute("""
                SELECT COUNT(*) FROM raw_posts r JOIN analyzed_posts a ON a.post_id = r.id
                WHERE r.vehicle_id=? AND (lower(r.title) LIKE ? OR lower(r.content) LIKE ?)
                  AND a.subject = 'competitor'
            """, (vid, pat, pat)).fetchone()[0]
            leak = n - n_own - n_comp
            if leak > 0:
                samp = cur.execute("""
                    SELECT r.title FROM raw_posts r
                    LEFT JOIN analyzed_posts a ON a.post_id = r.id
                    WHERE r.vehicle_id=? AND (lower(r.title) LIKE ? OR lower(r.content) LIKE ?)
                      AND (lower(r.title) NOT LIKE ? AND lower(r.content) NOT LIKE ?)
                      AND COALESCE(a.subject,'self') != 'competitor'
                    LIMIT 2
                """, (vid, pat, pat, f"%{own}%", f"%{own}%")).fetchall()
                s = " | ".join((x[0] or "")[:24] for x in samp)
                print(f"{name:<12}{pat:<28}{leak:>5}  {s}")

con.close()
