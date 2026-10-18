#!/usr/bin/env python3
"""Runs read-only PromQL / LogQL queries against Grafana Cloud's Mimir and Loki.

Each argument is one query, prefixed with its language:

    prom:<promql>            instant query, prints every series and value
    logs:<hours>:<logql>     newest 40 lines from the last <hours> hours

Needs GRAFANA_URL and GRAFANA_TOKEN in the environment:

    bash scripts/prod-secrets.sh run --reason "..." --secrets GRAFANA_URL,GRAFANA_TOKEN \\
      -- op run --env-file env.op/grafana.prod.env -- python3 scripts/grafana_query.py 'prom:up' 'logs:2:{service_name="x"}'

The stack is shared with billz and the scraper repo; datasources are resolved by type, preferring Grafana Cloud's own.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

url = os.environ.get("GRAFANA_URL", "").rstrip("/")
token = os.environ.get("GRAFANA_TOKEN", "")
if not url or not token:
    sys.exit("GRAFANA_URL and GRAFANA_TOKEN must be set")


def get(path: str, params: dict | None = None):
    q = f"?{urllib.parse.urlencode(params)}" if params else ""
    req = urllib.request.Request(f"{url}{path}{q}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def datasource(kind: str) -> str:
    cands = [d for d in get("/api/datasources") if d["type"] == kind]
    # A stack has several grafanacloud-* Loki sources (alert state history,
    # usage insights) besides the logs one; picking the first of those
    # returned "(no lines)" for events that were there. Prefer *-logs / *-prom.
    suffix = {"loki": "-logs", "prometheus": "-prom"}.get(kind, "")
    cands.sort(key=lambda d: (not d["name"].startswith("grafanacloud-"), not d["name"].endswith(suffix)))
    if not cands:
        sys.exit(f"no {kind} datasource")
    print(f"  ({kind} datasource: {cands[0]['name']})")
    return cands[0]["uid"]


# Stream labels every schoolz line carries; what's left is the line's own
# structured metadata (the `extra=` fields), which is what's worth reading.
_COMMON = {"service_name", "service_namespace", "service_version", "deployment_environment", "detected_level",
           "level", "severity_text", "severity_number", "telemetry_sdk_language", "telemetry_sdk_name",
           "telemetry_sdk_version", "host_name", "host_arch", "os_type", "os_description", "process_pid",
           "process_runtime_name", "process_runtime_version", "process_runtime_description",
           "process_executable_name", "process_executable_path", "process_command", "process_command_args",
           "process_command_line", "process_owner", "observed_timestamp", "scope_name", "code_file_path",
           "code_filepath", "code_function_name", "code_function", "code_line_number", "code_lineno",
           "otelServiceName", "otelSpanID", "otelTraceID", "otelTraceSampled", "flags", "trace_id", "span_id",
           "cloud_region", "cloud_provider", "fly_app_name", "fly_region", "fly_machine_id", "fly_process_group"}


prom = logs = None
for arg in sys.argv[1:]:
    lang, _, rest = arg.partition(":")
    print(f"\n### {arg}")
    if lang == "prom":
        prom = prom or datasource("prometheus")
        data = get(f"/api/datasources/proxy/uid/{prom}/api/v1/query", {"query": rest})["data"]["result"]
        if not data:
            print("  (no series)")
        for s in data:
            labels = {k: v for k, v in s["metric"].items() if k != "__name__"}
            print(f"  {s['value'][1]}  {labels}")
    elif lang == "logs":
        logs = logs or datasource("loki")
        hours, _, logql = rest.partition(":")
        now = time.time_ns()
        res = get(f"/api/datasources/proxy/uid/{logs}/loki/api/v1/query_range",
                  {"query": logql, "start": now - int(float(hours) * 3600e9), "end": now,
                   "limit": 40, "direction": "backward"})["data"]["result"]
        lines = sorted(((ts, line, st.get("stream", {})) for st in res for ts, line in st["values"]),
                       key=lambda x: x[0], reverse=True)[:40]
        if not lines:
            print("  (no lines)")
        for ts, line, stream in lines:
            stamp = time.strftime("%m-%d %H:%M:%S", time.gmtime(int(ts) / 1e9))
            fields = " ".join(f"{k}={v}" for k, v in sorted(stream.items()) if k not in _COMMON)
            print(f"  {stamp}  {line[:200]}  {fields[:600]}")
    else:
        print("  unknown prefix; use prom: or logs:")
