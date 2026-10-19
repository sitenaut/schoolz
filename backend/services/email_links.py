"""What an email scanner may take from an email: links to public newsletter
pages of the kinds in `LINK_KINDS`, and nothing else.

A scanner reads someone's real inbox, and a search filter that matches too
much reaches mail that has nothing to do with school (a doctor, an IEP
thread). So the message is read in memory, the allowed links are pulled
out, and only those links are kept - never the body, subject, sender or
Gmail's preview. Each scanner ticks which kinds it collects
(`EmailScanner.link_kinds`); the catalog itself is code, so nobody can widen
it to "every link".

Every link is reduced to the newsletter's public address before it is kept:
query strings go, because a newsletter's "view in browser" link carries the
recipient's subscriber id (`?e=...`). Click-tracking redirects
(`list-manage.com/track/click`, `out.smore.com`) and short links are never
matched at all - their destination is unknown without following them, and
following one tells the sender this recipient clicked. Images and
attachments never match: only these page addresses do.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from services.links import unwrap_redirect


@dataclass(frozen=True)
class LinkKind:
    key: str
    label: str
    # The newsletter source_type a found link becomes (SmoreNewsletter.source_type).
    source_type: str


LINK_KINDS: dict[str, LinkKind] = {
    "smore": LinkKind("smore", "Smore newsletters", "smore"),
    "mailchimp": LinkKind("mailchimp", "Mailchimp newsletters", "mailchimp"),
}

# A Smore issue: /n/<code> on app., www. or secure. (the three hosts real
# scanned issues have used). Author profiles (/u/) and image hosts don't match.
_SMORE_RE = re.compile(r"^(app|www|secure)\.smore\.com$", re.IGNORECASE)
_SMORE_PATH_RE = re.compile(r"^/n/([A-Za-z0-9-]+)/?$")
# Mailchimp's two public homes for a sent campaign:
#   https://mailchi.mp/<account>/<campaign-slug>
#   https://us7.campaign-archive.com/?u=<account>&id=<campaign>
_MAILCHIMP_SHORT_HOST = "mailchi.mp"
_MAILCHIMP_SHORT_PATH_RE = re.compile(r"^/[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)?/?$")
_CAMPAIGN_ARCHIVE_RE = re.compile(r"^(us\d+)\.campaign-archive\.com$", re.IGNORECASE)
_HEX_RE = re.compile(r"^[0-9a-f]{6,40}$", re.IGNORECASE)

# Candidate URLs in plain text. Deliberately loose: every candidate still
# has to pass `canonical` below.
_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)


def canonical(url: str) -> tuple[str, str] | None:
    """(kind, public URL) for a newsletter page of a known kind, else None."""
    url = unwrap_redirect(url.strip()) or ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    if _SMORE_RE.match(host):
        m = _SMORE_PATH_RE.match(parts.path)
        return ("smore", f"https://{host}/n/{m.group(1)}") if m else None
    if host == _MAILCHIMP_SHORT_HOST:
        if not _MAILCHIMP_SHORT_PATH_RE.match(parts.path):
            return None
        return "mailchimp", f"https://{host}{parts.path.rstrip('/')}"
    m = _CAMPAIGN_ARCHIVE_RE.match(host)
    if m and parts.path in ("", "/"):
        # /home/?u=... is the list's archive index, not one campaign - left out.
        query = parse_qs(parts.query)
        account, campaign = (query.get("u") or [""])[0], (query.get("id") or [""])[0]
        if _HEX_RE.match(account) and _HEX_RE.match(campaign):
            return "mailchimp", f"https://{m.group(1).lower()}.campaign-archive.com/?u={account}&id={campaign}"
    return None


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _candidates(payload: dict) -> list[str]:
    """Every URL in the message's text and HTML parts, in order. HTML is
    read for its link targets (newsletters are mostly HTML-only mail); no
    part is fetched, and attachments are never read."""
    found: list[str] = []

    def walk(part: dict) -> None:
        mime = (part.get("mimeType") or "").lower()
        data = (part.get("body") or {}).get("data")
        is_attachment = bool(part.get("filename"))
        if data and not is_attachment:
            if mime == "text/plain":
                found.extend(_URL_RE.findall(_decode(data)))
            elif mime == "text/html":
                soup = BeautifulSoup(_decode(data), "lxml")
                found.extend(a["href"] for a in soup.find_all("a", href=True))
                found.extend(_URL_RE.findall(soup.get_text(" ")))
        for sub in part.get("parts") or []:
            walk(sub)

    walk(payload)
    return found


def extract(message: dict, kinds: list[str] | tuple[str, ...]) -> list[dict]:
    """[{"kind", "url"}] for each distinct allowed link in a Gmail message
    (format="full"), in the order they appear."""
    allowed = set(kinds) & set(LINK_KINDS)
    out: dict[str, str] = {}
    for candidate in _candidates(message.get("payload") or {}):
        hit = canonical(candidate)
        if hit and hit[0] in allowed and hit[1] not in out:
            out[hit[1]] = hit[0]
    return [{"kind": kind, "url": url} for url, kind in out.items()]


def same_newsletter_urls(kind: str, url: str) -> list[str]:
    """Stored URLs that are the same newsletter as `url`: a Smore issue is
    one code on any of its three hosts (and older rows kept a `?ref=`)."""
    if kind == "smore":
        code = url.rsplit("/n/", 1)[1]
        return [f"https://{host}.smore.com/n/{code}" for host in ("app", "www", "secure")]
    return [url]
