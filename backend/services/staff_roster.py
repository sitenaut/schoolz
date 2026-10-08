"""Fetches and parses a school's own staff directory (Finalsite
`/contact-us`, confirmed structure: `.fsConstituentItem` cards, paginated
via `?const_page=N`, with a stable `data-constituent-id` per person that
survives re-scans even if name formatting changes slightly)."""

import asyncio
import csv
import hashlib
import time
import re
from urllib.parse import parse_qs, urljoin, urlparse

import io
import zipfile
import xml.etree.ElementTree as ET

import httpx
import pdfplumber
from bs4 import BeautifulSoup

import scraper_client
from services import smart_sites


def _text_after_label(el, label: str) -> str | None:
    text = el.get_text(" ", strip=True)
    text = text.replace(label, "", 1).strip()
    return text or None


_NEXT_PAGE_SELECTOR = "a.fsNextPageLink"


# Scheduling placeholders a district leaves in its directory (Pennsauken:
# "FILLER STAFF RO-ART", "FILLER STAFF CA-03"), not people.
_PLACEHOLDER_NAME_RE = re.compile(r"filler\s+staff\b", re.I)


def _parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items = []
    for el in soup.select(".fsConstituentItem"):
        constituent_id = el.get("data-constituent-id")
        name_el = el.select_one(".fsFullName")
        name = name_el.get_text(strip=True) if name_el else None
        if not constituent_id or not name or _PLACEHOLDER_NAME_RE.match(name):
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
    # A school's website_url can be its own page on the district host
    # (Runnemede: /apps/pages/index.jsp?uREC_ID=...), so /apps/staff/ hangs off the origin.
    parts = urlparse(base)
    origin = f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else base
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_EDNET_HEADERS) as client:
            resp = await client.get(origin + _EDNET_PATH)
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
        # Gibbsboro: "Staff Member | Position", names typed "Last, First".
        title_col = next((i for i, h in enumerate(header) if h in ("position", "title", "assignment")), None)
        email_col = next((i for i, h in enumerate(header) if h == "email"), None)
        phone_col = next((i for i, h in enumerate(header) if "ext" in h or "room" in h), None)
        for row in rows[1:]:
            cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in row.select("td,th")]
            if len(cells) <= name_col or not cells[name_col]:
                continue
            name = _first_last(cells[name_col])
            if title_col is not None:
                title = cells[title_col] if title_col < len(cells) else ""
            else:
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


def _parse_tablepress_directory(html: str) -> list[dict]:
    """Haddonfield's WordPress directories (`/staff-directory/` on every
    school): one TablePress table, a "Name" / "Email" header, then rows whose
    first cell is either a section header (`<div class="directory-letters">`:
    a letter, or a department like "Kindergarten") or a person - name, a
    `<br>`, and the title in `<i>`. The email column is a Cloudflare-obfuscated
    envelope icon, and some people (Central) have none. A person with no
    title takes the section header as their department."""
    soup = BeautifulSoup(html, "lxml")
    items = {}
    for table in soup.select("table.tablepress"):
        section = None
        for row in table.select("tbody tr"):
            cells = row.select("td")
            if not cells:
                continue
            header = cells[0].select_one(".directory-letters")
            if header:
                label = re.sub(r"\s+", " ", header.get_text(" ", strip=True))
                section = label if len(label) > 1 else None
                continue
            title_el = cells[0].find("i")
            title = re.sub(r"\s+", " ", title_el.get_text(" ", strip=True)) if title_el else ""
            if title_el:
                title_el.extract()
            name = re.sub(r"\s+", " ", cells[0].get_text(" ", strip=True))
            if not name:
                continue
            link = row.select_one("a[href*='email-protection#']")
            email = _decode_cf_email(link["href"]) if link else None
            # source_constituent_id is String(64): 3-letter prefix + bounded slugs.
            key = f"tp:{_slug(name)[:34]}|{_slug(title or section or '')[:22]}"
            items[key] = {
                "constituent_id": key,
                "full_name": name,
                "title": title or None,
                "department": section,
                "email": email.lower() if email else None,
                "phone": None,
            }
    return list(items.values())


_PLAIN_PAGE_PATHS = ("/about-us/staff", "/about-us/ourfaculty/", "/staff-directory/", "/staff-directory-2/")


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
                items = _parse_table_page(resp.text) or _parse_wp_card_page(resp.text) or _parse_tablepress_directory(resp.text)
                if items:
                    return items
    except httpx.HTTPError:
        return []
    return []


_NOT_A_PERSON_RE = re.compile(r"vacant|conference room|^tbd$|^n/?a$|/", re.I)


def _column_map(cells: list[str]) -> dict[str, int]:
    """Which column is which, from a header row's text. Schools head the name
    column anything ("Name", "Teacher", "Staff Members", "School Leadership"),
    and the title column "Title", "Position", "Subject" or "Grade"."""
    cols: dict[str, int] = {}
    for field, words in (
        ("email", ("email",)),
        ("department", ("department",)),
        ("phone", ("ext", "phone")),
        ("title", ("title", "position", "subject", "grade")),
        ("name", ("name", "teacher", "staff", "leadership", "faculty")),
    ):
        for i, c in enumerate(cells):
            if i not in cols.values() and any(w in c.lower() for w in words):
                cols[field] = i
                break
    if "name" not in cols:  # an unclaimed first column is the name
        free = [i for i in range(len(cells)) if i not in cols.values() and cells[i]]
        if free:
            cols["name"] = free[0]
    return cols


def _first_last(name: str) -> str:
    """"Last, First" -> "First Last"; a suffix ("Smith, Jr.") is left alone."""
    last, comma, first = name.partition(",")
    if comma and "," not in first and first.strip() and not re.match(r"^(jr|sr|ii|iii|iv)\b", first.strip(), re.I):
        return f"{first.strip()} {last.strip()}"
    return name


def _people_from_rows(tables, key_prefix: str) -> list[dict]:
    """Rows of a document's tables -> roster entries. A header row - any row
    with an "Email" cell and no address in it - names the columns, and stays in
    force across pages and tables, since the sheets print it once; a new header
    mid-table (Davis re-heads its "Staff Members" section) replaces it. Rows
    that aren't a person (a "Vacant" slot, a conference-room line, a shared
    "Veronica/Joey" desk, a section label) are skipped. Email cells in
    hand-typed sheets carry stray characters ("name@x.org>"), so only the
    address itself is kept. Identity is the email when there is one, else
    name + title, so a re-scan matches the same person."""
    items: dict[str, dict] = {}
    cols: dict[str, int] | None = None
    for table in tables:
        for raw in table:
            cells = [re.sub(r"\s+", " ", c or "").strip() for c in raw]
            if any("email" in c.lower() for c in cells) and not any("@" in c for c in cells):
                cols = _column_map(cells)
                continue
            if not cols or "name" not in cols or "email" not in cols:
                continue
            col = lambda field: cells[cols[field]] if field in cols and cols[field] < len(cells) else ""  # noqa: E731
            name = _first_last(col("name"))
            if not name or _NOT_A_PERSON_RE.search(name):
                continue
            title = col("title")
            email_match = _EMAIL_RE.search(col("email"))
            email = email_match.group(0).lower() if email_match else None
            phone = col("phone")
            key = f"{key_prefix}:{email or _slug(name) + '|' + _slug(title)}"
            items[key] = {
                "constituent_id": key,
                "full_name": name,
                "title": title or None,
                "department": col("department") or None,
                "email": email,
                "phone": phone if _PHONE_CELL_RE.match(phone) else None,
            }
    return list(items.values())


def parse_pdf_directory(data: bytes) -> list[dict]:
    """A staff directory published as a PDF table (Camden's Eastside, Davis and
    Catto sheets); see _people_from_rows for the row rules."""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return _people_from_rows((t for page in pdf.pages for t in page.extract_tables()), "pdf")


_XLSX_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _xlsx_sheets(data: bytes) -> list[list[list[str]]]:
    """Each sheet of an .xlsx as rows of cell text, read with the standard
    library (an xlsx is zipped XML) rather than a spreadsheet dependency for
    one school's file."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            shared = ["".join(t.text or "" for t in si.iter(_XLSX_NS + "t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(_XLSX_NS + "si")]
        sheets = []
        for name in sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)):
            rows = []
            for r in ET.fromstring(z.read(name)).iter(_XLSX_NS + "row"):
                row: list[str] = []
                for c in r.findall(_XLSX_NS + "c"):
                    idx = _col_index(c.get("r") or "")
                    row.extend([""] * (idx - len(row)))
                    v = c.find(_XLSX_NS + "v")
                    inline = c.find(_XLSX_NS + "is")
                    if v is not None:
                        row.append(shared[int(v.text)] if c.get("t") == "s" else (v.text or ""))
                    elif inline is not None:
                        row.append("".join(t.text or "" for t in inline.iter(_XLSX_NS + "t")))
                    else:
                        row.append("")
                rows.append(row)
            sheets.append(rows)
        return sheets


def _col_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref)
    n = 0
    for ch in letters.group(0) if letters else "A":
        n = n * 26 + ord(ch) - 64
    return n - 1


def parse_xlsx_directory(data: bytes) -> list[dict]:
    """A staff roster kept as a spreadsheet (Veterans Memorial's), which stacks
    several sections each under its own header row. Sheets are read
    separately so a header never carries onto an unrelated sheet."""
    out: dict[str, dict] = {}
    for rows in _xlsx_sheets(data):
        for e in _people_from_rows([rows], "xlsx"):
            out[e["constituent_id"]] = e
    return list(out.values())


_SHEET_RE = re.compile(r"https://docs\.google\.com/spreadsheets/d/e/([\w-]+)/pub")


def published_sheet_csv_url(url: str) -> str | None:
    """The CSV export of a Google Sheet that was "published to the web" (the
    `/d/e/<key>/pubhtml` link a school embeds as an iframe), same tab."""
    m = _SHEET_RE.match(url)
    if not m:
        return None
    gid = (parse_qs(urlparse(url).query).get("gid") or ["0"])[0]
    return f"https://docs.google.com/spreadsheets/d/e/{m.group(1)}/pub?gid={gid}&single=true&output=csv"


def parse_csv_directory(text: str) -> list[dict]:
    """A staff list kept as a published Google Sheet (Delran's four schools).
    The sheets split the name over "First Name" / "Last Name" columns and head
    the address "E-Mail", so the header is rewritten to the one-name-column
    shape _people_from_rows reads. Extension columns hold a bare "3024", not a
    number a parent can dial, and are left out."""
    rows = []
    first = last = None
    for raw in csv.reader(io.StringIO(text)):
        cells = [c.strip() for c in raw]
        lowered = [c.lower() for c in cells]
        if "first name" in lowered and "last name" in lowered:
            first, last = lowered.index("first name"), lowered.index("last name")
            cells = ["Email" if c.replace("-", "") == "email" else cells[i] for i, c in enumerate(lowered)]
        if first is not None and max(first, last) < len(cells):
            name = "Name" if cells[first].lower() == "first name" else f"{cells[first]} {cells[last]}".strip()
            cells = [name] + [c for i, c in enumerate(cells) if i not in (first, last)]
        rows.append(cells)
    return _people_from_rows([rows], "sheet")


_SLIDES_RE = re.compile(r"https://docs\.google\.com/presentation/d/([\w-]+)")
_PAGE_MARKER_RE = re.compile(r"^pg \d+$|^teacher email addresses$", re.I)
_PAREN_RE = re.compile(r"\s*\(([^)]*)\)\s*$")


def parse_slides_directory(text: str) -> list[dict]:
    """A staff contact list kept as a Google Slides deck (Cooper's Poynt),
    read from Google's plain-text export: grade/area headings, then each
    person as a name line ("Ms. Baker", "Mr. King (PE/Health)") immediately
    followed by an email line. A line followed by an email is a person; any
    other line is a heading for the people under it (a parenthetical-only
    line like "(PE/Health)" isn't one). Only the honorific + surname is
    published, which is what full_name holds. Hand-typed addresses carry
    typos, so an address that isn't well-formed, or whose domain differs from
    the list's own most common one, is dropped rather than shown - the person
    stays, since a wrong address mails a stranger about a child."""
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not _PAGE_MARKER_RE.match(ln)]
    people: list[tuple[str, str, str | None]] = []
    section = ""
    for i, line in enumerate(lines):
        if _EMAIL_RE.fullmatch(line) or "@" in line:
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if "@" in nxt:
            paren = _PAREN_RE.search(line)
            name = _PAREN_RE.sub("", line).strip()
            title = (f"{section} ({paren.group(1)})" if section else paren.group(1)) if paren else section
            email = _EMAIL_RE.fullmatch(nxt.replace("\u2019", "'"))
            people.append((name, title, nxt if email and "\u2019" not in nxt else None))
        elif not line.startswith("("):
            section = line
    domains = [e.rsplit("@", 1)[1].lower() for _, _, e in people if e]
    modal = max(set(domains), key=domains.count) if domains else None
    items: dict[str, dict] = {}
    for name, title, email in people:
        email = email.lower() if email and email.rsplit("@", 1)[1].lower() == modal else None
        key = f"doc:{email or _slug(name) + '|' + _slug(title)}"
        items[key] = {
            "constituent_id": key,
            "full_name": name,
            "title": title or None,
            "department": None,
            "email": email,
            "phone": None,
        }
    return list(items.values())


async def fetch_directory_document(url: str) -> list[dict]:
    """The school's directory as a document rather than a page. A Google Slides
    deck is read through its public plain-text export and a published Google
    Sheet through its CSV export; anything else is taken
    to be a PDF table (or an .xlsx sheet), fetched through the scraper's /fetch-raw because school
    sites behind a bot wall (Camden's Cloudflare) 403 a plain GET."""
    slides = _SLIDES_RE.match(url)
    if slides:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(f"https://docs.google.com/presentation/d/{slides.group(1)}/export/txt")
            resp.raise_for_status()
        return parse_slides_directory(resp.text)
    sheet_csv = published_sheet_csv_url(url)
    if sheet_csv:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(sheet_csv)
            resp.raise_for_status()
        return parse_csv_directory(resp.content.decode("utf-8-sig"))
    data = await scraper_client.fetch_raw_bytes(url)
    if urlparse(url).path.lower().endswith(".xlsx"):
        return parse_xlsx_directory(data)
    return parse_pdf_directory(data)


# Moorestown: "/for_staff/staff_directory", except Upper Elementary, whose
# own page is "/for_staff/ues_staff_directory".
_PRESENCE_PATHS = (
    "/staff_directory",
    "/School/staff_directory",
    "/for_staff/staff_directory",
    "/for_staff/ues_staff_directory",
)
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


# Berlin Township (WordPress, Beaver Builder "UABB" post grid behind a
# Cloudflare challenge, so every fetch goes through the scraper): one
# /staff-directory/ page lists the whole district - every teacher of both
# schools plus the district office - as cards of name + title, filterable by
# grade/department. Which school someone works at, and their email, are only
# on their own /staff-member/<slug>/ page ("Location(s): Dwight D. Eisenhower |
# John F. Kennedy"). `locations` rides on each item so the scan can keep the
# right people per school (drop_sibling_school_staff).
_WP_GRID_PATH = "/staff-directory/"
_WP_GRID_TTL = 6 * 3600
_wp_grid_cache: dict[str, tuple[float, list[dict]]] = {}
_WP_PROFILE_LABELS = ("Grade(s)/Department:", "Title(s):", "Location(s):")


def _parse_wp_staff_grid(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    categories = {}
    for li in soup.select("li[data-filter]"):
        match = re.search(r"cat-(\d+)", li.get("data-filter", ""))
        if match:
            categories[match.group(1)] = li.get_text(" ", strip=True)
    items: dict[str, dict] = {}
    for card in soup.select(".uabb-post-wrapper"):
        link = card.select_one("a[href*='/staff-member/']")
        heading = card.select_one(".uabb-post-heading")
        if not link or not heading:
            continue
        name = re.sub(r"\s+", " ", heading.get_text(" ", strip=True))
        slug = urlparse(link["href"]).path.rstrip("/").rsplit("/", 1)[-1]
        if not name or not slug:
            continue
        parts = [re.sub(r"\s+", " ", t) for t in card.get_text("\n", strip=True).split("\n")]
        title = next((t for t in parts if t and t != name and not t.lower().startswith("read bio")), "")
        depts = [categories[c] for c in re.findall(r"uabb-masonary-cat-(\d+)", " ".join(card.get("class", []))) if c in categories]
        items[slug] = {
            "constituent_id": f"wpstaff:{slug}"[:64],
            "full_name": name,
            "title": title or None,
            "department": ", ".join(depts) or None,
            "email": None,
            "phone": None,
            "profile_url": link["href"],
            "locations": [],
        }
    return list(items.values())


_PHONE_TEXT_RE = re.compile(r"\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?:\s*(?:ext\.?|x)\s*\d+)?", re.IGNORECASE)


def _parse_wp_staff_profile(html: str, name: str) -> dict:
    """{"locations": [...], "email": ..., "phone": ...} from one person's
    page. The fields are a run of labels and values after the person's name;
    the email and an optional phone follow the last location. Over plain HTTP
    Cloudflare serves the email obfuscated ("[email protected]" with the real
    one in data-cfemail); a rendered page has it as text."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    hidden = soup.select_one("[data-cfemail]")
    email = _decode_cf_email("#" + hidden["data-cfemail"]) if hidden else None
    parts = [re.sub(r"\s+", " ", t) for t in soup.get_text("\n", strip=True).split("\n") if t.strip()]
    starts = [i for i, t in enumerate(parts) if t == name]
    parts = parts[starts[-1] :] if starts else parts
    locations: list[str] = []
    phone = None
    if "Location(s):" in parts:
        after = parts[parts.index("Location(s):") + 1 :]
        for i, value in enumerate(after):
            found = _EMAIL_RE.search(value)
            if found or "[email" in value or _PHONE_TEXT_RE.search(value):
                email = email or (found.group(0) if found else None)
                number = next((m.group(0) for v in after[i : i + 3] if (m := _PHONE_TEXT_RE.search(v))), None)
                phone = number
                break
            if value in _WP_PROFILE_LABELS or value.lower().startswith(("staff directory", "staff bio")):
                break
            locations.append(value)
    return {"locations": locations, "email": email.lower() if email else None, "phone": phone}


async def _get_html(client: httpx.AsyncClient, url: str) -> str | None:
    """Plain HTTP first; the scraper only when the site's bot wall answers
    instead (Cloudflare lets some networks through and challenges others)."""
    try:
        resp = await client.get(url)
        if resp.status_code == 200:
            return resp.text
        if resp.status_code not in (403, 429, 503):
            return None
    except httpx.HTTPError:
        pass
    try:
        return (await scraper_client.fetch_html(url, wait_for_selector="a", timeout_ms=30_000))["html"]
    except Exception:  # noqa: BLE001 - an unreachable page is simply not this layout
        return None


async def _fetch_wp_staff_grid_roster(base: str) -> list[dict]:
    cached = _wp_grid_cache.get(base)
    if cached and time.monotonic() - cached[0] < _WP_GRID_TTL:
        return [dict(item) for item in cached[1]]
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_EDNET_HEADERS) as client:
        listing = await _get_html(client, base + _WP_GRID_PATH)
        people = _parse_wp_staff_grid(listing) if listing and "uabb-post-wrapper" in listing else []
        if not people:
            return []
        gate = asyncio.Semaphore(5)

        async def fill(person: dict) -> None:
            async with gate:
                page = await _get_html(client, person["profile_url"])
            if page:  # else keep the person, just without a school or email
                person.update(_parse_wp_staff_profile(page, person["full_name"]))

        await asyncio.gather(*(fill(p) for p in people))
    for person in people:
        person.pop("profile_url", None)
    _wp_grid_cache[base] = (time.monotonic(), people)
    return [dict(item) for item in people]


_DIRECTORY_LINK_RE = re.compile(r"staff[\s_-]*directory|faculty[\s_-]*(?:&|and)?[\s_-]*staff|staff[\s_-]*list", re.IGNORECASE)
_MAX_DISCOVERED = 3


def find_directory_links(home_html: str, base: str) -> list[str]:
    """Staff-directory pages a school links from its own navigation, best
    first. The fixed paths above cover the common Finalsite layouts, but a
    directory can sit anywhere (Lindenwold: /our-school/high-school-staff-directory;
    Gibbsboro: /our-district/staff-directory). Same site only - a link to the
    district's directory from a school subsite would list every school's staff."""
    host = urlparse(base).hostname or ""
    scored: dict[str, int] = {}
    for a in BeautifulSoup(home_html, "lxml").find_all("a", href=True):
        url = urljoin(base + "/", a["href"].strip()).split("#")[0]
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or parsed.hostname != host:
            continue
        text = a.get_text(" ", strip=True)
        in_text, in_path = bool(_DIRECTORY_LINK_RE.search(text)), bool(_DIRECTORY_LINK_RE.search(parsed.path))
        if not (in_text or in_path) or re.search(r"websites?", text + parsed.path, re.IGNORECASE):
            continue
        scored[url] = max(scored.get(url, 0), 2 * in_text + in_path)
    return sorted(scored, key=lambda u: -scored[u])[:_MAX_DISCOVERED]


async def _fetch_discovered_roster(base: str) -> list[dict]:
    """Follows the school's own "Staff Directory" link when no known path
    worked: constituent cards are clicked through like any Finalsite
    directory, anything else is read as a plain table page."""
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_EDNET_HEADERS) as client:
            home = await client.get(base)
            if home.status_code != 200:
                return []
            for url in find_directory_links(home.text, base):
                page = await client.get(url)
                if page.status_code != 200:
                    continue
                if "fsConstituentItem" in page.text:
                    pages_html = await scraper_client.fetch_paginated(url, next_page_selector=_NEXT_PAGE_SELECTOR, max_pages=20, block_assets=True)
                    people = {item["constituent_id"]: item for html in pages_html for item in _parse_page(html)}
                    if people:
                        return list(people.values())
                    continue
                items = _parse_table_page(page.text) or _parse_wp_card_page(page.text) or _parse_tablepress_directory(page.text)
                if items:
                    return items
    except httpx.HTTPError:
        return []
    return []


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
    # Before the Finalsite loop, which would spend its page loads on a
    # WordPress site; returns at once when /staff-directory/ isn't this layout.
    grid = await _fetch_wp_staff_grid_roster(base)
    if grid:
        return grid
    for path in _DIRECTORY_PATHS:
        pages_html = await scraper_client.fetch_paginated(
            base + path, next_page_selector=_NEXT_PAGE_SELECTOR, max_pages=20, block_assets=True
        )
        by_constituent_id: dict[str, dict] = {}

        for html in pages_html:
            for item in _parse_page(html):
                by_constituent_id[item["constituent_id"]] = item
        if by_constituent_id:
            return list(by_constituent_id.values())

    return await _fetch_discovered_roster(base)


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
        # A directory that says where each person works (Berlin Township's
        # "Location(s)") decides it outright; someone at both schools, or at
        # neither (district office), stays on each.
        source = " ".join(e["locations"]) if e.get("locations") else (e["title"] or "")
        words = set(re.findall(r"[a-z]+", source.lower()))
        (dropped if words & sibling and not words & own else kept).append(e)
    return kept, dropped
