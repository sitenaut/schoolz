"""Security headers on every API response (from billz's SEC-11).

The web app's nginx sets its own (frontend/security-headers.inc.template); the
API at schoolz-api.sitenaut.com had none. This adds:

- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`.
- `Strict-Transport-Security` outside local (local is plain HTTP).
- `Content-Security-Policy`: `default-src 'none'` on JSON and text, so a
  response opened directly in a tab can load nothing. The one HTML page the
  API renders itself (the Gmail OAuth popup closer) carries a small inline
  script, so HTML gets `'unsafe-inline'` for script and nothing else. Files
  (images, PDFs, XML) get no CSP, so the browser's own viewers still work.
- `Cache-Control: no-store` on JSON, unless the route set its own, so a
  signed-in visitor's data isn't kept by browser or proxy caches.

A header the route already set is left alone. Paths that nginx serves to
visitors under its own headers are skipped entirely: two CSP headers are both
enforced, so the API's would block the scripts in a prerendered page.
"""

from __future__ import annotations

import os

API_CSP = b"default-src 'none'; frame-ancestors 'none'"
HTML_CSP = b"default-src 'none'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
HSTS = b"max-age=31536000"
# /prerender and /sitemap.xml reach visitors through schoolz-web's nginx
# (frontend/nginx.conf.template); /docs and /redoc (local only) load their UI
# from a CDN.
_SKIP_PATHS = ("/prerender", "/sitemap.xml", "/docs", "/redoc")


def _csp_for(content_type: bytes) -> bytes | None:
    kind = content_type.split(b";")[0].strip().lower()
    if kind == b"text/html":
        return HTML_CSP
    if not kind or kind.endswith(b"json") or kind.startswith(b"text/"):
        return API_CSP
    return None


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app
        self.hsts = os.getenv("APP_ENV", "local") != "local"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "").startswith(_SKIP_PATHS):
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                content_type = next((v for k, v in headers if k.lower() == b"content-type"), b"")

                def add(name: bytes, value: bytes | None) -> None:
                    if value is not None and name not in present:
                        headers.append((name, value))

                add(b"x-content-type-options", b"nosniff")
                add(b"x-frame-options", b"DENY")
                add(b"referrer-policy", b"no-referrer")
                if self.hsts:
                    add(b"strict-transport-security", HSTS)
                add(b"content-security-policy", _csp_for(content_type))
                if content_type.split(b";")[0].strip().lower() == b"application/json":
                    add(b"cache-control", b"no-store")
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
