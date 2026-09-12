"""Renders the frontend's own public pages through the scraper's headless
Chromium and caches the result, so a search-engine/social-card crawler that
doesn't execute JS still sees real content instead of the SPA's empty
`<div id="root">` shell (frontend/nginx.conf.template proxies bot user
agents here instead of serving index.html - see that file's comments).

Kept process-local and in-memory rather than a DB table: traffic here is a
handful of crawler hits, not user traffic, and a cold cache after a deploy
just means the next crawl of each path pays one render.
"""

import os
import time

import scraper_client

_TTL_SECONDS = 6 * 3600
_CACHE: dict[str, tuple[float, str]] = {}

# Only these routes carry indexable content - restricts what an arbitrary
# caller can force this process to spend a Playwright render on (this
# endpoint has no auth, since nginx is the only intended caller but the
# API itself is public).
_ALLOWED_PATHS = {"/", "/schools", "/calendar", "/lunch", "/privacy", "/contact", "/chcomms", "/survey"}
_ALLOWED_PREFIXES = ("/schools/",)


class PathNotAllowed(ValueError):
    pass


def _is_allowed(path: str) -> bool:
    return path in _ALLOWED_PATHS or path.startswith(_ALLOWED_PREFIXES)


async def get_prerendered_html(path: str) -> str:
    if not _is_allowed(path):
        raise PathNotAllowed(path)

    now = time.monotonic()
    cached = _CACHE.get(path)
    if cached and cached[0] > now:
        return cached[1]

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
        timeout_ms=20_000,
    )
    html = result["html"]
    _CACHE[path] = (now + _TTL_SECONDS, html)
    return html
