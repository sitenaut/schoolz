# Operations runbook

How schoolz tells a person something is wrong, and what to do about each alert.
Every alert's `runbook_url` points at its heading in this file, so the headings
below are alert uids - don't rename one without renaming the rule.

Everything here is generated and pushed, never clicked together:

```
python3 scripts/build_grafana_alerts.py       # rules + the SLO list  -> grafana/cloud-dashboards/alerts.json
python3 scripts/build_grafana_slos.py         # SLO definitions       -> slos.json
python3 scripts/build_grafana_dashboards.py   # dashboards            -> schoolz-*.json
python3 scripts/grafana_sync.py --dry-run     # then without --dry-run
```

Start at the **schoolz / Operations** dashboard: what needs action, what is only
context, how each SLO stands, and whether every process is alive.

## The model

An alert answers one question before anything else: *does a person need to do
something, and how soon?* That answer is the `tier` label, and it is the only
thing routing looks at.

| tier | means | goes to | repeats |
|---|---|---|---|
| `page` | someone is being failed right now | IRM, "schoolz page" chain: important notification rules, again after 15 min unacknowledged | hourly while firing |
| `ticket` | real, but it can wait for daylight | IRM, "schoolz ticket" chain: default notification rules, once | daily |
| `info` | a trigger worth knowing; nothing to do on its own | email, one per alert name, batched | weekly |

`kind` says what sort of thing fired, which is what decides the tier:

| kind | what it is | default tier |
|---|---|---|
| `slo` | an error budget is burning - a promise is being broken | `page` if visitors feel it now, else `ticket` |
| `symptom` | a visible failure with no SLO behind it (the scheduler stopped) | `page` or `ticket` |
| `cause` | explains a symptom (a slow route, a failing scraper, memory) | `info`, unless it predicts an outage |
| `event` | something happened and nothing is wrong (a signup) | `info` |

Causes are informational on purpose. When the API is failing you get one
actionable alert (the availability SLO) and an email naming the route - not two
pages for one problem. If a cause fires with no symptom, the system absorbed it.

`component` (`api`, `prerender`, `scheduler`, `scans`, `scraper`, `llm`, `auth`,
`database`, `alexa`, `growth`) is for filtering and grouping; IRM alert groups
are per alert name + component.

**Managing an alert as informational vs actionable** is therefore one word:
change its `tier=` in `scripts/build_grafana_alerts.py` and sync. In an
incident, do it in the Grafana UI (rules are deliberately editable there) and
bring the change back to the builder afterwards, or the next sync reverts it.

Quieting things: acknowledge or silence the alert group in IRM, or add a silence
in Grafana Alerting matching `app=schoolz` plus the `alertname`/`component`. A
planned deploy window is a silence on `tier=page`.

## SLOs

28-day rolling windows, defined in the `SLOS` list in
`scripts/build_grafana_alerts.py` (one source for the objective and its alerts).

| SLO | objective | counts as good | deliberately excluded |
|---|---|---|---|
| API availability | 99.5% | a request answered without a 5xx | `/prerender` (own SLO), CORS preflights |
| API latency | 95% within 1s | an interactive GET under 1 second | `/chat`, `/admin/*`, scraper and job routes - slow by design |
| Prerender for crawlers | 99% | a `/prerender` request that returned a page | - |
| Scan runs | 99% | a run that didn't end in `error` (warnings are finished runs) | skipped runs |

Each has two burn-rate alerts. **Fast** (14.4x over 1h and 5m, or 6x over 6h and
30m) means the month's budget is gone in about two days. **Slow** (3x over a day,
or 1x over three days) means it won't last the window. Both need a minimum
number of requests in the window, because overnight one failure in five requests
is a 20% error rate and nobody should be woken for it.

Only fast burn on API availability pages. Everything else is a ticket: a slow
crawler or a failing scan is real, and none of it is worth 3 AM.

Known blind spot: a counter series that first appears already at 1 is not seen
as an increase, so the *first* error of a new kind/code can be missed by the
scan SLO. `schoolz-job-failing` reads the database instead and has no such gap.

## What is not covered

- **Nothing probes the site from outside.** If Fly's proxy or DNS fails, no
  request reaches the app, so no metric says so; `schoolz-api-down` only catches
  the process being gone. A Synthetic Monitoring check on the web and API URLs
  is the fix (free tier covers it) and has to be created in the Grafana UI.
- **The web container** (nginx) emits nothing. Its health is inferred from RUM.
- **Postgres** itself (connections, disk) is only visible from the app's pool.
- **CloudWatch** rules exist only once a read-only key is in
  `env/secrets.prod.env` (`GRAFANA_CLOUDWATCH_*`); until then they're skipped.

## Alerts

### schoolz-api-down
No API machine has reported telemetry for 10 minutes. One machine is always kept
running, so either none is up or export broke. Check `fly status -a schoolz-api`
and the app logs; if machines are healthy and serving, the problem is the OTLP
secret or the gateway, not the site - downgrade your urgency accordingly.

### schoolz-scheduler-down
The scheduler process has not reconciled in 10 minutes; no scan is running and
nothing will fail to tell you. `fly status -a schoolz-api` (process group
`scheduler`), then its logs. An OOM kill shows as a restart loop - see
`schoolz-memory-high`.

### schoolz-slo-api-availability-fast
Visitors are getting server errors at a rate that empties the budget in days.
The `schoolz-route-5xx` email names the route. API dashboard → errors by route,
then the trace for one failing request. If it started with a deploy, roll back
first and diagnose second.

### schoolz-slo-api-availability-slow
A steady trickle of 5xx. Same path as the fast alert without the urgency: find
the route, find the exception in Loki (`service_name="schoolz-api"`, level error).

### schoolz-slo-api-latency-fast
### schoolz-slo-api-latency-slow
More than 5% of interactive GETs are taking over a second. `schoolz-route-slow`
names the route. Usual causes, in order: a cold machine (compare with cold-start
count), one route's query plan (trace → SQL spans), the database pool
(`schoolz-db-pool-saturated`).

### schoolz-slo-prerender-fast
### schoolz-slo-prerender-slow
Crawlers and link previews are getting errors instead of pages. `/prerender`
drives headless Chromium through the scraper, so check the scraper first
(`schoolz-scraper-failing`, `schoolz-scraper-silent`), then the route's own
errors. It serves stale cache when a re-render fails, so a 500 means there was
no cache to fall back on.

### schoolz-slo-scans-fast
### schoolz-slo-scans-slow
Scan runs are ending in `error` faster than the budget allows. Scans dashboard →
failures by error code. One code across many kinds is infrastructure (scraper,
database, LLM provider); one kind is a site that changed.

### schoolz-no-scans
The scheduler is alive but nothing has run for 13 hours. Check `/admin` → Jobs:
are jobs enabled, and does the scheduler log show them being loaded on reconcile?

### schoolz-job-stuck
A run of this kind has been in flight for over an hour. Don't force-error it on
a hunch - a long run that checkpoints is healthy. Look at the run's
`last_progress_at` and the scheduler log for that job before touching it.

### schoolz-job-failing
This specific job's last two runs both errored. `/admin` → Jobs → Runs has the
stage and traceback. One failure is a flaky site; two is a changed layout, a
dead URL, or a source that now blocks us.

### schoolz-memory-high
A process is within 15% of its machine's memory. For the scheduler the next
event is an OOM kill that abandons the running scan. Find what's running
(`schoolz_job_in_flight`), and if this is the new normal, raise the machine size
in `backend/fly.toml` and the limit in the alerts builder together.

### schoolz-db-pool-saturated
Every connection in a process's pool (4 + 2 overflow) has been checked out for
10 minutes. Further requests queue, then fail `db_pool_timeout`. Look for one
slow query in traces, or a code path holding a session across a network call.

### schoolz-llm-truncated
A model reply hit `max_tokens`. For extraction this has produced zero items from
a full newsletter while the run looked fine. The `purpose` label says which
call; re-run the affected scan after raising the cap or shrinking the chunk.

### schoolz-scraper-silent
The schoolz scraper machine isn't reporting. It never auto-stops, so it's down:
`fly status -a schoolz-scraper`. Scans fall back to the droplet meanwhile.

### schoolz-auth-stalled
A visitor's auth check never resolved and they saw the Reload fallback. This is
the supabase-js lock deadlock's signature - see "Supabase auth deadlock" in
`CLAUDE.md`. Any recent change touching `AuthContext` or `apiFetch` is the suspect.

### schoolz-alexa-errors
The Alexa skill's Lambda is failing invocations. Its CloudWatch log group has
the traceback; the Operations dashboard shows whether it's every call or a few.

### schoolz-route-5xx
Context for an availability burn: which route, how many. Nothing to do if the
SLO alert isn't firing.

### schoolz-route-slow
Context for a latency burn: which route's p95 is over 2.5s.

### schoolz-scraper-failing
Over 30% of the schoolz scraper's page loads are failing. Callers retry and fall
back to the droplet, so this often costs nothing - the scan SLO says whether it
did. Persistent, it means the machine is too small for the burst or sites are
blocking its address.

### schoolz-scan-warnings
More than half of a kind's runs in a day "fetched fine, found nothing". For a
kind that usually finds something, that is what a redesigned site looks like.
For kinds that are mostly empty by nature, raise the threshold or drop them from
the rule rather than learning to ignore the email.

### schoolz-parse-issues
A parser is dropping an unusual amount of content from scans that succeed. The
`code` and `job_kind` labels say where; the `parse_issue` log lines carry a sample.

### schoolz-queue-wait
Scans are waiting over five minutes for a concurrency slot. Either too many jobs
share a minute (check hand-made jobs' cron) or one long job is holding a slot.

### schoolz-llm-spend
Token use over 24h is more than double a heavy day. A loop re-extracting the
same content or a translation backfill both look like this; the Scans dashboard
splits tokens by purpose.

### schoolz-auth-slow
The client-side auth check is slow without outright stalling. Same family as
`schoolz-auth-stalled`, earlier.

### schoolz-user-created
Someone registered. Nothing is wrong.

### schoolz-alexa-throttled
The Lambda hit a concurrency limit. Not expected at this traffic.

### schoolz-newsletter-stale
Some newsletters have missed their weekly scan; the Scans dashboard lists them.

### schoolz-vision-backlog
Image blocks have been waiting on vision extraction for a day - usually an image
the model can't read. The block stays pending and warns on each scan.

## Adding an alert

1. Add it to `rules()` in `scripts/build_grafana_alerts.py` with a tier, kind
   and component. If nobody would act differently at 3 AM it isn't `page`; if
   nobody would act at all it's `info`.
2. Write the summary so it reads correctly on a lock screen, using the series'
   own labels (`{{ $labels.job_kind }}`) and value.
3. Add a heading here named after its uid.
4. Build, `--dry-run`, sync.
