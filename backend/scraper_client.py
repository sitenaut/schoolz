import os

import httpx

SCRAPER_URL = os.getenv("SCRAPER_URL", "")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")


class ScraperNotConfigured(RuntimeError):
    pass


async def fetch_html(url: str, wait_for_selector: str | None = None, timeout_ms: int = 15_000) -> dict:
    if not SCRAPER_URL or not SCRAPER_API_KEY:
        raise ScraperNotConfigured("SCRAPER_URL / SCRAPER_API_KEY are not configured")

    async with httpx.AsyncClient(timeout=timeout_ms / 1000 + 5) as client:
        response = await client.post(
            f"{SCRAPER_URL}/fetch-html",
            headers={"X-API-Key": SCRAPER_API_KEY},
            json={"url": url, "wait_for_selector": wait_for_selector, "timeout_ms": timeout_ms},
        )
        response.raise_for_status()
        return response.json()


async def fetch_paginated(
    url: str, next_page_selector: str, max_pages: int = 20, wait_after_click_ms: int = 1200, timeout_ms: int = 15_000
) -> list[str]:
    """Returns one HTML string per page, clicked through in one live
    browser session - for pagination controls that don't respond to a URL
    query param (client-side/JS-driven pagination)."""
    if not SCRAPER_URL or not SCRAPER_API_KEY:
        raise ScraperNotConfigured("SCRAPER_URL / SCRAPER_API_KEY are not configured")

    timeout_budget = (timeout_ms / 1000 + wait_after_click_ms / 1000 * max_pages) + 10
    async with httpx.AsyncClient(timeout=timeout_budget) as client:
        response = await client.post(
            f"{SCRAPER_URL}/fetch-paginated",
            headers={"X-API-Key": SCRAPER_API_KEY},
            json={
                "url": url,
                "next_page_selector": next_page_selector,
                "max_pages": max_pages,
                "wait_after_click_ms": wait_after_click_ms,
                "timeout_ms": timeout_ms,
            },
        )
        response.raise_for_status()
        return response.json()["pages"]
