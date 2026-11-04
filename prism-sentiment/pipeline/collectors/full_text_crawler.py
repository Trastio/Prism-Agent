"""Full-text crawler with trafilatura -> snippet fallback chain."""

import asyncio
import logging

import trafilatura

logger = logging.getLogger(__name__)

_TRAFILATURA_TIMEOUT = 10


def _try_trafilatura(url: str) -> dict:
    """Attempt to extract full text using trafilatura."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return {"url": url, "full_text": None, "status": "failed"}
        full_text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )
        if full_text and len(full_text.strip()) > 200:
            return {"url": url, "full_text": full_text, "status": "success"}
        return {"url": url, "full_text": None, "status": "failed"}
    except Exception:
        logger.debug("Trafilatura failed for %s", url)
        return {"url": url, "full_text": None, "status": "failed"}


async def crawl_full_text(url: str, snippet: str = "", retries: int = 1) -> dict:
    """Crawl full text from a URL, falling back to snippet.

    Uses trafilatura with a timeout. Falls back to snippet if extraction fails.

    Returns:
        dict with keys: url, full_text, status ("success" | "fallback")
    """
    for attempt in range(retries + 1):
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_try_trafilatura, url),
                timeout=_TRAFILATURA_TIMEOUT,
            )
            if result["status"] == "success":
                return result
        except asyncio.TimeoutError:
            logger.debug("Trafilatura timed out for %s (attempt %d)", url, attempt + 1)
        except Exception:
            logger.debug("Trafilatura error for %s (attempt %d)", url, attempt + 1)
        if attempt < retries:
            await asyncio.sleep(1)

    return {"url": url, "full_text": snippet, "status": "fallback"}
