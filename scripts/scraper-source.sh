#!/usr/bin/env bash
# Checks out the shared scraper (Profitnaut/playwright-scraper, a private repo)
# at the commit pinned in scraper/SOURCE_REF, into .cache/playwright-scraper
# (gitignored), and prints that directory. deploy-scraper.sh builds the Fly
# scraper from it; compose-local.sh builds the local one.
#
# Cloning needs read access to that repo: `gh auth login` (the clone goes
# through gh when it is installed) or git credentials for github.com.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ref="$(tr -d '[:space:]' < "$ROOT_DIR/scraper/SOURCE_REF")"
dir="$ROOT_DIR/.cache/playwright-scraper"

if [ ! -d "$dir/.git" ]; then
  mkdir -p "$(dirname "$dir")"
  if command -v gh >/dev/null; then
    gh repo clone Profitnaut/playwright-scraper "$dir" -- --quiet >&2
  else
    git clone --quiet https://github.com/Profitnaut/playwright-scraper.git "$dir" >&2
  fi
fi
if [ "$(git -C "$dir" rev-parse HEAD 2>/dev/null)" != "$ref" ]; then
  git -C "$dir" fetch --quiet origin >&2
  git -C "$dir" checkout --quiet --detach "$ref" >&2
fi
echo "$dir"
