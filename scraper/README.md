# schoolz-scraper

A small FastAPI + Playwright (headless Chromium) service for fetching pages
that need a real browser - JS-rendered school/district sites, or downloads
blocked by bot-detection when fetched with a plain HTTP client.

Not deployed via Fly.io - Fly's model doesn't suit a long-running browser
process well. Locally it runs as a `docker-compose` service; in prod it's
meant to run on a persistent host (see `notes/prod-checklist.md`) the same
way billz's own scraper does.

## Endpoints

All routes except `/health` require an `X-API-Key` header matching `SCRAPER_API_KEY`.

- `GET /health` - liveness check, also reports whether the shared browser instance is connected.
- `POST /fetch-html` - `{"url": "...", "wait_for_selector": "...", "timeout_ms": 15000}` → renders the page and returns its HTML + title. Use this for anything that needs JavaScript to show its content.
- `POST /fetch-raw` - `{"url": "...", "timeout_ms": 15000}` → returns the raw response body (base64-encoded) and content-type through a real browser context. Use this for downloads (ICS, PDF, CSV) that block plain HTTP clients.

The browser is launched once at startup and reused across requests (a fresh
browser *context* per request, not a fresh browser process) for speed.

## Local development

Runs as part of the main stack:
```
./scripts/compose-local.sh up --build scraper
```
Backend reaches it at `http://scraper:8765` (see `SCRAPER_URL` in
`docker-compose.yml`). To call it directly:
```
curl -X POST http://localhost:8765/fetch-html \
  -H "X-API-Key: $SCRAPER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

## Adding site-specific extraction

This service is intentionally generic (fetch + render only). Site-specific
parsing (pulling events/homework/announcements out of a particular district's
HTML) belongs in the **backend**, which calls `/fetch-html` and then parses
the returned HTML itself - keeps this service simple and swappable, and
keeps scraping logic testable without spinning up a browser.
