#!/usr/bin/env bash
# Render a page through the local stack's scraper (Playwright) and print the HTML.
# Used by the district-crawler agent for sites that block or hang plain HTTP.
#   scripts/crawl-fetch.sh <url> [css-selector-to-wait-for]
# Needs the local stack up (./scripts/compose-local.sh up). Plain httpx/curl first;
# this is the fallback, and the one to use directly on Cloudflare-challenged sites.
set -euo pipefail
url="${1:?usage: crawl-fetch.sh <url> [wait_for_selector]}"
sel="${2:-}"
docker exec -i schoolz-api-local python - "$url" "$sel" <<'PY'
import asyncio, sys
sys.path.insert(0, "/app")
import scraper_client

async def main(url, sel):
    r = await scraper_client.fetch_html(url, wait_for_selector=sel or None, timeout_ms=30_000)
    print(r.get("html", ""))

asyncio.run(main(sys.argv[1], sys.argv[2]))
PY
