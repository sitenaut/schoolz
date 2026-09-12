from opentelemetry import metrics

_meter = metrics.get_meter("schoolz-scraper")

# host, not the full URL - about 40 school hosts is fine cardinality.
page_load_seconds = _meter.create_histogram(
    "schoolz.scraper.page_load",
    unit="s",
    description="page.goto + wait_for_selector wall time, by target host and outcome.",
)
pages_open = _meter.create_up_down_counter(
    "schoolz.scraper.pages_open",
    description="Browser pages/contexts currently open.",
)
