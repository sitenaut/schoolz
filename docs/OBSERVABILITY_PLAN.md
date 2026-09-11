# schoolz observability plan: Grafana Cloud (RUM, APM, scans, logs)

Status (2026-09-11): **Phases 1-5 code complete and deployed to prod.**
`schoolz-api`, `schoolz-scraper`, and `schoolz-web` all redeployed with
this code; OTLP secrets (endpoint + schoolz-only token) live on all three,
Faro collector secret live on `schoolz-web`. Verified post-deploy:
`https://schoolz-api.sitenaut.com/health` 200, `/metrics` now 404 (public
leak closed), `https://schoolz.sitenaut.com/` 200 with the new build, and
a real POST through `/rum/collect` reaches the actual Grafana collector
(400, not 502/timeout - the collector rejecting a test payload, not a
connection failure). **Not yet confirmed**: that data is actually landing
in Grafana Cloud (Explore/Tempo/Loki/Frontend Observability) - check there
next, since a live proxy round-trip and passing health checks aren't 100%
proof the SDK-side export path has no separate bug. Phase 6 (dashboards,
alerts, the "what to simplify" hypotheses) still needs either Grafana Cloud
console access (no admin API token available for non-interactive
dashboard/alert creation) or a week of real traffic to analyze - neither
achievable in this session. Written so a Sonnet session can execute
it phase by phase. Each phase lists exact files, the change, and how to
verify it. Do the phases in order. Commit after each phase (branch
`ecastillo-dev`). If a step's verification fails, stop and report back.
Don't improvise around it.

Progress:
- Phase 1: `backend/scripts/sql/grafana_ro.sql` run against prod Supabase
  (2026-09-11) — `grafana_ro` role exists, SELECT + RLS policy confirmed on
  all 13 tables. Password lives in `env/secrets.prod.env`
  (`GRAFANA_RO_PASSWORD`). **Still needed**: create the Postgres datasource
  + "schoolz / Scans" dashboard + alerts in the Grafana Cloud console (no
  admin API token available to do that non-interactively — see
  `grafana/cloud-dashboards/scans_queries.sql` for the panel queries and
  alert conditions to paste in).
- Phase 2: `backend/telemetry.py`, `backend/observability.py` added;
  `backend/main.py`, `backend/scheduler/entrypoint.py`,
  `backend/scheduler/runner.py`, `backend/requirements.txt` updated;
  `prometheus-client`/`/metrics` removed. Local `OBSERVABILITY=1` stack
  (`alloy/config.alloy`, `docker-compose.yml`, `scripts/compose-local.sh`,
  the provisioned dashboard) updated to match. `pytest -q` passes (66
  tests, including new `tests/test_telemetry.py`), verified inside a fresh
  Docker build against a throwaway Postgres. OTLP endpoint + Basic-auth
  header **staged** on `schoolz-api` via `fly secrets set --stage`
  (2026-09-11, not live yet — takes effect on the next deploy, deliberately
  not forced now to avoid an unplanned restart on old code that doesn't
  read these vars anyway). Scraper/Claude-call-level metrics (2e's
  `scraper_client.py`/`content_extractor.py`/`lunch_menu.py` wiring) not
  done — only the job-run metrics in `runner.py` are wired so far.
- Phase 3: `backend/scheduler/errors.py` (ScanError, classify_exception,
  parse_warning, record_parse_issue) added. `job_runs.error_code`/
  `error_stage` + `scheduled_jobs.last_error_code` added via migration 0026.
  `scheduler/runner.py` now classifies every error/warning and emits a
  structured `job_finished` log line with queue-wait/duration. The 9 plain
  `"WARNING: ..."` sites plus `hs_rotation_scan.py`'s second one,
  `school_info_scan.py`, and `transportation_scan.py` now carry
  `"WARNING[<code>]: ..."`; `smore_scan.py` propagates whichever code
  `content_extractor.py`'s own warning carried (`image_unsupported` /
  `llm_max_tokens`) instead of a generic re-wrap. `record_parse_issue` calls
  added at the 8 fragile spots named in the plan (smore_parser
  `_classify`, content_extractor `_parse_date`/`_parse_lunch_menu_days`/
  vision failures/max_tokens, marking_period's tier-heading miss,
  hs_rotation's unplaced day tokens, preschool_locations' address-less
  entries, documents_scan's yearless documents). Stuck-run reaper runs every
  30s reconcile tick in `scheduler/entrypoint.py` (plan said "once before
  the loop" - made periodic instead, strictly stronger, same query).
  `ScheduledJobOut`/`JobRunOut` schemas and `JobsPage.tsx` surface
  `last_error_code`/`error_code` as a chip. `backend/tests/test_scan_errors.py`
  added (14 tests). **Full suite verified: 80/80 pytest pass** (66 + 14 new),
  migration 0026 applies cleanly, inside a fresh Docker build against a
  throwaway Postgres. Frontend `tsc --noEmit` and `npm test` both clean.
  Migration 0026 run against prod (2026-09-11, `0025 -> 0026`) - columns
  confirmed present. Still not live end-to-end: `schoolz-api` hasn't been
  deployed with this code yet.
- Phase 4: Faro packages installed (`@grafana/faro-react`/`-web-sdk`/
  `-web-tracing` pinned `1.19.0` - the 1.x line, not 2.x, to match this
  app's `react-router-dom` v6 peer dep). `src/lib/telemetry.ts`
  (`initTelemetry`, `scrubUrl`, `FaroRoutes` re-export), `src/lib/track.ts`
  (`trackEvent`/`trackMeasurement`) added. Wired: `page_view`,
  session attributes, `today_ready`, `school_page_ready`,
  `school_filter_toggle`, `action` (absence button only). **Not wired**:
  `calendar_ready`/`lunch_ready`/`calendar_search`/`schools_picked` and
  `action` for the other buttons (nurse/counselor/bus/add-to-calendar/
  document-open/sports-link) - same pattern, just not done in this pass.
  Same-origin `/rum/collect` proxy (`frontend/nginx.conf.template` +
  envsubst + Dockerfile placeholder default) verified with a real Docker
  build: nginx starts cleanly with and without `FARO_COLLECTOR_URL` set,
  and a real POST through the proxy reaches the actual Grafana Faro
  collector. `VITE_APP_VERSION` now the git short SHA in `deploy.yml`.
  `PrivacyPage.tsx` updated with the owner-approved RUM disclosure; no
  consent banner added (flagged as the owner's call). CORS `max_age=86400`
  added. `tsc --noEmit`, `npm test` (12 tests incl. 7 new scrub tests), and
  a real `npm run build` all clean. **Not yet live**: `FARO_COLLECTOR_URL`
  not pushed to `schoolz-web` via `fly secrets set`, and nothing in this
  phase has been deployed.
- Phase 5: `scraper/telemetry.py` (trimmed standalone copy, no import from
  backend) + `scraper/observability.py` (`schoolz.scraper.page_load`
  histogram, `schoolz.scraper.pages_open` up-down counter -
  `schoolz.scraper.browser_restarts` from the plan skipped: the service has
  no Chromium-restart logic to wire it to) added. `main.py`:
  `FastAPIInstrumentor.instrument_app`, manual spans around `page.goto`/
  `wait_for_selector`/each paginated click (attributes `url.host`, not the
  full URL; `selector`; `page_index`), all three endpoints
  (`fetch_html`/`fetch_paginated`/`fetch_raw`) record page-load
  duration/outcome. `requirements.txt` updated (same pinned OTel versions
  as backend). Verified in a real Docker build: `pytest -q` passes (2/2),
  and a live `/fetch-html` call against `https://example.com` returns 200
  with real page content through the instrumented code path (checked via
  `docker exec` after host->container curl hit an unrelated WSL2 dual-stack
  port-forwarding quirk - same `uvicorn --host ::` binding already
  documented in CLAUDE.md, not something this phase changed).
  **Not yet deployed** - no `fly secrets set -a schoolz-scraper` run yet.
- Phase 6: not started.
- Faro collector URL for Phase 4 already obtained:
  `https://faro-collector-prod-us-east-2.grafana.net/collect/e134be0a82120a899938a4022a5bf806`
  (app name to use: `schoolz-web`, per section 2 — not the tutorial
  snippet's default `schoolz-faro`).

---

## 0. Goals

| Question the owner wants answered | Where the answer comes from |
|---|---|
| Did a scan fail? Which one, and **why**? | `job_runs` (Postgres datasource) + `schoolz_job_runs_total{status}` metric + `job_finished` log line with `error_code`/`error_stage` + alert |
| How long do scans take? Is the 12h burst queueing? | `schoolz_job_duration_seconds`, `schoolz_job_queue_wait_seconds`, per-run trace (scraper + Claude calls as child spans) |
| How many failed per kind / per school over time? | Postgres datasource on `job_runs` joined to `scheduled_jobs.params` |
| What exactly failed while parsing? | `parse_issue` structured log lines + `schoolz_parse_issues_total{job_kind,code}` |
| Page load times (real users) | Grafana Faro RUM: Web Vitals (LCP/INP/CLS/TTFB/FCP) per route + custom "ready" measurements |
| Which paths do users visit most / how do they move? | Faro `page_view` custom event with `route` (template) + `from_route` |
| Which backend calls are slow, chatty or redundant? | Faro fetch spans → propagated `traceparent` → backend OTel traces (FastAPI → SQLAlchemy → httpx) in Tempo; per-route RED metrics |
| Cold starts (Fly auto-stop, `min_machines_running = 0`) | `app.cold_start` span attribute + `schoolz_cold_start_requests_total` + TTFB outliers in RUM |

## 1. Architecture

```
Browser (Faro Web SDK, app "schoolz-web")
   ├─ RUM (vitals, errors, events, fetch spans) ──► schoolz.sitenaut.com/rum/ (nginx proxy) ──► Faro collector (Grafana Cloud)
   └─ fetch + traceparent header ──► schoolz-api (FastAPI)

schoolz-api  "app" process      ─┐  OpenTelemetry SDK, OTLP/HTTP push
schoolz-api  "scheduler" process ├─► otlp-gateway-<region>.grafana.net/otlp ─► Mimir (metrics) / Tempo (traces) / Loki (logs)
schoolz-scraper                  ─┘

Grafana Cloud ──(PostgreSQL datasource, read-only role grafana_ro)──► Supabase session pooler (job_runs, scheduled_jobs, schools, ...)
```

Why these choices (don't re-litigate them during execution):

- **OTLP push from each process, no Alloy on Fly.** Fly machines have no Docker socket, the `app` machines auto-stop (nothing can scrape a stopped machine), and the `scheduler` process has no HTTP port. With push, each process ships its own data, and nothing extra has to be deployed.
- **Drop `prometheus_client` and the public `/metrics` mount.** Today `https://schoolz-api.sitenaut.com/metrics` is publicly readable. Also, `_normalize_path` only collapses hex ids, so every `/schools/<slug>/...` becomes its own series, which is a cardinality leak. OTel's FastAPI instrumentation labels by route template (`/schools/{school_id}/today`), which fixes both.
- **Postgres datasource for scan history.** `job_runs` already records every run's status and duration. Grafana can query it directly: that covers history from day one and lets per-school breakdowns join to `schools`. The high-cardinality "which school" dimension stays out of the metrics bill.
- **Faro via a same-origin nginx proxy.** `*.grafana.net` collector hosts are on common ad-block lists. Proxying through `/rum/` on our own domain keeps RUM data from silently disappearing for those users.

## 2. Separating schoolz from billz (same Grafana Cloud stack)

schoolz reuses billz's stack (`enr.grafana.net`, stack `1595929`, Loki user `1553718`). Every signal must carry a schoolz tag:

| Signal | Tag | Query filter |
|---|---|---|
| Metrics | resource `service.namespace=schoolz` → Grafana Cloud sets `job="schoolz/<service.name>"` on every series; custom metrics are also prefixed `schoolz_` | `{job=~"schoolz/.*"}` |
| Logs | `service_namespace="schoolz"`, `service_name="schoolz-api"\|"schoolz-scheduler"\|"schoolz-scraper"` (indexed labels) | `{service_namespace="schoolz"}` |
| Traces | `resource.service.namespace="schoolz"` | TraceQL `{resource.service.namespace="schoolz"}` |
| RUM | its own Frontend Observability app named `schoolz-web` | the app picker / `{app_name="schoolz-web"}` |
| Env | `deployment.environment=prod\|local` | logs: `deployment_environment` label; metrics: `* on (job, instance) group_left(deployment_environment) target_info` |

billz logs use `app="billz-api"`. No label collides.

Service names: `schoolz-api` (uvicorn), `schoolz-scheduler` (scheduler process, same Fly app), `schoolz-scraper`, `schoolz-web`.

## 3. Inputs needed from the owner (blocking; get these before Phase 2)

Already in `env/base.env`: `GRAFANA_CLOUD_PROMETHEUS_URL`/`_USER_ID`, `GRAFANA_CLOUD_LOKI_URL`/`_USER_ID`, `GRAFANA_CLOUD_API_KEY`. That key is billz's Alloy token (`stack-1595929-alloy-billzdev`, decoded name). It's also a secret sitting in `base.env`, which `docs/ENV_SETUP.md` defines as non-secret defaults. Still needed:

1. **OTLP endpoint + instance ID**: Grafana Cloud portal → stack → *OpenTelemetry* tile → Configure. Expect `https://otlp-gateway-prod-us-east-2.grafana.net/otlp` and instance ID `1595929`. Confirm both on the tile.
2. **A schoolz-only access policy token** with `metrics:write`, `logs:write`, `traces:write`. Name it `schoolz-otlp-write`. Don't reuse billz's token: revoking one app's token shouldn't break the other.
3. **Faro collector URL**: Grafana Cloud → Frontend Observability → *Create app* `schoolz-web`, allowed origins `https://schoolz.sitenaut.com` and `http://localhost:5173`. The URL looks like `https://faro-collector-prod-us-east-2.grafana.net/collect/<key>`. It's public by design and ships in the JS bundle.
4. **OK to create a read-only DB role on prod Supabase** (`grafana_ro`, SELECT on non-PII tables only, section 5). Pick a password.
5. **Alert contact point**: email, Slack, Discord, or Grafana IRM mobile push.
6. **Privacy page wording**: `/privacy` currently promises "No analytics… of any kind." RUM needs that text updated (Phase 4). Owner approves the wording.

Where the values live:
- Prod: `fly secrets set` on `schoolz-api` and `schoolz-scraper` (section 6), mirrored in `env/secrets.prod.env`.
- Move `GRAFANA_CLOUD_API_KEY` out of `env/base.env` into `env/secrets.*.env`.
- Never put `OTEL_*` vars in `base.env`: local compose sources it, and local would start shipping to prod Grafana.

---

## Phase 1: Scan visibility with no app changes (Postgres datasource + alerts)

The fastest win for "did a scan fail". It covers history already in `job_runs`.

1. Run once in the Supabase SQL editor (prod). **Don't** put this in an Alembic migration: it holds a password, and the role doesn't exist locally. RLS is on with no policies on every table, so without explicit policies a non-owner role sees zero rows.

   ```sql
   CREATE ROLE grafana_ro LOGIN PASSWORD '<from owner>';
   ALTER ROLE grafana_ro SET statement_timeout = '15s';
   GRANT USAGE ON SCHEMA public TO grafana_ro;
   DO $$ DECLARE t text; BEGIN
     FOREACH t IN ARRAY ARRAY['scheduled_jobs','job_runs','districts','schools','smore_newsletters',
       'smore_blocks','school_content_items','school_documents','staff_members','lunch_menus',
       'lunch_menu_items','sacc_programs','district_transportation'] LOOP
       EXECUTE format('GRANT SELECT ON %I TO grafana_ro', t);
       EXECUTE format('CREATE POLICY grafana_ro_read ON %I FOR SELECT TO grafana_ro USING (true)', t);
     END LOOP; END $$;
   ```
   Deliberately excluded (PII / credentials): `users`, `students`, `guardian_student_links`, `guardian_invites`, `gmail_tokens`, `email_scanners`, `email_scanner_matches`, `school_email_messages`, `notifications`.
   Save the SQL (password replaced by `<PASSWORD>`) as `backend/scripts/sql/grafana_ro.sql` for re-runs.

2. Grafana Cloud → Connections → PostgreSQL datasource `schoolz-prod-db`:
   - Host: `aws-1-us-east-1.pooler.supabase.com:5432`
   - User: `grafana_ro.lxithuvstfslndvsdnsk` (pooler username format is `<role>.<project-ref>`)
   - DB: `postgres`. TLS: require.
   - **Max open connections: 2**, max idle: 1. The session pooler's connection budget is shared with the app (see `backend/database.py`'s `pool_size` comment).

3. Build dashboard **"schoolz / Scans"** from these queries. Save the JSON export to `grafana/cloud-dashboards/scans.json`.

   ```sql
   -- Runs by kind × status, selected window
   SELECT j.kind, r.status, count(*) FROM job_runs r JOIN scheduled_jobs j ON j.id = r.job_id
   WHERE $__timeFilter(r.started_at) GROUP BY 1,2 ORDER BY 1,2;

   -- Failure rate per kind over time (time series)
   SELECT $__timeGroupAlias(r.started_at, '12h'), j.kind AS metric,
          avg((r.status = 'error')::int) AS value
   FROM job_runs r JOIN scheduled_jobs j ON j.id = r.job_id
   WHERE $__timeFilter(r.started_at) AND r.status <> 'skipped' GROUP BY 1,2 ORDER BY 1;

   -- Duration p50/p95 per kind
   SELECT j.kind, percentile_cont(0.5) WITHIN GROUP (ORDER BY r.duration_ms)/1000 AS p50_s,
          percentile_cont(0.95) WITHIN GROUP (ORDER BY r.duration_ms)/1000 AS p95_s, max(r.duration_ms)/1000 AS max_s
   FROM job_runs r JOIN scheduled_jobs j ON j.id = r.job_id
   WHERE $__timeFilter(r.started_at) AND r.duration_ms IS NOT NULL GROUP BY 1 ORDER BY p95_s DESC;

   -- Currently failing jobs, with the school name when the job is school-scoped
   SELECT j.kind, j.name, s.name AS school, j.last_status, j.last_run_at, left(j.last_error, 200) AS error
   FROM scheduled_jobs j LEFT JOIN schools s ON s.id = j.params->>'school_id'
   WHERE j.enabled AND j.last_status IN ('error','warning') ORDER BY j.last_status, j.kind;

   -- Stuck runs: process died mid-run (e.g. OOM), row never finalized
   SELECT r.id, j.kind, j.name, r.started_at FROM job_runs r JOIN scheduled_jobs j ON j.id = r.job_id
   WHERE r.status = 'running' AND r.started_at < now() - interval '45 minutes';

   -- Newsletters gone stale
   SELECT label, url, last_scanned_at FROM smore_newsletters
   WHERE last_scanned_at IS NULL OR last_scanned_at < now() - interval '8 days';

   -- Vision backlog
   SELECT count(*) FROM smore_blocks WHERE pending_vision_extraction;
   ```
   Check each column name against `backend/models.py` before saving the panel. `smore_newsletters.label` etc. are from memory. After Phase 3, add `r.error_code` to the tables and a "failures by error_code" bar chart.

4. Grafana-managed alerts (folder `schoolz`, label `app=schoolz`), all against `schoolz-prod-db`, evaluated every 5m:
   - **Job failed twice in a row**: jobs whose last 2 non-skipped runs are both `error`. One failure is often a flaky site; two in a row is real.
   - **Stuck run** > 45 min (query above, count > 0).
   - **No runs at all in 13h** (`max(started_at) < now() - 13h`). The scheduler is dead or not reconciling.
   - **Stale newsletter** > 8 days.
   - **Vision backlog** > 0 for 24h.

**Verify:** the dashboard shows the 2026-09-10 first-prod-run tally (roughly 25 errors of 99). The "Currently failing" table lists the private-preschool `warning` rows.

---

## Phase 2: Backend OpenTelemetry (api + scheduler)

### 2a. Dependencies (`backend/requirements.txt`)
Add, pinned to whatever pip resolves today. All `opentelemetry-instrumentation-*` packages must share one `0.xxbN` version that matches the SDK's `1.xx`:
`opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http`, `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-httpx`, `opentelemetry-instrumentation-sqlalchemy`, `opentelemetry-instrumentation-logging`, `opentelemetry-instrumentation-system-metrics`.
Remove `prometheus-client`.

### 2b. `backend/telemetry.py` (new)
- `telemetry_enabled()`: true only if `OTEL_EXPORTER_OTLP_ENDPOINT` is set and `OTEL_SDK_DISABLED != "true"`. With no endpoint every function no-ops, so pytest and plain local runs send nothing.
- `setup_telemetry(service_name: str)`:
  - Resource: `service.name`, `service.namespace="schoolz"`, `service.version=os.getenv("FLY_IMAGE_REF", "dev")`, `deployment.environment=os.getenv("APP_ENV","local")`, `service.instance.id=os.getenv("FLY_MACHINE_ID") or socket.gethostname()`, `cloud.region=os.getenv("FLY_REGION","local")`. `service.instance.id` is required. Without it, the 2 app machines' cumulative counters collide in one series.
  - TracerProvider + `BatchSpanProcessor(OTLPSpanExporter())`. Skip it if `OTEL_TRACES_EXPORTER == "none"` (local).
  - MeterProvider + `PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=30000)`. Add Views that drop `http.server.request.body.size`/`http.server.response.body.size`, since only duration is needed (keeps the series budget down).
  - LoggerProvider + `BatchLogRecordProcessor(OTLPLogExporter())`, plus an OTel `LoggingHandler(level=INFO)` on the root logger. The existing stdout JSON handler stays: Fly logs keep working.
  - `LoggingInstrumentor().instrument(set_logging_format=False)`, so `otelTraceID`/`otelSpanID` land in the stdout JSON too.
  - `HTTPXClientInstrumentor().instrument()`. This covers scraper calls **and** Claude calls (the `anthropic` SDK uses httpx).
  - `SQLAlchemyInstrumentor().instrument(engine=database.engine.sync_engine)`.
  - `SystemMetricsInstrumentor(config={"process.memory.usage": None, "process.cpu.utilization": None}).instrument()`. Memory matters: the scheduler has been OOM-killed before.
  - Exporters take no constructor args. They read `OTEL_EXPORTER_OTLP_ENDPOINT` (and append `/v1/traces` etc.) and `OTEL_EXPORTER_OTLP_HEADERS` from the environment.
- `shutdown_telemetry()`: `force_flush()` + `shutdown()` on all three providers. Call it from FastAPI lifespan shutdown and the scheduler's stop path, so an auto-stopping machine flushes its last batch.

### 2c. `backend/main.py`
- Call `setup_telemetry("schoolz-api")` right after `setup_logging()`.
- Delete `_HTTP_REQUESTS`, `_HTTP_DURATION`, `_normalize_path`, `app.mount("/metrics", ...)`, and the prometheus import.
- `FastAPIInstrumentor.instrument_app(app, excluded_urls="health")`.
- Keep the `log_requests` middleware's log line. Change `"path": request.url.path` to also include `"route": request.scope.get("route").path if request.scope.get("route") else None`.
- **Cold start**: a module-level `_first_request_seen = False`. On the first non-health request, set span attribute `app.cold_start=True` on the current span, increment `schoolz_cold_start_requests_total`, and log `cold_start_request` with the process uptime (`time.monotonic()` at import vs now).

### 2d. `backend/scheduler/entrypoint.py`
Call `setup_telemetry("schoolz-scheduler")` after `setup_logging()` and `shutdown_telemetry()` after the reconcile loop exits. In `_reconcile`, on success, set an observable-gauge value `schoolz_scheduler_last_reconcile_timestamp_seconds` (unix time) and count `schoolz_scheduler_reconciles_total{outcome}`.

### 2e. `backend/observability.py` (new): all custom instruments, defined once at import via `metrics.get_meter("schoolz")`
The API's proxy meter works even when `setup_telemetry` runs later or never.

| Instrument | Type | Attributes (keep to these; **no ids, no slugs**) |
|---|---|---|
| `schoolz.job.runs` | Counter | `job.kind`, `status` (success/warning/error/skipped), `error_code`, `triggered_by` |
| `schoolz.job.duration` (unit `s`) | Histogram, buckets `[1,5,15,30,60,120,300,600,1200,1800]` | `job.kind`, `status` |
| `schoolz.job.queue_wait` (unit `s`) | Histogram, same buckets | `job.kind` (time blocked on `JOB_CONCURRENCY` semaphore) |
| `schoolz.job.in_flight` | UpDownCounter | `job.kind` |
| `schoolz.scraper.requests` | Counter | `endpoint` (fetch-html/fetch-raw/fetch-paginated), `outcome` (ok/http_502/http_503/http_504/http_other/timeout/transport), `attempt` |
| `schoolz.scraper.duration` (unit `s`) | Histogram | `endpoint`, `outcome` |
| `schoolz.llm.calls` | Counter | `model`, `purpose` (vision/extract/lunch_pdf), `stop_reason` |
| `schoolz.llm.tokens` | Counter | `model`, `purpose`, `direction` (input/output) |
| `schoolz.llm.duration` (unit `s`) | Histogram | `model`, `purpose` |
| `schoolz.parse.issues` | Counter | `job.kind`, `code` (Phase 3) |
| `schoolz.cold_start.requests` | Counter | none |

In Mimir these appear as `schoolz_job_runs_total`, `schoolz_job_duration_seconds_bucket`, etc. **Check the real names in Explore before building panels**, because the OTLP→Prometheus translation adds unit and `_total` suffixes.

Wire-up points:
- `scheduler/runner.py`: see Phase 3 (it changes runner anyway).
- `scraper_client.py:_post`: time each attempt, record `outcome`/`attempt`, and record the semaphore wait as a span event.
- `services/content_extractor.py` (both `messages.create` calls) and `services/lunch_menu.py`: after each call, record `response.usage.input_tokens`/`output_tokens`, `response.stop_reason`, `response.model`, and wall time.

### 2f. Fly config
- `backend/fly.toml` `[env]` needs nothing new: the code sets the resource attributes and the export interval, and `APP_ENV=prod` already exists.
- Secrets (owner runs these, or Sonnet with owner approval):
  ```
  fly secrets set -a schoolz-api \
    OTEL_EXPORTER_OTLP_ENDPOINT=https://otlp-gateway-prod-us-east-2.grafana.net/otlp \
    OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic%20$(printf '%s' '<instanceId>:<schoolz token>' | base64 -w0)"
  ```
  **The `%20` is required.** Header values in that env var are URL-encoded, and a literal space silently breaks auth (401s logged only at debug level).

### 2g. Local
- Default: no `OTEL_*` vars, so telemetry is off. Nothing changes for `pytest` or the plain local stack.
- `OBSERVABILITY=1` stack: `alloy/config.alloy` currently scrapes `/metrics`, which is about to disappear. Replace it with:
  ```alloy
  otelcol.receiver.otlp "default" {
    http { endpoint = "0.0.0.0:4318" }
    output { metrics = [otelcol.exporter.prometheus.mimir.input] }
  }
  otelcol.exporter.prometheus "mimir" { forward_to = [prometheus.remote_write.mimir.receiver] }
  prometheus.remote_write "mimir" { endpoint { url = "http://mimir:8080/api/v1/push" } }
  ```
  Then, in the observability compose profile, give `backend` and `scheduler` `OTEL_EXPORTER_OTLP_ENDPOINT=http://alloy:4318`, `OTEL_TRACES_EXPORTER=none`, `OTEL_LOGS_EXPORTER=none` (Promtail still ships local logs). Update the provisioned "schoolz backend overview" dashboard from `http_requests_total`/`http_request_duration_seconds` to `http_server_request_duration_seconds_{count,bucket}` with label `http_route`.
- Update `CLAUDE.md` "Observability" section and `docs/ENV_SETUP.md` with the new env vars.

**Verify:**
- `cd backend && pytest -q` passes. Add `tests/test_telemetry.py`: without `OTEL_EXPORTER_OTLP_ENDPOINT`, `setup_telemetry` is a no-op and nothing is exported.
- Local `OBSERVABILITY=1` up → Grafana (3001) Explore shows `http_server_request_duration_seconds_count{http_route="/schools/{school_id}/today"}`. The label is the route template, not a slug.
- After deploying: Grafana Cloud Explore → Tempo `{resource.service.namespace="schoolz"}` shows traces from `schoolz-api`. Loki `{service_namespace="schoolz"}` shows logs from both services. `https://schoolz-api.sitenaut.com/metrics` returns 404.

---

## Phase 3: Scan and parse error taxonomy ("what kind of failure was it")

Today a failure is only `f"{type(exc).__name__}: {exc}"` plus a traceback in `log_excerpt`. Warnings are free text. That can't be grouped. Add stable codes.

### 3a. `backend/scheduler/errors.py` (new)
```python
class ScanError(Exception):
    """Raise from a handler/parser to give a failure a stable, groupable reason."""
    def __init__(self, code: str, message: str, *, stage: str, **context): ...
```
Stages: `fetch`, `parse`, `extract`, `persist`. Codes:

| stage | code | when |
|---|---|---|
| fetch | `scraper_timeout` | `httpx.TimeoutException` on a scraper call |
| fetch | `site_did_not_load` | scraper answered 502 (its wrapper for "target site failed/timed out") |
| fetch | `scraper_unavailable` | connect error / 503 / 504 from the scraper |
| fetch | `source_http_error` | direct fetch (PDF, ICS) got 4xx/5xx |
| parse | `selector_missing` | expected DOM anchor absent (e.g. `.fsLocationAddress`, `.block-wrapper`). The site layout probably changed |
| parse | `no_matches` | page loaded, parser found zero rows/links/dates |
| parse | `unexpected_format` | a value found but unparseable (date, table header, PDF row) |
| parse | `pdf_unreadable` | pdfplumber failure / empty text |
| extract | `llm_max_tokens` | `stop_reason == "max_tokens"` |
| extract | `llm_rate_limited` | `anthropic.RateLimitError` |
| extract | `llm_api_error` | other `anthropic.APIError` |
| extract | `llm_bad_output` | tool-use block missing or fails schema |
| extract | `image_unsupported` | vision image couldn't be prepared |
| persist | `db_pool_timeout` | `sqlalchemy.exc.TimeoutError` |
| persist | `db_error` | `sqlalchemy.exc.DBAPIError` |
| — | `unknown` | anything else (group these weekly and promote the common ones to real codes) |

- `classify_exception(exc) -> tuple[str, str]` (code, stage): `ScanError` returns its own; otherwise map library exceptions per the table. Walk `exc.__cause__`/`__context__`, because `scraper_client` re-raises.
- Warning codes: change the 14 `return "WARNING: ..."` sites in `backend/scheduler/jobs/*.py` to `"WARNING[<code>]: ..."`. Codes: `no_marking_period_dates`, `no_preschools_tracked`, `no_preschool_team`, `no_documents_found`, `school_info_missing_fields`, `no_preschool_locations`, `no_menu_pdfs`, `no_staff_found`, `no_rotation_pdf_link`, `rotation_pdf_empty`, `no_ics_events`, `transportation_missing_fields`, and for smore `extraction_warning`. `parse_warning(text) -> str | None` extracts the code with `r"^WARNING\[([a-z_]+)\]:"`, falling back to `"unspecified"` for a bare `WARNING:`. **Keep the `startswith("WARNING")` detection working.**
- `record_parse_issue(job_kind, code, **context)`: logs a WARNING `parse_issue` with `extra={"job_kind":..., "code":..., **context}` and increments `schoolz.parse.issues`. It's for non-fatal problems inside an otherwise-successful scan. Add calls at the known fragile spots (grep for them):
  - `smore_parser._classify` hits an unrecognized block shape.
  - `content_extractor._parse_date` fails, or `_parse_lunch_menu_days` falls back to the raw description.
  - `content_extractor`'s max_tokens path (already logged; add the counter).
  - `_prepare_image` failure (block left `pending_vision_extraction`).
  - `marking_period`: a table heading not found in the tier map.
  - `hs_rotation.parse_rotation_pdf`: words that don't fit a row.
  - `preschool_locations`: address dedup miss.
  - `school_documents._extract_year` returns None.
  Context: `url`, `school_id`, `selector`/`sample` (≤200 chars). **Never** log email bodies or anything from `school_email_messages`.

### 3b. Schema (Alembic migration)
Add to `job_runs`: `error_code String(40) NULL` (indexed), `error_stage String(20) NULL`. Add `scheduled_jobs.last_error_code String(40) NULL`. Warnings set `error_code` to the warning code with `error_stage=NULL`.

### 3c. `backend/scheduler/runner.py`
- Measure the semaphore wait in `_execute` (`perf_counter` before/after `async with`) → `schoolz.job.queue_wait`; pass it into `_execute_locked`.
- Wrap the handler call in a span `job.run` with attributes `job.kind`, `job.id`, `job.triggered_by`, and every `params` key ending in `_id` as `job.param.<key>`. Scraper/Claude/DB spans nest under it automatically.
- `_finalize(...)` takes `error_code`/`error_stage`, writes them to the row, and emits a **single structured log line per run**:
  `logger.log(level, "job_finished", extra={"job_id","run_id","job_kind","status","error_code","error_stage","duration_ms","queue_wait_ms","triggered_by", **param ids})`. Level: INFO for success, WARNING for warning, ERROR for error, with `exc_info` so the traceback is attached (OTel exports it as `exception.stacktrace`).
- Increment `schoolz.job.runs` for **skipped** and **unknown-kind** runs too, which today return early without metrics.
- **Stuck-run reaper**: in `scheduler/entrypoint.py` `main()`, before the reconcile loop, run `UPDATE job_runs SET status='error', error_code='abandoned', error_stage='runtime', error='process exited mid-run (OOM kill, deploy, or crash)', finished_at=now() WHERE status='running' AND started_at < now() - interval '45 minutes'`. The same fix applies to `scheduled_jobs.last_status='running'`. Rationale: an OOM-killed run otherwise stays `running` forever and never counts as a failure.
- `frontend/src/pages/JobsPage.tsx`: show `last_error_code` as a small chip next to the status.

**Verify:**
- Unit tests in `backend/tests/test_scan_errors.py` cover `classify_exception` (fabricated httpx 502 / timeout / anthropic / sqlalchemy exceptions) and `parse_warning`. `pytest -q` passes.
- Locally, point a school's `website_url` at a bad host, run its `info/run-now`, and see a `job_runs` row with `error_code='site_did_not_load'` or `'scraper_unavailable'`.
- In prod Loki:
  ```logql
  sum by (error_code, job_kind) (count_over_time({service_namespace="schoolz", service_name="schoolz-scheduler"} |= "job_finished" | status="error" [24h]))
  ```
  returns rows. OTLP log attributes arrive as structured metadata, so `| status="error"` works without a parser.

---

## Phase 4: Frontend RUM (Grafana Faro)

### 4a. Setup
- `npm i @grafana/faro-react @grafana/faro-web-sdk @grafana/faro-web-tracing` (pin exact versions in `package.json`).
- Build args (`frontend/Dockerfile`, `frontend/fly.toml`, `vite-env.d.ts`): `VITE_FARO_URL` (prod: `/rum/collect`, see 4d). Set `VITE_APP_VERSION` to the git short SHA instead of the literal `"prod"`: in `.github/workflows/deploy.yml` frontend step, `flyctl deploy --remote-only --build-arg VITE_APP_VERSION=${GITHUB_SHA::7}`. Also document the manual-deploy form.
- `src/lib/telemetry.ts`: `initTelemetry()`, a no-op when `VITE_FARO_URL` is empty (local dev, vitest). Call it in `main.tsx` before render.
  ```ts
  initializeFaro({
    url: import.meta.env.VITE_FARO_URL,
    app: { name: "schoolz-web", version: import.meta.env.VITE_APP_VERSION, environment: import.meta.env.MODE === "production" ? "prod" : "local" },
    sessionTracking: { samplingRate: 1 },          // 100% at current traffic; revisit if sessions > free tier
    instrumentations: [
      ...getWebInstrumentations({ captureConsole: true }),
      new TracingInstrumentation({ instrumentationOptions: {
        propagateTraceHeaderCorsUrls: [new RegExp("^" + escapeRegExp(API_URL))],  // API only - NEVER supabase.co
        fetchInstrumentationOptions: { ignoreUrls: [/\/invites\//, /\/rum\//] },
      }}),
      new ReactIntegration({ router: { version: ReactRouterVersion.V6, dependencies: {
        createRoutesFromChildren, matchRoutes, Routes, useLocation, useNavigationType } } }),
    ],
    beforeSend: scrubItem,
  });
  ```
  (If the installed faro-react version exposes `createReactRouterV6Options`, use that form. Check its README.) In `App.tsx`, replace `<Routes>` with `<FaroRoutes>`. That makes view names route templates (`/schools/:schoolId`), not raw URLs.
- **Privacy scrubbing (required, test it)**: `scrubUrl(url)`:
  - Drop the entire `#hash`: Supabase OAuth returns `#access_token=...&refresh_token=...`.
  - Drop query params `code`, `token`, `access_token`, `refresh_token`, `state`.
  - Rewrite `/invites/<token>` → `/invites/:token`.

  `scrubItem` applies it to `item.meta.page.url`, `item.meta.view`, and any string attribute value starting with `http`. Add `src/lib/telemetry.test.ts` covering all three cases. No `setUser` with email/id. Set only `faro.api.setSession` attributes `logged_in`, `is_admin`, `schools_count` (numbers/bools, from `useAuth()`/`useMySchools()` via a small effect in `AppShell`).

### 4b. Custom events and measurements
One helper module `src/lib/track.ts` wrapping `faro.api.pushEvent`/`pushMeasurement`, no-op when Faro isn't initialized.

| Event / measurement | Where | Attributes |
|---|---|---|
| `page_view` event | a `useEffect` on `useLocation()` in `AppShell` | `route` (matched template via `matchRoutes`), `from_route`, `school_slug` when the route has one (public data, fine) |
| `today_ready` measurement (ms) | `TodayPage`: when every active school's `/today` has resolved | `schools` (count), `cold` (bool: first view in session) |
| `school_page_ready` (ms) | `SchoolDetailPage`: when its `Promise.all` resolves | `school_slug` |
| `calendar_ready` (ms) | `CalendarPage` first data render | `mode` (month/year/search) |
| `lunch_ready` (ms) | `LunchPage` | — |
| `action` event | absence button, nurse/counselor/bus/late-bus `tel:`, add-to-Google-Calendar, document open, Sports link | `action`, `method` (mailto/tel/portal), `school_slug` |
| `calendar_search` event | on debounced search resolve | `result_count`, `query_length`. **Never the query text** |
| `school_filter_toggle` event | ribbon chip | `active_count` |
| `schools_picked` event | `/start` save | `count` |

"Ready" = `performance.now()` at the route change (store it in the `page_view` effect) → data rendered. This is the real UX number for an SPA: LCP fires on the shell, before data arrives.

### 4c. Backend CORS
`allow_headers=["*"]` already admits `traceparent`. Add `max_age=86400` to `CORSMiddleware`. Browsers cap it (Chrome 2h), but it cuts repeat preflights. Add `expose_headers=["Server-Timing"]` if Phase 6 adds it.

### 4d. Same-origin RUM proxy (`frontend/nginx.conf`)
```nginx
location = /rum/collect {
    proxy_pass https://faro-collector-prod-us-east-2.grafana.net/collect/<key>;
    proxy_ssl_server_name on;
    proxy_set_header Host faro-collector-prod-us-east-2.grafana.net;
    client_max_body_size 1m;
}
```
Put the collector key in the nginx config via an envsubst template (`/etc/nginx/templates/default.conf.template`, which the `nginx:alpine` image supports natively). Pass it as a `fly secrets set -a schoolz-web FARO_COLLECTOR_URL=...` runtime env, not a build arg. The browser's `Origin` header is forwarded, so the collector's allowed-origins check still works. Side effect: the collector sees Fly's IP, not the visitor's, so there's no per-user geo. Accept that (privacy-positive).

### 4e. Privacy page
Update `frontend/src/pages/PrivacyPage.tsx` and its header comment: replace "No analytics… of any kind" with a truthful, owner-approved line. Suggested:
> "We collect anonymous performance and error data (page load times, which pages are used, errors) to make the site faster. It's tied to a random per-visit session, never to your name, email, or children, and isn't shared with advertisers."

Whether a consent banner is needed is the owner's call, not Sonnet's. Flag it in the PR description.

**Verify:**
- `npm run build && npm run test` pass (including the scrub tests).
- Deploy, open the site, and navigate Today → a school → Calendar. Within ~1 min, Grafana Cloud → Frontend Observability → `schoolz-web` shows the session with Web Vitals and `page_view` events.
- Open one fetch span → "View trace" goes to the matching `schoolz-api` server span in Tempo. That proves traceparent propagation.
- An OAuth login round-trip leaves no `access_token` anywhere in Faro data. Search Loki for `{app_name="schoolz-web"} |= "access_token"`: zero results.

---

## Phase 5: Scraper service

- Same OTel deps (minus sqlalchemy/system-metrics if unwanted). Copy a trimmed `telemetry.py` into `scraper/`. The scraper is standalone on purpose, so don't import from backend. Use `service.name=schoolz-scraper`.
- `FastAPIInstrumentor.instrument_app(app, excluded_urls="health")`. Trace context arrives from backend httpx automatically, so a scan's trace now spans backend → scraper.
- Manual spans around `page.goto`, `wait_for_selector`, each paginated click, with attributes `url.host` (not the full URL), `selector`, `page_index`.
- Metrics: `schoolz.scraper.page_load` histogram {`host`, `outcome`}. About 40 school hosts is fine cardinality. Also `schoolz.scraper.pages_open` up-down counter, and `schoolz.scraper.browser_restarts` counter if the service restarts Chromium.
- `fly secrets set -a schoolz-scraper` with the same two OTEL vars. Deploy manually (`cd scraper && fly deploy --remote-only`). CI doesn't deploy the scraper.

**Verify:** a manual `smore/run-now` in prod produces one trace containing `job.run` → `POST /fetch-html` → scraper `page.goto` → Claude `POST /v1/messages` spans.

---

## Phase 6: Dashboards, alerts, and the "what should we simplify" review

Dashboards (export JSON to `grafana/cloud-dashboards/`, one file each):

1. **schoolz / Scans**: Phase 1 SQL panels, plus:
   - `sum by (job_kind, status) (increase(schoolz_job_runs_total[12h]))`
   - p95 `histogram_quantile(0.95, sum by (le, job_kind) (rate(schoolz_job_duration_seconds_bucket[1h])))`
   - Queue wait p95 during the burst.
   - `schoolz_job_in_flight`.
   - Scraper outcome ratio.
   - Failures by `error_code` (SQL + LogQL).
   - Recent `parse_issue` log panel.
   - LLM tokens/day by purpose, with a cost estimate (look up current Haiku/Sonnet prices via the claude-api skill; don't hardcode from memory).
   - Count of `stop_reason="max_tokens"`.
2. **schoolz / API**:
   - RED per `http_route` (rate, error ratio, p50/p95).
   - Top routes by total time `sum by (http_route) (rate(http_server_request_duration_seconds_sum[1h]))`. This is where the server's time actually goes.
   - DB pool usage (`db_client_connections_usage`).
   - Process memory per service (scheduler especially).
   - Cold-start count and cold-request latency.
3. **schoolz / User experience** (Faro data in Loki/Tempo; supplements the built-in Frontend Observability app):
   - p75 LCP/INP/CLS/TTFB by route.
   - p50/p75 of each `*_ready` measurement.
   - Top routes by `page_view` count.
   - Top `school_slug`s.
   - **Transitions table** `from_route → route` counts (user paths).
   - Entry routes (`from_route` empty).
   - Top `action`s.
   - JS errors by route.
   - **API calls per page view**: count of fetch spans grouped by the view they fired in.
   - Device/browser split.

Additional metric alerts (same `schoolz` folder, label `app=schoolz`):
- Scheduler heartbeat: `time() - max(schoolz_scheduler_last_reconcile_timestamp_seconds) > 300`, or the series is absent for 10m.
- Error ratio per kind > 30% across a 12h burst window.
- API 5xx ratio > 2% for 10m.
- p95 of public GETs > 1.5s for 15m.
- `increase(schoolz_llm_calls_total{stop_reason="max_tokens"}[1h]) > 0`.
- Scraper `site_did_not_load` + `scraper_timeout` > 30% of scraper calls in 1h.
- RUM: daily p75 LCP > 4s, JS error sessions > 5%.

### Hypotheses the data should confirm or kill (after ~1 week of real traffic)

Found while writing this plan. **Measure before changing any of them.**

1. **Every API GET triggers a CORS preflight.** `apiFetch` always sends `Content-Type: application/json`, even on bodyless GETs. That makes every cross-origin request non-simple, and `traceparent` will too. Each unique URL pays one extra round trip until the preflight cache expires. Check: OPTIONS rate vs GET rate on the API dashboard; RUM fetch timing. Fixes, in order of size:
   - Drop `Content-Type` on GET (small, but moot once traceparent is on).
   - Serve the API same-origin (`schoolz.sitenaut.com/api/*` proxied by nginx). No preflights at all.
2. **School page fan-out.** `SchoolDetailPage` fires 7 parallel requests (`/today`, `/content`, `/staff`, `/documents`, `/sacc`, `/newsletters`, `/transportation`), each its own preflight + DB session. Candidate: one `GET /schools/{id}/page` aggregate. Check: `school_page_ready` p75 vs the slowest single call in the trace.
3. **Today page N+1.** `TodayPage` calls `/schools/{slug}/today` once per picked school. Candidate: `GET /today?schools=a,b,c`. Check: `today_ready` vs `schools` count.
4. **Full school list on every load.** `MySchoolsProvider` fetches all of `/schools` on every app load, even on pages that only need the picked ones. Candidate: cache with `Cache-Control: max-age` + ETag, or embed the list in the bundle at build time. Check: `/schools` share of total API time.
5. **Cold starts dominate p95.** Both `schoolz-api` and `schoolz-web` run `min_machines_running = 0`. Check: `app.cold_start` request latency and RUM TTFB p95 vs p50. The fix (`min_machines_running = 1` on `schoolz-api`) costs a small always-on machine; the owner decides once the numbers exist.
6. **12h burst queueing.** `JOB_CONCURRENCY=3` and scraper concurrency 3 with about 85 jobs in one minute. Check: `schoolz_job_queue_wait` p95. Candidate: jitter cron minutes per job instead of `0 */12 * * *` for all of them.

Write the findings up in this doc's appendix after a week. Each fix is its own follow-up change, not part of this plan.

---

## Series budget (shared stack with billz)

Rough ceiling for schoolz:
- HTTP duration: about 60 routes × 3 statuses × 16 buckets × 2 instances ≈ 6k series worst case. It's usually far lower, since most routes see one status.
- Job metrics: about 13 kinds × 4 statuses × 11 buckets ≈ 600.
- Everything else: under 500.

After Phase 2 has run 24h, check Grafana Cloud → Usage → Metrics (active series by `job`). If `job=~"schoolz/.*"` is above about 5k, trim the HTTP histogram buckets with a View first. Check the current free-tier limits on the stack's billing page; don't assume them.

## Guardrails for the executor

- Never commit secrets. Collector keys and tokens go in Fly secrets and `env/secrets.*.env` only.
- Never attach user ids, emails, student names, search text, or invite tokens to any metric, log, span, or RUM event.
- Metric attributes stay low-cardinality (no ids, slugs, or URLs). Put those in spans and logs.
- Don't change behavior while instrumenting. The one intended behavior change is the stuck-run reaper (Phase 3).
- `fly deploy`, `fly secrets set`, and SQL against prod Supabase are prod actions. Confirm with the owner before each.
