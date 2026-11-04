import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import get_session
from models.schemas import Vehicle, VehicleCreate, VehicleUpdate, VehicleResponse

router = APIRouter(prefix="/api/vehicles", tags=["vehicles"])

_BRAND_PATTERNS = [
    ("特斯拉", ["Model 3", "Model Y", "Model S", "Model X", "特斯拉"]),
    ("比亚迪", ["元", "宋", "唐", "秦", "汉", "海豚", "海豹", "海鸥", "驱逐舰", "护卫舰", "腾势", "方程豹"]),
    ("理想", ["理想", "L6", "L7", "L8", "L9", "MEGA"]),
    ("问界", ["问界", "AITO"]),
    ("蔚来", ["蔚来", "ET", "ES", "EC"]),
    ("小鹏", ["小鹏"]),
    ("极氪", ["极氪"]),
    ("领克", ["领克"]),
    ("零跑", ["零跑", "C01", "C11", "C10", "T03"]),
    ("长安", ["逸动", "UNI", "CS", "深蓝", "阿维塔"]),
    ("吉利", ["星瑞", "星越", "博越", "帝豪", "银河", "几何"]),
    ("奇瑞", ["艾瑞泽", "瑞虎", "星途", "iCAR", "智界"]),
    ("长城", ["哈弗", "坦克", "魏牌", "欧拉"]),
    ("广汽", ["传祺", "埃安", "昊铂"]),
    ("宝马", ["宝马", "i3", "iX", "i4"]),
    ("奔驰", ["奔驰", "EQ"]),
    ("奥迪", ["奥迪", "e-tron"]),
    ("丰田", ["凯美瑞", "卡罗拉", "RAV4", "汉兰达", "赛那", "bZ"]),
    ("本田", ["雅阁", "思域", "CR-V", "皓影", "型格"]),
    ("大众", ["朗逸", "帕萨特", "迈腾", "途观", "ID"]),
    ("宝骏", ["宝骏", "云朵"]),
    ("上汽", ["荣威", "名爵", "飞凡", "智己"]),
    ("一汽", ["红旗", "奔腾"]),
    ("东风", ["岚图", "风神"]),
    ("北汽", ["极狐", "BEIJING"]),
]


def _detect_brand(name: str) -> str:
    for brand, prefixes in _BRAND_PATTERNS:
        if name == brand:
            return brand
        if any(name.startswith(p) or name == p for p in prefixes):
            return brand
    return ""


def _to_resp(v: Vehicle) -> dict:
    return {
        "id": v.id, "name": v.name, "brand": v.brand,
        "search_keywords": v.search_keywords,
        "lifecycle_anchors": v.lifecycle_anchors,
        "competitor_ids": v.competitor_ids,
        "status": v.status,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
    }


@router.post("", response_model=VehicleResponse)
async def create_vehicle(data: VehicleCreate, session: AsyncSession = Depends(get_session)):
    # Auto-fill brand if not provided
    brand = data.brand
    if not brand and data.name:
        brand = _detect_brand(data.name)
    # Auto-fill search_keywords from name if not provided
    kw = data.search_keywords
    if not kw and data.name:
        kw = [data.name]
    v = Vehicle(
        id=str(uuid.uuid4()), name=data.name, brand=brand,
        search_keywords=json.dumps(kw, ensure_ascii=False) if kw else None,
        lifecycle_anchors=json.dumps(data.lifecycle_anchors, ensure_ascii=False) if data.lifecycle_anchors else None,
        competitor_ids=json.dumps(data.competitor_ids, ensure_ascii=False) if data.competitor_ids else None,
    )
    session.add(v)
    await session.commit()
    await session.refresh(v)
    return _to_resp(v)


@router.get("", response_model=list[VehicleResponse])
async def list_vehicles(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Vehicle).where(Vehicle.status == "active"))
    return [_to_resp(v) for v in result.scalars().all()]


@router.get("/search", response_model=list[VehicleResponse])
async def search_vehicles(q: str = Query(..., min_length=1), session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Vehicle).where(Vehicle.status == "active", (Vehicle.name.contains(q) | Vehicle.brand.contains(q)))
    )
    return [_to_resp(v) for v in result.scalars().all()]


@router.get("/suggest")
async def suggest_vehicle(q: str = Query(..., min_length=1)):
    """汽车之家车系联想 — A+B 车型校验/输入联想的数据源。
    输入车型名关键词，返回真实车系 [{name, brand, series_id, price_range, level}]。
    用于加车型时强制从真实车系选（杜绝'铂智3X 填成铂金'类错误）。"""
    from utils.autohome_api import get_autohome_api  # noqa: inline-import
    try:
        api = await get_autohome_api()
        results = await api.search_series(q, limit=8)
        return [{
            "name": r.get("name", ""),
            "brand": r.get("brand_name", ""),
            "series_id": r.get("series_id", ""),
            "price_range": r.get("price_range", ""),
            "level": r.get("level", ""),
        } for r in results]
    except Exception as e:
        raise HTTPException(503, detail=f"车型库暂不可用: {e}")


@router.get("/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(vehicle_id: str, session: AsyncSession = Depends(get_session)):
    v = await session.get(Vehicle, vehicle_id)
    if not v:
        raise HTTPException(404, detail="Vehicle not found")
    return _to_resp(v)


@router.put("/{vehicle_id}", response_model=VehicleResponse)
async def update_vehicle(vehicle_id: str, data: VehicleUpdate, session: AsyncSession = Depends(get_session)):
    v = await session.get(Vehicle, vehicle_id)
    if not v:
        raise HTTPException(404, detail="Vehicle not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        if field in ("search_keywords", "lifecycle_anchors", "competitor_ids") and value is not None:
            value = json.dumps(value, ensure_ascii=False)
        setattr(v, field, value)
    await session.commit()
    await session.refresh(v)
    return _to_resp(v)


@router.delete("/{vehicle_id}")
async def delete_vehicle(vehicle_id: str, session: AsyncSession = Depends(get_session)):
    v = await session.get(Vehicle, vehicle_id)
    if not v:
        raise HTTPException(404, detail="Vehicle not found")
    v.status = "deleted"
    await session.commit()
    return {"status": "deleted"}


@router.put("/{vehicle_id}/lifecycle", response_model=VehicleResponse)
async def update_lifecycle(vehicle_id: str, anchors: dict, session: AsyncSession = Depends(get_session)):
    v = await session.get(Vehicle, vehicle_id)
    if not v:
        raise HTTPException(404, detail="Vehicle not found")
    v.lifecycle_anchors = json.dumps(anchors, ensure_ascii=False)
    await session.commit()
    await session.refresh(v)
    return _to_resp(v)


@router.put("/{vehicle_id}/competitors", response_model=VehicleResponse)
async def update_competitors(vehicle_id: str, competitor_ids: list[str], session: AsyncSession = Depends(get_session)):
    v = await session.get(Vehicle, vehicle_id)
    if not v:
        raise HTTPException(404, detail="Vehicle not found")
    v.competitor_ids = json.dumps(competitor_ids, ensure_ascii=False)
    await session.commit()
    await session.refresh(v)
    return _to_resp(v)
