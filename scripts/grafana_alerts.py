#!/usr/bin/env python3
"""Lists Grafana-managed alerts that are firing or pending, across the whole stack.

Read-only. Needs GRAFANA_URL and GRAFANA_TOKEN in the environment:

    bash scripts/prod-secrets.sh run --reason "check firing alerts" --secrets GRAFANA_URL,GRAFANA_TOKEN \\
      -- op run --env-file env.op/grafana.prod.env -- python3 scripts/grafana_alerts.py

The stack is shared with billz and the scraper repo, so the folder column says whose rule it is.
"""
import json
import os
import sys
import urllib.request

url = os.environ.get("GRAFANA_URL", "").rstrip("/")
token = os.environ.get("GRAFANA_TOKEN", "")
if not url or not token:
    sys.exit("GRAFANA_URL and GRAFANA_TOKEN must be set")

req = urllib.request.Request(f"{url}/api/prometheus/grafana/api/v1/rules",
                             headers={"Authorization": f"Bearer {token}"})
with urllib.request.urlopen(req, timeout=30) as resp:
    groups = json.load(resp)["data"]["groups"]

rows = []
for g in groups:
    for r in g.get("rules", []):
        for a in r.get("alerts") or []:
            state = a.get("state", "").lower()
            if state.startswith(("alerting", "firing", "pending", "nodata", "error")):
                skip = {"alertname", "grafana_folder", "app", "tier", "kind", "component", "__alert_rule_uid__"}
                where = " ".join(f"{k}={v}" for k, v in sorted(a.get("labels", {}).items()) if k not in skip)
                rows.append((g.get("file", ""), r.get("name", ""), state, where, (a.get("activeAt") or "")[:16]))

total = sum(len(g.get("rules", [])) for g in groups)
print(f"{total} rules in {len(groups)} groups; {len(rows)} alert instances not normal")
for row in sorted(rows):
    print("  " + " | ".join(row))
