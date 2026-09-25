"""Source adapter that fetches rendered HTML via a scraper service and
extracts events from it. Ported from billz's events pipeline.

Used for sites that require JS execution (SPAs) or block direct fetches.
Scraper routing, most capable first:

    LOCAL_EVENTS_SCRAPER_URL  default: https://scraper-droplet.profitnaut.com
    LOCAL_EVENTS_SCRAPER_KEY  its X-API-Key (billz's RECIPE_SCRAPER_KEY)
    SCRAPER_URL / SCRAPER_API_KEY  schoolz's own scraper, as the fallback

The droplet is primary because it supports stealth and extra waits, and it
keeps these scans off schoolz's one small Chromium, which already absorbs
the 12h school-scan burst. A service with no key configured is skipped, so
local dev without the droplet key uses the local scraper.

Extraction strategy (per page):
1. Look for `<script type="application/ld+json">` blocks containing one or
   more schema.org Event entries. This handles sites that publish structured
   data after JS hydration.
2. If selectors are configured in the source params (`selectors.item`,
   `selectors.title`, `selectors.date`, `selectors.link`, `selectors.location`,
   `selectors.image`), iterate matching elements and assemble events that way.

Either path is acceptable. Sites that emit JSON-LD are preferable because the
data is canonical; selector configs are a per-site fragile workaround.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .base import RawEvent, Source

logger = logging.getLogger(__name__)

DEFAULT_PRIMARY_URL = "https://scraper-droplet.profitnaut.com"

_CHALLENGE_MARKERS = (
    "just a moment",
    "checking your browser",
    "attention required",
    "cloudflare",
)


def _looks_like_challenge(html: str) -> bool:
    head = html[:600].lower()
    return any(m in head for m in _CHALLENGE_MARKERS)


def _services() -> list[tuple[str, str]]:
    """(base_url, api_key) pairs to try in order, skipping any without a key."""
    # `or`, not env.get(..., default): an env var set to "" (compose's
    # `${VAR:-}` when the host has it unset) must still fall back.
    candidates = [
        ((os.environ.get("LOCAL_EVENTS_SCRAPER_URL") or DEFAULT_PRIMARY_URL).rstrip("/"), os.environ.get("LOCAL_EVENTS_SCRAPER_KEY", "")),
        ((os.environ.get("SCRAPER_URL") or "").rstrip("/"), os.environ.get("SCRAPER_API_KEY", "")),
    ]
    services = [(u, k) for u, k in candidates if u and k]
    if not services:
        raise RuntimeError("no scraper service configured (set LOCAL_EVENTS_SCRAPER_KEY, or SCRAPER_URL + SCRAPER_API_KEY)")
    return services


async def fetch_rendered_html(
    url: str,
    timeout: float = 90.0,
    wait_for_selector: str | None = None,
    extra_wait_ms: int | None = None,
    stealth: bool = True,
    include_shadow_dom: bool = False,
    timeout_ms: int | None = None,
) -> tuple[str, str]:
    """Fetch rendered HTML via the scraper service.

    Tries the droplet first, then schoolz's own scraper. Raises if both fail
    or both return a bot-challenge page. Returns (html, fetched_url).

    `wait_for_selector` makes Playwright wait for that CSS selector to appear
    before returning HTML - useful for SPAs that XHR content after first paint.
    `extra_wait_ms` adds a fixed sleep after page load (cap 30s) when no
    deterministic selector is available.
    `stealth` (default True) enables playwright-stealth's anti-bot-detection
    patches. Set False for sites confirmed not to need it - those patches
    have been observed to break a site's own JS (philaymca.org's Deyra
    Finder widget throws reference errors and never initializes with
    stealth on). schoolz's own scraper ignores stealth and extra_wait_ms.
    `include_shadow_dom` inlines open shadow roots into the returned HTML
    (schoolz's scraper; see scraper/main.py) - for web components like the
    Y's <deyra-finder>, whose content page.content() otherwise omits.
    `timeout_ms` is the scraper's own per-step limit (page load and the
    selector wait each get it; its default is 15s, max 60s) - raise it for
    heavy pages on prod's 1GB scraper.
    """
    payload: dict = {"url": url, "stealth": stealth}
    if wait_for_selector:
        payload["wait_for_selector"] = wait_for_selector
    if extra_wait_ms:
        payload["extra_wait_ms"] = int(extra_wait_ms)
    if include_shadow_dom:
        payload["include_shadow_dom"] = True
    if timeout_ms:
        payload["timeout_ms"] = int(timeout_ms)
        # The scraper spends up to timeout_ms on the page load and again on
        # the selector wait, so the HTTP call has to outlast both.
        timeout = max(timeout, 2 * timeout_ms / 1000 + 20)

    errors: list[str] = []
    for service_url, key in _services():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
                resp = await client.post(
                    f"{service_url}/fetch-html",
                    json=payload,
                    headers={"X-API-Key": key},
                )
                resp.raise_for_status()
            data = resp.json()
            html = data.get("html") or ""
            fetched_url = data.get("fetched_url") or data.get("url") or url
            if not html:
                errors.append(f"{service_url}: empty html")
                logger.info("scraper_empty_html", extra={"service": service_url, "url": url})
                continue
            if _looks_like_challenge(html):
                errors.append(f"{service_url}: bot challenge")
                logger.info("scraper_challenge_page", extra={"service": service_url, "url": url})
                continue
            return html, fetched_url
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{service_url}: {type(exc).__name__}: {exc}")
            logger.warning(
                "scraper_service_failed",
                extra={"service": service_url, "url": url, "error": str(exc)},
            )
            continue

    raise RuntimeError("all scraper services failed:\n  " + "\n  ".join(errors))


async def fetch_raw_via_scraper(url: str, timeout: float = 90.0) -> str:
    """Fetch a raw response body (e.g. an ICS file download) via the scraper service.

    Uses /fetch-raw instead of /fetch-html so Playwright captures the download
    content rather than trying to render the response as a page. The droplet
    returns `body`; schoolz's scraper returns `body_base64`. Returns the body
    as a string. Raises RuntimeError if all services fail.
    """
    errors: list[str] = []
    for service_url, key in _services():
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
                resp = await client.post(
                    f"{service_url}/fetch-raw",
                    json={"url": url},
                    headers={"X-API-Key": key},
                )
                resp.raise_for_status()
            data = resp.json()
            body = data.get("body") or ""
            if not body and data.get("body_base64"):
                body = base64.b64decode(data["body_base64"]).decode("utf-8", errors="replace")
            if not body:
                errors.append(f"{service_url}: empty body")
                continue
            return body
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{service_url}: {type(exc).__name__}: {exc}")
            logger.warning(
                "scraper_raw_failed",
                extra={"service": service_url, "url": url, "error": str(exc)},
            )
            continue

    raise RuntimeError("all scraper services failed:\n  " + "\n  ".join(errors))


# ── extraction helpers ──────────────────────────────────────────────────────

def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _iter_jsonld_events(html: str) -> list[dict]:
    """Yield each schema.org Event object found in <script type=application/ld+json>."""
    soup = BeautifulSoup(html, "html.parser")
    events: list[dict] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in _walk_jsonld(parsed):
            t = node.get("@type")
            if isinstance(t, list):
                if any(x and "Event" in x for x in t):
                    events.append(node)
            elif isinstance(t, str) and "Event" in t:
                events.append(node)
    return events


def _walk_jsonld(node: Any) -> list[dict]:
    """Yield dict nodes from arbitrarily nested JSON-LD (@graph, arrays, etc.)."""
    out: list[dict] = []
    if isinstance(node, dict):
        out.append(node)
        if isinstance(node.get("@graph"), list):
            for child in node["@graph"]:
                out.extend(_walk_jsonld(child))
    elif isinstance(node, list):
        for child in node:
            out.extend(_walk_jsonld(child))
    return out


def _location_from_jsonld(loc: Any) -> tuple[str | None, str | None, float | None, float | None]:
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if not isinstance(loc, dict):
        return None, None, None, None
    name = loc.get("name")
    addr = loc.get("address")
    addr_str: str | None = None
    if isinstance(addr, dict):
        parts = [addr.get(k) for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode")]
        addr_str = ", ".join(p for p in parts if p) or None
    elif isinstance(addr, str):
        addr_str = addr
    geo = loc.get("geo") if isinstance(loc.get("geo"), dict) else None
    lat = lon = None
    if geo:
        try:
            lat = float(geo["latitude"]) if geo.get("latitude") is not None else None
            lon = float(geo["longitude"]) if geo.get("longitude") is not None else None
        except (TypeError, ValueError):
            lat = lon = None
    return name, addr_str, lat, lon


def _jsonld_image(image: Any) -> str | None:
    if isinstance(image, str):
        return image
    if isinstance(image, list) and image:
        first = image[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return first.get("url")
    if isinstance(image, dict):
        return image.get("url")
    return None


def _jsonld_offer_prices(offers: Any) -> tuple[float | None, float | None, bool | None]:
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list) or not offers:
        return None, None, None
    prices: list[float] = []
    for o in offers:
        if not isinstance(o, dict):
            continue
        for k in ("price", "lowPrice", "highPrice"):
            v = o.get(k)
            try:
                if v is not None:
                    prices.append(float(v))
            except (TypeError, ValueError):
                continue
    if not prices:
        return None, None, None
    pmin, pmax = min(prices), max(prices)
    is_free = pmin == 0
    return pmin, pmax, is_free


def _jsonld_to_raw(node: dict, source_name: str, default_categories: list[str], page_url: str) -> RawEvent | None:
    title = (node.get("name") or "").strip()
    start = _parse_iso(node.get("startDate"))
    if not title or start is None:
        return None
    end = _parse_iso(node.get("endDate"))
    venue, addr, lat, lon = _location_from_jsonld(node.get("location"))
    image = _jsonld_image(node.get("image"))
    pmin, pmax, is_free = _jsonld_offer_prices(node.get("offers"))
    url = node.get("url") or page_url
    description = node.get("description")
    if isinstance(description, str):
        description = description.strip() or None
    else:
        description = None
    sid = node.get("@id") or node.get("identifier") or url
    if not sid:
        sid = "hash:" + hashlib.sha1(f"{title}|{start.isoformat()}".encode("utf-8")).hexdigest()[:24]

    return RawEvent(
        source=source_name,
        source_event_id=str(sid),
        title=title,
        description=description,
        start_time=start,
        end_time=end,
        venue_name=venue,
        venue_address=addr,
        latitude=lat,
        longitude=lon,
        url=url,
        image_url=image,
        price_min=pmin,
        price_max=pmax,
        is_free=is_free,
        default_categories=list(default_categories),
        raw={"jsonld_type": node.get("@type")},
    )


def _selector_to_raws(
    html: str,
    selectors: dict,
    source_name: str,
    default_categories: list[str],
    page_url: str,
) -> list[RawEvent]:
    item_sel = selectors.get("item")
    if not item_sel:
        return []
    soup = BeautifulSoup(html, "html.parser")
    raws: list[RawEvent] = []
    for el in soup.select(item_sel):
        try:
            def pick(key: str) -> str | None:
                sel = selectors.get(key)
                if not sel:
                    return None
                node = el.select_one(sel)
                if node is None:
                    return None
                txt = node.get_text(" ", strip=True)
                return txt or None

            def pick_attr(key: str, attr: str) -> str | None:
                sel = selectors.get(key)
                if not sel:
                    return None
                node = el.select_one(sel)
                if node is None:
                    return None
                return node.get(attr) or None

            title = pick("title")
            date_str = pick("date")
            link = pick_attr("link", "href")
            image = pick_attr("image", "src")
            location = pick("location")
            if not title or not date_str:
                continue
            start = _parse_iso(date_str)
            if start is None:
                continue
            raws.append(
                RawEvent(
                    source=source_name,
                    source_event_id=link or ("hash:" + hashlib.sha1(f"{title}|{start.isoformat()}".encode()).hexdigest()[:24]),
                    title=title,
                    start_time=start,
                    url=link,
                    image_url=image,
                    venue_name=location,
                    venue_address=location,
                    default_categories=list(default_categories),
                    raw={"selector_item": item_sel},
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("scraper_selector_item_skipped", extra={"source": source_name, "error": str(exc)})
            continue
    return raws


class ScraperSource(Source):
    def __init__(
        self,
        name: str,
        url: str,
        default_categories: list[str] | None = None,
        selectors: dict | None = None,
        render_wait_selector: str | None = None,
        render_extra_wait_ms: int | None = None,
    ):
        self.name = name
        self.url = url
        self.default_categories = default_categories or []
        self.selectors = selectors or {}
        self.render_wait_selector = render_wait_selector
        self.render_extra_wait_ms = render_extra_wait_ms

    async def fetch(self) -> list[RawEvent]:
        html, fetched_url = await fetch_rendered_html(
            self.url,
            wait_for_selector=self.render_wait_selector,
            extra_wait_ms=self.render_extra_wait_ms,
        )

        # 1. JSON-LD first.
        jsonld_nodes = _iter_jsonld_events(html)
        raws: list[RawEvent] = []
        for node in jsonld_nodes:
            raw = _jsonld_to_raw(node, self.name, self.default_categories, fetched_url)
            if raw is not None:
                raws.append(raw)
        if raws:
            return raws

        # 2. Selector fallback.
        if self.selectors:
            return _selector_to_raws(html, self.selectors, self.name, self.default_categories, fetched_url)

        logger.info(
            "scraper_no_events_extracted",
            extra={"source": self.name, "url": self.url, "html_len": len(html)},
        )
        return []

    async def diagnose(self) -> dict[str, str]:
        """Return a small dict of probe info for the verbose test-fetch mode."""
        try:
            html, fetched_url = await fetch_rendered_html(
                self.url,
                wait_for_selector=self.render_wait_selector,
                extra_wait_ms=self.render_extra_wait_ms,
            )
        except Exception as exc:  # noqa: BLE001
            return {"_error": f"{type(exc).__name__}: {exc}"}
        jsonld_nodes = _iter_jsonld_events(html)
        soup = BeautifulSoup(html, "html.parser")
        head = soup.find("head")
        title_tag = head.find("title") if head else None
        return {
            "fetched_url": fetched_url,
            "html_chars": str(len(html)),
            "jsonld_event_count": str(len(jsonld_nodes)),
            "page_title": (title_tag.get_text(strip=True) if title_tag else "")[:200],
            "first_jsonld_type": str(jsonld_nodes[0].get("@type")) if jsonld_nodes else "(no JSON-LD Event found)",
            "body_text_excerpt": re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:300],
        }
