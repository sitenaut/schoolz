"""Guards for the one public endpoint that accepts a file from a stranger
(POST /submissions): a bot check, where the request came from, and what the
bytes really are.

The bot check is Cloudflare Turnstile. The widget on the page hands the
browser a one-time token; `verify_bot_check` trades it with Cloudflare for a
yes/no. With no TURNSTILE_SECRET_KEY the check is skipped locally and in
tests, but **refused in prod** - a missing secret must never quietly turn
the protection off.
"""

import logging
import os
import re

import httpx
from fastapi import Request

logger = logging.getLogger(__name__)

_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class BotCheckUnavailable(Exception):
    """The check couldn't be run at all (no secret in prod, Cloudflare down)."""


def client_ip(request: Request) -> str | None:
    """Fly puts the real client address in Fly-Client-IP, which a client
    can't forge. Elsewhere it's the first X-Forwarded-For entry, else the
    socket peer."""
    fly_ip = request.headers.get("fly-client-ip")
    if fly_ip:
        return fly_ip.strip()[:45]
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.client.host if request.client else None


def request_source(request: Request) -> dict:
    """The columns of SubmissionAttempt that come straight off the request."""
    h = request.headers
    return {
        "ip": client_ip(request),
        "forwarded_for": (h.get("x-forwarded-for") or "")[:500] or None,
        "user_agent": (h.get("user-agent") or "")[:400] or None,
        "accept_language": (h.get("accept-language") or "")[:200] or None,
        "referer": (h.get("referer") or "")[:500] or None,
        "origin": (h.get("origin") or "")[:200] or None,
        "edge_region": (h.get("fly-region") or "")[:20] or None,
    }


async def verify_bot_check(token: str | None, ip: str | None) -> tuple[bool, dict]:
    """(passed, what the checker said). Raises BotCheckUnavailable when no
    answer could be had."""
    secret = os.getenv("TURNSTILE_SECRET_KEY", "")
    if not secret:
        if os.getenv("APP_ENV", "local") == "prod":
            raise BotCheckUnavailable("TURNSTILE_SECRET_KEY is not set")
        return True, {"skipped": True}
    if not token:
        return False, {"success": False, "error-codes": ["missing-input-response"]}
    data = {"secret": secret, "response": token[:2048]}
    if ip:
        data["remoteip"] = ip
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(_VERIFY_URL, data=data)
            res.raise_for_status()
            body = res.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("turnstile verification unavailable: %s", exc)
        raise BotCheckUnavailable(str(exc)) from exc
    return bool(body.get("success")), body


_HEIF_BRANDS = {b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1", b"heif"}


def sniff_file_type(data: bytes) -> str | None:
    """The media type the bytes themselves claim, for the few kinds a flyer
    comes as - or None. The browser's Content-Type is never trusted: it is
    whatever the sender typed, and the admin download serves the file
    inline, so a stored "text/html" would run as a page."""
    if data[:5] == b"%PDF-":
        return "application/pdf"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS:
        return "image/heic"
    return None


def safe_file_name(name: str | None) -> str:
    """A bare file name that is safe inside a quoted Content-Disposition."""
    name = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[\x00-\x1f\x7f"]', "", name).strip()
    return name[:255] or "upload"
