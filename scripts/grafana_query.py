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
    cands.sort(key=lambda d: not d["name"].startswith("grafanacloud-"))
    if not cands:
        sys.exit(f"no {kind} datasource")
    return cands[0]["uid"]


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
        lines = sorted(((ts, line) for st in res for ts, line in st["values"]), reverse=True)[:40]
        if not lines:
            print("  (no lines)")
        for ts, line in lines:
            stamp = time.strftime("%m-%d %H:%M:%S", time.gmtime(int(ts) / 1e9))
            print(f"  {stamp}  {line[:300]}")
    else:
        print("  unknown prefix; use prom: or logs:")
