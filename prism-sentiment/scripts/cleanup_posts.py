"""30 天保留线老帖物理清理（舆情降本 change T3 / 方案 R40+R42）。

规则（2026-10-15 拍板）：
- 删除 published_at 早于「今天 − POST_RETENTION_DAYS（默认 30）」的 raw_posts，
  **级联删除 post_comments 与 analyzed_posts**（两表均无 FK 强制，手动 DELETE）。
- **paused 车豁免**（R42）：status='paused' 的车存量冻结不删，永久可回查；
  inactive 车无帖，天然不受影响。
- published_at 为 NULL 的帖**不删**（无日期判据，宁保守）——与增量采集的
  时间过滤档不同路，此类帖只见于历史解析事故，数量极少。

引用处理（Step6 S3，2026-10-16）：
- event_groups.post_ids（JSON 数组存 RawPost.id）——**live 删除事务内自动修剪**
  （剔除已删 id；修剪后空组保留——组本身是话题记录）；dry-run 仍走引用审计
  报告"将悬空"供人工过目
- watch_items.source_ref（source_type=hot_post/complaint 时存 post_id）——
  **用户手动关注的清单**，只警告不自动动（悬空项由用户自行清理）
- defect_themes.payload 为 24h TTL 派生缓存（Phase 9 全量覆盖重算自愈），不审计

用法：
    python scripts/cleanup_posts.py --dry-run          # 只列清单统计（只读）
    python scripts/cleanup_posts.py                    # 真删（T6 验收前禁用）
    python scripts/cleanup_posts.py --vehicle 银河E5   # 单车清理
    python scripts/cleanup_posts.py --retention-days 7 # 临时收紧线

退出码：0=正常（含 0 删）；1=异常。
挂接：daily_update.py 收尾（互动刷新之后、备份之前——备份清理后的库）。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import env_int  # noqa: E402

_DELETE_BATCH = 500


def db_path() -> str:
    """调用时读取 DB_PATH（**禁止**模块级捕获——conftest 的 monkeypatch
    隔离在 import 时够不到，2026-10-16 事故根因之一）。"""
    return os.getenv("DB_PATH", "data/vehicle_sentiment.db")


def _connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    con.row_factory = sqlite3.Row
    return con


def retention_days_from_env(override: int | None = None) -> int:
    return override if override is not None else env_int("POST_RETENTION_DAYS", 30)


def cutoff_date(today: date, retention_days: int) -> date:
    """删除线：published_at 的日期部分 < cutoff 即删（30 天龄=保留，31 天=删）。"""
    return today - timedelta(days=retention_days)


def select_stale_posts(
    con: sqlite3.Connection, cutoff: date, vehicle: str = "",
) -> list[sqlite3.Row]:
    """将删帖清单（含车名/状态），paused 豁免在此 WHERE 收口。"""
    sql = (
        "SELECT p.id, p.vehicle_id, v.name AS vehicle_name, v.status AS vehicle_status, "
        "       date(p.published_at) AS pub_date "
        "FROM raw_posts p JOIN vehicles v ON v.id = p.vehicle_id "
        "WHERE p.published_at IS NOT NULL AND date(p.published_at) < ? "
        "  AND v.status != 'paused'"
    )
    params: list = [cutoff.isoformat()]
    if vehicle:
        sql += " AND v.name LIKE ?"
        params.append(f"%{vehicle}%")
    return list(con.execute(sql + " ORDER BY v.name, p.published_at", params))


def audit_references(
    con: sqlite3.Connection, post_ids: set[str],
) -> dict[str, list[dict]]:
    """将删集在 event_groups / watch_items 上的存活引用（警告用，不强阻）。"""
    hits: dict[str, list[dict]] = {"event_groups": [], "watch_items": []}
    if not post_ids:
        return hits
    # event_groups.post_ids 是 JSON 数组文本；行量级百级，Python 侧解析足够稳
    for row in con.execute(
        "SELECT id, vehicle_id, event_tag, start_date, end_date, post_ids "
        "FROM event_groups"
    ):
        try:
            ids = json.loads(row["post_ids"] or "[]")
        except (ValueError, TypeError):
            continue
        n = len(post_ids.intersection(ids))
        if n:
            hits["event_groups"].append({
                "id": row["id"], "event_tag": row["event_tag"],
                "start": row["start_date"], "end": row["end_date"],
                "dangling": n, "total": len(ids),
            })
    # watch_items：用户手动关注清单（source_ref 存 post_id），分批 IN 防超参上限
    for chunk_start in range(0, len(post_ids), 900):
        chunk = list(post_ids)[chunk_start:chunk_start + 900]
        qmarks = ",".join("?" * len(chunk))
        for row in con.execute(
            f"SELECT id, title, source_type, source_ref, vehicle_id FROM watch_items "
            f"WHERE source_type IN ('hot_post','complaint') AND source_ref IN ({qmarks})",
            chunk,
        ):
            hits["watch_items"].append(dict(row))
    return hits


def prune_event_groups(
    con: sqlite3.Connection, post_ids: set[str],
) -> int:
    """删除事务内修剪 event_groups.post_ids：剔除已删 id，空组保留。

    组本身是话题记录（Step6 S3，2026-10-16）——成员归零不清组行，前端
    话题列表仍可见历史事件。paused 车帖不在 post_ids 集内，天然不被修剪。
    返回被修剪的组数。

    2026-10-20：修剪时同步 ``post_count = len(kept)``——原只动 post_ids 不动
    post_count，轻卡「事件 post_count≥2 兜底」判据随删除静默失真。
    """
    post_ids = {str(p) for p in post_ids}
    pruned = 0
    rows = con.execute("SELECT id, post_ids FROM event_groups").fetchall()
    for row in rows:
        try:
            ids = json.loads(row["post_ids"] or "[]")
        except (ValueError, TypeError):
            continue
        if not isinstance(ids, list):
            continue
        kept = [i for i in ids if str(i) not in post_ids]
        if len(kept) == len(ids):
            continue  # 无交集，不动
        con.execute(
            "UPDATE event_groups SET post_ids = ?, post_count = ? WHERE id = ?",
            (json.dumps(kept, ensure_ascii=False), len(kept), row["id"]),
        )
        pruned += 1
    return pruned


def prune_dangling_refs(con: sqlite3.Connection, dry_run: bool = False) -> dict:
    """存量修复：剔除 event_groups.post_ids 中**库中已不存在**的 id（不限本次删集）。

    背景（2026-10-20 审计）：10-16 首删执行时 S3 prune 尚未合入，此后清理
    一直 dry-run，存量悬空引用从未修剪（T7 的 21 个事件全部含已删帖 id，
    95/60/42 条不等）。本函数幂等、零删除——只修剪引用并把 post_count 对齐
    ``len(kept)``；空组保留（与 S3 语义一致）。

    用法：``python scripts/cleanup_posts.py --prune-only [--dry-run]``
    （prune 引用不删数据，不需 PRISM_CLEANUP_LIVE 门）。
    """
    all_ids = {str(r[0]) for r in con.execute("SELECT id FROM raw_posts")}
    stats = {"dry_run": dry_run, "groups_scanned": 0, "groups_pruned": 0,
             "ids_removed": 0, "counts_fixed": 0}
    for row in con.execute("SELECT id, post_ids, post_count FROM event_groups").fetchall():
        stats["groups_scanned"] += 1
        try:
            ids = json.loads(row["post_ids"] or "[]")
        except (ValueError, TypeError):
            continue
        if not isinstance(ids, list):
            continue
        kept = [i for i in ids if str(i) in all_ids]
        removed = len(ids) - len(kept)
        if not removed and row["post_count"] == len(kept):
            continue  # 干净行
        if removed:
            stats["groups_pruned"] += 1
            stats["ids_removed"] += removed
        else:
            stats["counts_fixed"] += 1  # 仅 post_count 漂移
        if not dry_run:
            con.execute(
                "UPDATE event_groups SET post_ids = ?, post_count = ? WHERE id = ?",
                (json.dumps(kept, ensure_ascii=False), len(kept), row["id"]),
            )
    if not dry_run:
        con.commit()
    return stats


def _delete_in_batches(
    con: sqlite3.Connection, table: str, column: str, ids: list[str],
) -> int:
    deleted = 0
    for i in range(0, len(ids), _DELETE_BATCH):
        batch = ids[i:i + _DELETE_BATCH]
        qmarks = ",".join("?" * len(batch))
        cur = con.execute(f"DELETE FROM {table} WHERE {column} IN ({qmarks})", batch)
        deleted += cur.rowcount
    return deleted


def run_cleanup(
    dry_run: bool = False, vehicle: str = "", retention_days: int | None = None,
    con: sqlite3.Connection | None = None, today: date | None = None,
) -> dict:
    """主入口。con 参数供测试注入临时库；today 供边界用例冻结日期。"""
    own = con is None
    con = con or _connect(db_path())
    today = today or date.today()
    days = retention_days_from_env(retention_days)
    cutoff = cutoff_date(today, days)

    stale = select_stale_posts(con, cutoff, vehicle)
    post_ids = [r["id"] for r in stale]

    # 各车明细（含 paused 车存活对照，供人工过目）
    per_vehicle: dict[str, dict] = {}
    for r in stale:
        d = per_vehicle.setdefault(r["vehicle_name"], {"posts": 0, "oldest": r["pub_date"]})
        d["posts"] += 1
        d["oldest"] = min(d["oldest"], r["pub_date"])
    paused_kept = {
        r["name"]: r["n"] for r in con.execute(
            "SELECT v.name, count(p.id) AS n FROM vehicles v "
            "JOIN raw_posts p ON p.vehicle_id = v.id "
            "WHERE v.status = 'paused' AND p.published_at IS NOT NULL "
            "  AND date(p.published_at) < ? GROUP BY v.id", (cutoff.isoformat(),))
    }
    refs = audit_references(con, set(post_ids))

    result = {
        "dry_run": dry_run, "retention_days": days, "cutoff": cutoff.isoformat(),
        "posts": len(post_ids), "per_vehicle": per_vehicle,
        "paused_kept": paused_kept, "references": refs,
        "comments_deleted": 0, "analyzed_deleted": 0, "event_groups_pruned": 0,
        "elapsed_s": 0.0,
    }

    if dry_run or not post_ids:
        return result

    t0 = time.monotonic()

    with con:  # 单事务：三表同删 + 事件组修剪，失败整体回滚
        result["comments_deleted"] = _delete_in_batches(con, "post_comments", "post_id", post_ids)
        result["analyzed_deleted"] = _delete_in_batches(con, "analyzed_posts", "post_id", post_ids)
        result["posts"] = _delete_in_batches(con, "raw_posts", "id", post_ids)
        result["event_groups_pruned"] = prune_event_groups(con, set(post_ids))
    result["elapsed_s"] = round(time.monotonic() - t0, 2)
    if own:
        con.close()
    return result


def _print_report(r: dict) -> None:
    mode = "[DRY-RUN] " if r["dry_run"] else ""
    print(f"{mode}保留线 {r['retention_days']} 天（cutoff {r['cutoff']}）：将删/已删帖 {r['posts']}")
    for name, d in sorted(r["per_vehicle"].items()):
        print(f"  {name}: {d['posts']} 帖（最老 {d['oldest']}）")
    if r["paused_kept"]:
        kept = ", ".join(f"{k} {v}" for k, v in sorted(r["paused_kept"].items()))
        print(f"  [paused 豁免] 存量保留: {kept}")
    if not r["dry_run"]:
        print(f"[CLEANUP] 删帖 {r['posts']} / 评论 {r['comments_deleted']} / "
              f"分析行 {r['analyzed_deleted']} / 修剪事件组 {r['event_groups_pruned']}，"
              f"耗时 {r['elapsed_s']}s")
    refs = r["references"]
    for eg in refs["event_groups"]:
        print(f"  [WARN][引用] event_group「{eg['event_tag']}」({eg['start']}~{eg['end']}) "
              f"{eg['dangling']}/{eg['total']} 帖将悬空")
    for wi in refs["watch_items"]:
        print(f"  [WARN][引用] 用户关注项「{wi['title']}」(source_ref={wi['source_ref']}) 将悬空")


def main() -> int:
    ap = argparse.ArgumentParser(description="30 天保留线老帖物理清理（R40/R42）")
    ap.add_argument("--dry-run", action="store_true", help="只列清单统计，不删")
    ap.add_argument("--vehicle", default="", help="按车名子串过滤（空=全部）")
    ap.add_argument("--retention-days", type=int, default=None,
                    help="临时覆盖保留线（默认 env POST_RETENTION_DAYS=30）")
    ap.add_argument("--prune-only", action="store_true",
                    help="只修事件表悬空引用/post_count（不删任何帖，无需 LIVE 门）")
    args = ap.parse_args()
    if args.prune_only:
        try:
            con = _connect(db_path())
            try:
                stats = prune_dangling_refs(con, dry_run=args.dry_run)
            finally:
                con.close()
        except Exception as e:  # noqa: BLE001
            print(f"[ERROR] prune-only 失败: {e}")
            return 1
        mode = "[DRY-RUN] " if stats["dry_run"] else ""
        print(f"{mode}[PRUNE-ONLY] 扫描事件组 {stats['groups_scanned']}：修剪 "
              f"{stats['groups_pruned']} 组（剔除悬空 id {stats['ids_removed']} 个），"
              f"post_count 对齐 {stats['counts_fixed']} 组")
        return 0
    try:
        r = run_cleanup(dry_run=args.dry_run, vehicle=args.vehicle,
                        retention_days=args.retention_days)
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] 清理失败: {e}")
        return 1
    _print_report(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
