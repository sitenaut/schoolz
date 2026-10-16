"""Scheduled job: refresh Localz's community resources (resources/).

NJ 211 is the only source so far. Daily: a list crawl when the last one is
`list_every_days` old, then up to `max_details_per_run` full records. The
first detail backfill (~6,000 statewide) is spread over nights by the
per-run cap.

Places are where NJ 211 is asked "what serves here?" - one per county
(location there means "serves this place", not a radius)."""
from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from resources.refresh import DEFAULT_TAXONOMY_ROOTS, refresh_nj211
from scheduler.registry import register_job

DEFAULT_PARAMS = {
    "nj211": {
        # One place per county (its seat): NJ 211 answers "what serves this
        # place?", and `county` records which county's search listed each
        # service. ~1,100 list pages for all 21, about 3 h at 10 s a page,
        # once every `list_every_days`; the start rotates daily.
        "places": [
            {"label": "Mays Landing, NJ", "county": "Atlantic", "lat": 39.4523, "lon": -74.7277},
            {"label": "Hackensack, NJ", "county": "Bergen", "lat": 40.8859, "lon": -74.0435},
            {"label": "Mount Holly, NJ", "county": "Burlington", "lat": 39.9929, "lon": -74.7874},
            {"label": "Cherry Hill, NJ", "county": "Camden", "lat": 39.9348, "lon": -75.0246},
            {"label": "Cape May Court House, NJ", "county": "Cape May", "lat": 39.0826, "lon": -74.8238},
            {"label": "Bridgeton, NJ", "county": "Cumberland", "lat": 39.4273, "lon": -75.2341},
            {"label": "Newark, NJ", "county": "Essex", "lat": 40.7357, "lon": -74.1724},
            {"label": "Woodbury, NJ", "county": "Gloucester", "lat": 39.8382, "lon": -75.1527},
            {"label": "Jersey City, NJ", "county": "Hudson", "lat": 40.7178, "lon": -74.0431},
            {"label": "Flemington, NJ", "county": "Hunterdon", "lat": 40.5123, "lon": -74.8593},
            {"label": "Trenton, NJ", "county": "Mercer", "lat": 40.2206, "lon": -74.7597},
            {"label": "New Brunswick, NJ", "county": "Middlesex", "lat": 40.4862, "lon": -74.4518},
            {"label": "Freehold, NJ", "county": "Monmouth", "lat": 40.2601, "lon": -74.2738},
            {"label": "Morristown, NJ", "county": "Morris", "lat": 40.7968, "lon": -74.4815},
            {"label": "Toms River, NJ", "county": "Ocean", "lat": 39.9537, "lon": -74.1979},
            {"label": "Paterson, NJ", "county": "Passaic", "lat": 40.9168, "lon": -74.1718},
            {"label": "Salem, NJ", "county": "Salem", "lat": 39.5718, "lon": -75.4671},
            {"label": "Somerville, NJ", "county": "Somerset", "lat": 40.5743, "lon": -74.6099},
            {"label": "Newton, NJ", "county": "Sussex", "lat": 41.0579, "lon": -74.7527},
            {"label": "Elizabeth, NJ", "county": "Union", "lat": 40.664, "lon": -74.2107},
            {"label": "Belvidere, NJ", "county": "Warren", "lat": 40.8298, "lon": -75.0777},
        ],
        "taxonomy_roots": DEFAULT_TAXONOMY_ROOTS,
        "list_every_days": 6,
        "max_details_per_run": 300,
        "detail_refresh_days": 30,
        "delay_seconds": 10,
    }
}


@register_job(
    kind="resources.refresh",
    default_name="Community resources refresh",
    default_cron="23 3 * * *",
    default_params=DEFAULT_PARAMS,
    description="Crawl NJ 211's public directory (politely: robots.txt, 10 s between requests) into Localz's community resources.",
)
async def run(db: AsyncSession, params: dict) -> str | None:
    cfg = params.get("nj211")
    if not cfg:
        return "WARNING[resources_no_sources]: no nj211 params"
    summary = await refresh_nj211(db, cfg)
    text = json.dumps(summary, default=str)
    if summary["blocked"]:
        return f"WARNING[resource_source_blocked]: NJ 211 refused or disallowed us - stopped: {text}"
    if summary["errors"] or summary["detail_failures"]:
        return f"WARNING[resource_source_partial]: {len(summary['errors'])} error(s): {text}"
    if summary["list_crawl"] == "complete" and summary["listed"] == 0:
        return f"WARNING[resource_source_empty]: the list crawl found nothing - layout change? {text}"
    return text
