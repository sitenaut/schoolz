#!/usr/bin/env bash
# Import a seed file into <target> together with what the local stack's
# scans already extracted for its districts, so the target's first runs find
# those sources done instead of paying for the same model calls again.
#
#   scripts/seed-with-results.sh prod backend/seed/<district>.json
#
# Results are read straight from the local stack's database inside the api
# container (the same export_results behind GET /admin/config/results, so no
# local API key is needed) and ride along as `results` in one POST
# /admin/config/import: one transaction, because a new job's first run starts
# within ~30s of the import. Needs the local stack up and an API key for the
# target (scripts/schoolz-api.sh login prod).
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: $0 <prod|local> <seed.json>" >&2
  exit 2
fi
target=$1 seed=$2
root=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# What to export: the seed's district names and state (one state per seed).
request=$(python3 - "$seed" <<'PY'
import json, sys

seed = json.load(open(sys.argv[1]))
names = [d["name"] for d in seed.get("districts", [])] + [s.get("district_name") for s in seed.get("schools", [])]
names = list(dict.fromkeys(n for n in names if n))
if not names:
    sys.exit("seed names no district")
# A district is its state plus its name; a seed that doesn't say is New Jersey.
states = {d.get("state", "NJ") for d in seed.get("districts", [])} or {"NJ"}
if len(states) != 1:
    sys.exit("seed spans several states; carry results one state at a time")
print(json.dumps({"names": names, "state": states.pop()}))
PY
)

printf '%s' "$request" | docker exec -i "${API_CONTAINER:-schoolz-api-local}" sh -c 'cd /app && PYTHONPATH=/app python -c "
import asyncio, json, sys
import database
from services.config_results import export_results

async def main(req):
    async with database.SessionLocal() as db:
        print(json.dumps(json.loads((await export_results(db, req[\"names\"], req[\"state\"])).model_dump_json())))

asyncio.run(main(json.load(sys.stdin)))
"' > "$tmp/results.json"

python3 - "$seed" "$tmp/results.json" "$tmp/bundle.json" <<'PY'
import json, sys

seed_path, results_path, out_path = sys.argv[1:4]
results = json.load(open(results_path))
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
