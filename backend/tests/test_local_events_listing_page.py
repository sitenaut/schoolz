"""Unit tests for events.sources.listing_page.ListingPageSource.

The scraper service and detail-page fetches are mocked so these run without
any network access or a running scraper container.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from local_events.sources.listing_page import ListingPageSource

_BASE = "https://www.phila.gov"

_LISTING_HTML = """
<html><body>
  <a href="/the-latest/events/jazz-fest/">Jazz Festival</a>
  <a href="/the-latest/events/art-show/">Art Show</a>
  <a href="/the-latest/events/art-show/">Art Show duplicate</a>
  <a href="/about/">About (should not match)</a>
  <a href="https://external.example.com/event/">External (should not match)</a>
</body></html>
"""

_DETAIL_JSONLD = """
<html><head>
<script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@type": "Event",
  "name": "{title}",
  "startDate": "2026-08-01T10:00:00-04:00",
  "endDate": "2026-08-01T12:00:00-04:00",
  "location": {{"@type": "Place", "name": "City Hall", "address": "1 Centre Square, Philadelphia, PA 19102"}},
  "url": "{url}"
}}
</script>
</head><body></body></html>
"""


def _make_source(**kwargs) -> ListingPageSource:
    defaults = dict(
        name="phila_gov",
        listing_url=f"{_BASE}/the-latest/all-events/",
        url_pattern=r"/the-latest/events/[^/?#]+",
    )
    return ListingPageSource(**{**defaults, **kwargs})


# ── list_urls ────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_list_urls_returns_matched_deduplicated_links():
    source = _make_source()
    with patch(
        "local_events.sources.listing_page.fetch_rendered_html",
        new=AsyncMock(return_value=(_LISTING_HTML, f"{_BASE}/the-latest/all-events/")),
    ):
        urls = await source.list_urls()

    assert len(urls) == 2
    assert f"{_BASE}/the-latest/events/jazz-fest" in urls
    assert f"{_BASE}/the-latest/events/art-show" in urls


@pytest.mark.anyio
async def test_list_urls_excludes_non_matching_hrefs():
    source = _make_source()
    with patch(
        "local_events.sources.listing_page.fetch_rendered_html",
        new=AsyncMock(return_value=(_LISTING_HTML, f"{_BASE}/the-latest/all-events/")),
    ):
        urls = await source.list_urls()

    assert not any("/about/" in u for u in urls)
    assert not any("external.example.com" in u for u in urls)


@pytest.mark.anyio
async def test_list_urls_respects_max_pages():
    source = _make_source(max_pages=1)
    with patch(
        "local_events.sources.listing_page.fetch_rendered_html",
        new=AsyncMock(return_value=(_LISTING_HTML, f"{_BASE}/the-latest/all-events/")),
    ):
        urls = await source.list_urls()

    assert len(urls) == 1


@pytest.mark.anyio
async def test_list_urls_returns_empty_on_fetch_error():
    source = _make_source()
    with patch(
        "local_events.sources.listing_page.fetch_rendered_html",
        new=AsyncMock(side_effect=RuntimeError("scraper down")),
    ):
        urls = await source.list_urls()

    assert urls == []


# ── fetch (full pipeline) ────────────────────────────────────────────────────

def _detail_html(title: str, url: str) -> str:
    return _DETAIL_JSONLD.format(title=title, url=url)


@pytest.mark.anyio
async def test_fetch_extracts_events_via_jsonld():
    jazz_url = f"{_BASE}/the-latest/events/jazz-fest"
    art_url = f"{_BASE}/the-latest/events/art-show"

    async def _fake_render(url, **_kwargs):
        if "all-events" in url:
            return _LISTING_HTML, url
        if "jazz-fest" in url:
            return _detail_html("Jazz Festival", jazz_url), url
        return _detail_html("Art Show", art_url), url

    source = _make_source()
    with patch("local_events.sources.listing_page.fetch_rendered_html", new=AsyncMock(side_effect=_fake_render)):
        events = await source.fetch()

    assert len(events) == 2
    titles = {e.title for e in events}
    assert titles == {"Jazz Festival", "Art Show"}


@pytest.mark.anyio
async def test_fetch_skips_detail_pages_with_no_jsonld():
    no_jsonld_html = "<html><body><h1>Event</h1></body></html>"

    async def _fake_render(url, **_kwargs):
        if "all-events" in url:
            return _LISTING_HTML, url
        return no_jsonld_html, url

    source = _make_source()
    with patch("local_events.sources.listing_page.fetch_rendered_html", new=AsyncMock(side_effect=_fake_render)):
        events = await source.fetch()

    assert events == []


@pytest.mark.anyio
async def test_fetch_skips_failed_detail_pages():
    jazz_url = f"{_BASE}/the-latest/events/jazz-fest"

    async def _fake_render(url, **_kwargs):
        if "all-events" in url:
            return _LISTING_HTML, url
        if "jazz-fest" in url:
            return _detail_html("Jazz Festival", jazz_url), url
        raise RuntimeError("timeout")

    source = _make_source()
    with patch("local_events.sources.listing_page.fetch_rendered_html", new=AsyncMock(side_effect=_fake_render)):
        events = await source.fetch()

    assert len(events) == 1
    assert events[0].title == "Jazz Festival"


@pytest.mark.anyio
async def test_fetch_propagates_default_categories():
    jazz_url = f"{_BASE}/the-latest/events/jazz-fest"

    async def _fake_render(url, **_kwargs):
        if "all-events" in url:
            # Only one matching link so we get one event.
            html = f'<html><body><a href="/the-latest/events/jazz-fest/">Jazz</a></body></html>'
            return html, url
        return _detail_html("Jazz Festival", jazz_url), url

    source = _make_source(default_categories=["philadelphia", "municipal"])
    with patch("local_events.sources.listing_page.fetch_rendered_html", new=AsyncMock(side_effect=_fake_render)):
        events = await source.fetch()

    assert events[0].default_categories == ["philadelphia", "municipal"]


# ── constructor validation ────────────────────────────────────────────────────

def test_unknown_parser_raises():
    with pytest.raises(ValueError, match="unknown detail parser"):
        _make_source(parser_name="does_not_exist")


def test_valid_parser_name_accepted():
    src = _make_source(parser_name="macaronikid")
    assert src._parser is not None


def test_max_pages_clamped():
    assert _make_source(max_pages=0).max_pages == 1
    assert _make_source(max_pages=9999).max_pages == 500


def test_concurrency_clamped():
    assert _make_source(concurrency=0).concurrency == 1
    assert _make_source(concurrency=999).concurrency == 16
