"""Yodel (events.yodel.today) calendar widgets - where Macaroni KID moved its
event calendar. cherryhill.macaronikid.com/events is now just an iframe of
a Yodel widget, and its sitemap no longer lists any events (the old
sitemap source silently returned 0).

No scraper/Playwright needed. The widget is a Next.js page that server-
renders the first page of events into its React Server Components payload
(`self.__next_f.push(...)` chunks) with every field we want - description,
start/end, address + coordinates, pricing, categories. Later pages come
from the page's `fetchEvents` server action, called the same way the
widget's own "load more" button does: a POST to the widget URL with a
`Next-Action` header and a cursor. The action id is re-read from the page
on every run, since it changes whenever Yodel redeploys.

Example job-params entry:

    {
      "name": "macaronikid_cherryhill",
      "widget_url": "https://events.yodel.today/y/widget/69cd3f9d63e5877b4044dac3",
      "fallback_url": "https://cherryhill.macaronikid.com/events",
      "default_categories": ["kids", "family"]
    }
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

import httpx

from .base import RawEvent, Source

_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.S)
_ROW_ID_RE = re.compile(rb"([0-9a-f]+):")

# Yodel category -> this app's vocabulary (see normalizer.KEYWORD_CATEGORIES),
# so the chatbot's category filter and the /local chips mean the same thing.
_CATEGORY_MAP = {
    "Kids & Family": ["kids", "family"],
    "Parks & Rec": ["outdoor"],
    "Festivals/Fairs": ["outdoor"],
    "Arts": ["arts"],
    "Music & Entertainment": ["music", "entertainment"],
    "Sports, Youth": ["sports"],
    "Health & Fitness": ["fitness", "exercise"],
    "Classes/Workshops": ["classes-&-lessons"],
    "Seasonal & Holiday": ["seasonal"],
}

DEFAULT_MAX_PAGES = 10


def parse_flight(payload: bytes) -> dict[str, Any]:
    """Parse a React Server Components payload into {row_id: value}.

    Rows are `<hex id>:<json>\\n`, except text rows `<id>:T<hex len>,<text>`,
    whose text is exactly <len> UTF-8 bytes with no terminator (a long
    description is one of these, referenced elsewhere as "$<id>"). Other
    row kinds (I[...] module refs, etc.) are kept as raw strings.
    """
    rows: dict[str, Any] = {}
    i, n = 0, len(payload)
    while i < n:
        m = _ROW_ID_RE.match(payload, i)
        if not m:
            nl = payload.find(b"\n", i)
            i = n if nl < 0 else nl + 1
            continue
        row_id = m.group(1).decode()
        i = m.end()
        if payload[i : i + 1] == b"T":
            comma = payload.index(b",", i)
            length = int(payload[i + 1 : comma], 16)
            rows[row_id] = payload[comma + 1 : comma + 1 + length].decode("utf-8", "replace")
            i = comma + 1 + length
            continue
        nl = payload.find(b"\n", i)
        end = n if nl < 0 else nl
        raw = payload[i:end].decode("utf-8", "replace")
        try:
            rows[row_id] = json.loads(raw)
        except ValueError:
            rows[row_id] = raw
        i = end + 1
    return rows


def _page_flight(html: str) -> bytes:
    return "".join(json.loads(f'"{chunk}"') for chunk in _PUSH_RE.findall(html)).encode("utf-8")


def _find_key(obj: Any, key: str) -> dict | None:
    if isinstance(obj, dict):
        if key in obj:
            return obj
        children = obj.values()
    elif isinstance(obj, list):
        children = obj
    else:
        return None
    for child in children:
        found = _find_key(child, key)
        if found is not None:
            return found
    return None


def _deref(value: Any, rows: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$") and value[1:] in rows:
        return rows[value[1:]]
    return value


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class YodelSource(Source):
    def __init__(
        self,
        name: str,
        widget_url: str,
        *,
        fallback_url: str | None = None,
        default_categories: list[str] | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
        timeout: float = 30.0,
    ):
        self.name = name
        self.widget_url = widget_url
        self.fallback_url = fallback_url
        self.default_categories = default_categories or []
        self.max_pages = max(1, int(max_pages))
        self.timeout = timeout

    async def fetch(self) -> list[RawEvent]:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers={"User-Agent": _UA}) as client:
            resp = await client.get(self.widget_url)
            resp.raise_for_status()
            rows = parse_flight(_page_flight(resp.text))
            props = next((p for p in (_find_key(r, "initialEvents") for r in rows.values()) if p), None)
            if props is None:
                raise RuntimeError("Yodel widget page had no initialEvents - the page format changed")

            events = [self._to_raw(e, rows) for e in props.get("initialEvents") or []]
            has_more = bool(props.get("initialHasMore"))
            cursor = props.get("initialNextPageCursor")
            # A server-action reference is "$h<row>", and that row is {"id": ...}.
            ref = str(props.get("fetchEvents") or "")
            action = rows.get(ref[2:]) if ref.startswith("$h") else None
            action_id = action.get("id") if isinstance(action, dict) else None

            page = 1
            self.partial_failures = []
            while has_more and cursor and page < self.max_pages:
                if not action_id:
                    self.partial_failures.append("no fetchEvents action id - only the first page was read")
                    break
                page += 1
                try:
                    more_rows = await self._fetch_page(client, action_id, page, cursor)
                except Exception as exc:  # noqa: BLE001 - keep what page 1 gave us
                    self.partial_failures.append(f"page {page}: {type(exc).__name__}: {exc}"[:300])
                    break
                result = _find_key(more_rows.get("1"), "events") or {}
                events += [self._to_raw(e, more_rows) for e in result.get("events") or []]
                has_more = bool(result.get("hasMore"))
                cursor = result.get("nextPageCursor")

        seen: set[str] = set()
        unique = []
        for ev in events:
            if ev is not None and ev.source_event_id not in seen:
                seen.add(ev.source_event_id)
                unique.append(ev)
        return unique

    async def _fetch_page(self, client: httpx.AsyncClient, action_id: str, page: int, cursor: str) -> dict[str, Any]:
        widget_id = self.widget_url.rstrip("/").rsplit("/", 1)[-1]
        # Mirrors the widget's own call: fetchEvents(page, adsEnabled, widget,
        # searchParams, lastEventIds, eventsToSkip, false, cursor).
        body = json.dumps([page, False, {"widget_id": widget_id}, {}, None, 0, False, cursor])
        resp = await client.post(
            self.widget_url,
            content=body,
            headers={"Next-Action": action_id, "Accept": "text/x-component", "Content-Type": "text/plain;charset=UTF-8"},
        )
        resp.raise_for_status()
        return parse_flight(resp.content)

    def _to_raw(self, e: dict, rows: dict[str, Any]) -> RawEvent | None:
        content = e.get("content") or {}
        title = e.get("event_name") or content.get("event_name")
        start = _parse_dt(e.get("start") or (e.get("dateTime") or {}).get("start_dt"))
        if not title or not start or e.get("cancelled"):
            return None
        description = _deref(e.get("description") or content.get("description"), rows)
        location = e.get("location") or {}
        coords = ((location.get("geolocation") or {}).get("coordinates")) or [None, None]
        pricing = e.get("pricing") or {}
        categories = list(self.default_categories)
        for cat in e.get("categories") or content.get("categories") or []:
            for mapped in _CATEGORY_MAP.get(cat.get("name", ""), []):
                if mapped not in categories:
                    categories.append(mapped)
        url = e.get("website_url") or e.get("tickets_url") or e.get("register_url") or self.fallback_url
        occurrence = e.get("occurance_id") or start.date().isoformat()
        return RawEvent(
            source=self.name,
            source_event_id=f"{e.get('event_id') or e.get('_id')}:{occurrence}",
            title=title,
            description=description if isinstance(description, str) else None,
            start_time=start,
            end_time=_parse_dt(e.get("end") or (e.get("dateTime") or {}).get("end_dt")),
            all_day=bool(e.get("all_day")),
            venue_name=(e.get("organizer") or {}).get("organization_name"),
            venue_address=location.get("full"),
            longitude=coords[0],
            latitude=coords[1],
            url=url,
            image_url=e.get("raw_media_url"),
            price_min=pricing.get("amount_min"),
            price_max=pricing.get("amount_max"),
            is_free=pricing.get("is_free") if pricing else None,
            default_categories=categories,
            raw={"yodel_event_id": e.get("event_id"), "tags": [t.get("name") for t in content.get("tags") or []]},
        )
