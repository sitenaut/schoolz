"""Scheduled job: refresh Localz's child care providers from ChildCareNJ.gov
(resources/childcarenj.py).

Weekly: 21 requests, one per county, 5 s apart - a couple of minutes. Kept
apart from resources.refresh so NJ 211's hours-long throttled crawl never
holds it up, and so a refusal from one source doesn't stop the other."""
from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from resources.childcarenj import MIN_DELAY_SECONDS, NJ_COUNTIES
from resources.refresh import refresh_childcarenj
from scheduler.registry import register_job

DEFAULT_PARAMS = {
    "childcarenj": {
        "counties": NJ_COUNTIES,
        "delay_seconds": MIN_DELAY_SECONDS,
    },
}


@register_job(
    kind="resources.childcarenj",
    default_name="Child care providers refresh",
    default_cron="41 4 * * 2",
    default_params=DEFAULT_PARAMS,
    description="Localz child care providers from ChildCareNJ.gov's directory (one request per county, 5 s apart). Home daycares are kept at town level.",
)
async def run(db: AsyncSession, params: dict) -> str | None:
    cfg = params.get("childcarenj")
    if not cfg:
        return "WARNING[resources_no_sources]: no childcarenj params"
    summary = await refresh_childcarenj(db, cfg)
    text = json.dumps(summary, default=str)
    if summary["blocked"]:
        return f"WARNING[resource_source_blocked]: ChildCareNJ refused us - stopped: {text}"
    if summary["errors"]:
        return f"WARNING[resource_source_partial]: {len(summary['errors'])} error(s): {text}"
    if summary["listed"] == 0:
        return f"WARNING[resource_source_empty]: ChildCareNJ returned no providers - endpoint changed? {text}"
    if summary["unknown_codes"]:
        return f"WARNING[resource_unknown_codes]: codes missing from the lookup table: {', '.join(summary['unknown_codes'][:10])}: {text}"
    return text
