#!/usr/bin/env bash
# Make the key that encrypts Gmail tokens at rest (backend/crypto.py) and put
# it where it lives: first the schoolz-prod 1Password vault, then the Fly
# secret DATA_ENCRYPTION_KEYS on schoolz-api (which restarts its machines).
#
#   scripts/new-encryption-key.sh
#
# Run it yourself, signed in to 1Password with an account that can write to
# schoolz-prod (`eval $(op signin)`): the prod service account is read-only,
# and no agent session should hold this key. The key is never printed and
# never in argv. Once set, encrypt the existing rows (docs/ENV_SETUP.md).
#
# Refuses if DATA_ENCRYPTION_KEYS is already set: rotating means putting a new
# key in front of the old one, which this script does not do.
set -euo pipefail

app=${SCHOOLZ_FLY_APP:-schoolz-api}
vault=${SCHOOLZ_OP_PROD_VAULT:-schoolz-prod}
name=DATA_ENCRYPTION_KEYS

die() { echo "$*" >&2; exit 2; }
command -v op >/dev/null || die "op (1Password CLI) not found"
command -v fly >/dev/null || die "fly not found"
command -v openssl >/dev/null || die "openssl not found"
op whoami >/dev/null 2>&1 || die "not signed in to 1Password: run  eval \$(op signin)  first"

if fly secrets list -a "$app" | awk '{print $1}' | grep -qx "$name"; then
  die "$name is already set on $app; nothing changed"
fi
if op item get "$name" --vault "$vault" >/dev/null 2>&1; then
  die "$vault already has an item named $name; nothing changed (set the Fly secret from it by hand)"
fi

# A Fernet key: 32 random bytes, URL-safe base64.
key=$(openssl rand 32 | base64 | tr '+/' '-_')
[ ${#key} -eq 44 ] || die "could not make a key; nothing changed"

# Vault first: a key that reaches Fly but not the vault could be lost.
printf '{"title":"%s","category":"API_CREDENTIAL","fields":[{"id":"credential","type":"CONCEALED","label":"credential","value":"%s"}]}' "$name" "$key" \
  | op item create --vault "$vault" >/dev/null
back=$(op read "op://$vault/$name/credential")
[ "$back" = "$key" ] || die "the vault did not read back the key; Fly was not changed (check $vault/$name)"
unset back

printf '%s=%s\n' "$name" "$key" | fly secrets import -a "$app"
unset key
echo "$name is in $vault and set on $app."
