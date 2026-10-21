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

- **Outside visits** (everything but source `internal`) are the headline. `internal` is the team's own browsing; mention it once, separately.
- **Visits, not people.** `page_visits` stores one counter per day/path/source and nothing per visitor (the `/chcomms` promise), so it can't count people. A visit is counted once per page per browser session.
- **Days are Eastern calendar days**, with no hours. "Last 24 hours" or "last few hours" can only be answered as today + part of yesterday, or as the change since an earlier check in the same conversation.
- Compare with the same weekday last week; weekends and Facebook posts swing it a lot.
- **School pages** (`/schools/<slug>`), `/local` and `/directory` are counted only from Oct 20 2026, ~5pm; before that they were dropped. Nine other pages (`/`, `/start`, `/schools`, `/calendar`, `/lunch`, `/chcomms`, `/survey`, `/contact`, `/privacy`) go back further. Class pages and anything else are not counted.

## People, and history before the counter

Only GA4 counts people (cookie-based users), and it undercounts heavily (ad blockers, opt-out, deferred load) and trails 24-48h. It also has school-page and `/local` history from before the counter. Pulling it needs a prod-secrets approval: the query goes through Grafana's `schoolz-ga` Infinity datasource with `GRAFANA_URL`/`GRAFANA_TOKEN` (see the `observability` skill); the GA property id is read from a live schoolz dashboard, never written down. Treat GA as a floor and compare trends, not totals.
