"""Scheduled job: refresh the local events feed from configured sources.

Ported from billz's events.refresh - same params, same defaults, same
pipeline (local_events/), so a source config tested in one app works in
the other. One difference: billz reports a failed source only as -1 in the
run summary; here any failed source makes the run a WARNING, so a dead feed
shows up in the Scans tab instead of hiding behind a success."""
from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from local_events.pipeline import run_pipeline
from scheduler.registry import register_job

DEFAULT_PARAMS = {
    "evvnt_sources": [
        # Evvnt discovery API — one paginated query per search_term, deduped on
        # objectID, filtered to the bbox. publisher_id scopes to a specific site.
        {
            "name": "70and73",
            "publisher_id": 8119,
            "search_terms": ["philadelphia", "camden", "cherry hill", "atlantic city"],
            "bbox": {"lat_min": 38.9, "lat_max": 40.3, "lng_min": -75.7, "lng_max": -74.0},
            "default_categories": ["entertainment"],
        }
    ],
    "json_sources": [
        # DPCalendar (Joomla component used by many NJ townships).
        # The `parser: "dpcalendar"` post-processor extracts calendar category
        # names from the HTML tooltip and detects cancelled events.
        {
            "name": "evesham_township",
            "url": "https://evesham-nj.org/index.php?option=com_dpcalendar&view=events&format=raw",
            "base_url": "https://evesham-nj.org",
            "parser": "dpcalendar",
            "default_categories": ["municipal"],
        }
    ],
    "ical_sources": [
        # Example shape (URL must point to an actual .ics feed, not a calendar landing page):
        # {"name": "cherryhill_township",
        #  "url": "https://www.cherryhill-nj.com/common/modules/iCalendar/iCalendar.aspx?feed=calendar",
        #  "default_categories": ["municipal", "family"]}
    ],
    "rss_sources": [
        # Example shape. `treat_pubdate_as_start: true` lets blog-style feeds
        # use the article publish date as the event date when no explicit
        # event-date field is present — leave false for event-plugin feeds.
        # {"name": "uwishunu",
        #  "url": "https://www.uwishunu.com/feed/",
        #  "default_categories": ["philly"],
        #  "treat_pubdate_as_start": false}
    ],
    "gcal_sources": [
        # phila.gov loads all its calendars from the Google Calendar v3 API.
        # IDs extracted from HAR capture of https://www.phila.gov/the-latest/all-events/
        # Only calendars that returned >0 events in that snapshot are included.
        {
            "name": "phila_gov",
            "api_key": "AIzaSyDbErVzyNPKfT2foVLZxCgtC-OO8FVSCUE",
            "referer": "https://www.phila.gov/",
            "default_categories": ["philadelphia", "municipal"],
            "months_ahead": 6,
            "calendar_ids": [
                "rvua773ubdecb44n1ienf6kjeo@group.calendar.google.com",   # Love Park Public Calendar (250)
                "3efanutsrofqu273785lh789ko@group.calendar.google.com",   # Parks & Recreation Special Events (153)
                "n5arf069v2ho67lt203mvf0oec@group.calendar.google.com",   # COVID Containment (117)
                "q4p7ff0b6ca85mrdmm6in741qo@group.calendar.google.com",   # Wedding Schedule (100)
                "phl.csc1640@gmail.com",                                   # (90)
                "phila.fairhousingcommission@gmail.com",                   # Fair Housing Commission (66)
                "phila.revenue.calendar@gmail.com",                        # Revenue (60)
                "efe037bd209ffe805a90f592ada461d24b180a7fac26a736f7bbf061435f4ee5@group.calendar.google.com",  # OHR Tech Spec (53)
                "scesk19l8m9bm9peo6uchob2g0@group.calendar.google.com",   # Office of Children and Families (52)
                "brtphilly@gmail.com",                                     # (50)
                "pdphresourcehubs@gmail.com",                              # Resource Hubs (39)
                "v9b53bmja6m3qh0lnv3lk0bg5k@group.calendar.google.com",   # PHL City ID Mobile Sites (37)
                "qhf9dub8ld1aj52qhqrnduf4fs@group.calendar.google.com",   # Murrell Dobbins CTE High School (26)
                "465l3t04phdold2di6hihsa8n4@group.calendar.google.com",   # Samuel Gompers School (26)
                "480da9e95f438c57b60f49ca97dd8c897f48eb9249f221c8b1487ebf5ceb5f6a@group.calendar.google.com",  # Reproductive/Adolescent/Child Health (26)
                "5ki7gktt4uk9j4jrvfmv8uqpsg@group.calendar.google.com",   # SUPHR (24)
                "itt3rmmphlrot0ijhuot7dopm8@group.calendar.google.com",   # Website Calendar (24)
                "phillyregisterofwills@gmail.com",                         # Register of Wills (22)
                "taxreviewboard@gmail.com",                                # Tax Review Board (20)
                "phillydhs@gmail.com",                                     # Philadelphia DHS (18)
                "phlpoliceadvisory@gmail.com",                             # Police Advisory (16)
                "philahistoricalcommission@gmail.com",                     # Historical Commission (15)
                "do6kgfl3sslqvfq0iumt9eogto@group.calendar.google.com",   # Events (13)
                "pchrfhc@gmail.com",                                       # (12)
                "phila.art.commission@gmail.com",                          # Art Commission (12)
                "cjpsphila@gmail.com",                                     # CJPS (11)
                "phl.licenses.inspections@gmail.com",                      # L&I (8)
                "officeofimmigrantaffairs@gmail.com",                      # Office of Immigrant Affairs (8)
                "od0i95b23a7svmvaunommav95s@group.calendar.google.com",   # Rate Board Meetings (8)
                "kensingtonmeetings@gmail.com",                            # Kensington Community Meetings (7)
                "3e25f973efe5e731714088f8e7d935d32c7ebb9cac6836597e77ee3de2a47b97@group.calendar.google.com",  # Board of Labor Standards (6)
                "lrqh5qpmrv3acli5kgfcloffgo@group.calendar.google.com",   # Administrative Board (6)
                "c_be625b034c255712d129a51d650f2246262effc4ce35e051df2f0cebec5f457f@group.calendar.google.com",  # Dept of Commerce (5)
                "beifrq1plp36g9eof9t6mobha0@group.calendar.google.com",   # Civic Engagement Academy (2)
            ],
        }
    ],
    "listing_page_sources": [
    ],
    "yodel_sources": [
        # Yodel (events.yodel.today) calendar widgets. Macaroni KID moved its
        # calendar here - its sitemap no longer lists events. Plain HTTP, no
        # scraper; see local_events/sources/yodel.py.
        {
            "name": "macaronikid_cherryhill",
            "widget_url": "https://events.yodel.today/y/widget/69cd3f9d63e5877b4044dac3",
            "fallback_url": "https://cherryhill.macaronikid.com/events",
            "default_categories": ["kids", "family"],
        }
    ],
    "sitemap_sources": [
        # For sites whose listing/calendar pages are JS-rendered shells but
        # whose per-event detail pages are server-rendered. (Macaroni KID
        # used to work this way; it's a yodel_sources entry now.)
        # We walk sitemap.xml, regex-filter URLs, scrape each detail page
        # through the scraper service, and dispatch to a named parser.
        #
        # Available parsers: "macaronikid".
        #
        # {"name": "macaronikid_cherryhill",
        #  "sitemap_url": "https://cherryhill.macaronikid.com/sitemap.xml",
        #  "url_pattern": "/events/[0-9a-f]{20,32}/",
        #  "parser": "macaronikid",
        #  "default_categories": ["kids", "family"],
        #  "max_pages": 60,
        #  "concurrency": 4}
    ],
    "deyra_schedule_sources": [
        # "Deyra Finder" class-schedule widget used by Open Y branch sites
        # (philaymca.org group exercise / open swim / open gym pages). Shows
        # one day at a time via a `df_start_date` query param with no public
        # API, so this renders the page once per day (via the JS scraper) and
        # reads that day's class list off the DOM, expanding the recurring
        # weekly schedule into `days_ahead` days of individual occurrences.
        {
            "name": "mt_laurel_ymca_group_exercise",
            "url": "https://www.philaymca.org/locations/mt-laurel-ymca/schedules/group-exercise",
            "venue_name": "Mt. Laurel YMCA",
            "venue_address": "59 Centerton Road, Mt. Laurel, NJ 08054",
            "default_categories": ["fitness", "group-exercise", "ymca"],
            "days_ahead": 14,
        },
        {
            "name": "mt_laurel_ymca_open_swim",
            "url": "https://www.philaymca.org/locations/mt-laurel-ymca/schedules/open-swim",
            "venue_name": "Mt. Laurel YMCA",
            "venue_address": "59 Centerton Road, Mt. Laurel, NJ 08054",
            "default_categories": ["pool", "swim", "ymca"],
            "days_ahead": 14,
        },
        {
            "name": "mt_laurel_ymca_open_gym",
            "url": "https://www.philaymca.org/locations/mt-laurel-ymca/schedules/open-gym",
            "venue_name": "Mt. Laurel YMCA",
            "venue_address": "59 Centerton Road, Mt. Laurel, NJ 08054",
            "default_categories": ["gym", "open-gym", "ymca"],
            "days_ahead": 14,
        },
    ],
    "scraper_sources": [
        # Sites that need JS rendering (SPAs) or block direct fetches. Goes
        # through the scraper service (scraper-droplet primary, scraper fallback).
        # Tries JSON-LD `Event` schema first; falls back to CSS selectors if
        # the page has none.
        #
        # `render_wait_selector`: CSS selector Playwright will wait for before
        # returning HTML — use when content loads via XHR after first paint.
        # `render_extra_wait_ms`: fixed extra delay (capped at 30s).
        #
        # {"name": "macaronikid_cherryhill",
        #  "url": "https://cherryhill.macaronikid.com/events/calendar",
        #  "default_categories": ["kids", "family"],
        #  "render_wait_selector": "div.calendar-eventlist a",
        #  "render_extra_wait_ms": 2000,
        #  "selectors": {
        #    "item": "div.calendar-eventlist",
        #    "title": "a",
        #    "date": "time[datetime]",
        #    "link": "a",
        #    "image": "img"
        #  }}
    ],
}


_NAMED_SOURCE_COMMON = {
    "name": {"type": "string", "description": "Stable identifier used for dedupe and logs."},
    "default_categories": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Tags applied to every event from this source.",
    },
}

EVENTS_REFRESH_PARAM_SCHEMA = {
    "type": "object",
    "description": (
        "Configures which feeds to pull on each run. Every source key is a list — "
        "leave a list empty to disable that source type."
    ),
    "properties": {
        "evvnt_sources": {
            "type": "array",
            "description": "Evvnt discovery API sources (e.g. 70and73.com). Queries one page per search term, dedupes on objectID, filters by bounding box.",
            "items": {
                "type": "object",
                "required": ["name", "publisher_id", "search_terms", "bbox"],
                "properties": {
                    **_NAMED_SOURCE_COMMON,
                    "publisher_id": {"type": "integer", "description": "Evvnt publisher account ID."},
                    "search_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Free-text search terms. One paginated query is issued per term.",
                    },
                    "bbox": {
                        "type": "object",
                        "description": "Geographic bounding box. Events outside it are dropped.",
                        "required": ["lat_min", "lat_max", "lng_min", "lng_max"],
                        "properties": {
                            "lat_min": {"type": "number"},
                            "lat_max": {"type": "number"},
                            "lng_min": {"type": "number"},
                            "lng_max": {"type": "number"},
                        },
                    },
                    "hits_per_page": {"type": "integer", "default": 100},
                    "max_pages_per_term": {"type": "integer", "default": 20},
                    "throttle_seconds": {"type": "number", "default": 1.5},
                },
            },
        },
        "json_sources": {
            "type": "array",
            "description": "JSON API endpoints that return an events array (e.g. DPCalendar, custom municipal APIs).",
            "items": {
                "type": "object",
                "required": ["name", "url"],
                "properties": {
                    **_NAMED_SOURCE_COMMON,
                    "url": {"type": "string", "description": "JSON endpoint URL."},
                    "base_url": {
                        "type": "string",
                        "description": "Prepended to relative event URLs (e.g. 'https://evesham-nj.org').",
                    },
                    "data_path": {
                        "type": "string",
                        "description": "Dot-path to the events array in the response.",
                        "default": "data.events",
                    },
                    "id_field": {"type": "string", "default": "id"},
                    "title_field": {"type": "string", "default": "title"},
                    "start_field": {"type": "string", "default": "start"},
                    "end_field": {"type": "string", "default": "end"},
                    "all_day_field": {"type": "string", "default": "allDay"},
                    "url_field": {"type": "string", "default": "url"},
                    "description_field": {"type": "string", "default": "description"},
                    "image_field": {"type": "string", "description": "JSON key for image URL (optional)."},
                    "parser": {
                        "type": "string",
                        "enum": ["dpcalendar"],
                        "description": "Site-specific post-processor. 'dpcalendar' handles Joomla DPCalendar HTML tooltips.",
                    },
                },
            },
        },
        "ical_sources": {
            "type": "array",
            "description": "iCalendar feeds (.ics URLs).",
            "items": {
                "type": "object",
                "required": ["name", "url"],
                "properties": {
                    **_NAMED_SOURCE_COMMON,
                    "url": {"type": "string", "description": "Direct .ics feed URL (not a calendar landing page)."},
                    "via_scraper": {
                        "type": "boolean",
                        "description": "Route the fetch through the Playwright scraper service to bypass WAF/Cloudflare blocks.",
                        "default": False,
                    },
                },
            },
        },
        "rss_sources": {
            "type": "array",
            "description": "RSS/Atom feeds.",
            "items": {
                "type": "object",
                "required": ["name", "url"],
                "properties": {
                    **_NAMED_SOURCE_COMMON,
                    "url": {"type": "string", "description": "Feed URL."},
                    "treat_pubdate_as_start": {
                        "type": "boolean",
                        "description": "Use the article publish date as the event start when no explicit event date is present.",
                        "default": False,
                    },
                },
            },
        },
        "gcal_sources": {
            "type": "array",
            "description": "Public Google Calendar feeds fetched via the Calendar v3 API (API key, no OAuth).",
            "items": {
                "type": "object",
                "required": ["name", "calendar_ids", "api_key"],
                "properties": {
                    **_NAMED_SOURCE_COMMON,
                    "calendar_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "One or more Google Calendar IDs (e.g. 'abc123@group.calendar.google.com'). Events from all IDs are merged.",
                    },
                    "api_key": {"type": "string", "description": "Google API key with Calendar read access."},
                    "referer": {"type": "string", "description": "Referer header sent with each request — set to the site that owns the calendar if the key has referrer restrictions."},
                    "months_ahead": {"type": "integer", "default": 6, "description": "How many months ahead to fetch (timeMax = now + months_ahead months)."},
                },
            },
        },
        "listing_page_sources": {
            "type": "array",
            "description": "Render a JS listing page, extract event detail URLs by href regex, scrape each detail page for JSON-LD events.",
            "items": {
                "type": "object",
                "required": ["name", "listing_url", "url_pattern"],
                "properties": {
                    **_NAMED_SOURCE_COMMON,
                    "listing_url": {"type": "string", "description": "URL of the JS-rendered listing/calendar page."},
                    "url_pattern": {"type": "string", "description": "Regex applied to hrefs found on the listing page. Matched hrefs are scraped as detail pages."},
                    "link_selector": {"type": "string", "default": "a", "description": "CSS selector to find candidate <a> elements on the listing page."},
                    "render_wait_selector": {"type": "string", "description": "CSS selector Playwright waits for on the listing page before returning HTML."},
                    "render_extra_wait_ms": {"type": "integer", "description": "Fixed extra delay on listing page (capped at 30000)."},
                    "detail_render_wait_selector": {"type": "string", "description": "CSS selector Playwright waits for on each detail page."},
                    "detail_render_extra_wait_ms": {"type": "integer", "description": "Fixed extra delay on each detail page."},
                    "parser": {
                        "type": "string",
                        "enum": ["macaronikid"],
                        "description": "Optional named detail-page parser. Defaults to JSON-LD extraction when omitted.",
                    },
                    "max_pages": {"type": "integer", "default": 80},
                    "concurrency": {"type": "integer", "default": 4},
                },
            },
        },
        "sitemap_sources": {
            "type": "array",
            "description": "Walk sitemap.xml, regex-filter URLs, scrape detail pages through a named parser.",
            "items": {
                "type": "object",
                "required": ["name", "sitemap_url", "url_pattern", "parser"],
                "properties": {
                    **_NAMED_SOURCE_COMMON,
                    "sitemap_url": {"type": "string"},
                    "url_pattern": {"type": "string", "description": "Regex applied to sitemap URLs to keep only event pages."},
                    "parser": {"type": "string", "enum": ["macaronikid"], "description": "Detail-page parser identifier."},
                    "max_pages": {"type": "integer", "default": 60},
                    "concurrency": {"type": "integer", "default": 4},
                },
            },
        },
        "deyra_schedule_sources": {
            "type": "array",
            "description": "Open Y 'Deyra Finder' recurring class-schedule widgets (group exercise / open swim / open gym pages). Renders one day at a time via the JS scraper and expands the weekly schedule into individual daily occurrences.",
            "items": {
                "type": "object",
                "required": ["name", "url"],
                "properties": {
                    **_NAMED_SOURCE_COMMON,
                    "url": {"type": "string", "description": "The branch schedule page URL (e.g. .../schedules/group-exercise)."},
                    "venue_name": {"type": "string", "description": "Branch name shown as the event venue."},
                    "venue_address": {"type": "string", "description": "Branch street address shown as the event venue address."},
                    "days_ahead": {"type": "integer", "default": 14, "description": "How many days ahead to render and expand into events (max 60)."},
                },
            },
        },
        "yodel_sources": {
            "type": "array",
            "description": "Yodel (events.yodel.today) calendar widgets, e.g. the one Macaroni KID embeds on its /events page. Plain HTTP, no scraper: reads the widget's server-rendered first page, then pages through its own 'load more' call.",
            "items": {
                "type": "object",
                "required": ["name", "widget_url"],
                "properties": {
                    **_NAMED_SOURCE_COMMON,
                    "widget_url": {"type": "string", "description": "The widget URL from the host page's iframe, https://events.yodel.today/y/widget/<id>."},
                    "fallback_url": {"type": "string", "description": "Link used for an event with no website/tickets/registration URL of its own (Yodel's event pages block non-browser clients)."},
                    "max_pages": {"type": "integer", "default": 10},
                },
            },
        },
        "scraper_sources": {
            "type": "array",
            "description": "JS-rendered or fetch-blocked sites — routed through the scraper service.",
            "items": {
                "type": "object",
                "required": ["name", "url"],
                "properties": {
                    **_NAMED_SOURCE_COMMON,
                    "url": {"type": "string"},
                    "render_wait_selector": {
                        "type": "string",
                        "description": "CSS selector Playwright waits for before returning HTML.",
                    },
                    "render_extra_wait_ms": {
                        "type": "integer",
                        "description": "Fixed extra delay (capped at 30000).",
                    },
                    "selectors": {
                        "type": "object",
                        "description": "CSS-selector fallback when no JSON-LD Event schema is present on the page.",
                        "properties": {
                            "item": {"type": "string"},
                            "title": {"type": "string"},
                            "date": {"type": "string"},
                            "link": {"type": "string"},
                            "image": {"type": "string"},
                        },
                    },
                },
            },
        },
    },
    "required": [],
}


@register_job(
    kind="local_events.refresh",
    default_name="Local events refresh",
    default_cron="0 */3 * * *",  # every 3 hours
    default_params=DEFAULT_PARAMS,
    description="Fetch local-event feeds (iCal, RSS, JSON, Google Calendar, Evvnt, sitemap/listing/scraper pages, Open Y schedules), normalize, dedupe, and upsert into local_events.",
    param_schema=EVENTS_REFRESH_PARAM_SCHEMA,
)
async def run(db: AsyncSession, params: dict) -> str | None:
    summary = await run_pipeline(db, params)
    failed = [name for name, count in (summary.get("per_source") or {}).items() if count == -1]
    text = json.dumps(summary, default=str)
    if failed:
        return f"WARNING[local_event_source_failed]: {len(failed)} source(s) failed ({', '.join(failed)}): {text}"
    partial = summary.get("partial_failures") or {}
    if partial:
        return f"WARNING[local_event_source_partial]: part of {len(partial)} source(s) failed ({', '.join(partial)}): {text}"
    return text
