"""Discovers flyer/event links on a district's running "virtual backpack"
bulletin-board page (confirmed real: Audubon Public Schools, published at
/virtual-backpack) - a Finalsite page that just accumulates one <a> per
flyer/notice over the school year, rather than a Smore issue that gets
replaced week to week. Each link is a Finalsite "/fs/resource-manager/view/
<uuid>" wrapper, never the file itself - the real PDF only appears after
following that page's redirect, so a plain href=".pdf" scan (as
services/lunch_menu.py does) finds nothing on a page like this."""

import hashlib
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

import scraper_client

_RESOURCE_MANAGER_HREF_RE = re.compile(r"/fs/resource-manager/view/([0-9a-fA-F-]+)")


def _extract_links(html: str, page_url: str) -> list[dict]:
    """Returns [{"resource_id", "title", "wrapper_url"}], one per
    resource-manager link, in document order. Deduped by resource id - a
    real page genuinely repeats the same flyer under more than one section
    (confirmed real: Audubon's "Saturday Storytime" and "Chess Club Flyer"
    each appear twice), and only the first occurrence's link text is kept.
    A link with no text (an icon-only button) is skipped - there's nothing
    for a person or a model to read."""
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    items = []
    for anchor in soup.select('a[href*="/fs/resource-manager/view/"]'):
        href = anchor.get("href") or ""
        match = _RESOURCE_MANAGER_HREF_RE.search(href)
        if not match:
            continue
        resource_id = match.group(1)
        if resource_id in seen:
            continue
        title = anchor.get_text(strip=True)
        if not title:
            continue
        seen.add(resource_id)
        items.append({"resource_id": resource_id, "title": title, "wrapper_url": urljoin(page_url, href)})
    return items


async def discover_backpack_links(page_url: str) -> list[dict]:
    result = await scraper_client.fetch_html(page_url, wait_for_selector="a")
    return _extract_links(result["html"], page_url)


async def resolve_final_url(wrapper_url: str) -> str | None:
    """Follows a resource-manager wrapper's redirect to the real hosted
    file (a PDF, or occasionally an external page for a plain "Register
    Here" link). A HEAD is enough - Finalsite issues the redirect without
    needing the body, confirmed against real Audubon links."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            resp = await client.head(wrapper_url)
        return str(resp.url)
    except httpx.HTTPError:
        return None


def resource_content_hash(resource_id: str) -> str:
    """A dedup key that's stable *before* resolution, so an already-seen
    link is skipped without spending a network round-trip re-resolving it
    on every scan - this page only ever grows (~190 links and counting on
    Audubon's), so re-resolving everything every run would be pure waste."""
    return hashlib.sha256(f"backpack:{resource_id}".encode()).hexdigest()
