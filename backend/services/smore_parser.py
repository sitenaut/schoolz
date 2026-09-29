"""Parses a Smore (or similarly structured) hosted-newsletter page into a
flat list of content blocks. Confirmed against real newsletters: Smore
renders client-side (Svelte), so this always goes through the scraper
service, waiting for `.block-wrapper` elements - the one class present
across every block type, image-only ones included - rather than waiting on
`img` specifically, which would time out on an all-text newsletter."""

import hashlib
import re
from datetime import datetime

from bs4 import BeautifulSoup

import scraper_client
from scheduler.errors import record_parse_issue
from services.links import unwrap_redirect

_WAIT_SELECTOR = ".block-wrapper"
_SMORE_ISSUE_HREF_RE = re.compile(r"^https?://(?:app|secure)\.smore\.com/n/", re.IGNORECASE)
# A site-nav link to a Smore AUTHOR's profile - every newsletter that
# person has ever published, not any one issue (confirmed real: Clara
# Barton Elementary's own archive page links only this, not per-issue
# links directly - contrast Cooper Elementary's archive page, which lists
# per-issue links itself with no author-profile hop needed).
_SMORE_AUTHOR_HREF_RE = re.compile(r"^https?://(?:www\.|app\.|secure\.)?smore\.com/u/", re.IGNORECASE)
_ARCHIVE_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y", "%m/%d/%y")
# Confirmed real: a Smore author profile shows each newsletter as a
# thumbnail card with no date in the link text itself - the date only
# appears as sibling text a few DOM levels up, e.g. "Last edited October 3, 2025".
_LAST_EDITED_RE = re.compile(r"Last edited\s+([A-Za-z]+ \d{1,2},\s*\d{4})")
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

    # A video embed (data-block-type="embed.video", confirmed real: a
    # YouTube embed on Cherry Hill East's newsletter) renders its actual
    # thumbnail as a CSS background-image on the play button, and puts a
    # base64-encoded SVG play-icon placeholder in the *foreground* <img
    # src>. Reading that <img> naively picks up the placeholder data: URI
    # as if it were a real fetchable image - _vision_extract then crashes
    # on it (httpx has no http(s) scheme to fetch) and the block is stuck
    # `pending_vision_extraction` forever. The video's title is already
    # real text in the DOM, so there's nothing to vision-extract anyway -
    # treat this as a text+link block instead of an image block.
    video_btn = block.select_one("[data-video-title]")
    if video_btn:
        title = video_btn.get("data-video-title") or ""
        video_url = video_btn.get("data-video-original-url") or video_btn.get("data-video-url")
        text_content = f"Video: {title}" if title else "Video"
        return {
            "block_type": "text",
            "text_content": text_content,
            "image_url": None,
            "link_url": video_url,
            "content_hash": _content_hash("text", text_content + (video_url or "")),
        }

    img = block.select_one("img")
    text = block.get_text(strip=True)
    link_url = _find_link(block, text)

    if img and img.get("src") and not img["src"].startswith("data:"):
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
            # Unwrapped only after _classify has hashed it: a link block's
            # content_hash is keyed on the URL as published, so hashing the
            # unwrapped one would make every already-stored wrapped link
            # look new on the next scan and get re-extracted.
            classified["link_url"] = unwrap_redirect(classified["link_url"])
            classified["position"] = position
            blocks.append(classified)
        else:
            record_parse_issue("smore.scan", "unclassified_block", url=url, position=position)
    return blocks


def _parse_archive_date(text: str) -> datetime | None:
    text = text.strip()
    for fmt in _ARCHIVE_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _nearby_last_edited_date(anchor) -> datetime | None:
    """Walks a few ancestors up from an issue link looking for a "Last
    edited <date>" string - the date lives as sibling text near the card,
    not inside the anchor itself, on a Smore author-profile page."""
    node = anchor
    for _ in range(5):
        if node.parent is None:
            break
        node = node.parent
        match = _LAST_EDITED_RE.search(node.get_text(" ", strip=True))
        if match:
            return _parse_archive_date(match.group(1))
    return None


def _pick_current_issue_link(html: str) -> str | None:
    """Confirmed real (Cherry Hill's James F. Cooper Elementary and Clara
    Barton Elementary, both of which publish from a page like this rather
    than emailing the new link out each week): the school's OWN website
    keeps a "Newsletter Archive" page that lists every past issue, e.g.
    "September 10, 2026" -> app.smore.com/n/0mhat. The *page* is the
    stable thing to track, not any one issue's link - a fixed issue URL
    goes dead the moment a newer one is published.

    Tries, in order: a parseable date in the link's own text (Cooper's
    style); a "Last edited <date>" string near the link (a Smore author
    profile's style); falling back to the *last* smore.com/n/ link in
    document order (a real archive lists oldest-to-newest) when neither
    yields a date, since a page that link-texts its issues some other way
    (an icon, "Read now") still reliably lists them chronologically."""
    soup = BeautifulSoup(html, "lxml")
    candidates = []
    for anchor in soup.select("a[href]"):
        href = anchor["href"]
        if _SMORE_ISSUE_HREF_RE.match(href):
            candidates.append((href, anchor))
    if not candidates:
        return None

    dated = []
    for href, anchor in candidates:
        found = _parse_archive_date(anchor.get_text(strip=True)) or _nearby_last_edited_date(anchor)
        if found:
            dated.append((href, found))
    if dated:
        return max(dated, key=lambda pair: pair[1])[0]
    return candidates[-1][0]


def _find_author_profile_link(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    for anchor in soup.select("a[href]"):
        if _SMORE_AUTHOR_HREF_RE.match(anchor["href"]):
            return anchor["href"]
    return None


async def discover_current_issue_url(archive_page_url: str) -> str | None:
    """Fetches a school's own "newsletter archive" page and resolves it to
    its current issue's URL. That page is itself a normal server-rendered
    page (Finalsite, in every case seen so far) - no Smore-specific wait
    selector needed for *this* fetch.

    Some schools' archive pages don't list per-issue links themselves,
    only a single link to the publishing staff member's Smore AUTHOR
    profile (confirmed real: Clara Barton Elementary) - a second,
    client-rendered Smore page listing every issue that person has ever
    published. When the first fetch finds no direct issue link, this
    follows that one extra hop."""
    result = await scraper_client.fetch_html(archive_page_url, wait_for_selector="a")
    link = _pick_current_issue_link(result["html"])
    if link:
        return link

    author_url = _find_author_profile_link(result["html"])
    if not author_url:
        return None
    author_result = await scraper_client.fetch_html(author_url, wait_for_selector='a[href*="smore.com/n/"]', timeout_ms=25_000)
    return _pick_current_issue_link(author_result["html"])
