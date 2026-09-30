"""Discovers and parses district-published breakfast/lunch menu PDFs.

Confirmed real structure (Cherry Hill Public Schools): one food-services
page lists PDFs named like 'September2026-ES-Lunch.pdf' - grade band (ES/MS/HS)
and meal type (Breakfast/Lunch) encoded in the filename, a new PDF each
month rather than one edited in place. Menus are genuinely district-wide
(the same PDF serves every elementary school), so this parses once per
(district, school_type, meal_type) and every school of that type looks the
result up - see School.district_id/school_type and LunchMenu.
"""

import base64
import logging
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import urljoin

import httpx
from anthropic import AsyncAnthropic

import observability
import scraper_client
from services.content_extractor import ANTHROPIC_API_KEY, MODEL, _parse_date

logger = logging.getLogger(__name__)

_GRADE_BAND_TO_SCHOOL_TYPE = {"ES": "elementary", "MS": "middle", "HS": "high"}
_PDF_FILENAME_RE = re.compile(
    r"([A-Za-z]+)0?(\d{4})-([A-Z]{2})-(Breakfast|Lunch)", re.IGNORECASE
)

# Confirmed real (Audubon Public Schools): no hyphens at all, band spelled
# out ("Elementary"/"JH-HS"/"PreK") rather than a two-letter code, and the
# meal type is glued to a trailing "Menu" - e.g. "September2026JH-HSLunchMenu.pdf".
_BAND_WORD_TO_SCHOOL_TYPE = {"ELEMENTARY": "elementary", "MS": "middle", "HS": "high", "JHHS": "high", "PREK": "other"}
_PDF_FILENAME_RE2 = re.compile(
    r"([A-Za-z]+)0?(\d{4})([A-Za-z-]+?)(Breakfast|Lunch)Menu", re.IGNORECASE
)

# Confirmed real (Audubon Public Schools): the food-services page links a
# Finalsite "/fs/resource-manager/view/<uuid>" wrapper, not the PDF itself -
# the actual resources.finalsite.net PDF only appears after following that
# page's redirect, so a plain href=".pdf" scan finds nothing at all.
_RESOURCE_MANAGER_RE = re.compile(r'href="(/fs/resource-manager/view/[0-9a-fA-F-]+)"', re.IGNORECASE)


_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
# Eastern Regional's single monthly menu: "08182026_September2026_002.pdf" -
# no grade band, since the district is one high school.
_MONTH_YEAR_RE = re.compile(r"(" + "|".join(_MONTHS) + r")_?(\d{4})", re.IGNORECASE)


# Evesham publishes the menu PDF beside per-band "..._lunch_spreadsheet.pdf" /
# "..._breakfast_spreadsheet.pdf" nutrition tables with the same month prefix;
# those aren't menus.
_NOT_A_MENU_RE = re.compile(r"spreadsheet|nutrition|breakfast|allergen", re.IGNORECASE)


def _classify_unbanded_pdf_link(url: str, school_type: str) -> dict | None:
    filename = url.rsplit("/", 1)[-1]
    if _NOT_A_MENU_RE.search(filename):
        return None
    match = _MONTH_YEAR_RE.search(filename)
    if not match:
        return None
    month, year = match.groups()
    return {
        "school_type": school_type,
        "meal_type": "lunch",
        "period_label": f"{month.title()} {year}",
        "pdf_url": url,
        "_sort": (int(year), _MONTHS.index(month.lower())),
    }


def _classify_pdf_link(url: str) -> dict | None:
    filename = url.rsplit("/", 1)[-1]
    match = _PDF_FILENAME_RE.search(filename)
    if match:
        month, year, grade_band, meal = match.groups()
        school_type = _GRADE_BAND_TO_SCHOOL_TYPE.get(grade_band.upper())
        if school_type:
            return {
                "school_type": school_type,
                "meal_type": meal.lower(),
                "period_label": f"{month.title()} {year}",
                "pdf_url": url,
            }

    match2 = _PDF_FILENAME_RE2.search(filename)
    if match2:
        month, year, band, meal = match2.groups()
        school_type = _BAND_WORD_TO_SCHOOL_TYPE.get(re.sub(r"[^A-Za-z]", "", band).upper())
        if school_type:
            return {
                "school_type": school_type,
                "meal_type": meal.lower(),
                "period_label": f"{month.title()} {year}",
                "pdf_url": url,
            }

    return None


async def _resolve_resource_manager_links(page_url: str, html: str) -> set[str]:
    """Follows each Finalsite resource-manager wrapper link to its real
    PDF URL. Non-PDF resources (a handbook, a USDA notice) resolve fine but
    are simply filtered out by _classify_pdf_link downstream."""
    wrappers = {urljoin(page_url, path) for path in _RESOURCE_MANAGER_RE.findall(html)}
    if not wrappers:
        return set()
    resolved: set[str] = set()
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
        for wrapper_url in wrappers:
            try:
                resp = await client.head(wrapper_url)
            except httpx.HTTPError:
                continue
            final_url = str(resp.url)
            if final_url.lower().endswith(".pdf"):
                resolved.add(final_url)
    return resolved


async def discover_current_menus(menu_page_url: str, school_types: list[str] | None = None) -> list[dict]:
    """Returns one entry per (school_type, meal_type) found on the page,
    e.g. {"school_type": "elementary", "meal_type": "lunch",
    "period_label": "September 2026", "pdf_url": "..."}.

    `school_types` is the district's school types, for a district whose menu
    PDFs carry no grade band (Eastern: one high school; Evesham: one
    all-grades PDF): a bare month+year filename is taken as every listed
    type's lunch menu, latest month winning."""
    result = await scraper_client.fetch_html(menu_page_url, wait_for_selector="a")
    urls = set(re.findall(r'href="([^"]+\.pdf)"', result["html"], re.IGNORECASE))
    urls |= await _resolve_resource_manager_links(menu_page_url, result["html"])

    by_key: dict[tuple, dict] = {}
    for url in urls:
        classified = _classify_pdf_link(url)
        if classified:
            by_key[(classified["school_type"], classified["meal_type"])] = classified
    if not by_key and school_types:
        unbanded = [c for c in (_classify_unbanded_pdf_link(u, school_types[0]) for u in urls) if c]
        if unbanded:
            # This month and any later one: the next month's PDF is usually up
            # before the current month ends, and the current month's last days
            # still matter. Nothing current → the latest, as before.
            now = datetime.now(ZoneInfo("America/New_York"))
            current = [c for c in unbanded if c["_sort"] >= (now.year, now.month - 1)]
            picked = sorted(current or [max(unbanded, key=lambda c: c["_sort"])], key=lambda c: c["_sort"])
            return [{**{k: v for k, v in c.items() if k != "_sort"}, "school_type": t} for c in picked for t in school_types]
    return list(by_key.values())


_MENU_TOOL = {
    "name": "record_menu",
    "description": "Records the day-by-day meal entries from a school lunch/breakfast menu calendar.",
    "input_schema": {
        "type": "object",
        "properties": {
            "days": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "ISO 8601 date, e.g. '2026-09-03'."},
                        "description": {"type": "string", "description": "The meal(s) offered that day."},
                        "notes": {"type": "string", "description": "Anything else noted for that day (e.g. 'School Closed')."},
                    },
                    "required": ["date", "description"],
                },
            }
        },
        "required": ["days"],
    },
}


async def parse_menu_pdf(pdf_url: str, period_label: str) -> list[dict]:
    """Returns [{date: datetime, description: str, notes: str|None}, ...].
    Days marked only 'School Closed' with no meal are still included (with
    that as the description) so the calendar reads correctly."""
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
        tools=[_MENU_TOOL],
        tool_choice={"type": "tool", "name": "record_menu"},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}},
                    {
                        "type": "text",
                        "text": f"This is the {period_label} school menu calendar. Extract every day that has "
                        "an entry (a meal offered, or a note like 'School Closed'), resolving each into a full "
                        "ISO date for that month/year.",
                    },
                ],
            }
        ],
    )
    observability.record_llm_call("lunch_menu", MODEL, response, time.perf_counter() - _llm_started)
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_use:
        return []

    items = []
    for day in tool_use.input.get("days", []):
        parsed_date = _parse_date(day.get("date"))
        description = day.get("description")
        if not parsed_date or not description:
            continue
        items.append({"date": parsed_date, "description": description[:500], "notes": day.get("notes")})
    return items
