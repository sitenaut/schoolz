#!/usr/bin/env bash
# Deploys the Fly scraper (schoolz-scraper): the shared playwright-scraper at
# scraper/SOURCE_REF, with scraper/fly.toml. By hand only; deploy.yml doesn't
# touch it. To move to a newer playwright-scraper, put its commit in
# scraper/SOURCE_REF (through a PR) and run this.
#
#   scripts/deploy-scraper.sh             deploy SOURCE_REF
#   scripts/deploy-scraper.sh --rollback  put the previous release's image back
#
# A deploy fails, and the old machines keep serving, if a new machine doesn't
# pass /health/deep (fly.toml's check).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP=schoolz-scraper
CONFIG="$ROOT_DIR/scraper/fly.toml"

previous_image() {
  fly releases -a "$APP" --image --json \
    | python3 -c 'import json, sys; ok = [r for r in json.load(sys.stdin) if r["Status"] == "complete"]; print(ok[1]["ImageRef"] if len(ok) > 1 else "")'
}

if [ "${1:-}" = "--rollback" ]; then
  image="$(previous_image)"
  [ -n "$image" ] || { echo "No earlier release to roll back to." >&2; exit 1; }
  echo "Rolling $APP back to $image"
  # An image from before the move to playwright-scraper needs the fly.toml it
  # was deployed with: pass that one as FLY_CONFIG.
  exec fly deploy -a "$APP" --config "${FLY_CONFIG:-$CONFIG}" --image "$image"
fi

src="$("$ROOT_DIR/scripts/scraper-source.sh")"
sha="$(git -C "$src" rev-parse --short=12 HEAD)"
echo "Deploying playwright-scraper $sha to $APP (rollback: scripts/deploy-scraper.sh --rollback)"
fly deploy "$src" -a "$APP" --config "$CONFIG" --remote-only \
  --build-arg GIT_SHA="$sha" --image-label "pws-$sha"
