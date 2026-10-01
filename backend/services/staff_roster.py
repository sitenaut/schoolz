"""Fetches and parses a school's own staff directory (Finalsite
`/contact-us`, confirmed structure: `.fsConstituentItem` cards, paginated
via `?const_page=N`, with a stable `data-constituent-id` per person that
survives re-scans even if name formatting changes slightly)."""

import hashlib
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
        header = category.select_one(".staff-header h1") or category.select_one("caption h1")
        department = header.get_text(" ", strip=True) if header else None
        for card in category.select(".staff-categoryStaffMember"):
            link = card.select_one("a[href]")
            # Stratford's school sites render the same list as a table: name
            # and position in `td[data-label]` cells rather than dt/dd.
            name_el = card.select_one("dt") or card.select_one("td[data-label^='Name'] a")
            if not link or not name_el:
                continue
            ids = parse_qs(urlparse(link["href"]).query).get("uREC_ID")
            name = re.sub(r"\s+", " ", name_el.get_text(" ", strip=True))
            if not ids or not name:
                continue
            title_el = card.select_one("dd") or card.select_one("td[data-label^='Position']")
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


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


_PHONE_CELL_RE = re.compile(r"^\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}$")
_EMAIL_RE = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")


def _parse_table_page(html: str) -> list[dict]:
    """A hand-edited page of plain tables (Magnolia's /about-us/staff, pasted
    from Word): a header row naming a "Staff Member" / "Teacher/Staff Member"
    column, then one row per person - first column the grade or position,
    optional "Email" column typed as text (no mailto link) and a "Room/EXT"
    column that is a room number except where someone typed a full phone.
    Identity is name + title; a person listed twice collapses to one row."""
    soup = BeautifulSoup(html, "lxml")
    items = {}
    for table in soup.select("table"):
        rows = table.select("tr")
        if not rows:
            continue
        header = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)).lower() for c in rows[0].select("td,th")]
        name_col = next((i for i, h in enumerate(header) if "staff member" in h), None)
        if name_col is None:
            continue
        email_col = next((i for i, h in enumerate(header) if h == "email"), None)
        phone_col = next((i for i, h in enumerate(header) if "ext" in h or "room" in h), None)
        for row in rows[1:]:
            cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in row.select("td,th")]
            if len(cells) <= name_col or not cells[name_col]:
                continue
            name = cells[name_col]
            title = cells[0] if name_col > 0 else ""
            email_match = _EMAIL_RE.search(cells[email_col]) if email_col is not None and email_col < len(cells) else None
            phone = cells[phone_col] if phone_col is not None and phone_col < len(cells) else ""
            key = f"table:{_slug(name)}|{_slug(title)}"
            items[key] = {
                "constituent_id": key,
                "full_name": name,
                "title": title or None,
                "department": None,
                "email": email_match.group(0).lower() if email_match else None,
                "phone": phone if _PHONE_CELL_RE.match(phone) else None,
            }
    return list(items.values())


def _decode_cf_email(href: str) -> str | None:
    """Cloudflare's email obfuscation: `/cdn-cgi/l/email-protection#<hex>`,
    the first hex byte is an XOR key for every byte after it."""
    _, _, hexed = href.partition("#")
    try:
        raw = bytes.fromhex(hexed)
    except ValueError:
        return None
    if len(raw) < 2:
        return None
    decoded = bytes(b ^ raw[0] for b in raw[1:]).decode("utf-8", "ignore")
    return decoded if "@" in decoded else None


def _parse_wp_card_page(html: str) -> list[dict]:
    """WordPress X-theme faculty cards (Laurel Springs /about-us/ourfaculty/):
    each `.x-card` has a front face (last name with honorific as the primary
    text, grade or position as the subheadline) and a back face with
    "Extension NNN" and, for most people, an email button that Cloudflare
    obfuscates. Staff with no email button just have no email."""
    soup = BeautifulSoup(html, "lxml")
    items = {}
    for card in soup.select(".x-card"):
        front = card.select_one(".is-front") or card
        name_el = front.select_one(".x-text-content-text-primary")
        if not name_el:
            continue
        name = re.sub(r"\s+", " ", name_el.get_text(" ", strip=True))
        sub_el = front.select_one(".x-text-content-text-subheadline")
        title = re.sub(r"\s+", " ", sub_el.get_text(" ", strip=True)) if sub_el else ""
        link = card.select_one("a[href*='email-protection#']")
        email = _decode_cf_email(link["href"]) if link else None
        if not name or not (title or email):
            continue
        key = f"wpcard:{_slug(name)}|{_slug(title)}"
        items[key] = {
            "constituent_id": key,
            "full_name": name,
            "title": title or None,
            "department": None,
            "email": email.lower() if email else None,
            "phone": None,
        }
    return list(items.values())


_PLAIN_PAGE_PATHS = ("/about-us/staff", "/about-us/ourfaculty/")


async def _fetch_plain_page_roster(base: str) -> list[dict]:
    """Hand-built school sites that serve their directory as plain HTML at a
    fixed path - tried before the Finalsite click-through, which would spend
    ~100 browser loads on a site with no constituent cards."""
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_EDNET_HEADERS) as client:
            for path in _PLAIN_PAGE_PATHS:
                resp = await client.get(base + path)
                if resp.status_code != 200:
                    continue
                items = _parse_table_page(resp.text) or _parse_wp_card_page(resp.text)
                if items:
                    return items
    except httpx.HTTPError:
        return []
    return []


_PRESENCE_PATHS = ("/staff_directory", "/School/staff_directory")
_PRESENCE_WS = "/Common/controls/StaffDirectory/ws/StaffDirectoryWS.asmx/"
_PRESENCE_PORTLET_RE = re.compile(r'staffDirectoryComponent[^>]*data-portlet-instance-id="(\d+)"')


def _parse_presence_table_page(html: str) -> list[dict]:
    """SchoolMessenger Presence (ex-SharpSchool) staff directory rendered as
    one table (Sterling High): a one-cell colspan row names the department,
    then one row per person - [salutation, first, last, title, email], the
    email Cloudflare-obfuscated. Blank spacer rows are skipped. Title is the
    person's own ("Teacher"), the department is the header they sit under."""
    soup = BeautifulSoup(html, "lxml")
    items = {}
    for table in soup.select("table"):
        department = None
        for row in table.select("tr"):
            cells = row.select("td")
            texts = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in cells]
            if len(cells) == 1 or (cells and cells[0].get("colspan")):
                department = texts[0] or department
                continue
            if len(cells) < 5 or not texts[1] or not texts[2]:
                continue
            name = f"{texts[1]} {texts[2]}"
            title = texts[3]
            link = cells[4].select_one("a[href*='email-protection#']")
            email = _decode_cf_email(link["href"]) if link else None
            # constituent_id is varchar(64); a long title/department overflowed it
            digest = hashlib.sha256(f"{_slug(name)}|{_slug(title)}|{_slug(department or '')}".encode()).hexdigest()[:24]
            key = f"presence:{digest}"
            items[key] = {
                "constituent_id": key,
                "full_name": name,
                "title": title or None,
                "department": department,
                "email": email.lower() if email else None,
                "phone": None,
            }
    return list(items.values())


def _parse_presence_search(results: list[dict], department: str | None) -> list[dict]:
    """One StaffDirectoryWS `Search` response. `email` is the literal string
    "private" when the district hides addresses (Somerdale) - stored as no
    email, never as that word."""
    out = []
    for r in results:
        name = f"{(r.get('firstName') or '').strip()} {(r.get('lastName') or '').strip()}".strip()
        if not name:
            continue
        email = (r.get("email") or "").strip()
        out.append(
            {
                "constituent_id": f"presence:{r.get('userID') or _slug(name)}",
                "full_name": name,
                "title": (r.get("jobTitle") or "").strip() or None,
                "department": department,
                "email": email.lower() if "@" in email else None,
                "phone": (r.get("phone") or "").strip() or None,
            }
        )
    return out


async def _fetch_presence_roster(base: str) -> list[dict]:
    """Presence sites answer plain HTTP. Some render the directory server-side
    as a table; others mount a React component that reads the same JSON web
    service the page calls (`Settings` lists the groups, `Search` returns one
    group's people), keyed by the component's portlet-instance id. Sterling
    has both: `/staff_directory` is a 17-person district component, the full
    ~120 is the table at `/School/staff_directory`, so the biggest wins."""
    best: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_EDNET_HEADERS) as client:
            for path in _PRESENCE_PATHS:
                resp = await client.get(base + path)
                if resp.status_code != 200:
                    continue
                portlet = _PRESENCE_PORTLET_RE.search(resp.text)
                if not portlet:
                    items = _parse_presence_table_page(resp.text)
                    if len(items) > len(best):
                        best = items
                    continue
                instance_id = portlet.group(1)
                headers = {"Content-Type": "application/json; charset=utf-8"}
                settings = await client.post(base + _PRESENCE_WS + "Settings", json={"portletInstanceId": instance_id}, headers=headers)
                settings.raise_for_status()
                by_id: dict[str, dict] = {}
                for group in settings.json()["d"]["groups"]:
                    search = await client.post(
                        base + _PRESENCE_WS + "Search",
                        json={
                            "firstRecord": 0,
                            "lastRecord": 999,
                            "groupIds": [group["groupID"]],
                            "portletInstanceId": instance_id,
                            "searchTerm": "",
                            "sortOrder": "LastName,FirstName ASC",
                            "searchByJobTitle": True,
                        },
                        headers=headers,
                    )
                    search.raise_for_status()
                    for item in _parse_presence_search(search.json()["d"]["results"], group["name"]):
                        by_id.setdefault(item["constituent_id"], item)
                if len(by_id) > len(best):
                    best = list(by_id.values())
    except (httpx.HTTPError, KeyError, ValueError):
        return best
    return best


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
    plain = await _fetch_plain_page_roster(base)
    if plain:
        return plain
    presence = await _fetch_presence_roster(base)
    if presence:
        return presence
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
