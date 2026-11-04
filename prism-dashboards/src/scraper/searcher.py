"""车型搜索器 — 直接使用汽车之家内部 API"""
import logging
from src.api.autohome_api import get_autohome_api

logger = logging.getLogger(__name__)


class ModelSearcher:
    async def search(self, keyword: str) -> list[dict]:
        """搜索车型，使用内部 API 本地索引匹配"""
        try:
            api = await get_autohome_api()
            results = await api.search_series(keyword, limit=10)
            if results:
                return results
        except Exception as e:
            logger.warning(f"API search failed: {e}")

        return []
