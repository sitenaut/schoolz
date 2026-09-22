"""Turn whatever an admin copied out of billz into local_events.refresh jobs.

billz has no export, so this accepts the three things you can actually copy
from it: the params JSON (the job editor's Copy button), one job object, or
the whole GET /admin/scheduled-jobs list. Only billz's events.refresh maps
here - its params are the same shape, since local_events/ is a port of that
pipeline - and every other kind (plaid.sync, gmail.sync, ...) is reported as
skipped rather than silently dropped."""

from __future__ import annotations

import json

from croniter import croniter

BILLZ_KIND = "events.refresh"
KIND = "local_events.refresh"
SOURCE_KEYS = (
    "evvnt_sources",
    "json_sources",
    "ical_sources",
    "rss_sources",
    "gcal_sources",
    "listing_page_sources",
    "sitemap_sources",
    "deyra_schedule_sources",
    "scraper_sources",
)


def _is_params(obj: dict) -> bool:
    return "kind" not in obj and any(k in obj for k in SOURCE_KEYS)


def plan_import(text: str) -> tuple[list[dict], list[dict]]:
    """Returns (jobs_to_create, skipped). Each job is a ScheduledJobCreate-shaped
    dict; each skipped entry is {"name", "reason"}. Raises ValueError on
    input that isn't JSON or isn't any of the accepted shapes."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Not valid JSON: {exc}") from exc
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        data = data["items"]
    entries = data if isinstance(data, list) else [data]

    jobs: list[dict] = []
    skipped: list[dict] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            skipped.append({"name": f"entry {i + 1}", "reason": "not a JSON object"})
            continue
        if _is_params(entry):
            jobs.append({"kind": KIND, "name": "Local events refresh (from billz)", "description": None, "cron_expr": "0 */6 * * *", "timezone": "America/New_York", "params": entry, "enabled": True})
            continue
        name = str(entry.get("name") or f"entry {i + 1}")
        kind = entry.get("kind")
        if kind not in (BILLZ_KIND, KIND):
            skipped.append({"name": name, "reason": f"kind {kind!r} has no schoolz equivalent" if kind else "no kind and no *_sources keys"})
            continue
        params = entry.get("params")
        if not isinstance(params, dict):
            skipped.append({"name": name, "reason": "params missing or not an object"})
            continue
        cron = entry.get("cron_expr") or "0 */6 * * *"
        if not croniter.is_valid(cron):
            skipped.append({"name": name, "reason": f"invalid cron {cron!r}"})
            continue
        jobs.append(
            {
                "kind": KIND,
                "name": name[:200],
                "description": (entry.get("description") or None) and str(entry["description"])[:500],
                "cron_expr": cron,
                "timezone": entry.get("timezone") or "America/New_York",
                "params": params,
                "enabled": bool(entry.get("enabled", True)),
            }
        )
    if not jobs and not skipped:
        raise ValueError("Nothing to import")
    return jobs, skipped
