"""A small in-process TTL cache with single-flight, for expensive public GETs.

Built for GET /calendar: an anonymous visitor (and every crawler's prerender)
sends the same month-window request, and each one used to recompute it from
the database - ~0.5-1.3s idle, 5-17s while a scan burst held the pool
(2026-10-03). Identical requests now share one computation, and a fresh
result is served for a short TTL.

Process-local on purpose: each API machine keeps its own copy, so there is
nothing to invalidate across machines. Time is the only freshness rule,
which is fine for data that changes on a 12h scan cadence.

Stale while revalidate: for `stale_s` after it expires, an entry is still
served at once while one refresh runs behind it, so a visitor waits for a
computation only on a key nobody asked for in the last hour or so. With a
2-minute TTL and morning-rush traffic of a few requests a minute, half the
/calendar requests in the 2026-10-22 rush were 1.3-2.3s misses. Past
`stale_s` the caller waits, as before.

Bytes in, bytes out by default: the cached value is the already-serialized
response body, so a hit does no database or serialization work, and the
memory bound is an exact byte count. A cache of something else (the
directory's people, filtered per request) passes `sizeof`, an estimate of
an entry's bytes.
"""

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from typing import Any

logger = logging.getLogger(__name__)


class SingleFlightTTLCache:
    def __init__(
        self,
        ttl_s: float,
        stale_s: float = 3600,
        max_total_bytes: int = 40 * 1024 * 1024,
        max_entry_bytes: int = 3 * 1024 * 1024,
        clock: Callable[[], float] = time.monotonic,
        sizeof: Callable[[Any], int] = len,
    ):
        self.ttl_s = ttl_s
        self.stale_s = stale_s
        self.max_total_bytes = max_total_bytes
        self.max_entry_bytes = max_entry_bytes
        self._clock = clock
        self._sizeof = sizeof
        # key -> (expires_at, body). Oldest first, so eviction pops the front.
        self._entries: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._sizes: dict[Hashable, int] = {}
        self._total_bytes = 0
        self._inflight: dict[Hashable, asyncio.Task] = {}

    @property
    def enabled(self) -> bool:
        return self.ttl_s > 0

    def _store(self, key: Hashable, body: Any) -> None:
        size = self._sizeof(body)
        if size > self.max_entry_bytes:
            # Too big to be worth holding (an unbounded, whole-year pull).
            self._drop(key)
            return
        self._drop(key)
        self._entries[key] = (self._clock() + self.ttl_s, body)
        self._sizes[key] = size
        self._total_bytes += size
        while self._total_bytes > self.max_total_bytes and self._entries:
            oldest = next(iter(self._entries))
            self._drop(oldest)

    def _drop(self, key: Hashable) -> None:
        if self._entries.pop(key, None) is not None:
            self._total_bytes -= self._sizes.pop(key)

    async def _run(self, key: Hashable, compute: Callable[[], Awaitable[Any]]) -> Any:
        body = await compute()
        self._store(key, body)  # once, here - not once per waiter
        return body

    async def get_or_compute(self, key: Hashable, compute: Callable[[], Awaitable[Any]]) -> Any:
        entry = self._entries.get(key)
        now = self._clock()
        if entry is not None and entry[0] > now:
            return entry[1]

        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._run(key, compute))
            self._inflight[key] = task
            task.add_done_callback(lambda t, k=key: self._finished(k, t))

        if entry is not None and entry[0] + self.stale_s > now:
            return entry[1]  # the refresh above replaces it for the next caller

        try:
            # Shielded so one caller disconnecting doesn't cancel the
            # computation every other waiter is sharing.
            return await asyncio.shield(task)
        except Exception:
            # An expired entry is kept until replaced precisely for this:
            # slightly old public data beats an error page.
            if entry is not None:
                logger.warning("response_cache_failed_serving_stale")
                return entry[1]
            raise

    def _finished(self, key: Hashable, task: asyncio.Task) -> None:
        self._inflight.pop(key, None)
        # A refresh nobody waited for fails silently otherwise.
        if not task.cancelled() and task.exception() is not None:
            logger.warning("response_cache_refresh_failed", exc_info=task.exception())
