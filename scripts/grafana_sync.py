#!/usr/bin/env python3
"""Pushes the generated dashboards, alert rules, SLOs and alert routing into Grafana.

Usage:
    python3 scripts/grafana_sync.py            # everything
    python3 scripts/grafana_sync.py --dry-run  # show what would happen
    python3 scripts/grafana_sync.py --only dashboards,alerts   # or slos, routing

Credentials come from env/secrets.prod.env (gitignored):
    GRAFANA_URL=https://<stack>.grafana.net
    GRAFANA_TOKEN=glsa_...
    GRAFANA_CLOUDWATCH_ACCESS_KEY_ID / _SECRET_ACCESS_KEY   (optional)
    GRAFANA_ALERT_EMAIL                                     (optional)

Create the token at: Grafana -> Administration -> Users and access ->
Service accounts -> Add service account (Admin) -> Add service account token.
The same token drives IRM's API.

Everything is written into a "schoolz" folder. The stack is shared with
billz and the scraper, so this script never touches anything outside that
folder, resolves datasource UIDs on this instance rather than assuming
them, and edits the one shared object - the notification policy tree - by
replacing only its own routes.

How an alert reaches a person (docs/RUNBOOK.md has the reasoning):

    rule label tier=page    -> IRM, "schoolz page" chain   (important rules, re-notifies)
    rule label tier=ticket  -> IRM, "schoolz ticket" chain (default rules, once)
    rule label tier=info    -> email, batched
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DASH_DIR = ROOT / "grafana" / "cloud-dashboards"
SECRETS = ROOT / "env" / "secrets.prod.env"
FOLDER_TITLE = "schoolz"
FOLDER_UID = "schoolz"


def load_env() -> dict:
    """Process environment first, then env/secrets.prod.env for anything unset."""
    wanted = ("GRAFANA_URL", "GRAFANA_TOKEN", "GRAFANA_ALERT_EMAIL",
              "GRAFANA_CLOUDWATCH_ACCESS_KEY_ID", "GRAFANA_CLOUDWATCH_SECRET_ACCESS_KEY")
    env = {key: os.getenv(key, "") for key in wanted}
    if SECRETS.exists():
        for line in SECRETS.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() in env and not env[key.strip()]:
                env[key.strip()] = value.strip()
    if not env["GRAFANA_URL"] or not env["GRAFANA_TOKEN"]:
        sys.exit(
            "GRAFANA_URL / GRAFANA_TOKEN not set.\n"
            "Add them to env/secrets.prod.env - see this script's docstring for where to "
            "generate the token."
        )
    env["GRAFANA_URL"] = env["GRAFANA_URL"].rstrip("/")
    return env


def request(base: str, path: str, method: str, body, headers: dict) -> tuple[int, object]:
    """One HTTP call. Returns (status, parsed body) and never raises on an
    HTTP error, so callers can tell "not there yet" from "broken"."""
    req = urllib.request.Request(
        f"{base}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw[:400]


def call(url: str, token: str, path: str, method: str = "GET", body=None, headers: dict | None = None):
    status, parsed = request(url, path, method, body, {"Authorization": f"Bearer {token}", **(headers or {})})
    if status >= 300:
        raise SystemExit(f"{method} {path} failed: HTTP {status}\n{str(parsed)[:400]}")
    return parsed


# Provisioned objects are read-only in the UI unless this header says
# otherwise; allowing UI edits means a threshold can be tuned during an
# incident without a deploy.
EDITABLE = {"X-Disable-Provenance": "true"}


def resolve_datasources(url: str, token: str) -> dict:
    """Maps our ${DS_*} placeholders onto this instance's real datasource UIDs.

    Picked by type, preferring a name containing "schoolz" when an instance
    has several of a kind (the shared stack has billz's datasources too)."""
    # A Grafana Cloud stack ships several datasources of the same type -
    # three Loki ones (logs, alert-state-history, usage-insights) and two
    # Prometheus ones (the real store and Grafana's own usage metrics).
    # Picking "the first of the right type" silently lands on the wrong
    # one, so each placeholder carries what to prefer and what to rule out.
    wanted = {
        "DS_METRICS": {
            "types": ("prometheus",),
            "prefer": ("schoolz", "-prom"),
            "avoid": ("usage",),  # grafanacloud-usage is Grafana's own billing metrics
        },
        "DS_LOGS": {
            "types": ("loki",),
            "prefer": ("schoolz", "-logs"),
            # Both are Loki-typed but hold Grafana's own telemetry, not ours.
            "avoid": ("alert-state-history", "usage-insights"),
        },
        "DS_SQL": {
            "types": ("grafana-postgresql-datasource", "postgres"),
            "prefer": ("schoolz",),
            "avoid": (),
        },
        "DS_CLOUDWATCH": {"types": ("cloudwatch",), "prefer": ("schoolz",), "avoid": ()},
    }
    available = call(url, token, "/api/datasources")
    resolved = {}
    for placeholder, spec in wanted.items():
        matches = [d for d in available if d.get("type") in spec["types"]]
        matches = [
            d for d in matches
            if not any(bad in f"{d.get('name', '')}{d.get('uid', '')}".lower() for bad in spec["avoid"])
        ]
        if not matches:
            print(f"  ! no usable {spec['types'][0]} datasource - {placeholder} left unresolved")
            continue
        best = next(
            (m for p in spec["prefer"] for m in matches if p in f"{m.get('name', '')}{m.get('uid', '')}".lower()),
            matches[0],
        )
        resolved[placeholder] = best["uid"]
        print(f"  {placeholder} -> {best['name']} ({best['uid']})")
    return resolved


def substitute(obj, mapping: dict):
    """Replaces ${DS_X} placeholders with real UIDs, and drops the now-redundant
    datasource template variables so the dashboards open without a picker."""
    if isinstance(obj, dict):
        return {k: substitute(v, mapping) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute(v, mapping) for v in obj]
    if isinstance(obj, str):
        for placeholder, uid in mapping.items():
            obj = obj.replace(f"${{{placeholder}}}", uid)
    return obj


def ensure_cloudwatch(url: str, token: str, env: dict, dry: bool) -> None:
    """The Alexa skill is the only thing schoolz runs on AWS (one Lambda, one
    DynamoDB table). Created only when a key is supplied - it should be a
    read-only IAM user's, never an admin's."""
    key, secret = env["GRAFANA_CLOUDWATCH_ACCESS_KEY_ID"], env["GRAFANA_CLOUDWATCH_SECRET_ACCESS_KEY"]
    if not key or not secret:
        print("  no GRAFANA_CLOUDWATCH_* key in env - CloudWatch datasource and Alexa alerts skipped")
        return
    ds = {"uid": "schoolz-cloudwatch", "name": "schoolz-cloudwatch", "type": "cloudwatch", "access": "proxy",
          "jsonData": {"authType": "keys", "defaultRegion": "us-east-1"},
          "secureJsonData": {"accessKey": key, "secretKey": secret}}
    if dry:
        print("  would upsert datasource schoolz-cloudwatch")
        return
    status, _ = request(url, "/api/datasources/uid/schoolz-cloudwatch", "GET", None, {"Authorization": f"Bearer {token}"})
    if status == 200:
        call(url, token, "/api/datasources/uid/schoolz-cloudwatch", "PUT", ds)
    else:
        call(url, token, "/api/datasources", "POST", ds)
    print("  datasource schoolz-cloudwatch")


def runbook_url() -> str:
    """Where docs/RUNBOOK.md is browsable, derived from the checkout's own
    remote so no repository address is written into a tracked file."""
    try:
        remote = subprocess.run(["git", "-C", str(ROOT), "remote", "get-url", "origin"],
                                capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "docs/RUNBOOK.md"
    if remote.startswith("git@"):
        remote = "https://" + remote[4:].replace(":", "/", 1)
    if "@" in remote:  # a credential embedded in an https remote
        remote = "https://" + remote.split("@", 1)[1]
    return remote.removesuffix(".git") + "/blob/main/docs/RUNBOOK.md"


def sync_dashboards(url: str, token: str, mapping: dict, dry: bool) -> None:
    for path in sorted(DASH_DIR.glob("schoolz-*.json")):
        dashboard = substitute(json.loads(path.read_text()), mapping)
        # Keep the picker variables only when a UID couldn't be resolved.
        dashboard["templating"]["list"] = [
            v for v in dashboard["templating"]["list"] if v["name"] not in mapping
        ]
        if dry:
            print(f"  would upload {dashboard['title']} ({len(dashboard['panels'])} panels)")
            continue
        call(url, token, "/api/dashboards/db", "POST", {
            "dashboard": dashboard, "folderUid": FOLDER_UID, "overwrite": True,
            "message": "synced by scripts/grafana_sync.py",
        })
        print(f"  uploaded {dashboard['title']} ({len(dashboard['panels'])} panels)")


def sync_alerts(url: str, token: str, mapping: dict, dry: bool) -> None:
    alerts_path = DASH_DIR / "alerts.json"
    if not alerts_path.exists():
        print("no alerts.json - run scripts/build_grafana_alerts.py first")
        return
    mapping = {**mapping, "RUNBOOK_URL": runbook_url(), "GRAFANA_URL": url}
    wanted = set()
    for group in json.loads(alerts_path.read_text())["groups"]:
        for rule in group["rules"]:
            rule = substitute(rule, mapping)
            rule["folderUID"] = FOLDER_UID
            # A rule whose datasource isn't on this instance would only ever
            # sit in an error state; leave it out until the datasource exists.
            if any("${DS_" in q["datasourceUid"] for q in rule["data"]):
                print(f"  skipped (datasource missing): {rule['title']}")
                continue
            wanted.add(rule["uid"])
            if dry:
                print(f"  would upsert alert: {rule['title']}")
                continue
            status, detail = request(url, f"/api/v1/provisioning/alert-rules/{rule['uid']}", "PUT", rule,
                                     {"Authorization": f"Bearer {token}", **EDITABLE})
            if status == 409 and "provenance" in str(detail).lower():
                # Written by an earlier version of this script as a locked,
                # API-owned rule; it can only be replaced, not converted.
                call(url, token, f"/api/v1/provisioning/alert-rules/{rule['uid']}", "DELETE")
                status = 404
            if status == 404:
                call(url, token, "/api/v1/provisioning/alert-rules", "POST", rule, EDITABLE)
            elif status >= 300:
                raise SystemExit(f"alert {rule['uid']} failed: HTTP {status}\n{str(detail)[:400]}")
            print(f"  alert: {rule['title']}")
        if not dry and any(r["uid"] in wanted for r in group["rules"]):
            # A group created implicitly by its first rule evaluates every
            # minute; the interval can only be set on the group itself.
            path = f"/api/v1/provisioning/folder/{FOLDER_UID}/rule-groups/{group['name']}"
            current = call(url, token, path)
            current["interval"] = _seconds(group["interval"])
            call(url, token, path, "PUT", current, EDITABLE)
    # Rules this script created earlier and no longer generates. Scoped to the
    # schoolz folder and the schoolz- uid prefix so nothing made by hand, by
    # the SLO app, or by another repo is ever removed.
    for existing in call(url, token, "/api/v1/provisioning/alert-rules"):
        uid = existing["uid"]
        if existing.get("folderUID") == FOLDER_UID and uid.startswith("schoolz-") and uid not in wanted:
            if dry:
                print(f"  would delete retired alert: {existing['title']}")
                continue
            headers = {} if existing.get("provenance") else EDITABLE
            call(url, token, f"/api/v1/provisioning/alert-rules/{uid}", "DELETE", None, headers)
            print(f"  deleted retired alert: {existing['title']}")


def _seconds(interval: str) -> int:
    return int(interval[:-1]) * {"s": 1, "m": 60, "h": 3600}[interval[-1]]


def sync_slos(url: str, token: str, mapping: dict, dry: bool) -> None:
    slos_path = DASH_DIR / "slos.json"
    if not slos_path.exists():
        print("no slos.json - run scripts/build_grafana_slos.py first")
        return
    base = "/api/plugins/grafana-slo-app/resources/v1/slo"
    for slo in substitute(json.loads(slos_path.read_text()), mapping)["slos"]:
        if dry:
            print(f"  would upsert SLO: {slo['name']}")
            continue
        status, _ = request(url, f"{base}/{slo['uuid']}", "GET", None, {"Authorization": f"Bearer {token}"})
        if status == 200:
            call(url, token, f"{base}/{slo['uuid']}", "PUT", slo)
        else:
            call(url, token, base, "POST", slo)
        print(f"  SLO: {slo['name']}")


# --------------------------------------------------------------------------
# Routing: IRM escalation chains, contact points, notification policy
# --------------------------------------------------------------------------
IRM_CONTACT = "schoolz-irm"
EMAIL_CONTACT = "schoolz-info-email"
APP_MATCHER = ["app", "=", "schoolz"]
# Frontend Observability writes its own rules (web vitals, new JS errors)
# with no labels at all, so they can only be claimed by their folder.
RUM_MATCHER = ["grafana_folder", "=", "frontend-observability-alerts"]
PAGE_ROUTE = '{{ payload.commonLabels.tier == "page" }}'


def sync_irm(url: str, token: str, dry: bool) -> str | None:
    """Builds the IRM side and returns the integration's webhook URL.

    Create-if-missing only: escalation steps are the thing most likely to be
    tuned by hand in the IRM UI (who, how long to wait), and a sync must not
    quietly put them back."""
    settings = call(url, token, "/api/plugins/grafana-irm-app/settings")
    base = settings["jsonData"]["onCallApiUrl"].rstrip("/") + "/api/v1"
    headers = {"Authorization": token, "X-Grafana-URL": url}

    def irm(path: str, method: str = "GET", body=None):
        status, parsed = request(base, path, method, body, headers)
        if status >= 300:
            raise SystemExit(f"IRM {method} {path} failed: HTTP {status}\n{str(parsed)[:400]}")
        return parsed.get("results", parsed) if isinstance(parsed, dict) else parsed

    people = [u["id"] for u in irm("/users/") if u.get("role") == "admin"]
    if not people:
        print("  ! no IRM admin user to notify - open IRM once in the browser, then re-run")
        return None

    chains = {c["name"]: c["id"] for c in irm("/escalation_chains/")}
    # page: important rules (push + phone, set per person in IRM), and again
    # after 15 minutes if nobody has acknowledged. ticket: default rules, once.
    steps = {
        "schoolz page": [
            {"type": "notify_persons", "persons_to_notify": people, "important": True},
            {"type": "wait", "duration": 900},
            {"type": "notify_persons", "persons_to_notify": people, "important": True},
        ],
        "schoolz ticket": [
            {"type": "notify_persons", "persons_to_notify": people, "important": False},
        ],
    }
    for name, chain_steps in steps.items():
        if name in chains:
            print(f"  IRM escalation chain '{name}' exists (left as is)")
            continue
        if dry:
            print(f"  would create IRM escalation chain '{name}'")
            continue
        chains[name] = irm("/escalation_chains/", "POST", {"name": name})["id"]
        for position, step in enumerate(chain_steps):
            irm("/escalation_policies/", "POST", {"escalation_chain_id": chains[name], "position": position, **step})
        print(f"  IRM escalation chain '{name}' created ({len(chain_steps)} steps)")

    integration = next((i for i in irm("/integrations/") if i["name"] == "schoolz alerts"), None)
    if integration:
        print("  IRM integration 'schoolz alerts' exists (left as is)")
        return integration["link"]
    if dry:
        print("  would create IRM integration 'schoolz alerts' (page route + default ticket route)")
        return None
    integration = irm("/integrations/", "POST", {
        "type": "grafana_alerting", "name": "schoolz alerts",
        "description_short": "Every schoolz alert with tier=page or tier=ticket.",
        "default_route": {"escalation_chain_id": chains["schoolz ticket"]},
    })
    irm("/routes/", "POST", {
        "integration_id": integration["id"], "escalation_chain_id": chains["schoolz page"],
        "routing_type": "jinja2", "routing_regex": PAGE_ROUTE, "position": 0,
    })
    print("  IRM integration 'schoolz alerts' created")
    return integration["link"]


def upsert_contact_point(url: str, token: str, point: dict) -> None:
    status, detail = request(url, f"/api/v1/provisioning/contact-points/{point['uid']}", "PUT", point,
                             {"Authorization": f"Bearer {token}", **EDITABLE})
    if status == 404:
        call(url, token, "/api/v1/provisioning/contact-points", "POST", point, EDITABLE)
    elif status >= 300:
        raise SystemExit(f"contact point {point['uid']} failed: HTTP {status}\n{str(detail)[:400]}")
    print(f"  contact point {point['uid']}")


def sync_routing(url: str, token: str, env: dict, dry: bool) -> None:
    irm_link = sync_irm(url, token, dry)

    email = env["GRAFANA_ALERT_EMAIL"]
    if not email:
        # Reuse whatever address this stack already emails rather than ask
        # for one more secret that says the same thing.
        existing = call(url, token, "/api/v1/provisioning/contact-points")
        email = next((c["settings"].get("addresses") for c in existing
                      if c["type"] == "email" and c["settings"].get("addresses")), "")
    if dry:
        print(f"  would upsert contact points {IRM_CONTACT}, {EMAIL_CONTACT} and the app=schoolz policy route")
        return
    if not irm_link or not email:
        print("  ! routing not written: needs the IRM integration and an email address (GRAFANA_ALERT_EMAIL)")
        return
    upsert_contact_point(url, token, {"uid": IRM_CONTACT, "name": IRM_CONTACT, "type": "oncall",
                                      "settings": {"url": irm_link}, "disableResolveMessage": False})
    upsert_contact_point(url, token, {"uid": EMAIL_CONTACT, "name": EMAIL_CONTACT, "type": "email",
                                      "settings": {"addresses": email, "singleEmail": True},
                                      "disableResolveMessage": True})

    tier = lambda value: [["tier", "=", value]]
    ours = [
        {
            # Anything labelled app=schoolz with no tier still reaches a
            # person, as a ticket - a rule added by hand in the UI shouldn't
            # vanish into the root policy's empty receiver.
            "receiver": IRM_CONTACT, "object_matchers": [APP_MATCHER],
            "group_by": ["alertname", "component"],
            "group_wait": "1m", "group_interval": "30m", "repeat_interval": "1d",
            "routes": [
                {"receiver": IRM_CONTACT, "object_matchers": tier("page"),
                 "group_by": ["alertname", "component"],
                 "group_wait": "10s", "group_interval": "5m", "repeat_interval": "1h"},
                {"receiver": IRM_CONTACT, "object_matchers": tier("ticket"),
                 "group_by": ["alertname", "component"],
                 "group_wait": "2m", "group_interval": "30m", "repeat_interval": "1d"},
                # One email per alert name, however many routes or job kinds
                # are behind it, and a week before it says the same thing again.
                {"receiver": EMAIL_CONTACT, "object_matchers": tier("info"),
                 "group_by": ["alertname"],
                 "group_wait": "5m", "group_interval": "2h", "repeat_interval": "1w"},
            ],
        },
        {"receiver": EMAIL_CONTACT, "object_matchers": [RUM_MATCHER], "group_by": ["alertname"],
         "group_wait": "5m", "group_interval": "2h", "repeat_interval": "1w"},
    ]
    tree = call(url, token, "/api/v1/provisioning/policies")
    others = [r for r in tree.get("routes") or [] if r.get("object_matchers") not in ([APP_MATCHER], [RUM_MATCHER])]
    tree["routes"] = others + ours
    call(url, token, "/api/v1/provisioning/policies", "PUT", tree, EDITABLE)
    print(f"  notification policy: app=schoolz routed by tier (kept {len(others)} other routes)")


def main() -> None:
    parts = ("dashboards", "slos", "alerts", "routing")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", default=",".join(parts), help=f"comma-separated subset of: {', '.join(parts)}")
    args = parser.parse_args()
    only = set(args.only.split(","))
    if only - set(parts):
        parser.error(f"unknown part(s): {', '.join(sorted(only - set(parts)))}")

    env = load_env()
    url, token = env["GRAFANA_URL"], env["GRAFANA_TOKEN"]
    print(f"Grafana: {url}")
    if args.dry_run:
        print("(dry run - nothing will be written)")

    ensure_cloudwatch(url, token, env, args.dry_run)

    # Resolved even on a dry run: it's a read-only GET, it proves the token
    # actually works, and which datasources matched is the main thing worth
    # checking before writing anything (an unresolved DS_SQL means the eight
    # SQL panels would land empty).
    print("Resolving datasources...")
    mapping = resolve_datasources(url, token)

    if not args.dry_run:
        # Creating a folder that already exists returns 409 (conflict) or 412
        # (version-mismatch) depending on Grafana version - both mean "it's
        # already there", which is the normal case on every run after the
        # first. Only a genuinely new failure should stop the sync.
        try:
            call(url, token, "/api/folders", "POST", {"uid": FOLDER_UID, "title": FOLDER_TITLE})
            print(f"folder '{FOLDER_TITLE}' created")
        except SystemExit as exc:
            if "409" in str(exc) or "412" in str(exc) or "already exists" in str(exc):
                print(f"folder '{FOLDER_TITLE}' already exists")
            else:
                raise

    # Order matters: the burn-rate alerts read series the SLOs record, and
    # routing comes last so nothing notifies through a half-built rule set.
    if "dashboards" in only:
        sync_dashboards(url, token, mapping, args.dry_run)
    if "slos" in only:
        sync_slos(url, token, mapping, args.dry_run)
    if "alerts" in only:
        sync_alerts(url, token, mapping, args.dry_run)
    if "routing" in only:
        sync_routing(url, token, env, args.dry_run)


if __name__ == "__main__":
    main()
