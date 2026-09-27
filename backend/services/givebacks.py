"""Givebacks (givebacks.com) - the platform behind most PTAs' own sites in
this district. Confirmed live: **no bot-blocking at all** (unlike NJDOE's
Incapsula wall) - a clean public JSON API sits under the client-rendered
SPA, reachable with plain httpx, no scraper/Playwright needed.

There's no structured "events" feature to read - each PTA hand-builds its
own pages with a drag-and-drop page builder, and the builder itself has
changed generations over the org's lifetime, so the SAME organization can
have pages in more than one shape:

- Newest ("block-tree") pages carry a pre-rendered `content.html_raw` -
  full static HTML (Unlayer-style `.u_content_text`/`.u_content_image`
  blocks) - confirmed real on Bret Harte's "UpcomingEvents"/
  "VolunteerOpportunities" pages. This is the simple case: parse the
  static HTML directly, same shape of problem `smore_parser.py` already
  solves for Smore, and images are real S3-hosted URLs.
- Older ("legacy") pages have an EMPTY `html_raw` and instead carry one or
  more named blobs (`content.content`, `content.block1`, `content.block2`,
  ...), each `{"text": "<html>", "title": "..."}` - confirmed real on
  Thomas Sharp's home page (`block1`/`block2`) and its "Events and
  Opportunities" page (`content`). A flyer image here is embedded directly
  as a `data:` URI in the HTML, not a hosted URL - there's nothing to fetch
  later, so the bytes are decoded once here and carried through in-memory
  for the same run's vision pass (see scheduler/jobs/givebacks_scan.py).

Both shapes are normalized into the same flat block-dict shape
smore_parser.py returns, so the rest of the pipeline (dedup, vision
extraction, content_extractor's stale-year/supersede logic) doesn't need
to know which generation of page builder produced a given block.
"""

import base64
import hashlib
import re

import httpx
from bs4 import BeautifulSoup

_HEADERS = {"User-Agent": "Mozilla/5.0 (schoolz PTA content sync)", "Accept": "application/json"}
_CAUSE_URL = "https://api.givebacks.com/services/core/causes/{shortname}"
_WEBPAGES_URL = "https://legacy.api.givebacks.com/services/memberhub-service/webpages"

_BARE_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")
_DATA_URI_RE = re.compile(r"^data:([\w/.+-]+);base64,(.+)$", re.DOTALL)

# Keys under a legacy page's `content` that hold an HTML blob, in the order
# a page builder actually lays them out (confirmed real: Thomas Sharp's
# home page has both `block1` and `block2`, `block1` first).
_LEGACY_BLOB_KEYS = ("block1", "block2", "block3", "content")


def _content_hash(block_type: str, key: str) -> str:
    return hashlib.sha256(f"{block_type}:{key}".encode()).hexdigest()


async def resolve_org(client: httpx.AsyncClient, shortname: str) -> dict | None:
    """Looks up a `<shortname>.givebacks.com` org. Returns the `cause` dict
    (name/address/memberhub_id/...) or None if the shortname doesn't exist -
    a 404-shaped org (Givebacks answers 200 with an error body, not a real
    404 status, for an unknown shortname)."""
    resp = await client.get(_CAUSE_URL.format(shortname=shortname), headers=_HEADERS, timeout=15.0)
    if resp.status_code != 200:
        return None
    data = resp.json()
    cause = data.get("cause")
    if not cause or not cause.get("memberhub_id"):
        return None
    return cause


# A PTA's own name routinely adds words a school's name never has ("PTA",
# "PTSO", "Parent Teacher Association") and just as routinely drops the
# level word a school's name has ("Bret Harte School PTA" vs our "Bret
# Harte Elementary") - stripped on both sides so the comparison is on the
# building's actual name, not on which naming convention each side chose.
# Unlike schoolcafe.py's matcher (which compares among many candidate
# schools and must not collapse two real, differently-leveled buildings
# into the same token set), this only ever sanity-checks one admin-chosen
# shortname against the one school it was set on - there's no sibling
# building to accidentally match instead.
_NAME_NOISE = re.compile(r"\b(pta|ptso|parent|teacher|association|school|elementary|middle|high|the|of|and|at)\b")


def _norm(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    return " ".join(_NAME_NOISE.sub(" ", cleaned).split())


def _tokens(text: str) -> set[str]:
    return set(_norm(text).split())


def verified_match(org: dict, school_name: str, school_address: str | None) -> bool:
    """Cheap name/address sanity check before a shortname is trusted at
    onboarding time - a wrong PTA's page is worse than none. Reuses the
    same symmetric token-containment idea as schoolcafe.py:_either_contains
    rather than a third copy of it (this module can't import that one
    directly without pulling in schoolcafe's school-menu-specific noise
    stripping, which doesn't apply to PTA org names)."""
    org_tokens = _tokens(org.get("name") or "")
    school_tokens = _tokens(school_name)
    name_match = bool(org_tokens) and bool(school_tokens) and (org_tokens <= school_tokens or school_tokens <= org_tokens)
    if name_match:
        return True
    if not school_address:
        return False
    return bool(_tokens(org.get("address") or "") & _tokens(school_address))


async def fetch_pages(client: httpx.AsyncClient, org_uuid: str) -> list[dict]:
    """Every page on the org's site - there's no fixed naming convention
    ("UpcomingEvents", "/calendar", "/eventsandopportunities" all seen for
    real), so every page is crawled rather than guessing a path."""
    resp = await client.get(_WEBPAGES_URL, params={"organization_uuid": org_uuid, "live": "true"}, headers=_HEADERS, timeout=20.0)
    resp.raise_for_status()
    return resp.json().get("webpages") or []


def _find_link(el) -> str | None:
    anchor = el.select_one("a[href]")
    if anchor and anchor.get("href"):
        return anchor["href"]
    bare = _BARE_URL_RE.search(el.get_text(" "))
    return bare.group(0) if bare else None


def _decode_data_uri(src: str) -> bytes | None:
    m = _DATA_URI_RE.match(src.strip())
    if not m:
        return None
    try:
        return base64.b64decode(m.group(2))
    except (ValueError, base64.binascii.Error):
        return None


def _parse_block_tree_html(page_path: str, html_raw: str) -> list[dict]:
    """Newer page-builder format: html_raw is a full static page, real
    content living in Unlayer's own `.u_content_text`/`.u_content_image`
    wrapper classes. Images here are always real S3 URLs (confirmed real:
    Bret Harte) - no data: URI handling needed, unlike the legacy format."""
    soup = BeautifulSoup(html_raw, "html.parser")
    blocks = []
    for position, el in enumerate(soup.select(".u_content_text, .u_content_image")):
        classes = el.get("class") or []
        link_url = _find_link(el)
        if "u_content_image" in classes:
            img = el.select_one("img")
            src = img.get("src") if img else None
            if not src:
                continue
            blocks.append(
                {
                    "page_path": page_path,
                    "position": position,
                    "block_type": "image",
                    "text_content": None,
                    "image_url": src,
                    "link_url": link_url,
                    "content_hash": _content_hash("image", src),
                    "_image_bytes": None,
                }
            )
            continue
        text = el.get_text(" ", strip=True)
        if not text:
            continue
        blocks.append(
            {
                "page_path": page_path,
                "position": position,
                "block_type": "text",
                "text_content": text,
                "image_url": None,
                "link_url": link_url,
                "content_hash": _content_hash("text", text),
                "_image_bytes": None,
            }
        )
    return blocks


def _parse_legacy_blob(page_path: str, html: str, start_position: int) -> list[dict]:
    """Older page-builder format: one HTML blob per named section
    (block1/block2/content), each parsed the same way - a flyer image is
    embedded as a `data:` URI directly in the markup (confirmed real:
    Thomas Sharp), so it's decoded to real bytes here rather than stored as
    a fetchable URL (there isn't one). Text is whatever's left once every
    <img> is stripped out, on the theory that this format's captions/blurbs
    are typically short and adjacent to the image they describe rather than
    interleaved with several unrelated images (confirmed real: Thomas
    Sharp's events page is three flyer images with no other text at all)."""
    soup = BeautifulSoup(html, "html.parser")
    blocks = []
    position = start_position
    for img in soup.select("img"):
        src = img.get("src") or ""
        if src.startswith("data:"):
            image_bytes = _decode_data_uri(src)
            if image_bytes is None:
                img.decompose()
                continue
            blocks.append(
                {
                    "page_path": page_path,
                    "position": position,
                    "block_type": "image",
                    "text_content": None,
                    "image_url": None,
                    "link_url": None,
                    "content_hash": _content_hash("image", hashlib.sha256(image_bytes).hexdigest()),
                    "_image_bytes": image_bytes,
                }
            )
        elif src:
            blocks.append(
                {
                    "page_path": page_path,
                    "position": position,
                    "block_type": "image",
                    "text_content": None,
                    "image_url": src,
                    "link_url": None,
                    "content_hash": _content_hash("image", src),
                    "_image_bytes": None,
                }
            )
        else:
            img.decompose()
            continue
        position += 1
        img.decompose()

    link_url = _find_link(soup)
    text = soup.get_text(" ", strip=True)
    if text:
        blocks.insert(
            0,
            {
                "page_path": page_path,
                "position": start_position - 1,
                "block_type": "text",
                "text_content": text,
                "image_url": None,
                "link_url": link_url,
                "content_hash": _content_hash("text", text),
                "_image_bytes": None,
            },
        )
    return blocks


def _renumber(blocks: list[dict]) -> list[dict]:
    for position, block in enumerate(blocks):
        block["position"] = position
    return blocks


def parse_page(page: dict) -> list[dict]:
    """Normalizes one webpage entry (whichever content shape it's in) into
    the flat block list the rest of the pipeline expects."""
    path = page.get("path") or "/"
    content = page.get("content") or {}
    html_raw = content.get("html_raw") or ""
    if html_raw.strip():
        return _renumber(_parse_block_tree_html(path, html_raw))

    blocks: list[dict] = []
    for key in _LEGACY_BLOB_KEYS:
        blob = content.get(key)
        if isinstance(blob, dict) and isinstance(blob.get("text"), str) and blob["text"].strip():
            blocks.extend(_parse_legacy_blob(path, blob["text"], len(blocks)))
    return _renumber(blocks)


async def fetch_and_parse(shortname: str) -> list[dict]:
    """Resolves the org, crawls every page, and returns every page's blocks
    normalized and concatenated - mirrors smore_parser.py:fetch_and_parse's
    return contract (position/block_type/text_content/image_url/link_url/
    content_hash), plus `page_path` since one org has several pages, and an
    internal-only `_image_bytes` for a legacy-format image with no
    fetchable URL (see module docstring)."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        org = await resolve_org(client, shortname)
        if org is None:
            return []
        pages = await fetch_pages(client, org["memberhub_id"])

    blocks: list[dict] = []
    for page in pages:
        blocks.extend(parse_page(page))
    return blocks
