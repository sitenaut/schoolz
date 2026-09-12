"""Discovers and parses a school's own monthly "special events" calendar
PDF - confirmed real for Chesterbrook Academy (a private preschool, not a
Cherry Hill Public Schools building): a themed calendar graphic per month
(spirit days like "Teddy Bear Day"/"Disney Day", plus the school's own
closures) linked from a page that swaps which month's PDFs it lists via
`?mm=&yy=` query params - not a live day-grid widget, just download links.

Deliberately never promotes any of these to scope="district": unlike a
Cherry Hill public school, a private preschool's closure calendar is its
own, entirely independent of the district's - a "SCHOOL CLOSED" day here
applies to this one school, never every Cherry Hill school.
"""

import base64
import logging
import re
from datetime import date

import httpx
from anthropic import AsyncAnthropic

import scraper_client
from services.content_extractor import ANTHROPIC_API_KEY, MODEL, _parse_date

logger = logging.getLogger(__name__)

_PDF_LINK_RE = re.compile(r'href="([^"]*Special-Events-Calendar[^"]*\.pdf)"', re.IGNORECASE)


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _find_calendar_pdf_url(html: str) -> str | None:
    match = _PDF_LINK_RE.search(html)
    return match.group(1) if match else None


async def discover_calendar_pdf_urls(base_url: str, today: date | None = None) -> list[tuple[int, int, str]]:
    """Checks the current month's page and next month's - schools sometimes
    post next month's calendar before the current one ends. Returns
    [(year, month, pdf_url), ...], one entry per month that actually has a
    calendar PDF linked (a month with nothing posted yet is just omitted)."""
    today = today or date.today()
    months = [(today.year, today.month), _next_month(today.year, today.month)]
    found = []
    for year, month in months:
        url = f"{base_url}{'&' if '?' in base_url else '?'}mm={month}&yy={year}"
        try:
            result = await scraper_client.fetch_html(url, wait_for_selector="a")
        except Exception:
            logger.exception("special_events_page_fetch_failed", extra={"url": url})
            continue
        pdf_url = _find_calendar_pdf_url(result["html"])
        if pdf_url:
            found.append((year, month, pdf_url))
    return found


_SPECIAL_EVENTS_TOOL = {
    "name": "record_special_events",
    "description": "Records the labeled day entries from a monthly special-events calendar graphic.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "day": {"type": "integer", "description": "Day of the month (1-31)."},
                        "title": {"type": "string", "description": "The event/theme-day label as shown, verbatim (e.g. 'Teddy Bear Day', 'SCHOOL CLOSED', 'Grandparent's Day Snack at 3pm')."},
                        "note": {"type": "string", "description": "Any secondary text under the title (e.g. 'Wear Your Disney Gear!', 'Bring a Teddy Bear!'), if present."},
                    },
                    "required": ["day", "title"],
                },
            }
        },
        "required": ["items"],
    },
}


async def parse_special_events_pdf(pdf_url: str, year: int, month: int) -> list[dict]:
    """Returns [{date: datetime, title: str, note: str|None}, ...]."""
    if not ANTHROPIC_API_KEY:
        return []

    async with httpx.AsyncClient(timeout=20.0) as http_client:
        resp = await http_client.get(pdf_url)
        resp.raise_for_status()
        pdf_b64 = base64.b64encode(resp.content).decode("ascii")

    client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model=MODEL,
        max_tokens=4096,
        tools=[_SPECIAL_EVENTS_TOOL],
        tool_choice={"type": "tool", "name": "record_special_events"},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
                    {
                        "type": "text",
                        "text": f"This is a preschool's {year}-{month:02d} monthly calendar of special/spirit days "
                        "(a themed graphic, one day per grid cell). Extract every day that has a label - a themed "
                        "day, a closure, a scheduled activity - skipping blank days and purely decorative icons with "
                        "no text. Keep each title exactly as written, including any time mentioned.",
                    },
                ],
            }
        ],
    )
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_use:
        return []

    items = []
    for entry in tool_use.input.get("items", []):
        day = entry.get("day")
        if not isinstance(day, int) or not (1 <= day <= 31):
            continue
        parsed_date = _parse_date(f"{year:04d}-{month:02d}-{day:02d}")
        if not parsed_date:
            continue
        items.append({"date": parsed_date, "title": entry["title"][:300], "note": entry.get("note")})
    return items
