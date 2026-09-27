"""Apptegy (Thrillshare) - the CMS behind Collingswood, Oaklyn, and
Woodlynne's own sites, a genuinely different platform from the Finalsite
family the rest of this app was built against. Both endpoints below are
plain public JSON, no scraper: confirmed real by watching the browser's own
network calls (the "Calendar" and "Staff" pages fire these on load/search).

Each Apptegy site is one numeric "org" per building *and* one for the
district root - e.g. Collingswood's own org ids: district=4848, High=8801,
Middle=8800, Preschool=8799 (covers both its CECC and Parkview buildings -
see models.py:School.apptegy_org_id), Mark Newbie=8795, Sharp=8796,
Tatem=8797, Zane=8798. Oaklyn=4847, Woodlynne=12858 (single-building
districts, one org each). There's no discovery endpoint for these - they're
read off the page's own network requests once, by hand, same as Finalsite's
calendar `feed_id`.
"""

from datetime import date, datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

import scraper_client

_BASE = "https://thrillshare-cmsv2.services.thrillshare.com/api/v4"
_PAGE_SIZE = 20


async def fetch_events(org_id: str, start: date, end: date, timeout: float = 30.0) -> list[dict]:
    """Returns a list of {external_uid, title, description, start_date,
    end_date, is_all_day} dicts - same shape as
    services/district_calendar.py:fetch_district_calendar, so a calendar
    feed entry can point at either platform interchangeably."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(
            f"{_BASE}/o/{org_id}/cms/events",
            params={"start_date": start.isoformat(), "end_date": end.isoformat(), "paginate": "false", "locale": "en"},
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        payload = resp.json()

    out = []
    for event in payload.get("events") or []:
        start_at = event.get("start_at")
        if not start_at:
            continue
        try:
            start = datetime.fromisoformat(start_at)
        except ValueError:
            continue
        end_at = event.get("end_at")
        end = None
        if end_at:
            try:
                end = datetime.fromisoformat(end_at)
            except ValueError:
                end = None
        out.append(
            {
                "external_uid": str(event.get("id")),
                "title": (event.get("title") or "").strip() or "(untitled)",
                "description": (event.get("description") or "").strip() or None,
                "start_date": start,
                "end_date": end,
                "is_all_day": bool(event.get("all_day")),
            }
        )
    return out


async def fetch_staff(org_id: str, timeout: float = 30.0) -> list[dict]:
    """Returns a list of {constituent_id, full_name, title, department,
    email, phone} dicts - same shape as
    services/staff_roster.py:fetch_roster's return value. Paginates fully
    (20/page) by following meta.links.next; an org with a genuinely empty
    directory (confirmed real: every one of Collingswood's 8 orgs) just
    returns []."""
    out: list[dict] = []
    url = f"{_BASE}/o/{org_id}/cms/directories"
    params: dict | None = {"locale": "en"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        while url:
            resp = await client.get(url, params=params, headers={"Accept": "application/json"})
            resp.raise_for_status()
            payload = resp.json()
            params = None  # links.next already carries its own querystring

            for person in payload.get("directories") or []:
                out.append(
                    {
                        "constituent_id": str(person.get("id")),
                        "full_name": (person.get("full_name") or "").strip(),
                        "title": (person.get("title") or "").strip() or None,
                        "department": (person.get("department") or "").strip() or None,
                        "email": (person.get("email") or "").strip() or None,
                        "phone": (person.get("phone_number") or "").strip() or None,
                    }
                )
            url = ((payload.get("meta") or {}).get("links") or {}).get("next")

    return [p for p in out if p["full_name"]]


async def discover_school_info(website_url: str, timeout_ms: int = 20_000) -> dict:
    """Returns {"address": str|None, "main_phone": str|None, "logo_url":
    str|None} from an Apptegy page's own footer widget - confirmed real,
    per-building (not shared district boilerplate): each school subsite's
    own footer shows that school's own name/address/phone, e.g. Thomas
    Sharp's page shows Thomas Sharp's own address, not the district
    office's. Client-rendered (a plain fetch without waiting sees none of
    this), and genuinely empty for some schools whose profile was never
    filled in - that's a real "nothing to find" here, not a parse failure,
    same as the Finalsite equivalent's missing-fields case.

    Apptegy sites pick from more than one footer template - confirmed two:
    Collingswood/Woodlynne's "Find Us" (a `.footer-column-main` block, its
    address spans direct children of one `<p>`) and Oaklyn's "Contact Us:"
    (a `.contact-data .info` block, spans direct children of the div
    itself, with the phone one level deeper inside a nested span). Both
    share `img.footer-logo` and `a.tel-link` regardless of template, so
    those are found globally rather than assuming one container shape; the
    address spans are read from whichever direct span-parent (a `<p>` if
    the template has one, else the container itself) holds them, skipping
    the first (the school's own name) and whichever span holds the phone
    link.
    """
    result: dict = {"address": None, "main_phone": None, "logo_url": None}
    try:
        page = await scraper_client.fetch_html(website_url.rstrip("/") + "/", wait_for_selector="img.footer-logo", timeout_ms=timeout_ms)
    except Exception:
        return result

    soup = BeautifulSoup(page["html"], "lxml")
    logo = soup.select_one("img.footer-logo")
    if logo and logo.get("src"):
        result["logo_url"] = urljoin(website_url, logo["src"])

    tel = soup.select_one("a.tel-link")
    if tel:
        result["main_phone"] = tel.get_text(strip=True) or None

    block = soup.select_one(".footer-column-main") or soup.select_one(".contact-data .info")
    if block:
        span_parent = block.find("p") or block
        spans = span_parent.find_all("span", recursive=False)
        address_bits = [
            text
            for i, s in enumerate(spans)
            if i > 0 and not s.select_one("a.tel-link")
            for text in [s.get_text(strip=True)]
            if text
        ]
        result["address"] = ", ".join(dict.fromkeys(address_bits)) or None

    return result
