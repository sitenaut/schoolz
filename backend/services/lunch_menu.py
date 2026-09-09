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

import httpx
from anthropic import AsyncAnthropic

import scraper_client
from services.content_extractor import ANTHROPIC_API_KEY, MODEL, _parse_date

logger = logging.getLogger(__name__)

_GRADE_BAND_TO_SCHOOL_TYPE = {"ES": "elementary", "MS": "middle", "HS": "high"}
_PDF_FILENAME_RE = re.compile(
    r"([A-Za-z]+)0?(\d{4})-([A-Z]{2})-(Breakfast|Lunch)", re.IGNORECASE
)


def _classify_pdf_link(url: str) -> dict | None:
    match = _PDF_FILENAME_RE.search(url)
    if not match:
        return None
    month, year, grade_band, meal = match.groups()
    school_type = _GRADE_BAND_TO_SCHOOL_TYPE.get(grade_band.upper())
    if not school_type:
        return None
    return {
        "school_type": school_type,
        "meal_type": meal.lower(),
        "period_label": f"{month.title()} {year}",
        "pdf_url": url,
    }


async def discover_current_menus(menu_page_url: str) -> list[dict]:
    """Returns one entry per (school_type, meal_type) found on the page,
    e.g. {"school_type": "elementary", "meal_type": "lunch",
    "period_label": "September 2026", "pdf_url": "..."}."""
    result = await scraper_client.fetch_html(menu_page_url, wait_for_selector="a")
    urls = set(re.findall(r'href="([^"]+\.pdf)"', result["html"], re.IGNORECASE))

    by_key: dict[tuple, dict] = {}
    for url in urls:
        classified = _classify_pdf_link(url)
        if classified:
            by_key[(classified["school_type"], classified["meal_type"])] = classified
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
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_use:
        return []

    items = []
    for day in tool_use.input.get("days", []):
        parsed_date = _parse_date(day.get("date"))
        if not parsed_date:
            continue
        items.append({"date": parsed_date, "description": day["description"][:500], "notes": day.get("notes")})
    return items
