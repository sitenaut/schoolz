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
import io
import logging
import re
import time
from datetime import date, datetime
from html import unescape
from urllib.parse import quote, unquote, urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
import pdfplumber
from anthropic import AsyncAnthropic
from bs4 import BeautifulSoup

import observability
import scraper_client
from scheduler.errors import record_parse_issue
from services import haiku, page_extractions
from services.content_extractor import ANTHROPIC_API_KEY, MODEL, _parse_date
from services.tool_output import object_list, recover_spilled_input

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
# St. Joan of Arc (Marlton): "October-2026-Lunch-Forms.pdf", an order form that
# lists the month's standing choices and weekday specials rather than a calendar.
_MONTH_YEAR_FORMS_RE = re.compile(r"(" + "|".join(_MONTHS) + r")-(\d{4})-lunch-forms?\b", re.IGNORECASE)


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


# Burlington City: "October 2026 Elementary Breakfast -Lunch- Aftercare.pdf",
# "October 2026 MS-HS Breakfast -Lunch-Aftercare Menu.pdf", "... Pre-K ...":
# month, year and the band in words, one PDF holding breakfast, lunch and
# the aftercare snack. Every name says "Breakfast", so _NOT_A_MENU_RE threw
# them all out; only September's MS-HS file got through, on its typo
# "Breakfasat", as an unbanded menu for every school type, so the
# elementaries were served the MS-HS menu. One band can cover two types.
_BAND_WORDS_MENU_RE = re.compile(
    r"^(" + "|".join(_MONTHS) + r")\s+(\d{4})\s*-?\s*(Elementary|Middle|High|MS-HS|MS|HS|Pre-?K)\b.*\bLunch\b", re.IGNORECASE
)
_BAND_WORDS = {"ELEMENTARY": ("elementary",), "MIDDLE": ("middle",), "HIGH": ("high",), "MS": ("middle",), "HS": ("high",), "MSHS": ("middle", "high"), "PREK": ("other",)}


def _classify_band_words_pdf_link(url: str) -> list[dict]:
    match = _BAND_WORDS_MENU_RE.search(unquote(url.rsplit("/", 1)[-1].split("?", 1)[0]))
    if not match:
        return []
    month, year, band = match.groups()
    return [
        {
            "school_type": school_type,
            "meal_type": "lunch",
            "period_label": f"{month.title()} {year}",
            "pdf_url": url,
            "_sort": (int(year), _MONTHS.index(month.lower())),
        }
        for school_type in _BAND_WORDS[re.sub(r"[^A-Za-z]", "", band).upper()]
    ]


# Riverside: "oct_hsms_lunch_menu.pdf", "oct_elementary_breakfast_menu.pdf",
# "oct_prek_lunch_menu.pdf" - a month abbreviation, a band and the meal, no
# year (inferred as the nearest, like Magnolia's).
_MONTH_BAND_MENU_RE = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*_(elementary|hsms|mshs|hs|ms|prek|pre-k)_(breakfast|lunch)_menu\b",
    re.IGNORECASE,
)


def _classify_month_band_pdf_link(url: str, today: date | None = None) -> list[dict]:
    match = _MONTH_BAND_MENU_RE.search(unquote(url.rsplit("/", 1)[-1].split("?", 1)[0]))
    if not match:
        return []
    month_abbr, band, meal = match.groups()
    month_idx = next(i for i, m in enumerate(_MONTHS) if m.startswith(month_abbr.lower()))
    year_num = _infer_year(month_idx, today or datetime.now(ZoneInfo("America/New_York")).date())
    band_key = re.sub(r"[^A-Za-z]", "", band).upper().replace("HSMS", "MSHS")
    return [
        {
            "school_type": school_type,
            "meal_type": meal.lower(),
            "period_label": f"{_MONTHS[month_idx].title()} {year_num}",
            "pdf_url": url,
            "_sort": (year_num, month_idx),
        }
        for school_type in _BAND_WORDS[band_key]
    ]


def _classify_unbanded_pdf_link(url: str, school_type: str) -> dict | None:
    filename = url.rsplit("/", 1)[-1]
    if _NOT_A_MENU_RE.search(filename):
        return None
    match = _MONTH_YEAR_RE.search(filename) or _MONTH_YEAR_FORMS_RE.search(filename)
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
# month closest to today. Berlin Township's are "October-Lunch-Menu.pdf" (words
# separated, no year); its "October-Pre-K-Lunch-Menu.pdf" twin doesn't match
# because only a separator, not another word, may sit before the meal.
_ABBREV_MENU_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*?[-_ ]?(\d{4}|\d{2})?[-_ ]?(Breakfast|Lunch)[-_ ]?Menu(?!_?SPA)",
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


# Gloucester City: one PDF per school per meal per month (Chance Light, a program with no school row, is skipped), named with a school
# code - "Oct 2026 MS Lunch Menu.pdf", and one with the code first and a typo'd
# year, "CS Sept 27 Lunch Menu.pdf". A year that isn't four digits is inferred
# (the nearest one to today), since "27" is the 2026-27 school year, not 2027.
_CODED_MENU_RE = re.compile(
    r"(?:(?P<m1>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[ _-]*(?P<y1>\d{4}|\d{2})?[ _-]+(?P<c1>CS|ECC|MS|HS)"
    r"|(?P<c2>CS|ECC|MS|HS)[ _-]+(?P<m2>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[ _-]*(?P<y2>\d{4}|\d{2})?)"
    r"[ _-]+(?P<meal>Breakfast|Lunch)[ _-]*Menu",
    re.IGNORECASE,
)
_MENU_CODE_TO_SCHOOL_TYPE = {"CS": "elementary", "MS": "middle", "HS": "high", "ECC": "other"}


def _classify_coded_pdf_link(url: str, today: date | None = None) -> dict | None:
    filename = unquote(url.rsplit("/", 1)[-1])
    match = _CODED_MENU_RE.search(filename)
    if not match:
        return None
    g = match.groupdict()
    month_abbr, year, code = (g["m1"], g["y1"], g["c1"]) if g["m1"] else (g["m2"], g["y2"], g["c2"])
    month_idx = next(i for i, m in enumerate(_MONTHS) if m.startswith(month_abbr.lower()))
    year_num = int(year) if year and len(year) == 4 else _infer_year(month_idx, today or datetime.now(ZoneInfo("America/New_York")).date())
    return {
        "school_type": _MENU_CODE_TO_SCHOOL_TYPE[code.upper()],
        "meal_type": g["meal"].lower(),
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


# Washington Township (Gloucester): last month's menus are resource-manager
# PDFs, but the current month's are fixed-name PNGs (/uploaded/Food_Service/
# ES_L.png, overwritten monthly) with no filename to classify - only the link
# text says what they are: "Elementary Lunch Menu -- October 2026".
_IMAGE_MENU_LINK_RE = re.compile(
    r'<a\b[^>]*href="([^"]+\.(?:png|jpe?g|webp)(?:\?[^"]*)?)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL
)
_IMAGE_MENU_TEXT_RE = re.compile(
    r"(preschool|pre-?k|elementary|middle(?:\s+school)?|high(?:\s+school)?)\s+(breakfast|lunch)\s+menu\W+("
    + "|".join(_MONTHS)
    + r")\W+(\d{4})",
    re.IGNORECASE,
)
_IMAGE_BAND = {"pre": "other", "ele": "elementary", "mid": "middle", "hig": "high"}


def _classify_image_menu_links(page_url: str, html: str) -> list[dict]:
    out = []
    for href, inner in _IMAGE_MENU_LINK_RE.findall(html):
        text = re.sub(r"<[^>]+>", " ", inner).replace("&nbsp;", " ").replace("\xa0", " ")
        m = _IMAGE_MENU_TEXT_RE.search(re.sub(r"\s+", " ", text))
        if not m:
            continue
        band, meal, month, year = m.groups()
        out.append(
            {
                "school_type": _IMAGE_BAND[band.lower()[:3]],
                "meal_type": meal.lower(),
                "period_label": f"{month.title()} {year}",
                "pdf_url": urljoin(page_url, href),
                "_sort": _month_sort(month, year),
            }
        )
    return out


# Clayton (Apptegy): each month's menu is a PDF in an <iframe src="https://aptg.co/<code>">
# on a per-level menus page, and the district's food-service page only links
# to those pages. The short link redirects to a differently-named file whose
# name says little ("HS-MS-BK.pdf" has no month), so the PDF's own heading
# ("HS/MS Lunch Menu October 2026") is what classifies it.
_EMBED_IFRAME_RE = re.compile(r'<iframe[^>]+src=\\*"(https://aptg\.co/[\w-]+)', re.IGNORECASE)
_MENU_SUBPAGE_RE = re.compile(r'(/o/[\w-]+/page/[\w-]*menus?[\w-]*)', re.IGNORECASE)
_PDF_HEADING_RE = re.compile(
    r"(HS/MS|HS|MS|Pre-?K|Elementary|Herma[\w .'-]*?)\s+(breakfast|lunch)\s+menu\s+(" + "|".join(_MONTHS) + r")\s+(\d{4})", re.IGNORECASE
)


def _classify_menu_heading(text: str, pdf_url: str) -> list[dict]:
    m = _PDF_HEADING_RE.search(re.sub(r"\s+", " ", text or ""))
    if not m:
        return []
    band, meal, month, year = m.groups()
    b = band.upper().replace("-", "")
    types = ["high", "middle"] if b == "HS/MS" else ["high"] if b == "HS" else ["middle"] if b == "MS" else ["other"] if b.startswith("PREK") else ["elementary"]
    return [
        {"school_type": t, "meal_type": meal.lower(), "period_label": f"{month.title()} {year}", "pdf_url": pdf_url, "_sort": _month_sort(month, year)}
        for t in types
    ]


async def _discover_embedded_menus(page_url: str, html: str) -> list[dict]:
    pages = [page_url]
    unescaped = html.replace('\\"', '"')
    for path in dict.fromkeys(_MENU_SUBPAGE_RE.findall(unescaped)):
        url = urljoin(page_url, path)
        if url not in pages:
            pages.append(url)
    codes: dict[str, None] = {}
    for url in pages[:6]:
        page_html = html if url == page_url else (await scraper_client.fetch_html(url, wait_for_selector="a", block_assets=True))["html"]
        for src in _EMBED_IFRAME_RE.findall(page_html.replace('\\"', '"')):
            codes[src] = None
    found: list[dict] = []
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (schoolz menu sync)"}) as client:
        for src in list(codes)[:12]:
            try:
                resp = await client.get(src)
                resp.raise_for_status()
                with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                    first_page = pdf.pages[0].extract_text() or ""
            except Exception:  # noqa: BLE001 - one bad embed shouldn't hide the others
                continue
            found += _classify_menu_heading(first_page, src)
    return found


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


# Gibbsboro: the lunchroom page embeds each month's menu as a Google Drive
# viewer (`<iframe src="drive.google.com/file/d/<id>/preview">`), so there is
# no filename in the page at all. The real one is the Drive page's own
# <title> ("October 2026 monthly menu.pdf"); the bytes download anonymously
# from /uc?export=download.
_DRIVE_FILE_RE = re.compile(r"drive\.google\.com/file/d/([\w-]{20,})/", re.IGNORECASE)
_DRIVE_TITLE_RE = re.compile(r"<title>(.*?)\s+-\s+Google Drive</title>", re.IGNORECASE | re.DOTALL)
_MAX_DRIVE_LINKS = 10


async def _resolve_drive_links(html: str) -> dict[str, str]:
    """{download URL: Drive file name} for every Drive file the page embeds
    or links. Non-menus (a budget PDF) resolve fine and are filtered out by
    the classifiers, which look for a month and year in the name."""
    ids = list(dict.fromkeys(_DRIVE_FILE_RE.findall(html)))[:_MAX_DRIVE_LINKS]
    resolved: dict[str, str] = {}
    if not ids:
        return resolved
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0, headers={"User-Agent": "Mozilla/5.0 (schoolz menu sync)"}) as client:
        for file_id in ids:
            try:
                resp = await client.get(f"https://drive.google.com/file/d/{file_id}/view")
            except httpx.HTTPError:
                continue
            title = _DRIVE_TITLE_RE.search(resp.text)
            if title:
                resolved[f"https://drive.google.com/uc?export=download&id={file_id}"] = title.group(1).strip()
    return resolved


# Clementon: a real <table>, a month per row, a Breakfast cell and a Lunch
# cell, each "PreK / K-8" Drive links. The Drive titles are all over the place
# ("CLE BRK 9.26", "Sept. k- 8th Lunch Menu"), so month and meal come from the
# cell's position and the year from the "2026-2027" heading above the table.
_SCHOOL_YEAR_RE = re.compile(r"^\s*(20\d{2})\s*-\s*(20\d{2})\s*$")
_K8_LINK_RE = re.compile(r"drive\.google\.com/file/d/([\w-]{20,})/", re.IGNORECASE)


def _classify_menu_table(html: str, school_type: str) -> list[dict]:
    """Menus laid out as a month/breakfast/lunch table of Drive links. Only
    the K-8 file is kept: the PreK one is a near-copy."""
    soup = BeautifulSoup(html, "html.parser")
    heading = next((h for h in soup.find_all(["h3", "h4"]) if _SCHOOL_YEAR_RE.match(h.get_text())), None)
    if heading is None:
        return []
    start_year = int(_SCHOOL_YEAR_RE.match(heading.get_text()).group(1))
    found = []
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        month = cells[0].get_text(strip=True).lower() if cells else ""
        if len(cells) < 3 or month not in _MONTHS:
            continue
        month_idx = _MONTHS.index(month)
        year = start_year if month_idx >= 6 else start_year + 1  # school year runs Jul-Jun
        for meal, cell in (("breakfast", cells[1]), ("lunch", cells[2])):
            link = next((a for a in cell.find_all("a", href=_K8_LINK_RE) if re.fullmatch(r"K\s*-\s*8", a.get_text(strip=True), re.IGNORECASE)), None)
            if link:
                file_id = _K8_LINK_RE.search(link["href"]).group(1)
                found.append(
                    {
                        "school_type": school_type,
                        "meal_type": meal,
                        "period_label": f"{month.title()} {year}",
                        "pdf_url": f"https://drive.google.com/uc?export=download&id={file_id}",
                        "_sort": (year, month_idx),
                    }
                )
    return found


# Aramark MySchoolPlate (Willingboro's elementary and early-childhood schools):
# the vendor's menu API is empty for them, but each location page lists the
# monthly menu PDFs as links ("Elementary Lunch", "Stuart and Garfield
# Breakfast") that are client-rendered and carry no month in the URL. The month
# is printed on the PDF itself, and the same asset URL is replaced in place
# each month, so it rides along as a fragment to make each month a new key.
_MSP_PDF_LINK_RE = re.compile(r'href="([^"]+\.pdf)"[^<]*?>([^<]*)<', re.IGNORECASE)


def _classify_myschoolplate_link(text: str) -> tuple[str, str] | None:
    """(school_type, meal_type) from a location-page link's text, or None for
    one the vendor API already covers (middle/high) or a one-off ("Grab & Go")."""
    lowered = text.lower()
    meal = "breakfast" if "breakfast" in lowered else "lunch" if "lunch" in lowered else None
    if not meal or "grab" in lowered:
        return None
    if "elementary" in lowered:
        return "elementary", meal
    if re.search(r"stuart|garfield|early childhood|ecdc", lowered):
        return "other", meal
    return None


async def _myschoolplate_pdf_period(pdf_url: str) -> str | None:
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (schoolz menu sync)"}) as http_client:
        resp = await http_client.get(pdf_url)
        resp.raise_for_status()
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        text = (pdf.pages[0].extract_text() or "") if pdf.pages else ""
    match = _MONTH_YEAR_RE.search(text)
    return f"{match.group(1).title()} {match.group(2)}" if match else None


async def _discover_myschoolplate_menus(menu_page_url: str) -> list[dict]:
    from services import myschoolplate

    tenant = urlparse(menu_page_url).netloc.split(".")[0]
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (schoolz menu sync)"}) as http_client:
        cfg = await myschoolplate.fetch_config(http_client, tenant)
        locations = await myschoolplate.fetch_locations(http_client, cfg) if cfg else []
    found: dict[tuple[str, str], str] = {}
    for loc in locations:
        page = await scraper_client.fetch_html(myschoolplate.location_page_url(tenant, loc["key"]), wait_for_selector="main", block_assets=True)
        for href, text in _MSP_PDF_LINK_RE.findall(page["html"]):
            key = _classify_myschoolplate_link(unescape(text).strip())
            if key and key not in found:
                found[key] = quote(unescape(href), safe=":/")
    entries = []
    for (school_type, meal_type), url in found.items():
        period = await _myschoolplate_pdf_period(url)
        if period:
            month, year = period.split()
            entries.append({"school_type": school_type, "meal_type": meal_type, "period_label": period, "pdf_url": f"{url}#{month}-{year}"})
    return entries


async def discover_current_menus(menu_page_url: str, school_types: list[str] | None = None) -> list[dict]:
    """Returns one entry per (school_type, meal_type) found on the page,
    e.g. {"school_type": "elementary", "meal_type": "lunch",
    "period_label": "September 2026", "pdf_url": "..."}.

    `school_types` is the district's school types, for a district whose menu
    PDFs carry no grade band (Eastern: one high school; Evesham: one
    all-grades PDF): a bare month+year filename is taken as every listed
    type's lunch menu, latest month winning."""
    if urlparse(menu_page_url).netloc.endswith(".myschoolplate.com"):
        return await _discover_myschoolplate_menus(menu_page_url)
    result = await scraper_client.fetch_html(menu_page_url, wait_for_selector="a", block_assets=True)

    # Edlio/ednet file links are site-relative and carry a cache-buster
    # ("/ourpages/auto/.../File.pdf?rnd=1773934928084") once a file is replaced.
    urls = {urljoin(menu_page_url, u) for u in re.findall(r'href="([^"]+\.pdf(?:\?[^"]*)?)"', result["html"], re.IGNORECASE)}
    urls |= await _resolve_resource_manager_links(menu_page_url, result["html"])
    # Drive files have no filename in their URL, so each is classified under a
    # stand-in URL ending in its Drive title, then swapped back to the real one.
    table = _classify_menu_table(result["html"], (school_types or ["elementary"])[0])
    alias = {} if table else {f"https://drive.google.com/{quote(title)}": url for url, title in (await _resolve_drive_links(result["html"])).items()}
    urls |= set(alias)

    def restore(entries: list[dict]) -> list[dict]:
        return [{**c, "pdf_url": alias.get(c["pdf_url"], c["pdf_url"])} for c in entries]

    by_key: dict[tuple, dict] = {}
    classified_links = []
    for u in urls:
        one = _classify_pdf_link(u) or _classify_coded_pdf_link(u)
        # A band no school in the district has (Burlington City's Pre-K) would only cost a parse.
        classified_links += [one] if one else [
            c for c in _classify_band_words_pdf_link(u) + _classify_month_band_pdf_link(u) if not school_types or c["school_type"] in school_types
        ]
    for _url, classified in [(c["pdf_url"], c) for c in classified_links] + [(c["pdf_url"], c) for c in _classify_image_menu_links(menu_page_url, result["html"])]:
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
        for c in table:
            by_meal.setdefault(c["meal_type"], []).append(c)
        if by_meal:
            return restore(fan_out([c for entries in by_meal.values() for c in current_or_latest(entries)]))

        unbanded = [c for c in (_classify_unbanded_pdf_link(u, school_types[0]) for u in urls) if c]
        if unbanded:
            return restore(fan_out(current_or_latest(unbanded)))
    if not by_key:
        for c in await _discover_embedded_menus(menu_page_url, result["html"]):
            key = (c["school_type"], c["meal_type"])
            if key not in by_key or c["_sort"] > by_key[key]["_sort"]:
                by_key[key] = c
    return restore([{k: v for k, v in c.items() if k != "_sort"} for c in by_key.values()])


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


# Burlington Township (Princeton Food Management): a Google Site with one page
# per school, each embedding that month's and last month's menus as Drive files
# titled by hand ("October 2026 young school lunch.jpg"). The title carries the
# month and meal, so the Drive title becomes a Presence-style document item and
# the same picker applies; the school's own page keeps each school's lunch its own.
async def list_google_sites_menu_files(page_url: str) -> list[dict]:
    """[{title, extension, url}] for the Drive files embedded in a Google Sites
    page, in page order. [] when the page embeds none."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=30.0, headers={"User-Agent": "Mozilla/5.0 (schoolz menu sync)"}) as http_client:
        resp = await http_client.get(page_url)
        resp.raise_for_status()
    items = []
    for url, name in (await _resolve_drive_links(resp.text)).items():
        stem, dot, ext = name.rpartition(".")
        items.append({"title": stem if dot else name, "extension": ext.lower() if dot else "", "url": url})
    return items


# A price legend the model sometimes files under a real date ("Lunch Meal Prices: $3.25 ...").
_PRICE_BOX_RE = re.compile(r"\bmeal prices\b", re.IGNORECASE)


async def _read_menu_file(pdf_url: str, content: bytes, prompt: str) -> list[dict] | None:
    """The model's day entries for one menu file, or None when it answered
    without the tool call (nothing worth keeping)."""
    pdf_b64 = base64.b64encode(content).decode("ascii")
    # Some schools post a month's menu as a picture rather than a PDF
    # (Somerdale Park's October JPGs); sniffed from bytes, never the URL.
    image_type = _sniff_image_type(content)
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
        **haiku.CALL_KWARGS,
        tools=[_MENU_TOOL],
        tool_choice={"type": "tool", "name": "record_menu"},
        messages=[{"role": "user", "content": [file_block, {"type": "text", "text": prompt}]}],
    )
    observability.record_llm_call("lunch_menu", MODEL, response, time.perf_counter() - _llm_started)
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_use:
        return None
    # `days` as a JSON string is a real Haiku answer; read raw, it failed
    # (and rolled back) the whole district's scan.
    days, dropped = object_list(recover_spilled_input(tool_use.input, "days").get("days"))
    if dropped:
        record_parse_issue("lunch_menu.scan", "unexpected_format", url=pdf_url, sample=str(dropped)[:200])
    return days


async def parse_menu_pdf(pdf_url: str, period_label: str, meal_type: str | None = None) -> list[dict]:
    """Returns [{date: datetime, description: str, notes: str|None}, ...].
    Days marked only 'School Closed' with no meal are still included (with
    that as the description) so the calendar reads correctly."""
    if not ANTHROPIC_API_KEY:
        return []

    # Presence hosts 403 the default UA; a host that 403s Fly's addresses
    # (Chesterbrook's Cloudflare) is read through the scrapers.
    _, content = await scraper_client.get_bytes(pdf_url, headers={"User-Agent": "Mozilla/5.0 (schoolz menu sync)"}, timeout_s=20.0)
    prompt = (
        f"This is the {period_label} school menu calendar. Extract every day that has "
        "an entry (a meal offered, or a note like 'School Closed'), resolving each into a full "
        "ISO date for that month/year. Go cell by cell through EVERY week row including the "
        "first and last, which are often partial (the month may start on a Thursday): a day "
        "number in the top-right corner of a cell with a meal in it is an entry even when "
        "other cells in the same row hold only a notice or are blank. Ignore sidebar legends "
        "and notice boxes that carry no day number. If the file is not a calendar at all but a "
        "standing daily menu or order form (the same choices every day plus a special for each "
        "weekday), record one entry for every Monday to Friday of that month: the description is "
        "that weekday's special followed by the daily choices, summarised briefly."
        + (
            f" If the file holds more than one meal's calendar (a breakfast page and a lunch "
            f"page), record only the {meal_type} calendar."
            if meal_type
            else ""
        )
    )
    # Stored by a hash of the prompt and the file's bytes (page_extractions):
    # a parse that stored no menu (nothing read, or no day left after the
    # scan's own filtering) left nothing to say the file was read, so the
    # same file was paid for again on every scan that still listed it.
    key = page_extractions.file_key("lunch_menu", prompt, _MENU_TOOL, content)
    days = await page_extractions.stored(key)
    if days is None:
        days = await _read_menu_file(pdf_url, content, prompt)
        if days is None:
            return []
        await page_extractions.store(key, days)
    items = []
    for day in days:
        parsed_date = _parse_date(day.get("date"))
        description = day.get("description")
        if not parsed_date or not description or _PRICE_BOX_RE.search(description):
            continue
        items.append({"date": parsed_date, "description": description[:500], "notes": day.get("notes")})
    return items
