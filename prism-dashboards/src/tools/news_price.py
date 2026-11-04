"""资讯搜索与经销商报价工具"""
import logging
import re

logger = logging.getLogger(__name__)


async def search_news(keyword: str, model_id: str | None = None) -> dict:
    """搜索汽车资讯/评测文章。

    传入 model_id 可获取更精准的车型相关资讯。

    Args:
        keyword: 搜索关键词
        model_id: 车系 ID（可选，传入后优先使用车型专属资讯）

    Returns:
        articles: 资讯列表 [{title, url, date, summary}]
    """
    if model_id:
        try:
            from src.api.autohome_api import get_autohome_api
            api = await get_autohome_api()
            result = await api.search_news(model_id, keyword=keyword)
            if result.get("articles"):
                article_count = len(result.get("articles", []))
                result["data_source"] = f"汽车之家资讯API（{article_count}条结果）"
                return result
        except Exception as e:
            logger.warning(f"API search_news failed: {e}")

    try:
        from src.search.engine import get_search_engine
        engine = get_search_engine()
        results = await engine.search(f"{keyword} 汽车 资讯", num_results=10)
        articles = []
        sources = set()
        for r in results:
            if r.title and len(r.title) > 4:
                articles.append({
                    "title": r.title,
                    "url": r.url,
                    "date": "",
                    "summary": r.description[:200] if r.description else "",
                })
                sources.add(r.source)
        if articles:
            src_label = "+".join(sorted(sources)) if sources else "搜索引擎"
            return {
                "articles": articles,
                "keyword": keyword,
                "count": len(articles),
                "data_source": f"{src_label}（{len(articles)}条结果）",
            }
    except Exception as e:
        logger.warning(f"搜索引擎查询失败: {e}")

    return {"error": "资讯搜索暂不可用", "articles": [], "keyword": keyword, "count": 0,
            "data_source": "暂无数据源"}


async def get_dealer_price(model_id: str, city: str = "") -> dict:
    """查询经销商报价（各版本指导价列表）。

    Args:
        model_id: 车系 ID
        city: 城市名称（可选，默认全国）

    Returns:
        price_list: 各版本报价 [{spec_id, name, guide_price}]
    """
    try:
        from src.api.autohome_api import get_autohome_api
        api = await get_autohome_api()
        specs = await api.get_series_specs(model_id)
        if specs:
            priced = [s for s in specs if s.get("price")]
            if priced:
                prices = []
                for s in priced:
                    price_str = s.get("price", "")
                    nums = re.findall(r'[\d.]+', price_str)
                    if nums:
                        prices.append({
                            "spec_id": s.get("spec_id", ""),
                            "name": s.get("name", ""),
                            "guide_price": price_str,
                        })

                if prices:
                    return {
                        "model_id": model_id,
                        "city": city or "全国",
                        "price_list": prices[:20],
                        "price_count": len(prices),
                        "data_source": f"汽车之家内部API（{len(prices)}个版本报价）",
                        "note": "指导价来自汽车之家内部API，具体优惠以经销商实际报价为准",
                    }
    except Exception as e:
        logger.warning(f"get_series_specs 获取报价失败: {e}")

    try:
        from src.api.autohome_api import get_autohome_api
        api = await get_autohome_api()
        info = await api.get_series_info(model_id)
        dealer_prices = info.get("dealerPrices_data")
        if dealer_prices:
            return {
                "model_id": model_id,
                "city": city or "全国",
                "dealer_prices": dealer_prices,
                "data_source": "汽车之家配置页嵌入数据",
                "note": "具体优惠以经销商实际报价为准",
            }
    except Exception as e:
        logger.warning(f"get_series_info 获取报价也失败: {e}")

    return {"error": "无法获取经销商报价", "model_id": model_id, "data_source": "暂无数据源"}
