"""Scheduled job: render sitemap pages for crawlers ahead of time, so
Googlebot is always served a stored snapshot (~0.1s) instead of waiting on
a live render (2-10s; services/prerender.py). Slow and erroring responses
are what Google throttles a site's crawl for - Search Console showed 48
"server errors" and ~500 pages "discovered, not crawled" while crawlers
were still paying for renders.

Nightly, serial: one render at a time leaves the other scraper slots to the
scans running in the same process.

**Only what changed.** It used to re-render all ~1,000 pages (264 schools in
five languages) every night, at ~23s a render on a scraper it shares with
the night's scans: 8 hours, and a deploy-interrupted run's catch-up ran on
past 10 AM, through parents' morning. A school's page is re-rendered when
its content changed since its snapshot (14-78 of 264 schools a day), or the
snapshot is nearly as old as prerender's TTL, and so is its calendar page
(/schools/<slug>/calendar), which is also redone when a new month starts:
it shows the month it was rendered in. The pages that show dated content
(home, calendar, local, directory...) are re-rendered nightly.

**Never in the daytime.** It stops at 6 AM Eastern and a catch-up after a
daytime deploy does nothing: a page it didn't reach keeps serving its
snapshot, and tonight's run picks it up."""
from __future__ import annotations

import re
import zlib
from datetime import UTC, datetime
from datetime import time as dtime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

import services.prerender as prerender
from routers.seo import school_lastmods, sitemap_paths
from scheduler import progress
from scheduler.registry import register_job

# A page that isn't a school page is redone when its snapshot is older than
# this - under a day, so last night's render is redone tonight.
DATED_MAX_AGE_S = 18 * 3600
# A school page whose content hasn't changed is redone at this age, under
# prerender's 7-day TTL, so a crawler's visit never finds it expired - less
# up to SCHOOL_AGE_SPREAD_DAYS, fixed per path, so pages rendered on the
# same night (every one of them, the first time) don't all come due on the
# same night again.
SCHOOL_MAX_AGE_S = 6 * 24 * 3600
SCHOOL_AGE_SPREAD_DAYS = 3
# Often enough that a run of slow renders (each may now wait out the
# scraper's queue, with retries) never looks stuck to the 45-minute reaper.
CHECKPOINT_EVERY = 5

_LOCAL_TZ = ZoneInfo("America/New_York")
# Renders only between these Eastern times (the cron fires at 22:40).
NIGHT_START = dtime(22, 0)
NIGHT_END = dtime(6, 0)

_SCHOOL_PATH = re.compile(r"^(?:/(?:es|zh|ko|hi))?/schools/([^/]+)(/calendar)?$")


def _now() -> datetime:
    return datetime.now(UTC)


def is_night(now: datetime) -> bool:
    t = now.astimezone(_LOCAL_TZ).time()
    return t >= NIGHT_START or t < NIGHT_END


def _month(at: datetime) -> str:
    return at.astimezone(_LOCAL_TZ).strftime("%Y-%m")


def school_max_age_s(path: str) -> int:
    return SCHOOL_MAX_AGE_S - zlib.crc32(path.encode()) % SCHOOL_AGE_SPREAD_DAYS * 86400


def paths_to_render(paths: list[str], rendered: dict[str, datetime], lastmods: dict[str, datetime], now: datetime) -> list[str]:
    """The pages worth rendering tonight, most needed first: never rendered,
    then school pages whose content changed, then the dated pages, then
    school pages aging out. Order matters because a run can stop at 6 AM."""
    picked: list[tuple[int, int, str]] = []
    for order, path in enumerate(paths):
        at = rendered.get(path)
        school = _SCHOOL_PATH.match(path)
        if at is None:
            rank = 0
        elif school:
            changed = lastmods.get(school.group(1))
            if changed is not None and changed > at:
                rank = 1
            elif school.group(2) and _month(at) != _month(now):
                rank = 1
            elif (now - at).total_seconds() > school_max_age_s(path):
                rank = 3
            else:
                continue
        elif (now - at).total_seconds() > DATED_MAX_AGE_S:
            rank = 2
        else:
            continue
        picked.append((rank, order, path))
    return [path for _, _, path in sorted(picked)]


@register_job(
    kind="prerender.warm",
    default_name="Prerender warm (crawler snapshots)",
    default_cron="40 22 * * *",
    description="Render the sitemap pages whose content changed (and the dated pages) into the crawler snapshot cache, overnight only, so search engines never wait on a live render.",
)
async def run(db: AsyncSession, params: dict) -> str | None:
    if not is_night(_now()):
        return "daytime: nothing rendered (renders run 10 PM - 6 AM Eastern)"
    all_paths = await sitemap_paths(db)
    paths = paths_to_render(all_paths, await prerender.rendered_at(all_paths), await school_lastmods(db), _now())
    rendered = failed = 0
    failed_paths: list[str] = []
    stopped_at: int | None = None
    for idx, path in enumerate(paths, start=1):
        if not is_night(_now()):
            stopped_at = idx - 1
            break
        try:
            await prerender.refresh(path)
            rendered += 1
        except Exception:
            failed += 1
            if len(failed_paths) < 20:
                failed_paths.append(path)
        if idx % CHECKPOINT_EVERY == 0:
            await progress.checkpoint({"done": idx, "of": len(paths), "rendered": rendered, "failed": failed})

    summary = f"rendered {rendered} of {len(paths)} pages to render ({len(all_paths)} in the sitemap), {failed} failed"
    if stopped_at is not None:
        summary += f"; stopped at 6 AM with {len(paths) - stopped_at} left for tonight"
    if failed:
        summary += f" (e.g. {', '.join(failed_paths[:5])})"
    if paths and not rendered and stopped_at is None:
        return f"WARNING[prerender_warm_all_failed]: {summary}"
    return summary
