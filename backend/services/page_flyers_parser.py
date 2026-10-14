"""A school or PTA page that is a stack of flyer images (St. Joan of Arc's
`/pta-1/` "Current PTA Happenings": two full-size posters in SiteOrigin image
widgets, no text at all). Each large image in the page's content becomes an
image block, read by the same vision step as a Smore flyer image.

The page is what is tracked, not an image: the school swaps the posters in
place, so an image seen before is skipped by URL and a new one is extracted."""

import hashlib
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

_HEADERS = {"User-Agent": "Mozilla/5.0 (schoolz flyer sync)"}
_IMAGE_EXT_RE = re.compile(r"\.(?:jpe?g|png|webp)(?:\?|$)", re.IGNORECASE)
_MIN_WIDTH = 300  # a logo, icon or avatar is smaller than a flyer
_CONTENT_SELECTORS = ("main", "#content", "article", ".entry-content")


def content_hash(image_url: str) -> str:
    return hashlib.sha256(f"page_flyers:{image_url}".encode()).hexdigest()


def extract_flyers(html: str, page_url: str) -> list[dict]:
    """[{position, block_type, text_content, image_url, link_url, content_hash}]
    in document order - the block shape every newsletter source produces, so
    services/content_extractor.py is reused unchanged."""
    soup = BeautifulSoup(html, "lxml")
    for junk in soup.select("header, footer, nav, script, style"):
        junk.decompose()
    root = next((el for sel in _CONTENT_SELECTORS if (el := soup.select_one(sel))), soup.body or soup)
    items: list[dict] = []
    seen: set[str] = set()
    for img in root.find_all("img"):
        src = (img.get("src") or "").strip()
        if not src or src.startswith("data:") or not _IMAGE_EXT_RE.search(src):
            continue
        width = str(img.get("width") or "")
        if width.isdigit() and int(width) < _MIN_WIDTH:
            continue
        url = urljoin(page_url, src)
        if url in seen:
            continue
        seen.add(url)
        alt = (img.get("alt") or "").strip()
        items.append({
            "position": len(items),
            "block_type": "image",
            "text_content": alt or None,
            "image_url": url,
            "link_url": None,
            "content_hash": content_hash(url),
        })
    return items


async def fetch_and_parse(page_url: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_HEADERS) as client:
        resp = await client.get(page_url)
        resp.raise_for_status()
        return extract_flyers(resp.text, str(resp.url))
