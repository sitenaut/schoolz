"""OpenTelemetry setup for the scraper service - trimmed copy of
backend/telemetry.py's pattern (no shared import: the scraper is standalone
on purpose, see CLAUDE.md's Scraper section). No-ops entirely unless
OTEL_EXPORTER_OTLP_ENDPOINT is set. See docs/OBSERVABILITY_PLAN.md Phase 5.
"""
import logging
import os
import socket

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.metrics import set_meter_provider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None


def telemetry_enabled() -> bool:
    return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")) and os.getenv("OTEL_SDK_DISABLED") != "true"


def setup_telemetry(service_name: str) -> None:
    global _tracer_provider, _meter_provider

    if not telemetry_enabled():
        return

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "schoolz",
            "service.version": os.getenv("FLY_IMAGE_REF", "dev"),
            "service.instance.id": os.getenv("FLY_MACHINE_ID") or socket.gethostname(),
            "deployment.environment": os.getenv("APP_ENV", "local"),
            "cloud.region": os.getenv("FLY_REGION", "local"),
        }
    )

    if os.getenv("OTEL_TRACES_EXPORTER") != "none":
        _tracer_provider = TracerProvider(resource=resource)
        _tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(_tracer_provider)

    _meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=30000)],
    )
    set_meter_provider(_meter_provider)


def shutdown_telemetry() -> None:
    for provider in (_tracer_provider, _meter_provider):
        if provider is None:
            continue
        try:
            provider.force_flush()
        except Exception:
            logging.getLogger(__name__).exception("telemetry_flush_failed")
        try:
            provider.shutdown()
        except Exception:
            logging.getLogger(__name__).exception("telemetry_shutdown_failed")
