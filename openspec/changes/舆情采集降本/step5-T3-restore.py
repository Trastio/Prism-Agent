"""T3 事故恢复工具（2026-10-16）：从 pre-change 备份外科式回插被误删行。

背景：全量 pytest 期间 test_daily_update::test_main 真跑 du.main()，漏补丁
新收尾钩子 _run_post_cleanup → 生产库被真删（active 车老帖 5,248 / 评论
40,125 / 分析行 4,845；paused 豁免生效未受损）。根因已三重修复（钩子默认
dry-run + env 门控 / DB_PATH 调用时读 / 肇事测试补丁）。

用法（在 prism-sentiment 目录下）：
    python ../openspec/changes/舆情采集降本/step5-T3-restore.py           # dry-run 只数
    python ../openspec/changes/舆情采集降本/step5-T3-restore.py --live   # 真恢复（单事务）

注意：
- 恢复=生产库写入，**须经用户/主会话批准后执行**；:8000 服务运行中也可跑
  （WAL + busy_timeout 30s），但建议低峰执行。
- 回插仅取「备份有、现存无」的行——对期间无新增写入的库是纯加法，幂等。
- 若用户拍板"接受现状当首次清理"（删除集与 R40/R42 授权语义完全一致，
  仅缺人工过目步骤），则本工具不执行，留档即可。
"""
import argparse
import os
import sqlite3
import sys

BAK_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "snapshots", "vehicle_sentiment-pre-change.db")
TARGETS = [("raw_posts", "id"), ("post_comments", "id"), ("analyzed_posts", "post_id")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", default=BAK_DEFAULT)
    ap.add_argument("--live", action="store_true", help="真恢复（默认 dry-run）")
    args = ap.parse_args()

    db = os.getenv("DB_PATH", "data/vehicle_sentiment.db")
    con = sqlite3.connect(db, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("ATTACH DATABASE ? AS bak", (f"file:{args.backup}?mode=ro",))
    try:
        total = 0
        for tbl, key in TARGETS:
            n = con.execute(
                f"SELECT count(*) FROM bak.{tbl} b WHERE NOT EXISTS "
                f"(SELECT 1 FROM main.{tbl} m WHERE m.{key} = b.{key})").fetchone()[0]
            print(f"[{'RESTORE' if args.live else 'DRY-RUN'}] {tbl}: 待回插 {n}")
            total += n
        if not args.live:
            print("dry-run 结束（--live 执行）")
            return 0
        with con:
            for tbl, key in TARGETS:
                cols_bak = [r[1] for r in con.execute(f"PRAGMA bak.table_info({tbl})")]
                cur_cols = [r[1] for r in con.execute(f"PRAGMA main.table_info({tbl})")]
                common = [c for c in cols_bak if c in cur_cols]
                col_list = ",".join(common)
                con.execute(
                    f"INSERT INTO main.{tbl} ({col_list}) "
                    f"SELECT {col_list} FROM bak.{tbl} b WHERE NOT EXISTS "
                    f"(SELECT 1 FROM main.{tbl} m WHERE m.{key} = b.{key})")
        print(f"[RESTORE] 完成，共回插 {total} 行（单事务）")
        return 0
    except Exception as e:
        print(f"[ERROR] {e}")
        return 1
    finally:
        con.execute("DETACH DATABASE bak")
        con.close()


if __name__ == "__main__":
    sys.exit(main())
