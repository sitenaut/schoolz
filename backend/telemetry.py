"""OpenTelemetry setup: traces/metrics/logs pushed via OTLP to Grafana Cloud.

No-ops entirely when OTEL_EXPORTER_OTLP_ENDPOINT isn't set - pytest and a
plain local run send nothing. See docs/OBSERVABILITY_PLAN.md Phase 2.
"""
import logging
import os
import socket

from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
from opentelemetry.metrics import set_meter_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None
_logger_provider: LoggerProvider | None = None


def telemetry_enabled() -> bool:
    return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")) and os.getenv("OTEL_SDK_DISABLED") != "true"


def _resource(service_name: str) -> Resource:
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


def setup_telemetry(service_name: str) -> None:
    global _tracer_provider, _meter_provider, _logger_provider

    if not telemetry_enabled():
        return

    resource = _resource(service_name)

    if os.getenv("OTEL_TRACES_EXPORTER") != "none":
        _tracer_provider = TracerProvider(resource=resource)
        _tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(_tracer_provider)

    _meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=30000)],
    )
    set_meter_provider(_meter_provider)

    if os.getenv("OTEL_LOGS_EXPORTER") != "none":
        _logger_provider = LoggerProvider(resource=resource)
        _logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
        set_logger_provider(_logger_provider)
        logging.getLogger().addHandler(LoggingHandler(level=logging.INFO, logger_provider=_logger_provider))

    LoggingInstrumentor().instrument(set_logging_format=False)
    HTTPXClientInstrumentor().instrument()

    try:
        SystemMetricsInstrumentor(
            config={"process.memory.usage": None, "process.cpu.utilization": None}
        ).instrument()
    except Exception:
        logging.getLogger(__name__).exception("system_metrics_instrumentation_failed")


def instrument_sqlalchemy_engine(engine) -> None:
    if not telemetry_enabled():
        return
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)


def shutdown_telemetry() -> None:
    for provider in (_tracer_provider, _meter_provider, _logger_provider):
        if provider is None:
            continue
        try:
            provider.force_flush()
        except Exception:
            pass
        try:
            provider.shutdown()
        except Exception:
            pass
