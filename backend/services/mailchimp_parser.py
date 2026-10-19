"""Parses a sent Mailchimp campaign's public page (mailchi.mp/<account>/<slug>
or <dc>.campaign-archive.com/?u=..&id=..) into the same flat block list
smore_parser.py produces, so services/content_extractor.py reads it
unchanged and image blocks get the same vision pass.

Server-rendered HTML, so a plain GET is enough (no scraper, no JS wait).
Checked against real campaigns: the current builder marks text blocks
`.mceText`, images `img.mceImage` and buttons `a.mceButtonLink`; the classic
templates use `.mcnTextContent` / `img.mcnImage` / `a.mcnButton`. Social
icons carry neither image class, so they never become blocks.

A campaign Mailchimp has taken down redirects to
mailchimp.com/about/mcsv-static (a page about Mailchimp itself) - reported
as zero blocks, like an expired Smore link.
"""
from __future__ import annotations

import hashlib
import re

import httpx
from bs4 import BeautifulSoup

from services.links import unwrap_redirect

_BLOCK_SELECTOR = ".mceText, .mcnTextContent, img.mceImage, img.mcnImage, a.mceButtonLink, a.mcnButton"
# The archive page's own toolbar (share, translate, subscribe) above the email.
_CHROME_SELECTOR = "script, style, noscript, #awesomewrap, #awesomebar, #awesomeshare, #awesomesocial"
# The footer every campaign carries. A text block saying any of these is
# the footer, not content.
_FOOTER_RE = re.compile(
    r"unsubscribe|update your preferences|view (this )?email in (your )?browser|why did i get this|"
    r"you are receiving this|our mailing address is|add us to your address book",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")
_GONE_HOST = "mailchimp.com"


def _content_hash(block_type: str, key: str) -> str:
    return hashlib.sha256(f"{block_type}:{key}".encode()).hexdigest()


def _text(node) -> str:
    return _WS_RE.sub(" ", node.get_text(" ", strip=True)).strip()


def parse(html: str) -> list[dict]:
    """[{position, block_type, text_content, image_url, link_url, content_hash}]
    in document order."""
    soup = BeautifulSoup(html, "lxml")
    for chrome in soup.select(_CHROME_SELECTOR):
        chrome.decompose()
    blocks: list[dict] = []
    seen: set[str] = set()
    for node in soup.select(_BLOCK_SELECTOR):
        if node.name == "img":
            src = (node.get("src") or "").strip()
            if not src.lower().startswith(("http://", "https://")):
                continue
            parent_link = node.find_parent("a", href=True)
            block = {
                "block_type": "image",
                "text_content": (node.get("alt") or "").strip() or None,
                "image_url": src,
                "link_url": unwrap_redirect(parent_link["href"]) if parent_link else None,
                "content_hash": _content_hash("image", src),
            }
        elif node.name == "a":
            text, href = _text(node), unwrap_redirect(node.get("href"))
            if not text or not href:
                continue
            block = {
                "block_type": "text",
                "text_content": text,
                "image_url": None,
                "link_url": href,
                "content_hash": _content_hash("text", text + href),
            }
        else:
            text = _text(node)
            if not text or _FOOTER_RE.search(text):
                continue
            anchor = node.select_one("a[href]")
            block = {
                "block_type": "text",
                "text_content": text,
                "image_url": None,
                "link_url": unwrap_redirect(anchor["href"]) if anchor else None,
                "content_hash": _content_hash("text", text),
            }
        if block["content_hash"] in seen:
            continue
        seen.add(block["content_hash"])
        blocks.append({"position": len(blocks), **block})
    return blocks


async def fetch_and_parse(url: str) -> list[dict]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
        res = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; schoolz)"})
    if (res.url.host or "").lower().endswith(_GONE_HOST):
        return []
    res.raise_for_status()
    return parse(res.text)
