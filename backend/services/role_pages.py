"""Staff from a school site that has no directory at all, only one page per
role in its nav ("Principal", "School Nurse", "School Counselor" - confirmed
on Jaggard and Van Zant, ParentSquare Smart Sites). Each page names its
person one of three ways, and only a name that is *placed* like one counts:
the line right before an email, the sign-off line after "Warmly,", or the
line right before their own job title. A page naming no one (a nurse page
that is only health forms) yields nothing rather than a guess.
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import scraper_client
from services.handtyped_directory import _clean, _name_like

_ROLE_LINK_RE = re.compile(r"\b(principal|nurse|counselor|counsellor)\b", re.I)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_GENERIC_EMAIL_RE = re.compile(r"^(info|office|contact|webmaster|noreply)@", re.I)
_TITLE_LINE_RE = re.compile(r"^(assistant\s+)?principal$|^school\s+(nurse|counselor)$|^nurse$|\bschool counselor$", re.I)
_MAX_ROLE_PAGES = 8
_HEADING_WORDS = {"message", "welcome", "dear", "families", "family", "letter", "greetings"}


def _is_name(line: str) -> bool:
    return _name_like(line) and not any(re.sub(r"['’]s?$", "", t.lower()) in _HEADING_WORDS for t in line.split())


def find_role_links(home_html: str, base_url: str) -> list[tuple[str, str]]:
    """[(title, url)] for nav links whose text names a school role. The
    "Principal's Message" page is the principal's page."""
    soup = BeautifulSoup(home_html, "lxml")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(" ", strip=True).split())
        if not text or len(text) > 40 or not _ROLE_LINK_RE.search(text):
            continue
        url = urljoin(base_url.rstrip("/") + "/", a["href"])
        if url in seen or url.rstrip("/") == base_url.rstrip("/"):
            continue
        seen.add(url)
        title = re.sub(r"['’]?s\s+message$", "", text, flags=re.I).strip()
        out.append((title, url))
    return out[:_MAX_ROLE_PAGES]


def _content_root(soup):
    """The page body: the Smart Sites wrapper, else <main> (WordPress), else
    everything. Without this a footer's webmaster/HIB-specialist address
    becomes a candidate for the page's person."""
    return soup.select_one("#page-content-wrapper") or soup.find("main") or soup


def _content_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    root = _content_root(soup)
    for t in root(["script", "style", "nav"]):
        t.decompose()
    lines = [_clean(l) for l in root.get_text("\n").splitlines()]
    lines = [l for l in lines if l]
    # The school-name + "Address:" block starts the footer.
    for i, l in enumerate(lines):
        if re.match(r"^address:?$", l, re.I):
            return lines[: max(i - 1, 0)]
    return lines


def _email_near(lines: list[str], i: int) -> str | None:
    for l in lines[i + 1 : i + 4]:
        m = _EMAIL_RE.search(l)
        if m and not _GENERIC_EMAIL_RE.match(m.group(0)):
            return m.group(0).lower()
    return None


_INLINE_RE = re.compile(
    r"\b((?:school\s+)?(?:nurse|counselor|principal))\s+((?:(?!(?:health|office|phone|email|school|nurse)\b)[A-Z][\w.'\u2019-]*\s+){1,3}(?!(?:health|office|phone|email|school|nurse)\b)[A-Z][\w'\u2019-]+)\s+(?:(?:health\s+office\s+)?phone:?\s+)?\(?\d{3}\)?[\s.-]",
    re.I,
)


_INLINE_AFTER_RE = re.compile(
    r"((?:(?!(?i:health|office|phone|email|school|nurse)\b)[A-Z][\w.'\u2019-]*\s+){1,2}(?!(?i:health|office|phone|email|school|nurse)\b)[A-Z][\w'\u2019-]+)"
    r"\s+((?i:(?:school\s+)?(?:nurse|counselor)))\s+(?i:(?:health\s+office\s+)?phone:?\s+)?\(?\d{3}\)?[\s.-]",
)


def _inline_person(lines: list[str], page_emails: list[str], title: str) -> dict | None:
    """"School Nurse Jane Doe 856-555-0100, extension 4 - jdoe@..." in the
    page's running text (Camden's WordPress sites; each piece is its own
    element, so the lines are joined first). The name is placed by its role label
    and phone number; the address must contain the person's surname, so a
    footer's bullying-specialist address can't be taken for hers."""
    for text in (" ".join(lines),):
        m = _INLINE_RE.search(text)
        name, role = (m.group(2), m.group(1)) if m else (None, None)
        if not m and (m := _INLINE_AFTER_RE.search(text)):
            name, role = m.group(1), m.group(2)
        if not name:
            continue
        name = name.strip()
        surname = re.sub(r"[^a-z]", "", name.split()[-1].lower())
        email = next((e.lower() for e in page_emails if surname and surname in e.split("@")[0].lower()), None)
        return {"full_name": name, "title": role.title(), "email": email}
    return None


_CREDENTIAL = r"(?:NJ-)?(?:RN|BSN|MSN|CSN)\b"
_CREDENTIALED_RE = re.compile(
    rf"^(?:Contact\s+)?(?:(?:Mrs?|Ms|Dr)\.?\s+)?((?!{_CREDENTIAL})[A-Z][\w.'-]*(?:\s+(?!{_CREDENTIAL})[A-Z][\w.'-]*){{1,2}}),?\s+{_CREDENTIAL}(?:[,\s]+{_CREDENTIAL})*$"
)


def _credentialed_nurse(lines: list[str], page_emails: list[str]) -> dict | None:
    """A line that is a name followed by nursing credentials ("Mrs. Pat Doe,
    RN, BSN, CSN", "Contact Pat Doe, BSN, RN" - Cinnaminson's nurse pages)
    names the nurse: nothing else on a page is written that way. The address
    must contain her surname."""
    for line in lines:
        m = _CREDENTIALED_RE.match(line)
        if not m:
            continue
        name = m.group(1).strip()
        surname = re.sub(r"[^a-z]", "", name.split()[-1].lower())
        email = next((e.lower() for e in page_emails if surname and surname in e.split("@")[0].lower()), None)
        return {"full_name": name, "title": "School Nurse", "email": email}
    return None


def parse_inline_page(html: str, title: str) -> dict | None:
    lines = _content_lines(html)
    soup = BeautifulSoup(html, "lxml")
    emails = [a["href"][7:].split("?")[0].strip().lower() for a in _content_root(soup).select("a[href^='mailto:']")]
    emails += [e.lower() for e in _EMAIL_RE.findall(" ".join(lines))]
    # Credentials first: on a page that has such a line, the looser inline rule
    # can read "Jane Roe / Example Middle School Nurse / 555-..." as a
    # person called "Roe Example Middle".
    return _credentialed_nurse(lines, emails) or _inline_person(lines, emails, title)


def parse_page(html: str, title: str) -> dict | None:
    lines = _content_lines(html)
    page_emails = [e for e in _EMAIL_RE.findall(" ".join(lines)) if not _GENERIC_EMAIL_RE.match(e)]
    # mailto links carry the address without it appearing as text
    soup = BeautifulSoup(html, "lxml")
    for a in _content_root(soup).select("a[href^='mailto:']"):
        addr = a["href"][7:].split("?")[0].strip().lower()
        if "@" in addr and not _GENERIC_EMAIL_RE.match(addr):
            page_emails.append(addr)

    signed = adjacent = None
    for i, l in enumerate(lines):
        if not _is_name(l):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        prev = lines[i - 1] if i else ""
        if _email_near(lines, i) or _TITLE_LINE_RE.search(nxt):
            adjacent = adjacent or l
        if prev.endswith(",") and len(prev) < 30:
            signed = l  # last sign-off wins
    name = adjacent or signed
    if not name:
        return _inline_person(lines, page_emails, title)
    email = None
    for i, l in enumerate(lines):
        if l == name:
            email = _email_near(lines, i)
            # The job title printed under the name ("School Nurse") beats the
            # nav label the link was found by ("Nurse's Corner").
            if i + 1 < len(lines) and _TITLE_LINE_RE.search(lines[i + 1]):
                title = lines[i + 1]
            break
    email = email or (page_emails[0] if len(set(page_emails)) == 1 else None)
    return {"full_name": name, "title": title, "email": email}


async def fetch_role_staff(client, home_html: str, base_url: str) -> list[dict]:
    """Roster entries (staff_roster's shape) from a site's role pages."""
    out = []
    for title, url in find_role_links(home_html, base_url):
        resp = await client.get(url)
        if resp.status_code != 200:
            continue
        person = parse_page(resp.text, title)
        if not person:
            continue
        key = person["email"] or re.sub(r"[^a-z0-9]+", "-", person["full_name"].lower()).strip("-")
        out.append({"constituent_id": f"ss:{key}"[:64], **person, "department": None, "phone": None})
    return out


async def fetch_role_staff_scraped(base_url: str) -> list[dict]:
    """Nurse pages for a site a plain GET can't reach (Camden's Cloudflare
    wall), fetched through the scraper. Only the inline "School Nurse <name>
    <phone>" shape counts: on these WordPress pages the generic name-placement
    rules took a page heading ("Nurse's Corner") for a person, and a principal
    page's bio for a contact."""
    home = await scraper_client.fetch_html(base_url.rstrip("/") + "/", wait_for_selector="a", block_assets=True)
    out = []
    for title, url in find_role_links(home["html"], base_url):
        if not re.search(r"nurse|health", title, re.I):
            continue
        page = await scraper_client.fetch_html(url, block_assets=True)
        person = parse_inline_page(page["html"], title)
        if not person:
            continue
        key = person["email"] or re.sub(r"[^a-z0-9]+", "-", person["full_name"].lower()).strip("-")
        # The nav often links one nurse page twice ("School Nurse", "School Nurse Home").
        if not any(e["constituent_id"] == f"rp:{key}"[:64] for e in out):
            out.append({"constituent_id": f"rp:{key}"[:64], **person, "department": None, "phone": None})
    return out
