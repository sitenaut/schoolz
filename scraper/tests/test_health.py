from fastapi.testclient import TestClient

from main import app


def test_health():
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"


def test_health_disconnected(monkeypatch):
    import main
    class DummyBrowser:
        def is_connected(self):
            return False

    with TestClient(app) as client:
        monkeypatch.setitem(main._state, "browser", DummyBrowser())
        res = client.get("/health")
        assert res.status_code == 503
        assert res.json()["detail"]["browser_connected"] is False


def test_validate_target_url():
    import pytest
    from fastapi import HTTPException
    from main import validate_target_url

    # Allowed
    validate_target_url("https://www.chclc.org/calendar")
    validate_target_url("http://school.edu/events")

    # Invalid schemes -> 400
    for bad_url in ("file:///etc/passwd", "ftp://example.com", "gopher://example.com", "javascript:void(0)"):
        with pytest.raises(HTTPException) as exc_info:
            validate_target_url(bad_url)
        assert exc_info.value.status_code == 400

    # Forbidden internal/loopback hosts -> 403
    for blocked_url in (
        "http://localhost:8000",
        "http://127.0.0.1:8765",
        "http://[::1]:8765",
        "http://schoolz-api.internal:8000",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.1:8000",
        "http://192.168.1.1:80",
    ):
        with pytest.raises(HTTPException) as exc_info:
            validate_target_url(blocked_url)
        assert exc_info.value.status_code == 403


def test_require_api_key_constant_time(monkeypatch):
    import pytest
    from fastapi import HTTPException
    import main

    monkeypatch.setattr(main, "SCRAPER_API_KEY", "secret-test-key-12345")
    # Correct key passes
    main.require_api_key(x_api_key="secret-test-key-12345")

    # Wrong key raises 401
    with pytest.raises(HTTPException) as exc_info:
        main.require_api_key(x_api_key="wrong-key")
    assert exc_info.value.status_code == 401

    # Missing key raises 401
    with pytest.raises(HTTPException) as exc_info:
        main.require_api_key(x_api_key=None)
    assert exc_info.value.status_code == 401


def test_fetch_html_requires_api_key():
    with TestClient(app) as client:
        res = client.post("/fetch-html", json={"url": "https://example.com"})
        assert res.status_code == 401


def test_scraper_metric_resource_excludes_service_version(monkeypatch):
    import telemetry
    monkeypatch.setenv("FLY_IMAGE_REF", "registry.fly.io/schoolz-scraper:deployment-test123")
    trace_res = telemetry._resource("schoolz-scraper")
    metric_res = telemetry._metric_resource("schoolz-scraper")
    assert trace_res.attributes.get("service.version") == "registry.fly.io/schoolz-scraper:deployment-test123"
    assert "service.version" not in metric_res.attributes


def test_scraper_metric_views_configured():
    import telemetry
    from opentelemetry.sdk.metrics.view import DropAggregation
    dropped = [v._instrument_name for v in telemetry._metric_views if isinstance(v._aggregation, DropAggregation)]
    assert "http.server.request.size" in dropped
    assert "http.server.response.size" in dropped


def test_abort_heavy_assets_logic():
    import asyncio
    import main

    aborted = []
    continued = []

    class DummyRequest:
        def __init__(self, resource_type):
            self.resource_type = resource_type

    class DummyRoute:
        def __init__(self, resource_type):
            self.request = DummyRequest(resource_type)

        async def abort(self):
            aborted.append(self.request.resource_type)

        async def continue_(self):
            continued.append(self.request.resource_type)

    async def run_scenario():
        for r_type in ("image", "media", "font"):
            await main._abort_heavy_assets(DummyRoute(r_type))
        for r_type in ("document", "script", "xhr", "fetch"):
            await main._abort_heavy_assets(DummyRoute(r_type))

    asyncio.run(run_scenario())

    assert aborted == ["image", "media", "font"]
    assert continued == ["document", "script", "xhr", "fetch"]


