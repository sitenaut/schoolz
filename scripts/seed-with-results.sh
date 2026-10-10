#!/usr/bin/env bash
# Import a seed file into <target> together with what the local stack's
# scans already extracted for its districts, so the target's first runs find
# those sources done instead of paying for the same model calls again.
#
#   scripts/seed-with-results.sh prod backend/seed/<district>.json
#
# Results come from GET /admin/config/results on local and ride along as
# `results` in one POST /admin/config/import: one transaction, because a new
# job's first run starts within ~30s of the import. Needs an API key for both
# sides (scripts/schoolz-api.sh login local, ... login prod).
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: $0 <prod|local> <seed.json>" >&2
  exit 2
fi
target=$1 seed=$2
root=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

query=$(python3 - "$seed" <<'PY'
import json, sys, urllib.parse

seed = json.load(open(sys.argv[1]))
names = [d["name"] for d in seed.get("districts", [])] + [s.get("district_name") for s in seed.get("schools", [])]
names = list(dict.fromkeys(n for n in names if n))
if not names:
    sys.exit("seed names no district")
print(urllib.parse.urlencode([("district", n) for n in names]))
PY
)

"$root/scripts/schoolz-api.sh" local GET "/admin/config/results?$query" > "$tmp/results.raw"

python3 - "$seed" "$tmp/results.raw" "$tmp/bundle.json" <<'PY'
import json, sys

seed_path, raw_path, out_path = sys.argv[1:4]
body, _, status = open(raw_path).read().rstrip("\n").rpartition("\nHTTP ")
if status != "200":
    sys.exit(f"local results export failed (HTTP {status}): {body[:300]}")
results = json.loads(body)
seed = json.load(open(seed_path))
seed["results"] = results
with open(out_path, "w") as f:
    json.dump(seed, f)
blocks = sum(len(n["blocks"]) for n in results["newsletters"]) + sum(len(s["givebacks_blocks"]) for s in results["schools"])
menus = sum(len(d["lunch_menus"]) for d in results["districts"]) + sum(len(s["lunch_menus"]) for s in results["schools"])
print(
    f"Carrying {len(results['newsletters'])} newsletter(s), {blocks} block(s), {menus} lunch menu(s), "
    f"{sum(1 for d in results['districts'] if d['calendar_pdf_items'])} calendar PDF(s), "
    f"{sum(1 for s in results['schools'] if s['contact_staff'])} contact page(s).",
    file=sys.stderr,
)
PY

"$root/scripts/schoolz-api.sh" "$target" POST /admin/config/import "$tmp/bundle.json"
