"""Key contacts (principal, nurse, counselor, office) from a school's
hand-typed "Contact Us" page - the fallback when its Finalsite staff
directory carries no titles. Confirmed on Voorhees Township, where the
directory is a list of teachers' websites and the six schools' contact
pages use four different layouts ("Principal:" headings, "Name, Title"
lines, "Title: Name" lines, and a table read column-wise). One model call
reads any of them; every person it returns must have an email and name
that appear verbatim on the page, so nothing is invented.
"""

import logging
import os
import re
import time
from urllib.parse import urljoin, urlparse

from anthropic import AsyncAnthropic
from bs4 import BeautifulSoup

import observability
import scraper_client

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
_MAX_CHARS = 12_000

_TOOL = {
    "name": "record_contacts",
    "description": "Record every staff member listed on this school contact page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "people": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Full name exactly as written."},
                        "title": {"type": "string", "description": "Their role as written, e.g. 'Principal', 'School Nurse', 'Secretary', 'Guidance'."},
                        "email": {"type": "string"},
                        "phone": {"type": "string", "description": "Phone with extension if given, else empty."},
                    },
                    "required": ["name", "title", "email"],
                },
            }
        },
        "required": ["people"],
    },
}

_SYSTEM = (
    "You read a school's 'Contact Us' page and list its staff. Copy names, titles and emails exactly as they appear. "
    "A title may be a heading above several people, a label before the name, or a table column header. "
    "Skip anyone without an email. Do not include the school itself or generic office addresses."
)


def page_text(html: str) -> str:
    """#fsPageContent's text, with each table row on one line so a column
    layout (titles in one row, names in the next) keeps its alignment."""
    soup = BeautifulSoup(html, "lxml")
    root = soup.select_one("#fsPageContent") or soup
    for table in root.select("table"):
        rows = [" | ".join(c.get_text(" ", strip=True) for c in tr.select("th, td")) for tr in table.select("tr")]
        table.replace_with("\n".join(rows) + "\n")
    return "\n".join(line.strip() for line in root.get_text("\n").split("\n") if line.strip())


def find_contact_page(home_html: str, home_url: str) -> str | None:
    host = urlparse(home_url).netloc
    soup = BeautifulSoup(home_html, "lxml")
    for a in soup.select("a[href]"):
        if re.fullmatch(r"\s*contact(\s+us)?\s*", a.get_text(" ", strip=True), re.I):
            url = urljoin(home_url, a["href"])
            if urlparse(url).netloc == host:
                return url
    return None


def verified(people: list[dict], text: str) -> list[dict]:
    haystack = text.lower()
    out, seen = [], set()
    for p in people:
        email = (p.get("email") or "").strip().strip(".").lower()
        name = " ".join((p.get("name") or "").split())
        title = " ".join((p.get("title") or "").split()).rstrip(":")
        if not email or email in seen or email not in haystack or not name or name.lower() not in haystack:
            continue
        seen.add(email)
        out.append({
            "constituent_id": f"contact-page:{email}",
            "full_name": name,
            "title": title or None,
            "department": None,
            "email": email,
            "phone": (p.get("phone") or "").strip() or None,
        })
    return out


async def fetch_contacts(school_website_url: str) -> list[dict]:
    """Roster-shaped dicts (see staff_roster.fetch_roster), or [] when there's
    no contact page or no API key."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return []
    home_url = school_website_url.rstrip("/") + "/"
    home = await scraper_client.fetch_html(home_url, wait_for_selector="a")
    url = find_contact_page(home["html"], home_url)
    if not url:
        return []
    page = await scraper_client.fetch_html(url, wait_for_selector="#fsPageContent")
    text = page_text(page["html"])[:_MAX_CHARS]

    client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    started = time.perf_counter()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=2000,
        temperature=0,
        system=_SYSTEM,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "record_contacts"},
        messages=[{"role": "user", "content": text}],
    )
    observability.record_llm_call("contact_page_extract", MODEL, response, time.perf_counter() - started)
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    people = (tool_use.input.get("people") if tool_use else None) or []
    return verified([p for p in people if isinstance(p, dict)], text)
