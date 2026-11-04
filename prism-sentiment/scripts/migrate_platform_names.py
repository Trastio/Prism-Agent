"""迁移 raw_posts + post_comments 的 platform 缩写 → 规范全名（主题 B 治根）。

幂等：缩写与全名一一对应，无信息损失；无缩写时 no-op，可重复执行。
覆盖两表：raw_posts.platform、post_comments.platform（AnalyzedPost 无 platform 列，
经 models/schemas.py 核实）。映射来自 pipeline.platforms 单一真理源，不在本脚本重复定义。

用法：
    python scripts/migrate_platform_names.py --dry-run   # 先核对分布
    python scripts/migrate_platform_names.py             # 执行迁移
"""
import argparse
import os
import sqlite3

from pipeline.platforms import _SHORT_TO_FULL

DB_PATH = os.getenv("DB_PATH", "data/vehicle_sentiment.db")

# 存 platform 列的表（AnalyzedPost 经核实无 platform 列）
TABLES = ("raw_posts", "post_comments")


def migrate(con, dry_run: bool = False) -> int:
    """在给定 sqlite 连接上把缩写 UPDATE 为全名，返回更新行数。"""
    total = 0
    for table in TABLES:
        for short, full in _SHORT_TO_FULL.items():
            cur = con.execute(
                f"UPDATE {table} SET platform = ? WHERE platform = ?",
                (full, short),
            )
            total += cur.rowcount
    if dry_run:
        con.rollback()
    else:
        con.commit()
    return total


def _print_dist(con, header: str):
    print(f"=== {header} ===")
    for table in TABLES:
        rows = con.execute(
            f"SELECT platform, COUNT(*) FROM {table} GROUP BY platform ORDER BY 2 DESC"
        ).fetchall()
        print(f"[{table}]")
        for plat, n in rows:
            mark = "  ← 缩写(待迁移)" if plat in _SHORT_TO_FULL else ""
            print(f"    {plat!r:20} {n}{mark}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="只统计不写入")
    args = ap.parse_args()

    con = sqlite3.connect(DB_PATH)
    _print_dist(con, "迁移前 platform 分布")
    updated = migrate(con, dry_run=args.dry_run)
    if args.dry_run:
        print(f"\n(dry-run) 将更新 {updated} 行，未写入")
    else:
        print(f"\n已迁移 {updated} 行")
        _print_dist(con, "迁移后 platform 分布")
    con.close()


if __name__ == "__main__":
    main()
