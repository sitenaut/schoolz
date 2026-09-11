-- Panel queries for the Grafana Cloud "schoolz / Scans" dashboard
-- (datasource: PostgreSQL "schoolz-prod-db", see docs/OBSERVABILITY_PLAN.md
-- Phase 1). Column/table names checked against backend/models.py.
--
-- This is NOT a Grafana dashboard JSON export - creating the datasource,
-- panels, and alert rules is a Grafana Cloud console step (or needs a
-- Grafana instance admin API token, which is separate from the OTLP
-- metrics/logs/traces write token in env/secrets.prod.env). These queries
-- are what to paste into each panel's query editor.

-- Runs by kind x status, selected window
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

-- Alert conditions (create as Grafana-managed alert rules against the same
-- datasource, folder "schoolz", label app=schoolz, evaluated every 5m,
-- contact point: enr@profitnaut.com):
--   1. Job failed twice in a row: jobs whose last 2 non-skipped runs are both 'error'.
--   2. Stuck run > 45 min (query above, count > 0).
--   3. No runs at all in 13h: max(started_at) < now() - interval '13 hours'.
--   4. Stale newsletter > 8 days (query above, count > 0).
--   5. Vision backlog > 0 for 24h.
