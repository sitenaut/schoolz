"""The resources.refresh pipeline for NJ 211: list crawl -> upsert ->
detail fetches -> mark vanished records inactive.

Two phases with different cadences, so one daily job stays cheap:

- **List crawl**, at most every `list_every_days`: every top-level taxonomy
  code for every place, all pages. New ids are inserted from the listing;
  a known id whose listing changed gets its detail re-queued. Only a crawl
  that finished every query may mark records missing - a run cut short by
  an error or a block would otherwise deactivate everything it didn't
  reach. Two complete crawls in a row without a record make it inactive.
- **Details**, every run, up to `max_details_per_run`: never-fetched
  records first, then any not fetched in `detail_refresh_days`.

Commits after every page and every few details, and checkpoints progress,
so a long throttled run (10 s a request) is never one huge transaction and
the stuck-run reaper sees it alive.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models import ResourceOrganization, ResourceService
from scheduler import progress

from . import childcarenj, nj211, ownership
from .categories import categories_for_codes

logger = logging.getLogger(__name__)

# Inform USA top-level branches: Basic needs, Consumer, legal (F), Education
# (H), Health (L), income/employment (N), Individual & family life (P),
# mental health/substance use (R), community services (T). J (environment)
# and Y (target populations) hold nothing Localz lists on its own.
DEFAULT_TAXONOMY_ROOTS = ["B", "D", "F", "H", "L", "N", "P", "R", "T"]

DETAIL_COMMIT_EVERY = 10
INACTIVE_AFTER_MISSED_CRAWLS = 2


def _now() -> datetime:
    return datetime.now(UTC)


def name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def missing_core(row: ResourceService) -> list[str]:
    """The required core (docs/LOCALZ_DESIGN.md, "Required core") this
    record lacks. A service-area-only service (a hotline, a statewide
    program) satisfies "address" with the areas it serves."""
    missing = []
    if not row.name:
        missing.append("name")
    if not (row.address or row.service_areas):
        missing.append("address")
    if not row.hours_text:
        missing.append("hours")
    if not row.phone:
        missing.append("phone")
    if not row.taxonomy_codes:
        missing.append("services")
    return missing


def _derive(row: ResourceService) -> None:
    row.categories = categories_for_codes(list(row.taxonomy_codes or []))
    row.missing_core = missing_core(row)


class _Orgs:
    """Organization lookup by normalized name, cached for the run."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.cache: dict[str, ResourceOrganization] = {}

    async def get(self, fields: dict) -> ResourceOrganization | None:
        name = fields.get("name")
        if not name:
            return None
        key = name_key(name)
        if not key:
            return None
        org = self.cache.get(key)
        if org is None:
            org = (await self.db.execute(select(ResourceOrganization).where(ResourceOrganization.name_key == key))).scalar_one_or_none()
        if org is None:
            org = ResourceOrganization(name=name, name_key=key)
            self.db.add(org)
        for attr in ("alternate_name", "description", "url"):
            if fields.get(attr):
                setattr(org, attr, fields[attr])
        self.cache[key] = org
        return org


async def _upsert_listing(db: AsyncSession, orgs: _Orgs, results: list[dict], now: datetime, summary: dict, county: str | None = None) -> None:
    ids = [r["id"] for r in results]
    existing = {
        row.source_record_id: row
        for row in (
            await db.execute(
                select(ResourceService).where(ResourceService.source == nj211.SOURCE, ResourceService.source_record_id.in_(ids))
            )
        ).scalars()
    }
    for result in results:
        record_id = result["id"]
        digest = nj211.summary_hash(result)
        row = existing.get(record_id)
        if row is None:
            fields = nj211.summary_fields(result)
            org = await orgs.get({"name": fields["organization_name"], "alternate_name": result.get("organizationAlternateName")})
            row = ResourceService(
                source=nj211.SOURCE,
                source_record_id=record_id,
                organization_id=org.id if org else None,
                summary_hash=digest,
                first_seen_at=now,
                last_seen_at=now,
                raw=nj211.storable_raw(result),
                required_documents=[],
                languages=[],
                service_areas=[],
                listed_in_counties=[county] if county else [],
                **fields,
            )
            if org is not None and org.id is None:
                await db.flush()
                row.organization_id = org.id
            _derive(row)
            db.add(row)
            existing[record_id] = row
            summary["new"] += 1
        else:
            if row.summary_hash != digest:
                # The detail fetch rewrites every field; until then the old
                # record stays on show.
                row.summary_hash = digest
                row.detail_fetched_at = None
                summary["changed"] += 1
            row.last_seen_at = now
            row.missed_crawls = 0
            if county and county not in (row.listed_in_counties or []):
                # A new list, not an in-place append: SQLAlchemy only notices
                # an ARRAY change on assignment.
                row.listed_in_counties = [*(row.listed_in_counties or []), county]
            if row.status != "active":
                row.status = "active"
                summary["reactivated"] += 1
    summary["listed"] += len(results)


async def _list_crawl_due(db: AsyncSession, every_days: float, now: datetime) -> bool:
    last = (await db.execute(select(func.max(ResourceService.last_seen_at)).where(ResourceService.source == nj211.SOURCE))).scalar()
    return last is None or last < now - timedelta(days=every_days)


async def _mark_missing(db: AsyncSession, crawl_started: datetime, source: str = nj211.SOURCE) -> int:
    await db.execute(
        update(ResourceService)
        .where(
            ResourceService.source == source,
            ResourceService.status == "active",
            ResourceService.last_seen_at < crawl_started,
        )
        .values(missed_crawls=ResourceService.missed_crawls + 1)
    )
    # A listing a provider has claimed stays up when the source drops it:
    # the provider keeps it current now (missed_crawls still counts).
    result = await db.execute(
        update(ResourceService)
        .where(
            ResourceService.source == source,
            ResourceService.status == "active",
            ResourceService.missed_crawls >= INACTIVE_AFTER_MISSED_CRAWLS,
            func.cardinality(ResourceService.provider_owned_fields) == 0,
        )
        .values(status="inactive")
    )
    return result.rowcount or 0


def _rotated(places: list[dict], now: datetime) -> list[dict]:
    """Start the list crawl at a different place each day. A full statewide
    crawl takes hours, so a deploy can cut one short; rotating means the
    same counties aren't the ones that always miss out."""
    if not places:
        return places
    start = now.toordinal() % len(places)
    return places[start:] + places[:start]


async def _list_crawl(db: AsyncSession, client: nj211.NJ211Client, cfg: dict, summary: dict) -> None:
    places = _rotated(cfg["places"], _now())
    roots = cfg.get("taxonomy_roots") or DEFAULT_TAXONOMY_ROOTS
    max_pages = int(cfg.get("max_pages_per_query", 80))
    orgs = _Orgs(db)
    crawl_started = _now()
    complete = True
    for place in places:
        for root in roots:
            page = 1
            while True:
                try:
                    results, total = await client.search(root, place, page)
                except nj211.Blocked:
                    raise
                except Exception as exc:  # noqa: BLE001 - one bad page shouldn't sink the run
                    complete = False
                    summary["errors"].append(f"{place['label']} {root} p{page}: {type(exc).__name__}: {exc}"[:300])
                    logger.warning("nj211_search_failed", extra={"place": place["label"], "code": root, "page": page, "error": str(exc)[:300]})
                    break
                summary["pages"] += 1
                await _upsert_listing(db, orgs, results, _now(), summary, place.get("county"))
                await db.commit()
                await progress.checkpoint(summary)
                if not results or page * nj211.PAGE_SIZE >= total:
                    break
                if page >= max_pages:
                    complete = False
                    summary["errors"].append(f"{place['label']} {root}: stopped at the {max_pages}-page cap of {total} results")
                    break
                page += 1
    summary["list_crawl"] = "complete" if complete else "partial"
    if complete:
        summary["deactivated"] = await _mark_missing(db, crawl_started)
        await db.commit()


async def _apply_detail(db: AsyncSession, orgs: _Orgs, row: ResourceService, record: dict, now: datetime) -> None:
    managed = ownership.is_managed(row)
    # Provider-owned fields are held for review instead of overwritten.
    await ownership.apply_source_fields(db, row, nj211.detail_fields(record), nj211.SOURCE)
    if not managed:
        org = await orgs.get(nj211.organization_fields(record))
        if org is not None:
            if org.id is None:
                await db.flush()
            row.organization_id = org.id
    if row.address_kind != "confidential":
        row.raw = nj211.storable_raw(record)
    row.detail_fetched_at = now
    _derive(row)


async def _fetch_details(db: AsyncSession, client: nj211.NJ211Client, cfg: dict, summary: dict) -> None:
    limit = int(cfg.get("max_details_per_run", 250))
    if limit <= 0:
        return
    stale_before = _now() - timedelta(days=int(cfg.get("detail_refresh_days", 30)))
    rows = (
        (
            await db.execute(
                select(ResourceService)
                .where(
                    ResourceService.source == nj211.SOURCE,
                    ResourceService.status == "active",
                    or_(ResourceService.detail_fetched_at.is_(None), ResourceService.detail_fetched_at < stale_before),
                )
                .order_by(ResourceService.detail_fetched_at.asc().nulls_first(), ResourceService.first_seen_at.asc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    orgs = _Orgs(db)
    for i, row in enumerate(rows, start=1):
        try:
            record = await client.detail(row.source_record_id)
        except nj211.Blocked:
            raise
        except Exception as exc:  # noqa: BLE001
            summary["detail_failures"] += 1
            if len(summary["errors"]) < 20:
                summary["errors"].append(f"detail {row.source_record_id}: {type(exc).__name__}: {exc}"[:300])
            logger.warning("nj211_detail_failed", extra={"record_id": row.source_record_id, "error": str(exc)[:300]})
            continue
        await _apply_detail(db, orgs, row, record, _now())
        summary["details"] += 1
        if i % DETAIL_COMMIT_EVERY == 0:
            await db.commit()
            await progress.checkpoint(summary)
    await db.commit()


async def refresh_nj211(db: AsyncSession, cfg: dict, client: Any = None) -> dict:
    """Run one refresh. `client` is for tests (an object with check_robots,
    search and detail); by default a throttled NJ211Client."""
    if not cfg.get("places"):
        raise ValueError("nj211 params need at least one place ({label, lat, lon})")
    summary: dict[str, Any] = {
        "list_crawl": "not due",
        "pages": 0,
        "listed": 0,
        "new": 0,
        "changed": 0,
        "reactivated": 0,
        "deactivated": 0,
        "details": 0,
        "detail_failures": 0,
        "blocked": None,
        "errors": [],
    }
    owns = client is None
    if owns:
        client = nj211.NJ211Client(delay_seconds=float(cfg.get("delay_seconds", nj211.MIN_DELAY_SECONDS)))
        await client.__aenter__()
    try:
        await client.check_robots()
        if cfg.get("force_list") or await _list_crawl_due(db, float(cfg.get("list_every_days", 6)), _now()):
            await _list_crawl(db, client, cfg, summary)
        await _fetch_details(db, client, cfg, summary)
    except nj211.Blocked as exc:
        await db.commit()  # keep what was saved before the refusal
        summary["blocked"] = str(exc)
        if summary["list_crawl"] == "not due" and summary["pages"]:
            summary["list_crawl"] = "partial"
        logger.warning("nj211_blocked", extra={"reason": str(exc)})
    finally:
        summary["requests"] = getattr(client, "requests", None)
        if owns:
            await client.__aexit__(None, None, None)
    return summary


# ---- ChildCareNJ -----------------------------------------------------------


async def _upsert_providers(db: AsyncSession, orgs: _Orgs, records: list[dict], county: str, now: datetime, summary: dict, unknown: set[str]) -> None:
    ids = [str(r["UniqueProgramID"]) for r in records]
    existing = {
        row.source_record_id: row
        for row in (
            await db.execute(
                select(ResourceService).where(ResourceService.source == childcarenj.SOURCE, ResourceService.source_record_id.in_(ids))
            )
        ).scalars()
    }
    for record in records:
        record_id = str(record["UniqueProgramID"])
        digest = childcarenj.record_hash(record)
        row = existing.get(record_id)
        if row is not None and row.summary_hash == digest:
            row.last_seen_at = now
            row.missed_crawls = 0
            if row.status != "active":
                row.status = "active"
                summary["reactivated"] += 1
            continue
        values = childcarenj.fields(record, county, unknown)
        org = await orgs.get({"name": values["organization_name"], "url": values["website"]})
        if org is not None and org.id is None:
            await db.flush()
        if row is None:
            row = ResourceService(source=childcarenj.SOURCE, source_record_id=record_id, first_seen_at=now)
            db.add(row)
            existing[record_id] = row
            summary["new"] += 1
        else:
            summary["changed"] += 1
            if row.status != "active":
                summary["reactivated"] += 1
        managed = ownership.is_managed(row)
        await ownership.apply_source_fields(db, row, values, childcarenj.SOURCE)
        if not managed:
            row.organization_id = org.id if org else None
        if row.address_kind != "confidential":
            row.raw = childcarenj.storable_raw(record)
        row.summary_hash = digest
        row.last_seen_at = now
        row.detail_fetched_at = now  # the list record is the whole record
        row.missed_crawls = 0
        row.status = "active"
        _derive(row)


async def refresh_childcarenj(db: AsyncSession, cfg: dict, client: Any = None) -> dict:
    """One pass over every county in `cfg["counties"]` (all 21 by default).
    Only a pass that read every county completely may count records as
    missing; two such passes without a provider make it inactive. `client`
    is for tests (an object with `providers(county, page)`)."""
    counties = cfg.get("counties") or childcarenj.NJ_COUNTIES
    summary: dict[str, Any] = {
        "counties": 0,
        "listed": 0,
        "hidden": 0,
        "new": 0,
        "changed": 0,
        "reactivated": 0,
        "deactivated": 0,
        "short_counts": [],
        "unknown_codes": [],
        "blocked": None,
        "errors": [],
    }
    unknown: set[str] = set()
    owns = client is None
    if owns:
        client = childcarenj.ChildCareNJClient(
            delay_seconds=float(cfg.get("delay_seconds", childcarenj.MIN_DELAY_SECONDS)), via_scraper=bool(cfg.get("via_scraper"))
        )
        await client.__aenter__()
    orgs = _Orgs(db)
    started = _now()
    complete = True
    try:
        for county in counties:
            page, records, total = 0, [], 0
            try:
                while True:
                    batch, total = await client.providers(county, page)
                    records.extend(batch)
                    if not batch or len(records) >= total or (page + 1) * childcarenj.PAGE_SIZE >= total:
                        break
                    page += 1
            except childcarenj.Blocked:
                raise
            except Exception as exc:  # noqa: BLE001 - one county shouldn't sink the run
                complete = False
                summary["errors"].append(f"{county}: {type(exc).__name__}: {exc}"[:300])
                logger.warning("childcarenj_fetch_failed", extra={"county": county, "error": str(exc)[:300]})
                continue
            visible = [r for r in records if not r.get("Hidden")]
            summary["hidden"] += len(records) - len(visible)
            if len(records) < total:
                # The source counts a few more than it returns (Camden: 397
                # counted, 395 sent). Recorded, not an error.
                summary["short_counts"].append(f"{county}: {len(records)} of {total}")
            await _upsert_providers(db, orgs, visible, county, _now(), summary, unknown)
            summary["counties"] += 1
            summary["listed"] += len(visible)
            await db.commit()
            await progress.checkpoint(summary)
        if complete and summary["listed"]:
            summary["deactivated"] = await _mark_missing(db, started, childcarenj.SOURCE)
            await db.commit()
    except childcarenj.Blocked as exc:
        await db.commit()
        summary["blocked"] = str(exc)
        logger.warning("childcarenj_blocked", extra={"reason": str(exc)})
    finally:
        summary["unknown_codes"] = sorted(unknown)
        summary["requests"] = getattr(client, "requests", None)
        summary["route"] = getattr(client, "route", None)
        if owns:
            await client.__aexit__(None, None, None)
    return summary
