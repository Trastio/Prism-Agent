"""T1.6 Tests: News Collector — Bocha/Anspire with dedup + config filter."""
import pytest
import pytest_asyncio
from unittest.mock import patch, AsyncMock, MagicMock
import httpx


async def test_search_all_no_keys():
    from pipeline.collectors.news_collector import NewsCollector
    with patch.object(NewsCollector, "__init__", lambda self: None):
        c = NewsCollector()
        c._bocha_key = ""
        c._anspire_key = ""
        assert await c.search_all("海豹", "2026-01-01", "2026-05-01") == []


async def test_search_all_dedup_by_url():
    from pipeline.collectors.news_collector import NewsCollector
    with patch.object(NewsCollector, "__init__", lambda self: None):
        c = NewsCollector()
        c._bocha_key = "key"
        c._anspire_key = "key"
        with patch.object(c, "search_bocha", return_value=[
            {"title": "A", "url": "http://x.com/1", "published_at": "2026-05-01", "source": "bocha", "platform": "news"},
            {"title": "B", "url": "http://x.com/2", "published_at": "2026-05-02", "source": "bocha", "platform": "news"},
        ]):
            with patch.object(c, "search_anspire", return_value=[
                {"title": "A dup", "url": "http://x.com/1", "published_at": "2026-05-01", "source": "anspire", "platform": "news"},
            ]):
                result = await c.search_all("海豹", "2026-01-01", "2026-05-01")
    urls = [r["url"] for r in result]
    assert len(urls) == 2 and len(set(urls)) == 2


async def test_search_all_does_not_call_tavily():
    from pipeline.collectors.news_collector import NewsCollector
    with patch.object(NewsCollector, "__init__", lambda self: None):
        c = NewsCollector()
        c._tavily_key = "key"
        c._bocha_key = "key"
        c._anspire_key = "key"
        with patch.object(c, "search_tavily", new_callable=AsyncMock) as mock_tavily:
            with patch.object(c, "search_bocha", new_callable=AsyncMock, return_value=[]):
                with patch.object(c, "search_anspire", new_callable=AsyncMock, return_value=[]):
                    await c.search_all("海豹", "2026-01-01", "2026-05-01")
    mock_tavily.assert_not_called()


async def test_search_tavily_api_error():
    from pipeline.collectors.news_collector import NewsCollector
    with patch.object(NewsCollector, "__init__", lambda self: None):
        c = NewsCollector()
        c._tavily_key = "key"
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.HTTPStatusError(
            "err", request=MagicMock(), response=MagicMock(status_code=500)))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await c.search_tavily("海豹", "2026-01-01", "2026-05-01")
    assert result == []


async def test_search_all_sorted_by_date():
    from pipeline.collectors.news_collector import NewsCollector
    with patch.object(NewsCollector, "__init__", lambda self: None):
        c = NewsCollector()
        c._bocha_key = "key"
        c._anspire_key = ""
        with patch.object(c, "search_bocha", return_value=[
            {"title": "A", "url": "1", "published_at": "2026-05-01", "source": "bocha", "platform": "news"},
            {"title": "B", "url": "2", "published_at": "2026-05-03", "source": "bocha", "platform": "news"},
        ]):
            with patch.object(c, "search_anspire", return_value=[]):
                result = await c.search_all("test", "2026-01-01", "2026-05-01")
    assert [r["published_at"] for r in result] == ["2026-05-03", "2026-05-01"]


def test_dedup_key_by_url():
    from pipeline.collectors.news_collector import _dedup_key
    assert _dedup_key({"url": "http://x.com/1"}) == _dedup_key({"url": "http://x.com/1"})


def test_dedup_key_by_title_fallback():
    from pipeline.collectors.news_collector import _dedup_key
    assert _dedup_key({"title": "同标题", "url": ""}) == _dedup_key({"title": "同标题", "url": ""})


async def test_search_anspire_no_key():
    from pipeline.collectors.news_collector import NewsCollector
    with patch.object(NewsCollector, "__init__", lambda self: None):
        c = NewsCollector()
        c._anspire_key = ""
        assert await c.search_anspire("海豹", "2026-01-01", "2026-05-01") == []


async def test_search_anspire_success():
    from pipeline.collectors.news_collector import NewsCollector
    with patch.object(NewsCollector, "__init__", lambda self: None):
        c = NewsCollector()
        c._anspire_key = "key"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"results": [
            {"title": "海豹新闻", "content": "内容", "url": "http://x.com",
             "date": "2026-05-01T20:00:00+08:00"},
        ]}
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await c.search_anspire("海豹", "2026-01-01", "2026-05-01")
    assert len(result) == 1
    assert result[0]["source"] == "anspire"
    assert result[0]["platform"] == "news"
    assert result[0]["title"] == "海豹新闻"


async def test_search_anspire_api_error():
    from pipeline.collectors.news_collector import NewsCollector
    with patch.object(NewsCollector, "__init__", lambda self: None):
        c = NewsCollector()
        c._anspire_key = "key"
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.HTTPStatusError(
            "err", request=MagicMock(), response=MagicMock(status_code=500)))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await c.search_anspire("海豹", "2026-01-01", "2026-05-01")
    assert result == []


async def test_search_tavily_sends_include_domains():
    from pipeline.collectors.news_collector import NewsCollector
    with patch.object(NewsCollector, "__init__", lambda self: None):
        c = NewsCollector()
        c._tavily_key = "key"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"results": []}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        with patch("httpx.AsyncClient", return_value=mock_client):
            await c.search_tavily("海豹", "2026-01-01", "2026-05-01")
    call_args = mock_client.post.call_args
    body = call_args[1]["json"]
    assert "include_domains" in body
    assert "autohome.com.cn" in body["include_domains"]
    assert "海豹" in body["query"]
    assert body["max_results"] == 30


async def test_search_all_includes_anspire():
    from pipeline.collectors.news_collector import NewsCollector
    with patch.object(NewsCollector, "__init__", lambda self: None):
        c = NewsCollector()
        c._bocha_key = ""
        c._anspire_key = "key"
        with patch.object(c, "search_bocha", return_value=[]):
            with patch.object(c, "search_anspire", return_value=[
                {"title": "A", "url": "http://a.com", "published_at": "2026-05-01",
                 "source": "anspire", "platform": "news"},
            ]):
                result = await c.search_all("海豹", "2026-01-01", "2026-05-01")
    assert len(result) == 1
    assert result[0]["source"] == "anspire"


class TestConfigPageFilter:
    def test_filters_config_url(self):
        from pipeline.collectors.news_collector import _is_config_page
        assert _is_config_page({"url": "https://www.bitauto.com/byd/seal/config/", "title": "参数配置"}) is True

    def test_filters_compare_url(self):
        from pipeline.collectors.news_collector import _is_config_page
        assert _is_config_page({"url": "https://pk.16888.com/?cid=206334", "title": "车型对比"}) is True

    def test_filters_dealer_url(self):
        from pipeline.collectors.news_collector import _is_config_page
        assert _is_config_page({"url": "https://www.carsbooks.com/series/13327/dealer", "title": "经销商报价"}) is True

    def test_filters_config_title_with_config_url(self):
        from pipeline.collectors.news_collector import _is_config_page
        assert _is_config_page({"url": "https://www.byd.com/cn/parameter-comparison?goodsId=10029", "title": "配置及参数表"}) is True

    def test_passes_normal_article(self):
        from pipeline.collectors.news_collector import _is_config_page
        assert _is_config_page({"url": "https://chejiahao.autohome.com.cn/info/25533163", "title": "海豹06测评"}) is False

    def test_passes_forum_post(self):
        from pipeline.collectors.news_collector import _is_config_page
        assert _is_config_page({"url": "https://baa.yiche.com/oceanX/thread-46506686.html", "title": "比亚迪海豹体验"}) is False
