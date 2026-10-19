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

# Scrapers measured from this side (scraper_client.py), so the dashboards
# and alerts work whichever scraper image runs behind each URL: the Fly
# scraper, the droplet and the Pi all run playwright-scraper, which reports
# to its own Grafana folder, not under schoolz. `scraper` is the role
# (primary | fallback | residential), never a host or a target URL.
scraper_calls_total = _meter.create_counter(
    "schoolz.scraper_client.calls",
    description="Calls to a scraper, per attempt, by scraper role, endpoint and outcome "
                "(ok | unavailable: retryable, the scraper's fault | refused: the target's answer).",
)
scraper_call_seconds = _meter.create_histogram(
    "schoolz.scraper_client.duration",
    unit="s",
    description="How long one scraper call took, by scraper role and outcome.",
)
scraper_healthy = _meter.create_gauge(
    "schoolz.scraper.healthy",
    description="1 if the scraper's /health/deep answered 200 at the scheduler's last check "
                "(every 5 minutes), else 0. By scraper role.",
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

translation_items_total = _meter.create_counter(
    "schoolz.translation.items",
    description="Content items that needed a translation, by lang and reason (missing / stale / reused).",
)

parse_issues_total = _meter.create_counter(
    "schoolz.parse.issues",
    description="Non-fatal parse problems inside an otherwise-successful scan.",
)

cold_start_requests_total = _meter.create_counter(
    "schoolz.cold_start.requests",
    description="First request handled after a Fly machine start.",
)

csp_violations_total = _meter.create_counter(
    "schoolz.csp.violations",
    description="Content-Security-Policy violation reports received, by directive (routers/csp_report.py).",
)

user_created_total = _meter.create_counter(
    "schoolz.user.created",
    description="New user rows created, by source (local_register / supabase_autoprovision).",
)


def record_translation_items(lang: str, missing: int, stale: int, reused: int) -> None:
    """Why translation spend happens: `missing` is new text, `stale` is an item
    whose English changed after it was translated (churn), `reused` was copied
    from identical text already translated (no model call)."""
    for reason, n in (("missing", missing), ("stale", stale), ("reused", reused)):
        if n > 0:
            translation_items_total.add(n, {"lang": lang, "reason": reason})


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
