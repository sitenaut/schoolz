"""Request IDs and the error envelope (SZ-17).

Every request gets an ID: the caller's `X-Request-ID` when it is a sane token
(so a trace can start in the browser or a script), otherwise a new one. It is
sent back in the `X-Request-ID` response header, stamped on every log line
written while the request runs (`request_id`), and put in every error body.

Every error answers `{"detail": ..., "code": ..., "request_id": ...}`.
`detail` is exactly what it was before (a message, or FastAPI's validation
list), so callers that read it keep working; `code` is a stable word for
the kind of error; `request_id` is what to search the logs for.
"""
from __future__ import annotations

import contextvars
import logging
import re
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

HEADER = "X-Request-ID"
_HEADER_BYTES = HEADER.lower().encode()
_SANE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    410: "gone",
    413: "too_large",
    415: "unsupported_media_type",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "bad_gateway",
    503: "unavailable",
    504: "timeout",
}


def code_for(status: int) -> str:
    return CODES.get(status, "client_error" if status < 500 else "server_error")


class RequestIdMiddleware:
    """Pure ASGI, so the ID is set in the request's own context (log lines
    from anywhere inside see it) and the header is added to every response,
    streamed or not."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = next((v.decode("latin-1") for k, v in scope.get("headers", []) if k == _HEADER_BYTES), "")
        rid = incoming if _SANE.match(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid
        token = request_id_var.set(rid)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != _HEADER_BYTES]
                headers.append((_HEADER_BYTES, rid.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)


class RequestIdLogFilter(logging.Filter):
    """Puts the current request's ID on every log record (None outside one)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = request_id_var.get()
        return True


def _envelope(request: Request, status: int, detail, headers: dict | None = None) -> JSONResponse:
    rid = getattr(request.state, "request_id", None) or request_id_var.get()
    return JSONResponse(
        {"detail": detail, "code": code_for(status), "request_id": rid},
        status_code=status,
        headers={**(headers or {}), **({HEADER: rid} if rid else {})},
    )


def install(app: FastAPI) -> None:
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _envelope(request, exc.status_code, exc.detail, getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        from fastapi.encoders import jsonable_encoder

        return _envelope(request, 422, jsonable_encoder(exc.errors()))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # The traceback goes to the log under this request's ID; the caller
        # gets the ID to quote, never the exception text.
        # (This handler runs outside RequestIdMiddleware, so the ID comes
        # from request.state, not the context variable.)
        logger.exception(
            "unhandled_error",
            extra={"path": request.url.path, "request_id": getattr(request.state, "request_id", None)},
        )
        return _envelope(request, 500, "Internal server error")
