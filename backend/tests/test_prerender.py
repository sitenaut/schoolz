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
    # Six-hour-old real content beats an error page for a crawler, so an
    # expired entry is kept rather than evicted.
    prerender._CACHE["/lunch"] = (time.time() - 1, "<html>stale</html>")

    async def failing_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False):
        raise RuntimeError("scraper unavailable")

    monkeypatch.setattr(scraper_client, "failing", None, raising=False)
    monkeypatch.setattr(scraper_client, "fetch_html", failing_fetch_html)

    assert await prerender.get_prerendered_html("/lunch") == "<html>stale</html>"


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


@pytest.mark.anyio
async def test_an_expired_stored_page_is_rendered_again(monkeypatch):
    import database
    from models import PrerenderedPage

    async with database.SessionLocal() as db:
        db.add(PrerenderedPage(path="/lunch", html_gz=gzip.compress(b"<html>old</html>"), rendered_at=datetime.now(timezone.utc) - timedelta(hours=7)))
        await db.commit()
    calls = await _fake_render(monkeypatch, "<html>new</html>")

    assert await prerender.get_prerendered_html("/lunch") == "<html>new</html>"
    assert len(calls) == 1


@pytest.mark.anyio
async def test_a_stale_stored_page_is_served_when_the_render_fails(monkeypatch):
    import database
    from models import PrerenderedPage

    async with database.SessionLocal() as db:
        db.add(PrerenderedPage(path="/survey", html_gz=gzip.compress(b"<html>old</html>"), rendered_at=datetime.now(timezone.utc) - timedelta(hours=7)))
        await db.commit()

    async def failing_fetch_html(url: str, wait_for_selector=None, timeout_ms=15_000, block_assets=False):
        raise RuntimeError("scraper unavailable")

    monkeypatch.setattr(scraper_client, "fetch_html", failing_fetch_html)

    assert await prerender.get_prerendered_html("/survey") == "<html>old</html>"


@pytest.mark.anyio
async def test_an_overlong_path_is_rejected():
    with pytest.raises(prerender.PathNotAllowed):
        await prerender.get_prerendered_html("/schools/" + "x" * 300)
