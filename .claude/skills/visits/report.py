#!/usr/bin/env python3
"""Prints the prod visit report from page_visits (GET /page-views).

    python3 .claude/skills/visits/report.py [days]     # default 10

Needs a prod API key with analytics.view in env/api-keys.env
(scripts/schoolz-api.sh login prod). Counts are visits per day (Eastern),
never people: page_visits is aggregate-only by design.
"""
import collections
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
TZ = ZoneInfo("America/New_York")
days = int(sys.argv[1]) if len(sys.argv) > 1 else 10

out = subprocess.run(
    ["bash", str(ROOT / "scripts/schoolz-api.sh"), "prod", "GET", f"/page-views?days={days}"],
    capture_output=True, text=True,
)
body, _, status = out.stdout.rpartition("\nHTTP ")
if out.returncode != 0 or status.strip() != "200":
    sys.exit(f"API call failed (HTTP {status.strip() or '?'}): {(body or out.stderr).strip()[:300]}\n"
             "403 means the saved key lacks analytics.view - run: bash scripts/schoolz-api.sh login prod")
rows = json.loads(body)["rows"]

now = datetime.now(TZ)
today = now.strftime("%Y-%m-%d")
yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

by_day = collections.defaultdict(collections.Counter)
by_path = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
for r in rows:
    by_day[r["day"]][r["source"]] += r["count"]
    by_path[r["day"]][r["path"]][r["source"]] += r["count"]


# "team" is a browser flagged as the team's own. Older rows say "internal",
# which only ever meant a session that started from one of our own pages
# (now "self") - real visitors, so it counts as outside.
TEAM = "team"


def outside(c: collections.Counter) -> int:
    return sum(c.values()) - c.get(TEAM, 0)


def group(path: str) -> int:
    """Sort order: site pages, then /budgets and each district's budget page, then school pages."""
    if path == "/budgets" or path.startswith("/budgets/"):
        return 1
    return 2 if path.startswith("/schools/") else 0


print(f"As of {now:%a %b %-d, %-I:%M %p} Eastern\n")
print("## Daily (outside = everything but 'team', the team's flagged browsers)")
print(f"{'day':<16}{'outside':>8}{'team':>6}  sources (outside)")
for day in sorted(by_day):
    c = by_day[day]
    label = datetime.strptime(day, "%Y-%m-%d").strftime("%a %b %-d")
    if day == today:
        label += " *"
    srcs = ", ".join(f"{s} {n}" for s, n in c.most_common() if s != TEAM)
    print(f"{label:<16}{outside(c):>8}{c.get(TEAM, 0):>6}  {srcs}")
print("(* today, partial)\n")

for day, name in ((yesterday, "Yesterday"), (today, "Today so far")):
    paths = by_path.get(day)
    if not paths:
        print(f"## {name}: no visits\n")
        continue
    print(f"## {name} by page (outside visits; budget pages, then school pages, at the bottom)")
    ordered = sorted(paths.items(), key=lambda kv: (group(kv[0]), -outside(kv[1])))
    for path, c in ordered:
        if outside(c) == 0:
            continue
        srcs = ", ".join(f"{s} {n}" for s, n in c.most_common() if s != TEAM)
        print(f"  {path:<45}{outside(c):>4}  {srcs}")
    budgets = sum(outside(c) for p, c in paths.items() if group(p) == 1)
    schools = sum(outside(c) for p, c in paths.items() if group(p) == 2)
    print(f"  {'(all budget pages)':<45}{budgets:>4}")
    print(f"  {'(all school pages)':<45}{schools:>4}\n")
