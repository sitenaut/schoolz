"""Parses a Smore (or similarly structured) hosted-newsletter page into a
flat list of content blocks. Confirmed against real newsletters: Smore
renders client-side (Svelte), so this always goes through the scraper
service, waiting for `.block-wrapper` elements - the one class present
across every block type, image-only ones included - rather than waiting on
`img` specifically, which would time out on an all-text newsletter."""

import hashlib
import re

from bs4 import BeautifulSoup

import scraper_client
from scheduler.errors import record_parse_issue

_WAIT_SELECTOR = ".block-wrapper"
# Fallback for links that aren't real <a href> tags - Smore renders some
# links as plain auto-detected text (confirmed: a handbook link on a real
# newsletter was plain text inside an image block, no anchor at all).
_BARE_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")


def _content_hash(block_type: str, key: str) -> str:
    return hashlib.sha256(f"{block_type}:{key}".encode()).hexdigest()


def _find_link(block, text: str) -> str | None:
    anchor = block.select_one("a[href]")
    if anchor and anchor.get("href"):
        return anchor["href"]
    bare = _BARE_URL_RE.search(text)
    return bare.group(0) if bare else None


def _classify(block) -> dict | None:
    # Every image block carries a hover-only "zoom" control (a Material
    # Icons ligature "zoom_out_map" plus a screen-reader-only "Show in
    # original size" caption) that was silently being captured as if it
    # were the block's real text - since content_extractor.py favors
    # text_content over vision_extracted_text when both are present, this
    # meant the actual (vision-extracted) flyer content never reached
    # extraction for ANY image block, project-wide. Confirmed real: this
    # exact string ("zoom_out_mapShow in original size") was the stored
    # text_content for every image block checked. Remove it before reading
    # text - it's UI chrome, not content.
    for zoom_control in block.select("a.material-icons"):
        zoom_control.decompose()

    img = block.select_one("img")
    text = block.get_text(strip=True)
    link_url = _find_link(block, text)

    if img and img.get("src"):
        image_url = img["src"]
        return {
            "block_type": "image",
            "text_content": text or None,
            "image_url": image_url,
            "link_url": link_url,
            "content_hash": _content_hash("image", image_url),
        }
    if text:
        return {
            "block_type": "text",
            "text_content": text,
            "image_url": None,
            "link_url": link_url,
            "content_hash": _content_hash("text", text),
        }
    if link_url:
        return {
            "block_type": "link",
            "text_content": None,
            "image_url": None,
            "link_url": link_url,
            "content_hash": _content_hash("link", link_url),
        }
    return None


async def fetch_and_parse(url: str) -> list[dict]:
    """Returns a list of {position, block_type, text_content, image_url,
    link_url, content_hash} dicts, in document order. Empty/decorative
    blocks (no text, no image, no link) are skipped."""
    result = await scraper_client.fetch_html(url, wait_for_selector=_WAIT_SELECTOR, timeout_ms=25_000)
    soup = BeautifulSoup(result["html"], "lxml")

    blocks = []
    for position, wrapper in enumerate(soup.select(_WAIT_SELECTOR)):
        classified = _classify(wrapper)
        if classified:
            classified["position"] = position
            blocks.append(classified)
        else:
            record_parse_issue("smore.scan", "unclassified_block", url=url, position=position)
    return blocks
