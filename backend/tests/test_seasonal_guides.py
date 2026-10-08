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
from routers.seasonal_guides import today_et
from tests.test_students import _make_admin, _register


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _guide(season: str, starts: date, ends: date, **extra) -> dict:
    return {
        "season": season,
        "title": f"{season} guide",
        "publisher": "A Local Blog",
        "url": "https://example.com/guide",
        "starts_on": starts.isoformat(),
        "ends_on": ends.isoformat(),
        **extra,
    }


@pytest.mark.anyio
async def test_only_guides_in_their_window_are_public():
    run = uuid.uuid4().hex[:8]
    season = f"test-{run}"
    today = today_et()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await _register(client, f"a_{run}@example.com", f"a_{run}")
        guardian = await _register(client, f"g_{run}@example.com", f"g_{run}")
        await _make_admin(f"a_{run}@example.com")

        # Inclusive both ends: a guide ending today still shows.
        live = await client.post("/seasonal-guides", json=_guide(season, today - timedelta(days=3), today, sort_order=5), headers=auth(admin))
        assert live.status_code == 201
        lead = await client.post(
            "/seasonal-guides", json=_guide(season, today, today + timedelta(days=9), title="Headline map"), headers=auth(admin)
        )
        await client.post("/seasonal-guides", json=_guide(season, today + timedelta(days=1), today + timedelta(days=9)), headers=auth(admin))
        await client.post("/seasonal-guides", json=_guide(season, today - timedelta(days=9), today - timedelta(days=1)), headers=auth(admin))

        # Public, no login - and only the two whose window includes today, headline (lower sort_order) first.
        public = (await client.get(f"/seasonal-guides?season={season.upper()}")).json()
        assert [g["id"] for g in public] == [lead.json()["id"], live.json()["id"]]

        # The admin list has all four.
        assert len([g for g in (await client.get("/seasonal-guides/all", headers=auth(admin))).json() if g["season"] == season]) == 4

        # Writes and the full list are admin-only.
        assert (await client.post("/seasonal-guides", json=_guide(season, today, today), headers=auth(guardian))).status_code == 403
        assert (await client.get("/seasonal-guides/all")).status_code == 401

        # Validation: a backwards window, either on create or by a patch.
        assert (await client.post("/seasonal-guides", json=_guide(season, today, today - timedelta(days=1)), headers=auth(admin))).status_code == 422
        guide_id = live.json()["id"]
        bad = await client.patch(f"/seasonal-guides/{guide_id}", json={"ends_on": (today - timedelta(days=30)).isoformat()}, headers=auth(admin))
        assert bad.status_code == 422

        # Ending it yesterday takes it off the public list; delete removes it.
        ended = await client.patch(f"/seasonal-guides/{guide_id}", json={"ends_on": (today - timedelta(days=1)).isoformat()}, headers=auth(admin))
        assert ended.status_code == 200
        assert [g["id"] for g in (await client.get(f"/seasonal-guides?season={season}")).json()] == [lead.json()["id"]]
        assert (await client.delete(f"/seasonal-guides/{guide_id}", headers=auth(admin))).status_code == 204
        assert (await client.delete(f"/seasonal-guides/{guide_id}", headers=auth(admin))).status_code == 404


def test_chatbot_tool_is_registered_and_says_link_only():
    mcp = build_mcp_server(FastAPI())
    tool = next(t for t in asyncio.run(mcp.list_tools()) if t.name == "get_seasonal_guides")
    # The guides are other people's curation; the tool must steer the model
    # to link and credit rather than recite listings.
    assert "never name specific houses" in tool.description
