"""Ludus-hosted ticketing sites (ludus.com) - a school or theatre company's
own events page, plain server-rendered HTML, no model call needed: one
`<div class="show_item" data-show-id>` per production with a nested
`<div class="showtimes_item" data-showtime-id>` per performance, both with
stable platform-issued ids. Confirmed on Collingswood's school theatre
program (collstheater.ludus.com), which lists CHS and CMS shows on one
shared page, each `show_item` tagged with one or more
`.show_item_category_pill` labels ("CHS"/"CMS"). `school_labels` maps those
labels to a school slug; a show whose label matches gets `RawEvent.school_slug`
set, which the pipeline uses to also publish it on that school's own public
page (see `school_sync.py`) - a school's own theatre program is both a
community event and school content, not one or the other.

One RawEvent per performance, not per production: each showtime already has
its own id, date and time, so there's nothing to summarize into a date range
(contrast theatre.py, which reads free-form prose and has to ask a model to
guess the right granularity).

What's deliberately NOT read: Ludus renders `.sold_out_span` and
`.join_waitlist_button_container` unconditionally in every showtime's markup
regardless of real availability (confirmed: present and identical whether a
showtime is on sale, not yet on sale, or actually sold out) - true
availability is decided client-side by JS this fetch never runs, so the
element's mere presence carries no signal. Only "not yet on sale" is
reliable: it's `.patron_coming_soon_badge` XOR `.showtimes_item_get_tickets_button`,
a real server-side conditional, not a later JS-toggled class. Asserting
sold-out status from a signal that's always present would tell people a
show is sold out when it might not be - worse than saying nothing.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from .base import RawEvent, Source
from .scraper import fetch_rendered_html

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_DATE_RE = re.compile(r"([A-Z][a-z]+ \d{1,2}, \d{4})")
_TIME_RE = re.compile(r"(\d{1,2}:\d{2}\s*[AP]M)", re.I)


def _parse_showtime(text: str) -> datetime | None:
    # \s matches the non-breaking spaces Ludus pads its date/time text with.
    text = re.sub(r"\s+", " ", text).strip()
    date_match = _DATE_RE.search(text)
    if not date_match:
        return None
    day = datetime.strptime(date_match.group(1), "%B %d, %Y")
    time_match = _TIME_RE.search(text)
    if not time_match:
        return datetime(day.year, day.month, day.day, tzinfo=_ET)
    clock = datetime.strptime(time_match.group(1).upper().replace(" ", ""), "%I:%M%p")
    return datetime(day.year, day.month, day.day, clock.hour, clock.minute, tzinfo=_ET)


class LudusSource(Source):
    """One Ludus site's public events listing (`index.php?sections=events`)."""

    def __init__(
        self,
        name: str,
        url: str,
        *,
        venue_name: str | None = None,
        venue_address: str | None = None,
        default_categories: list[str] | None = None,
        school_labels: dict[str, str] | None = None,
    ):
        self.name = name
        self.url = url
        self.venue_name = venue_name
        self.venue_address = venue_address
        self.default_categories = default_categories or ["theatre", "arts"]
        self.school_labels = school_labels or {}
        self.partial_failures: list[str] = []

    async def fetch(self) -> list[RawEvent]:
        self.partial_failures = []
        html = None
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": _UA}) as client:
                resp = await client.get(self.url)
                resp.raise_for_status()
                html = resp.text
        except httpx.HTTPError as direct_exc:
            # Confirmed real: a plain request from a dev machine gets 200,
            # the same request from a datacenter IP (this backend's own, or
            # Fly's in prod) gets a bot-blocked 403. Stealth + a residential
            # IP (the scraper service's droplet/Pi split) gets through.
            try:
                html, _ = await fetch_rendered_html(self.url, wait_for_selector="div.show_item")
            except Exception as scraper_exc:  # noqa: BLE001
                raise RuntimeError(
                    f"direct fetch: {type(direct_exc).__name__}: {direct_exc}; "
                    f"scraper fallback: {type(scraper_exc).__name__}: {scraper_exc}"
                ) from scraper_exc

        soup = BeautifulSoup(html, "lxml")
        events: list[RawEvent] = []
        skipped_undated = 0
        for item in soup.select("div.show_item[data-show-id]"):
            show_id = item.get("data-show-id")
            title_el = item.select_one(".show_item_title .patron_heading_label") or item.select_one(".show_item_title")
            title = re.sub(r"\s+", " ", title_el.get_text(" ", strip=True)) if title_el else ""
            if not show_id or not title:
                continue
            labels = [re.sub(r"\s+", " ", p.get_text(strip=True)) for p in item.select(".show_item_category_pill")]
            school_slug = next((self.school_labels[label] for label in labels if label in self.school_labels), None)
            detail_link = item.select_one('a[href*="show_location.php"]')
            detail_url = urljoin(self.url, detail_link["href"]) if detail_link and detail_link.get("href") else self.url

            for showtime in item.select("div.showtimes_item[data-showtime-id]"):
                if showtime.get("data-past-date") == "1":
                    continue
                showtime_id = showtime.get("data-showtime-id")
                time_el = showtime.select_one(".admin_showtimes_item_title .desktop_copy .span_link")
                start = _parse_showtime(time_el.get_text(" ", strip=True)) if time_el else None
                if not showtime_id or not start:
                    skipped_undated += 1
                    continue
                coming_soon = showtime.select_one(".patron_coming_soon_badge") is not None
                events.append(
                    RawEvent(
                        source=self.name,
                        source_event_id=f"ludus:{show_id}:{showtime_id}",
                        title=title,
                        description="Not yet on sale." if coming_soon else None,
                        start_time=start,
                        all_day=False,
                        venue_name=self.venue_name,
                        venue_address=self.venue_address,
                        url=detail_url,
                        default_categories=list(self.default_categories),
                        school_slug=school_slug,
                    )
                )
        if not events:
            raise RuntimeError(
                f"no showtimes found ({skipped_undated} show_item(s) had no parseable showtime) - "
                "page structure may have changed"
            )
        return events
