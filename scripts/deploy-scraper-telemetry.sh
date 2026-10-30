#!/usr/bin/env bash
# Deploys the Fly scraper's telemetry apps (scraper/telemetry/): Alloy for its
# metrics, Vector for its logs. By hand only, like the scraper itself.
#
#   scripts/deploy-scraper-telemetry.sh            both
#   scripts/deploy-scraper-telemetry.sh metrics    one of them (or logs)
#
# One machine each (--ha=false): neither serves anything, and two would ship
# every series and line twice. Secrets: scraper/telemetry/README.md.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
targets=("${@:-metrics logs}")

for t in ${targets[*]}; do
  case "$t" in
    metrics|logs) ;;
    *) echo "usage: $0 [metrics|logs]" >&2; exit 2 ;;
  esac
  # fly.toml's [[files]] local_path is read from the current directory.
  (cd "$ROOT_DIR/scraper/telemetry/$t" && fly deploy --config fly.toml --ha=false)
done
