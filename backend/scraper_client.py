import asyncio
import base64
import html
import os
import re
import time

import httpx

import observability

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
_FALLBACK_URL = os.getenv("LOCAL_EVENTS_SCRAPER_URL") or "https://scraper-droplet.profitnaut.com"
_FALLBACK_API_KEY = os.getenv("LOCAL_EVENTS_SCRAPER_KEY", "")
_RESIDENTIAL_URL = os.getenv("RESIDENTIAL_SCRAPER_URL") or "https://scraper.profitnaut.com"
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


def _role(service_url: str) -> str:
    """Which configured scraper a URL is: the metric label, never the host."""
    base = service_url.rstrip("/")
    for role, url in (("primary", SCRAPER_URL), ("fallback", _FALLBACK_URL), ("residential", _RESIDENTIAL_URL)):
        if url and base == url.rstrip("/"):
            return role
    return "other"


def _record_call(service_url: str, path: str, outcome: str, started: float) -> None:
    attrs = {"scraper": _role(service_url), "endpoint": path, "outcome": outcome}
    observability.scraper_calls_total.add(1, attrs)
    observability.scraper_call_seconds.record(time.perf_counter() - started, attrs)


async def _post_to(service_url: str, api_key: str, path: str, payload: dict, timeout_s: float) -> dict:
    last: Exception | None = None
    for attempt in range(_ATTEMPTS):
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                response = await client.post(f"{service_url}{path}", headers={"X-API-Key": api_key}, json=payload)
                response.raise_for_status()
                data = response.json()
            _record_call(service_url, path, "ok", started)
            return data
        except Exception as exc:
            if not _is_retryable(exc):
                _record_call(service_url, path, "refused", started)
                raise
            _record_call(service_url, path, "unavailable", started)
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


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_PRE_RE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.S | re.I)


def _json_viewer_text(text: str) -> str | None:
    """The JSON inside a browser's JSON viewer page, or None. playwright-
    scraper's raw mode loads the URL in Chromium and, when no download
    starts, returns the rendered page labelled text/html: the JSON escaped
    inside a lone <pre>. A Cloudflare block page has no such <pre>."""
    match = _PRE_RE.search(text) if text.lstrip().startswith("<") else None
    if not match:
        return None
    inner = html.unescape(match.group(1)).strip()
    return inner if inner[:1] in ("{", "[") else None


async def fetch_raw_text_from_any(
    url: str,
    timeout_ms: int = 45_000,
    expect_content_type: str | None = None,
    prefer: str | None = None,
) -> dict:
    """A text response (JSON, CSV) from the first scraper the source doesn't
    refuse. A WAF block is usually per network (datacenter vs residential),
    and /fetch-raw reports the source's answer inside its own 200 - so the
    usual fallback never moves on from a refusal. Here each service is asked
    in turn (`prefer`, a host that worked earlier in the run, first) and an
    answer counts only if its status is 200 and, with
    `expect_content_type`, its content type contains it: playwright-scraper
    (droplet, Pi) sends no status at all, so a Cloudflare page shows up only
    as the wrong content type - except that its browser labels good JSON
    text/html too, so for "json" a JSON viewer page counts (unwrapped), and
    a refusal records the page's title. Returns {status, content_type, text,
    service}; raises ScraperRefused when no service got a usable answer."""
    services = _services()
    if not services:
        raise ScraperNotConfigured("SCRAPER_URL / SCRAPER_API_KEY are not configured")
    if prefer:
        services = sorted(services, key=lambda s: httpx.URL(s[0]).host != prefer)
    seen: list[str] = []
    async with _get_semaphore():
        for service_url, api_key in services:
            host = httpx.URL(service_url).host
            try:
                result = await _post_to(service_url, api_key, "/fetch-raw", {"url": url, "timeout_ms": timeout_ms}, timeout_s=timeout_ms / 1000 * 2 + 10)
            except Exception as exc:  # noqa: BLE001 - try the next service
                seen.append(f"{host}: {type(exc).__name__}")
                continue
            status = result.get("status")
            content_type = result.get("content_type") or ""
            if status is not None and int(status) != 200:
                seen.append(f"{host}: HTTP {status}")
                continue
            if result.get("body_base64"):
                text = base64.b64decode(result["body_base64"]).decode("utf-8", "replace")
            else:
                text = result.get("body") or ""
            if expect_content_type and expect_content_type not in content_type.lower():
                viewer = _json_viewer_text(text) if expect_content_type == "json" else None
                if viewer is None:
                    title = _TITLE_RE.search(text)
                    page = f' "{html.unescape(title.group(1)).strip()[:80]}"' if title else ""
                    seen.append(f"{host}: {content_type or 'no content type'}{page}")
                    continue
                text = viewer
            return {"status": int(status or 200), "content_type": content_type, "text": text, "service": host}
    raise ScraperRefused(f"no scraper got a usable answer for {url}: {'; '.join(seen)}")


async def check_health() -> dict[str, bool]:
    """{role: healthy} for every configured scraper: /health/deep (real
    readiness in playwright-scraper) answering 200 within 10s. A scraper
    without that route (404) is asked /health instead."""
    results: dict[str, bool] = {}
    async with httpx.AsyncClient(timeout=10) as client:
        for service_url, _key in _services():
            try:
                response = await client.get(f"{service_url}/health/deep")
                if response.status_code == 404:
                    response = await client.get(f"{service_url}/health")
                results[_role(service_url)] = response.status_code == 200
            except httpx.HTTPError:
                results[_role(service_url)] = False
    return results
