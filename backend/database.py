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


engine = create_async_engine(
    database_url(),
    pool_pre_ping=True,
    pool_recycle=1800,
    connect_args={"statement_cache_size": 0} if "asyncpg" in database_url() else {},
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
