import asyncio
import os

import httpx

SCRAPER_URL = os.getenv("SCRAPER_URL", "")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")

# The scraper is one small headless Chromium, and every 12h cron fires
# ~85 school-level scans in the same minute. Without a cap, the whole
# burst lands on it at once and most requests time out or get 502s.
# This caps in-flight scraper requests per process (the API and the
# scheduler each get their own cap); waiting on the semaphore costs no
# request timeout, so queued callers just run a little later.
_MAX_IN_FLIGHT = 3
_semaphore: asyncio.Semaphore | None = None

_RETRY_STATUSES = {502, 503, 504}
_ATTEMPTS = 3
_BACKOFF_S = 2.0


class ScraperNotConfigured(RuntimeError):
    pass


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(_MAX_IN_FLIGHT)
    return _semaphore


def _is_retryable(exc: Exception) -> bool:
    """A 502 from the scraper means the *school's* site failed to load in
    time (it wraps any Playwright failure that way); timeouts/connection
    drops are the same class of transient upstream flakiness."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRY_STATUSES
    return isinstance(exc, httpx.TransportError)


async def _post(path: str, payload: dict, timeout_s: float) -> dict:
    if not SCRAPER_URL or not SCRAPER_API_KEY:
        raise ScraperNotConfigured("SCRAPER_URL / SCRAPER_API_KEY are not configured")

    async with _get_semaphore():
        last: Exception | None = None
        for attempt in range(_ATTEMPTS):
            try:
                async with httpx.AsyncClient(timeout=timeout_s) as client:
                    response = await client.post(
                        f"{SCRAPER_URL}{path}", headers={"X-API-Key": SCRAPER_API_KEY}, json=payload
                    )
                    response.raise_for_status()
                    return response.json()
            except Exception as exc:
                if not _is_retryable(exc):
                    raise
                last = exc
                if attempt < _ATTEMPTS - 1:
                    await asyncio.sleep(_BACKOFF_S * (attempt + 1))
        assert last is not None
        raise last


async def fetch_html(url: str, wait_for_selector: str | None = None, timeout_ms: int = 15_000) -> dict:
    # The scraper applies timeout_ms to page.goto AND again to
    # wait_for_selector, so it can legitimately take ~2x that before it
    # answers - a client budget of timeout_ms + 5s (the old value) gave up
    # on slow-but-fine pages and reported ReadTimeout.
    return await _post(
        "/fetch-html",
        {"url": url, "wait_for_selector": wait_for_selector, "timeout_ms": timeout_ms},
        timeout_s=timeout_ms / 1000 * 2 + 10,
    )


async def fetch_paginated(
    url: str, next_page_selector: str, max_pages: int = 20, wait_after_click_ms: int = 1200, timeout_ms: int = 15_000
) -> list[str]:
    """Returns one HTML string per page, clicked through in one live
    browser session - for pagination controls that don't respond to a URL
    query param (client-side/JS-driven pagination)."""
    timeout_budget = (timeout_ms / 1000 * 2 + wait_after_click_ms / 1000 * max_pages) + 10
    result = await _post(
        "/fetch-paginated",
        {
            "url": url,
            "next_page_selector": next_page_selector,
            "max_pages": max_pages,
            "wait_after_click_ms": wait_after_click_ms,
            "timeout_ms": timeout_ms,
        },
        timeout_s=timeout_budget,
    )
    return result["pages"]
