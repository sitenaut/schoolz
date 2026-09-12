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

# NOTE: there are deliberately no scraper instruments here. The scraper
# service measures its own work at the source (schoolz.scraper.page_load /
# schoolz.scraper.pages_open in scraper/observability.py), with the host and
# outcome attributes that only it can see. A backend-side duplicate was
# declared here originally and never recorded by anything - dashboards
# should query the scraper service's own metrics instead.

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


def record_llm_call(purpose: str, model: str, response, duration_s: float) -> None:
    """Records one Anthropic call's outcome, latency and token usage.

    Every `messages.create` in this codebase goes through here, which is
    what makes "what did the LLM cost us last month, and which job spent
    it" answerable at all - token counts are the only usage signal the API
    gives back, and they're on the response object, so nothing else can
    reconstruct them after the fact.

    `stop_reason` is carried deliberately: "max_tokens" means a reply was
    truncated mid-structure, which has silently produced empty extractions
    before (see CLAUDE.md's max_tokens incident) and is alerted on.

    Attributes stay low-cardinality on purpose - purpose and model are both
    small fixed sets. Never add a school, url or newsletter id here.
    """
    attrs = {"purpose": purpose, "model": model}
    llm_calls_total.add(1, {**attrs, "stop_reason": getattr(response, "stop_reason", None) or "unknown"})
    llm_duration_seconds.record(duration_s, attrs)

    usage = getattr(response, "usage", None)
    if usage is None:
        return
    for direction, value in (
        ("input", getattr(usage, "input_tokens", 0)),
        ("output", getattr(usage, "output_tokens", 0)),
        # Cache reads/writes are billed at different rates than plain input
        # tokens, so they're separate directions rather than folded in -
        # a cost panel that lumped them together would overstate spend.
        ("cache_read", getattr(usage, "cache_read_input_tokens", 0)),
        ("cache_write", getattr(usage, "cache_creation_input_tokens", 0)),
    ):
        if value:
            llm_tokens_total.add(int(value), {**attrs, "direction": direction})


scheduler_reconciles_total = _meter.create_counter(
    "schoolz.scheduler.reconciles",
    description="Scheduler reconcile ticks - the process's heartbeat.",
)
