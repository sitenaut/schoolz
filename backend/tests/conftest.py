import inspect
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")
# Tests change data between identical anonymous calls to the cached routes.
os.environ.setdefault("CALENDAR_CACHE_TTL_S", "0")
os.environ.setdefault("DIRECTORY_CACHE_TTL_S", "0")
os.environ.setdefault("SITEMAP_CACHE_TTL_S", "0")
os.environ.setdefault("AUDIT_CACHE_TTL_S", "0")
os.environ.setdefault("RESOURCE_CATEGORIES_CACHE_TTL_S", "0")
os.environ.setdefault("LOCAL_EVENTS_CACHE_TTL_S", "0")

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import database


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _no_real_scrapers(monkeypatch):
    """The dev container carries real scraper keys, so any test that didn't
    mock fetch_html sent live renders to the droplet and the residential Pi
    (the Pi's "more than half of requests failing" alert fired on pytest's
    example-school.chclc.org, 2026-10-05). Tests get no scraper configured."""
    import scraper_client
    for name in ("SCRAPER_URL", "SCRAPER_API_KEY", "_FALLBACK_URL", "_FALLBACK_API_KEY",
                 "_RESIDENTIAL_URL", "_RESIDENTIAL_API_KEY"):
        monkeypatch.setattr(scraper_client, name, "")


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch):
    """Files named by scraped pages are fetched only from public addresses
    (services/public_url.py PUBLIC_ONLY), which resolves each host. Tests use
    made-up hosts behind mock transports, so here a name resolves to a public
    address and an IP literal to itself."""
    import ipaddress

    from services import public_url

    async def addresses(host, port):
        try:
            ipaddress.ip_address(host.split("%", 1)[0])
        except ValueError:
            return ["93.184.216.34"]
        return [host]

    monkeypatch.setattr(public_url, "_addresses", addresses)


@pytest.fixture(autouse=True)
def _no_real_geocoding(monkeypatch):
    """run_pipeline ends by geocoding the events it saved (local_events/
    locate.py); with no lookup budget a test never calls Census or
    Nominatim. A test of locate.py raises the budget and mocks _lookup."""
    from local_events import locate
    monkeypatch.setattr(locate, "MAX_LOOKUPS", 0)


@pytest.fixture(autouse=True)
def _no_background_translation(monkeypatch):
    """A request queues missing translations for a background worker. Under
    pytest that worker would share the test's one connection with the request
    still using it, so it never starts: a test that wants the translations
    runs the queue itself with `content_translation.drain()`."""
    from services import content_translation
    monkeypatch.setattr(content_translation, "_start_worker", lambda: None)
    content_translation._PENDING.clear()
    yield
    content_translation._PENDING.clear()


@pytest.fixture(autouse=True)
def _isolated_db_transaction(request):
    """Every async test runs inside `_db_transaction` below. A plain sync test
    can't reach the async database, and pytest 9 refuses a sync test that
    depends on an async fixture (pytest 8 handed it an un-awaited coroutine,
    so it never had a transaction either)."""
    if inspect.iscoroutinefunction(request.function) and request.node.get_closest_marker("anyio"):
        request.getfixturevalue("_db_transaction")


@pytest.fixture
async def _db_transaction(monkeypatch):
    """Wraps every test in one database transaction that's rolled back at
    the end, so nothing a test does - registering a user, creating a
    school or district, scheduling a job - persists past that test. This
    is the real fix for the "tests write into the shared local database"
    footgun documented in CLAUDE.md: previously nothing rolled test data
    back at all, so every local `pytest -q` run left another batch of
    throwaway rows behind (confirmed to reach 169 leftover test users
    across sessions before being caught). `scripts/cleanup_test_data.py`
    remains as a one-time sweep for anything left over from before this
    fixture existed, but new runs shouldn't need it.

    Each anyio test gets its own event loop, and the module-level async
    engine/pool is bound to whichever loop was current when it was first
    created, so the pool is disposed first to force a fresh connection on
    the *current* loop (same reasoning the old version of this fixture
    had). Then one connection is opened for the whole test and
    `database.SessionLocal` is monkeypatched to a sessionmaker bound to
    that single connection, with `join_transaction_mode="create_savepoint"`
    so that a `session.commit()` anywhere in application code (including
    inside a request handled through `get_db()`, and inside any test
    helper that calls `database.SessionLocal()` directly - see
    tests/test_students.py's `_make_admin`) only releases a SAVEPOINT
    instead of ending the outer transaction. Rolling back that one outer
    transaction at the end undoes everything, from every session, in one
    step - the standard SQLAlchemy pattern for this ("joining a session
    into an external transaction"), not something bespoke to this repo.

    A test that itself calls `commit()` still sees its own writes (SAVEPOINT
    release, not a real commit) - reads within the same test behave exactly
    as they would against a real commit. Only a fresh connection *outside*
    this transaction (there isn't one anywhere in this test suite) would
    fail to see them, which is the whole point."""
    await database.engine.dispose()
    conn = await database.engine.connect()
    await conn.begin()
    test_session_factory = async_sessionmaker(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
    monkeypatch.setattr(database, "SessionLocal", test_session_factory)
    try:
        yield
    finally:
        await conn.rollback()
        await conn.close()
