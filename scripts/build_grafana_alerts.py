#!/usr/bin/env python3
"""Generates Grafana-managed alert rules into grafana/cloud-dashboards/alerts.json.

The provisioning API's rule shape is verbose and repetitive (every rule
carries a query stage plus reduce and threshold stages), so the thresholds
live here as a few lines each and the JSON is generated.

Every rule carries the same four routing labels, and the notification
policy (scripts/grafana_sync.py) routes on `tier` alone:

    tier       page    someone is being failed right now -> IRM, important
               ticket  real, but it can wait for daylight -> IRM, default
               info    a trigger worth knowing, never an interruption -> email
    kind       slo      an error budget is burning
               symptom  a user- or data-visible failure with no SLO behind it
               cause    explains a symptom; rarely actionable on its own
               event    something happened (a signup), nothing is wrong
    component  api | prerender | scheduler | scans | scraper | llm | auth |
               database | alexa | growth
    severity   critical | warning | info (derived from tier; kept because
               Grafana's own UI colours by it)

The rule of thumb when adding one: if nobody would do anything different at
3 AM, it is not `page`; if nobody would do anything different at all, it is
`info`. Causes default to `info` because the symptom they explain already
has its own alert - two notifications for one problem trains you to ignore
both.

Every rule is namespace-filtered to schoolz - the Grafana Cloud stack is
shared with billz, and an unfiltered rule would page on billz's traffic.

Run: python3 scripts/build_grafana_alerts.py
"""
import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "grafana" / "cloud-dashboards" / "alerts.json"

FOLDER = "schoolz"
NS = 'service_namespace="schoolz"'
ERRORED = 'status="error"'
TRUNCATED = 'stop_reason="max_tokens"'
WARNED = 'status="warning"'
FINISHED = 'status=~"success|warning"'
NOT_SKIPPED = 'status!="skipped"'
SERVER_ERROR = 'http_response_status_code=~"5.."'
POOL_USED = 'state="used"'
FARO = '{app_name="schoolz-faro"}'

SEVERITY = {"page": "critical", "ticket": "warning", "info": "info"}
# Evaluation interval per group. Pages are checked every minute; the SQL
# group is slow on purpose - its datasource is capped at 2 connections on a
# pooler the app shares.
GROUPS = {
    "schoolz-page": "1m",
    "schoolz-ticket": "5m",
    "schoolz-info": "5m",
    "schoolz-sql": "15m",
}

# Machine memory per service (backend/fly.toml). The process metric has no
# limit series to divide by, so the limits are repeated here.
MEMORY_LIMIT_MB = {"schoolz-api": 512, "schoolz-scheduler": 1024}

ALEXA_FUNCTION = "ask-schoolhelper-default-default-1791156946239"


def sel(*extra: str) -> str:
    """PromQL selector, always namespace-filtered (stack shared with billz)."""
    return "{" + ", ".join([NS, *extra]) + "}"


def _prom(ref: str, expr: str, range_s: int) -> dict:
    return {
        "refId": ref,
        "relativeTimeRange": {"from": range_s, "to": 0},
        "datasourceUid": "${DS_METRICS}",
        "model": {"refId": ref, "expr": expr, "instant": True, "editorMode": "code"},
    }


def _loki(ref: str, expr: str, range_s: int) -> dict:
    return {
        "refId": ref,
        "relativeTimeRange": {"from": range_s, "to": 0},
        "datasourceUid": "${DS_LOGS}",
        "model": {"refId": ref, "expr": expr, "queryType": "instant", "editorMode": "code"},
    }


def _sql(ref: str, sql: str, range_s: int) -> dict:
    return {
        "refId": ref,
        "relativeTimeRange": {"from": range_s, "to": 0},
        "datasourceUid": "${DS_SQL}",
        "model": {"refId": ref, "rawSql": sql, "rawQuery": True, "format": "table", "editorMode": "code"},
    }


def _cloudwatch(ref: str, metric: str, range_s: int) -> dict:
    return {
        "refId": ref,
        "relativeTimeRange": {"from": range_s, "to": 0},
        "datasourceUid": "${DS_CLOUDWATCH}",
        "model": {
            "refId": ref, "queryMode": "Metrics", "metricQueryType": 0, "metricEditorMode": 0,
            "region": "default", "namespace": "AWS/Lambda", "metricName": metric,
            "dimensions": {"FunctionName": [ALEXA_FUNCTION]}, "statistic": "Sum",
            "period": "300", "matchExact": True, "id": "", "expression": "",
        },
    }


def _reduce(ref: str, source: str, reducer: str = "last") -> dict:
    return {
        "refId": ref,
        "datasourceUid": "__expr__",
        "model": {"refId": ref, "type": "reduce", "reducer": reducer, "expression": source,
                  "settings": {"mode": "dropNN"}},
    }


def _threshold(ref: str, source: str, op: str, value: float) -> dict:
    return {
        "refId": ref,
        "datasourceUid": "__expr__",
        "model": {"refId": ref, "type": "threshold", "expression": source,
                  "conditions": [{"evaluator": {"type": op, "params": [value]}}]},
    }


def _math(ref: str, expression: str) -> dict:
    return {
        "refId": ref,
        "datasourceUid": "__expr__",
        "model": {"refId": ref, "type": "math", "expression": expression},
    }


def _rule(uid, title, data, condition, *, tier, kind, component, summary, description, dashboard,
          for_="10m", no_data="OK", extra_labels=None) -> dict:
    """`${RUNBOOK_URL}` and `${GRAFANA_URL}` are filled in by grafana_sync.py -
    the repo and the stack address are facts about a deployment, not about
    the rule, and don't belong in a generated file."""
    group = "schoolz-sql" if any(d["datasourceUid"] == "${DS_SQL}" for d in data) else f"schoolz-{tier}"
    return {
        "uid": uid,
        "title": title,
        "condition": condition,
        "for": for_,
        "labels": {"app": "schoolz", "tier": tier, "kind": kind, "component": component,
                   "severity": SEVERITY[tier], **(extra_labels or {})},
        "annotations": {
            "summary": summary,
            "description": description,
            "runbook_url": "${RUNBOOK_URL}#" + uid,
            "dashboard_url": "${GRAFANA_URL}/d/" + dashboard,
        },
        "noDataState": no_data,
        "execErrState": "Error",
        "orgId": 1,
        "folderUID": FOLDER,
        "ruleGroup": group,
        "data": data,
    }


def prom(uid, title, expr, threshold, *, op="gt", range_s=3600, **kw) -> dict:
    """One PromQL threshold rule: query -> reduce(last) -> threshold. A query
    returning several series alerts once per series, and each series' labels
    (job_kind, http_route, ...) become labels on that alert."""
    return _rule(uid, title, [_prom("A", expr, range_s), _reduce("B", "A"), _threshold("C", "B", op, threshold)],
                 "C", **kw)


def loki(uid, title, expr, threshold, *, op="gt", range_s=3600, **kw) -> dict:
    return _rule(uid, title, [_loki("A", expr, range_s), _reduce("B", "A"), _threshold("C", "B", op, threshold)],
                 "C", **kw)


def sql(uid, title, query, threshold, *, op="gt", **kw) -> dict:
    """The query returns one row per alert instance: text columns become
    labels, the numeric `value` column is what's compared. No rows is the
    healthy state, so these keep no_data="OK"."""
    return _rule(uid, title, [_sql("A", query, 600), _reduce("B", "A"), _threshold("C", "B", op, threshold)],
                 "C", **kw)


def cloudwatch(uid, title, metric, threshold, *, range_s=1800, **kw) -> dict:
    return _rule(uid, title,
                 [_cloudwatch("A", metric, range_s), _reduce("B", "A", "sum"), _threshold("C", "B", "gt", threshold)],
                 "C", **kw)


def burn(slo: dict, speed: str) -> dict:
    """Multi-window burn-rate alert on an SLO's recorded SLI series.

    The SLO app records `grafana_slo_sli_<window>` for each SLO; its own
    generated alerts are turned off (build_grafana_slos.py) because they fire
    into the Mimir alertmanager rather than the notification policy the rest
    of these rules use, and can't carry a runbook or a traffic floor.

    Burn rate = observed error ratio / allowed error ratio. Both a long and
    a short window must agree, so a burst that has already stopped doesn't
    keep alerting for the length of the long window.
      fast  14.4x over 1h+5m (2% of a 28d budget in an hour) or 6x over 6h+30m
      slow  3x over 1d+2h or 1x over 3d+6h
    `floor` is the fewest events in the long window worth alerting on: with
    a few requests an hour overnight, one failure is a 20% error ratio.
    """
    budget = round(1 - slo["objective"], 6)
    sli = lambda window: f'(1 - grafana_slo_sli_{window}{{grafana_slo_uuid="{slo["uuid"]}"}}) / {budget}'
    if speed == "fast":
        windows = [("A", "1h"), ("B", "5m"), ("C", "6h"), ("D", "30m")]
        cond = "(($A > 14.4 && $B > 14.4) || ($C > 6 && $D > 6)) && $E > %d" % slo["floor"]
        volume_window, for_ = "1h", "2m"
        what = "burning fast"
        detail = ("At this rate the whole 28-day error budget is gone in about two days. "
                  "Burn rate {{ printf \"%.1f\" $values.A.Value }}x over 1h, "
                  "{{ printf \"%.1f\" $values.C.Value }}x over 6h.")
    else:
        windows = [("A", "1d"), ("B", "2h"), ("C", "3d"), ("D", "6h")]
        cond = "(($A > 3 && $B > 3) || ($C > 1 && $D > 1)) && $E > %d" % (slo["floor"] * 6)
        volume_window, for_ = "6h", "30m"
        what = "burning steadily"
        detail = ("Nothing is on fire, but this pace spends the 28-day error budget before the window ends. "
                  "Burn rate {{ printf \"%.1f\" $values.A.Value }}x over 1d, "
                  "{{ printf \"%.1f\" $values.C.Value }}x over 3d.")
    data = [_prom(ref, sli(window), 600) for ref, window in windows]
    data.append(_prom("E", slo["volume"].replace("$window", volume_window), 600))
    data.append(_math("F", cond))
    return _rule(
        f'schoolz-slo-{slo["slug"]}-{speed}',
        f'schoolz SLO: {slo["name"]} error budget {what}',
        data, "F",
        tier=slo["tiers"][speed], kind="slo", component=slo["component"],
        summary=f'{slo["name"]}: error budget {what} (objective {slo["objective"]:.1%} over 28d)',
        description=f'{slo["meaning"]} {detail}',
        dashboard="grafana_slo_app-" + slo["uuid"],
        for_=for_,
        extra_labels={"slo": slo["slug"]},
    )


API = 'service_name="schoolz-api"'
# What "the API" means for the availability and latency SLOs: real requests
# from people. /prerender is crawler-only and has its own SLO; preflights
# never reach a handler.
USER_TRAFFIC = sel(API, 'http_route!="/prerender"', 'http_request_method!="OPTIONS"')
# Routes that are slow by design (a model call, an admin import, a scraper
# round trip) would spend the latency budget on nothing a parent feels.
INTERACTIVE = sel(API, 'http_request_method="GET"',
                  'http_route!~"/prerender|/chat.*|/admin.*|/scraper.*|/scheduled-jobs.*|/health"')
PRERENDER = sel(API, 'http_route="/prerender"')
HTTP = "http_server_request_duration_seconds"

# Shared with build_grafana_slos.py, which turns the same list into SLO
# definitions - one source for the objective and for the alert on it.
SLOS = [
    {
        "uuid": "schoolzapiavail", "slug": "api-availability", "name": "API availability",
        "component": "api", "objective": 0.995,
        "meaning": "Share of API requests from real visitors answered without a 5xx.",
        "good": f'{HTTP}_count{USER_TRAFFIC[:-1]}, http_response_status_code!~"5.."}}',
        "total": f"{HTTP}_count{USER_TRAFFIC}",
        "volume": f"sum(increase({HTTP}_count{USER_TRAFFIC}[$window]))",
        "floor": 50,
        "tiers": {"fast": "page", "slow": "ticket"},
    },
    {
        "uuid": "schoolzapilatency", "slug": "api-latency", "name": "API latency",
        "component": "api", "objective": 0.95,
        "meaning": "Share of interactive GETs answered within 1 second.",
        "good": f'{HTTP}_bucket{INTERACTIVE[:-1]}, le="1"}}',
        "total": f"{HTTP}_count{INTERACTIVE}",
        "volume": f"sum(increase({HTTP}_count{INTERACTIVE}[$window]))",
        "floor": 50,
        "tiers": {"fast": "ticket", "slow": "ticket"},
    },
    {
        "uuid": "schoolzprerender", "slug": "prerender", "name": "Prerender for crawlers",
        "component": "prerender", "objective": 0.99,
        "meaning": "Share of /prerender requests (search engines and link previews) that returned a page.",
        "good": f'{HTTP}_count{PRERENDER[:-1]}, http_response_status_code!~"5.."}}',
        "total": f"{HTTP}_count{PRERENDER}",
        "volume": f"sum(increase({HTTP}_count{PRERENDER}[$window]))",
        "floor": 30,
        "tiers": {"fast": "ticket", "slow": "ticket"},
    },
    {
        "uuid": "schoolzscans", "slug": "scans", "name": "Scan runs",
        "component": "scans", "objective": 0.99,
        "meaning": "Share of scan runs that finished without an error (warnings count as finished).",
        "good": f'schoolz_job_runs_total{sel(FINISHED)}',
        "total": f'schoolz_job_runs_total{sel(NOT_SKIPPED)}',
        "volume": f'sum(increase(schoolz_job_runs_total{sel(NOT_SKIPPED)}[$window]))',
        "floor": 10,
        "tiers": {"fast": "ticket", "slow": "ticket"},
    },
]


def rules() -> list:
    memory = " or ".join(
        "max by (service_name) (process_memory_usage_bytes%s) / %d" % (sel('service_name="%s"' % svc), mb * 1024 * 1024)
        for svc, mb in MEMORY_LIMIT_MB.items()
    )
    return [
        # ---- page: someone is being failed right now -----------------------
        prom(
            "schoolz-api-down", "schoolz: API is not reporting",
            f"count(process_memory_usage_bytes{sel(API)})", 1, op="lt", range_s=600,
            tier="page", kind="symptom", component="api", for_="10m",
            # A dead process emits no series, so absent data IS the outage.
            no_data="Alerting",
            summary="No schoolz-api machine has reported in 10 minutes",
            description="Every API machine exports a memory sample every 30s and one machine is always kept "
                        "running, so silence means none is up (or telemetry export broke). The site shows "
                        "empty pages while this lasts.",
            dashboard="schoolz-api",
        ),
        prom(
            "schoolz-scheduler-down", "schoolz: scheduler has stopped reconciling",
            f"sum(increase(schoolz_scheduler_reconciles_total{sel()}[10m]))", 1, op="lt",
            tier="page", kind="symptom", component="scheduler", for_="10m", no_data="Alerting",
            summary="The scheduler hasn't ticked in 10 minutes - every scan is stopped",
            description="It reconciles every 30s, so this should never be below 1. Nothing else will tell "
                        "you: pages keep serving yesterday's data and no run fails, because no run starts.",
            dashboard="schoolz-scans",
        ),
        burn(SLOS[0], "fast"),

        # ---- ticket: real, but it can wait for daylight --------------------
        burn(SLOS[0], "slow"),
        *[burn(slo, speed) for slo in SLOS[1:] for speed in ("fast", "slow")],
        prom(
            "schoolz-no-scans", "schoolz: no scan has run in 13 hours",
            f"sum(increase(schoolz_job_runs_total{sel()}[13h]))", 1, op="lt", range_s=46800,
            tier="ticket", kind="symptom", component="scans", for_="15m",
            summary="No scan of any kind has run in 13 hours",
            description="The cheapest feeds run every 12h, so a full 13h with zero runs means the scheduler "
                        "is up but not firing jobs (every job disabled, or the reconcile loop is not loading them).",
            dashboard="schoolz-scans",
        ),
        prom(
            "schoolz-job-stuck", "schoolz: a scan has been running for over an hour",
            f"max by (job_kind) (schoolz_job_in_flight{sel()})", 0, range_s=600,
            tier="ticket", kind="symptom", component="scans", for_="1h",
            summary="A {{ $labels.job_kind }} run has been in flight for over an hour",
            description="The reaper clears runs with no progress after 45 minutes, so one still in flight "
                        "is either checkpointing slowly or holding a concurrency slot. Look for real "
                        "evidence before force-erroring it.",
            dashboard="schoolz-scans",
        ),
        prom(
            "schoolz-memory-high", "schoolz: process memory above 85% of its machine",
            memory, 0.85, range_s=600,
            tier="ticket", kind="cause", component="api", for_="15m",
            summary="{{ $labels.service_name }} is at {{ humanizePercentage $values.B.Value }} of its machine's memory",
            description="The next step is an OOM kill, which for the scheduler abandons whatever scan was "
                        "running. Limits are the Fly machine sizes in backend/fly.toml.",
            dashboard="schoolz-api",
        ),
        prom(
            "schoolz-db-pool-saturated", "schoolz: database pool fully checked out",
            f'max by (service_name) (db_client_connections_usage{sel(POOL_USED)})', 5, range_s=600,
            tier="ticket", kind="cause", component="database", for_="10m",
            summary="{{ $labels.service_name }} has held {{ $values.B.Value }} of its 6 database connections for 10 minutes",
            description="Pool is 4 + 2 overflow per process; at 6 every further request waits and then "
                        "fails with db_pool_timeout. Usually one slow query or a leaked session.",
            dashboard="schoolz-api",
        ),
        prom(
            "schoolz-llm-truncated", "schoolz: an LLM reply was truncated (max_tokens)",
            f"sum by (purpose) (increase(schoolz_llm_calls_total{sel(TRUNCATED)}[1h]))", 0,
            tier="ticket", kind="symptom", component="llm", for_="5m",
            summary="A {{ $labels.purpose }} reply hit the output cap and was cut off",
            description="A truncated extraction has silently produced zero items from a full newsletter "
                        "before - the run does not necessarily look failed.",
            dashboard="schoolz-scans",
        ),
        prom(
            "schoolz-scraper-silent", "schoolz: scraper is not reporting",
            'count(schoolz_scraper_pages_open{service_name="schoolz-scraper"})', 1, op="lt", range_s=900,
            tier="ticket", kind="cause", component="scraper", for_="15m", no_data="Alerting",
            summary="The schoolz scraper machine has not reported in 15 minutes",
            description="It never auto-stops, so silence means it is down. Scans fall back to the shared "
                        "droplet, which is why this is a ticket and not a page.",
            dashboard="schoolz-scans",
        ),
        loki(
            "schoolz-auth-stalled", "schoolz: a visitor's auth check never resolved",
            f'sum(count_over_time({FARO} | logfmt | kind="event" | event_name="auth_timeout" [30m]))', 0,
            tier="ticket", kind="symptom", component="auth", for_="0m",
            summary="{{ $values.B.Value }} visitor(s) hit the auth timeout fallback in 30 minutes",
            description="AuthContext gave up waiting and showed Reload. This is the failure that left "
                        "signed-in mobile visitors stuck on 'Loading...' - see the onAuthStateChange comment "
                        "in frontend/src/context/AuthContext.tsx. It should be zero.",
            dashboard="schoolz-ux",
        ),
        cloudwatch(
            "schoolz-alexa-errors", "schoolz: Alexa skill Lambda is erroring", "Errors", 2,
            tier="ticket", kind="symptom", component="alexa", for_="5m",
            summary="The Alexa skill failed {{ $values.B.Value }} invocations in 30 minutes",
            description="Each one is a person hearing 'there was a problem with the requested skill's "
                        "response'. The Lambda's log group has the traceback.",
            dashboard="schoolz-ops",
        ),
        sql(
            "schoolz-job-failing", "schoolz: a scan has failed twice in a row",
            "SELECT j.kind, j.name AS job, COALESCE(j.last_error_code, 'unknown') AS error_code, 1 AS value\n"
            "FROM scheduled_jobs j\n"
            "WHERE j.enabled AND (\n"
            "  SELECT count(*) FROM (\n"
            "    SELECT r.status FROM job_runs r\n"
            "    WHERE r.job_id = j.id AND r.status NOT IN ('skipped', 'running')\n"
            "    ORDER BY r.started_at DESC LIMIT 2\n"
            "  ) last2 WHERE last2.status = 'error'\n"
            ") = 2", 0,
            tier="ticket", kind="symptom", component="scans", for_="0m",
            summary="{{ $labels.job }} failed twice in a row ({{ $labels.error_code }})",
            description="One failure is usually a flaky site; two in a row is real. The Runs tab in "
                        "/admin has the stage and traceback for this job.",
            dashboard="schoolz-scans",
        ),

        # ---- info: triggers, never interruptions ---------------------------
        prom(
            "schoolz-route-5xx", "schoolz: a route is returning 5xx",
            f'sum by (http_route, http_request_method) (increase({HTTP}_count'
            f'{sel(API, SERVER_ERROR)}[30m]))', 5, range_s=1800,
            tier="info", kind="cause", component="api", for_="5m",
            summary="{{ $labels.http_request_method }} {{ $labels.http_route }} returned "
                    "{{ printf \"%.0f\" $values.B.Value }} server errors in 30 minutes",
            description="Names the route behind an availability burn. On its own it is only a pointer - "
                        "the SLO alert decides whether it matters.",
            dashboard="schoolz-api",
        ),
        prom(
            "schoolz-route-slow", "schoolz: a route's p95 is above 2.5s",
            f"histogram_quantile(0.95, sum by (le, http_route) (rate({HTTP}_bucket{INTERACTIVE}[30m])))"
            f" and on (http_route) sum by (http_route) (increase({HTTP}_count{INTERACTIVE}[30m])) > 20",
            2.5, range_s=1800,
            tier="info", kind="cause", component="api", for_="30m",
            summary="{{ $labels.http_route }} p95 is {{ printf \"%.1f\" $values.B.Value }}s",
            description="Names the route behind a latency burn. Only routes with more than 20 requests "
                        "in the window count, so one cold start can't trip it.",
            dashboard="schoolz-api",
        ),
        prom(
            "schoolz-scraper-failing", "schoolz: scraper failing more than 30% of page loads",
            'sum(rate(schoolz_scraper_page_load_seconds_count{service_name="schoolz-scraper", outcome="error"}[1h])) '
            '/ clamp_min(sum(rate(schoolz_scraper_page_load_seconds_count{service_name="schoolz-scraper"}[1h])), 0.001)',
            0.30,
            tier="info", kind="cause", component="scraper", for_="30m",
            summary="{{ humanizePercentage $values.B.Value }} of scraper page loads are failing",
            description="Either the scraper machine is unhealthy or many school sites are unreachable. "
                        "Callers retry and fall back to the droplet, so the scans SLO says whether this hurt.",
            dashboard="schoolz-scans",
        ),
        prom(
            "schoolz-scan-warnings", "schoolz: a scan kind mostly finds nothing",
            f'sum by (job_kind) (increase(schoolz_job_runs_total{sel(WARNED)}[24h]))'
            f' / sum by (job_kind) (increase(schoolz_job_runs_total{sel(NOT_SKIPPED)}[24h]) > 5)',
            0.5, range_s=86400,
            tier="info", kind="cause", component="scans", for_="1h",
            summary="{{ humanizePercentage $values.B.Value }} of {{ $labels.job_kind }} runs ended in a warning over 24h",
            description="Fetched fine, found nothing. For a kind that normally finds something, a site "
                        "redesign looks exactly like this.",
            dashboard="schoolz-scans",
        ),
        prom(
            "schoolz-parse-issues", "schoolz: parse issues spiking",
            f"sum by (job_kind, code) (increase(schoolz_parse_issues_total{sel()}[6h]))", 500, range_s=21600,
            tier="info", kind="cause", component="scans", for_="1h",
            summary="{{ printf \"%.0f\" $values.B.Value }} {{ $labels.code }} parse issues from {{ $labels.job_kind }} in 6h",
            description="Scans are succeeding but dropping content. This is the failure mode that doesn't "
                        "turn anything red - coverage degrades quietly.",
            dashboard="schoolz-scans",
        ),
        prom(
            "schoolz-queue-wait", "schoolz: scans are queueing",
            f"histogram_quantile(0.95, sum by (le) (rate(schoolz_job_queue_wait_seconds_bucket{sel()}[1h])))",
            300,
            tier="info", kind="cause", component="scheduler", for_="30m",
            summary="Scans wait {{ humanizeDuration $values.B.Value }} at p95 for a concurrency slot",
            description="Too many jobs landing in the same minute, or one long job holding a slot.",
            dashboard="schoolz-scans",
        ),
        prom(
            "schoolz-llm-spend", "schoolz: LLM token use well above normal",
            f"sum(increase(schoolz_llm_tokens_total{sel()}[24h]))", 15_000_000, range_s=86400,
            tier="info", kind="cause", component="llm", for_="30m",
            summary="{{ humanize $values.B.Value }} LLM tokens in 24h",
            description="A normal day is well under half of this. A loop re-extracting the same content, "
                        "or a translation backfill, looks like this.",
            dashboard="schoolz-scans",
        ),
        loki(
            "schoolz-auth-slow", "schoolz: auth check p95 above 5s",
            f'quantile_over_time(0.95, {FARO} | logfmt | kind="measurement" | type="auth_ready" | unwrap value_ms [30m])',
            5000,
            tier="info", kind="cause", component="auth", for_="15m",
            summary="The client-side auth check takes {{ printf \"%.0f\" $values.B.Value }}ms at p95",
            description="Short of the outright stall schoolz-auth-stalled catches, but the same failure "
                        "degrading: every API call waits behind the Supabase auth lock.",
            dashboard="schoolz-ux",
        ),
        prom(
            "schoolz-user-created", "schoolz: new user registered",
            f"sum(increase(schoolz_user_created_total{sel()}[5m]))", 0, range_s=300,
            tier="info", kind="event", component="growth", for_="0m",
            summary="A new account was just created",
            description="Local register or a first Supabase sign-in. The `user_created` log line has the source.",
            dashboard="schoolz-ux",
        ),
        cloudwatch(
            "schoolz-alexa-throttled", "schoolz: Alexa skill Lambda throttled", "Throttles", 0,
            tier="info", kind="cause", component="alexa", for_="5m",
            summary="The Alexa skill Lambda was throttled {{ $values.B.Value }} times in 30 minutes",
            description="The account's concurrency limit was hit. Expected never at this traffic.",
            dashboard="schoolz-ops",
        ),
        sql(
            "schoolz-newsletter-stale", "schoolz: newsletters not scanned in 8 days",
            "SELECT count(*) AS value FROM smore_newsletters\n"
            "WHERE last_scanned_at IS NULL OR last_scanned_at < now() - interval '8 days'", 0,
            tier="info", kind="cause", component="scans", for_="1h",
            summary="{{ printf \"%.0f\" $values.B.Value }} newsletter(s) have missed a weekly scan",
            description="The Scans dashboard lists which. An expired per-issue URL does not show up here - "
                        "it scans fine and finds nothing (smore_no_blocks).",
            dashboard="schoolz-scans",
        ),
        sql(
            "schoolz-vision-backlog", "schoolz: flyer images waiting on vision extraction",
            "SELECT count(*) AS value FROM smore_blocks WHERE pending_vision_extraction", 0,
            tier="info", kind="cause", component="llm", for_="1d",
            summary="{{ printf \"%.0f\" $values.B.Value }} image block(s) have been pending for a day",
            description="A failed vision extract stays pending and retries on the next scan; a day of it "
                        "means the image itself can't be read.",
            dashboard="schoolz-scans",
        ),
    ]


def main() -> None:
    by_group: dict = {name: [] for name in GROUPS}
    for r in rules():
        by_group[r["ruleGroup"]].append(r)
    OUT.write_text(json.dumps({"apiVersion": 1, "groups": [
        {"orgId": 1, "name": name, "folder": FOLDER, "interval": GROUPS[name], "rules": group_rules}
        for name, group_rules in by_group.items()
    ]}, indent=2) + "\n")
    print(f"wrote {OUT.name} ({len(rules())} rules in {len(by_group)} groups)")


if __name__ == "__main__":
    main()
