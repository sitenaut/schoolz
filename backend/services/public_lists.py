"""A short cache for the lists every page asks for: GET /schools,
/districts/summary and /seasonal-guides.

Each page load made all three, each one a database query on a pool of four
connections a machine, and /schools is about a megabyte of JSON built from
1,300 rows every time. On 2026-11-25 a crawler rendering about 2,000 pages
filled both API machines' pools, and every route answered 500 for twenty
minutes; these three were the largest share of the request time. They
change only when a scan, an import or an admin edit runs.

Anonymous requests only: a request carrying a sign-in or an API key is
answered from the database, so an admin who edits a school sees it in the
list at once. Everyone else can be a minute behind (and, on a list nobody
asked for in a while, as old as the stale window for one request).
"""
import os
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

import database
from services.response_cache import SingleFlightTTLCache

# 0 turns it off; the test suite does.
CACHE = SingleFlightTTLCache(
    name="public-lists",
    ttl_s=float(os.getenv("PUBLIC_LISTS_CACHE_TTL_S", "60")),
    stale_s=600,
    max_total_bytes=16 * 1024 * 1024,
)


def is_anonymous(request: Request) -> bool:
    return "authorization" not in request.headers


async def cached_json(
    request: Request,
    key: tuple,
    compute: Callable[[AsyncSession], Awaitable[object]],
    adapter: TypeAdapter,
) -> Response | None:
    """The list as a ready-made JSON response, or None when this request must
    be answered from the database (signed in, or the cache is off)."""
    if not CACHE.enabled or not is_anonymous(request):
        return None

    async def body() -> bytes:
        # Its own session: other visitors wait on this same computation, and
        # the caller's request may be gone before it finishes.
        async with database.SessionLocal() as db:
            return adapter.dump_json(adapter.validate_python(await compute(db), from_attributes=True))

    return Response(content=await CACHE.get_or_compute(key, body), media_type="application/json")
