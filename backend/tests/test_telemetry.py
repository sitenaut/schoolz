import telemetry


def test_disabled_with_no_otlp_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    assert telemetry.telemetry_enabled() is False


def test_disabled_when_sdk_disabled_even_with_endpoint(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://example.invalid")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    assert telemetry.telemetry_enabled() is False


def test_enabled_with_endpoint_set(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://example.invalid")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    assert telemetry.telemetry_enabled() is True


def test_setup_is_noop_without_endpoint(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    # Should not raise, and should not touch the global providers.
    telemetry.setup_telemetry("schoolz-test")
    assert telemetry._tracer_provider is None
    assert telemetry._meter_provider is None
    assert telemetry._logger_provider is None
    telemetry.shutdown_telemetry()


def test_metric_resource_excludes_service_version(monkeypatch):
    monkeypatch.setenv("FLY_IMAGE_REF", "registry.fly.io/schoolz-api:deployment-test12345")
    trace_res = telemetry._resource("schoolz-api")
    metric_res = telemetry._metric_resource("schoolz-api")
    assert trace_res.attributes.get("service.version") == "registry.fly.io/schoolz-api:deployment-test12345"
    assert "service.version" not in metric_res.attributes


def test_metric_views_drop_unused_high_cardinality_instruments():
    from opentelemetry.sdk.metrics.view import DropAggregation
    dropped = [v._instrument_name for v in telemetry._metric_views if isinstance(v._aggregation, DropAggregation)]
    assert "http.server.request.body.size" in dropped
    assert "http.server.response.body.size" in dropped
    assert "http.client.request.duration" in dropped
