import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from logging_config import setup_logging

setup_logging()

import database  # noqa: E402
import models  # noqa: F401,E402  (register tables with Base.metadata)
import observability  # noqa: E402
import scheduler.jobs  # noqa: F401,E402  (populate the job registry in this process too - needed for run-now)
import telemetry  # noqa: E402
from auth import prewarm_supabase_jwks, seed_admin  # noqa: E402
from routers import admin_config as admin_config_router  # noqa: E402
from routers import analytics as analytics_router  # noqa: E402
from routers import auth as auth_router  # noqa: E402
from routers import bucket3 as bucket3_router  # noqa: E402
from routers import calendar as calendar_router  # noqa: E402
from routers import community_submissions as community_submissions_router  # noqa: E402
from routers import directory as directory_router  # noqa: E402
from routers import districts as districts_router  # noqa: E402
from routers import email_scanners as email_scanners_router  # noqa: E402
from routers import gmail as gmail_router  # noqa: E402
from routers import health as health_router  # noqa: E402
from routers import invites as invites_router  # noqa: E402
from routers import notifications as notifications_router  # noqa: E402
from routers import scheduled_jobs as scheduled_jobs_router  # noqa: E402
from routers import school_emails as school_emails_router  # noqa: E402
from routers import schools as schools_router  # noqa: E402
from routers import scraper as scraper_router  # noqa: E402
from routers import seo as seo_router  # noqa: E402
from routers import survey as survey_router  # noqa: E402
from routers import smore_newsletters as smore_newsletters_router  # noqa: E402
from routers import student_accounts as student_accounts_router  # noqa: E402
from routers import students as students_router  # noqa: E402

logger = logging.getLogger(__name__)

_DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    # Local compose's own container-network origin for the frontend - the
    # scraper renders http://frontend:3000/... (not localhost:5173, which
    # only resolves on the host) when prerendering a page for a crawler
    # (services/prerender.py), so its browser's fetches carry this as
    # their Origin. Never sent by a real browser, in prod or locally, so
    # harmless to always allow.
    "http://frontend:3000",
]
_ALLOWED_ORIGIN_REGEX = r"^https://([a-zA-Z0-9-]+\.)*sitenaut\.com$|^http://localhost(:\d+)?$"
_SKIP_LOG_PATHS = {"/health"}

telemetry.setup_telemetry("schoolz-api")
telemetry.instrument_sqlalchemy_engine(database.engine)

# Set on the first non-health request this process handles - a Fly machine
# with min_machines_running=0 pays a cold-start tax on whoever wakes it.
_first_request_seen = False
_process_started_at = time.monotonic()


# Set once app/mcp_server are built below - referenced (not called) here,
# so definition order is fine as long as it's set before the app actually
# starts serving (lifespan runs long after module-level code finishes).
_mcp: FastMCP | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    prewarm_supabase_jwks()
    await seed_admin()
    assert _mcp is not None, "mcp_server must be mounted before the app starts"
    # The MCP session manager needs its own lifespan running for the
    # Streamable HTTP transport to work - mounting the sub-app alone
    # doesn't trigger it, since Starlette doesn't propagate lifespan into
    # mounted sub-apps automatically.
    async with _mcp.session_manager.run():
        yield
    telemetry.shutdown_telemetry()


app = FastAPI(title="schoolz-api", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app, excluded_urls="health")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in (os.getenv("PUBLIC_WEB_URL"),) if o] + _DEFAULT_ALLOWED_ORIGINS,
    allow_origin_regex=_ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Every GET currently sends Content-Type: application/json (see
    # apiFetch), which makes it a non-simple request and forces a preflight
    # - and Faro's traceparent header will too, once RUM ships. Browsers
    # cap how long they'll actually honor this (Chrome: 2h), but it still
    # cuts down repeat preflights within a session.
    max_age=86400,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    if request.url.path in _SKIP_LOG_PATHS:
        return await call_next(request)

    global _first_request_seen
    is_cold_start = not _first_request_seen
    _first_request_seen = True

    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start

    route = request.scope.get("route")
    route_path = route.path if route else None

    if is_cold_start:
        span = trace.get_current_span()
        span.set_attribute("app.cold_start", True)
        observability.cold_start_requests_total.add(1)
        logger.info(
            "cold_start_request",
            extra={"uptime_ms": round((time.monotonic() - _process_started_at) * 1000, 1)},
        )

    # user_id/authed are set by the auth dependencies in auth.py when a
    # request actually resolved a user. Without them there was no way to
    # tell an authenticated request from an anonymous one in the logs -
    # which is the first question worth asking about a bug a visitor only
    # hits while logged in (see the 2026-09-15 auth stall).
    user_id = getattr(request.state, "user_id", None)
    logger.info(
        "http_request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "route": route_path,
            "status": response.status_code,
            "duration_ms": round(duration * 1000, 1),
            "user_id": user_id,
            "authed": user_id is not None,
        },
    )
    return response


app.include_router(health_router.router)
app.include_router(admin_config_router.router)
app.include_router(auth_router.router)
app.include_router(scraper_router.router)
app.include_router(students_router.router)
app.include_router(bucket3_router.router)
app.include_router(student_accounts_router.router)
app.include_router(invites_router.router)
app.include_router(notifications_router.router)
app.include_router(gmail_router.router)
app.include_router(email_scanners_router.router)
app.include_router(scheduled_jobs_router.router)
app.include_router(school_emails_router.router)
app.include_router(smore_newsletters_router.router)
app.include_router(schools_router.router)
app.include_router(districts_router.router)
app.include_router(directory_router.router)
app.include_router(calendar_router.router)
app.include_router(community_submissions_router.router)
app.include_router(seo_router.router)
app.include_router(survey_router.router)
app.include_router(analytics_router.router)

from mcp_server import build_mcp_server  # noqa: E402

_mcp = build_mcp_server(app)
app.mount("/mcp", _mcp.streamable_http_app())
