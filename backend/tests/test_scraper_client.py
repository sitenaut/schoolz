import httpx
import pytest

import scraper_client
from scraper_client import ScraperNotConfigured, _is_retryable, _services

pytestmark = pytest.mark.anyio


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://scraper/fetch-html")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_scraper_502_is_retried():
    # The scraper answers 502 whenever the *school's* site fails to load in
    # time - transient, so worth another go.
    assert _is_retryable(_status_error(502))


def test_gateway_timeouts_are_retried():
    assert _is_retryable(_status_error(503))
    assert _is_retryable(_status_error(504))


def test_client_side_timeout_is_retried():
    assert _is_retryable(httpx.ReadTimeout("slow", request=httpx.Request("POST", "http://scraper")))
    assert _is_retryable(httpx.ConnectError("refused", request=httpx.Request("POST", "http://scraper")))


def test_auth_and_client_errors_are_not_retried():
    assert not _is_retryable(_status_error(401))
    assert not _is_retryable(_status_error(404))
    assert not _is_retryable(_status_error(422))


def test_unrelated_exceptions_are_not_retried():
    assert not _is_retryable(ValueError("bad json"))


def _set_services(monkeypatch, primary=("https://primary", "pkey"), fallback=("", ""), residential=("", "")):
    monkeypatch.setattr(scraper_client, "SCRAPER_URL", primary[0])
    monkeypatch.setattr(scraper_client, "SCRAPER_API_KEY", primary[1])
    monkeypatch.setattr(scraper_client, "_FALLBACK_URL", fallback[0])
    monkeypatch.setattr(scraper_client, "_FALLBACK_API_KEY", fallback[1])
    monkeypatch.setattr(scraper_client, "_RESIDENTIAL_URL", residential[0])
    monkeypatch.setattr(scraper_client, "_RESIDENTIAL_API_KEY", residential[1])


def test_services_skips_unconfigured_entries(monkeypatch):
    _set_services(monkeypatch, primary=("https://primary", "pkey"), fallback=("https://droplet", "dkey"))
    assert _services() == [("https://primary", "pkey"), ("https://droplet", "dkey")]


def test_services_includes_all_three_when_configured(monkeypatch):
    _set_services(
        monkeypatch,
        primary=("https://primary", "pkey"),
        fallback=("https://droplet", "dkey"),
        residential=("https://residential", "rkey"),
    )
    assert _services() == [("https://primary", "pkey"), ("https://droplet", "dkey"), ("https://residential", "rkey")]


async def test_post_with_fallback_falls_through_on_retryable_failure(monkeypatch):
    # Confirmed real, 2026-09-29: schoolz's own scraper wedged (every call
    # 502s even after a restart) - the droplet must still answer.
    _set_services(monkeypatch, primary=("https://primary", "pkey"), fallback=("https://droplet", "dkey"))

    calls = []

    async def fake_post_to(service_url, api_key, path, payload, timeout_s):
        calls.append(service_url)
        if service_url == "https://primary":
            raise _status_error(502)
        return {"html": "<p>ok</p>"}

    monkeypatch.setattr(scraper_client, "_post_to", fake_post_to)
    result = await scraper_client._post_with_fallback("/fetch-html", {}, timeout_s=5)
    assert result == {"html": "<p>ok</p>"}
    assert calls == ["https://primary", "https://droplet"]


async def test_post_with_fallback_does_not_mask_nonretryable_errors(monkeypatch):
    _set_services(monkeypatch, primary=("https://primary", "pkey"), fallback=("https://droplet", "dkey"))

    calls = []

    async def fake_post_to(service_url, api_key, path, payload, timeout_s):
        calls.append(service_url)
        raise _status_error(422)  # e.g. the school's own site returned real 4xx content

    monkeypatch.setattr(scraper_client, "_post_to", fake_post_to)
    with pytest.raises(httpx.HTTPStatusError):
        await scraper_client._post_with_fallback("/fetch-html", {}, timeout_s=5)
    # Never tries the droplet for a non-retryable failure - it would hit
    # the same non-retryable response for a real error on the target site.
    assert calls == ["https://primary"]


async def test_post_with_fallback_raises_not_configured_with_no_services(monkeypatch):
    _set_services(monkeypatch, primary=("", ""))
    with pytest.raises(ScraperNotConfigured):
        await scraper_client._post_with_fallback("/fetch-html", {}, timeout_s=5)


async def test_fetch_paginated_only_ever_uses_the_primary_scraper(monkeypatch):
    # No droplet equivalent for /fetch-paginated - never falls through.
    _set_services(monkeypatch, primary=("https://primary", "pkey"), fallback=("https://droplet", "dkey"))

    calls = []

    async def fake_post_to(service_url, api_key, path, payload, timeout_s):
        calls.append(service_url)
        return {"pages": ["<p>1</p>"]}

    monkeypatch.setattr(scraper_client, "_post_to", fake_post_to)
    pages = await scraper_client.fetch_paginated("https://school.example/roster", ".next")
    assert pages == ["<p>1</p>"]
    assert calls == ["https://primary"]


async def test_fetch_html_passes_block_assets(monkeypatch):
    _set_services(monkeypatch, primary=("https://primary", "pkey"))
    received_payloads = []

    async def fake_post_to(service_url, api_key, path, payload, timeout_s):
        received_payloads.append(payload)
        return {"html": "<p>ok</p>"}

    monkeypatch.setattr(scraper_client, "_post_to", fake_post_to)
    await scraper_client.fetch_html("https://school.example/page", block_assets=True)
    assert received_payloads[0]["block_assets"] is True

    await scraper_client.fetch_html("https://school.example/page")
    assert received_payloads[1]["block_assets"] is False


async def test_fetch_paginated_passes_block_assets(monkeypatch):
    _set_services(monkeypatch, primary=("https://primary", "pkey"))
    received_payloads = []

    async def fake_post_to(service_url, api_key, path, payload, timeout_s):
        received_payloads.append(payload)
        return {"pages": ["<p>1</p>"]}

    monkeypatch.setattr(scraper_client, "_post_to", fake_post_to)
    await scraper_client.fetch_paginated("https://school.example/roster", ".next", block_assets=True)
    assert received_payloads[0]["block_assets"] is True

    await scraper_client.fetch_paginated("https://school.example/roster", ".next")
    assert received_payloads[1]["block_assets"] is False

