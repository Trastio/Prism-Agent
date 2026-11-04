"""存量 raw_posts 回填 author_type（2026-09-15 Q5 分层）。

幂等：全量按当前规则重算覆盖（规则更新后重跑即可）。采集侧新帖已在
scheduler._store_posts 打标，本脚本只处理存量。

用法（项目根目录运行）：
    C:/Users/<you>/Anaconda3/python.exe scripts/backfill_author_type.py [--dry-run]
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:  # Windows GBK 控制台兜底
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from pipeline.collectors.post_utils import classify_author_type, profile_author_behavior

DB = "data/vehicle_sentiment.db"


def main():
    ap = argparse.ArgumentParser(description="回填 raw_posts.author_type")
    ap.add_argument("--dry-run", action="store_true", help="只统计分布不写库")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    # 列可能尚未迁移（迁移在服务启动期执行，旧进程仍在跑改前代码）——自足补齐
    cols = {r[1] for r in cur.execute("PRAGMA table_info(raw_posts)")}
    if "author_type" not in cols:
        cur.execute("ALTER TABLE raw_posts ADD COLUMN author_type VARCHAR DEFAULT 'organic'")
        conn.commit()
    rows = cur.execute(
        "SELECT p.id, p.author, p.title, v.brand, v.name "
        "FROM raw_posts p JOIN vehicles v ON p.vehicle_id = v.id"
    ).fetchall()

    # 行为背调（B1）：批量查所有作者近 90 天历史帖，内存分组——防 N+1。
    # 一作者跨车型多帖时合计判定 marketing_account（错标的 organic 改正）。
    all_authors = {r[1] for r in rows if r[1]}
    hist_by_author: dict[str, list[dict]] = {}
    if all_authors:
        since = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d %H:%M:%S")
        hist_rows = cur.execute(
            "SELECT author, title, content FROM raw_posts "
            "WHERE author IN (%s) AND collected_at >= ?" % ",".join("?" for _ in all_authors),
            (*all_authors, since),
        ).fetchall()
        for author, title, content in hist_rows:
            hist_by_author.setdefault(author or "", []).append(
                {"title": title or "", "content": content or ""})

    dist: dict[str, int] = {}
    updates = []
    for pid, author, title, brand, name in rows:
        author = author or ""
        # 行为背调优先：库内历史帖汽车内容占比达标的标 marketing_account
        label = profile_author_behavior(author, hist_by_author.get(author, []))
        at = label or classify_author_type(author, title or "", brand or "", name or "")
        dist[at] = dist.get(at, 0) + 1
        updates.append((at, pid))

    total = len(rows)
    print(f"总帖数 {total}")
    for k in sorted(dist, key=dist.get, reverse=True):
        print(f"  {k:16s} {dist[k]:5d}  ({dist[k] / max(total, 1) * 100:.1f}%)")

    if args.dry_run:
        print("(dry-run，未写库)")
        conn.close()
        return

    cur.executemany("UPDATE raw_posts SET author_type=? WHERE id=?", updates)
    conn.commit()
    print(f"已回填 {len(updates)} 行")
    conn.close()


if __name__ == "__main__":
    main()
