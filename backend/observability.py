"""Custom OTel instruments, defined once at import via a proxy meter - this
works even when telemetry.setup_telemetry() runs later (or never, e.g.
pytest), because `metrics.get_meter` returns a no-op meter until a real
MeterProvider is registered, then the SDK swaps the implementation under it.

Keep attributes low-cardinality: no ids, slugs, or URLs (those belong in
spans/logs, not metrics). See docs/OBSERVABILITY_PLAN.md Phase 2e.
"""
from opentelemetry import metrics

_meter = metrics.get_meter("schoolz")

_DURATION_BUCKETS = (1, 5, 15, 30, 60, 120, 300, 600, 1200, 1800)

job_runs_total = _meter.create_counter(
    "schoolz.job.runs",
    description="Scheduled job runs, by kind and outcome.",
)
job_duration_seconds = _meter.create_histogram(
    "schoolz.job.duration",
    unit="s",
    description="Scheduled job handler duration.",
)
job_queue_wait_seconds = _meter.create_histogram(
    "schoolz.job.queue_wait",
    unit="s",
    description="Time a job spent waiting on the JOB_CONCURRENCY semaphore.",
)
job_in_flight = _meter.create_up_down_counter(
    "schoolz.job.in_flight",
    description="Jobs currently executing.",
)

scraper_requests_total = _meter.create_counter(
    "schoolz.scraper.requests",
    description="Requests to the scraper service, by endpoint and outcome.",
)
scraper_duration_seconds = _meter.create_histogram(
    "schoolz.scraper.duration",
    unit="s",
    description="Scraper request duration.",
)

llm_calls_total = _meter.create_counter(
    "schoolz.llm.calls",
    description="Anthropic API calls, by model/purpose/stop_reason.",
)
llm_tokens_total = _meter.create_counter(
    "schoolz.llm.tokens",
    description="Anthropic API token usage, by model/purpose/direction.",
)
llm_duration_seconds = _meter.create_histogram(
    "schoolz.llm.duration",
    unit="s",
    description="Anthropic API call wall time.",
)

parse_issues_total = _meter.create_counter(
    "schoolz.parse.issues",
    description="Non-fatal parse problems inside an otherwise-successful scan.",
)

cold_start_requests_total = _meter.create_counter(
    "schoolz.cold_start.requests",
    description="First request handled after a Fly machine start.",
)
