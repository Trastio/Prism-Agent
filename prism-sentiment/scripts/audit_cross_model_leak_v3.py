# -*- coding: utf-8 -*-
"""只读审计：跨车型混入 v3 排查（银河A7 奥迪A7L/星舰7 + 全车队扫描）。

不修改任何数据。输出：
[1] 银河A7 混入帖明细 + 放行路径还原（subject/analysis_status/model_used）
[2] 银河A7 品牌词元分析（采集层过滤键）
[3] 全车队扫描：不含本车名的入库帖（每车计数+样本+命中词元）
[4] 后缀变体扫描：本车名是更长车型名的子串（如 风云T9 ⊂ 风云T9L）
"""
import re
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DB = Path(__file__).resolve().parents[1] / "data" / "vehicle_sentiment.db"
con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
cur = con.cursor()

BRAND_TOKEN_RE = re.compile(r'[一-鿿]+|[A-Za-z0-9]+')


def tokens(name, brand):
    out = []
    for t in (name, brand):
        if not t:
            continue
        out += [p for p in BRAND_TOKEN_RE.findall(t) if len(p) >= 2]
    seen, res = set(), []
    for t in out:
        if t.lower() not in seen:
            seen.add(t.lower())
            res.append(t)
    return res


vehicles = cur.execute(
    "SELECT id, name, brand, search_keywords, expanded_keywords FROM vehicles ORDER BY name"
).fetchall()

# ── [1] 银河A7 混入明细 ─────────────────────────────────────────────
print("=" * 72)
print("[1] 银河A7 混入帖明细")
a7 = [v for v in vehicles if "A7" in (v[1] or "") and "银河" in (v[1] or "")]
if not a7:
    a7 = [v for v in vehicles if "银河" in (v[1] or "")]
if a7:
    vid, vname, vbrand = a7[0][0], a7[0][1], a7[0][2]
    print(f"  vehicle: {vname} ({vbrand}) id={vid}")
    print(f"  search_keywords: {a7[0][3]}")
    print(f"  expanded_keywords: {(a7[0][4] or '')[:300]}")
    rows = cur.execute("""
        SELECT r.id, r.title, r.platform, r.analysis_status, r.author_type,
               a.subject, a.subject_name, a.confidence, a.model_used,
               substr(r.content, 1, 60), r.collected_at
        FROM raw_posts r LEFT JOIN analyzed_posts a ON a.post_id = r.id
        WHERE r.vehicle_id = ?
          AND (r.title LIKE '%奥迪%' OR r.title LIKE '%星舰%' OR r.title LIKE '%A7L%'
               OR r.content LIKE '%奥迪%' OR r.content LIKE '%星舰%' OR r.content LIKE '%A7L%')
        ORDER BY r.collected_at DESC LIMIT 40
    """, (vid,)).fetchall()
    print(f"  混入帖数(奥迪/星舰/A7L 命中): {len(rows)}")
    for r in rows:
        title = (r[1] or "")[:36]
        print(f"    [{r[2]:<6}] subj={r[5]!s:<6} st={r[3]:<9} conf={r[7]!s:<4} "
              f"model={r[8]!s:<12} | {title}")
    # 全量计数（不截断）
    for pat in ("奥迪", "星舰", "A7L"):
        n = cur.execute(
            "SELECT COUNT(*) FROM raw_posts WHERE vehicle_id=? AND "
            "(title LIKE ? OR content LIKE ?)", (vid, f"%{pat}%", f"%{pat}%")
        ).fetchone()[0]
        print(f"  计数 '{pat}': {n}")
    # subject 分布
    dist = cur.execute("""
        SELECT COALESCE(a.subject,'(无analyzed行)'), COUNT(*) FROM raw_posts r
        LEFT JOIN analyzed_posts a ON a.post_id = r.id
        WHERE r.vehicle_id=? AND (r.title LIKE '%奥迪%' OR r.title LIKE '%星舰%'
            OR r.content LIKE '%奥迪%' OR r.content LIKE '%星舰%')
        GROUP BY 1
    """, (vid,)).fetchall()
    print(f"  混入帖 subject 分布: {dist}")

# ── [2] 银河A7 词元分析 ─────────────────────────────────────────────
print("=" * 72)
print("[2] 品牌词元分析（采集层 _extract_brand_keywords 语义）")
if a7:
    tks = tokens(a7[0][1], a7[0][2])
    print(f"  {a7[0][1]} ({a7[0][2]}) → 词元: {tks}")
    print("  → 采集层过滤 = 帖文含任一词元即放行")
    probe = "奥迪A7L 45TFSI 上市"
    hit = [t for t in tks if t.lower() in probe.lower()]
    print(f"  探针 '奥迪A7L 45TFSI 上市' 命中词元: {hit}  {'→ 采集层放行!' if hit else ''}")
    probe2 = "吉利银河星舰7 EM-i 上市"
    hit2 = [t for t in tks if t.lower() in probe2.lower()]
    print(f"  探针 '吉利银河星舰7 EM-i 上市' 命中词元: {hit2}  {'→ 采集层放行!' if hit2 else ''}")

# ── [3] 全车队扫描：不含本车名的入库帖 ─────────────────────────────
print("=" * 72)
print("[3] 全车队扫描：帖文(title+content)不含本车名 → 依赖词元放行的可疑帖")
print(f"{'车名':<14}{'总帖':>6}{'可疑':>6}  样本(标题)")
for vid_, name, brand, _sk, _ek in vehicles:
    if not name:
        continue
    n_total = cur.execute(
        "SELECT COUNT(*) FROM raw_posts WHERE vehicle_id=?", (vid_,)
    ).fetchone()[0]
    if not n_total:
        continue
    # 用 SQL 排除含本车名的（大小写不敏感：SQLite LIKE 对 ASCII 不敏感）
    sus = cur.execute("""
        SELECT title, platform FROM raw_posts
        WHERE vehicle_id=? AND (title NOT LIKE ? AND content NOT LIKE ?)
        LIMIT 2000
    """, (vid_, f"%{name}%", f"%{name}%")).fetchall()
    if sus:
        samples = "; ".join((s[0] or "")[:22] for s in sus[:3])
        print(f"{name:<14}{n_total:>6}{len(sus):>6}  {samples}")
con.close()
print("=" * 72)
print("[4] 后缀变体（本车名 ⊂ 更长车名，子串匹配放行）见 README 手工清单：")
print("    风云T9⊂T9L? 银河A7⊂? 元PLUS? 海狮06⊂06EV? —— 逐车人工核对 aliases")
