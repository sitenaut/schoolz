import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import database


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def _isolated_db_transaction(monkeypatch):
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
