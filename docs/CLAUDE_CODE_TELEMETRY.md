# Claude Code telemetry

Coding-agent sessions are the largest Anthropic cost centre and the one the app
cannot meter: they never pass through `observability.record_llm_call`. Claude
Code has its own OpenTelemetry export, which can feed the same Grafana Cloud
stack. The **Claude Code** panels at the bottom of `schoolz / Cost` read it.

On a subscription the dollar figure is what the same tokens would cost at API
list prices, not what was charged. That is the number to weigh against the
subscription's price.

## Setup (once per machine)

1. In Grafana Cloud, create an **access policy** with the `metrics:write` scope
   only, and a token for it. Store the token in 1Password.
2. In the user-level Claude Code settings (not a repo file), set:

   ```json
   {
     "env": {
       "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
       "OTEL_METRICS_EXPORTER": "otlp",
       "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
       "OTEL_EXPORTER_OTLP_ENDPOINT": "<the stack's OTLP gateway URL, no trailing path>",
       "CLAUDE_CODE_OTLP_INSTANCE_ID": "<OTLP instance id>",
       "CLAUDE_CODE_OTLP_TOKEN_REF": "op://<vault>/<item>/<field>"
     },
     "otelHeadersHelper": "<absolute path to scripts/claude-code-otel-headers.sh>"
   }
   ```

   The gateway URL and instance id are on the stack's OpenTelemetry tile
   (`docs/OBSERVABILITY_PLAN.md`). `otelHeadersHelper` builds the Basic auth
   header from the token at export time.
3. Tag each project in its **untracked** project settings:
   `"env": {"OTEL_RESOURCE_ATTRIBUTES": "service.namespace=schoolz"}`.
   `service_namespace` is the same label every other app on the stack uses, and
   it is what `Claude Code spend, by project` groups by. A project without it
   shows as an unlabelled bar.

Prompts and tool contents are not exported unless `OTEL_LOG_USER_PROMPTS` or
`OTEL_LOG_TOOL_DETAILS` is set; leave both off. Only metrics are enabled here.

## Check it

Restart Claude Code, run a few turns, then in Grafana Explore query
`claude_code_cost_usage_USD_total`. The first points can take a few minutes.
Metric names come from Claude Code's `claude_code.cost.usage`,
`claude_code.token.usage` and `claude_code.session.count` after Prometheus
renaming; if a panel stays empty with data flowing, check the spelling in
Explore first (same advice as the `observability` skill).

## What is still not metered

Anything billed flat (Fly, Supabase, the scraper droplet, domains), and coding
sessions on a machine that has not done the setup above.
