"""Start-up check of the environment (SZ-16): every setting the backend
reads that can be wrong in a way nothing else notices.

`check_settings(process)` runs first thing in the API and the scheduler. A
missing or malformed setting is named (never its value) in one
`settings_validation_failed` log line. With `SETTINGS_ENFORCE=1` it also
refuses to start; that is off until a deploy has logged clean.

Why it exists: prod ran for weeks without JWT_SECRET, so the Gmail connect
state was signed with an empty key, and nothing said so. Values are still
read where they are used (`os.getenv`); this module only says, at start-up,
which of them are missing or would fail later.

Each entry: the variable, its kind, and which deployed processes need it.
Locally nothing is required, only checked for shape when set.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

API, SCHEDULER = "api", "scheduler"
BOTH = (API, SCHEDULER)


@dataclass(frozen=True)
class Setting:
    name: str
    kind: str = "text"  # text | int | float | url | bool | choice | fernet
    required_in: tuple[str, ...] = ()  # deployed processes that need it
    choices: tuple[str, ...] = ()


SETTINGS: tuple[Setting, ...] = (
    Setting("APP_ENV", "choice", BOTH, choices=("local", "prod")),
    Setting("AUTH_MODE", "choice", BOTH, choices=("local", "supabase")),
    Setting("DATABASE_URL", "url", BOTH),
    Setting("DATABASE_SSL_MODE", "choice", choices=("disable", "allow", "prefer", "require", "verify-ca", "verify-full")),
    Setting("DB_POOL_SIZE", "int"),
    Setting("DB_MAX_OVERFLOW", "int"),
    Setting("SUPABASE_URL", "url", BOTH),
    Setting("SUPABASE_SERVICE_ROLE_KEY", required_in=(API,)),
    Setting("PUBLIC_API_URL", "url", BOTH),
    Setting("PUBLIC_WEB_URL", "url", BOTH),
    Setting("FRONTEND_INTERNAL_URL", "url"),
    Setting("DATA_ENCRYPTION_KEYS", "fernet", BOTH),
    Setting("ENCRYPTION_REQUIRE", "bool"),
    Setting("RUN_NOW_VIA_SCHEDULER", "bool"),
    Setting("SECRETS_UNLOCK_KEY", required_in=(API,)),
    Setting("TURNSTILE_SECRET_KEY", required_in=(API,)),
    Setting("SCRAPER_URL", "url", BOTH),
    Setting("SCRAPER_API_KEY", required_in=BOTH),
    Setting("LOCAL_EVENTS_SCRAPER_URL", "url"),
    Setting("RESIDENTIAL_SCRAPER_URL", "url"),
    Setting("ANTHROPIC_API_KEY", required_in=BOTH),
    Setting("GOOGLE_CLIENT_ID", required_in=BOTH),
    Setting("GOOGLE_CLIENT_SECRET", required_in=BOTH),
    Setting("OTEL_EXPORTER_OTLP_ENDPOINT", "url"),
    Setting("LOG_LEVEL", "choice", choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")),
    Setting("JOB_CONCURRENCY", "int"),
    Setting("JOB_LAUNCH_SPACING_S", "float"),
    Setting("CALENDAR_CACHE_TTL_S", "float"),
)

# Set together or not at all: one without the other fails only when used.
PAIRS = (
    ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
    ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS"),
)

# Local-stack only. In prod they would be either unused or a hole.
LOCAL_ONLY = ("ADMIN_PASSWORD", "JWT_SECRET")

_BOOL_WORDS = ("1", "0", "true", "false", "yes", "no", "on", "off", "")


def _shape_problem(s: Setting, value: str) -> str | None:
    if s.kind == "int":
        try:
            int(value)
        except ValueError:
            return f"{s.name} is not a whole number"
    elif s.kind == "float":
        try:
            float(value)
        except ValueError:
            return f"{s.name} is not a number"
    elif s.kind == "url":
        parsed = urlparse(value)
        if not parsed.scheme or not parsed.netloc:
            return f"{s.name} is not a URL"
    elif s.kind == "bool":
        if value.strip().lower() not in _BOOL_WORDS:
            return f"{s.name} is not a yes/no value"
    elif s.kind == "choice":
        check = value.upper() if s.name == "LOG_LEVEL" else value
        if check not in s.choices:
            return f"{s.name} must be one of {', '.join(s.choices)}"
    elif s.kind == "fernet":
        from cryptography.fernet import Fernet

        import crypto

        try:
            for key in crypto.split_keys(value):
                Fernet(key)
        except ValueError:
            return f"{s.name} holds a value that is not a Fernet key"
    return None


def problems(process: str, env: dict[str, str] | None = None) -> list[str]:
    """What is wrong with the environment for `process`, by variable name."""
    env = dict(os.environ) if env is None else env
    deployed = bool(env.get("FLY_MACHINE_ID")) or env.get("APP_ENV") == "prod"
    found: list[str] = []
    for s in SETTINGS:
        value = env.get(s.name, "").strip()
        if not value:
            if deployed and process in s.required_in:
                found.append(f"{s.name} is not set")
            continue
        problem = _shape_problem(s, value)
        if problem:
            found.append(problem)
    for a, b in PAIRS:
        if bool(env.get(a)) != bool(env.get(b)):
            found.append(f"{a} and {b} must be set together")
    if deployed:
        for name in LOCAL_ONLY:
            if env.get(name):
                found.append(f"{name} is set but is only for the local stack")
    return found


def enforcing() -> bool:
    return os.getenv("SETTINGS_ENFORCE", "").strip().lower() in ("1", "true", "yes", "on")


class SettingsError(RuntimeError):
    pass


def check_settings(process: str) -> list[str]:
    """Log what is wrong; with SETTINGS_ENFORCE on, refuse to start."""
    found = problems(process)
    if not found:
        logger.info("settings_ok", extra={"component": process})
        return found
    logger.error("settings_validation_failed", extra={"component": process, "problems": found})
    if enforcing():
        raise SettingsError(f"{process}: refusing to start: " + "; ".join(found))
    return found
