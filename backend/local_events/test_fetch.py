"""Dry-run a local_events.refresh config: fetch every source, persist nothing.

Ported verbatim from billz's POST /admin/scheduled-jobs/test-fetch (the
per-source statuses, sample titles, capped dry-run page counts and the
verbose first-entry diagnostics are all billz's), moved out of the router so
routers/scheduled_jobs.py stays a thin wrapper. The only change is the kind
name it accepts."""
from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel

from .sources.deyra_schedule import DeyraScheduleSource
from .sources.evvnt import EvvntSource
from .sources.gcal import GoogleCalendarSource
from .sources.ical import ICalSource
from .sources.json_api import JsonApiSource
from .sources.listing_page import ListingPageSource
from .sources.rss import RSSSource
from .sources.scraper import ScraperSource
from .sources.sitemap import SitemapSource

KIND = "local_events.refresh"
_API_URL_EVVNT = "https://discovery.evvnt.com/api/events"


class TestFetchIn(BaseModel):
    kind: str
    params: dict
    verbose: bool = False


class TestFetchSourceResult(BaseModel):
    name: str
    url: str | None
    status: str  # ok | http_error | parse_error | misconfigured
    event_count: int
    sample_titles: list[str]
    error: str | None
    # Populated only when verbose=True: name -> truncated string for the first
    # entry/component, so unknown custom namespaces can be diagnosed.
    first_entry_fields: dict[str, str] | None = None
    source_type: str | None = None  # "ical" | "rss" | "scraper" | "sitemap"


class TestFetchOut(BaseModel):
    kind: str
    sources: list[TestFetchSourceResult]



def _truncate(s: str, n: int = 240) -> str:
    s = s.replace("\n", " ").replace("\r", " ").strip()
    return s if len(s) <= n else s[:n] + "…"



async def run_test_fetch(body: TestFetchIn) -> TestFetchOut:
    """Dry-run a job's fetch step without persisting anything.

    Useful for validating source URLs and params before enabling a schedule.
    Currently supports kind="local_events.refresh". Other kinds will be added as
    they grow a meaningful dry-run shape.
    """
    import httpx

    if body.kind != KIND:
        raise HTTPException(
            status_code=400,
            detail=f"test-fetch is not implemented for kind {body.kind!r}",
        )

    results: list[TestFetchSourceResult] = []
    evvnt_sources = body.params.get("evvnt_sources") or []
    gcal_sources = body.params.get("gcal_sources") or []
    ical_sources = body.params.get("ical_sources") or []
    listing_page_sources = body.params.get("listing_page_sources") or []
    rss_sources = body.params.get("rss_sources") or []
    scraper_sources = body.params.get("scraper_sources") or []
    sitemap_sources = body.params.get("sitemap_sources") or []
    json_sources = body.params.get("json_sources") or []
    deyra_schedule_sources = body.params.get("deyra_schedule_sources") or []
    if not isinstance(ical_sources, list):
        raise HTTPException(status_code=400, detail="params.ical_sources must be a list")
    if not isinstance(listing_page_sources, list):
        raise HTTPException(status_code=400, detail="params.listing_page_sources must be a list")
    if not isinstance(rss_sources, list):
        raise HTTPException(status_code=400, detail="params.rss_sources must be a list")
    if not isinstance(scraper_sources, list):
        raise HTTPException(status_code=400, detail="params.scraper_sources must be a list")
    if not isinstance(sitemap_sources, list):
        raise HTTPException(status_code=400, detail="params.sitemap_sources must be a list")
    if not isinstance(json_sources, list):
        raise HTTPException(status_code=400, detail="params.json_sources must be a list")
    if not isinstance(gcal_sources, list):
        raise HTTPException(status_code=400, detail="params.gcal_sources must be a list")
    if not isinstance(evvnt_sources, list):
        raise HTTPException(status_code=400, detail="params.evvnt_sources must be a list")
    if not isinstance(deyra_schedule_sources, list):
        raise HTTPException(status_code=400, detail="params.deyra_schedule_sources must be a list")

    async def _diagnose(source_type: str, source, url: str) -> dict[str, str] | None:
        """Return source-type-specific diagnostic info for verbose mode."""
        try:
            if source_type in ("scraper", "sitemap", "listing_page"):
                # All three expose a custom diagnose() that uses the scraper service.
                return await source.diagnose()
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "billz-events/1.0"})
                resp.raise_for_status()
                content = resp.content
            if source_type == "rss":
                import feedparser
                feed = feedparser.parse(content)
                if not feed.entries:
                    return {"_note": "feedparser returned 0 entries"}
                entry = feed.entries[0]
                return {k: _truncate(str(entry.get(k))) for k in entry.keys()}
            if source_type == "ical":
                from icalendar import Calendar
                cal = Calendar.from_ical(content)
                for component in cal.walk("VEVENT"):
                    return {str(k): _truncate(str(component.get(k))) for k in component.keys()}
                return {"_note": "no VEVENT components found"}
        except Exception as exc:  # noqa: BLE001
            return {"_error": f"{type(exc).__name__}: {exc}"}
        return None

    async def _probe(source_type: str, source) -> TestFetchSourceResult:
        url = getattr(source, "url", None)
        try:
            raws = await source.fetch()
            diag = await _diagnose(source_type, source, url) if (body.verbose and url) else None
            return TestFetchSourceResult(
                name=source.name, url=url, status="ok",
                event_count=len(raws),
                sample_titles=[r.title for r in raws[:5]],
                error=None,
                first_entry_fields=diag,
                source_type=source_type,
            )
        except httpx.HTTPStatusError as exc:
            return TestFetchSourceResult(
                name=source.name, url=url, status="http_error",
                event_count=0, sample_titles=[],
                error=f"HTTP {exc.response.status_code} from {exc.request.url}",
                source_type=source_type,
            )
        except httpx.HTTPError as exc:
            return TestFetchSourceResult(
                name=source.name, url=url, status="http_error",
                event_count=0, sample_titles=[],
                error=f"{type(exc).__name__}: {exc}",
                source_type=source_type,
            )
        except Exception as exc:  # noqa: BLE001
            diag = await _diagnose(source_type, source, url) if (body.verbose and url) else None
            return TestFetchSourceResult(
                name=source.name, url=url, status="parse_error",
                event_count=0, sample_titles=[],
                error=f"{type(exc).__name__}: {exc}",
                first_entry_fields=diag,
                source_type=source_type,
            )

    for entry in ical_sources:
        name = (entry or {}).get("name") or "(unnamed iCal)"
        url = (entry or {}).get("url")
        if not url:
            results.append(TestFetchSourceResult(
                name=name, url=None, status="misconfigured",
                event_count=0, sample_titles=[],
                error="missing 'url' field", source_type="ical",
            ))
            continue
        results.append(await _probe("ical", ICalSource(
            name=name,
            url=url,
            default_categories=list(entry.get("default_categories") or []),
            via_scraper=bool(entry.get("via_scraper", False)),
        )))

    for entry in rss_sources:
        name = (entry or {}).get("name") or "(unnamed RSS)"
        url = (entry or {}).get("url")
        if not url:
            results.append(TestFetchSourceResult(
                name=name, url=None, status="misconfigured",
                event_count=0, sample_titles=[],
                error="missing 'url' field", source_type="rss",
            ))
            continue
        results.append(await _probe("rss", RSSSource(
            name=name,
            url=url,
            default_categories=list(entry.get("default_categories") or []),
            treat_pubdate_as_start=bool((entry or {}).get("treat_pubdate_as_start", False)),
        )))

    for entry in scraper_sources:
        name = (entry or {}).get("name") or "(unnamed scraper)"
        url = (entry or {}).get("url")
        if not url:
            results.append(TestFetchSourceResult(
                name=name, url=None, status="misconfigured",
                event_count=0, sample_titles=[],
                error="missing 'url' field", source_type="scraper",
            ))
            continue
        results.append(await _probe("scraper", ScraperSource(
            name=name,
            url=url,
            default_categories=list(entry.get("default_categories") or []),
            selectors=entry.get("selectors") or {},
            render_wait_selector=entry.get("render_wait_selector"),
            render_extra_wait_ms=entry.get("render_extra_wait_ms"),
        )))

    for entry in sitemap_sources:
        name = (entry or {}).get("name") or "(unnamed sitemap)"
        sitemap_url = (entry or {}).get("sitemap_url")
        parser_name = (entry or {}).get("parser")
        url_pattern = (entry or {}).get("url_pattern")
        if not sitemap_url or not parser_name or not url_pattern:
            results.append(TestFetchSourceResult(
                name=name, url=sitemap_url, status="misconfigured",
                event_count=0, sample_titles=[],
                error="sitemap_sources entries require sitemap_url, url_pattern, and parser",
                source_type="sitemap",
            ))
            continue
        try:
            # Cap max_pages low for a fast dry-run; full pipeline uses the configured cap.
            sm_source = SitemapSource(
                name=name,
                sitemap_url=sitemap_url,
                url_pattern=url_pattern,
                parser_name=parser_name,
                default_categories=list(entry.get("default_categories") or []),
                max_pages=min(int(entry.get("max_pages", 80)), 3),
                concurrency=int(entry.get("concurrency", 2)),
                render_wait_selector=entry.get("render_wait_selector"),
                render_extra_wait_ms=entry.get("render_extra_wait_ms"),
            )
        except ValueError as exc:
            results.append(TestFetchSourceResult(
                name=name, url=sitemap_url, status="misconfigured",
                event_count=0, sample_titles=[], error=str(exc),
                source_type="sitemap",
            ))
            continue
        # Override .url so the result's url column shows the sitemap.
        sm_source.url = sitemap_url  # type: ignore[attr-defined]
        results.append(await _probe("sitemap", sm_source))

    for entry in gcal_sources:
        name = (entry or {}).get("name") or "(unnamed gcal)"
        cal_ids = (entry or {}).get("calendar_ids") or []
        api_key = (entry or {}).get("api_key") or ""
        if not cal_ids or not api_key:
            results.append(TestFetchSourceResult(
                name=name, url=None, status="misconfigured",
                event_count=0, sample_titles=[],
                error="gcal_sources entries require calendar_ids and api_key",
                source_type="gcal",
            ))
            continue
        results.append(await _probe("gcal", GoogleCalendarSource(
            name=name,
            calendar_ids=list(cal_ids),
            api_key=api_key,
            default_categories=list(entry.get("default_categories") or []),
            months_ahead=int(entry.get("months_ahead", 6)),
            referer=entry.get("referer"),
        )))

    for entry in listing_page_sources:
        name = (entry or {}).get("name") or "(unnamed listing-page)"
        listing_url = (entry or {}).get("listing_url")
        url_pattern = (entry or {}).get("url_pattern")
        if not listing_url or not url_pattern:
            results.append(TestFetchSourceResult(
                name=name, url=listing_url, status="misconfigured",
                event_count=0, sample_titles=[],
                error="listing_page_sources entries require listing_url and url_pattern",
                source_type="listing_page",
            ))
            continue
        try:
            lp_source = ListingPageSource(
                name=name,
                listing_url=listing_url,
                url_pattern=url_pattern,
                link_selector=entry.get("link_selector", "a"),
                default_categories=list(entry.get("default_categories") or []),
                # Cap detail pages low for a fast dry-run.
                max_pages=min(int(entry.get("max_pages", 80)), 3),
                concurrency=int(entry.get("concurrency", 2)),
                render_wait_selector=entry.get("render_wait_selector"),
                render_extra_wait_ms=entry.get("render_extra_wait_ms"),
                detail_render_wait_selector=entry.get("detail_render_wait_selector"),
                detail_render_extra_wait_ms=entry.get("detail_render_extra_wait_ms"),
                parser_name=entry.get("parser"),
            )
        except ValueError as exc:
            results.append(TestFetchSourceResult(
                name=name, url=listing_url, status="misconfigured",
                event_count=0, sample_titles=[], error=str(exc),
                source_type="listing_page",
            ))
            continue
        lp_source.url = listing_url  # type: ignore[attr-defined]
        results.append(await _probe("listing_page", lp_source))

    for entry in evvnt_sources:
        name = (entry or {}).get("name") or "(unnamed evvnt)"
        publisher_id = (entry or {}).get("publisher_id")
        search_terms = (entry or {}).get("search_terms")
        bbox = (entry or {}).get("bbox")
        if not publisher_id or not search_terms or not bbox:
            results.append(TestFetchSourceResult(
                name=name, url=_API_URL_EVVNT, status="misconfigured",
                event_count=0, sample_titles=[],
                error="evvnt_sources entries require publisher_id, search_terms, and bbox",
                source_type="evvnt",
            ))
            continue
        results.append(await _probe("evvnt", EvvntSource(
            name=name,
            publisher_id=int(publisher_id),
            search_terms=list(search_terms),
            bbox=bbox,
            default_categories=list(entry.get("default_categories") or []),
            # Cap at 1 page per term for test-fetch so it returns quickly.
            max_pages_per_term=1,
            throttle_seconds=0.0,
        )))

    for entry in json_sources:
        name = (entry or {}).get("name") or "(unnamed JSON)"
        url = (entry or {}).get("url")
        if not url:
            results.append(TestFetchSourceResult(
                name=name, url=None, status="misconfigured",
                event_count=0, sample_titles=[],
                error="missing 'url' field", source_type="json",
            ))
            continue
        results.append(await _probe("json", JsonApiSource(
            name=name,
            url=url,
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
        )))

    for entry in deyra_schedule_sources:
        name = (entry or {}).get("name") or "(unnamed deyra schedule)"
        url = (entry or {}).get("url")
        if not url:
            results.append(TestFetchSourceResult(
                name=name, url=None, status="misconfigured",
                event_count=0, sample_titles=[],
                error="missing 'url' field", source_type="deyra_schedule",
            ))
            continue
        results.append(await _probe("deyra_schedule", DeyraScheduleSource(
            name=name,
            url=url,
            default_categories=list(entry.get("default_categories") or []),
            venue_name=entry.get("venue_name"),
            venue_address=entry.get("venue_address"),
            # Cap to 1 day for a fast dry-run; full pipeline uses the configured days_ahead.
            days_ahead=1,
        )))

    return TestFetchOut(kind=body.kind, sources=results)
