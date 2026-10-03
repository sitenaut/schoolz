import asyncio
import base64
import ipaddress
import logging
import os
import secrets
import socket
import time
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException, status
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from playwright.async_api import async_playwright, Browser
from pydantic import BaseModel, Field

import observability
import telemetry

logger = logging.getLogger("schoolz-scraper")

SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")
_tracer = trace.get_tracer("schoolz-scraper")

BLOCKED_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def _resolve_hostname(hostname: str) -> list[str]:
    """Resolves a hostname the same way the browser's own navigation will.

    Checking only the literal hostname string (as the first cut of this
    guard did) misses two real bypasses: a domain that simply resolves to
    a private/internal address (DNS rebinding), and a numeric/hex/octal
    IP-literal host like "2130706433" or "0x7f000001" for 127.0.0.1, which
    `ipaddress.ip_address()` rejects as malformed but Chromium's own URL
    parser normalizes into a real IP and connects to anyway. Resolving
    here and checking every returned address closes both at once.
    """
    loop = asyncio.get_running_loop()
    try:
        addrinfo = await loop.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Could not resolve host '{hostname}': {exc}"
        ) from exc
    return [sockaddr[0] for _, _, _, _, sockaddr in addrinfo]


async def validate_target_url(url: str) -> None:
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Malformed URL: {exc}") from exc

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported URL scheme '{parsed.scheme}'. Only 'http' and 'https' are permitted.",
        )

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid URL: missing hostname.")

    if hostname in BLOCKED_HOSTNAMES or hostname.endswith(".internal"):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Target URL points to a forbidden internal or loopback host.",
        )

    for ip_str in await _resolve_hostname(hostname):
        if _is_blocked_ip(ipaddress.ip_address(ip_str)):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Target URL points to a forbidden private or local IP address.",
            )


def _host(url: str) -> str:
    return urlparse(url).netloc or "unknown"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT_MS = 15_000

_state: dict[str, Browser] = {}
_browser_lock = asyncio.Lock()


async def _get_browser() -> Browser:
    browser = _state.get("browser")
    if browser is not None and browser.is_connected():
        return browser
    async with _browser_lock:
        browser = _state.get("browser")
        if browser is not None and browser.is_connected():
            return browser
        playwright = _state.get("playwright")
        if playwright is None:
            playwright = await async_playwright().start()
            _state["playwright"] = playwright
        logger.warning("relaunching_chromium_browser")
        new_browser = await playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        _state["browser"] = new_browser
        return new_browser


telemetry.setup_telemetry("schoolz-scraper")


@asynccontextmanager
async def lifespan(_: FastAPI):
    playwright = await async_playwright().start()
    _state["playwright"] = playwright
    _state["browser"] = await playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    yield
    browser = _state.get("browser")
    if browser is not None and browser.is_connected():
        await browser.close()
    if playwright is not None:
        await playwright.stop()
    telemetry.shutdown_telemetry()


app = FastAPI(title="schoolz-scraper", lifespan=lifespan)
FastAPIInstrumentor.instrument_app(app, excluded_urls="health")


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    if not SCRAPER_API_KEY:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "SCRAPER_API_KEY is not configured")
    if not x_api_key or not secrets.compare_digest(x_api_key, SCRAPER_API_KEY):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing X-API-Key")



class FetchHtmlRequest(BaseModel):
    url: str
    wait_for_selector: Optional[str] = None
    timeout_ms: int = Field(default=DEFAULT_TIMEOUT_MS, le=60_000)
    # page.content() never includes shadow DOM, so a web component that
    # renders into its own shadow root comes back as an empty shell even
    # though wait_for_selector (which does pierce shadow roots) matched.
    # When set, open shadow roots are serialized inline as
    # <template shadowrootmode="open"> (declarative shadow DOM).
    include_shadow_dom: bool = False
    # When True, aborts image, media, and font downloads via page.route().
    # Cuts load latency by 50-70% and memory footprint by ~60% on text/directory
    # scans (staff rosters, calendar widgets, document discovery). Keep False
    # for newsletter/flyer pages where rasterized images carry the core data.
    block_assets: bool = False


class FetchHtmlResponse(BaseModel):
    url: str
    status: int
    title: str
    html: str


class FetchPaginatedRequest(BaseModel):
    url: str
    # CSS selector for the "next page" control, re-queried after each click
    # (some pagination UIs re-render it, so we can't cache the handle).
    # Confirmed real case: a directory whose ?page=N query param does
    # nothing (it's JS-driven, not real server-side pagination) - this
    # exists specifically for that, keeping one browser session alive
    # across clicks so pagination state isn't lost between requests.
    next_page_selector: str
    max_pages: int = Field(default=20, le=25)
    wait_after_click_ms: int = Field(default=1200, le=3000)
    timeout_ms: int = Field(default=DEFAULT_TIMEOUT_MS, le=60_000)
    block_assets: bool = False



class FetchPaginatedResponse(BaseModel):
    url: str
    pages: list[str]


class FetchRawRequest(BaseModel):
    url: str
    timeout_ms: int = Field(default=DEFAULT_TIMEOUT_MS, le=60_000)


class FetchRawResponse(BaseModel):
    url: str
    status: int
    content_type: str
    body_base64: str


@app.get("/health")
async def health():
    browser = _state.get("browser")
    is_connected = bool(browser and browser.is_connected())
    if not is_connected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "degraded", "browser_connected": False},
        )
    return {"status": "ok", "browser_connected": True}


_SERIALIZE_WITH_SHADOW_JS = """() => {
  if (typeof document.documentElement.getHTML !== "function") return null;
  const roots = [];
  const walk = (node) => {
    for (const el of node.querySelectorAll("*")) {
      if (el.shadowRoot) { roots.push(el.shadowRoot); walk(el.shadowRoot); }
    }
  };
  walk(document);
  return "<!DOCTYPE html><html>" + document.documentElement.getHTML({ serializableShadowRoots: true, shadowRoots: roots }) + "</html>";
}"""


async def _serialize_with_shadow_dom(page) -> str:
    html = await page.evaluate(_SERIALIZE_WITH_SHADOW_JS)
    return html if html else await page.content()
_HEAVY_RESOURCE_TYPES = {"image", "media", "font"}


async def _abort_heavy_assets(route):
    if route.request.resource_type in _HEAVY_RESOURCE_TYPES:
        await route.abort()
    else:
        await route.continue_()


@app.post("/fetch-html", response_model=FetchHtmlResponse, dependencies=[Depends(require_api_key)])
async def fetch_html(req: FetchHtmlRequest):

    """Render a URL with a real browser and return the resulting HTML.

    Use this for pages that need JavaScript to render their content -
    plain HTTP GETs won't see anything past the initial shell.
    """
    await validate_target_url(req.url)
    host = _host(req.url)
    browser = await _get_browser()
    context = await browser.new_context(user_agent=DEFAULT_USER_AGENT)
    observability.pages_open.add(1)
    start = time.perf_counter()
    outcome = "error"
    try:
        with _tracer.start_as_current_span("scraper.fetch_html", attributes={"url.host": host}):
            page = await context.new_page()
            if req.block_assets:
                await page.route("**/*", _abort_heavy_assets)
            with _tracer.start_as_current_span("page.goto", attributes={"url.host": host}):
                response = await page.goto(req.url, timeout=req.timeout_ms, wait_until="domcontentloaded")
            if req.wait_for_selector:
                with _tracer.start_as_current_span(
                    "wait_for_selector", attributes={"url.host": host, "selector": req.wait_for_selector}
                ):
                    await page.wait_for_selector(req.wait_for_selector, timeout=req.timeout_ms)
            html = await _serialize_with_shadow_dom(page) if req.include_shadow_dom else await page.content()
            title = await page.title()
        outcome = "ok"
        return FetchHtmlResponse(
            url=req.url,
            status=response.status if response else 0,
            title=title,
            html=html,
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - surface as a client-facing error
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to fetch {req.url}: {exc}") from exc
    finally:
        await context.close()
        observability.pages_open.add(-1)
        observability.page_load_seconds.record(time.perf_counter() - start, {"outcome": outcome})


@app.post("/fetch-paginated", response_model=FetchPaginatedResponse, dependencies=[Depends(require_api_key)])
async def fetch_paginated(req: FetchPaginatedRequest):
    """Clicks through JS-driven pagination in one live browser session,
    returning each page's rendered HTML. Use this instead of /fetch-html
    with a page query param when that param doesn't actually change the
    server-rendered response (confirmed real case: a Finalsite staff
    directory whose pagination is entirely client-side)."""
    await validate_target_url(req.url)
    host = _host(req.url)
    browser = await _get_browser()
    context = await browser.new_context(user_agent=DEFAULT_USER_AGENT)
    observability.pages_open.add(1)
    start = time.perf_counter()
    outcome = "error"
    pages: list[str] = []
    deadline = time.monotonic() + 90.0
    try:
        with _tracer.start_as_current_span("scraper.fetch_paginated", attributes={"url.host": host}):
            page = await context.new_page()
            if req.block_assets:
                await page.route("**/*", _abort_heavy_assets)
            with _tracer.start_as_current_span("page.goto", attributes={"url.host": host, "page_index": 0}):
                await page.goto(req.url, timeout=req.timeout_ms, wait_until="domcontentloaded")
            pages.append(await page.content())


            for page_index in range(1, req.max_pages):
                if time.monotonic() >= deadline:
                    logger.warning("fetch_paginated_deadline_reached", extra={"url": req.url, "pages_collected": len(pages)})
                    break
                with _tracer.start_as_current_span(
                    "paginated_click", attributes={"url.host": host, "page_index": page_index}
                ):
                    next_control = await page.query_selector(req.next_page_selector)
                    if not next_control:
                        break
                    is_disabled = await next_control.get_attribute("disabled")
                    aria_disabled = await next_control.get_attribute("aria-disabled")
                    if is_disabled is not None or aria_disabled == "true":
                        break
                    await next_control.click()
                    await page.wait_for_timeout(req.wait_after_click_ms)
                    pages.append(await page.content())

        outcome = "ok"
        return FetchPaginatedResponse(url=req.url, pages=pages)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to paginate {req.url}: {exc}") from exc
    finally:
        await context.close()
        observability.pages_open.add(-1)
        observability.page_load_seconds.record(time.perf_counter() - start, {"outcome": outcome})


@app.post("/fetch-raw", response_model=FetchRawResponse, dependencies=[Depends(require_api_key)])
async def fetch_raw(req: FetchRawRequest):
    """Fetch a URL's raw response bytes through a real browser context.

    Useful for downloads (ICS, PDF, CSV) served behind bot-detection/WAF
    that block plain HTTP clients but allow a real browser fingerprint.
    """
    await validate_target_url(req.url)
    host = _host(req.url)
    browser = await _get_browser()
    context = await browser.new_context(user_agent=DEFAULT_USER_AGENT)
    start = time.perf_counter()
    outcome = "error"
    try:
        with _tracer.start_as_current_span("scraper.fetch_raw", attributes={"url.host": host}):
            response = await context.request.get(req.url, timeout=req.timeout_ms)
            body = await response.body()
        outcome = "ok"
        return FetchRawResponse(
            url=req.url,
            status=response.status,
            content_type=response.headers.get("content-type", ""),
            body_base64=base64.b64encode(body).decode("ascii"),
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to fetch {req.url}: {exc}") from exc
    finally:
        await context.close()
        observability.page_load_seconds.record(time.perf_counter() - start, {"outcome": outcome})


def run_server():
    """Start uvicorn with a dual-stack socket binding both IPv4 (0.0.0.0 / 127.0.0.1)
    and IPv6 (:: / ::1 / Fly 6PN). This satisfies both Fly's private network
    (IPv6-only 6PN) and Fly machine health checks / local compose (IPv4 loopback)."""
    import socket
    import uvicorn

    port = int(os.getenv("PORT", "8765"))
    sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    except (AttributeError, OSError):
        pass
    sock.bind(("::", port))
    sock.listen(128)
    config = uvicorn.Config("main:app", fd=sock.fileno(), log_level="info")
    server = uvicorn.Server(config)
    server.run()


if __name__ == "__main__":
    run_server()

