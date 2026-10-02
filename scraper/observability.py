from opentelemetry import metrics

_meter = metrics.get_meter("schoolz-scraper")

# Only outcome (ok/error) - host is deliberately omitted from metrics to avoid
# multiplying histogram buckets across 80+ school domains (causes 3k+ active series).
# Host/URL details live in OTel traces (spans) and Loki logs at zero time-series cost.
page_load_seconds = _meter.create_histogram(
    "schoolz.scraper.page_load",
    unit="s",
    description="page.goto + wait_for_selector wall time, by outcome.",
)
pages_open = _meter.create_up_down_counter(
    "schoolz.scraper.pages_open",
    description="Browser pages/contexts currently open.",
)
