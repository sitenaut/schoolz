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
from datetime import date, datetime
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
# Runnemede's is "OCTOBER  2026  Menu.pdf" (double spaces, so "%20%20" in the href).
_MONTH_YEAR_RE = re.compile(r"(" + "|".join(_MONTHS) + r")(?:_|%20|\s)*(\d{4})", re.IGNORECASE)


# Evesham publishes the menu PDF beside per-band "..._lunch_spreadsheet.pdf" /
# "..._breakfast_spreadsheet.pdf" nutrition tables with the same month prefix;
# those aren't menus.
_NOT_A_MENU_RE = re.compile(r"spreadsheet|nutrition|breakfast|allergen", re.IGNORECASE)


# Laurel Springs: "2026-09-Lunch-Menu-LSS.pdf" - numeric month, and one PDF
# holding a breakfast page and a lunch page.
_NUMERIC_MENU_RE = re.compile(r"(\d{4})-(\d{2})-(Breakfast|Lunch)-Menu", re.IGNORECASE)


def _classify_numeric_pdf_link(url: str, school_type: str) -> dict | None:
    match = _NUMERIC_MENU_RE.search(url.rsplit("/", 1)[-1])
    if not match or not 1 <= int(match.group(2)) <= 12:
        return None
    year, month, meal = int(match.group(1)), int(match.group(2)), match.group(3)
    return {
        "school_type": school_type,
        "meal_type": meal.lower(),
        "period_label": f"{_MONTHS[month - 1].title()} {year}",
        "pdf_url": url,
        "_sort": (year, month - 1),
    }


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


# Merchantville: one school, no grade band, abbreviated month, 2- or 4-digit
# year, and a Spanish twin of every PDF - "MERSept26LunchMenu_1.pdf" beside
# "MERSept26LunchMenuSPA_1.pdf". The prefix is glued onto the month, so the
# month is found by its first three letters rather than anchored at the start.
#
# The year is optional: Magnolia's files are "SEPTLUNCHMENU.pdf" / "OCTLUNCHMENU.pdf",
# the same name every year, so the year is inferred as the one putting that
# month closest to today.
_ABBREV_MENU_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*?(\d{4}|\d{2})?(Breakfast|Lunch)Menu(?!_?SPA)",
    re.IGNORECASE,
)


def _infer_year(month_idx: int, today: date) -> int:
    return min((today.year - 1, today.year, today.year + 1), key=lambda y: abs((date(y, month_idx + 1, 15) - today).days))


def _classify_abbreviated_pdf_link(url: str, school_type: str, today: date | None = None) -> dict | None:
    match = _ABBREV_MENU_RE.search(url.rsplit("/", 1)[-1])
    if not match:
        return None
    month_abbr, year, meal = match.groups()
    month_idx = next(i for i, m in enumerate(_MONTHS) if m.startswith(month_abbr.lower()))
    if year is None:
        year_num = _infer_year(month_idx, today or datetime.now(ZoneInfo("America/New_York")).date())
    else:
        year_num = int(year) + 2000 if len(year) == 2 else int(year)
    return {
        "school_type": school_type,
        "meal_type": meal.lower(),
        "period_label": f"{_MONTHS[month_idx].title()} {year_num}",
        "pdf_url": url,
        "_sort": (year_num, month_idx),
    }


def _month_sort(month: str, year: str) -> tuple[int, int]:
    # A typo'd month ("Setember") sorts first rather than raising.
    idx = next((i for i, m in enumerate(_MONTHS) if m.startswith(month.lower()[:3])), -1)
    return (int(year), idx)


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
                "_sort": _month_sort(month, year),
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
                "_sort": _month_sort(month, year),
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
    result = await scraper_client.fetch_html(menu_page_url, wait_for_selector="a", block_assets=True)

    # Edlio/ednet file links are site-relative and carry a cache-buster
    # ("/ourpages/auto/.../File.pdf?rnd=1773934928084") once a file is replaced.
    urls = {urljoin(menu_page_url, u) for u in re.findall(r'href="([^"]+\.pdf(?:\?[^"]*)?)"', result["html"], re.IGNORECASE)}
    urls |= await _resolve_resource_manager_links(menu_page_url, result["html"])

    by_key: dict[tuple, dict] = {}
    for url in urls:
        classified = _classify_pdf_link(url)
        if classified:
            key = (classified["school_type"], classified["meal_type"])
            # The page can list more than one month at once, and `urls` is a
            # set: without this the winner was whichever came last in a
            # per-process-random order, so one scheduler process kept
            # re-picking an already-stored month and never saw the next one.
            if key not in by_key or classified["_sort"] > by_key[key]["_sort"]:
                by_key[key] = classified
    if not by_key and school_types:
        now = datetime.now(ZoneInfo("America/New_York"))

        def current_or_latest(entries: list[dict]) -> list[dict]:
            # This month and any later one: the next month's PDF is usually up
            # before the current month ends, and the current month's last days
            # still matter. Nothing current → the latest, as before.
            current = [c for c in entries if c["_sort"] >= (now.year, now.month - 1)]
            return sorted(current or [max(entries, key=lambda c: c["_sort"])], key=lambda c: c["_sort"])

        def fan_out(picked: list[dict]) -> list[dict]:
            return [{**{k: v for k, v in c.items() if k != "_sort"}, "school_type": t} for c in picked for t in school_types]

        by_meal: dict[str, list[dict]] = {}
        for c in (_classify_abbreviated_pdf_link(u, school_types[0]) or _classify_numeric_pdf_link(u, school_types[0]) for u in urls):
            if c:
                by_meal.setdefault(c["meal_type"], []).append(c)
        if by_meal:
            return fan_out([c for entries in by_meal.values() for c in current_or_latest(entries)])

        unbanded = [c for c in (_classify_unbanded_pdf_link(u, school_types[0]) for u in urls) if c]
        if unbanded:
            return fan_out(current_or_latest(unbanded))
    return [{k: v for k, v in c.items() if k != "_sort"} for c in by_key.values()]


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


def _sniff_image_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


_PRESENCE_MENU_EXTS = {"pdf", "jpg", "jpeg", "png"}
_MONTH_WORD_RE = re.compile(r"\b(" + "|".join(m[:3] for m in _MONTHS) + r")[a-z]*(?=[\s_.\-\d])", re.IGNORECASE)
_PREK_RE = re.compile(r"pre[\s-]?k", re.IGNORECASE)


def classify_presence_menu(item: dict) -> dict | None:
    """A Presence documents-widget item -> {meal_type, prek, month, year, url, period_label},
    or None when it isn't a monthly menu. Titles are hand-typed ('October Menu
    2026', 'October Pre K Menu 2026 -Breakfast', 'September 2026 PreK Lunch'),
    so month and year are found anywhere in them; an item with no meal word is
    lunch, the way a school's plain 'Menu' is."""
    title = item["title"]
    if item.get("extension") not in _PRESENCE_MENU_EXTS or not re.search(r"menu|lunch|breakfast", title, re.IGNORECASE):
        return None
    month_m = _MONTH_WORD_RE.search(title)
    year_m = re.search(r"\b(20\d{2})\b", title)
    if not month_m or not year_m:
        return None
    month = next(i for i, name in enumerate(_MONTHS, 1) if name.startswith(month_m.group(1).lower()))
    year = int(year_m.group(1))
    prek = bool(_PREK_RE.search(title))
    label = f"{_MONTHS[month - 1].title()} {year}" + (" (Pre-K)" if prek else "")
    return {
        "meal_type": "breakfast" if re.search(r"breakfast", title, re.IGNORECASE) else "lunch",
        "prek": prek,
        "month": month,
        "year": year,
        "url": item["url"],
        "period_label": label,
    }


def pick_presence_menus(items: list[dict], today: date) -> list[dict]:
    """Current-or-future months only, one menu per (month, meal). The plain
    menu wins over its Pre-K twin, which on a single-building school is the
    same lunch with a line or two swapped; Pre-K is kept only where nothing
    else covers that meal (Somerdale's breakfast is Pre-K only), and labelled."""
    best: dict[tuple[int, int, str], dict] = {}
    for item in items:
        c = classify_presence_menu(item)
        if not c or (c["year"], c["month"]) < (today.year, today.month):
            continue
        key = (c["year"], c["month"], c["meal_type"])
        if key not in best or (best[key]["prek"] and not c["prek"]):
            best[key] = c
    return [best[k] for k in sorted(best)]


async def parse_menu_pdf(pdf_url: str, period_label: str, meal_type: str | None = None) -> list[dict]:
    """Returns [{date: datetime, description: str, notes: str|None}, ...].
    Days marked only 'School Closed' with no meal are still included (with
    that as the description) so the calendar reads correctly."""
    if not ANTHROPIC_API_KEY:
        return []

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (schoolz menu sync)"}) as http_client:  # Presence hosts 403 the default UA
        resp = await http_client.get(pdf_url)
        resp.raise_for_status()
        pdf_b64 = base64.b64encode(resp.content).decode("ascii")
    # Some schools post a month's menu as a picture rather than a PDF
    # (Somerdale Park's October JPGs); sniffed from bytes, never the URL.
    image_type = _sniff_image_type(resp.content)
    file_block = (
        {"type": "image", "source": {"type": "base64", "media_type": image_type, "data": pdf_b64}}
        if image_type
        else {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_b64}}
    )

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
                    file_block,
                    {
                        "type": "text",
                        "text": f"This is the {period_label} school menu calendar. Extract every day that has "
                        "an entry (a meal offered, or a note like 'School Closed'), resolving each into a full "
                        "ISO date for that month/year. Go cell by cell through EVERY week row including the "
                        "first and last, which are often partial (the month may start on a Thursday): a day "
                        "number in the top-right corner of a cell with a meal in it is an entry even when "
                        "other cells in the same row hold only a notice or are blank. Ignore sidebar legends "
                        "and notice boxes that carry no day number."
                        + (
                            f" If the file holds more than one meal's calendar (a breakfast page and a lunch "
                            f"page), record only the {meal_type} calendar."
                            if meal_type
                            else ""
                        ),
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
