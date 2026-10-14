#!/usr/bin/env bash
# Claude Code `otelHeadersHelper`: prints the Authorization header for the
# Grafana Cloud OTLP gateway as JSON, so the token never sits in a settings file.
#
#   CLAUDE_CODE_OTLP_INSTANCE_ID   the stack's OTLP instance id (the number on its OpenTelemetry tile)
#   CLAUDE_CODE_OTLP_TOKEN_REF     a 1Password reference (op://vault/item/field) to a Grafana Cloud
#                                  access-policy token with the metrics:write scope and nothing else
#
# Docs: docs/CLAUDE_CODE_TELEMETRY.md
set -euo pipefail
: "${CLAUDE_CODE_OTLP_INSTANCE_ID:?set CLAUDE_CODE_OTLP_INSTANCE_ID}"
: "${CLAUDE_CODE_OTLP_TOKEN_REF:?set CLAUDE_CODE_OTLP_TOKEN_REF}"
# Same fallback compose-local.sh uses, so a session needs no interactive `op signin`.
token_file="${SCHOOLZ_OP_TOKEN_FILE:-${XDG_CONFIG_HOME:-$HOME/.config}/schoolz/op-local-token}"
if [ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" ] && [ -r "$token_file" ]; then
  OP_SERVICE_ACCOUNT_TOKEN="$(<"$token_file")"
  export OP_SERVICE_ACCOUNT_TOKEN
fi
token=$(op read "$CLAUDE_CODE_OTLP_TOKEN_REF")
basic=$(printf '%s:%s' "$CLAUDE_CODE_OTLP_INSTANCE_ID" "$token" | base64 | tr -d '\n')
printf '{"Authorization":"Basic %s"}\n' "$basic"
