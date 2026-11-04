"""统一查询构造器 + 时间窗 helper（Phase 3 T3.2/T3.4）。

所有口碑端点 SHALL 经 scoped_posts 出参，避免手工挂载口径常量导致漂移。
v3 报告 §6.5：引入统一查询构造器是口径收敛的治本方案。
"""
from datetime import datetime, timedelta

from sqlalchemy import select, func

from models.schemas import RawPost, LISTING_CALIBER


def scoped_posts(
    vehicle_id: str,
    caliber: tuple = LISTING_CALIBER,
    *,
    start: str | None = None,
    end: str | None = None,
) -> select:
    """统一口径查询构造器。

    Args:
        vehicle_id: 车辆 ID
        caliber: 口径常量元组，默认 LISTING_CALIBER（SELF_ONLY + AUTHENTIC_AUTHOR + RELEVANT_ONLY）
        start: 起始日期 ISO 字符串（含），用 coalesce(published_at, collected_at) 比较
        end: 结束日期 ISO 字符串（含），实际比较 < end+1天

    Returns:
        select(RawPost) 语句，已挂口径 + 时间窗
    """
    stmt = select(RawPost).where(RawPost.vehicle_id == vehicle_id, *caliber)
    if start:
        stmt = stmt.where(
            func.coalesce(RawPost.published_at, RawPost.collected_at) >= datetime.fromisoformat(start)
        )
    if end:
        stmt = stmt.where(
            func.coalesce(RawPost.published_at, RawPost.collected_at)
            < datetime.fromisoformat(end) + timedelta(days=1)
        )
    return stmt


def time_window_filter(
    start: str | None = None,
    end: str | None = None,
) -> list:
    """统一时间窗条件列表（coalesce 兜底 NULL published_at）。

    Returns:
        SQLAlchemy where 条件列表，空列表表示无时间窗。
    """
    conds = []
    if start:
        conds.append(
            func.coalesce(RawPost.published_at, RawPost.collected_at) >= datetime.fromisoformat(start)
        )
    if end:
        conds.append(
            func.coalesce(RawPost.published_at, RawPost.collected_at)
            < datetime.fromisoformat(end) + timedelta(days=1)
        )
    return conds
