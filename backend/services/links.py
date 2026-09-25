"""Unwrapping mail-security redirect links back to the URL they point at.

A newsletter or site that was drafted by forwarding an email carries the
forwarder's link-rewriting with it - confirmed real: a PTA Google Form
published on a newsletter as
`https://nam04.safelinks.protection.outlook.com/?url=https%3A%2F%2Fdocs.google.com%2Fforms%2F...&data=...`.
It still resolves, but it's a wall of encoded text wherever a link is shown
(the chatbot printed it verbatim), routes every click through Microsoft, and
the `data=` blob carries the original recipient's mailbox details.

Only the wrappers seen in real data are handled - add one here when it's
actually found, not speculatively.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

_SAFELINKS_HOST_RE = re.compile(r"(?:^|\.)safelinks\.protection\.outlook\.com$", re.I)
# A wrapper can wrap a wrapper (forwarded twice, two tenants); a small cap
# keeps a malformed self-referencing link from looping.
_MAX_DEPTH = 3


def unwrap_redirect(url: str | None) -> str | None:
    """The real destination of a known redirect wrapper, else `url` as-is.
    Only ever returns an http(s) URL in place of the wrapper - a wrapper
    whose target is missing or isn't http(s) is left alone rather than
    turned into something worse."""
    for _ in range(_MAX_DEPTH):
        if not url:
            return url
        parts = urlsplit(url.strip())
        if not _SAFELINKS_HOST_RE.search(parts.hostname or ""):
            return url
        target = (parse_qs(parts.query).get("url") or [""])[0].strip()
        if not target.lower().startswith(("http://", "https://")):
            return url
        url = target
    return url
