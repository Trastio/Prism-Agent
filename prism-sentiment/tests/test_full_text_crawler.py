import pytest
from unittest.mock import patch, MagicMock
from pipeline.collectors.full_text_crawler import crawl_full_text, _try_trafilatura


@pytest.mark.asyncio
async def test_crawl_trafilatura_success():
    with patch("pipeline.collectors.full_text_crawler._try_trafilatura") as mock_tf:
        mock_tf.return_value = {"url": "https://example.com/news", "full_text": "A" * 300, "status": "success"}
        result = await crawl_full_text("https://example.com/news", "short snippet")
        assert result["status"] == "success"
        assert len(result["full_text"]) > 200


@pytest.mark.asyncio
async def test_crawl_fallback_to_snippet():
    with patch("pipeline.collectors.full_text_crawler._try_trafilatura") as mock_tf:
        mock_tf.return_value = {"url": "https://example.com", "full_text": None, "status": "failed"}
        result = await crawl_full_text("https://example.com", "fallback snippet text")
        assert result["status"] == "fallback"
        assert result["full_text"] == "fallback snippet text"


def test_try_trafilatura_short_text():
    with patch("pipeline.collectors.full_text_crawler.trafilatura") as mock_tf:
        mock_tf.fetch_url.return_value = "<html>content</html>"
        mock_tf.extract.return_value = "too short"
        result = _try_trafilatura("https://example.com")
        assert result["status"] == "failed"


def test_try_trafilatura_none_result():
    with patch("pipeline.collectors.full_text_crawler.trafilatura") as mock_tf:
        mock_tf.fetch_url.return_value = "<html>content</html>"
        mock_tf.extract.return_value = None
        result = _try_trafilatura("https://example.com")
        assert result["status"] == "failed"
