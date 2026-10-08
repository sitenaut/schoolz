"""Scheduled job: render every sitemap page for crawlers ahead of time, so
Googlebot is always served a stored snapshot (~0.1s) instead of waiting on
a live render (2-10s; services/prerender.py). Slow and erroring responses
are what Google throttles a site's crawl for - Search Console showed 48
"server errors" and ~500 pages "discovered, not crawled" while crawlers
were still paying for renders.

Nightly, serial: one render at a time leaves the other scraper slots to the
scans running in the same process. Pages rendered recently (by a crawler's
own visit) are skipped, so a run only does what would otherwise expire."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

import services.prerender as prerender
from routers.seo import sitemap_paths
from scheduler import progress
from scheduler.registry import register_job

# Renders younger than this are left alone. Under the 24h freshness window
# so a page rendered at last night's run is redone tonight, before it expires.
SKIP_IF_RENDERED_WITHIN_S = 18 * 3600
CHECKPOINT_EVERY = 25


@register_job(
    kind="prerender.warm",
    default_name="Prerender warm (crawler snapshots)",
    default_cron="40 22 * * *",
    description="Render every sitemap page into the crawler snapshot cache so search engines never wait on a live render. Skips pages rendered in the last 18h.",
)
async def run(db: AsyncSession, params: dict) -> str | None:
    paths = await prerender.paths_needing_render(await sitemap_paths(db), SKIP_IF_RENDERED_WITHIN_S)
    rendered = failed = 0
    failed_paths: list[str] = []
    for idx, path in enumerate(paths, start=1):
        try:
            await prerender.refresh(path)
            rendered += 1
        except Exception:
            failed += 1
            if len(failed_paths) < 20:
                failed_paths.append(path)
        if idx % CHECKPOINT_EVERY == 0:
            await progress.checkpoint({"done": idx, "of": len(paths), "rendered": rendered, "failed": failed})

    summary = f"rendered {rendered} of {len(paths)} stale pages, {failed} failed"
    if failed:
        summary += f" (e.g. {', '.join(failed_paths[:5])})"
    if paths and not rendered:
        return f"WARNING[prerender_warm_all_failed]: {summary}"
    return summary
