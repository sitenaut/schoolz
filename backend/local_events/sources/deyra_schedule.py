"""Source adapter for the "Deyra Finder" class-schedule widget used by Open Y
branch sites (e.g. philaymca.org group exercise / open swim / open gym pages).

The widget shows one day's classes at a time, selected via the `df_start_date`
query param, and has no public read API — so this source renders the page
once per day (via the JS scraper service) and reads that day's class list off
the DOM. Each class is a slot in a recurring weekly pattern with no calendar
date of its own; since the `events` table has no recurrence concept, this
expands the schedule into one Event row per class per day for `days_ahead`
days.

The widget attaches its content via a *declarative* shadow root
(`<template shadowrootmode="open">`), which Chromium serializes back into
`outerHTML`/`page.content()` as long as the shadow root was created
serializable (the default for declarative shadow DOM) — confirmed by testing
against a real saved copy of the page. `html.parser` (via BeautifulSoup) does
not implement `<template>` content-fragment semantics, so `soup.find_all(...)`
walks straight through it like a normal container element.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .base import RawEvent, Source
from .scraper import fetch_rendered_html

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("America/New_York")

_TIME_RANGE_RE = re.compile(r"(\d{1,2}:\d{2}\s*[AP]M)\s*-\s*(\d{1,2}:\d{2}\s*[AP]M)", re.I)


def _parse_time_on(day: date, text: str) -> datetime | None:
    try:
        t = datetime.strptime(text.strip().upper(), "%I:%M %p").time()
    except ValueError:
        return None
    return datetime.combine(day, t, tzinfo=_TZ)


_TEMPLATE_TAG_RE = re.compile(r"</?template\b[^>]*>", re.I)


class DeyraScheduleSource(Source):
    def __init__(
        self,
        name: str,
        url: str,
        default_categories: list[str] | None = None,
        venue_name: str | None = None,
        venue_address: str | None = None,
        days_ahead: int = 14,
    ):
        self.name = name
        self.url = url
        self.default_categories = default_categories or []
        self.venue_name = venue_name
        self.venue_address = venue_address
        self.days_ahead = max(1, min(days_ahead, 60))

    def _day_url(self, day: date) -> str:
        sep = "&" if "?" in self.url else "?"
        return f"{self.url}{sep}df=%2Fresults&df_start_date={day.isoformat()}&df_page=1"

    async def fetch(self) -> list[RawEvent]:
        raws: list[RawEvent] = []
        today = datetime.now(_TZ).date()
        failures: list[str] = []
        fetched_days = 0
        for offset in range(self.days_ahead):
            day = today + timedelta(days=offset)
            day_url = self._day_url(day)
            try:
                html, fetched_url = await self._render_day(day_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "deyra_schedule_fetch_failed",
                    extra={"source": self.name, "day": day.isoformat(), "error": str(exc)},
                )
                # The tail of the message names the service that actually
                # failed last (the fallback) - the head is the droplet.
                failures.append(f"{day.isoformat()}: ...{str(exc)[-240:]}")
                continue
            fetched_days += 1
            raws.extend(self._parse_day(html, day, fetched_url))
        # These used to be swallowed, so a dead renderer looked like "0 events,
        # success" for days. Every day failing is a failed source; some days
        # failing, or pages that rendered with no classes in them (the widget
        # changed, or its content went missing again), is a WARNING.
        if not fetched_days and failures:
            raise RuntimeError(f"every day failed to render: {failures[0]}")
        self.partial_failures = failures[:3]
        if fetched_days and not raws:
            self.partial_failures.append(f"{fetched_days} day(s) rendered but no classes were found in them")
        return raws

    async def _render_day(self, day_url: str) -> tuple[str, str]:
        """One retry: on prod's 1GB scraper this page (240KB plus ad
        trackers) took ~16s to reach "success" against a 15s default limit,
        so days failed at random - a different set each run."""
        for attempt in range(2):
            try:
                return await fetch_rendered_html(
                    day_url,
                    wait_for_selector='[data-test="success"] article, [data-test="success"]',
                    extra_wait_ms=1500,
                    # playwright-stealth's patches break this widget's own JS
                    # outright (it throws "DeyraFinder is not defined" and
                    # never initializes) — confirmed by direct testing, not
                    # needed anyway since this site shows no bot-challenge.
                    stealth=False,
                    # The schedule renders inside <deyra-finder>'s shadow
                    # root, which a plain page.content() leaves out.
                    include_shadow_dom=True,
                    timeout_ms=40_000,
                )
            except Exception:
                if attempt == 1:
                    raise
        raise AssertionError("unreachable")

    def _parse_day(self, html: str, day: date, page_url: str) -> list[RawEvent]:
        # The widget's content arrives as declarative shadow DOM
        # (<template shadowrootmode="open">, from include_shadow_dom), and
        # BeautifulSoup keeps text inside <template> as TemplateString, which
        # get_text() skips - every field parsed as "". Unwrap the tags first.
        html = _TEMPLATE_TAG_RE.sub("", html)
        soup = BeautifulSoup(html, "html.parser")
        out: list[RawEvent] = []
        for article in soup.find_all("article"):
            time_div = article.find(
                "div", class_=lambda c: bool(c) and "font-sunflower" in c and "font-medium" in c
            )
            if time_div is None:
                continue  # not a class card — e.g. the page-level Drupal <article>
            m = _TIME_RANGE_RE.search(time_div.get_text(" ", strip=True))
            if not m:
                continue
            start = _parse_time_on(day, m.group(1))
            end = _parse_time_on(day, m.group(2))
            if start is None:
                continue

            grid = time_div.parent
            cells = grid.find_all("div", recursive=False)
            if len(cells) < 2:
                continue
            title_cell = cells[1]
            title_node = title_cell.find("div")
            title = (title_node or title_cell).get_text(" ", strip=True)
            if not title:
                continue
            cancelled = title_node is not None and any(
                "line-through" in c for c in (title_node.get("class") or [])
            )
            if cancelled:
                continue

            # Cells between title and actions vary: some schedules (group exercise)
            # render an instructor cell and a room cell; others (open swim/gym)
            # render only a room cell — the instructor slot becomes an HTML
            # comment placeholder instead of an empty div, shifting positions.
            # The room cell is distinguished by a nested "mb-1"-classed div.
            instructor: str | None = None
            room: str | None = None
            for cell in cells[2:-1]:
                if cell.find("div", class_=lambda c: bool(c) and "mb-1" in c):
                    room = cell.get_text(" ", strip=True) or None
                else:
                    text = cell.get_text(" ", strip=True)
                    if text:
                        instructor = text
            description = None
            if room and instructor:
                description = f"Room: {room} — Instructor: {instructor}"
            elif room:
                description = f"Room: {room}"
            elif instructor:
                description = f"Instructor: {instructor}"

            sid = "hash:" + hashlib.sha1(
                f"{self.name}|{title}|{start.isoformat()}|{room or ''}".encode("utf-8")
            ).hexdigest()[:24]

            out.append(
                RawEvent(
                    source=self.name,
                    source_event_id=sid,
                    title=title,
                    description=description,
                    start_time=start,
                    end_time=end,
                    venue_name=self.venue_name,
                    venue_address=self.venue_address,
                    url=page_url,
                    default_categories=list(self.default_categories),
                    raw={"instructor": instructor, "room": room, "day": day.isoformat()},
                )
            )
        return out
