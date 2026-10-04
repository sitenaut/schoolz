"""A small in-process TTL cache with single-flight, for expensive public GETs.

Built for GET /calendar: an anonymous visitor (and every crawler's prerender)
sends the same month-window request, and each one used to recompute it from
the database - ~0.5-1.3s idle, 5-17s while a scan burst held the pool
(2026-10-03). Identical requests now share one computation, and a fresh
result is served for a short TTL.

Process-local on purpose: each API machine keeps its own copy, so there is
nothing to invalidate across machines. The TTL is the only freshness rule,
which is fine for data that changes on a 12h scan cadence.

Bytes in, bytes out: the cached value is the already-serialized response
body, so a hit does no database or serialization work, and the memory bound
is an exact byte count.
"""

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable

logger = logging.getLogger(__name__)


class SingleFlightTTLCache:
    def __init__(
        self,
        ttl_s: float,
        max_total_bytes: int = 40 * 1024 * 1024,
        max_entry_bytes: int = 3 * 1024 * 1024,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.ttl_s = ttl_s
        self.max_total_bytes = max_total_bytes
        self.max_entry_bytes = max_entry_bytes
        self._clock = clock
        # key -> (expires_at, body). Oldest first, so eviction pops the front.
        self._entries: "OrderedDict[Hashable, tuple[float, bytes]]" = OrderedDict()
        self._total_bytes = 0
        self._inflight: dict[Hashable, "asyncio.Task[bytes]"] = {}

    @property
    def enabled(self) -> bool:
        return self.ttl_s > 0

    def _store(self, key: Hashable, body: bytes) -> None:
        if len(body) > self.max_entry_bytes:
            # Too big to be worth holding (an unbounded, whole-year pull).
            self._drop(key)
            return
        self._drop(key)
        self._entries[key] = (self._clock() + self.ttl_s, body)
        self._total_bytes += len(body)
        while self._total_bytes > self.max_total_bytes and self._entries:
            oldest = next(iter(self._entries))
            self._drop(oldest)

    def _drop(self, key: Hashable) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._total_bytes -= len(entry[1])

    async def _run(self, key: Hashable, compute: Callable[[], Awaitable[bytes]]) -> bytes:
        body = await compute()
        self._store(key, body)  # once, here - not once per waiter
        return body

    async def get_or_compute(self, key: Hashable, compute: Callable[[], Awaitable[bytes]]) -> bytes:
        entry = self._entries.get(key)
        if entry is not None and entry[0] > self._clock():
            return entry[1]

        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._run(key, compute))
            self._inflight[key] = task
            task.add_done_callback(lambda _t, k=key: self._inflight.pop(k, None))

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
