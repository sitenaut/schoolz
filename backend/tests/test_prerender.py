import asyncio
import gzip
import time
from datetime import datetime, timedelta, timezone

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

    async def fake_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False):
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

    async def fake_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False):
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

    async def failing_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False):
        raise RuntimeError("scraper unavailable")

    monkeypatch.setattr(scraper_client, "failing", None, raising=False)
    monkeypatch.setattr(scraper_client, "fetch_html", failing_fetch_html)

    assert await prerender.get_prerendered_html("/lunch") == "<html>stale</html>"
    await _drain_renders()


@pytest.mark.anyio
async def test_a_render_failure_with_no_cache_still_raises(monkeypatch):
    async def failing_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False):
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

    async def fake_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False):
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

    async def fake_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False):
        seen["url"] = url
        return {"html": "<html>ok</html>"}

    monkeypatch.setattr(scraper_client, "fetch_html", fake_fetch_html)

    await prerender.get_prerendered_html("/directory")

    assert seen["url"].endswith("/directory?internal=1&prerender=1")


async def _fake_render(monkeypatch, html="<html>rendered</html>"):
    calls = []

    async def fake_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False):
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


async def _store_old(path: str, hours: float = 25) -> None:
    import database
    from models import PrerenderedPage

    async with database.SessionLocal() as db:
        db.add(PrerenderedPage(path=path, html_gz=gzip.compress(b"<html>old</html>"), rendered_at=datetime.now(timezone.utc) - timedelta(hours=hours)))
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

    async def failing_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False):
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
async def test_paths_needing_render_skips_recent_snapshots():
    await _store_old("/lunch", hours=1)
    await _store_old("/calendar", hours=20)

    assert await prerender.paths_needing_render(["/", "/lunch", "/calendar"], 18 * 3600) == ["/", "/calendar"]


@pytest.mark.anyio
async def test_warm_job_renders_only_what_would_expire(monkeypatch):
    from scheduler.jobs import prerender_warm

    async def fake_paths(_db):
        return ["/", "/lunch", "/calendar"]

    monkeypatch.setattr(prerender_warm, "sitemap_paths", fake_paths)
    await _store_old("/lunch", hours=1)
    calls = await _fake_render(monkeypatch)

    import database

    async with database.SessionLocal() as db:
        summary = await prerender_warm.run(db, {})

    assert summary == "rendered 2 of 2 stale pages, 0 failed"
    assert sorted(c.split("?")[0].rsplit("/", 1)[-1] for c in calls) == ["", "calendar"]


@pytest.mark.anyio
async def test_warm_job_warns_when_every_render_fails(monkeypatch):
    from scheduler.jobs import prerender_warm

    async def fake_paths(_db):
        return ["/privacy"]

    async def failing_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False):
        raise RuntimeError("scraper unavailable")

    monkeypatch.setattr(prerender_warm, "sitemap_paths", fake_paths)
    monkeypatch.setattr(scraper_client, "fetch_html", failing_fetch_html)

    import database

    async with database.SessionLocal() as db:
        summary = await prerender_warm.run(db, {})

    assert summary.startswith("WARNING[prerender_warm_all_failed]")
