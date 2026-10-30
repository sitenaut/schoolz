# Fly scraper telemetry

The droplet and the Pi ship their scraper's metrics and logs to Grafana Cloud
with a host agent (playwright-scraper's `deploy/alloy/config.alloy`). Fly has
no host agent, so two small apps in the `schoolz` Fly org stand in for it and
label everything `service_namespace="scraper"`, `host="scraper-fly"`, the way
the droplet labels its own. The scraper repo's **Scraper host** dashboard and
its per-host alerts (last success, canary, `up`, failure rate, busy, watchdog)
then cover Fly too. Node, cAdvisor, blackbox and journal series don't exist
here, so host-level panels stay droplet-only.

| app | image | ships |
|---|---|---|
| `schoolz-scraper-metrics` | Grafana Alloy (`metrics/config.alloy`) | each scraper machine's `/metrics` as `job="scraper/app"`, `instance=<its address>` |
| `schoolz-scraper-logs` | Vector (`logs/vector.yaml`) | the app's output as `job="scraper/docker"`, Fly's own lines about it (machine starts, OOM kills) as `job="scraper/journal"` |

- **Metrics need `METRICS_ADDR = "::"` in `scraper/fly.toml`.** Fly's private
  network is IPv6-only, and the scraper's metrics server listens on IPv4 by
  default. Alloy finds the machines through `schoolz-scraper.internal`.
- **Logs come from Fly's NATS log stream** (`[fdaa::3]:4223`, subject
  `logs.schoolz-scraper.>`), which takes an org token. It is a read-only token
  for the `schoolz` org (billz is in another org), named "schoolz-scraper-logs
  (Vector, NATS log stream)", valid for two years from its creation in
  October 2026: when it expires the logs stop. Replace it with
  `fly tokens create readonly --org schoolz` piped into `fly secrets import`.
- **One machine each** (`--ha=false`); two would ship everything twice.

## Secrets

Set once, through `scripts/prod-secrets.sh`, never typed or printed:

| app | secret |
|---|---|
| both | `GRAFANA_CLOUD_API_KEY`: the bare `glc_` token behind `SCHOOLZ_OTLP_TOKEN` (the backend's OTLP write token) |
| metrics | `GRAFANA_CLOUD_PROMETHEUS_URL` (`<the grafanacloud-*-prom datasource URL>/push`), `GRAFANA_CLOUD_PROMETHEUS_USER_ID` (its basic-auth user) |
| logs | `GRAFANA_CLOUD_LOKI_URL` (the Loki host alone, `https://logs-prod-NNN.grafana.net`: Vector adds the push path), `GRAFANA_CLOUD_LOKI_USER_ID`, `FLY_ACCESS_TOKEN` |

Grafana Cloud's own datasources point at internal hosts
(`prometheus-prod-56-prod-us-east-2-local-nlb.internal.grafana.net`) that only
resolve inside Grafana's network; the public push host is the same name without
`-local-nlb.internal`.

Rotating `SCHOOLZ_OTLP_TOKEN` means re-staging it here too, or both apps go
quiet.

## Deploy

```
scripts/deploy-scraper-telemetry.sh          # both
scripts/deploy-scraper-telemetry.sh logs     # or one
```

Check: `up{service_namespace="scraper", host="scraper-fly"}` is 1 per scraper
machine, and `{service_namespace="scraper", host="scraper-fly"}` has lines in
Loki. `fly logs -a schoolz-scraper-logs` shows a NATS auth failure, if any.
