"""Renders the frontend's own public pages through the scraper's headless
Chromium and caches the result, so a search-engine/social-card crawler that
doesn't execute JS still sees real content instead of the SPA's empty
`<div id="root">` shell (frontend/nginx.conf.template proxies bot user
agents here instead of serving index.html - see that file's comments).

Cached in Postgres (models.PrerenderedPage), with a small in-process copy
in front. It used to be in-process only, on the theory that a cold cache
after a deploy costs one render per path - but there are ~1,000 paths
(schools x languages x class pages), two API machines with a cache each,
and several deploys plus auto-stops a day, so in practice it re-rendered
~3,000 pages a day on the scraper budget the real scans share.
"""

import asyncio
import gzip
import logging
import os
import re
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

import database
import scraper_client
from models import PrerenderedPage

logger = logging.getLogger(__name__)

# How long a snapshot counts as fresh. A crawler is served an older one
# anyway (and it's refreshed in the background) - this only decides when
# that refresh happens. A day is plenty for a search index, and the nightly
# scheduler job (scheduler/jobs/prerender_warm.py) renders every sitemap
# page before it expires, so crawlers essentially never wait on a render.
_TTL_SECONDS = 24 * 3600
# path -> (expires at, as time.time(); html). Wall clock, not monotonic,
# since entries also come from the DB with a rendered_at timestamp.
_CACHE: dict[str, tuple[float, str]] = {}

# Longer than any real route; keeps an arbitrary caller from filling the
# table with junk keys under an allowed prefix (/schools/<anything>).
_MAX_PATH_LEN = 200

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
    "/local",
    "/privacy",
    "/backpack-capture/privacy",
    "/contact",
    "/upload",
    "/chcomms",
    "/survey",
}
_ALLOWED_PREFIXES = ("/schools/", "/seasonal/")


class PathNotAllowed(ValueError):
    pass


_LANG_PREFIX = re.compile(r"^/(?:es|zh|ko|hi)(?=/|$)")


def _is_allowed(path: str) -> bool:
    # A language prefix ("/es/schools/x") renders the same routes.
    path = _LANG_PREFIX.sub("", path) or "/"
    return path in _ALLOWED_PATHS or path.startswith(_ALLOWED_PREFIXES)


async def _load_stored(path: str) -> tuple[float, str] | None:
    # The DB is a cache here, never a dependency: if it's unreachable a
    # crawler still gets a fresh render.
    try:
        async with database.SessionLocal() as db:
            row = (await db.execute(select(PrerenderedPage).where(PrerenderedPage.path == path))).scalar_one_or_none()
    except Exception:
        logger.warning("prerender_cache_read_failed", extra={"path": path}, exc_info=True)
        return None
    if row is None:
        return None
    return (row.rendered_at.timestamp() + _TTL_SECONDS, gzip.decompress(row.html_gz).decode("utf-8"))


async def _store(path: str, html: str) -> None:
    now = datetime.now(timezone.utc)
    values = {"path": path, "html_gz": gzip.compress(html.encode("utf-8")), "rendered_at": now}
    try:
        async with database.SessionLocal() as db:
            await db.execute(
                pg_insert(PrerenderedPage)
                .values(**values)
                .on_conflict_do_update(index_elements=["path"], set_={"html_gz": values["html_gz"], "rendered_at": now})
            )
            await db.commit()
    except Exception:
        logger.warning("prerender_cache_write_failed", extra={"path": path}, exc_info=True)


async def get_prerendered_html(path: str) -> str:
    if len(path) > _MAX_PATH_LEN or not _is_allowed(path):
        raise PathNotAllowed(path)

    cached = _CACHE.get(path)
    if not (cached and cached[0] > time.time()):
        stored = await _load_stored(path)
        if stored and (not cached or stored[0] > cached[0]):
            cached = stored
            _CACHE[path] = stored
    if cached:
        # Stale-while-revalidate: a crawler kept waiting 2-10s on an
        # uncached render is how pages ended up as Search Console "server
        # errors" - three render slots, Googlebot fetching in parallel, and
        # anything that timed out with nothing cached became a 500. An
        # expired snapshot is served instantly and refreshed behind it.
        if cached[0] <= time.time() and path not in _INFLIGHT:
            _start_render(path).add_done_callback(_log_background_failure)
        return cached[1]

    # Shielded so one caller giving up doesn't cancel the render every
    # other caller is waiting on.
    return await asyncio.shield(_start_render(path))


def _start_render(path: str) -> "asyncio.Task[str]":
    task = _INFLIGHT.get(path)
    if task is None:
        task = asyncio.create_task(_render(path))
        _INFLIGHT[path] = task
        task.add_done_callback(lambda _t, p=path: _INFLIGHT.pop(p, None))
    return task


def _log_background_failure(task: "asyncio.Task[str]") -> None:
    if not task.cancelled() and task.exception() is not None:
        logger.warning("prerender_refresh_failed", extra={"error": repr(task.exception())})


async def refresh(path: str) -> None:
    """Render `path` now and store it, whatever the cache holds - the
    nightly warm job's entry point."""
    if len(path) > _MAX_PATH_LEN or not _is_allowed(path):
        raise PathNotAllowed(path)
    await asyncio.shield(_start_render(path))


async def paths_needing_render(paths: list[str], older_than_seconds: float) -> list[str]:
    """The subset of `paths` with no stored snapshot, or one rendered more
    than `older_than_seconds` ago - in the order given."""
    cutoff = datetime.now(timezone.utc).timestamp() - older_than_seconds
    async with database.SessionLocal() as db:
        rows = (await db.execute(select(PrerenderedPage.path, PrerenderedPage.rendered_at).where(PrerenderedPage.path.in_(paths)))).all()
    fresh = {path for path, rendered_at in rows if rendered_at.timestamp() > cutoff}
    return [p for p in paths if p not in fresh]


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
        # ?internal=1 flags the render as internal traffic for GA. The
        # webdriver guard in lib/analytics.ts isn't enough on its own: the
        # droplet and residential fallbacks render the public hostname in
        # stealth Chromium, which hides navigator.webdriver, so crawler
        # visits were counting as real users. ?prerender=1 tells the page
        # it's a render, not a person, so it skips the page_visits beacon
        # and Faro RUM too (lib/prerenderReady.ts) - each render used to
        # count as a new visitor in both. _is_allowed() takes bare paths
        # only, so there's never an existing query to merge with.
        url=f"{base_url}{path}?internal=1&prerender=1",
        # Set by frontend/src/lib/prerenderReady.ts once a page's initial
        # data fetch has resolved - waiting on React having merely mounted
        # (e.g. any child of #root) would still capture "Loading…".
        wait_for_selector='body[data-prerender-ready="true"]',
        timeout_ms=_RENDER_TIMEOUT_MS,
        block_assets=True,
    )

    html = result["html"]
    _CACHE[path] = (time.time() + _TTL_SECONDS, html)
    await _store(path, html)
    return html
