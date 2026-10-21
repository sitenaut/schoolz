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

# The API process bills its Anthropic calls to its own key. What runs here was
# started by a person (a run-now, an on-demand translation, the kids view, a
# submission review), so a spend cap on it must not be able to stop the
# unattended scans in the scheduler, or the other way round. Swapped here,
# before the imports below, because several services read the key at import.
if os.getenv("ANTHROPIC_API_KEY_INTERACTIVE"):
    os.environ["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY_INTERACTIVE"]

import database  # noqa: E402
import models  # noqa: F401,E402  (register tables with Base.metadata)
import observability  # noqa: E402
import request_context  # noqa: E402
import scheduler.jobs  # noqa: F401,E402  (populate the job registry in this process too - needed for run-now)
import security_headers  # noqa: E402
import telemetry  # noqa: E402
from auth import check_deployed_auth_mode, is_deployed, prewarm_supabase_jwks, seed_admin  # noqa: E402
from routers import admin_api_keys as admin_api_keys_router  # noqa: E402
from routers import admin_audit as admin_audit_router  # noqa: E402
from routers import admin_chatbot as admin_chatbot_router  # noqa: E402
from routers import admin_config as admin_config_router  # noqa: E402
from routers import admin_resources as admin_resources_router  # noqa: E402
from routers import admin_secret_requests as admin_secret_requests_router  # noqa: E402
from routers import admin_users as admin_users_router  # noqa: E402
from routers import analytics as analytics_router  # noqa: E402
from routers import auth as auth_router  # noqa: E402
from routers import bucket3 as bucket3_router  # noqa: E402
from routers import calendar as calendar_router  # noqa: E402
from routers import capture_devices as capture_devices_router  # noqa: E402
from routers import chat as chat_router  # noqa: E402
from routers import class_years as class_years_router  # noqa: E402
from routers import community_submissions as community_submissions_router  # noqa: E402
from routers import contact_messages as contact_messages_router  # noqa: E402
from routers import csp_report as csp_report_router  # noqa: E402
from routers import data_audit as data_audit_router  # noqa: E402
from routers import directory as directory_router  # noqa: E402
from routers import districts as districts_router  # noqa: E402
from routers import email_scanners as email_scanners_router  # noqa: E402
from routers import gmail as gmail_router  # noqa: E402
from routers import health as health_router  # noqa: E402
from routers import invites as invites_router  # noqa: E402
from routers import local_events as local_events_router  # noqa: E402
from routers import notifications as notifications_router  # noqa: E402
from routers import provider_portal as provider_portal_router  # noqa: E402
from routers import resources as resources_router  # noqa: E402
from routers import saved_profile as saved_profile_router  # noqa: E402
from routers import scheduled_jobs as scheduled_jobs_router  # noqa: E402
from routers import school_emails as school_emails_router  # noqa: E402
from routers import schools as schools_router  # noqa: E402
from routers import scraper as scraper_router  # noqa: E402
from routers import seasonal_attractions as seasonal_attractions_router  # noqa: E402
from routers import seasonal_guides as seasonal_guides_router  # noqa: E402
from routers import seo as seo_router  # noqa: E402
from routers import smore_newsletters as smore_newsletters_router  # noqa: E402
from routers import specials as specials_router  # noqa: E402
from routers import student_accounts as student_accounts_router  # noqa: E402
from routers import students as students_router  # noqa: E402
from routers import survey as survey_router  # noqa: E402
from services import audit  # noqa: E402
from settings import check_settings  # noqa: E402

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
_SKIP_LOG_PATHS = {"/health", "/ready"}

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
    check_settings("api")
    check_deployed_auth_mode()
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


# The interactive docs and the schema are for local work only: in prod they
# hand anyone a map of every admin route and its parameters.
_api_docs = not is_deployed()
app = FastAPI(
    title="schoolz-api",
    lifespan=lifespan,
    docs_url="/docs" if _api_docs else None,
    redoc_url="/redoc" if _api_docs else None,
    openapi_url="/openapi.json" if _api_docs else None,
)
FastAPIInstrumentor.instrument_app(app, excluded_urls="/health$,/ready$")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in (os.getenv("PUBLIC_WEB_URL"),) if o] + _DEFAULT_ALLOWED_ORIGINS,
    allow_origin_regex=_ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
    # Every GET currently sends Content-Type: application/json (see
    # apiFetch), which makes it a non-simple request and forces a preflight
    # - and Faro's traceparent header will too, once RUM ships. Browsers
    # cap how long they'll actually honor this (Chrome: 2h), but it still
    # cuts down repeat preflights within a session.
    max_age=86400,
)
app.add_middleware(security_headers.SecurityHeadersMiddleware)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    if request.url.path in _SKIP_LOG_PATHS:
        return await call_next(request)

    global _first_request_seen
    is_cold_start = not _first_request_seen
    _first_request_seen = True

    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        # An unhandled exception never reaches the http_request line below,
        # so a crashed request was missing from every request count and
        # search. Write its line here - status 500, at ERROR, with the
        # exception type - then let it propagate to the error handler.
        route = request.scope.get("route")
        logger.error(
            "http_request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "route": route.path if route else None,
                "status": 500,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                "user_id": getattr(request.state, "user_id", None),
                "authed": getattr(request.state, "user_id", None) is not None,
                "api_key_id": getattr(request.state, "api_key_id", None),
                "exception": type(exc).__name__,
            },
        )
        raise
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
            "api_key_id": getattr(request.state, "api_key_id", None),
        },
    )
    return response


# Inside the request-id middleware (it records the id) and outside routing
# (it reads the matched route once the app has answered).
app.add_middleware(audit.AuditMiddleware)

# After every other middleware, so it is the outermost: the ID is set before
# log_requests runs and is on every response, errors included.
request_context.install(app)

app.include_router(health_router.router)
app.include_router(csp_report_router.router)
app.include_router(admin_config_router.router)
app.include_router(admin_users_router.router)
app.include_router(admin_audit_router.router)
app.include_router(admin_api_keys_router.router)
app.include_router(admin_api_keys_router.device_router)
app.include_router(capture_devices_router.router)
app.include_router(admin_secret_requests_router.router)
app.include_router(auth_router.router)
app.include_router(scraper_router.router)
app.include_router(students_router.router)
app.include_router(specials_router.router)
app.include_router(bucket3_router.router)
app.include_router(student_accounts_router.router)
app.include_router(invites_router.router)
app.include_router(notifications_router.router)
app.include_router(contact_messages_router.router)
app.include_router(gmail_router.router)
app.include_router(email_scanners_router.router)
app.include_router(scheduled_jobs_router.router)
app.include_router(school_emails_router.router)
app.include_router(smore_newsletters_router.router)
app.include_router(schools_router.router)
app.include_router(class_years_router.router)
app.include_router(districts_router.router)
app.include_router(directory_router.router)
app.include_router(calendar_router.router)
app.include_router(local_events_router.router)
app.include_router(resources_router.router)
app.include_router(saved_profile_router.router)
app.include_router(provider_portal_router.router)
app.include_router(admin_resources_router.router)
app.include_router(seasonal_guides_router.router)
app.include_router(seasonal_attractions_router.router)
app.include_router(community_submissions_router.router)
app.include_router(seo_router.router)
app.include_router(survey_router.router)
app.include_router(analytics_router.router)
app.include_router(chat_router.router)
app.include_router(admin_chatbot_router.router)
app.include_router(data_audit_router.router)
app.include_router(data_audit_router.public_router)

from mcp_server import build_mcp_server  # noqa: E402

_mcp = build_mcp_server(app)
app.mount("/mcp", _mcp.streamable_http_app())
# The chat router (routers/chat.py) reads this at request time rather than
# importing _mcp directly - chat_router is imported, and its router
# included, before _mcp exists (routers are wired up before the MCP server
# is built), so a module-level import would be a circular/order problem.
# Request-time access via app.state sidesteps that entirely.
app.state.mcp = _mcp
