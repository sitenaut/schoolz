"""Orchestrates fetch -> normalize -> dedupe -> upsert for all configured sources.

Sources are configured via the scheduled job's `params` JSON so admins can
add/remove feeds from the UI without code changes. Example params:

    {
      "ical_sources": [
        {"name": "cherryhill_township",
         "url": "https://www.cherryhill-nj.com/calendar.ics",
         "default_categories": ["municipal", "family"]}
      ],
      "deyra_schedule_sources": [
        {"name": "mt_laurel_ymca_group_exercise",
         "url": "https://www.philaymca.org/locations/mt-laurel-ymca/schedules/group-exercise",
         "venue_name": "Mt. Laurel YMCA",
         "venue_address": "59 Centerton Road, Mt. Laurel, NJ 08054",
         "default_categories": ["fitness", "group-exercise", "ymca"],
         "days_ahead": 14}
      ]
    }
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import LocalEvent as Event

from .deduper import find_duplicate, merge_into
from .normalizer import normalize
from .sources.base import RawEvent, Source
from .sources.deyra_schedule import DeyraScheduleSource
from .sources.evvnt import EvvntSource
from .sources.gcal import GoogleCalendarSource
from .sources.ical import ICalSource
from .sources.json_api import JsonApiSource
from .sources.listing_page import ListingPageSource
from .sources.rss import RSSSource
from .sources.scraper import ScraperSource
from .sources.sitemap import SitemapSource

logger = logging.getLogger(__name__)


def _build_sources(params: dict) -> list[Source]:
    sources: list[Source] = []
    for entry in params.get("ical_sources") or []:
        if not entry.get("url") or not entry.get("name"):
            continue
        sources.append(
            ICalSource(
                name=entry["name"],
                url=entry["url"],
                default_categories=list(entry.get("default_categories") or []),
                via_scraper=bool(entry.get("via_scraper", False)),
            )
        )
    for entry in params.get("rss_sources") or []:
        if not entry.get("url") or not entry.get("name"):
            continue
        sources.append(
            RSSSource(
                name=entry["name"],
                url=entry["url"],
                default_categories=list(entry.get("default_categories") or []),
                treat_pubdate_as_start=bool(entry.get("treat_pubdate_as_start", False)),
            )
        )
    for entry in params.get("scraper_sources") or []:
        if not entry.get("url") or not entry.get("name"):
            continue
        sources.append(
            ScraperSource(
                name=entry["name"],
                url=entry["url"],
                default_categories=list(entry.get("default_categories") or []),
                selectors=entry.get("selectors") or {},
                render_wait_selector=entry.get("render_wait_selector"),
                render_extra_wait_ms=entry.get("render_extra_wait_ms"),
            )
        )
    for entry in params.get("evvnt_sources") or []:
        if not entry.get("name") or not entry.get("publisher_id") or not entry.get("search_terms") or not entry.get("bbox"):
            continue
        sources.append(
            EvvntSource(
                name=entry["name"],
                publisher_id=int(entry["publisher_id"]),
                search_terms=list(entry["search_terms"]),
                bbox=entry["bbox"],
                default_categories=list(entry.get("default_categories") or []),
                hits_per_page=int(entry.get("hits_per_page", 100)),
                max_pages_per_term=int(entry.get("max_pages_per_term", 20)),
                throttle_seconds=float(entry.get("throttle_seconds", 1.5)),
            )
        )
    for entry in params.get("json_sources") or []:
        if not entry.get("url") or not entry.get("name"):
            continue
        sources.append(
            JsonApiSource(
                name=entry["name"],
                url=entry["url"],
                base_url=entry.get("base_url"),
                data_path=entry.get("data_path", "data.events"),
                id_field=entry.get("id_field", "id"),
                title_field=entry.get("title_field", "title"),
                start_field=entry.get("start_field", "start"),
                end_field=entry.get("end_field", "end"),
                all_day_field=entry.get("all_day_field", "allDay"),
                url_field=entry.get("url_field", "url"),
                description_field=entry.get("description_field", "description"),
                image_field=entry.get("image_field"),
                parser=entry.get("parser"),
                default_categories=list(entry.get("default_categories") or []),
            )
        )
    for entry in params.get("gcal_sources") or []:
        cal_ids = entry.get("calendar_ids") or []
        api_key = entry.get("api_key") or ""
        if not entry.get("name") or not cal_ids or not api_key:
            continue
        sources.append(
            GoogleCalendarSource(
                name=entry["name"],
                calendar_ids=list(cal_ids),
                api_key=api_key,
                default_categories=list(entry.get("default_categories") or []),
                months_ahead=int(entry.get("months_ahead", 6)),
                referer=entry.get("referer"),
            )
        )
    for entry in params.get("listing_page_sources") or []:
        if not entry.get("listing_url") or not entry.get("name") or not entry.get("url_pattern"):
            continue
        try:
            sources.append(
                ListingPageSource(
                    name=entry["name"],
                    listing_url=entry["listing_url"],
                    url_pattern=entry["url_pattern"],
                    link_selector=entry.get("link_selector", "a"),
                    default_categories=list(entry.get("default_categories") or []),
                    max_pages=int(entry.get("max_pages", 80)),
                    concurrency=int(entry.get("concurrency", 4)),
                    render_wait_selector=entry.get("render_wait_selector"),
                    render_extra_wait_ms=entry.get("render_extra_wait_ms"),
                    detail_render_wait_selector=entry.get("detail_render_wait_selector"),
                    detail_render_extra_wait_ms=entry.get("detail_render_extra_wait_ms"),
                    parser_name=entry.get("parser"),
                )
            )
        except ValueError as exc:
            logger.warning("listing_page_source_misconfigured", extra={"name": entry["name"], "error": str(exc)})
    for entry in params.get("sitemap_sources") or []:
        if not entry.get("sitemap_url") or not entry.get("name") or not entry.get("url_pattern") or not entry.get("parser"):
            continue
        try:
            sources.append(
                SitemapSource(
                    name=entry["name"],
                    sitemap_url=entry["sitemap_url"],
                    url_pattern=entry["url_pattern"],
                    parser_name=entry["parser"],
                    default_categories=list(entry.get("default_categories") or []),
                    max_pages=int(entry.get("max_pages", 80)),
                    concurrency=int(entry.get("concurrency", 4)),
                    render_wait_selector=entry.get("render_wait_selector"),
                    render_extra_wait_ms=entry.get("render_extra_wait_ms"),
                )
            )
        except ValueError as exc:
            logger.warning("sitemap_source_misconfigured", extra={"name": entry["name"], "error": str(exc)})
    for entry in params.get("deyra_schedule_sources") or []:
        if not entry.get("url") or not entry.get("name"):
            continue
        sources.append(
            DeyraScheduleSource(
                name=entry["name"],
                url=entry["url"],
                default_categories=list(entry.get("default_categories") or []),
                venue_name=entry.get("venue_name"),
                venue_address=entry.get("venue_address"),
                days_ahead=int(entry.get("days_ahead", 14)),
            )
        )
    return sources


async def run_pipeline(db: AsyncSession, params: dict) -> dict:
    sources = _build_sources(params)
    if not sources:
        return {"sources": 0, "fetched": 0, "inserted": 0, "updated": 0, "skipped": 0}

    fetched = 0
    inserted = 0
    updated = 0
    skipped = 0
    per_source: dict[str, int] = {}

    for source in sources:
        try:
            raws: list[RawEvent] = await source.fetch()
        except Exception as exc:  # noqa: BLE001
            logger.warning("event_source_failed", extra={"source": source.name, "error": str(exc)})
            per_source[source.name] = -1
            continue
        fetched += len(raws)
        per_source[source.name] = len(raws)

        for raw in raws:
            try:
                normalized = normalize(raw)
            except Exception as exc:  # noqa: BLE001
                logger.warning("event_normalize_failed", extra={"source": source.name, "error": str(exc)})
                skipped += 1
                continue

            # Same-source upsert path: exact (source, source_event_id) match.
            existing = (
                await db.execute(
                    select(Event).where(
                        Event.source == normalized["source"],
                        Event.source_event_id == normalized["source_event_id"],
                    )
                )
            ).scalar_one_or_none()

            if existing is not None:
                for k, v in normalized.items():
                    setattr(existing, k, v)
                updated += 1
                continue

            # Cross-source dedupe: fuzzy match.
            dup = await find_duplicate(db, normalized)
            if dup is not None:
                merge_into(dup, normalized)
                updated += 1
                continue

            db.add(Event(**normalized))
            inserted += 1

        # Commit per source so a later source's failure doesn't lose earlier work.
        await db.commit()

    summary = {
        "sources": len(sources),
        "fetched": fetched,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "per_source": per_source,
    }
    logger.info("events_pipeline_complete", extra=summary)
    return summary
