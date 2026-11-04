"""手动关注清单路由（openspec: watch-list）。

纯人工标记，无状态机——用户在看板信号旁点"关注"后落库 WatchItem。
只存线索元数据 + 来源信号锚点，不存状态（舆情不会"平息"）。
"""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_session
from models.schemas import WatchItem
from api.routes.dashboard import _get_vehicle_or_404

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class WatchItemCreate(BaseModel):
    title: str
    source_type: Literal["hot_post", "complaint", "defect_cluster", "event"]
    source_ref: str | None = None
    post_count: int = 0
    first_seen: date
    note: str | None = None


@router.post("/{vehicle_id}")
async def add_watchitem(
    vehicle_id: str, body: WatchItemCreate,
    session: AsyncSession = Depends(get_session),
):
    await _get_vehicle_or_404(vehicle_id, session)
    # 去重（P1-8）：同 vehicle_id + source_ref 已存在则返回"已关注"不重复 add
    if body.source_ref:
        existing = await session.execute(
            select(WatchItem.id).where(
                WatchItem.vehicle_id == vehicle_id,
                WatchItem.source_ref == body.source_ref,
            )
        )
        if existing.first():
            return {"id": existing.first()[0], "title": body.title, "duplicate": True}
    item = WatchItem(
        vehicle_id=vehicle_id,
        title=body.title,
        source_type=body.source_type,
        source_ref=body.source_ref,
        post_count=body.post_count,
        first_seen=body.first_seen,
        note=body.note,
    )
    session.add(item)
    await session.commit()
    return {"id": item.id, "title": item.title}


@router.get("/{vehicle_id}")
async def list_watchitems(
    vehicle_id: str, session: AsyncSession = Depends(get_session),
):
    await _get_vehicle_or_404(vehicle_id, session)
    rows = await session.execute(
        select(WatchItem).where(WatchItem.vehicle_id == vehicle_id)
        .order_by(WatchItem.first_seen.desc(), WatchItem.created_at.desc())
    )
    return [
        {
            "id": w.id, "title": w.title, "source_type": w.source_type,
            "source_ref": w.source_ref, "post_count": w.post_count,
            "first_seen": str(w.first_seen), "note": w.note or "",
        }
        for w in rows.scalars().all()
    ]


@router.delete("/{vehicle_id}/{item_id}")
async def delete_watchitem(
    vehicle_id: str, item_id: str,
    session: AsyncSession = Depends(get_session),
):
    await _get_vehicle_or_404(vehicle_id, session)
    await session.execute(
        delete(WatchItem).where(
            WatchItem.id == item_id, WatchItem.vehicle_id == vehicle_id
        )
    )
    await session.commit()
    return {"ok": True}
