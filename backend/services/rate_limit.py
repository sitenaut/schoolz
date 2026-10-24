"""Fixed-window limits per account or per connection, in the database
(models.RateWindow), so every API machine shares one count and a deploy
doesn't reset it. The chat keeps its own table (routers/chat.py).

A connection is keyed by the same reversible salted hash the other limits
keep (CLAUDE.md, "IP codes are reversible on purpose"), never the address,
and an IPv6 address by its /64: one home or phone is handed a whole /64,
so the full address would be a fresh bucket per request.
"""

import hashlib
import ipaddress
import os
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models import RateWindow

DAY = 86_400
HOUR = 3_600


def connection_key(ip: str | None) -> str | None:
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        addr = None
    if isinstance(addr, ipaddress.IPv6Address):
        ip = str(addr.ipv4_mapped or ipaddress.ip_network(f"{addr}/64", strict=False))
    salt = os.getenv("JWT_SECRET", "schoolz-rate-salt")
    return hashlib.sha256(f"{salt}:rate:{ip}".encode()).hexdigest()


async def count(db: AsyncSession, bucket: str, key: str, *, window_seconds: int) -> int:
    """Counts this request in `bucket` for `key` and returns the window's
    total so far, this one included. Commits, so a refused request still
    counts."""
    now = datetime.now(UTC)
    window = datetime.fromtimestamp(now.timestamp() // window_seconds * window_seconds, UTC)
    stmt = (
        insert(RateWindow)
        .values(bucket=bucket, key=key, window_start=window, count=1)
        .on_conflict_do_update(
            index_elements=[RateWindow.bucket, RateWindow.key, RateWindow.window_start],
            set_={"count": RateWindow.count + 1},
        )
        .returning(RateWindow.count)
    )
    total = (await db.execute(stmt)).scalar_one()
    if total == 1:
        # A new window for this key: a cheap moment to clear the bucket's old rows.
        await db.execute(
            delete(RateWindow).where(
                RateWindow.bucket == bucket, RateWindow.window_start < window - timedelta(seconds=window_seconds)
            )
        )
    await db.commit()
    return total


async def enforce(db: AsyncSession, bucket: str, key: str | None, *, limit: int, window_seconds: int, detail: str) -> None:
    """429 with `detail` once `key` has made more than `limit` requests in
    the current window. No key (no address known) is never limited."""
    if key and await count(db, bucket, key, window_seconds=window_seconds) > limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail)
