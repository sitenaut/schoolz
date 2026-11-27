"""Refuses a Backpack Capture import too big to hold in memory, before any of
it is read.

An import is parsed whole: the body, the parsed pages and every row they
touch sit in memory until the request ends. A 183-page publish (one request,
Backpack Capture 0.11.0) took the API machine past its 512 MB and Fly killed
it mid-request: the parent got a 502, and the site was down for everyone for
the seconds it took to restart. The extension now sends in batches well
under this cap, and Gradez's file import does the same; this is what stops
an older extension, or any other oversized request, from doing it again.

It has to run before routing: FastAPI reads and parses the whole body before
a route's dependencies run, so a check there would come after the memory was
already spent. Registered inside CORSMiddleware, so a browser can read the
refusal.
"""

import json
import re

IMPORT_MAX_BYTES = 4 * 1024 * 1024
_IMPORT_PATH = re.compile(r"^/(?:students/[^/]+/)?bucket3/import$")
TOO_LARGE = (
    "Too much to send to schoolz at once. Update Backpack Capture to the latest version, "
    "which sends in parts, then press Update schoolz."
)


async def _refuse(send) -> None:
    body = json.dumps({"detail": TOO_LARGE, "code": "too_large"}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


class ImportSizeLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST" or not _IMPORT_PATH.match(scope.get("path", "")):
            return await self.app(scope, receive, send)

        length = dict(scope.get("headers") or []).get(b"content-length")
        if length is not None:
            # The server holds the client to the length it declared.
            if not length.isdigit() or int(length) > IMPORT_MAX_BYTES:
                return await _refuse(send)
            return await self.app(scope, receive, send)

        # No declared length (chunked): read at most the cap, then hand the
        # app what was read as if it came straight from the client.
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return  # the client went away
            chunks.append(message.get("body", b""))
            size += len(chunks[-1])
            if size > IMPORT_MAX_BYTES:
                return await _refuse(send)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        sent = False

        async def replay():
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay, send)
