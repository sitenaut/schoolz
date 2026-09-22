"""Cross-source duplicate detection.

Two events are considered duplicates when start times are within 30 minutes
AND title fuzzy similarity >= 85 AND venue match (fuzzy >= 80 or lat/lon within 100m).

The deduper runs after normalization but before persistence. It compares each
candidate against already-persisted events in the same time window so that
re-fetches and cross-source overlaps converge.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import LocalEvent as Event

TIME_WINDOW = timedelta(minutes=30)
TITLE_THRESHOLD = 85
VENUE_THRESHOLD = 80
GEO_RADIUS_M = 100


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _venue_match(a: dict, b: Event) -> bool:
    if a.get("latitude") is not None and a.get("longitude") is not None \
            and b.latitude is not None and b.longitude is not None:
        if _haversine_m(a["latitude"], a["longitude"], b.latitude, b.longitude) <= GEO_RADIUS_M:
            return True
    av, bv = a.get("venue_name"), b.venue_name
    if av and bv:
        return fuzz.token_set_ratio(av, bv) >= VENUE_THRESHOLD
    # If neither side has venue info, treat as ambiguous → not a duplicate.
    return False


async def find_duplicate(db: AsyncSession, candidate: dict) -> Event | None:
    """Return an existing Event row that duplicates `candidate`, or None."""
    start: datetime | None = candidate.get("start_time")
    if start is None:
        return None
    window_lo = start - TIME_WINDOW
    window_hi = start + TIME_WINDOW
    rows = (
        await db.execute(
            select(Event).where(Event.start_time >= window_lo, Event.start_time <= window_hi)
        )
    ).scalars().all()
    for existing in rows:
        if existing.source == candidate.get("source") and existing.source_event_id == candidate.get("source_event_id"):
            # Same source row — that's an upsert target, not a cross-source duplicate.
            return existing
        if fuzz.token_set_ratio(candidate["title"], existing.title) < TITLE_THRESHOLD:
            continue
        if not _venue_match(candidate, existing):
            continue
        return existing
    return None


def merge_into(existing: Event, candidate: dict) -> None:
    """Prefer richer data: longer description, has image, has price."""
    cand_desc = candidate.get("description") or ""
    if len(cand_desc) > len(existing.description or ""):
        existing.description = candidate["description"]
    if not existing.image_url and candidate.get("image_url"):
        existing.image_url = candidate["image_url"]
    if existing.price_min is None and candidate.get("price_min") is not None:
        existing.price_min = candidate["price_min"]
    if existing.price_max is None and candidate.get("price_max") is not None:
        existing.price_max = candidate["price_max"]
    if existing.is_free is None and candidate.get("is_free") is not None:
        existing.is_free = candidate["is_free"]
    # Union categories.
    cand_cats = candidate.get("categories") or []
    existing_cats = list(existing.categories or [])
    for c in cand_cats:
        if c not in existing_cats:
            existing_cats.append(c)
    existing.categories = existing_cats
