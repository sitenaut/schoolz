"""Which source sets which field of a listing a provider has claimed.

A claimed scraped record keeps its `source` (so the scraper still refreshes
what the provider hasn't taken over), and `provider_owned_fields` names the
columns the provider set. A refresh never overwrites those: a scraped value
that differs becomes one pending `source_conflict` change request for a
reviewer, not a silent change either way (docs/LOCALZ_DESIGN.md, "Claiming a
scraped record").

A confidential listing never takes a location from a scraper at all - not
even into the review queue - so its street, town, ZIP and pin stay empty.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ResourceChangeRequest, ResourceService

LOCATION_FIELDS = ("address", "city", "postal_code", "latitude", "longitude")

# The status a reviewer sets to take a listing down at once (account taken
# over, closed for good). Off every public surface like "inactive", but a
# refresh never puts it back and its provider can't edit it.
HIDDEN = "hidden"


def is_managed(row: ResourceService) -> bool:
    return bool(row.provider_owned_fields) or row.address_kind == "confidential"


def jsonable(value: Any) -> Any:
    """A column value as JSON (dates as ISO strings)."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return list(value)
    return value


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, list) or isinstance(b, list):
        return list(a or []) == list(b or [])
    return (a or None) == (b or None)


def _keep_latest_assurance(row: ResourceService, fields: dict) -> dict:
    """"Last confirmed" is whoever confirmed the listing most recently. A
    provider's "Yes, it's all still right" was put back to NJ 211's older
    date by its next detail refresh, and blanked by ChildCareNJ (which has
    none), so the card lost it and the check-in mail asked again."""
    if "last_assured_on" not in fields:
        return fields
    current, scraped = row.last_assured_on, fields["last_assured_on"]
    if scraped is None or (current is not None and current >= scraped):
        return {k: v for k, v in fields.items() if k != "last_assured_on"}
    return fields


async def apply_source_fields(db: AsyncSession, row: ResourceService, fields: dict, source: str) -> dict:
    """Set `fields` from a scraper on `row`, except the ones a provider
    owns. Returns the held conflicts ({field: scraped value})."""
    fields = _keep_latest_assurance(row, fields)
    if not is_managed(row):
        for attr, value in fields.items():
            setattr(row, attr, value)
        return {}
    owned = set(row.provider_owned_fields or [])
    confidential = row.address_kind == "confidential"
    conflicts: dict = {}
    before: dict = {}
    for attr, value in fields.items():
        if confidential and attr in LOCATION_FIELDS:
            continue
        if attr in owned:
            current = getattr(row, attr)
            if value not in (None, "", []) and not _same(current, value):
                conflicts[attr] = jsonable(value)
                before[attr] = jsonable(current)
            continue
        setattr(row, attr, value)
    if conflicts and row.id:
        pending = (
            await db.execute(
                select(ResourceChangeRequest).where(
                    ResourceChangeRequest.service_id == row.id,
                    ResourceChangeRequest.kind == "source_conflict",
                    ResourceChangeRequest.status == "pending",
                )
            )
        ).scalars().all()
        # The same disagreement seen again on the next refresh is not news.
        if not any(p.changes == conflicts for p in pending):
            db.add(
                ResourceChangeRequest(
                    service_id=row.id, kind="source_conflict", source=source, changes=conflicts, before=before
                )
            )
    return conflicts
