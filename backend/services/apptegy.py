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

import httpx

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
