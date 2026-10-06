#!/usr/bin/env python3
"""Generates the Grafana SLO definitions into grafana/cloud-dashboards/slos.json.

The objectives live in build_grafana_alerts.py's SLOS list, next to the
burn-rate alerts written against them, so a target can't be changed in one
place and not the other.

The SLO app's own alerting is deliberately left off: it writes
datasource-managed rules that fire into the Mimir alertmanager, which the
notification policy (and so IRM) never sees. The burn-rate alerts are
ordinary Grafana-managed rules instead - see `burn()` in the alerts builder.

Run: python3 scripts/build_grafana_slos.py
"""
import json
import pathlib

from build_grafana_alerts import SLOS

OUT = pathlib.Path(__file__).resolve().parent.parent / "grafana" / "cloud-dashboards" / "slos.json"


def slo(spec: dict) -> dict:
    ratio = (f'sum(rate({spec["good"]}[$__rate_interval]))'
             f' / sum(rate({spec["total"]}[$__rate_interval]))')
    return {
        # The app only accepts lower-case alphanumerics, 21 characters at most.
        "uuid": spec["uuid"],
        "name": f'schoolz {spec["name"]}',
        "description": spec["meaning"],
        "query": {"type": "freeform", "freeform": {"query": ratio}},
        "objectives": [{"value": spec["objective"], "window": "28d"}],
        "labels": [{"key": "app", "value": "schoolz"}, {"key": "component", "value": spec["component"]}],
        "destinationDatasource": {"uid": "${DS_METRICS}"},
        "folder": {"uid": "schoolz"},
    }


def main() -> None:
    OUT.write_text(json.dumps({"slos": [slo(s) for s in SLOS]}, indent=2) + "\n")
    print(f"wrote {OUT.name} ({len(SLOS)} SLOs)")


if __name__ == "__main__":
    main()
