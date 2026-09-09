import logging
import os
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, make_asgi_app

from logging_config import setup_logging

setup_logging()

import models  # noqa: F401,E402  (register tables with Base.metadata)
import scheduler.jobs  # noqa: F401,E402  (populate the job registry in this process too - needed for run-now)
from auth import prewarm_supabase_jwks, seed_admin  # noqa: E402
from routers import admin_config as admin_config_router  # noqa: E402
from routers import auth as auth_router  # noqa: E402
from routers import calendar as calendar_router  # noqa: E402
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
from routers import smore_newsletters as smore_newsletters_router  # noqa: E402
from routers import students as students_router  # noqa: E402

logger = logging.getLogger(__name__)

_DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
]
_ALLOWED_ORIGIN_REGEX = r"^https://([a-zA-Z0-9-]+\.)*sitenaut\.com$|^http://localhost(:\d+)?$"

# ── Prometheus HTTP metrics, scraped by Alloy at /metrics ──────────────────────
_HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Total HTTP requests handled by the backend.",
    ["method", "path", "status"],
)
_HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency.",
    ["method", "path"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
_ID_RE = re.compile(r"/[0-9a-fA-F-]{8,}")
_SKIP_LOG_PATHS = {"/health", "/metrics"}


def _normalize_path(path: str) -> str:
    return (_ID_RE.sub("/:id", path) or "/")[:128]


@asynccontextmanager
async def lifespan(_: FastAPI):
    prewarm_supabase_jwks()
    await seed_admin()
    yield


app = FastAPI(title="schoolz-api", lifespan=lifespan)

app.mount("/metrics", make_asgi_app())

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in (os.getenv("PUBLIC_WEB_URL"),) if o] + _DEFAULT_ALLOWED_ORIGINS,
    allow_origin_regex=_ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    if request.url.path in _SKIP_LOG_PATHS:
        return await call_next(request)
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
    path = _normalize_path(request.url.path)
    _HTTP_REQUESTS.labels(method=request.method, path=path, status=response.status_code).inc()
    _HTTP_DURATION.labels(method=request.method, path=path).observe(duration)
    logger.info(
        "http_request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round(duration * 1000, 1),
        },
    )
    return response


app.include_router(health_router.router)
app.include_router(admin_config_router.router)
app.include_router(auth_router.router)
app.include_router(scraper_router.router)
app.include_router(students_router.router)
app.include_router(invites_router.router)
app.include_router(notifications_router.router)
app.include_router(gmail_router.router)
app.include_router(email_scanners_router.router)
app.include_router(scheduled_jobs_router.router)
app.include_router(school_emails_router.router)
app.include_router(smore_newsletters_router.router)
app.include_router(schools_router.router)
app.include_router(districts_router.router)
app.include_router(calendar_router.router)
