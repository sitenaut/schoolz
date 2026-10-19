import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from database import get_db
from main import app

client = TestClient(app)


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"


@pytest.mark.anyio
async def test_ready():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_ready_is_503_when_the_database_fails():
    class BrokenSession:
        async def execute(self, *args, **kwargs):
            raise ConnectionError("database down")

    async def broken_db():
        yield BrokenSession()

    app.dependency_overrides[get_db] = broken_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            res = await ac.get("/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert res.status_code == 503
    assert res.json() == {"status": "unavailable"}
