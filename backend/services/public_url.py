"""Whether a URL someone hands us points at the public internet.

The MCP server's submit_community_content (open to anyone, and to the
anonymous chatbot) checks that a submitted link is live by requesting it
from the API machine. Without this, that request could reach anything on
Fly's private network (schoolz-scraper.internal, 127.0.0.1, fdaa::) and the
reply's status said what answered: a port and service scanner.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

_MAX_REDIRECTS = 5
_PRIVATE_SUFFIXES = (".internal", ".local", ".localhost", "localhost")


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global


async def public_url_error(url: str) -> str | None:
    """Why `url` isn't a public http(s) address, or None when every address
    its host resolves to is public. Checked again before each redirect hop.
    (A host that re-resolves differently between this check and the request
    can still slip by; this closes the plain cases.)"""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "URL must start with http:// or https://"
    host = parts.hostname.rstrip(".").lower()
    if host.endswith(_PRIVATE_SUFFIXES):
        return "This URL isn't on the public internet"
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, ValueError, UnicodeError):
        return "Could not find this URL's website - double-check it's correct and publicly accessible"
    if not infos or not all(_is_public(info[4][0]) for info in infos):
        return "This URL isn't on the public internet"
    return None


async def check_public_page(client: httpx.AsyncClient, url: str) -> str | None:
    """Whether `url` is a live public page: an error message, or None.
    `client` must not follow redirects itself - each hop is re-checked here."""
    target = url
    for _ in range(_MAX_REDIRECTS + 1):
        problem = await public_url_error(target)
        if problem:
            return problem
        try:
            response = await client.head(target)
            # Some hosts (and most CDNs) reject HEAD outright - a 405
            # there says nothing about whether the page itself is real,
            # so fall back to a ranged GET rather than trusting HEAD.
            if response.status_code in (403, 405) or response.status_code >= 500:
                response = await client.get(target, headers={"Range": "bytes=0-0"})
        except httpx.RequestError as exc:
            return f"Could not reach this URL ({exc.__class__.__name__}) - double-check it's correct and publicly accessible"
        if response.is_redirect and response.headers.get("location"):
            target = urljoin(target, response.headers["location"])
            continue
        if response.status_code >= 400:
            return f"This URL returned {response.status_code} {response.reason_phrase} - it doesn't look like a live page"
        return None
    return "This URL redirects too many times"
