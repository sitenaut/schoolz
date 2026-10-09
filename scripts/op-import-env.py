#!/usr/bin/env python3
"""One-time import of the env/ secret files into 1Password.

Each variable becomes its own API Credential item, titled exactly as the
variable, so templates can reference op://<vault>/<NAME>/credential.
Prints names only, never values. Values reach `op` on stdin (a JSON
template), not argv, so they don't show up in `ps`.

    eval $(op signin)
    python3 scripts/op-import-env.py            # dry run: what would be created
    python3 scripts/op-import-env.py --apply    # create the vaults and items

Idempotent: an item that already exists in its vault is skipped, never
overwritten. Re-run after adding a variable to an env file.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / "env"

# vault -> files whose every variable goes into it
VAULT_FILES = {
    "schoolz-local": ["secrets.local.env", "db.local.env"],
    "schoolz-prod": ["secrets.prod.env", "db.prod.env", "api-keys.env"],
}
# The CI vault holds only what .github/workflows read. FLY_API_TOKEN isn't in
# any env file; add it by hand (op item create --vault schoolz-ci ...).
CI_VAULT = "schoolz-ci"
CI_NAMES = {"DATABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_URL"}
CI_FILES = ["secrets.prod.env", "db.prod.env", "auth.supabase-prod.env"]

# Variables holding a path to a key file: the file itself is stored as a
# Document item titled after the variable.
FILE_VARS = {"GRAFANA_GA_SERVICE_ACCOUNT_FILE"}


def parse(path):
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            out[name.strip()] = value
    return out


def collect(files, only=None):
    """Merge files; a name defined twice with different values is a conflict."""
    merged, conflicts = {}, set()
    for f in files:
        for name, value in parse(ENV / f).items():
            if only and name not in only:
                continue
            if name in merged and merged[name] != value:
                conflicts.add(name)
            merged.setdefault(name, value)
    for name in conflicts:
        merged.pop(name)
    return merged, conflicts


def op(*args, stdin=None):
    return subprocess.run(["op", *args], input=stdin, capture_output=True, text=True)


def main():
    apply = "--apply" in sys.argv
    if op("whoami").returncode != 0:
        sys.exit("Not signed in: run  eval $(op signin)  first.")

    plan = {v: collect(files) for v, files in VAULT_FILES.items()}
    plan[CI_VAULT] = collect(CI_FILES, only=CI_NAMES)

    existing_vaults = {v["name"] for v in json.loads(op("vault", "list", "--format", "json").stdout or "[]")}
    failures = 0
    for vault, (items, conflicts) in plan.items():
        print(f"\n== {vault}")
        for name in sorted(conflicts):
            print(f"  CONFLICT {name}: defined twice with different values, skipped; add it by hand")
        if vault not in existing_vaults:
            print(f"  + vault {vault}")
            if apply:
                r = op("vault", "create", vault)
                if r.returncode:
                    sys.exit(f"  vault create failed: {r.stderr.strip()}")
        have = set()
        if vault in existing_vaults:
            have = {i["title"] for i in json.loads(op("item", "list", "--vault", vault, "--format", "json").stdout or "[]")}
        for name in sorted(items):
            if name in have:
                print(f"  = {name} (exists, skipped)")
                continue
            value = items[name]
            if name in FILE_VARS:
                path = (ROOT / value) if not Path(value).is_absolute() else Path(value)
                print(f"  + {name} (document: {path.name})")
                if apply:
                    r = op("document", "create", str(path), "--vault", vault, "--title", name)
                    failures += _report(r, name)
                continue
            print(f"  + {name}")
            if apply:
                template = {
                    "title": name,
                    "category": "API_CREDENTIAL",
                    "fields": [{"id": "credential", "type": "CONCEALED", "label": "credential", "value": value}],
                }
                r = op("item", "create", "--vault", vault, "--format", "json", stdin=json.dumps(template))
                failures += _report(r, name)

    if not apply:
        print("\nDry run. Re-run with --apply to create the above.")
    elif failures:
        sys.exit(f"\n{failures} item(s) failed; fix and re-run (existing items are skipped).")
    else:
        print("\nDone.")


def _report(r, name):
    if r.returncode:
        # op's stderr names the problem, not the value
        print(f"    FAILED {name}: {r.stderr.strip()[:200]}")
        return 1
    return 0


if __name__ == "__main__":
    main()
