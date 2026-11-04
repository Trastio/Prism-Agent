"""车型搜索 — 汽车之家内部 API 为主，Tavily/DDG 为辅"""
import re
import time
import logging
from src.search.engine import get_search_engine

logger = logging.getLogger(__name__)

_SEARCH_CACHE: dict[str, tuple[float, dict]] = {}
_SEARCH_CACHE_TTL = 600
_DETAIL_CACHE: dict[str, tuple[float, dict]] = {}
_DETAIL_CACHE_TTL = 900
_GENERATIONS_CACHE: dict[str, tuple[float, dict]] = {}
_GENERATIONS_CACHE_TTL = 1800
_SIMILAR_CACHE: dict[str, tuple[float, dict]] = {}
_SIMILAR_CACHE_TTL = 1800

_AUTOHOME_PATTERNS = [r'/series/(\d+)/', r'/(\d{4,})/', r'/spec/(\d+)/']


def _extract_series_id(url: str) -> str | None:
    for pat in _AUTOHOME_PATTERNS:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


async def _search_autohome_api(keyword: str, brand: str = "",
                               price_min: float = 0, price_max: float = 0,
                               segment: str = "", energy: str = "") -> list[dict]:
    try:
        from src.api.autohome_api import get_autohome_api
        api = await get_autohome_api()

        search_keyword = f"{brand} {keyword}".strip() if brand else keyword
        results = await api.search_series(
            search_keyword, limit=20,
            price_min=price_min, price_max=price_max,
            level=segment, energy=energy,
        )

        if results:
            return results

        if brand:
            results = await api.search_series(
                keyword, limit=20,
                price_min=price_min, price_max=price_max,
                level=segment, energy=energy,
            )
            if results:
                return results

        if not keyword and (price_min > 0 or price_max > 0 or segment or energy):
            results = await api.search_series(
                "", limit=20,
                price_min=price_min, price_max=price_max,
                level=segment, energy=energy,
            )
            if results:
                return results

        return []
    except Exception as e:
        logger.warning(f"Autohome API search failed: {e}")
        return []


async def _search_external(keyword: str) -> list[dict]:
    brand_free = keyword.strip()
    query = f"{brand_free} 汽车之家 配置 口碑".strip()
    if not query or query == "汽车之家 配置 口碑":
        return []

    engine = get_search_engine()
    try:
        search_results = await engine.search(query, num_results=8)
    except Exception as e:
        logger.warning(f"External search failed: {e}")
        return []

    results = []
    seen = set()
    for r in search_results:
        href = r.url
        if "autohome.com.cn" not in href:
            continue
        sid = _extract_series_id(href)
        if not sid or sid in seen:
            continue
        seen.add(sid)
        name = r.title[:60] if r.title else f"series_{sid}"
        name = re.sub(r'\s+', ' ', name).strip()
        results.append({
            "series_id": sid,
            "name": name,
            "url": href,
            "description": r.description[:200] if r.description else "",
            "source": r.source,
        })
    return results


async def search_cars(keyword: str = "", price_min: int = 0, price_max: int = 10000000,
                       segment: str = "", energy: str = "", brand: str = "") -> dict:
    """搜索车型，返回匹配的车型列表。

    支持按关键词、品牌、价格范围、车型级别、能源类型筛选，
    可组合使用多个条件。价格单位为元（如 100000 = 10万）。

    Args:
        keyword: 车型名称或关键词（如"元UP"、"比亚迪 海豚"）
        price_min: 最低价格（元），0 表示不限
        price_max: 最高价格（元），默认不限
        segment: 车型级别（如"SUV"、"轿车"、"MPV"）
        energy: 能源类型（如"纯电"、"混动"、"燃油"）
        brand: 品牌名称（如"比亚迪"、"特斯拉"）

    Returns:
        models: 车型列表（含 series_id、name、price_range 等）
        count: 匹配数量
    """
    note_parts = []

    if not keyword.strip() and not segment and not energy and price_min == 0 and price_max == 10000000:
        return {"models": [], "count": 0, "note": "请提供车型名称或筛选条件", "use_knowledge": True}

    cache_key = f"{keyword}:{brand}:{price_min}:{price_max}:{segment}:{energy}"
    cached = _SEARCH_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _SEARCH_CACHE_TTL:
        return cached[1]

    all_results = []

    price_min_wan = price_min / 10000 if price_min > 0 else 0
    price_max_wan = price_max / 10000 if price_max < 10000000 else 0

    api_results = await _search_autohome_api(
        keyword, brand,
        price_min=price_min_wan, price_max=price_max_wan,
        segment=segment, energy=energy,
    )
    if api_results:
        all_results.extend(api_results)
        note_parts.append("来源：汽车之家内部API")
    else:
        external_results = await _search_external(keyword)
        if external_results:
            all_results.extend(external_results)
            note_parts.append("来源：外部搜索引擎")
        else:
            encoded = keyword
            note_parts.append(f"搜索暂时不可用，请手动搜索: https://sou.autohome.com.cn/zonghe?q={encoded}")
            return {"models": [], "count": 0, "note": " | ".join(note_parts),
                    "use_knowledge": True, "stop_searching": True}

    if all_results:
        seen = set()
        deduped = []
        for m in all_results:
            if m["series_id"] not in seen:
                seen.add(m["series_id"])
                deduped.append(m)

        if price_min > 0 or price_max < 10000000:
            filtered = []
            for m in deduped:
                p = m.get("price_range", "")
                if not p:
                    filtered.append(m)
                    continue
                nums = re.findall(r'[\d.]+', p)
                if nums:
                    low = float(nums[0])
                    high = float(nums[-1]) if len(nums) > 1 else low
                    if low <= price_max / 10000 and high >= price_min / 10000:
                        filtered.append(m)
                else:
                    filtered.append(m)
            deduped = filtered

        rv = {"models": deduped[:20], "count": len(deduped[:20])}
        if note_parts:
            rv["note"] = " | ".join(note_parts)
            rv["data_source"] = " | ".join(note_parts)
        _SEARCH_CACHE[cache_key] = (time.time(), rv)
        return rv

    return {
        "models": [], "count": 0, "use_knowledge": True, "stop_searching": True,
        "note": f"未在汽车之家找到「{keyword}」的相关车型。"
                f"如需要，建议用户手动访问: https://sou.autohome.com.cn/zonghe?q={keyword}",
    }


async def get_model_detail(model_id: str) -> dict:
    """获取车型详情，包含指导价、级别、能源类型、综合评分、各维度得分、PPH 等。

    Args:
        model_id: 车系 ID（series_id）
    """
    cached = _DETAIL_CACHE.get(model_id)
    if cached and (time.time() - cached[0]) < _DETAIL_CACHE_TTL:
        return cached[1]

    try:
        from src.api.autohome_api import get_autohome_api
        api = await get_autohome_api()
        detail = await api.get_model_detail(model_id)
        if detail and "error" not in detail:
            detail["data_source"] = "汽车之家实时数据"
            _DETAIL_CACHE[model_id] = (time.time(), detail)
            return detail
        if detail and "error" in detail:
            logger.warning(f"API get_model_detail failed: {detail.get('error')}")
    except Exception as e:
        logger.warning(f"Autohome API get_model_detail failed: {e}")

    result = {"error": "无法获取车型信息", "model_id": model_id,
              "data_source": "暂无数据源"}
    _DETAIL_CACHE[model_id] = (time.time(), result)
    return result


async def get_model_generations(series_id: str) -> dict:
    """查询车系的年款/换代历史，返回各代年款信息。

    Args:
        series_id: 车系 ID
    """
    cached = _GENERATIONS_CACHE.get(series_id)
    if cached and (time.time() - cached[0]) < _GENERATIONS_CACHE_TTL:
        return cached[1]

    try:
        from src.api.autohome_api import get_autohome_api
        api = await get_autohome_api()
        result = await api.get_model_generations(series_id)
        _GENERATIONS_CACHE[series_id] = (time.time(), result)
        return result
    except Exception as e:
        logger.error(f"get_model_generations error: {e}")
        return {"error": str(e), "series_id": series_id}


async def get_similar_models(series_id: str, limit: int = 8) -> dict:
    """获取同级别竞品/相似车型列表。

    Args:
        series_id: 车系 ID
        limit: 返回数量上限
    """
    cache_key = f"{series_id}:{limit}"
    cached = _SIMILAR_CACHE.get(cache_key)
    if cached and (time.time() - cached[0]) < _SIMILAR_CACHE_TTL:
        return cached[1]

    try:
        from src.api.autohome_api import get_autohome_api
        api = await get_autohome_api()
        result = await api.get_similar_models(series_id, limit)
        _SIMILAR_CACHE[cache_key] = (time.time(), result)
        return result
    except Exception as e:
        logger.error(f"get_similar_models error: {e}")
        return {"error": str(e), "series_id": series_id}
