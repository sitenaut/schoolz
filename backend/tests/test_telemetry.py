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
