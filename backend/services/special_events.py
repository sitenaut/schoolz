"""Discovers and parses a school's own monthly "special events" calendar
PDF - confirmed real for Chesterbrook Academy (a private preschool, not a
Cherry Hill Public Schools building): a themed calendar graphic per month
(spirit days like "Teddy Bear Day"/"Disney Day", plus the school's own
closures) linked from a page that was built to swap which month's PDFs it
lists via `?mm=&yy=` query params - not a live day-grid widget, just
download links.

The same page links each month's lunch menu PDF ("October-2026-Lunch-
Menu.pdf"), read here too (`discover_menu_pdf_urls`) and parsed like a
district menu. Two things about that page, both confirmed 2026-10:
* `?mm=` is ignored now - every month's URL serves the same list - so a
  PDF's month comes from its own filename, never from which URL listed it.
* It lags the uploads: October's menu was in `wp-content/uploads/.../2026/
  10/` while the page still listed only August and September. WordPress
  names uploads predictably, so a month the page doesn't list yet is looked
  for at its likely upload path (this month's or last month's folder).

Deliberately never promotes any of these to scope="district": unlike a
Cherry Hill public school, a private preschool's closure calendar is its
own, entirely independent of the district's - a "SCHOOL CLOSED" day here
applies to this one school, never every Cherry Hill school.
"""

import base64
import logging
import re
import time
from datetime import date

import httpx
from anthropic import AsyncAnthropic

import observability
import scraper_client
from services.content_extractor import ANTHROPIC_API_KEY, MODEL, _parse_date

logger = logging.getLogger(__name__)

_PDF_LINK_RE = re.compile(r'href="([^"]*Special-Events-Calendar[^"]*\.pdf)"', re.IGNORECASE)
_MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
_FILENAME_MONTH_RE = re.compile(r"/(" + "|".join(_MONTH_NAMES) + r")-(\d{4})-[^/]*\.pdf$", re.IGNORECASE)
_MENU_LINK_RE = re.compile(r'href="([^"]*/(?:' + "|".join(_MONTH_NAMES) + r')-\d{4}-Lunch-Menu[^"/]*\.pdf)"', re.IGNORECASE)
_UPLOADS_BASE_RE = re.compile(r'(https?://[^"\s]+?/wp-content/uploads/(?:sites/\d+/)?)\d{4}/\d{2}/', re.IGNORECASE)
_PDF_UA = {"User-Agent": "Mozilla/5.0 (schoolz menu sync)"}


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _find_calendar_pdf_url(html: str) -> str | None:
    match = _PDF_LINK_RE.search(html)
    return match.group(1) if match else None


def month_from_filename(url: str) -> tuple[int, int] | None:
    """'.../September-2026-Special-Events-Calendar.pdf' -> (2026, 9)."""
    m = _FILENAME_MONTH_RE.search(url)
    if not m:
        return None
    month = next(i for i, name in enumerate(_MONTH_NAMES, 1) if name.lower() == m.group(1).lower())
    return int(m.group(2)), month


async def fetch_month_pages(base_url: str, today: date | None = None) -> list[tuple[int, int, str]]:
    """The page for this month and next - [(year, month, html)] - for the
    calendar and the menu discovery to share. Schools sometimes post next
    month's files before the current one ends."""
    today = today or date.today()
    pages = []
    for year, month in [(today.year, today.month), _next_month(today.year, today.month)]:
        url = f"{base_url}{'&' if '?' in base_url else '?'}mm={month}&yy={year}"
        try:
            result = await scraper_client.fetch_html(url, wait_for_selector="a")
        except Exception:
            logger.exception("special_events_page_fetch_failed", extra={"url": url})
            continue
        pages.append((year, month, result["html"]))
    return pages


def calendar_pdfs_from_pages(pages: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """[(year, month, pdf_url)], one per month that has a calendar PDF. The
    month is the filename's when it names one - the page ignores `?mm=`, so
    October's page listing September's calendar must not file it as October."""
    found: dict[tuple[int, int], str] = {}
    for year, month, html in pages:
        pdf_url = _find_calendar_pdf_url(html)
        if pdf_url:
            found.setdefault(month_from_filename(pdf_url) or (year, month), pdf_url)
    return [(y, m, u) for (y, m), u in sorted(found.items())]


def menu_links_from_html(html: str) -> dict[tuple[int, int], str]:
    """{(year, month): pdf_url} for every '<Month>-<Year>-Lunch-Menu*.pdf'
    link. A later link for the same month wins (a re-upload gets '-1')."""
    out: dict[tuple[int, int], str] = {}
    for url in _MENU_LINK_RE.findall(html):
        ym = month_from_filename(url)
        if ym:
            out[ym] = url
    return out


_PORTION_RE = re.compile(r",\s*\d+(?:[./]\d+)?\s*(?:ea|oz|sl|slices?|cups?|c|tbsp|tsp|pcs?)\b\.?", re.IGNORECASE)


def strip_portions(description: str) -> str:
    """Chesterbrook's menu is a dietitian's sheet: 'Grilled Chicken Patty, 1ea;
    Ketchup, 1oz; ...'. The portions are noise to a parent (and read aloud by
    the Alexa skill), so 'Grilled Chicken Patty, Ketchup, ...'."""
    out = _PORTION_RE.sub("", description)
    out = re.sub(r"\s*;\s*", ", ", out)
    return re.sub(r"\s{2,}", " ", out).strip(" ,")


def menu_url_guesses(uploads_base: str, year: int, month: int) -> list[str]:
    """Where WordPress would have put that month's menu: uploaded during the
    month itself or the one before, maybe with a re-upload suffix."""
    name = f"{_MONTH_NAMES[month - 1]}-{year}-Lunch-Menu"
    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    folders = [f"{year}/{month:02d}", f"{prev_y}/{prev_m:02d}"]
    return [f"{uploads_base}{folder}/{name}{suffix}.pdf" for folder in folders for suffix in ("", "-1", "-2")]


async def _is_pdf(client: httpx.AsyncClient, url: str) -> bool:
    try:
        async with client.stream("GET", url) as resp:
            return resp.status_code == 200 and "pdf" in resp.headers.get("content-type", "")
    except httpx.HTTPError:
        return False


async def discover_menu_pdf_urls(pages: list[tuple[int, int, str]], today: date | None = None) -> list[tuple[int, int, str]]:
    """[(year, month, pdf_url)] for this month's and next month's lunch
    menus - linked on the page, or found at their likely upload path when
    the page hasn't caught up. A month with no menu anywhere is omitted."""
    today = today or date.today()
    wanted = [(today.year, today.month), _next_month(today.year, today.month)]
    linked: dict[tuple[int, int], str] = {}
    uploads_base = None
    for _, _, html in pages:
        linked.update(menu_links_from_html(html))
        uploads_base = uploads_base or (m.group(1) if (m := _UPLOADS_BASE_RE.search(html)) else None)
    found = []
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=_PDF_UA) as client:
        for year, month in wanted:
            url = linked.get((year, month))
            if not url and uploads_base:
                for guess in menu_url_guesses(uploads_base, year, month):
                    if await _is_pdf(client, guess):
                        url = guess
                        break
            if url:
                found.append((year, month, url))
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
    _llm_started = time.perf_counter()
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
    observability.record_llm_call("special_events", MODEL, response, time.perf_counter() - _llm_started)
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
