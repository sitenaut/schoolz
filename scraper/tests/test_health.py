from fastapi.testclient import TestClient

from main import app


def test_health():
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"


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
