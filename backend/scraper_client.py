import asyncio
import base64
import os

import httpx

SCRAPER_URL = os.getenv("SCRAPER_URL", "")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")

# Fallbacks for fetch_html and fetch_paginated (see _services below), tried
# in order after schoolz's own scraper. Confirmed real, 2026-09-29: schoolz's own
# Fly scraper wedged internally while its machines still showed "started"
# (no health check catches this - a known gap), 502ing every request
# including a plain restart; every general school-scan job (staff_roster,
# documents, ...) went down with it since they all go through this one
# client with no fallback. Two other healthy scrapers shouldn't sit unused
# while that happens:
#   - the Profitnaut/playwright-scraper droplet, already local_events' own
#     primary scraper (local_events/sources/scraper.py has the full
#     rationale) - reuses its LOCAL_EVENTS_SCRAPER_URL/_KEY env vars rather
#     than a separate pair, since it's the exact same service.
#   - a second, "residential"-IP scraper at scraper.profitnaut.com -
#     separate infra, own env vars. Its key isn't confirmed to be the same
#     as the droplet's; defaults to it as a reasonable guess for a
#     same-owner service, but set RESIDENTIAL_SCRAPER_KEY explicitly once
#     its real key is known.
_FALLBACK_URL = os.getenv("LOCAL_EVENTS_SCRAPER_URL", "https://scraper-droplet.profitnaut.com")
_FALLBACK_API_KEY = os.getenv("LOCAL_EVENTS_SCRAPER_KEY", "")
_RESIDENTIAL_URL = os.getenv("RESIDENTIAL_SCRAPER_URL", "https://scraper.profitnaut.com")
_RESIDENTIAL_API_KEY = os.getenv("RESIDENTIAL_SCRAPER_KEY", "") or _FALLBACK_API_KEY

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


class ScraperRefused(RuntimeError):
    """Every scraper got a refusal (403/429) from the source."""


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(_MAX_IN_FLIGHT)
    return _semaphore


# A 502 whose body names one of these is the *URL* being bad, not the site or
# the scraper being flaky: every scraper will say the same thing, so retrying
# and falling through to the droplet and the residential Pi just multiplies
# one dead link into 9 failed renders (what tripped the residential
# "more than half of requests failing" alert, 2026-10-05).
_PERMANENT_ERRORS = ("ERR_NAME_NOT_RESOLVED", "Cannot navigate to invalid URL")


def _is_retryable(exc: Exception) -> bool:
    """A 502 from the scraper means the *school's* site failed to load in
    time (it wraps any Playwright failure that way); timeouts/connection
    drops are the same class of transient upstream flakiness."""
    if isinstance(exc, httpx.HTTPStatusError):
        if any(m in exc.response.text for m in _PERMANENT_ERRORS):
            return False
        return exc.response.status_code in _RETRY_STATUSES
    return isinstance(exc, httpx.TransportError)


def scraper_hosts() -> set[str]:
    """Hostnames of every scraper this client can call, configured or not.
    classify_exception uses it to tell our scraper being down from a
    source's own server being down."""
    return {httpx.URL(u).host for u in (SCRAPER_URL, _FALLBACK_URL, _RESIDENTIAL_URL) if u}


def _services() -> list[tuple[str, str]]:
    """(base_url, api_key) pairs to try in order, skipping any without a
    key configured. playwright-scraper implements /fetch-paginated with the
    same request body as schoolz's own scraper, so both fetch_html and
    fetch_paginated fall through this list."""
    candidates = [
        (SCRAPER_URL.rstrip("/"), SCRAPER_API_KEY),
        (_FALLBACK_URL.rstrip("/"), _FALLBACK_API_KEY),
        (_RESIDENTIAL_URL.rstrip("/"), _RESIDENTIAL_API_KEY),
    ]
    return [(u, k) for u, k in candidates if u and k]


async def _post_to(service_url: str, api_key: str, path: str, payload: dict, timeout_s: float) -> dict:
    last: Exception | None = None
    for attempt in range(_ATTEMPTS):
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(f"{service_url}{path}", headers={"X-API-Key": api_key}, json=payload)
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


async def _post_with_fallback(path: str, payload: dict, timeout_s: float) -> dict:
    """Tries each configured service in order (schoolz's own scraper, then
    the droplet), falling through only after a service's own retries are
    exhausted - a non-retryable error (a real 404/422 from the school's
    own site, say) still raises immediately rather than masking the
    failure behind a pointless retry against a second scraper that would
    hit the exact same non-retryable response."""
    services = _services()
    if not services:
        raise ScraperNotConfigured("SCRAPER_URL / SCRAPER_API_KEY are not configured")
    async with _get_semaphore():
        last: Exception | None = None
        for service_url, api_key in services:
            try:
                return await _post_to(service_url, api_key, path, payload, timeout_s)
            except Exception as exc:
                if not _is_retryable(exc):
                    raise
                last = exc
        assert last is not None
        raise last


async def fetch_html(
    url: str,
    wait_for_selector: str | None = None,
    timeout_ms: int = 15_000,
    block_assets: bool = False,
) -> dict:
    # The scraper applies timeout_ms to page.goto AND again to
    # wait_for_selector, so it can legitimately take ~2x that before it
    # answers - a client budget of timeout_ms + 5s (the old value) gave up
    # on slow-but-fine pages and reported ReadTimeout.
    return await _post_with_fallback(
        "/fetch-html",
        {
            "url": url,
            "wait_for_selector": wait_for_selector,
            "timeout_ms": timeout_ms,
            "block_assets": block_assets,
        },
        timeout_s=timeout_ms / 1000 * 2 + 10,
    )


async def fetch_paginated(
    url: str,
    next_page_selector: str,
    max_pages: int = 20,
    wait_after_click_ms: int = 1200,
    timeout_ms: int = 15_000,
    block_assets: bool = False,
) -> list[str]:
    """Returns one HTML string per page, clicked through in one live
    browser session - for pagination controls that don't respond to a URL
    query param (client-side/JS-driven pagination).

    Falls back like fetch_html: staff_roster.scan used to have no fallback
    and was the only kind failing when schoolz's own scraper was overloaded,
    while the droplet and the Pi sat idle. The extra 30s over the old budget
    covers playwright-scraper's wait for a Cloudflare challenge to clear."""
    timeout_budget = (timeout_ms / 1000 * 2 + wait_after_click_ms / 1000 * max_pages) + 40
    result = await _post_with_fallback(
        "/fetch-paginated",
        {
            "url": url,
            "next_page_selector": next_page_selector,
            "max_pages": max_pages,
            "wait_after_click_ms": wait_after_click_ms,
            "timeout_ms": timeout_ms,
            "block_assets": block_assets,
        },
        timeout_s=timeout_budget,
    )
    return result["pages"]



async def fetch_raw_bytes(url: str, timeout_ms: int = 45_000) -> bytes:
    """A binary download (PDF) through a real browser context, for sites whose
    WAF 403s a plain GET. Uses /fetch-raw, which returns `body_base64`;
    playwright-scraper's variant returns a text `body` that would corrupt a
    PDF, so a service that answers without base64 is skipped, not trusted."""
    result = await _post_with_fallback("/fetch-raw", {"url": url, "timeout_ms": timeout_ms}, timeout_s=timeout_ms / 1000 * 2 + 10)
    if not result.get("body_base64"):
        raise RuntimeError(f"scraper returned no binary body for {url}")
    return base64.b64decode(result["body_base64"])


async def fetch_raw_text_from_any(url: str, timeout_ms: int = 45_000, refused: tuple[int, ...] = (403, 429)) -> dict:
    """A text response (JSON, CSV) from the first scraper the source doesn't
    refuse. /fetch-raw reports the source's own status inside a 200, so the
    usual fallback never moves on from a WAF's 403 - but a block is usually
    per network (datacenter vs residential), so each service is asked in
    turn. Returns {status, content_type, text, service}; raises
    ScraperRefused when every service was refused."""
    services = _services()
    if not services:
        raise ScraperNotConfigured("SCRAPER_URL / SCRAPER_API_KEY are not configured")
    seen: list[str] = []
    async with _get_semaphore():
        for service_url, api_key in services:
            host = httpx.URL(service_url).host
            try:
                result = await _post_to(service_url, api_key, "/fetch-raw", {"url": url, "timeout_ms": timeout_ms}, timeout_s=timeout_ms / 1000 * 2 + 10)
            except Exception as exc:  # noqa: BLE001 - try the next service
                seen.append(f"{host}: {type(exc).__name__}")
                continue
            status = int(result.get("status") or 0)
            if status in refused:
                seen.append(f"{host}: HTTP {status}")
                continue
            if result.get("body_base64"):
                text = base64.b64decode(result["body_base64"]).decode("utf-8", "replace")
            else:
                text = result.get("body") or ""
            return {"status": status, "content_type": result.get("content_type") or "", "text": text, "service": host}
    raise ScraperRefused(f"every scraper was refused or failed for {url}: {'; '.join(seen)}")
