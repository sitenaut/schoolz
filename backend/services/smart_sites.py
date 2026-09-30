"""ParentSquare Smart Sites (formerly SharpSchool) - the school-website
platform Evesham Township runs on. Everything schoolz needs is reachable with
plain HTTP; there is no bot wall, so no Playwright and no residential proxy.

Confirmed structure (all ten Evesham sites):

- Every page carries assets from `smartsites.parentsquare.com`, which is how a
  site is recognised (`is_smart_sites`) - school_info and staff_roster sniff a
  school's homepage with one cheap GET before choosing between this parser and
  the Finalsite one.
- The footer has address and phone as `school-footer-seven-*` links whose
  `aria-label` reads "Address 60 Caldwell Avenue, Marlton, NJ 08053" and
  "Phone 856-988-0619".
- The homepage nav links a "Staff Directory" page. When it uses the directory
  widget, the page ships an empty shell and a script call
  `getOnDemandDirectoryContent('<item id>', ...)`, which the browser answers by
  POSTing `/includes/ajax/load_stack_staff_directory.php` (JSON with the cards'
  HTML). That POST works for anyone. Emails are base64 in each card's
  `data-staff-email` (the site hides them from scrapers, not from us).
- Some schools instead hand-type the directory into the page body ("Principal -
  Ryan Mahlman", no emails; parsed by `handtyped_directory`) or embed a document
  viewer, which is reported as empty rather than guessed at."""

import base64
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from services import handtyped_directory, role_pages

_HEADERS = {"User-Agent": "Mozilla/5.0 (schoolz directory sync)"}
_MARKER = "smartsites.parentsquare.com"
_DIRECTORY_AJAX = "/includes/ajax/load_stack_staff_directory.php"
_ITEM_ID_RE = re.compile(r"getOnDemandDirectoryContent\(\s*'(\d+)'")
_DIRECTORY_LINK_RE = re.compile(r"^\s*(?:staff|teacher|faculty)?\s*directory\s*$", re.I)
_MAX_DIRECTORY_PAGES = 3
_MIN_HANDTYPED = 5


def is_smart_sites(html: str) -> bool:
    return _MARKER in html


async def fetch_home(base_url: str) -> str | None:
    """The homepage HTML if this is a Smart Sites site, else None (including
    when the fetch fails - the caller then falls back to its own parser)."""
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=_HEADERS) as client:
            resp = await client.get(base_url.rstrip("/") + "/")
            resp.raise_for_status()
    except httpx.HTTPError:
        return None
    return resp.text if is_smart_sites(resp.text) else None


def parse_footer(html: str) -> dict:
    """{"address": str|None, "main_phone": str|None} from the standard footer."""
    soup = BeautifulSoup(html, "lxml")
    address = phone = None
    link = soup.select_one(".school-footer-seven-address-info a")
    if link:
        label = (link.get("aria-label") or link.get_text(" ", strip=True)).strip()
        address = re.sub(r"^Address:?\s*", "", label, flags=re.I).strip() or None
    tel = soup.select_one("footer a[href^='tel:']")
    if tel:
        phone = tel.get_text(strip=True) or re.sub(r"^Phone:?\s*", "", tel.get("aria-label") or "", flags=re.I).strip() or None
    return {"address": address, "main_phone": phone}


def find_directory_links(home_html: str, base_url: str) -> list[str]:
    """Nav links titled "Staff Directory" / "Teacher Directory" / "Directory"
    (the page slug varies: /staff-directory, /435223_2), plus the common slug
    as a last resort."""
    soup = BeautifulSoup(home_html, "lxml")
    urls: list[str] = []
    for a in soup.find_all("a", href=True):
        if _DIRECTORY_LINK_RE.match(a.get_text(" ", strip=True)):
            url = urljoin(base_url.rstrip("/") + "/", a["href"])
            if url not in urls:
                urls.append(url)
    fallback = base_url.rstrip("/") + "/staff-directory"
    if fallback not in urls:
        urls.append(fallback)
    return urls[:_MAX_DIRECTORY_PAGES]


def directory_item_ids(page_html: str) -> list[str]:
    return list(dict.fromkeys(_ITEM_ID_RE.findall(page_html)))


def _decode_email(value: str | None) -> str | None:
    if not value:
        return None
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8").strip()
    except ValueError:
        return None
    return decoded if "@" in decoded else None


def _constituent_id(name: str, email: str | None) -> str:
    key = (email or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")).lower()
    return f"ss:{key}"[:64]


def parse_directory(fragment: str) -> list[dict]:
    """Staff cards from the widget's HTML, in the shape staff_roster returns."""
    soup = BeautifulSoup(fragment, "lxml")
    out = []
    for card in soup.select(".staff-item"):
        name_el = card.select_one(".stack-directory-name")
        name = " ".join(name_el.get_text(" ", strip=True).split()) if name_el else ""
        if not name:
            continue
        # Four title slots per card, mostly blank; the school's own name fills
        # one of them, so it is dropped rather than shown as a job title.
        slots = [t.get_text(" ", strip=True) for t in card.select(".stack-directory-title")]
        titles = [t for t in slots if t]
        btn = card.select_one("[data-staff-email]")
        email = _decode_email(btn.get("data-staff-email") if btn else None)
        out.append(
            {
                "constituent_id": _constituent_id(name, email),
                "full_name": name,
                "title": titles[0] if titles else None,
                "department": None,
                "email": email,
                "phone": None,
            }
        )
    return out


async def fetch_roster(base_url: str, home_html: str) -> list[dict]:
    base = base_url.rstrip("/")
    by_id: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_HEADERS) as client:
        for page_url in find_directory_links(home_html, base):
            resp = await client.get(page_url)
            if resp.status_code != 200:
                continue
            item_ids = directory_item_ids(resp.text)
            if not item_ids:
                typed = handtyped_directory.parse(resp.text)
                if len(typed) >= _MIN_HANDTYPED:  # fewer is a stray phrase, not a directory
                    for p in typed:
                        cid = _constituent_id(p["full_name"], None)
                        by_id[cid] = {"constituent_id": cid, **p, "department": None, "email": None, "phone": None}
            for item_id in item_ids:
                r = await client.post(
                    base + _DIRECTORY_AJAX,
                    data={"item_id": item_id, "search_term": "", "use_mongo": "false", "revision_time": ""},
                    headers={"X-Requested-With": "XMLHttpRequest", "Referer": page_url},
                )
                r.raise_for_status()
                payload = r.json()
                if payload.get("status") != "success":
                    continue
                for entry in parse_directory(payload["data"]["html"]):
                    by_id[entry["constituent_id"]] = entry
            if by_id:
                break
        if not by_id:
            # No directory anywhere (Jaggard, Van Zant): one page per role in the nav.
            for entry in await role_pages.fetch_role_staff(client, home_html, base):
                by_id[entry["constituent_id"]] = entry
    return list(by_id.values())
