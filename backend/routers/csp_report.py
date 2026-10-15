"""Where browsers send Content-Security-Policy violation reports (SZ-19).

The web app's policy (frontend/security-headers.inc.template) runs in
report-only mode first: nothing is blocked, and each violation a visitor's
browser sees is posted here. One `csp_violation` log line per report, plus
the `schoolz.csp.violations` counter by directive, so the policy can be
tightened, then enforced, on evidence.

Public by necessity (browsers post without credentials), so it stores
nothing, logs only origins and paths (never query strings, which can carry
tokens), caps the body, and drops reports past a per-minute budget.
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response, status

import observability
from services.client_ip import client_ip

logger = logging.getLogger(__name__)

router = APIRouter(tags=["security"])

_MAX_BODY = 16 * 1024
_MAX_REPORTS = 20
# Reports per address per minute. They arrive through the web app's nginx
# proxy (same-origin /csp-report), so every one comes from schoolz-web's
# address and this is in practice one shared cap: enough to see what the
# policy trips on, without letting a flood of reports flood the logs.
_BUDGET = 120
_WINDOW_S = 60.0
_seen: dict[str, deque[float]] = defaultdict(deque)

def _origin(url: str | None) -> str | None:
    """Scheme and host only. Bare keywords ('inline', 'eval', 'data') pass through."""
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return url[:40]


def _path(url: str | None) -> str | None:
    return urlsplit(url).path[:200] if url else None


def _within_budget(ip: str | None, now: float) -> bool:
    key = ip or "unknown"
    hits = _seen[key]
    while hits and now - hits[0] > _WINDOW_S:
        hits.popleft()
    if len(hits) >= _BUDGET:
        return False
    hits.append(now)
    if len(_seen) > 10_000:  # bound memory under a spray of addresses
        _seen.clear()
    return True


def _reports(payload) -> list[dict]:
    """Both wire formats: report-uri posts {"csp-report": {...}} with
    kebab-case keys; the Reporting API posts a list of
    {"type": "csp-violation", "body": {...}} with camelCase keys."""
    if isinstance(payload, dict) and isinstance(payload.get("csp-report"), dict):
        r = payload["csp-report"]
        return [{
            "directive": r.get("effective-directive") or r.get("violated-directive"),
            "blocked": r.get("blocked-uri"),
            "document": r.get("document-uri"),
            "source": r.get("source-file"),
            "line": r.get("line-number"),
            "disposition": r.get("disposition"),
        }]
    if isinstance(payload, list):
        out = []
        for item in payload[:_MAX_REPORTS]:
            if not isinstance(item, dict) or item.get("type") != "csp-violation":
                continue
            body = item.get("body")
            if not isinstance(body, dict):
                continue
            out.append({
                "directive": body.get("effectiveDirective"),
                "blocked": body.get("blockedURL"),
                "document": body.get("documentURL"),
                "source": body.get("sourceFile"),
                "line": body.get("lineNumber"),
                "disposition": body.get("disposition"),
            })
        return out
    return []


@router.post("/csp-report", status_code=status.HTTP_204_NO_CONTENT)
async def csp_report(request: Request) -> Response:
    if not _within_budget(client_ip(request), time.monotonic()):
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    try:
        payload = json.loads(raw or b"null")
    except ValueError:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    for r in _reports(payload):
        directive = str(r["directive"] or "unknown")[:60]
        observability.csp_violations_total.add(1, {"directive": directive})
        logger.info(
            "csp_violation",
            extra={
                "directive": directive,
                "blocked": _origin(r["blocked"]),
                "page": _path(r["document"]),
                "source": _origin(r["source"]),
                "line": r["line"] if isinstance(r["line"], int) else None,
                "disposition": str(r["disposition"] or "")[:20] or None,
            },
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
