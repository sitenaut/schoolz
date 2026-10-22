import asyncio
import gzip
import time
from datetime import UTC, datetime, timedelta

import pytest

import scraper_client
import services.prerender as prerender


@pytest.fixture(autouse=True)
def _clean_prerender_state():
    prerender._CACHE.clear()
    prerender._INFLIGHT.clear()
    yield
    prerender._CACHE.clear()
    prerender._INFLIGHT.clear()


@pytest.mark.anyio
async def test_rejects_a_path_that_is_not_indexable():
    with pytest.raises(prerender.PathNotAllowed):
        await prerender.get_prerendered_html("/admin")


@pytest.mark.anyio
async def test_concurrent_requests_for_one_path_share_a_single_render(monkeypatch):
    # Crawlers hit the same URL from several connections at once, and
    # scraper_client only allows 3 in-flight requests process-wide - one
    # render per caller starved the real scan jobs sharing that budget.
    calls = 0

    async def fake_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False, stealth=True, **_kw):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"html": "<html>rendered</html>"}

    monkeypatch.setattr(scraper_client, "fetch_html", fake_fetch_html)

    results = await asyncio.gather(*(prerender.get_prerendered_html("/schools") for _ in range(5)))

    assert calls == 1
    assert results == ["<html>rendered</html>"] * 5


@pytest.mark.anyio
async def test_a_cached_page_is_not_rendered_again(monkeypatch):
    calls = 0

    async def fake_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False, stealth=True, **_kw):
        nonlocal calls
        calls += 1
        return {"html": "<html>fresh</html>"}

    monkeypatch.setattr(scraper_client, "fetch_html", fake_fetch_html)

    assert await prerender.get_prerendered_html("/calendar") == "<html>fresh</html>"
    assert await prerender.get_prerendered_html("/calendar") == "<html>fresh</html>"
    assert calls == 1


@pytest.mark.anyio
async def test_stale_content_is_served_when_a_re_render_fails(monkeypatch):
    # Day-old real content beats an error page for a crawler, so an
    # expired entry is kept rather than evicted.
    prerender._CACHE["/lunch"] = (time.time() - 1, "<html>stale</html>")

    async def failing_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False, stealth=True, **_kw):
        raise RuntimeError("scraper unavailable")

    monkeypatch.setattr(scraper_client, "failing", None, raising=False)
    monkeypatch.setattr(scraper_client, "fetch_html", failing_fetch_html)

    assert await prerender.get_prerendered_html("/lunch") == "<html>stale</html>"
    await _drain_renders()


@pytest.mark.anyio
async def test_a_render_failure_with_no_cache_still_raises(monkeypatch):
    async def failing_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False, stealth=True, **_kw):
        raise RuntimeError("scraper unavailable")

    monkeypatch.setattr(scraper_client, "fetch_html", failing_fetch_html)

    with pytest.raises(RuntimeError):
        await prerender.get_prerendered_html("/privacy")


@pytest.mark.anyio
async def test_render_uses_the_reduced_timeout(monkeypatch):
    # 20s here meant the scraper applied it to goto AND wait_for_selector,
    # with scraper_client budgeting 2x + 10s on top - a single crawl could
    # hold one of three slots for ~50s (48.6s max measured in prod).
    seen: dict = {}

    async def fake_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False, stealth=True, **_kw):
        seen["timeout_ms"] = timeout_ms
        return {"html": "<html>ok</html>"}

    monkeypatch.setattr(scraper_client, "fetch_html", fake_fetch_html)

    await prerender.get_prerendered_html("/contact")

    assert seen["timeout_ms"] == 10_000


@pytest.mark.anyio
async def test_render_is_flagged_as_internal_traffic_and_a_prerender(monkeypatch):
    # The fallback scrapers' stealth Chromium hides navigator.webdriver, so
    # without the flag every crawler-triggered render counted as a GA visitor.
    seen: dict = {}

    async def fake_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False, stealth=True, **_kw):
        seen["url"] = url
        return {"html": "<html>ok</html>"}

    monkeypatch.setattr(scraper_client, "fetch_html", fake_fetch_html)

    await prerender.get_prerendered_html("/directory")

    assert seen["url"].endswith("/directory?internal=1&prerender=1")


async def _fake_render(monkeypatch, html="<html>rendered</html>"):
    calls = []

    async def fake_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False, stealth=True, **_kw):
        calls.append(url)
        return {"html": html}

    monkeypatch.setattr(scraper_client, "fetch_html", fake_fetch_html)
    return calls


@pytest.mark.anyio
async def test_a_render_survives_a_process_restart(monkeypatch):
    # The in-process cache alone was wiped by every deploy and auto-stop and
    # kept separately per API machine: ~1,000 paths rendered ~3,000x a day.
    calls = await _fake_render(monkeypatch)

    assert await prerender.get_prerendered_html("/schools/bret-harte") == "<html>rendered</html>"
    prerender._CACHE.clear()  # a restart, or the other machine
    assert await prerender.get_prerendered_html("/schools/bret-harte") == "<html>rendered</html>"
    assert len(calls) == 1


async def _store_old(path: str, hours: float = 8 * 24, before: datetime | None = None) -> None:  # past the 7-day TTL
    import database
    from models import PrerenderedPage

    async with database.SessionLocal() as db:
        db.add(PrerenderedPage(path=path, html_gz=gzip.compress(b"<html>old</html>"), rendered_at=(before or datetime.now(UTC)) - timedelta(hours=hours)))
        await db.commit()


async def _drain_renders() -> None:
    while prerender._INFLIGHT:
        await asyncio.gather(*prerender._INFLIGHT.values(), return_exceptions=True)


@pytest.mark.anyio
async def test_an_expired_page_is_served_at_once_and_refreshed_behind_it(monkeypatch):
    # A crawler kept waiting on a 2-10s render is how pages became Search
    # Console server errors; an expired snapshot is served immediately.
    await _store_old("/lunch")
    calls = await _fake_render(monkeypatch, "<html>new</html>")

    assert await prerender.get_prerendered_html("/lunch") == "<html>old</html>"
    await _drain_renders()
    assert len(calls) == 1
    prerender._CACHE.clear()
    assert await prerender.get_prerendered_html("/lunch") == "<html>new</html>"
    assert len(calls) == 1


@pytest.mark.anyio
async def test_a_stale_stored_page_is_served_when_the_render_fails(monkeypatch):
    await _store_old("/survey")

    async def failing_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False, stealth=True, **_kw):
        raise RuntimeError("scraper unavailable")

    monkeypatch.setattr(scraper_client, "fetch_html", failing_fetch_html)

    assert await prerender.get_prerendered_html("/survey") == "<html>old</html>"
    await _drain_renders()
    # Still the old copy - a failed refresh never evicts it.
    assert await prerender.get_prerendered_html("/survey") == "<html>old</html>"


@pytest.mark.anyio
async def test_an_overlong_path_is_rejected():
    with pytest.raises(prerender.PathNotAllowed):
        await prerender.get_prerendered_html("/schools/" + "x" * 300)


def test_local_events_page_is_prerendered():
    # It's in the sitemap; without it here every crawl of /local was a 404.
    assert prerender._is_allowed("/local")


@pytest.mark.anyio
async def test_rendered_at_reads_each_stored_snapshots_time():
    await _store_old("/lunch", hours=1)
    got = await prerender.rendered_at(["/", "/lunch"])
    assert list(got) == ["/lunch"] and datetime.now(UTC) - got["/lunch"] < timedelta(hours=1, minutes=1)


@pytest.mark.anyio
async def test_only_the_nightly_render_waits_out_a_busy_scraper(monkeypatch):
    seen = []

    async def fake_fetch_html(url: str, **kw):
        seen.append(kw.get("queue_s"))
        return {"html": "<html>ok</html>"}

    monkeypatch.setattr(scraper_client, "fetch_html", fake_fetch_html)
    await prerender.get_prerendered_html("/contact")  # a crawler's render
    await prerender.refresh("/privacy")  # the nightly job's
    assert seen == [None, 90]


# ---- the nightly warm job ----

NIGHT = datetime(2031, 3, 4, 4, 0, tzinfo=UTC)  # 11 PM Eastern
DAY = datetime(2031, 3, 4, 14, 0, tzinfo=UTC)  # 9 AM Eastern


def test_night_is_10pm_to_6am_eastern():
    from scheduler.jobs.prerender_warm import is_night

    assert is_night(NIGHT) and not is_night(DAY)
    assert is_night(datetime(2031, 7, 1, 9, 59, tzinfo=UTC))  # 5:59 AM EDT
    assert not is_night(datetime(2031, 7, 1, 10, 0, tzinfo=UTC))  # 6:00 AM EDT


def test_a_school_page_is_rendered_only_when_it_changed_or_ages_out():
    from scheduler.jobs.prerender_warm import paths_to_render

    now = NIGHT
    hours = lambda h: now - timedelta(hours=h)  # noqa: E731
    paths = ["/", "/calendar", "/schools/a", "/es/schools/a", "/schools/b", "/schools/c", "/schools/d"]
    rendered = {
        "/": hours(1),  # dated, rendered recently: skip
        "/calendar": hours(20),  # dated, last night's: redo
        "/schools/a": hours(30),  # changed since: redo, every language
        "/es/schools/a": hours(30),
        "/schools/b": hours(30),  # unchanged: skip
        "/schools/c": hours(7 * 24 - 12),  # unchanged but ageing out: redo, last
    }
    lastmods = {"a": hours(2), "b": hours(40), "c": hours(400)}
    # Never rendered first, then changed schools, then dated, then ageing out.
    assert paths_to_render(paths, rendered, lastmods, now) == ["/schools/d", "/schools/a", "/es/schools/a", "/calendar", "/schools/c"]


def test_unchanged_school_pages_come_due_on_different_nights():
    from scheduler.jobs.prerender_warm import school_max_age_s

    ages = {school_max_age_s(f"/schools/school-{n}") // 86400 for n in range(200)}
    assert ages == {4, 5, 6}  # all under the 7-day TTL


async def _warm(monkeypatch, paths, *, now=NIGHT, lastmods=None):
    from scheduler.jobs import prerender_warm

    async def fake_paths(_db):
        return paths

    async def fake_lastmods(_db):
        return lastmods or {}

    clock = iter(now) if isinstance(now, list) else None
    monkeypatch.setattr(prerender_warm, "_now", (lambda: next(clock)) if clock else (lambda: now))
    monkeypatch.setattr(prerender_warm, "sitemap_paths", fake_paths)
    monkeypatch.setattr(prerender_warm, "school_lastmods", fake_lastmods)
    import database

    async with database.SessionLocal() as db:
        return await prerender_warm.run(db, {})


@pytest.mark.anyio
async def test_warm_job_renders_only_what_needs_it(monkeypatch):
    await _store_old("/lunch", hours=1, before=NIGHT)
    await _store_old("/schools/quiet", hours=30, before=NIGHT)
    calls = await _fake_render(monkeypatch)

    summary = await _warm(monkeypatch, ["/", "/lunch", "/calendar", "/schools/quiet"], lastmods={"quiet": NIGHT - timedelta(days=3)})

    assert summary == "rendered 2 of 2 pages to render (4 in the sitemap), 0 failed"
    assert sorted(c.split("?")[0].rsplit("/", 1)[-1] for c in calls) == ["", "calendar"]


@pytest.mark.anyio
async def test_warm_job_does_nothing_in_the_daytime_and_stops_at_6am(monkeypatch):
    calls = await _fake_render(monkeypatch)
    assert (await _warm(monkeypatch, ["/", "/calendar"], now=DAY)).startswith("daytime")
    assert calls == []

    # Night when it starts and picks its pages, 6 AM before the second render.
    summary = await _warm(monkeypatch, ["/", "/calendar", "/lunch"], now=[NIGHT, NIGHT, NIGHT, DAY])
    assert len(calls) == 1
    assert summary == "rendered 1 of 3 pages to render (3 in the sitemap), 0 failed; stopped at 6 AM with 2 left for tonight"


@pytest.mark.anyio
async def test_warm_job_warns_when_every_render_fails(monkeypatch):
    from scheduler.jobs import prerender_warm

    async def fake_paths(_db):
        return ["/privacy"]

    async def no_lastmods(_db):
        return {}

    monkeypatch.setattr(prerender_warm, "_now", lambda: NIGHT)
    monkeypatch.setattr(prerender_warm, "school_lastmods", no_lastmods)

    async def failing_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False, stealth=True, **_kw):
        raise RuntimeError("scraper unavailable")

    monkeypatch.setattr(prerender_warm, "sitemap_paths", fake_paths)
    monkeypatch.setattr(scraper_client, "fetch_html", failing_fetch_html)

    import database

    async with database.SessionLocal() as db:
        summary = await prerender_warm.run(db, {})

    assert summary.startswith("WARNING[prerender_warm_all_failed]")
