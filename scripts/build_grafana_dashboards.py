#!/usr/bin/env python3
"""Generates the schoolz Grafana dashboards into grafana/cloud-dashboards/.

Dashboards-as-code rather than "export the JSON from the UI and paste it
back": the UI export carries datasource UIDs, panel ids and a pile of
defaults specific to whoever exported it, which makes review of a one-line
query change impossible. Here the queries are the source, and the JSON is
a build artifact you can regenerate.

Every dashboard declares its datasources as *template variables*
(${DS_METRICS} etc.) instead of hardcoding UIDs, so the same file imports
cleanly into any Grafana - the local compose stack or Grafana Cloud -
without knowing that instance's UIDs.

IMPORTANT: the Grafana Cloud stack is shared with billz, so every metric
query filters on service_namespace="schoolz" (set as an OTel resource
attribute in backend/telemetry.py). Dropping that filter silently mixes
another app's data into these panels.

Run: python3 scripts/build_grafana_dashboards.py
"""
import json
import pathlib

from build_grafana_alerts import ALEXA_FUNCTION, SLOS

OUT = pathlib.Path(__file__).resolve().parent.parent / "grafana" / "cloud-dashboards"

NS = 'service_namespace="schoolz"'
ERRORED = 'status="error"'


def sel(*extra: str) -> str:
    """PromQL label selector, always namespace-filtered (shared stack)."""
    return "{" + ", ".join([NS, *extra]) + "}"

# Haiku 4.5 list price per million tokens, looked up 2026-09-12. Cache
# write is 1.25x base input and cache read is 0.1x, per Anthropic's
# standard cache multipliers. Kept as dashboard constants so a price
# change is a one-line edit, not a re-derivation of every expression.
PRICE = {"input": 1.00, "output": 5.00, "cache_write": 1.25, "cache_read": 0.10}

TRUNCATED = 'stop_reason="max_tokens"'
SERVER_ERROR = 'http_response_status_code=~"5.."'
POOL_USED = 'state="used"'
MEM_RSS = 'type="rss"'
API_SVC = 'service_name="schoolz-api"'


def ds_var(name: str, kind: str, label: str) -> dict:
    return {
        "current": {},
        "hide": 0,
        "includeAll": False,
        "label": label,
        "multi": False,
        "name": name,
        "options": [],
        "query": kind,
        "refresh": 1,
        "type": "datasource",
    }


def target(expr: str, legend: str = "", ds: str = "DS_METRICS", fmt: str = "time_series", ref: str = "A") -> dict:
    return {
        "datasource": {"type": "prometheus", "uid": f"${{{ds}}}"},
        "expr": expr,
        "legendFormat": legend,
        "range": True,
        "format": fmt,
        "refId": ref,
    }


def loki_target(expr: str, ref: str = "A", instant: bool = False) -> dict:
    return {
        "datasource": {"type": "loki", "uid": "${DS_LOGS}"},
        "expr": expr,
        "queryType": "range",
        "refId": ref,
        "instant": instant,
    }


def sql_target(sql: str, ref: str = "A", fmt: str = "table") -> dict:
    return {
        "datasource": {"type": "grafana-postgresql-datasource", "uid": "${DS_SQL}"},
        "rawSql": sql,
        "rawQuery": True,
        "format": fmt,
        "editorMode": "code",
        "refId": ref,
    }


def ga_target(dimension: str, metrics: list, columns: list, limit: int = 0, ref: str = "A") -> dict:
    """One Google Analytics Data API report, through the Infinity datasource
    (scripts/grafana_sync.py:ensure_ga). The dashboard's own time range
    becomes the report's date range; `${GA_PROPERTY}` is filled in at sync so
    the property id never lands in a tracked file."""
    by_date = dimension == "date"
    body = {
        "dateRanges": [{"startDate": "${__from:date:YYYY-MM-DD}", "endDate": "${__to:date:YYYY-MM-DD}"}],
        "dimensions": [{"name": dimension}],
        "metrics": [{"name": m} for m in metrics],
        "orderBys": [{"dimension": {"dimensionName": "date"}}] if by_date
                    else [{"metric": {"metricName": metrics[0]}, "desc": True}],
    }
    if limit:
        body["limit"] = limit
    first = ({"selector": "dimensionValues.0.value", "text": columns[0], "type": "timestamp", "timestampFormat": "20060102"}
             if by_date else {"selector": "dimensionValues.0.value", "text": columns[0], "type": "string"})
    return {
        "datasource": {"type": "yesoreyeram-infinity-datasource", "uid": "${DS_GA}"},
        "refId": ref, "type": "json", "source": "url", "format": "timeseries" if by_date else "table",
        "parser": "backend",
        "url": "https://analyticsdata.googleapis.com/v1beta/properties/${GA_PROPERTY}:runReport",
        "url_options": {"method": "POST", "body_type": "raw", "body_content_type": "application/json",
                        "data": json.dumps(body)},
        "root_selector": "rows",
        "columns": [first] + [{"selector": f"metricValues.{i}.value", "text": name, "type": "number"}
                              for i, name in enumerate(columns[1:])],
    }


def panel(pid, title, targets, gp, ptype="timeseries", unit=None, desc="", extra=None) -> dict:
    p = {
        "id": pid,
        "title": title,
        "description": desc,
        "type": ptype,
        "gridPos": gp,
        "targets": targets,
        "fieldConfig": {"defaults": {"custom": {}}, "overrides": []},
        "options": {},
    }
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    if ptype == "stat":
        p["options"] = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}}
    if ptype == "logs":
        p["options"] = {"showTime": True, "sortOrder": "Descending", "wrapLogMessage": True}
    if extra:
        p.update(extra)
    return p


def dashboard(uid: str, title: str, desc: str, panels: list, variables: list, tags=None) -> dict:
    return {
        "uid": uid,
        "title": title,
        "description": desc,
        "tags": tags or ["schoolz"],
        "timezone": "America/New_York",
        "schemaVersion": 39,
        "version": 0,
        "refresh": "5m",
        "time": {"from": "now-24h", "to": "now"},
        "templating": {"list": variables},
        "panels": panels,
        "editable": True,
    }


# --------------------------------------------------------------------------
# 1. Scans - is the data pipeline healthy, and what is it costing?
# --------------------------------------------------------------------------
def scans() -> dict:
    tokens_by_dir = f"sum by (direction) (increase(schoolz_llm_tokens_total{sel()}[24h]))"
    cost_terms = []
    for direction, price in PRICE.items():
        selector = sel('direction="%s"' % direction)
        cost_terms.append(f"(sum(increase(schoolz_llm_tokens_total{selector}[24h])) * {price} / 1e6)")
    cost_expr = " + ".join(cost_terms)
    truncated_expr = f'sum(increase(schoolz_llm_calls_total{sel(TRUNCATED)}[24h]))'
    panels = [
        panel(1, "Job runs (12h, by kind and outcome)",
              [target(f'sum by (job_kind, status) (increase(schoolz_job_runs_total{sel()}[12h]))', "{{job_kind}} · {{status}}")],
              {"h": 8, "w": 12, "x": 0, "y": 0},
              desc="The 12h window matches the scan cadence - every public-source job runs on '0 */12 * * *'."),
        panel(2, "Jobs in flight",
              [target(f'sum(schoolz_job_in_flight{sel()})', "in flight")],
              {"h": 8, "w": 12, "x": 12, "y": 0},
              desc="Capped by JOB_CONCURRENCY. Sitting at the cap during the 12h burst means jobs are queueing."),
        panel(3, "Job duration p95 by kind",
              [target(f'histogram_quantile(0.95, sum by (le, job_kind) (rate(schoolz_job_duration_seconds_bucket{sel()}[1h])))',
                      "{{job_kind}}")],
              {"h": 8, "w": 12, "x": 0, "y": 8}, unit="s"),
        panel(4, "Queue wait p95 (the burst test)",
              [target(f'histogram_quantile(0.95, sum by (le, job_kind) (rate(schoolz_job_queue_wait_seconds_bucket{sel()}[1h])))',
                      "{{job_kind}}")],
              {"h": 8, "w": 12, "x": 12, "y": 8}, unit="s",
              desc="~85 school-level scans fire in the same minute. This is the panel that proves whether "
                   "the cron needs jittering per job (OBSERVABILITY_PLAN hypothesis #6)."),
        panel(5, "Scraper page loads by outcome",
              [target(f'sum by (outcome) (rate(schoolz_scraper_page_load_seconds_count{{service_name="schoolz-scraper"}}[30m]))',
                      "{{outcome}}")],
              {"h": 8, "w": 12, "x": 0, "y": 16},
              desc="Recorded by the scraper service itself (scraper/observability.py), which is the only "
                   "place that can see the target host and outcome."),
        panel(6, "Parse issues (non-fatal, by code)",
              [target(f'sum by (code, job_kind) (increase(schoolz_parse_issues_total{sel()}[6h]))', "{{job_kind}} · {{code}}")],
              {"h": 8, "w": 12, "x": 12, "y": 16},
              desc="A scan that 'succeeded' while quietly dropping a block. Rising here means coverage is "
                   "degrading without anything turning red."),
        panel(7, "Scan failures by error code",
              [target(
                  f"sum by (error_code, error_stage, job_kind) "
                  f"(increase(schoolz_job_runs_total{sel(ERRORED)}[7d]))",
                  "{{job_kind}} · {{error_code}} · {{error_stage}}")],
              {"h": 8, "w": 12, "x": 0, "y": 24},
              desc="error_code/error_stage come from scheduler/errors.py classify_exception() - the "
                   "groupable version of a traceback. Metrics rather than SQL: this is the same data "
                   "schoolz_job_runs_total already carries, and keeping it here means the failure-ratio "
                   "alert and this panel can never disagree."),
        panel(8, "Newsletters not scanned in 8+ days",
              [sql_target(
                  "SELECT COALESCE(label, url) AS \"Newsletter\",\n"
                  "       date_trunc('minute', last_scanned_at) AS \"Last scanned\"\n"
                  "FROM smore_newsletters\n"
                  "WHERE last_scanned_at IS NULL OR last_scanned_at < now() - interval '8 days'\n"
                  "ORDER BY last_scanned_at NULLS FIRST;")],
              {"h": 8, "w": 12, "x": 12, "y": 24}, ptype="table",
              desc="Smore newsletters run weekly, so 8 days is one missed cycle. Catches the known "
                   "per-issue-URL schools (Cooper, Clara Barton) going stale."),
        panel(9, "LLM tokens (24h, by direction)",
              [target(tokens_by_dir, "{{direction}}")],
              {"h": 8, "w": 8, "x": 0, "y": 32},
              desc="Cache reads/writes are separate directions because they bill at different rates."),
        panel(10, "Estimated LLM spend (24h)",
              [target(cost_expr, "USD")],
              {"h": 8, "w": 8, "x": 8, "y": 32}, ptype="stat", unit="currencyUSD",
              desc=f"Haiku 4.5 list price (looked up 2026-09-12): input ${PRICE['input']}/MTok, "
                   f"output ${PRICE['output']}, cache write ${PRICE['cache_write']}, cache read ${PRICE['cache_read']}. "
                   "An estimate from token counts, not a billing feed - re-check the rates if they change."),
        panel(11, "Truncated LLM replies (stop_reason=max_tokens)",
              [target(truncated_expr, "truncated")],
              {"h": 8, "w": 8, "x": 16, "y": 32}, ptype="stat",
              desc="Non-zero means an extraction was cut off mid-structure - the failure mode that once "
                   "produced zero items from a 37-block newsletter with no error anywhere."),
    ]
    return dashboard(
        "schoolz-scans", "schoolz / Scans",
        "Scheduled scan health, scraper outcomes, and what the LLM extraction costs.",
        panels,
        [ds_var("DS_METRICS", "prometheus", "Metrics"),
         ds_var("DS_LOGS", "loki", "Logs"),
         ds_var("DS_SQL", "grafana-postgresql-datasource", "schoolz database")],
    )


# --------------------------------------------------------------------------
# 2. API - RED metrics for the backend
# --------------------------------------------------------------------------
def api() -> dict:
    dur = f'http_server_request_duration_seconds'
    panels = [
        panel(1, "Request rate by route",
              [target(f'sum by (http_route) (rate({dur}_count{sel()}[5m]))', "{{http_route}}")],
              {"h": 8, "w": 12, "x": 0, "y": 0}, unit="reqps"),
        panel(2, "5xx error ratio",
              [target(
                  f"sum(rate({dur}_count{sel(SERVER_ERROR)}[5m]))"
                  f" / clamp_min(sum(rate({dur}_count{sel()}[5m])), 0.001)",
                  "5xx ratio")],
              {"h": 8, "w": 12, "x": 12, "y": 0}, unit="percentunit"),
        panel(3, "Latency p50 / p95 by route",
              [target(f'histogram_quantile(0.50, sum by (le, http_route) (rate({dur}_bucket{sel()}[5m])))', "p50 {{http_route}}"),
               target(f'histogram_quantile(0.95, sum by (le, http_route) (rate({dur}_bucket{sel()}[5m])))', "p95 {{http_route}}", ref="B")],
              {"h": 8, "w": 12, "x": 0, "y": 8}, unit="s"),
        panel(4, "Where server time actually goes (total time by route)",
              [target(f'topk(10, sum by (http_route) (rate({dur}_sum{sel()}[1h])))', "{{http_route}}")],
              {"h": 8, "w": 12, "x": 12, "y": 8}, unit="s",
              desc="Rate times duration, not just p95 - a slowish route called constantly costs more total "
                   "time than a slow route nobody hits. This is the list worth optimizing."),
        panel(5, "Cold starts",
              [target(f'sum by (service_name) (increase(schoolz_cold_start_requests_total{sel()}[1h]))', "{{service_name}}")],
              {"h": 8, "w": 8, "x": 0, "y": 16},
              desc="schoolz-api keeps one machine warm (min_machines_running=1), so a rising count here "
                   "means machines are being cycled, not that traffic is waking them."),
        panel(6, "DB connection pool in use",
              [target(f"sum by (service_name) (db_client_connections_usage{sel(POOL_USED)})", "{{service_name}}")],
              {"h": 8, "w": 8, "x": 8, "y": 16}),
        panel(7, "Process memory (RSS)",
              [target(f"sum by (service_name) (process_runtime_cpython_memory_bytes{sel(MEM_RSS)})", "{{service_name}}")],
              {"h": 8, "w": 8, "x": 16, "y": 16}, unit="bytes",
              desc="The scheduler is the one to watch: 256MB got OOM-killed running the Monday extraction burst."),
    ]
    return dashboard(
        "schoolz-api", "schoolz / API",
        "Rate, errors and duration for schoolz-api, plus the resource signals behind them.",
        panels,
        [ds_var("DS_METRICS", "prometheus", "Metrics")],
    )


# --------------------------------------------------------------------------
# 3. User experience - did anyone come, and did the site work for them?
# --------------------------------------------------------------------------
def ux() -> dict:
    faro = '{app_name="schoolz-faro"}'
    panels = [
        panel(1, "Visits by page (server-side, last 30d)",
              [sql_target(
                  "SELECT day AS \"Day\", path AS \"Page\", sum(count) AS \"Visits\"\n"
                  "FROM page_visits\n"
                  "WHERE day >= to_char(now() - interval '30 days', 'YYYY-MM-DD')\n"
                  "GROUP BY 1, 2 ORDER BY 1 DESC, 3 DESC;")],
              {"h": 9, "w": 12, "x": 0, "y": 0}, ptype="table",
              desc="The reliable number: counted server-side, so ad blockers don't hide it. Aggregate only - "
                   "one row per day/page/source, nothing per visitor."),
        panel(2, "Where visitors came from (last 30d)",
              [sql_target(
                  "SELECT source AS \"Source\", sum(count) AS \"Visits\"\n"
                  "FROM page_visits\n"
                  "WHERE day >= to_char(now() - interval '30 days', 'YYYY-MM-DD')\n"
                  "GROUP BY 1 ORDER BY 2 DESC;")],
              {"h": 9, "w": 12, "x": 12, "y": 0}, ptype="table",
              desc="'facebook' is the campaign cohort. First-touch per browser session, so a reader who "
                   "lands from Facebook and clicks through stays attributed to Facebook."),
        panel(3, "Survey funnel (last 30d)",
              [sql_target(
                  "SELECT\n"
                  "  (SELECT COALESCE(sum(count), 0) FROM page_visits\n"
                  "     WHERE path = '/chcomms' AND day >= to_char(now() - interval '30 days', 'YYYY-MM-DD')) AS \"Read /chcomms\",\n"
                  "  (SELECT COALESCE(sum(count), 0) FROM page_visits\n"
                  "     WHERE path = '/survey' AND day >= to_char(now() - interval '30 days', 'YYYY-MM-DD')) AS \"Opened /survey\",\n"
                  "  (SELECT count(*) FROM survey_responses\n"
                  "     WHERE created_at > now() - interval '30 days') AS \"Completed survey\";")],
              {"h": 6, "w": 12, "x": 0, "y": 9}, ptype="stat",
              desc="The question the Facebook post is actually asking: how many read it, how many opened "
                   "the survey, how many finished."),
        panel(4, "Newsletters submitted by the community (last 30d)",
              [sql_target(
                  "SELECT date_trunc('day', created_at) AS time, count(*) AS \"Submissions\"\n"
                  "FROM community_submissions\n"
                  "WHERE created_at > now() - interval '30 days'\n"
                  "GROUP BY 1 ORDER BY 1;", fmt="time_series")],
              {"h": 6, "w": 12, "x": 12, "y": 9},
              desc="The single most valuable conversion - a submitted Smore link is what makes a school's "
                   "page fill in."),
        panel(5, "Survey satisfaction distribution",
              [sql_target(
                  "SELECT satisfaction AS \"Score (1-5)\", count(*) AS \"Responses\"\n"
                  "FROM survey_responses WHERE satisfaction IS NOT NULL\n"
                  "GROUP BY 1 ORDER BY 1;")],
              {"h": 8, "w": 8, "x": 0, "y": 15}, ptype="barchart"),
        panel(6, "What parents say is hard to find",
              [sql_target(
                  "SELECT jsonb_array_elements_text(pain_points::jsonb) AS \"Topic\", count(*) AS \"Picked by\"\n"
                  "FROM survey_responses\n"
                  "WHERE jsonb_typeof(pain_points::jsonb) = 'array'\n"
                  "GROUP BY 1 ORDER BY 2 DESC;")],
              {"h": 8, "w": 16, "x": 8, "y": 15}, ptype="table",
              desc="Directly answers whether the report's priorities match what parents actually feel. A "
                   "topic nobody picks is one we guessed wrong about."),
        # --- Faro / RUM. Field names below follow Faro's Loki shape; if a
        # panel is empty, run the query in Explore and adjust the label.
        panel(7, "Page views by route (RUM)",
              [loki_target(f'sum by (route) (count_over_time({faro} | logfmt | kind="event" | event_name="page_view" [1h]))')],
              {"h": 8, "w": 12, "x": 0, "y": 23},
              desc="RUM's view of the same traffic as panel 1. Lower than the server-side count by roughly "
                   "the ad-blocker rate - the gap between the two is itself informative."),
        panel(8, "CTA clicks on /chcomms (RUM)",
              [loki_target(f'sum by (cta) (count_over_time({faro} | logfmt | kind="event" | event_name="cta_click" [6h]))')],
              {"h": 8, "w": 12, "x": 12, "y": 23},
              desc="Which of the three asks actually converts: send_newsletter, take_survey, or try_app."),
        panel(9, "Core Web Vitals p75 by route",
              [loki_target(f'quantile_over_time(0.75, {faro} | logfmt | kind="measurement" | unwrap lcp [1h]) by (route)', ref="A")],
              {"h": 8, "w": 12, "x": 0, "y": 31}, unit="ms",
              desc="Largest Contentful Paint, the vital Google actually ranks on."),
        panel(10, "JavaScript errors by route (RUM)",
              [loki_target(f'sum by (route) (count_over_time({faro} | logfmt | kind="exception" [1h]))')],
              {"h": 8, "w": 12, "x": 12, "y": 31},
              desc="Catches the class of bug that blanked every local build (faro-react's FaroRoutes) before "
                   "a user has to report it."),
        panel(11, "Visitors and page views per day (Google Analytics)",
              [ga_target("date", ["activeUsers", "screenPageViews"], ["day", "visitors", "page views"])],
              {"h": 8, "w": 12, "x": 0, "y": 39},
              desc="GA's count, which loads only on the production hostname and never for crawlers or admins "
                   "flagged internal. Compare with the server-side page-visit panels: the gap is ad blockers "
                   "plus anyone who left before GA's deferred load."),
        panel(12, "Where sessions come from (Google Analytics)",
              [ga_target("sessionDefaultChannelGroup", ["sessions"], ["channel", "sessions"], limit=10)],
              {"h": 8, "w": 6, "x": 12, "y": 39}, ptype="table",
              desc="The one question only GA can answer here: search, social, direct or a campaign link."),
        panel(13, "Top pages (Google Analytics)",
              [ga_target("pagePath", ["screenPageViews", "activeUsers"], ["page", "views", "visitors"], limit=15)],
              {"h": 8, "w": 6, "x": 18, "y": 39}, ptype="table",
              desc="Paths as GA receives them: tokens stripped, personal and admin routes collapsed."),
    ]
    return dashboard(
        "schoolz-ux", "schoolz / User experience",
        "Did anyone come, where from, did they convert, and did the site work for them.",
        panels,
        [ds_var("DS_METRICS", "prometheus", "Metrics"),
         ds_var("DS_LOGS", "loki", "Logs (Faro RUM)"),
         ds_var("DS_SQL", "grafana-postgresql-datasource", "schoolz database"),
         ds_var("DS_GA", "yesoreyeram-infinity-datasource", "Google Analytics")],
    )


# --------------------------------------------------------------------------
# 4. Operations - the one page to open when something notifies you
# --------------------------------------------------------------------------
def alert_list(pid, title, tiers, gp, desc) -> dict:
    return panel(pid, title, [], gp, ptype="alertlist", desc=desc, extra={"options": {
        "alertInstanceLabelFilter": '{app="schoolz", tier=~"%s"}' % tiers,
        "stateFilter": {"firing": True, "pending": True, "noData": True, "error": True, "normal": False},
        "groupMode": "default", "viewMode": "list", "sortOrder": 3, "maxItems": 30, "alertName": "",
    }})


def cloudwatch_target(metric: str, ref: str) -> dict:
    return {
        "datasource": {"type": "cloudwatch", "uid": "${DS_CLOUDWATCH}"},
        "refId": ref, "queryMode": "Metrics", "metricQueryType": 0, "metricEditorMode": 0,
        "region": "default", "namespace": "AWS/Lambda", "metricName": metric,
        "dimensions": {"FunctionName": [ALEXA_FUNCTION]}, "statistic": "Sum", "period": "300",
        "matchExact": True, "id": "", "expression": "", "label": metric,
    }


def ops() -> dict:
    sli = [target(f'grafana_slo_sli_window{{grafana_slo_uuid="{s["uuid"]}"}}', s["name"], ref=chr(65 + i))
           for i, s in enumerate(SLOS)]
    budget = [target(f'1 - (1 - grafana_slo_sli_window{{grafana_slo_uuid="{s["uuid"]}"}}) / {round(1 - s["objective"], 6)}',
                     s["name"], ref=chr(65 + i)) for i, s in enumerate(SLOS)]
    burn = [target(f'(1 - grafana_slo_sli_1h{{grafana_slo_uuid="{s["uuid"]}"}}) / {round(1 - s["objective"], 6)}',
                   s["name"], ref=chr(65 + i)) for i, s in enumerate(SLOS)]
    red_below_zero = {"fieldConfig": {"defaults": {"unit": "percentunit", "custom": {}, "thresholds": {
        "mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "orange", "value": 0},
                                      {"color": "green", "value": 0.25}]}}, "overrides": []}}
    panels = [
        alert_list(1, "Needs action (page + ticket)", "page|ticket", {"h": 9, "w": 12, "x": 0, "y": 0},
                   "Everything routed to IRM. Empty is the goal."),
        alert_list(2, "Informational", "info", {"h": 9, "w": 12, "x": 12, "y": 0},
                   "Triggers and causes: context for whatever is on the left, emailed in batches, never paged."),
        panel(3, "SLO attainment (28d)", sli, {"h": 6, "w": 12, "x": 0, "y": 9}, ptype="stat", unit="percentunit",
              desc="Objectives: " + ", ".join(f'{s["name"]} {s["objective"]:.1%}' for s in SLOS) + "."),
        panel(4, "Error budget remaining (28d)", budget, {"h": 6, "w": 12, "x": 12, "y": 9}, ptype="stat",
              desc="100% = nothing spent, 0% = the objective is exactly met, negative = the SLO is violated.",
              extra=red_below_zero),
        panel(5, "Burn rate (1h)", burn, {"h": 8, "w": 12, "x": 0, "y": 15},
              desc="1x spends exactly the budget over 28 days. The fast alert needs 14.4x over 1h, the slow one 3x over a day."),
        panel(6, "Is each process reporting?",
              [target(f'count(process_memory_usage_bytes{sel(API_SVC)})', "API machines", ref="A"),
               target(f'sum(increase(schoolz_scheduler_reconciles_total{sel()}[10m]))', "scheduler ticks / 10m", ref="B"),
               target('count(schoolz_scraper_pages_open{service_name="schoolz-scraper"})', "scraper machines", ref="C"),
               target('max by (job) (probe_success{job=~"schoolz-web|schoolz-api"})', "{{job}} reachable", ref="D")],
              {"h": 8, "w": 12, "x": 12, "y": 15},
              desc="The liveness signals behind the down/silent alerts, plus the outside probes. A line ending or dropping to 0 is the outage."),
        panel(7, "Alexa skill (Lambda)",
              [cloudwatch_target("Invocations", "A"), cloudwatch_target("Errors", "B"), cloudwatch_target("Throttles", "C")],
              {"h": 8, "w": 24, "x": 0, "y": 23},
              desc="The only part of schoolz on AWS. From CloudWatch, so it lags a few minutes."),
    ]
    return dashboard(
        "schoolz-ops", "schoolz / Operations",
        "What needs a person, how the SLOs stand, and whether every process is alive.",
        panels,
        [ds_var("DS_METRICS", "prometheus", "Metrics"), ds_var("DS_CLOUDWATCH", "cloudwatch", "CloudWatch")],
    )


# --------------------------------------------------------------------------
# 5. Cost - what is being spent, on what, and what isn't metered yet
# --------------------------------------------------------------------------
# $ per million tokens as (input, output, cache_write, cache_read), keyed by a
# model-id regex. Anthropic list prices, looked up 2026-10-07. A model that
# matches nothing here is counted in tokens but priced at nothing, which is
# why the dashboard has an "unpriced models" panel instead of a silent zero.
MODEL_PRICES = {
    "claude-haiku-4-5.*": (1.00, 5.00, 1.25, 0.10),
    "claude-sonnet-5.*": (2.00, 10.00, 2.50, 0.20),
    "claude-opus-5-5.*": (4.00, 20.00, 5.00, 0.20),
    "claude-opus-5|claude-opus-5-20.*": (5.00, 25.00, 6.25, 0.50),
    "claude-fable-5.*": (10.00, 50.00, 12.50, 0.25),
}
PRICED_MODELS = "|".join(MODEL_PRICES)
DIRECTIONS = ("input", "output", "cache_write", "cache_read")
# Every log record reaches Loki twice: telemetry.py attaches an OTel handler
# and LoggingInstrumentor attaches its own. Only the second carries code_*
# attributes, so an empty code_function_name selects one copy of each line.
# If that is ever fixed at the source and these panels drop to zero, the
# surviving handler is the other one - remove this filter.
CHAT_LOGS = '{service_name="schoolz-api"} |= "chatbot_usage" | code_function_name=""'
CACHE_READ = 'direction="cache_read"'
ANY_INPUT = 'direction=~"input|cache_read|cache_write"'


def llm_cost(by: str = "", window: str = "$__range") -> str:
    """Dollars from schoolz_llm_tokens_total. Every (model, direction) pair is
    its own series, so the priced terms are unioned with `or` and summed -
    adding them with `+` would drop any purpose that lacks one direction."""
    terms = []
    for rx, prices in MODEL_PRICES.items():
        for direction, price in zip(DIRECTIONS, prices):
            selector = sel('model=~"%s"' % rx, 'direction="%s"' % direction)
            terms.append(f"increase(schoolz_llm_tokens_total{selector}[{window}]) * {price / 1e6:.3g}")
    return f"sum{f' by ({by})' if by else ''} ({' or '.join(terms)})"


def chat_cost(by: str = "", window: str = "$__range") -> str:
    """The same sum for the chatbot, which logs usage to Loki rather than the
    token counter. The `t` label keeps the four token kinds of one model from
    colliding in the `or`."""
    terms = []
    for rx, prices in MODEL_PRICES.items():
        for direction, price in zip(DIRECTIONS, prices):
            field = f"{direction}_tokens"
            terms.append(
                f'label_replace(sum by (provider, model) (sum_over_time({CHAT_LOGS} | model=~"{rx}" '
                f'| unwrap {field} [{window}])) * {price / 1e6:.3g}, "t", "{direction}", "", "")')
    return f"sum{f' by ({by})' if by else ''} ({' or '.join(terms)})"


def instant(expr: str, legend: str = "", ds: str = "DS_METRICS", ref: str = "A") -> dict:
    t = target(expr, legend, ds=ds, ref=ref)
    t.update({"range": False, "instant": True})
    return t


def loki_instant(expr: str) -> dict:
    # loki_target's `instant` flag alone still runs a range query, and a
    # [$__range] window on top of a 30-day range is past Loki's query limit.
    t = loki_target(expr, instant=True)
    t["queryType"] = "instant"
    return t


# Substring of a model id -> the same four prices, for the per-key estimate,
# which is computed inside the query (JSONata) because the cost report cannot
# be grouped by key. Order matters: "opus-5-5" must be tried before "opus-5".
BILLING_PRICES = (("haiku-4-5", MODEL_PRICES["claude-haiku-4-5.*"]), ("sonnet-5", MODEL_PRICES["claude-sonnet-5.*"]),
                  ("opus-5-5", MODEL_PRICES["claude-opus-5-5.*"]),
                  ("opus-5", MODEL_PRICES["claude-opus-5|claude-opus-5-20.*"]),
                  ("fable-5", MODEL_PRICES["claude-fable-5.*"]))
BILLING_RANGE = "starting_at=${__from:date:iso}&ending_at=${__to:date:iso}&limit=31"
# ${ANTHROPIC_NAMES} is a JSON object of id -> Console name, written in by
# scripts/grafana_sync.py; an id it doesn't know is shown as it is.
NAMED = ('function($id) { $type($id) = "string" ? ($exists($lookup($n, $id)) ? $lookup($n, $id) : $id) '
         ': "default workspace" }')


def billing_target(report: str, selector: str, columns: list, ref: str = "A") -> dict:
    """One call to Anthropic's usage or cost report, through the Infinity
    datasource scripts/grafana_sync.py:ensure_anthropic makes. Both reports
    return ids, nested per-day buckets and amounts as strings, so every
    selector flattens, converts and names them in JSONata."""
    return {
        "datasource": {"type": "yesoreyeram-infinity-datasource", "uid": "${DS_ANTHROPIC}"},
        "refId": ref, "type": "json", "source": "url", "format": "table", "parser": "backend",
        "url": f"https://api.anthropic.com/v1/organizations/{report}&{BILLING_RANGE}",
        "url_options": {"method": "GET"},
        "root_selector": "( $n := ${ANTHROPIC_NAMES}; $name := " + NAMED + "; " + selector + " )",
        "columns": [{"selector": name, "text": name, "type": kind} for name, kind in columns],
    }


def billed_by(field: str, expr: str) -> str:
    """Cost-report dollars summed per distinct value of `expr`."""
    return ('$r := data.results.{"k": ' + expr + ', "usd": $number(amount) / 100}; '
            '$distinct($r.k).( $k := $; {"' + field + '": $k, "usd": $sum($r[k = $k].usd)} )')


def cost() -> dict:
    usd = {"fieldConfig": {"defaults": {"unit": "currencyUSD", "decimals": 2, "custom": {}}, "overrides": []}}
    bars = {"options": {"orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
                        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}}}
    stacked = {"fieldConfig": {"defaults": {"unit": "currencyUSD", "custom": {
        "drawStyle": "bars", "fillOpacity": 80, "stacking": {"mode": "normal", "group": "A"}}}, "overrides": []}}
    quota = {"fieldConfig": {"defaults": {"unit": "percentunit", "min": 0, "max": 1.5, "custom": {}, "thresholds": {
        "mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "orange", "value": 0.8},
                                      {"color": "red", "value": 1}]}}, "overrides": []}}

    def used(name: str, usage: str, included: str, ref: str) -> dict:
        return instant(f"sum({usage}) / sum({included})", name, ds="DS_USAGE", ref=ref)

    price_of = "".join(f'$contains($m, "{part}") ? {list(prices)} : ' for part, prices in BILLING_PRICES) + "[0, 0, 0, 0]"
    by_key = (
        "$price := function($m) { " + price_of + " }; "
        "$r := data.results.( $p := $price(model); {"
        '"k": $type(api_key_id) = "string" ? $name(api_key_id) : "no key (Console or Claude Code)", '
        '"usd": ($number(uncached_input_tokens) * $p[0] + $number(output_tokens) * $p[1] '
        "+ $number(cache_creation.ephemeral_5m_input_tokens) * $p[2] "
        "+ $number(cache_creation.ephemeral_1h_input_tokens) * $p[0] * 2 "
        "+ $number(cache_read_input_tokens) * $p[3]) / 1000000} ); "
        '$distinct($r.k).( $k := $; {"key": $k, "usd": $sum($r[k = $k].usd)} )')
    rows = {"options": {"orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
                        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": True}}}
    per_series = {"transformations": [{"id": "partitionByValues", "options": {
        "fields": ["workspace"], "naming": {"asLabels": True}}}]}
    billed_bars = {"fieldConfig": {"defaults": {"unit": "currencyUSD", "displayName": "${__field.labels.workspace}", "custom": {
        "drawStyle": "bars", "fillOpacity": 80, "stacking": {"mode": "normal", "group": "A"}}}, "overrides": []}}
    chat_tokens = (f'sum by (provider, model) (sum_over_time({CHAT_LOGS} | model!~"{PRICED_MODELS}" '
                   f'| unwrap input_tokens [$__range]))')
    panels = [
        # --- headline
        panel(1, "Scans and extraction (selected range)", [instant(llm_cost())],
              {"h": 5, "w": 5, "x": 0, "y": 0}, ptype="stat", extra=usd,
              desc="Every Anthropic call that goes through observability.record_llm_call, priced per model. "
                   "An estimate: a counter's first increment after a deploy is invisible to increase(), so "
                   "this reads slightly low. The invoice is the truth; see the last panel."),
        panel(2, "Chatbot (selected range)", [loki_instant(chat_cost())],
              {"h": 5, "w": 5, "x": 5, "y": 0}, ptype="stat", extra=usd,
              desc="From chatbot_usage log lines, so it only reaches back as far as log retention. "
                   "Anthropic models only - other providers are in the unpriced panel."),
        panel(3, "Scans run-rate, per 30 days", [instant(f"({llm_cost(window='7d')}) * 30 / 7")],
              {"h": 5, "w": 5, "x": 10, "y": 0}, ptype="stat", extra=usd,
              desc="The last 7 days scaled to a month. A backfill inside those 7 days inflates it."),
        panel(4, "Grafana Cloud overage", [instant("sum(grafanacloud_org_total_overage)", ds="DS_USAGE")],
              {"h": 5, "w": 4, "x": 15, "y": 0}, ptype="stat", extra=usd,
              desc="What Grafana Cloud would bill beyond the included plan, for the whole shared stack."),
        panel(5, "Share of input served from cache",
              [instant(f'(sum(increase(schoolz_llm_tokens_total{sel(CACHE_READ)}[$__range])) or vector(0)) / '
                       f'sum(increase(schoolz_llm_tokens_total{sel(ANY_INPUT)}[$__range]))')],
              {"h": 5, "w": 5, "x": 19, "y": 0}, ptype="stat", unit="percentunit",
              desc="Scans and extraction only. Near zero is expected today: no scan sets a cache breakpoint. "
                   "It is the cheapest lever if a purpose grows."),
        # --- by cost centre
        panel(6, "Spend by purpose (selected range)", [instant(llm_cost("purpose"), "{{purpose}}")],
              {"h": 10, "w": 8, "x": 0, "y": 5}, ptype="bargauge", extra={**usd, **bars},
              desc="The cost centres that exist in code today. One purpose per call site."),
        panel(7, "Spend per day, by purpose", [target(llm_cost("purpose", "1d"), "{{purpose}}")],
              {"h": 10, "w": 16, "x": 8, "y": 5}, extra={**stacked, "interval": "1d"},
              desc="A one-off (a translation backfill, a new district's first extraction) is a single tall bar; "
                   "a standing cost is a floor that never goes away."),
        panel(8, "Spend by process", [instant(llm_cost("service_name"), "{{service_name}}")],
              {"h": 7, "w": 8, "x": 0, "y": 15}, ptype="bargauge", extra={**usd, **bars},
              desc="scheduler = unattended scans. api = work a person triggered (run-now, translation, kids view). "
                   "Both processes share one key today, so this split exists only here, not on the invoice."),
        panel(9, "Spend by model", [instant(llm_cost("model"), "{{model}}")],
              {"h": 7, "w": 8, "x": 8, "y": 15}, ptype="bargauge", extra={**usd, **bars}),
        panel(10, "Cost per call, by purpose",
              [instant(f"({llm_cost('purpose')}) / sum by (purpose) (increase(schoolz_llm_calls_total{sel()}[$__range]) > 0)",
                       "{{purpose}}")],
              {"h": 7, "w": 8, "x": 16, "y": 15}, ptype="bargauge",
              extra={"fieldConfig": {"defaults": {"unit": "currencyUSD", "decimals": 4, "custom": {}}, "overrides": []}, **bars},
              desc="Which call is expensive each time, as opposed to merely frequent."),
        panel(11, "Tokens per day, by direction",
              [target(f"sum by (direction) (increase(schoolz_llm_tokens_total{sel()}[1d]))", "{{direction}}")],
              {"h": 8, "w": 12, "x": 0, "y": 22}, extra={"interval": "1d"},
              desc="Output costs five times input on every model, so a rising output line matters most."),
        panel(12, "Calls per day, by purpose",
              [target(f"sum by (purpose) (increase(schoolz_llm_calls_total{sel()}[1d]))", "{{purpose}}")],
              {"h": 8, "w": 12, "x": 12, "y": 22}, extra={"interval": "1d"}),
        # --- chatbot
        panel(13, "Chatbot spend per day, by model",
              [loki_target(chat_cost("provider, model", "1d"))],
              {"h": 8, "w": 8, "x": 0, "y": 30}, extra={**stacked, "interval": "1d"},
              desc="Anonymous and signed-in turns are not told apart in the log line yet, so neither is this."),
        panel(14, "Chatbot turns per day, by model",
              [loki_target(f"sum by (provider, model) (count_over_time({CHAT_LOGS} [1d]))")],
              {"h": 8, "w": 8, "x": 8, "y": 30}, extra={"interval": "1d"}),
        panel(15, "Chatbot tokens on unpriced models (selected range)",
              [loki_instant(chat_tokens)],
              {"h": 8, "w": 8, "x": 16, "y": 30}, ptype="bargauge", extra=bars,
              desc="Input tokens sent to a model with no row in MODEL_PRICES (Gemini and the other "
                   "non-Anthropic providers). Billed by that provider, absent from every dollar figure here."),
        # --- what drove it
        panel(16, "Job runs and machine time, by kind (selected range)",
              [sql_target(
                  "SELECT j.kind AS \"Kind\", count(*) AS \"Runs\",\n"
                  "  count(*) FILTER (WHERE r.triggered_by <> 'cron') AS \"Run by hand\",\n"
                  "  round(sum(r.duration_ms) / 60000.0, 1) AS \"Minutes\",\n"
                  "  round(avg(r.duration_ms) / 1000.0, 1) AS \"Avg seconds\"\n"
                  "FROM job_runs r JOIN scheduled_jobs j ON j.id = r.job_id\n"
                  "WHERE $__timeFilter(r.started_at)\n"
                  "GROUP BY 1 ORDER BY 4 DESC NULLS LAST;")],
              {"h": 10, "w": 12, "x": 0, "y": 38}, ptype="table",
              desc="Fly bills the scheduler and scraper machines flat, so this is not dollars - it is which "
                   "scan kinds would force a bigger machine, and how much of the volume is hand-triggered."),
        # --- the observability bill itself
        panel(17, "Grafana Cloud: used / included",
              [used("metric series", "grafanacloud_org_metrics_billable_series", "grafanacloud_org_metrics_included_series", "A"),
               used("logs", "grafanacloud_org_logs_usage", "grafanacloud_org_logs_included_usage", "B"),
               used("traces", "grafanacloud_org_traces_usage", "grafanacloud_org_traces_included_usage", "C"),
               used("RUM sessions", "grafanacloud_org_fe_o11y_billable_sessions", "grafanacloud_org_fe_o11y_included_sessions", "D"),
               used("synthetic checks", "grafanacloud_org_sm_billable_check_executions", "grafanacloud_org_sm_included_check_executions", "E"),
               used("IRM users", "grafanacloud_org_irm_users", "grafanacloud_org_irm_included_users", "F"),
               used("Grafana users", "grafanacloud_org_grafana_billable_users", "grafanacloud_org_grafana_included_users", "G")],
              {"h": 10, "w": 6, "x": 12, "y": 38}, ptype="bargauge", extra={**quota, **bars},
              desc="Over 100% is past the plan's allowance. The stack is shared, so this is every app on it."),
        panel(18, "Active series by app",
              [instant('sort_desc(count by (service_namespace) ({__name__=~".+"}))', "{{service_namespace}}")],
              {"h": 10, "w": 6, "x": 18, "y": 38}, ptype="bargauge", extra=bars,
              desc="Who is using the series allowance. The unlabelled bar is everything with no service_namespace."),
        # --- the invoice
        panel(20, "Billed by Anthropic (selected range)",
              [billing_target("cost_report?group_by[]=description",
                              '{"usd": $sum(data.results.($number(amount))) / 100}', [("usd", "number")])],
              {"h": 5, "w": 6, "x": 0, "y": 48}, ptype="stat", extra=usd,
              desc="What the account was actually charged, for every workspace and app on it - not only schoolz. "
                   "The estimates above should sit a little under schoolz-prod's share of this. "
                   "Reaches back 31 days at most."),
        panel(21, "Billed by model",
              [billing_target("cost_report?group_by[]=description",
                              billed_by("model", '$type(model) = "string" ? model : description'),
                              [("model", "string"), ("usd", "number")])],
              {"h": 5, "w": 6, "x": 0, "y": 53}, ptype="bargauge", extra={**usd, **rows}),
        panel(22, "Billed per day, by workspace",
              [billing_target("cost_report?group_by[]=workspace_id",
                              'data.( $t := starting_at; results.{"time": $t, "workspace": $name(workspace_id), '
                              '"usd": $number(amount) / 100} )',
                              [("time", "timestamp"), ("workspace", "string"), ("usd", "number")])],
              {"h": 10, "w": 18, "x": 6, "y": 48}, extra={**billed_bars, **per_series},
              desc="A workspace is a cost centre with its own spend limit: one per app and environment."),
        panel(23, "Billed by workspace (selected range)",
              [billing_target("cost_report?group_by[]=workspace_id", billed_by("workspace", "$name(workspace_id)"),
                              [("workspace", "string"), ("usd", "number")])],
              {"h": 8, "w": 8, "x": 0, "y": 58}, ptype="bargauge", extra={**usd, **rows}),
        panel(24, "Spend by API key (selected range, priced from tokens)",
              [billing_target("usage_report/messages?bucket_width=1d&group_by[]=api_key_id&group_by[]=model", by_key,
                              [("key", "string"), ("usd", "number")])],
              {"h": 8, "w": 16, "x": 8, "y": 58}, ptype="bargauge", extra={**usd, **rows},
              desc="The cost report cannot be split by key, so this prices Anthropic's own token counts per key "
                   "with the list prices in MODEL_PRICES. Scans, person-triggered work, public chat and "
                   "signed-in chat each have a key."),
        panel(19, "Not on this dashboard yet", [], {"h": 8, "w": 24, "x": 0, "y": 66}, ptype="text",
              extra={"options": {"mode": "markdown", "content": NOT_METERED}}),
    ]
    d = dashboard(
        "schoolz-cost", "schoolz / Cost",
        "What schoolz spends on models and observability, split by cost centre, and what is not metered yet.",
        panels,
        [ds_var("DS_METRICS", "prometheus", "Metrics"),
         ds_var("DS_LOGS", "loki", "Logs"),
         ds_var("DS_SQL", "grafana-postgresql-datasource", "schoolz database"),
         ds_var("DS_USAGE", "prometheus", "Grafana Cloud usage"),
         ds_var("DS_ANTHROPIC", "yesoreyeram-infinity-datasource", "Anthropic billing")],
    )
    d["time"] = {"from": "now-30d", "to": "now"}
    d["refresh"] = "1h"
    return d


NOT_METERED = """\
| Cost centre | Why it is missing | What closes the gap |
|---|---|---|
| **Coding-agent sessions** (the largest by far) | Billed to a subscription, never touches this stack | Turn on the agent's own OpenTelemetry export to this stack, tagged with the project name |
| **Gemini and other chat providers** | No price row; billed by that provider | Their own billing export, or a price row in `MODEL_PRICES` |
| **Fly, Supabase, the scraper droplet, domains** | Flat monthly charges with no usage signal | Nothing to meter; enter them once as constants if a single total is wanted |
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in (("scans", scans), ("api", api), ("user-experience", ux), ("operations", ops),
                        ("cost", cost)):
        path = OUT / f"schoolz-{name}.json"
        path.write_text(json.dumps(build(), indent=2) + "\n")
        print(f"wrote {path.relative_to(OUT.parent.parent)}")


if __name__ == "__main__":
    main()
