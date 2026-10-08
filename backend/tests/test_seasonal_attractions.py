import asyncio
import os
import uuid
from datetime import date, timedelta

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from main import app
from mcp_server import build_mcp_server
from routers.seasonal_attractions import miles_between
from tests.test_students import _make_admin, _register

CHERRY_HILL = (39.9268, -75.0246)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _attraction(season: str, name: str, start: date, end: date, lat: float, lng: float, **extra) -> dict:
    return {
        "season": season,
        "kind": "haunt",
        "name": name,
        "address": "1 Main St, Somewhere, NJ",
        "town": "Somewhere",
        "latitude": lat,
        "longitude": lng,
        "url": "https://example.com/",
        "starts_on": start.isoformat(),
        "ends_on": end.isoformat(),
        **extra,
    }


def test_miles_between_is_sane():
    # Cherry Hill to Mullica Hill is about 20 miles as the crow flies.
    assert 18 < miles_between(*CHERRY_HILL, 39.70401, -75.25086) < 21


@pytest.mark.anyio
async def test_open_on_a_day_nearest_first_and_unknown_nights_stay_unknown():
    run = uuid.uuid4().hex[:8]
    season = f"test-{run}"
    d0 = date(2031, 10, 1)  # far from the seeded season, so only this test's rows match
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await _register(client, f"a_{run}@example.com", f"a_{run}")
        guardian = await _register(client, f"g_{run}@example.com", f"g_{run}")
        await _make_admin(f"a_{run}@example.com")

        async def add(body):
            r = await client.post("/seasonal-attractions", json=body, headers=auth(admin))
            assert r.status_code == 201, r.text
            return r.json()["id"]

        far = await add(_attraction(season, "Far haunt", d0, d0 + timedelta(days=30), 39.36, -74.64,
                                    open_dates=[(d0 + timedelta(days=i)).isoformat() for i in (0, 7)]))
        near = await add(_attraction(season, "Near haunt", d0, d0 + timedelta(days=30), 39.79, -75.07,
                                     open_dates=[d0.isoformat()], scare_level="mild"))
        some_nights = await add(_attraction(season, "Select nights", d0, d0 + timedelta(days=30), 39.94, -74.77))
        await add(_attraction(season, "Over", d0 - timedelta(days=30), d0 - timedelta(days=1), 39.9, -75.0))

        q = f"/seasonal-attractions?season={season}&on={d0.isoformat()}&near_lat={CHERRY_HILL[0]}&near_lng={CHERRY_HILL[1]}"
        rows = (await client.get(q)).json()  # public, no login
        assert [r["id"] for r in rows] == [near, some_nights, far]  # nearest first; the finished one is gone
        assert [r["open_on_day"] for r in rows] == [True, None, True]
        assert rows[0]["miles"] < rows[1]["miles"] < rows[2]["miles"]

        # The day after: the near one is closed, select-nights is still a maybe.
        d1 = (d0 + timedelta(days=1)).isoformat()
        rows = (await client.get(f"/seasonal-attractions?season={season}&on={d1}&open_only=true")).json()
        assert {r["id"] for r in rows} == {some_nights}

        assert [r["id"] for r in (await client.get(f"{q}&max_miles=12")).json()] == [near]
        assert [r["id"] for r in (await client.get(f"{q}&scare_level=mild")).json()] == [near]

        # Admin-only writes, and the rows have to make sense.
        bad = _attraction(season, "x", d0, d0, 39.9, -75.0)
        assert (await client.post("/seasonal-attractions", json=bad, headers=auth(guardian))).status_code == 403
        assert (await client.post("/seasonal-attractions", json={**bad, "scare_level": "terrifying"}, headers=auth(admin))).status_code == 422
        outside = {**bad, "open_dates": [(d0 + timedelta(days=3)).isoformat()]}
        assert (await client.post("/seasonal-attractions", json=outside, headers=auth(admin))).status_code == 422
        r = await client.patch(f"/seasonal-attractions/{far}", json={"ends_on": d0.isoformat()}, headers=auth(admin))
        assert r.status_code == 422  # its Oct 8 night would fall outside the window
        r = await client.patch(f"/seasonal-attractions/{far}", json={"price": "$15"}, headers=auth(admin))
        assert r.status_code == 200 and r.json()["price"] == "$15"
        assert (await client.delete(f"/seasonal-attractions/{far}", headers=auth(admin))).status_code == 204
        assert (await client.get("/seasonal-attractions/all")).status_code == 401


def test_chatbot_tool_is_registered():
    mcp = build_mcp_server(FastAPI())
    tool = next(t for t in asyncio.run(mcp.list_tools()) if t.name == "find_seasonal_attractions")
    assert "select nights" in tool.description  # tells the model not to promise an unknown night
