---
name: visits
description: The schoolz prod visit report - daily outside visits, sources (Facebook, Google, flyer, direct), and which pages (incl. each school page and /local) people opened yesterday and today. Use when the owner asks how many visitors/visits, how we did yesterday or today, what pages were popular, or about /local adoption.
user-invocable: true
---

# Visit report

Run:

```
python3 .claude/skills/visits/report.py        # last 10 days; pass a number for more
```

It calls `GET /page-views` on prod through `scripts/schoolz-api.sh`. A 403 means the saved key lacks `analytics.view`: run `bash scripts/schoolz-api.sh login prod` in the background and give the owner the approval link, asking them to tick `analytics.view` plus whatever the current key already has (`GET /auth/me` lists it) - the new key replaces the saved one.

## How to report

Lead with the number asked for, then a short table. Keep it brief; the owner usually wants counts, not commentary.

- **Outside visits** (everything but source `team`) are the headline. `team` is a browser flagged as the team's own (a staff sign-in, or `?internal=1` once on any URL); mention it once, separately. A team member who never signed in or used the flag on a device counts as outside.
- `self` (older rows: `internal`) is a session that started from one of our own pages, usually a link opened in a new tab. Those are real visitors and count as outside. Before the `team` label shipped, the team's browsing was mixed into the outside sources and can't be separated out.
- **Visits, not people.** `page_visits` stores one counter per day/path/source and nothing per visitor (the `/chcomms` promise), so it can't count people. A visit is counted once per page per browser session.
- **Crawlers inflate "direct" before Oct 22 2026.** Crawlers that run JavaScript (Meta's `meta-externalagent`, `ExaSearchBot`) were counted as direct visits until #425 (live ~11 PM Oct 21) skipped them: on Oct 21, ~80 of 126 outside visits were crawlers, landing on `/calendar`, `/lunch`, `/start`, `/directory`, `/privacy`, `/contact` and `/chcomms`. Treat an earlier jump in direct visits to those pages as likely crawler traffic. To tell a new spike apart, Faro's `page_view` events carry `browser_userAgent` (`observability` skill); crawlers name themselves there.
- **Days are Eastern calendar days**, with no hours. "Last 24 hours" or "last few hours" can only be answered as today + part of yesterday, or as the change since an earlier check in the same conversation.
- Compare with the same weekday last week; weekends and Facebook posts swing it a lot.
- **School pages** (`/schools/<slug>`), `/local` and `/directory` are counted only from Oct 20 2026, ~5pm; before that they were dropped. Nine other pages (`/`, `/start`, `/schools`, `/calendar`, `/lunch`, `/chcomms`, `/survey`, `/contact`, `/privacy`) go back further. Class pages and anything else are not counted.
- **Budget pages** (`/budgets`, and `/budgets/<slug>` per state district, tracked by schoolz or not) are counted only from the deploy of the change that added them (Oct 28 2026). Earlier visits are only in GA4 and Faro RUM, where a budget page's `route` was the raw path until then and is `/budgets/:slug` (with `budget_slug`) after.
- **Localz** (`/localz`, `/localz/<category>`, `/localz/providers`, the public Neighborz list `/localz/bills` (never its personal pages), and every listing as one `/localz/r/:id` row) is counted only from the deploy of the change that added it; GA never loads there by design, so its earlier history is only in Faro RUM (`event_name="page_view"`, `event_data_route`, through Loki; see the `observability` skill). RUM saw a one-day burst of ~620 listing views on Oct 17 2026, the same day as a bot spike, probably crawler traffic (not verified).

## People, and history before the counter

Only GA4 counts people (cookie-based users), and it undercounts heavily (ad blockers, opt-out, deferred load) and trails 24-48h. It also has school-page and `/local` history from before the counter. Pulling it needs a prod-secrets approval: the query goes through Grafana's `schoolz-ga` Infinity datasource with `GRAFANA_URL`/`GRAFANA_TOKEN` (see the `observability` skill); the GA property id is read from a live schoolz dashboard, never written down. Treat GA as a floor and compare trends, not totals.
