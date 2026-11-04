"""从 data/config_snapshots/*.json 批量迁入 config_snapshots 表。"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def migrate_snapshots(snap_dir: str = "data/config_snapshots") -> int:
    from src.storage.db import session_scope
    from src.models.orm import upsert_config_snapshot
    # init_db() 由调用方负责（tmp_db fixture 已 init；__main__ 块自行调用）
    count = 0
    with session_scope() as s:
        for fn in sorted(os.listdir(snap_dir)):
            if not fn.endswith(".json"):
                continue
            with open(os.path.join(snap_dir, fn), "r", encoding="utf-8") as f:
                snap = json.load(f)
            sid = snap["series_id"]
            data = {
                "series_name": snap.get("name"),
                "maker": snap.get("maker"),
                "energy": snap.get("energy"),
                "level": snap.get("level"),
                "price_range": snap.get("price_range"),
                "categories": snap.get("categories", {}),
                "fetched_at": snap.get("fetched_at"),
            }
            upsert_config_snapshot(s, sid, data)
            count += 1
    return count


if __name__ == "__main__":
    from src.storage.db import init_db
    init_db()
    n = migrate_snapshots()
    print(f"迁入 {n} 个快照")
