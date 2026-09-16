import logging
import os
import sys

from pythonjsonlogger import jsonlogger

_NOISY_LOGGERS = (
    "uvicorn.access",
    "sqlalchemy.engine",
    "httpx",
    "httpcore",
)


def setup_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    # otelTraceID/otelSpanID are put on every LogRecord by
    # LoggingInstrumentor (telemetry.py), but a field that isn't named in
    # `fmt` never reaches the emitted line - so until this was added, a log
    # in Loki could not be pivoted to its trace in Tempo. That cost real
    # time on 2026-09-15: a browser session stalling 25-42s and a set of
    # backend request logs existed in the same window with nothing to join
    # them on. Missing on a record (nothing instrumented locally) just
    # serialises as null, which is why this is safe to always request.
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s %(otelTraceID)s %(otelSpanID)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        rename_fields={
            "levelname": "levelname",
            "asctime": "ts",
            "otelTraceID": "trace_id",
            "otelSpanID": "span_id",
        },
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)
