"""Modern Events Calendar (WordPress plugin) monthly view, via its own AJAX.

collingswoodlib.org runs MEC without an iCal export or usable REST route. Its
month navigator POSTs `mec_monthly_view_load_month` to admin-ajax.php and gets
back JSON whose `events_side` holds, per day, a schema.org JSON-LD block
(title, url, description, place) plus an `<article>` with the time range
("5:00 pm - 6:00 pm"). The JSON-LD's own startDate is date-only, so the time
comes from the article. The skin id is read off the calendar page; a skin
rendered with no `atts` still answers with the full month.

Example job-params entry:

    {
      "name": "collingswood_library",
      "page_url": "https://www.collingswoodlib.org/eventcalendar/",
      "months_ahead": 3,
      "default_categories": ["collingswood", "library"]
    }
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

from .base import RawEvent, Source

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
DEFAULT_MONTHS_AHEAD = 3
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
_SKIN_RE = re.compile(r'id="mec_skin_(\d+)"')
_AJAX_RE = re.compile(r'ajaxurl\s*=\s*"([^"]+)"')
_SECTION_RE = re.compile(r'<div class="mec-calendar-events-sec"\s+data-mec-cell="(\d{8})"\s*>')
_LDJSON_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_ARTICLE_RE = re.compile(r'<article\b.*?</article>', re.S)
_TIME_RE = re.compile(r'class="mec-event-time[^"]*">(?:\s*<i[^>]*></i>)?\s*([^<]*)<', re.S)
_CLOCK_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([ap])m", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    # The JSON-LD description is HTML that was then entity-escaped: undo that first.
    text = html.unescape(_TAG_RE.sub(" ", html.unescape(text))).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip() or None


def _clock(text: str) -> tuple[int, int] | None:
    m = _CLOCK_RE.search(text)
    if not m:
        return None
    hour, minute = int(m.group(1)) % 12, int(m.group(2) or 0)
    return hour + (12 if m.group(3).lower() == "p" else 0), minute


def _months(start: date, count: int) -> list[tuple[int, int]]:
    return [((start.year * 12 + start.month - 1 + i) // 12, (start.year * 12 + start.month - 1 + i) % 12 + 1) for i in range(count + 1)]


def parse_events_side(markup: str, name: str, default_categories: list[str]) -> list[RawEvent]:
    out: list[RawEvent] = []
    cells = list(_SECTION_RE.finditer(markup))
    for i, cell in enumerate(cells):
        day = datetime.strptime(cell.group(1), "%Y%m%d").date()
        block = markup[cell.end(): cells[i + 1].start() if i + 1 < len(cells) else len(markup)]
        # Each event is a JSON-LD block followed by its article.
        for ld in _LDJSON_RE.finditer(block):
            try:
                data = json.loads(ld.group(1), strict=False)
            except ValueError:
                continue
            title = _clean(data.get("name"))
            if not title:
                continue
            article = _ARTICLE_RE.search(block, ld.end())
            time_text = ""
            if article:
                tm = _TIME_RE.search(article.group(0))
                time_text = tm.group(1) if tm else ""
            clocks = _CLOCK_RE.findall(time_text)
            first = _clock(time_text)
            start = datetime(day.year, day.month, day.day, *(first or (0, 0)), tzinfo=ET)
            end = None
            if len(clocks) > 1:
                end_clock = _CLOCK_RE.findall(time_text)[-1]
                last = _clock(f"{end_clock[0]}:{end_clock[1] or '00'} {end_clock[2]}m")
                if last:
                    end = datetime(day.year, day.month, day.day, *last, tzinfo=ET)
            place = data.get("location") if isinstance(data.get("location"), dict) else {}
            url = data.get("url") or (data.get("offers") or {}).get("url")
            out.append(
                RawEvent(
                    source=name,
                    source_event_id=f"{url or title}:{day.isoformat()}",
                    title=title,
                    description=_clean(data.get("description")),
                    start_time=start,
                    end_time=end if end and end > start else None,
                    all_day=first is None,
                    venue_name=_clean(place.get("name")),
                    venue_address=_clean(place.get("address")),
                    url=url,
                    default_categories=list(default_categories),
                )
            )
    return out


class MECSource(Source):
    def __init__(
        self,
        name: str,
        page_url: str,
        *,
        default_categories: list[str] | None = None,
        months_ahead: int = DEFAULT_MONTHS_AHEAD,
        timeout: float = 30.0,
    ):
        self.name = name
        self.page_url = page_url
        self.default_categories = default_categories or []
        self.months_ahead = max(0, int(months_ahead))
        self.timeout = timeout

    async def fetch(self) -> list[RawEvent]:
        out: dict[str, RawEvent] = {}
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers={"User-Agent": _UA}) as client:
            page = await client.get(self.page_url)
            page.raise_for_status()
            skin, ajax = _SKIN_RE.search(page.text), _AJAX_RE.search(page.text)
            if not skin or not ajax:
                raise RuntimeError(f"{self.page_url} has no Modern Events Calendar monthly view")
            today = datetime.now(ET).date()
            for year, month in _months(today, self.months_ahead):
                resp = await client.post(
                    ajax.group(1),
                    data={
                        "action": "mec_monthly_view_load_month", "mec_year": year, "mec_month": f"{month:02d}",
                        "id": skin.group(1), "atts": "", "current_month_divider": f"{year}{month:02d}", "apply_sf_date": 0,
                    },
                )
                resp.raise_for_status()
                for ev in parse_events_side(resp.json().get("events_side") or "", self.name, self.default_categories):
                    # The grid pads with neighbouring months' days; the key dedups them.
                    if ev.start_time.date() >= today:
                        out[ev.source_event_id] = ev
        return list(out.values())
