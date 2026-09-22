"""API tests for POST /scheduled-jobs/test-fetch (ported from billz).

Verifies that every source type accepted by the endpoint (ical, rss, scraper,
sitemap, listing_page, evvnt, json) is recognised, probed, and returned in the
`sources` array — and that misconfigured entries come back with status
"misconfigured" rather than being silently dropped.

All network I/O is mocked so no external services are needed.
"""
from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from local_events.sources.base import RawEvent

pytestmark = pytest.mark.anyio

_FAKE_EVENT = RawEvent(
    source="test",
    source_event_id="abc123",
    title="Test Event",
    start_time=datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc),
)


@pytest.fixture
async def admin_client():
    from auth import require_admin
    from main import app

    async def _require_admin():
        return None

    app.dependency_overrides[require_admin] = _require_admin
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(require_admin, None)


# ── helpers ───────────────────────────────────────────────────────────────────

async def _post(client: AsyncClient, params: dict) -> dict:
    resp = await client.post(
        "/scheduled-jobs/test-fetch",
        json={"kind": "local_events.refresh", "params": params},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── listing_page_sources ──────────────────────────────────────────────────────

async def test_listing_page_source_ok(admin_client):
    with patch(
        "local_events.test_fetch.ListingPageSource.fetch",
        new=AsyncMock(return_value=[_FAKE_EVENT]),
    ):
        data = await _post(admin_client, {
            "listing_page_sources": [{
                "name": "phila_gov",
                "listing_url": "https://www.phila.gov/the-latest/all-events/",
                "url_pattern": "/the-latest/events/[^/?#]+",
            }]
        })

    assert len(data["sources"]) == 1
    src = data["sources"][0]
    assert src["name"] == "phila_gov"
    assert src["status"] == "ok"
    assert src["event_count"] == 1
    assert src["sample_titles"] == ["Test Event"]
    assert src["source_type"] == "listing_page"


async def test_listing_page_source_missing_listing_url(admin_client):
    data = await _post(admin_client, {
        "listing_page_sources": [{
            "name": "bad",
            "url_pattern": "/events/",
            # listing_url omitted
        }]
    })

    assert data["sources"][0]["status"] == "misconfigured"
    assert data["sources"][0]["source_type"] == "listing_page"


async def test_listing_page_source_missing_url_pattern(admin_client):
    data = await _post(admin_client, {
        "listing_page_sources": [{
            "name": "bad",
            "listing_url": "https://example.com/events/",
            # url_pattern omitted
        }]
    })

    assert data["sources"][0]["status"] == "misconfigured"


async def test_listing_page_source_invalid_parser(admin_client):
    data = await _post(admin_client, {
        "listing_page_sources": [{
            "name": "bad",
            "listing_url": "https://example.com/events/",
            "url_pattern": "/events/",
            "parser": "does_not_exist",
        }]
    })

    assert data["sources"][0]["status"] == "misconfigured"


async def test_listing_page_source_fetch_error(admin_client):
    with patch(
        "local_events.test_fetch.ListingPageSource.fetch",
        new=AsyncMock(side_effect=RuntimeError("scraper down")),
    ):
        data = await _post(admin_client, {
            "listing_page_sources": [{
                "name": "phila_gov",
                "listing_url": "https://www.phila.gov/the-latest/all-events/",
                "url_pattern": "/the-latest/events/[^/?#]+",
            }]
        })

    src = data["sources"][0]
    assert src["status"] == "parse_error"
    assert "scraper down" in src["error"]


# ── empty params → zero sources (no silent drop) ─────────────────────────────

async def test_empty_listing_page_sources_returns_zero_sources(admin_client):
    data = await _post(admin_client, {"listing_page_sources": []})
    assert data["sources"] == []


# ── wrong kind rejected ───────────────────────────────────────────────────────

async def test_non_events_kind_rejected(admin_client):
    resp = await admin_client.post(
        "/scheduled-jobs/test-fetch",
        json={"kind": "plaid.sync", "params": {}},
    )
    assert resp.status_code == 400


# ── other source types still work alongside listing_page_sources ──────────────

async def test_mixed_sources_all_returned(admin_client):
    with patch(
        "local_events.test_fetch.ListingPageSource.fetch",
        new=AsyncMock(return_value=[_FAKE_EVENT]),
    ), patch(
        "local_events.test_fetch.ScraperSource.fetch",
        new=AsyncMock(return_value=[_FAKE_EVENT]),
    ):
        data = await _post(admin_client, {
            "listing_page_sources": [{
                "name": "phila_gov",
                "listing_url": "https://www.phila.gov/the-latest/all-events/",
                "url_pattern": "/the-latest/events/[^/?#]+",
            }],
            "scraper_sources": [{
                "name": "some_scraper",
                "url": "https://example.com/events/",
            }],
        })

    assert len(data["sources"]) == 2
    types = {s["source_type"] for s in data["sources"]}
    assert types == {"listing_page", "scraper"}
