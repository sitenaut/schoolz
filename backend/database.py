import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase


def _normalize(url: str, driver: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = f"postgresql+{driver}://" + url[len("postgresql://"):]
    return url


def database_url(*, sync: bool = False) -> str:
    driver = "psycopg" if sync else "asyncpg"

    raw = os.getenv("DATABASE_URL")
    if raw:
        url = _normalize(raw, driver)
        ssl_mode = os.getenv("DATABASE_SSL_MODE")
        if ssl_mode and "sslmode=" not in url and "ssl=" not in url:
            sep = "&" if "?" in url else "?"
            param = "sslmode" if sync else "ssl"
            url = f"{url}{sep}{param}={ssl_mode}"
        return url

    host = os.getenv("DATABASE_HOST", "postgres")
    port = os.getenv("DATABASE_PORT", "5432")
    name = os.getenv("DATABASE_NAME", "schoolz")
    user = os.getenv("DATABASE_USER", "schoolz")
    password = os.getenv("DATABASE_PASSWORD") or os.getenv("POSTGRES_PASSWORD", "")
    return f"postgresql+{driver}://{user}:{password}@{host}:{port}/{name}"


class Base(DeclarativeBase):
    pass


# Supabase's session pooler allows 15 connections for this database user,
# every process together - a shared ceiling, not a per-engine allowance - and
# in session mode a connection idling in our pool still holds its slot. Over
# the limit, the pooler refuses the connect: EMAXCONNSESSION, a 500.
#
# Prod runs up to three processes: the scheduler and two API machines (Fly
# starts the second one under load). At 4 + 2 each they could ask for 18,
# and every traffic spike that woke the second API machine turned into a
# burst of 500s on public pages. The budget, per process (pool + overflow):
#   API machine  3 + 1 = 4, two of them = 8
#   scheduler    4 + 2 = 6  (a burst of concurrent scans needs it:
#                            scheduler/runner.py's JOB_CONCURRENCY)
# 14 in all, one spare for the nightly backup or a deploy's release step. A
# third API machine or a bigger scheduler pool means redoing this sum; the
# pool-saturated alert (scripts/build_grafana_alerts.py:DB_POOL_MAX) repeats
# these numbers.
_POOL_DEFAULTS = {"scheduler": (4, 2)}
_pool_size, _max_overflow = _POOL_DEFAULTS.get(os.getenv("FLY_PROCESS_GROUP", ""), (3, 1))

engine = create_async_engine(
    database_url(),
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_size=int(os.getenv("DB_POOL_SIZE", _pool_size)),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", _max_overflow)),
    connect_args={"statement_cache_size": 0} if "asyncpg" in database_url() else {},
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
