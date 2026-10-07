# API keys

The model (what a key can do) is in the root `CLAUDE.md` under Access model. This is how to get one.

Get one with **`scripts/schoolz-api.sh login prod`**, a device flow built because the owner is often on a phone: it prints a code and an `/admin/api-keys/approve?code=` link, a super admin approves in any signed-in browser, and the script writes the key into gitignored `env/api-keys.env` (0600) — it never passes through chat or the screen. The key is minted when the script collects it (`ApiKeyRequest`, 10-min window, single use), so plaintext is never stored. `/auth/device/start` and `/token` are unauthenticated, bounded by a cap on open requests. `RequireAdmin` carries `?next=` through login so the link survives an expired session. The script passes the key to curl on a file descriptor so it never appears in argv.
