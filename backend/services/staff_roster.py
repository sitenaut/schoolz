"""Fetches and parses a school's own staff directory (Finalsite
`/contact-us`, confirmed structure: `.fsConstituentItem` cards, paginated
via `?const_page=N`, with a stable `data-constituent-id` per person that
survives re-scans even if name formatting changes slightly)."""

import re
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

import scraper_client
from services import smart_sites


def _text_after_label(el, label: str) -> str | None:
    text = el.get_text(" ", strip=True)
    text = text.replace(label, "", 1).strip()
    return text or None


_NEXT_PAGE_SELECTOR = "a.fsNextPageLink"


def _parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items = []
    for el in soup.select(".fsConstituentItem"):
        constituent_id = el.get("data-constituent-id")
        name_el = el.select_one(".fsFullName")
        name = name_el.get_text(strip=True) if name_el else None
        if not constituent_id or not name:
            continue

        title_el = el.select_one(".fsTitles")
        department_el = el.select_one(".fsDepartments")
        email_el = el.select_one(".fsEmail a[href^='mailto:']")
        phone_el = el.select_one(".fsPhones a[href^='tel:']")

        items.append(
            {
                "constituent_id": constituent_id,
                "full_name": name,
                "title": _text_after_label(title_el, "Titles:") if title_el else None,
                "department": _text_after_label(department_el, "Departments:") if department_el else None,
                "email": email_el["href"].replace("mailto:", "").strip() if email_el else None,
                "phone": phone_el.get_text(strip=True) if phone_el else None,
            }
        )
    return items


_EDNET_HEADERS = {"User-Agent": "Mozilla/5.0 (schoolz directory sync)"}
_EDNET_PATH = "/apps/staff/"


def _parse_ednet_page(html: str) -> list[dict]:
    """Educational Networks / SchoolSitePro `/apps/staff/` (Haddon Heights,
    Barrington): one `.staff-category` per department, each card a name
    (`dt`) and optional title (`dd`). Profile links are `uREC_ID=<id>` and
    open an email *form*, so there is never an address or phone to keep."""
    soup = BeautifulSoup(html, "lxml")
    items = []
    for category in soup.select(".staff-category"):
        header = category.select_one(".staff-header h1")
        department = header.get_text(" ", strip=True) if header else None
        for card in category.select(".staff-categoryStaffMember"):
            link = card.select_one("a[href]")
            name_el = card.select_one("dt")
            if not link or not name_el:
                continue
            ids = parse_qs(urlparse(link["href"]).query).get("uREC_ID")
            name = re.sub(r"\s+", " ", name_el.get_text(" ", strip=True))
            if not ids or not name:
                continue
            title_el = card.select_one("dd")
            title = re.sub(r"\s+", " ", title_el.get_text(" ", strip=True)) if title_el else ""
            items.append(
                {
                    "constituent_id": f"ednet:{ids[0]}",
                    "full_name": name,
                    "title": title or None,
                    "department": department or None,
                    "email": None,
                    "phone": None,
                }
            )
    return items


def _parse_edlio_page(html: str) -> list[dict]:
    """Edlio's newer `/apps/staff/` template (Medford): one `li.staff` per
    person with `a.name` (`uREC_ID=<id>`) and an optional `.user-position`.
    The email link is a form and the phone is just "Ext. 6222", so neither is
    kept."""
    soup = BeautifulSoup(html, "lxml")
    items = {}
    for card in soup.select("li.staff"):
        link = card.select_one("a.name[href]")
        if not link:
            continue
        ids = parse_qs(urlparse(link["href"]).query).get("uREC_ID")
        name = re.sub(r"\s+", " ", link.get_text(" ", strip=True))
        if not ids or not name:
            continue
        title_el = card.select_one(".user-position")
        title = re.sub(r"\s+", " ", title_el.get_text(" ", strip=True)) if title_el else ""
        items[f"edlio:{ids[0]}"] = {
            "constituent_id": f"edlio:{ids[0]}",
            "full_name": name,
            "title": title or None,
            "department": None,
            "email": None,
            "phone": None,
        }
    return list(items.values())


async def _fetch_ednet_roster(base: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_EDNET_HEADERS) as client:
            resp = await client.get(base + _EDNET_PATH)
            resp.raise_for_status()
    except httpx.HTTPError:
        return []
    return _parse_ednet_page(resp.text) or _parse_edlio_page(resp.text)


def _parse_eschoolview_page(html: str) -> list[dict]:
    """eSchoolView/LINQ staff page (Mount Laurel; the home page has no reliable
    platform marker, so the fetcher just follows its "Staff Directory" link and
    lets this return [] on any other markup): `span.scName` ("Last, First")
    beside `span.scTitle`, no stable id, address or phone - the profile link
    opens a contact form. Identity is name + title, so a person listed under
    two titles stays two rows and a repeated card collapses to one."""
    soup = BeautifulSoup(html, "lxml")
    items = {}
    for name_el in soup.select(".scName"):
        raw = re.sub(r"\s+", " ", name_el.get_text(" ", strip=True))
        if not raw:
            continue
        last, sep, first = raw.partition(",")
        name = f"{first.strip()} {last.strip()}" if sep and first.strip() else raw
        card = name_el.find_parent(class_=re.compile(r"col-")) or name_el.parent
        title_el = card.select_one(".scTitle") if card else None
        title = re.sub(r"\s+", " ", title_el.get_text(" ", strip=True)) if title_el else ""
        key = f"eschoolview:{name.lower()}|{title.lower()}"
        items[key] = {
            "constituent_id": key,
            "full_name": name,
            "title": title or None,
            "department": None,
            "email": None,
            "phone": None,
        }
    return list(items.values())


async def _fetch_eschoolview_roster(base: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_EDNET_HEADERS) as client:
            home = await client.get(base)
            home.raise_for_status()
            link = next(
                (a for a in BeautifulSoup(home.text, "lxml").find_all("a", href=True) if re.search(r"staff\s+directory", a.get_text(" ", strip=True), re.I)),
                None,
            )
            if not link:
                return []
            page = await client.get(urljoin(str(home.url), link["href"]))
            page.raise_for_status()
    except httpx.HTTPError:
        return []
    return _parse_eschoolview_page(page.text)


# The rest are Voorhees Township's per-school subsites (Voorhees Middle's
# is the odd one out) and Eastern Regional - same Finalsite constituent
# cards, different page path.
_DIRECTORY_PATHS = (
    "/contact-us",
    "/contact-us/alphabetical-staff-directory",
    "/staff-directory",
    "/staff-directory-websites",
    "/parents-students/staff-directory",
    # Haddon Township Public Schools - confirmed same .fsConstituentItem
    # cards, just a different Finalsite nav path.
    "/our-school/staff-directory",
)


async def fetch_roster(school_website_url: str) -> list[dict]:
    """Paginates by actually clicking the "next page" control in one live
    browser session - confirmed the directory's ?const_page=N query param
    does nothing on its own (client-side/JS pagination, not real
    server-side paging), so a plain per-page fetch just returns page 1
    every time.

    Most schools' directory lives directly at /contact-us, but some (seen on
    the district's high schools) instead put it at
    /contact-us/alphabetical-staff-directory, and other districts elsewhere
    again - try each, in order, and use
    the first one that actually yields results."""
    base = school_website_url.rstrip("/")
    # ParentSquare Smart Sites (Evesham) answers plain HTTP; the Finalsite
    # click-through below would spend up to 100 browser page loads finding nothing.
    smart_home = await smart_sites.fetch_home(base)
    if smart_home:
        return await smart_sites.fetch_roster(base, smart_home)
    ednet = await _fetch_ednet_roster(base)
    if ednet:
        return list({item["constituent_id"]: item for item in ednet}.values())
    eschoolview = await _fetch_eschoolview_roster(base)
    if eschoolview:
        return eschoolview
    for path in _DIRECTORY_PATHS:
        pages_html = await scraper_client.fetch_paginated(base + path, next_page_selector=_NEXT_PAGE_SELECTOR, max_pages=20)
        by_constituent_id: dict[str, dict] = {}
        for html in pages_html:
            for item in _parse_page(html):
                by_constituent_id[item["constituent_id"]] = item
        if by_constituent_id:
            return list(by_constituent_id.values())

    return []


_SCHOOL_NAME_NOISE = {"the", "school", "schools", "elementary", "middle", "high", "junior", "senior", "jr", "sr", "memorial", "township", "public", "center", "primary", "intermediate"}


def _school_tokens(*names: str | None) -> set[str]:
    words: set[str] = set()
    for n in names:
        words |= set(re.findall(r"[a-z]+", (n or "").lower()))
    return words - _SCHOOL_NAME_NOISE


def drop_sibling_school_staff(roster: list[dict], own_names: list[str | None], sibling_names: list[list[str | None]]) -> tuple[list[dict], list[dict]]:
    """Sister schools on one shared site (Medford Lakes) all list the same
    staff, titled "Nokomis Nurse" / "Neeta Principal". A title that names a
    sibling school and not this one belongs to the sibling; returns
    (kept, dropped)."""
    own = _school_tokens(*own_names)
    sibling = set().union(*(_school_tokens(*n) for n in sibling_names)) - own if sibling_names else set()
    if not sibling:
        return roster, []
    kept, dropped = [], []
    for e in roster:
        words = set(re.findall(r"[a-z]+", (e["title"] or "").lower()))
        (dropped if words & sibling and not words & own else kept).append(e)
    return kept, dropped
