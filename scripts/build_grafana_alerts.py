#!/usr/bin/env python3
"""Generates Grafana-managed alert rules into grafana/cloud-dashboards/alerts.json.

Same reasoning as the dashboard builder: the provisioning API's rule shape
is verbose and repetitive (every rule carries a query stage plus reduce and
threshold stages), so the thresholds live here as one line each and the
JSON is generated.

Every rule is namespace-filtered to schoolz - the Grafana Cloud stack is
shared with billz, and an unfiltered rule would page on billz's traffic.

Run: python3 scripts/build_grafana_alerts.py
"""
import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "grafana" / "cloud-dashboards" / "alerts.json"

FOLDER = "schoolz"
GROUP = "schoolz-alerts"
NS = 'service_namespace="schoolz"'
ERRORED = 'status="error"'
SERVER_ERROR = 'http_response_status_code=~"5.."'
TRUNCATED = 'stop_reason="max_tokens"'


def sel(*extra: str) -> str:
    """PromQL selector, always namespace-filtered (stack shared with billz)."""
    return "{" + ", ".join([NS, *extra]) + "}"


def rule(uid, title, expr, threshold, summary, *, op="gt", for_="10m", no_data="OK") -> dict:
    """One threshold rule: query -> reduce(last) -> threshold.

    `no_data` is per-rule on purpose. Most rules should stay quiet when a
    series is absent (a job kind that hasn't run in the window isn't a
    failure), but the scheduler heartbeat must do the opposite: absent
    data there is the outage.
    """
    return {
        "uid": uid,
        "title": title,
        "condition": "C",
        "for": for_,
        "labels": {"app": "schoolz", "severity": "warning"},
        "annotations": {"summary": summary},
        "noDataState": no_data,
        "execErrState": "Error",
        "orgId": 1,
        "folderUID": FOLDER,
        "ruleGroup": GROUP,
        "data": [
            {
                "refId": "A",
                "relativeTimeRange": {"from": 3600, "to": 0},
                "datasourceUid": "${DS_METRICS}",
                "model": {"refId": "A", "expr": expr, "instant": True, "editorMode": "code"},
            },
            {
                "refId": "B",
                "datasourceUid": "__expr__",
                "model": {"refId": "B", "type": "reduce", "reducer": "last", "expression": "A"},
            },
            {
                "refId": "C",
                "datasourceUid": "__expr__",
                "model": {
                    "refId": "C",
                    "type": "threshold",
                    "expression": "B",
                    "conditions": [{"evaluator": {"type": op, "params": [threshold]}}],
                },
            },
        ],
    }


def rules() -> list:
    return [
        rule(
            "schoolz-scheduler-down",
            "schoolz: scheduler has stopped reconciling",
            f"sum(increase(schoolz_scheduler_reconciles_total{sel()}[10m]))",
            1,
            "The scheduler process hasn't ticked in 10 minutes - every scan is silently stopped. "
            "It reconciles every 30s, so this should never be below 1.",
            op="lt",
            for_="10m",
            # The whole point of this rule: if the process is dead its series
            # disappears, and "no data" IS the outage.
            no_data="Alerting",
        ),
        rule(
            "schoolz-job-error-ratio",
            "schoolz: scan failure ratio above 30%",
            f"sum(increase(schoolz_job_runs_total{sel(ERRORED)}[12h]))"
            f" / clamp_min(sum(increase(schoolz_job_runs_total{sel()}[12h])), 1)",
            0.30,
            "More than 30% of scans failed over the last 12h window (one full scan cycle). "
            "Check the Scans dashboard's failures-by-error-code panel.",
            for_="30m",
        ),
        rule(
            "schoolz-api-5xx",
            "schoolz: API 5xx ratio above 2%",
            f"sum(rate(http_server_request_duration_seconds_count{sel(SERVER_ERROR)}[10m]))"
            f" / clamp_min(sum(rate(http_server_request_duration_seconds_count{sel()}[10m])), 0.001)",
            0.02,
            "The API is returning server errors to real visitors.",
        ),
        rule(
            "schoolz-api-latency",
            "schoolz: public GET p95 above 1.5s",
            f"histogram_quantile(0.95, sum by (le) (rate(http_server_request_duration_seconds_bucket{sel()}[10m])))",
            1.5,
            "The site feels slow. Check whether it's cold starts or a specific route on the API dashboard.",
            for_="15m",
        ),
        rule(
            "schoolz-llm-truncated",
            "schoolz: an LLM reply was truncated (max_tokens)",
            f"sum(increase(schoolz_llm_calls_total{sel(TRUNCATED)}[1h]))",
            0,
            "An extraction hit the output cap and was cut off mid-structure. This has silently produced "
            "zero extracted items from a full newsletter before - the run won't necessarily look failed.",
            for_="5m",
        ),
        rule(
            "schoolz-scraper-failing",
            "schoolz: scraper failing more than 30% of page loads",
            'sum(rate(schoolz_scraper_page_load_seconds_count{service_name="schoolz-scraper", outcome="error"}[1h])) '
            '/ clamp_min(sum(rate(schoolz_scraper_page_load_seconds_count{service_name="schoolz-scraper"}[1h])), 0.001)',
            0.30,
            "Most scraper fetches are failing - either the scraper machine is unhealthy or a lot of school "
            "sites are unreachable. Scans will be returning warnings rather than data.",
            for_="30m",
        ),
        rule(
            "schoolz-parse-issues",
            "schoolz: parse issues spiking",
            f"sum(increase(schoolz_parse_issues_total{sel()}[6h]))",
            50,
            "Scans are succeeding but dropping an unusual amount of content. This is the failure mode that "
            "doesn't turn anything red - coverage degrades quietly.",
            for_="1h",
        ),
    ]


def main() -> None:
    OUT.write_text(json.dumps({"apiVersion": 1, "groups": [
        {"orgId": 1, "name": GROUP, "folder": FOLDER, "interval": "5m", "rules": rules()}
    ]}, indent=2) + "\n")
    print(f"wrote {OUT.name} ({len(rules())} rules)")


if __name__ == "__main__":
    main()
