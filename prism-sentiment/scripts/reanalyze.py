"""重分析脚本 —— 分析规则/模型改进后回溯历史帖（2026-09-13）。

背景：分析一次定型（帖入库时分析一次，此后不重跑）。当情感规则/维度
模型/subject 标注逻辑改进后，历史结论不会自动更新——本脚本重置后触发
重跑（分析管线按 raw_posts.analysis_status='pending' 取帖）。

用法：
    python scripts/reanalyze.py --vehicle M03                # 全部已分析帖
    python scripts/reanalyze.py --vehicle M03 --since 2026-08-01
    python scripts/reanalyze.py --vehicle M03 --dry-run      # 只看会影响多少

注意：
- 评论的 dim_sentiment 不在本脚本范围（采集时随抓随分析）
- 事件会在分析管线下一轮自动全量重算（先删后建）
- LLM 分析按量计费（GLM），量大时留意成本
"""
import argparse
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = Path(__file__).resolve().parent.parent / "data" / "vehicle_sentiment.db"
BASE = "http://127.0.0.1:8000"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vehicle", required=True, help="车名（子串匹配）")
    ap.add_argument("--since", default="", help="只重置该日期后发布的帖 (YYYY-MM-DD)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    row = con.execute("SELECT id, name FROM vehicles WHERE name LIKE ?",
                      (f"%{args.vehicle}%",)).fetchone()
    if not row:
        print(f"[FAIL] 找不到车辆: {args.vehicle}")
        return 2
    vid, name = row

    where = "ap.vehicle_id = ?"
    params: list = [vid]
    if args.since:
        where += " AND date(rp.published_at) >= ?"
        params.append(args.since)
    rows = con.execute(
        f"""SELECT ap.id, ap.post_id FROM analyzed_posts ap
            JOIN raw_posts rp ON ap.post_id = rp.id
            WHERE {where}""", params).fetchall()
    ap_ids = [r[0] for r in rows]
    post_ids = [r[1] for r in rows]
    print(f"[{name}] 待重置: {len(ap_ids)} 帖"
          + (f"（{args.since} 后发布）" if args.since else "（全部，含社媒+新闻）"))

    if args.dry_run:
        print("[dry-run] 到此为止")
        return 0
    if not ap_ids:
        print("无可重置，退出")
        return 0

    q1 = ",".join("?" * len(ap_ids))
    q2 = ",".join("?" * len(post_ids))
    n1 = con.execute(f"DELETE FROM analyzed_posts WHERE id IN ({q1})", ap_ids).rowcount
    n2 = con.execute(
        f"UPDATE raw_posts SET analysis_status='pending' WHERE id IN ({q2})",
        post_ids).rowcount
    con.commit()
    print(f"已删分析行 {n1}，重置待分析 {n2}")

    req = urllib.request.Request(f"{args.base}/api/analysis/trigger/{vid}", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print("触发重跑:", json.loads(r.read()))
    except Exception as e:
        print(f"[FAIL] 触发失败（服务在跑吗？）: {e}")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
