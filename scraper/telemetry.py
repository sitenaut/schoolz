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
from opentelemetry.sdk.metrics.view import (
    DropAggregation,
    ExplicitBucketHistogramAggregation,
    View,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None


def telemetry_enabled() -> bool:
    return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")) and os.getenv("OTEL_SDK_DISABLED") != "true"


def _resource(service_name: str) -> Resource:
    """Resource for traces - keeps service.version for Tempo span analysis."""
    return Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "schoolz",
            "service.version": os.getenv("FLY_IMAGE_REF", "dev"),
            "service.instance.id": os.getenv("FLY_MACHINE_ID") or socket.gethostname(),
            "deployment.environment": os.getenv("APP_ENV", "local"),
            "cloud.region": os.getenv("FLY_REGION", "local"),
        }
    )


def _metric_resource(service_name: str) -> Resource:
    """Resource for metrics - excludes service.version so Fly image deploys
    do not multiply active time series before previous versions expire.
    """
    return Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "schoolz",
            "service.instance.id": os.getenv("FLY_MACHINE_ID") or socket.gethostname(),
            "deployment.environment": os.getenv("APP_ENV", "local"),
            "cloud.region": os.getenv("FLY_REGION", "local"),
        }
    )


_metric_views = [
    # Drop unused HTTP server size histograms emitted by FastAPIInstrumentor
    View(instrument_name="http.server.request.size", aggregation=DropAggregation()),
    View(instrument_name="http.server.response.size", aggregation=DropAggregation()),
    View(instrument_name="http.server.request.body.size", aggregation=DropAggregation()),
    View(instrument_name="http.server.response.body.size", aggregation=DropAggregation()),
    # Compact page_load duration histogram to essential buckets
    View(
        instrument_name="schoolz.scraper.page_load",
        aggregation=ExplicitBucketHistogramAggregation(
            boundaries=[1.0, 3.0, 5.0, 10.0, 15.0, 30.0]
        ),
    ),
]


def setup_telemetry(service_name: str) -> None:
    global _tracer_provider, _meter_provider

    if not telemetry_enabled():
        return

    if os.getenv("OTEL_TRACES_EXPORTER") != "none":
        _tracer_provider = TracerProvider(resource=_resource(service_name))
        _tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(_tracer_provider)

    _meter_provider = MeterProvider(
        resource=_metric_resource(service_name),
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=30000)],
        views=_metric_views,
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
