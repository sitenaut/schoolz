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


async def test_fetch_paginated_falls_back_when_the_primary_scraper_fails(monkeypatch):
    # Confirmed real, 2026-10: staff_roster.scan was the only kind failing
    # during the 12h burst - schoolz's own scraper 502'd while the droplet
    # (which now implements /fetch-paginated) sat idle.
    _set_services(monkeypatch, primary=("https://primary", "pkey"), fallback=("https://droplet", "dkey"))

    calls = []

    async def fake_post_to(service_url, api_key, path, payload, timeout_s):
        calls.append((service_url, path))
        if service_url == "https://primary":
            raise _status_error(502)
        return {"pages": ["<p>1</p>"]}

    monkeypatch.setattr(scraper_client, "_post_to", fake_post_to)
    pages = await scraper_client.fetch_paginated("https://school.example/roster", ".next")
    assert pages == ["<p>1</p>"]
    assert calls == [("https://primary", "/fetch-paginated"), ("https://droplet", "/fetch-paginated")]


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



def _mock_http(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(scraper_client.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def _recorded_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(scraper_client.observability.scraper_calls_total, "add", lambda n, attrs: calls.append(attrs))
    monkeypatch.setattr(scraper_client.observability.scraper_call_seconds, "record", lambda v, attrs: None)
    return calls


async def test_each_attempt_is_counted_by_role_and_outcome(monkeypatch):
    _set_services(monkeypatch, fallback=("https://droplet", "dkey"))
    monkeypatch.setattr(scraper_client, "_BACKOFF_S", 0)
    calls = _recorded_calls(monkeypatch)

    def handler(request):
        if request.url.host == "primary":
            return httpx.Response(502)
        return httpx.Response(200, json={"html": "<p>ok</p>"})

    _mock_http(monkeypatch, handler)
    assert (await scraper_client.fetch_html("https://school.example/"))["html"] == "<p>ok</p>"
    assert [(c["scraper"], c["outcome"]) for c in calls] == (
        [("primary", "unavailable")] * scraper_client._ATTEMPTS + [("fallback", "ok")]
    )
    assert {c["endpoint"] for c in calls} == {"/fetch-html"}


async def test_a_memory_kill_moves_on_to_the_next_scraper_without_retrying(monkeypatch):
    # The same page blows the same budget every time; the droplet's is bigger.
    _set_services(monkeypatch, fallback=("https://droplet", "dkey"))
    monkeypatch.setattr(scraper_client, "_BACKOFF_S", 0)
    calls = _recorded_calls(monkeypatch)

    def handler(request):
        if request.url.host == "primary":
            return httpx.Response(502, json={"detail": "Render exceeded the 700MB memory budget and was killed"})
        return httpx.Response(200, json={"html": "<p>ok</p>"})

    _mock_http(monkeypatch, handler)
    assert (await scraper_client.fetch_html("https://school.example/"))["html"] == "<p>ok</p>"
    assert [(c["scraper"], c["outcome"]) for c in calls] == [("primary", "unavailable"), ("fallback", "ok")]


async def test_a_targets_own_refusal_is_counted_as_refused(monkeypatch):
    _set_services(monkeypatch)
    calls = _recorded_calls(monkeypatch)
    _mock_http(monkeypatch, lambda request: httpx.Response(422, json={"detail": "bad"}))
    with pytest.raises(httpx.HTTPStatusError):
        await scraper_client.fetch_html("https://school.example/")
    assert [(c["scraper"], c["outcome"]) for c in calls] == [("primary", "refused")]


async def test_check_health_asks_health_deep_and_falls_back_to_health(monkeypatch):
    _set_services(monkeypatch, fallback=("https://droplet", "dkey"), residential=("https://pi", "rkey"))
    asked = []

    def handler(request):
        asked.append(f"{request.url.host}{request.url.path}")
        if request.url.host == "primary":  # an old scraper with no /health/deep
            return httpx.Response(404 if request.url.path == "/health/deep" else 200)
        if request.url.host == "pi":
            raise httpx.ConnectError("down")
        return httpx.Response(503 if request.url.path == "/health/deep" else 200)

    _mock_http(monkeypatch, handler)
    assert await scraper_client.check_health() == {"primary": True, "fallback": False, "residential": False}
    assert asked == ["primary/health/deep", "primary/health", "droplet/health/deep", "pi/health/deep"]


async def test_fetch_raw_bytes_asks_for_request_mode_and_skips_unusable_answers(monkeypatch):
    import base64
    import json

    _set_services(monkeypatch, fallback=("https://droplet", "dkey"), residential=("https://pi", "rkey"))
    _recorded_calls(monkeypatch)
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        if request.url.host == "primary":  # the site's own refusal, passed through
            return httpx.Response(200, json={"status": 403, "body_base64": "PGh0bWw+"})
        if request.url.host == "droplet":  # an older scraper: text only
            return httpx.Response(200, json={"body": "%PDF mangled"})
        return httpx.Response(200, json={"status": 200, "body_base64": base64.b64encode(b"%PDF-1.4").decode()})

    _mock_http(monkeypatch, handler)
    assert await scraper_client.fetch_raw_bytes("https://school.example/staff.pdf") == b"%PDF-1.4"
    assert {b["via"] for b in bodies} == {"request"}


async def test_fetch_raw_bytes_says_what_each_scraper_answered(monkeypatch):
    _set_services(monkeypatch)
    _recorded_calls(monkeypatch)
    _mock_http(monkeypatch, lambda request: httpx.Response(200, json={"status": 404}))
    with pytest.raises(RuntimeError, match="primary: HTTP 404"):
        await scraper_client.fetch_raw_bytes("https://school.example/staff.pdf")


@pytest.mark.anyio
async def test_fetch_html_sends_stealth(monkeypatch):
    """No stealth choice unless the caller makes one (prerender does)."""
    sent = []

    async def fake_post(path, payload, timeout_s):
        sent.append(payload)
        return {"html": "<html></html>"}

    monkeypatch.setattr(scraper_client, "_post_with_fallback", fake_post)
    await scraper_client.fetch_html("https://example.org")
    await scraper_client.fetch_html("https://example.org", stealth=False)
    assert [p["stealth"] for p in sent] == [None, False]


@pytest.mark.anyio
async def test_prerender_renders_without_stealth(monkeypatch):
    import services.prerender as prerender

    seen = {}

    async def fake_fetch_html(url, **kw):
        seen.update(kw)
        return {"html": "<html>ok</html>"}

    async def fake_store(path, html):
        return None

    monkeypatch.setattr(prerender.scraper_client, "fetch_html", fake_fetch_html)
    monkeypatch.setattr(prerender, "_store", fake_store)
    await prerender._render("/privacy")
    assert seen["stealth"] is False


def test_primary_renders_without_stealth_unless_asked(monkeypatch):
    """The primary ran without playwright-stealth until it became
    playwright-scraper (stealth on by default); the fallbacks keep theirs."""
    _set_services(monkeypatch, primary=("http://p", "k"), fallback=("http://f", "k"), residential=("http://r", "k"))
    unset = {"url": "u", "stealth": None}
    assert scraper_client._with_stealth("http://p", unset) == {"url": "u", "stealth": False}
    assert scraper_client._with_stealth("http://f", unset) == {"url": "u"}
    assert scraper_client._with_stealth("http://r", {"url": "u", "stealth": True}) == {"url": "u", "stealth": True}
    assert scraper_client._with_stealth("http://p", {"url": "u"}) == {"url": "u"}


class _Resp:
    def __init__(self, status: int, content: bytes = b"", url: str = "https://site/x"):
        self.status_code, self.content, self.url = status, content, url
        self.request = httpx.Request("GET", url)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=self.request, response=self)


def _fake_client(monkeypatch, resp):
    class Client:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, url):
            return resp

    monkeypatch.setattr(scraper_client.httpx, "AsyncClient", Client)


async def test_get_bytes_reads_a_403_through_the_scrapers(monkeypatch):
    _fake_client(monkeypatch, _Resp(403))

    async def fake_raw(url, timeout_ms=45_000):
        return b"%PDF-via-scraper"

    monkeypatch.setattr(scraper_client, "fetch_raw_bytes", fake_raw)
    assert await scraper_client.get_bytes("https://site/x.pdf") == ("https://site/x.pdf", b"%PDF-via-scraper")


async def test_get_bytes_keeps_a_plain_answer_and_raises_other_errors(monkeypatch):
    _fake_client(monkeypatch, _Resp(200, b"%PDF-plain", "https://site/final.pdf"))
    assert await scraper_client.get_bytes("https://site/x.pdf") == ("https://site/final.pdf", b"%PDF-plain")
    _fake_client(monkeypatch, _Resp(404))
    with pytest.raises(httpx.HTTPStatusError):
        await scraper_client.get_bytes("https://site/x.pdf")


async def test_fetch_html_from_any_moves_past_a_bot_wall_page(monkeypatch):
    """A datacenter scraper gets the challenge page; the next one gets the real page."""
    _set_services(monkeypatch, primary=("http://p", "k"), fallback=("http://f", "k"), residential=("http://r", "k"))
    pages = {"http://p": "<html>challenge</html>", "http://f": "<html>challenge</html>", "http://r": "<a href='cal.pdf'>"}
    asked = []

    async def fake_post_to(service_url, api_key, path, payload, timeout_s):
        asked.append(service_url)
        return {"html": pages[service_url]}

    monkeypatch.setattr(scraper_client, "_post_to", fake_post_to)
    html = await scraper_client.fetch_html_from_any("https://site/", accept=lambda h: ".pdf" in h)
    assert html == pages["http://r"] and asked == ["http://p", "http://f", "http://r"]
    with pytest.raises(scraper_client.ScraperRefused):
        await scraper_client.fetch_html_from_any("https://site/", accept=lambda h: False)


def test_a_broken_certificate_is_not_retried():
    """Every scraper fails a bad certificate the same way; retrying it cost
    Beck's roster scan ~12 minutes and then the scan."""
    req = httpx.Request("POST", "http://scraper/fetch-html")
    resp = httpx.Response(502, request=req, text='{"detail":"net::ERR_CERT_COMMON_NAME_INVALID at https://www2.eboard.com/"}')
    assert not _is_retryable(httpx.HTTPStatusError("bad gateway", request=req, response=resp))


async def test_a_dead_nurse_link_does_not_fail_the_roster(monkeypatch):
    from services import role_pages

    home = '<a href="/nurse">Nurse</a><a href="https://broken.example/board">Nurse eBoard</a>'
    nurse = "<main><p>School Nurse Jane Doe 856-555-0100</p></main>"

    async def fake_fetch_html(url, **kw):
        if "broken" in url:
            raise RuntimeError("certificate")
        return {"html": home if url.endswith("org/") else nurse}

    monkeypatch.setattr(role_pages.scraper_client, "fetch_html", fake_fetch_html)
    people = await role_pages.fetch_role_staff_scraped("https://school.example.org")
    assert [p["full_name"] for p in people] == ["Jane Doe"]
