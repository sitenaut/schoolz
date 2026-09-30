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


def _content_lines(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    root = soup.select_one("#page-content-wrapper") or soup
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


def parse_page(html: str, title: str) -> dict | None:
    lines = _content_lines(html)
    page_emails = [e for e in _EMAIL_RE.findall(" ".join(lines)) if not _GENERIC_EMAIL_RE.match(e)]
    # mailto links carry the address without it appearing as text
    soup = BeautifulSoup(html, "lxml")
    for a in soup.select("#page-content-wrapper a[href^='mailto:']"):
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
        return None
    email = None
    for i, l in enumerate(lines):
        if l == name:
            email = _email_near(lines, i)
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
