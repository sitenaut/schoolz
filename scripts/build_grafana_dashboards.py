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
    ]
    return dashboard(
        "schoolz-ux", "schoolz / User experience",
        "Did anyone come, where from, did they convert, and did the site work for them.",
        panels,
        [ds_var("DS_METRICS", "prometheus", "Metrics"),
         ds_var("DS_LOGS", "loki", "Logs (Faro RUM)"),
         ds_var("DS_SQL", "grafana-postgresql-datasource", "schoolz database")],
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, build in (("scans", scans), ("api", api), ("user-experience", ux)):
        path = OUT / f"schoolz-{name}.json"
        path.write_text(json.dumps(build(), indent=2) + "\n")
        print(f"wrote {path.relative_to(OUT.parent.parent)}")


if __name__ == "__main__":
    main()
