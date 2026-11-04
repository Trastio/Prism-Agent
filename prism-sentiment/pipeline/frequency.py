"""频率分层纯函数（从 scripts/daily_update.py 抽离）。

P1-1 照搬原则：常量/逻辑/SQL 与 daily_update.py 逐字一致，不擅自改阈值/排期。
API 层（fleet.py）导入此模块，不 import scripts，避免同步阻塞 + 模块副作用。
"""
import os
import sqlite3
from datetime import date, timedelta
from typing import Literal

Tier = Literal["hot", "mid", "cold"]

# P1-1：照搬 daily_update.py:46-47 真实常量（审查 v5 §9.3 逐字核验通过）
HOT_THRESHOLD = 100   # 日更
MID_THRESHOLD = 30    # 隔日（偶数日）


def db_path() -> str:
    """DB 路径（P2-2：从 daily_update.py:50-51 抽出，逐字一致）。"""
    return os.getenv("DB_PATH", "data/vehicle_sentiment.db")


def recent_post_counts(vehicle_ids: list[str], db_path_str: str | None = None) -> dict[str, int]:
    """同步查近30天帖数（sqlite3）。调用方用 asyncio.to_thread 包裹避免阻塞事件循环。

    与 daily_update.py:54-73 _recent_post_counts 逐字一致。
    失败返回全 0（按 cold 兜底，不阻断）。
    """
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    out = {vid: 0 for vid in vehicle_ids}
    try:
        conn = sqlite3.connect(db_path_str or db_path())
        try:
            rows = conn.execute(
                "SELECT vehicle_id, COUNT(*) FROM raw_posts "
                "WHERE collected_at >= ? GROUP BY vehicle_id",
                (cutoff,),
            ).fetchall()
            for vid, cnt in rows:
                if vid in out:
                    out[vid] = cnt
        finally:
            conn.close()
    except Exception as e:
        print(f"[WARN] 近30天帖数查询失败（按 cold 兜底）: {e}")
    return out


def _tier_of(cnt: int) -> Tier:
    """P1-1：照搬 daily_update.py:76-81，> 不是 >=。"""
    if cnt > HOT_THRESHOLD:
        return "hot"
    if cnt > MID_THRESHOLD:
        return "mid"
    return "cold"


def select_by_frequency(
    vehicles: list[dict],
    counts: dict[str, int],
    today: date,
) -> tuple[list[dict], list[tuple[str, Tier]]]:
    """频率分层：hot 日更/mid 隔日（偶数日）/cold 周一。返回 (targets, skipped)。

    P1-1：照搬 daily_update.py:84-100 排期逻辑（today.day % 2 == 0，非 weekday()）。
    counts 由调用方传入（纯函数，不在内部查库）。
    """
    active = [v for v in vehicles if v.get("status") == "active"]
    targets, skipped = [], []
    for v in active:
        tier = _tier_of(counts.get(v["id"], 0))
        run = (
            tier == "hot"
            or (tier == "mid" and today.day % 2 == 0)
            or (tier == "cold" and today.weekday() == 0)  # 周一
        )
        if run:
            targets.append(v)
        else:
            skipped.append((v["name"], tier))
    return targets, skipped
