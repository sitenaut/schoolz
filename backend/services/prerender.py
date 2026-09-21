"""Renders the frontend's own public pages through the scraper's headless
Chromium and caches the result, so a search-engine/social-card crawler that
doesn't execute JS still sees real content instead of the SPA's empty
`<div id="root">` shell (frontend/nginx.conf.template proxies bot user
agents here instead of serving index.html - see that file's comments).

Kept process-local and in-memory rather than a DB table: traffic here is a
handful of crawler hits, not user traffic, and a cold cache after a deploy
just means the next crawl of each path pays one render.
"""

import asyncio
import logging
import os
import time

import scraper_client

logger = logging.getLogger(__name__)

_TTL_SECONDS = 6 * 3600
_CACHE: dict[str, tuple[float, str]] = {}

# One render per path at a time. Crawlers hit the same URL from several
# connections at once, and scraper_client only allows 3 in-flight requests
# process-wide - without this, N concurrent crawls of one page each queued
# a full Playwright render and starved the real scan jobs sharing that
# budget. Measured in prod (2026-09-12..15): /prerender p95 4.6s, max 48.6s,
# against <1s for every user-facing route.
_INFLIGHT: dict[str, "asyncio.Task[str]"] = {}

# The scraper applies this to page.goto AND to wait_for_selector, and
# scraper_client budgets 2x + 10s on top - so 20s here meant a single
# request could hold a slot for ~50s, which is what the 48.6s max was.
_RENDER_TIMEOUT_MS = 10_000

# Only these routes carry indexable content - restricts what an arbitrary
# caller can force this process to spend a Playwright render on (this
# endpoint has no auth, since nginx is the only intended caller but the
# API itself is public).
_ALLOWED_PATHS = {
    "/",
    "/schools",
    "/directory",
    "/calendar",
    "/lunch",
    "/privacy",
    "/backpack-capture/privacy",
    "/contact",
    "/chcomms",
    "/survey",
}
_ALLOWED_PREFIXES = ("/schools/",)


class PathNotAllowed(ValueError):
    pass


def _is_allowed(path: str) -> bool:
    return path in _ALLOWED_PATHS or path.startswith(_ALLOWED_PREFIXES)


async def get_prerendered_html(path: str) -> str:
    if not _is_allowed(path):
        raise PathNotAllowed(path)

    cached = _CACHE.get(path)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    task = _INFLIGHT.get(path)
    if task is None:
        task = asyncio.create_task(_render(path))
        _INFLIGHT[path] = task
        task.add_done_callback(lambda _t, p=path: _INFLIGHT.pop(p, None))

    try:
        # Shielded so one caller giving up doesn't cancel the render every
        # other caller is waiting on.
        return await asyncio.shield(task)
    except Exception:
        # An expired entry is kept rather than evicted precisely for this:
        # six-hour-old real content beats an error page for a crawler.
        if cached:
            logger.warning("prerender_failed_serving_stale", extra={"path": path})
            return cached[1]
        raise


async def _render(path: str) -> str:
    # Deliberately NOT PUBLIC_WEB_URL: that's the address a human's own
    # browser can reach (http://localhost:5173 locally, since it's also
    # used in things like invite emails), but the scraper container
    # rendering this page needs an address reachable from ITS network
    # namespace - "localhost:5173" from inside another container just
    # loops back to itself. FRONTEND_INTERNAL_URL is that address
    # (http://frontend:3000 in local compose, http://schoolz-web.internal:3000
    # on Fly's private network) - falls back to PUBLIC_WEB_URL for any
    # environment where the public and internal addresses are the same.
    base_url = os.getenv("FRONTEND_INTERNAL_URL", os.getenv("PUBLIC_WEB_URL", "http://localhost:5173")).rstrip("/")
    result = await scraper_client.fetch_html(
        url=f"{base_url}{path}",
        # Set by frontend/src/lib/prerenderReady.ts once a page's initial
        # data fetch has resolved - waiting on React having merely mounted
        # (e.g. any child of #root) would still capture "Loading…".
        wait_for_selector='body[data-prerender-ready="true"]',
        timeout_ms=_RENDER_TIMEOUT_MS,
    )
    html = result["html"]
    _CACHE[path] = (time.monotonic() + _TTL_SECONDS, html)
    return html
