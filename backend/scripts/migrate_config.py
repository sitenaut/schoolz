"""Ports centrally-managed configuration (districts, schools, Smore
newsletters, SACC programs, and every recurring scan they imply) from one
schoolz environment to another - the tool for "I've set all this up
locally, now get it into prod without starting from scratch."

It's a thin client for GET /admin/config/export and POST /admin/config/import
(backend/routers/admin_config.py) - both admin-only. Nothing here talks to
a database directly; it just calls the API on each side, the same way a
person clicking through the admin UI would, so the same job-creation
logic runs in both places.

Usage:
    python scripts/migrate_config.py \\
        --source-url http://localhost:8000 --source-user admin --source-password ... \\
        --target-url https://schoolz-api.fly.dev --target-user admin --target-password ...

Or, to inspect what would be exported without importing anywhere:
    python scripts/migrate_config.py --source-url http://localhost:8000 \\
        --source-user admin --source-password ... --dry-run --out export.json

Or, to import a previously-saved export file instead of pulling live:
    python scripts/migrate_config.py --in export.json \\
        --target-url https://schoolz-api.fly.dev --target-user admin --target-password ...

Safe to re-run: import is idempotent (matched by district name / school
slug / newsletter url), so running this again after making more changes
locally only pushes what's different.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request


def _post(url: str, body: dict | None = None, token: str | None = None) -> dict:
    headers = {"content-type": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else b""
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"POST {url} failed: {exc.code} {exc.read().decode()[:500]}")


def _get(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"GET {url} failed: {exc.code} {exc.read().decode()[:500]}")


def login(base_url: str, username: str, password: str) -> str:
    result = _post(f"{base_url.rstrip('/')}/auth/login", {"username_or_email": username, "password": password})
    return result["access_token"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-url", help="Base URL of the environment to export FROM, e.g. http://localhost:8000")
    parser.add_argument("--source-user")
    parser.add_argument("--source-password")
    parser.add_argument("--in", dest="infile", help="Import from a previously-saved JSON file instead of --source-*")
    parser.add_argument("--out", help="Save the export to this file (in addition to importing, if --target-* is given)")
    parser.add_argument("--target-url", help="Base URL of the environment to import INTO, e.g. https://schoolz-api.fly.dev")
    parser.add_argument("--target-user")
    parser.add_argument("--target-password")
    parser.add_argument("--dry-run", action="store_true", help="Export (and optionally save with --out) without importing anywhere")
    args = parser.parse_args()

    if args.infile:
        with open(args.infile) as f:
            export = json.load(f)
    elif args.source_url:
        if not (args.source_user and args.source_password):
            raise SystemExit("--source-user and --source-password are required with --source-url")
        token = login(args.source_url, args.source_user, args.source_password)
        export = _get(f"{args.source_url.rstrip('/')}/admin/config/export", token)
    else:
        raise SystemExit("Provide either --source-url (+ credentials) or --in <file>")

    print(
        f"Exported {len(export['districts'])} district(s), {len(export['schools'])} school(s), "
        f"{len(export['smore_newsletters'])} newsletter(s) (from {export.get('exported_at')})."
    )

    if args.out:
        with open(args.out, "w") as f:
            json.dump(export, f, indent=2)
        print(f"Saved export to {args.out}")

    if args.dry_run or not args.target_url:
        if not args.dry_run:
            print("No --target-url given - nothing imported. Pass --target-url (+ credentials) to actually port this over.")
        return

    if not (args.target_user and args.target_password):
        raise SystemExit("--target-user and --target-password are required with --target-url")
    target_token = login(args.target_url, args.target_user, args.target_password)
    result = _post(f"{args.target_url.rstrip('/')}/admin/config/import", export, token=target_token)

    print("Import result:")
    for key, value in result.items():
        print(f"  {key}: {value}")
    if result.get("smore_skipped"):
        print(
            "\nNote: the skipped newsletters above are linked to a school slug that doesn't exist in the "
            "target environment yet - import schools first (they are, in the same call, so this usually means "
            "the school itself failed to import - check the school list above)."
        )


if __name__ == "__main__":
    main()
