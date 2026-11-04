"""口碑工具的自然语言输入归一化层。

把用户口语化的地域/年款/版型表述归一化为工具可查询的结构化输入，
消除"北方→0条""新款→ValueError"等问题。纯函数、无外部依赖。
"""
import logging

logger = logging.getLogger(__name__)

# 城市 → 大区（单一数据源；regional_analysis 复用）
CITY_TO_REGION: dict[str, str] = {
    "北京": "华北", "天津": "华北", "石家庄": "华北", "太原": "华北", "济南": "华北", "青岛": "华北",
    "上海": "华东", "南京": "华东", "杭州": "华东", "苏州": "华东", "合肥": "华东", "宁波": "华东", "无锡": "华东",
    "广州": "华南", "深圳": "华南", "东莞": "华南", "佛山": "华南", "珠海": "华南",
    "成都": "西南", "重庆": "西南", "西安": "西北", "武汉": "华中", "长沙": "华中", "郑州": "华中",
    "沈阳": "东北", "大连": "东北", "长春": "东北", "哈尔滨": "东北",
}

# 大区 → 城市集（反向索引）
REGION_TO_CITIES: dict[str, list[str]] = {}
for _c, _r in CITY_TO_REGION.items():
    REGION_TO_CITIES.setdefault(_r, []).append(_c)

# 方位词 → 大区集
_DIRECTION_REGIONS: dict[str, list[str]] = {
    "北方": ["华北", "东北", "西北"],
    "北方地区": ["华北", "东北", "西北"],
    "南方": ["华南", "华东", "华中"],
    "南方地区": ["华南", "华东", "华中"],
}

# 经济圈/俗称 → 城市集
_AGGREGATIONS: dict[str, list[str]] = {
    "江浙沪": ["上海", "南京", "杭州", "苏州", "宁波", "无锡"],
    "长三角": ["上海", "南京", "杭州", "苏州", "宁波", "无锡", "合肥"],
    "大湾区": ["广州", "深圳", "东莞", "佛山", "珠海"],
    "珠三角": ["广州", "深圳", "东莞", "佛山", "珠海"],
    "东北": ["沈阳", "大连", "长春", "哈尔滨"],
    "东三省": ["沈阳", "大连", "长春", "哈尔滨"],
}


def resolve_region(text: str) -> dict:
    """将地域口语表述归一化为城市列表。

    Returns:
        {cities: [...], regions: [...], low_confidence: bool, matched_as: str}
        matched_as: "direction"|"aggregation"|"region"|"city"|"unknown"|"empty"

    解析顺序：方位(北方/南方) → 经济圈(江浙沪/大湾区/东北) → 7大区 → 单城市 → 未识别(字面+low_confidence)
    """
    if not text or not text.strip():
        return {"cities": [], "regions": [], "low_confidence": False, "matched_as": "empty"}

    t = text.strip().replace("市", "")

    if t in _DIRECTION_REGIONS:
        regions = _DIRECTION_REGIONS[t]
        cities = [c for r in regions for c in REGION_TO_CITIES.get(r, [])]
        return {"cities": cities, "regions": regions, "low_confidence": False, "matched_as": "direction"}

    if t in _AGGREGATIONS:
        cities = _AGGREGATIONS[t]
        regions = sorted({CITY_TO_REGION[c] for c in cities if c in CITY_TO_REGION})
        return {"cities": cities, "regions": regions, "low_confidence": False, "matched_as": "aggregation"}

    if t in REGION_TO_CITIES:
        return {"cities": REGION_TO_CITIES[t], "regions": [t], "low_confidence": False, "matched_as": "region"}

    if t in CITY_TO_REGION:
        return {"cities": [t], "regions": [CITY_TO_REGION[t]], "low_confidence": False, "matched_as": "city"}

    # 未识别 → 字面当城市查 + 标记低置信
    return {"cities": [t], "regions": [], "low_confidence": True, "matched_as": "unknown"}


from datetime import datetime
import re


def _purchase_to_year(purchase_date) -> str | None:
    """购买日期 → 年款（9月后购车算次年款，与 year_analysis._estimate_model_year 一致）。"""
    if not purchase_date:
        return None
    try:
        if isinstance(purchase_date, str):
            purchase_date = datetime.strptime(purchase_date, "%Y-%m-%d")
        y, m = purchase_date.year, purchase_date.month
        return f"{y + 1}款" if m >= 9 else f"{y}款"
    except (ValueError, TypeError):
        return None


async def _year_extreme(model_id: str, latest: bool) -> str | None:
    """查该车系最新/最早年款（基于 purchase_date 推算）。"""
    from src.storage.db import session_scope
    from src.models.orm import OwnerReview
    with session_scope() as s:
        rows = s.query(OwnerReview.purchase_date).filter(
            OwnerReview.model_id == model_id,
            OwnerReview.purchase_date.isnot(None)
        ).all()
    years = sorted({y for r in rows if r[0] for y in [_purchase_to_year(r[0])] if y})
    return (years[-1] if latest else years[0]) if years else None


async def resolve_year(text: str, model_id: str) -> str | None:
    """将年款口语表述归一化为标准年款（如"2024款"）。

    "新款"/"最新款"→该车型最新年款；"老款"/"旧款"→最早；纯数字"2024"→"2024款"。
    无法解析→返回 None（调用方应回退到全国/全年款对比，不得 crash）。
    """
    if not text or not text.strip():
        return None
    t = text.strip()
    if re.fullmatch(r"\d{4}", t):
        return f"{t}款"
    if re.fullmatch(r"\d{4}款", t):
        return t
    if t in ("新款", "最新款", "新一代", "最新"):
        return await _year_extreme(model_id, latest=True)
    if t in ("老款", "旧款", "老一代", "最早"):
        return await _year_extreme(model_id, latest=False)
    return None


# 版型口语词 → spec_name 关键词模式（基础版；精确价格推断见 design Open Question 1）
_SPEC_KEYWORDS: dict[str, list[str]] = {
    "长续航": ["620", "700", "长续航", "长程"],
    "标准续航": ["510", "400", "标准"],
    "低配": ["air", "标准", "入门", "lite", "base"],
    "入门": ["air", "标准", "入门", "lite"],
    "高配": ["max", "旗舰", "性能", "pro+", "激光雷达"],
    "顶配": ["max", "旗舰", "性能", "激光雷达"],
}


async def resolve_spec(text: str, model_id: str) -> dict:
    """版型口语表述 → 该车系实际 spec_name 的模糊匹配。

    Returns:
        {spec_name: str, low_confidence: bool, all_matches: [...]}
    基础版：关键词组(长续航/高配/...) + 字面包含。未匹配→原样 + low_confidence。
    """
    if not text or not text.strip():
        return {"spec_name": "", "low_confidence": False, "all_matches": []}
    t = text.strip()
    from src.storage.db import session_scope
    from src.models.orm import OwnerReview
    with session_scope() as s:
        specs = [r[0] for r in s.query(OwnerReview.spec_name).filter(
            OwnerReview.model_id == model_id,
            OwnerReview.spec_name.isnot(None)
        ).distinct().all()]
    if not specs:
        return {"spec_name": t, "low_confidence": True, "all_matches": []}

    t_lower = t.lower()

    # 续航词 → 按 spec_name 里的 km 数字取最大/最小（比命名关键词可靠）
    km_specs = []
    for sp in specs:
        if not sp:
            continue
        m = re.search(r'(\d+)\s*km', sp.lower())
        if m:
            km_specs.append((sp, int(m.group(1))))
    if t_lower in ("长续航", "长程", "最大续航") and km_specs:
        km_specs.sort(key=lambda x: x[1], reverse=True)
        top_km = km_specs[0][1]
        top = [sp for sp, km in km_specs if km == top_km]
        return {"spec_name": top[0], "low_confidence": False, "all_matches": top}
    if t_lower in ("标准续航", "短续航", "最小续航") and km_specs:
        km_specs.sort(key=lambda x: x[1])
        bot_km = km_specs[0][1]
        bot = [sp for sp, km in km_specs if km == bot_km]
        return {"spec_name": bot[0], "low_confidence": False, "all_matches": bot}

    for key, patterns in _SPEC_KEYWORDS.items():
        if t_lower == key:
            matched = [sp for sp in specs if any(p in (sp or "").lower() for p in patterns)]
            if matched:
                return {"spec_name": matched[0], "low_confidence": False, "all_matches": matched}

    direct = [sp for sp in specs if t in (sp or "")]
    if direct:
        return {"spec_name": direct[0], "low_confidence": False, "all_matches": direct}

    return {"spec_name": t, "low_confidence": True, "all_matches": []}
