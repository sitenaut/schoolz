from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

import telemetry


def _provider(ratio: float) -> tuple[TracerProvider, InMemorySpanExporter]:
    exported = InMemorySpanExporter()
    provider = TracerProvider(sampler=telemetry._KeepJobRuns(ratio))
    provider.add_span_processor(SimpleSpanProcessor(exported))
    return provider, exported


def _browser_parent(sampled: bool):
    """The context a request carrying Faro's traceparent starts from."""
    flags = TraceFlags(TraceFlags.SAMPLED if sampled else TraceFlags.DEFAULT)
    ctx = SpanContext(trace_id=0x5CE0F00D, span_id=0xB0A7, is_remote=True, trace_flags=flags)
    return trace.set_span_in_context(NonRecordingSpan(ctx))


def _names(exported: InMemorySpanExporter) -> list[str]:
    return [s.name for s in exported.get_finished_spans()]


def test_a_job_run_is_always_kept_with_everything_under_it():
    provider, exported = _provider(0.0)
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("job.run"), tracer.start_as_current_span("SELECT"):
        pass
    assert _names(exported) == ["SELECT", "job.run"]


def test_a_trace_of_its_own_is_kept_at_the_ratio():
    provider, exported = _provider(0.0)
    with provider.get_tracer("test").start_as_current_span("GET /prerender"):
        pass
    assert _names(exported) == []

    provider, exported = _provider(1.0)
    with provider.get_tracer("test").start_as_current_span("GET /prerender"):
        pass
    assert _names(exported) == ["GET /prerender"]


def test_a_browser_request_follows_the_browser_decision():
    provider, exported = _provider(0.0)
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("GET /schools", context=_browser_parent(sampled=True)):
        pass
    with tracer.start_as_current_span("GET /calendar", context=_browser_parent(sampled=False)):
        pass
    assert _names(exported) == ["GET /schools"]


def test_an_otel_traces_sampler_secret_wins(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "parentbased_always_on")
    assert telemetry._sampler() is None  # the SDK reads the variable itself
    monkeypatch.delenv("OTEL_TRACES_SAMPLER")
    assert isinstance(telemetry._sampler(), telemetry._KeepJobRuns)


def _one_request(ratio: float) -> tuple[list[dict], list[str]]:
    app = FastAPI()

    @app.get("/things/{thing_id}")
    def thing(thing_id: str):
        return {}

    provider, exported = _provider(ratio)
    reader = InMemoryMetricReader()
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider, meter_provider=MeterProvider(metric_readers=[reader]))
    TestClient(app).get("/things/42")
    points = [
        dict(p.attributes)
        for rm in reader.get_metrics_data().resource_metrics
        for sm in rm.scope_metrics
        for m in sm.metrics
        if m.name in ("http.server.request.duration", "http.server.duration")
        for p in m.data.data_points
    ]
    return points, _names(exported)


def test_dropping_a_trace_leaves_the_request_metric_unchanged():
    """The SLOs and route alerts read the duration histogram by route and
    status (http.route and http.response.status_code under prod's
    OTEL_SEMCONV_STABILITY_OPT_IN=http). An unsampled request must record the
    same labels as a sampled one."""
    kept, kept_spans = _one_request(1.0)
    dropped, dropped_spans = _one_request(0.0)
    assert kept_spans and not dropped_spans
    assert len(kept) == 1 and dropped == kept
    assert "/things/{thing_id}" in kept[0].values() and 200 in kept[0].values()
