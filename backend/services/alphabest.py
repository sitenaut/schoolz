"""AlphaBEST before/after-school care (the SACC provider for Gloucester City).

Each district has a server-rendered WordPress page, `alphabest.org/<slug>/`:
hours, 2026-27 monthly rates, the host school, registration link and an area
manager contact. Plain httpx works, no scraper. Like the rest of SACC this is a
one-off (`scripts/fill_alphabest_sacc.py` prints a seed `sacc` block), not a
recurring job: the page changes about once a year.

The page is per district, not per school; a district with several host schools
lists them under "Location", so the caller decides which school gets the block.
"""

import html
import re

import httpx
from bs4 import BeautifulSoup

_PHONE_RE = re.compile(r"^\D*(\d{3})\D*(\d{3})\D*(\d{4})\D*$")


def _lines(p) -> list[str]:
    """A `<p>` of `<strong>Heading</strong><br>line<br>line`, as its lines."""
    text = p.get_text("\n")
    return [html.unescape(" ".join(l.split())) for l in text.split("\n") if l.strip()]


def format_phone(raw: str) -> str | None:
    m = _PHONE_RE.match(raw or "")
    return f"({m.group(1)}) {m.group(2)}-{m.group(3)}" if m else None


def parse_location_page(page_html: str, url: str) -> dict:
    """SaccProgram-shaped fields from one AlphaBEST location page."""
    soup = BeautifulSoup(page_html, "html.parser")
    sections: dict[str, list[str]] = {}
    for p in soup.select(".callouts-section p"):
        strong = p.find("strong")
        if not strong:
            continue
        lines = _lines(p)
        heading = lines[0].strip(" *").lower()
        sections[heading] = lines[1:]

    hours = sections.get("hours", [])
    am = hours[0].replace("a.m.", "AM").replace("p.m.", "PM") if len(hours) > 0 else None
    pm = hours[1].replace("a.m.", "AM").replace("p.m.", "PM") if len(hours) > 1 else None
    # "7:00 a.m. to Start of School" -> "7:00 AM - start of school"
    am = _hours_range(am)
    pm = _hours_range(pm)

    notes = ["Run by AlphaBEST, not the district."]
    rates = [
        f"{name}: " + "; ".join(lines)
        for name, lines in sections.items()
        if name in {"before school", "after school", "before and after school", "other options", "annual registration fee"}
    ]
    if rates:
        notes.append("Rates (" + _rate_year(soup) + "): " + " | ".join(rates) + ".")
    if sections.get("location"):
        notes.append("Hosted at " + ", ".join(sections["location"]) + ".")
    reg = next((a["href"] for a in soup.find_all("a", href=True) if "kangarootime.com" in a["href"]), None)
    if reg:
        notes.append(f"Register: {reg}")

    phone_el = soup.select_one(".manager-number a")
    return {
        "am_hours": am,
        "pm_hours": pm,
        "site_phone": format_phone(phone_el.get_text()) if phone_el else None,
        "closures_notes": " ".join(notes),
        "handbook_url": url,
    }


def _rate_year(soup: BeautifulSoup) -> str:
    h = soup.select_one(".callouts-section h2")
    m = re.search(r"\d{4}\s*/\s*\d{4}", h.get_text()) if h else None
    return m.group(0).replace(" ", "") if m else "current"


def _hours_range(line: str | None) -> str | None:
    if not line:
        return None
    m = re.match(r"^(.+?)\s+to\s+(.+)$", line)
    if not m:
        return line
    a, b = m.group(1).strip(), m.group(2).strip()
    # "Start of School" / "Dismissal" read better lowercase mid-sentence
    return f"{a} - {b.lower()}" if b.lower().startswith("start") else f"{a} - {b}"


async def fetch_location(url: str) -> dict:
    async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers={"User-Agent": "Mozilla/5.0"}) as client:
        r = await client.get(url)
        r.raise_for_status()
    return parse_location_page(r.text, url)
