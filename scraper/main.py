import base64
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from playwright.async_api import async_playwright, Browser
from pydantic import BaseModel, Field

SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT_MS = 15_000

_state: dict[str, Browser] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    playwright = await async_playwright().start()
    _state["playwright"] = playwright
    _state["browser"] = await playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    yield
    await _state["browser"].close()
    await playwright.stop()


app = FastAPI(title="schoolz-scraper", lifespan=lifespan)


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    if not SCRAPER_API_KEY:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "SCRAPER_API_KEY is not configured")
    if x_api_key != SCRAPER_API_KEY:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing X-API-Key")


class FetchHtmlRequest(BaseModel):
    url: str
    wait_for_selector: Optional[str] = None
    timeout_ms: int = Field(default=DEFAULT_TIMEOUT_MS, le=60_000)


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
    max_pages: int = Field(default=20, le=50)
    wait_after_click_ms: int = Field(default=1200, le=10_000)
    timeout_ms: int = Field(default=DEFAULT_TIMEOUT_MS, le=60_000)


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
    return {"status": "ok", "browser_connected": _state.get("browser").is_connected() if _state.get("browser") else False}


@app.post("/fetch-html", response_model=FetchHtmlResponse, dependencies=[Depends(require_api_key)])
async def fetch_html(req: FetchHtmlRequest):
    """Render a URL with a real browser and return the resulting HTML.

    Use this for pages that need JavaScript to render their content -
    plain HTTP GETs won't see anything past the initial shell.
    """
    browser = _state["browser"]
    context = await browser.new_context(user_agent=DEFAULT_USER_AGENT)
    try:
        page = await context.new_page()
        response = await page.goto(req.url, timeout=req.timeout_ms, wait_until="domcontentloaded")
        if req.wait_for_selector:
            await page.wait_for_selector(req.wait_for_selector, timeout=req.timeout_ms)
        html = await page.content()
        title = await page.title()
        return FetchHtmlResponse(
            url=req.url,
            status=response.status if response else 0,
            title=title,
            html=html,
        )
    except Exception as exc:  # noqa: BLE001 - surface as a client-facing error
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to fetch {req.url}: {exc}") from exc
    finally:
        await context.close()


@app.post("/fetch-paginated", response_model=FetchPaginatedResponse, dependencies=[Depends(require_api_key)])
async def fetch_paginated(req: FetchPaginatedRequest):
    """Clicks through JS-driven pagination in one live browser session,
    returning each page's rendered HTML. Use this instead of /fetch-html
    with a page query param when that param doesn't actually change the
    server-rendered response (confirmed real case: a Finalsite staff
    directory whose pagination is entirely client-side)."""
    browser = _state["browser"]
    context = await browser.new_context(user_agent=DEFAULT_USER_AGENT)
    pages: list[str] = []
    try:
        page = await context.new_page()
        await page.goto(req.url, timeout=req.timeout_ms, wait_until="domcontentloaded")
        pages.append(await page.content())

        for _ in range(req.max_pages - 1):
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

        return FetchPaginatedResponse(url=req.url, pages=pages)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to paginate {req.url}: {exc}") from exc
    finally:
        await context.close()


@app.post("/fetch-raw", response_model=FetchRawResponse, dependencies=[Depends(require_api_key)])
async def fetch_raw(req: FetchRawRequest):
    """Fetch a URL's raw response bytes through a real browser context.

    Useful for downloads (ICS, PDF, CSV) served behind bot-detection/WAF
    that block plain HTTP clients but allow a real browser fingerprint.
    """
    browser = _state["browser"]
    context = await browser.new_context(user_agent=DEFAULT_USER_AGENT)
    try:
        response = await context.request.get(req.url, timeout=req.timeout_ms)
        body = await response.body()
        return FetchRawResponse(
            url=req.url,
            status=response.status,
            content_type=response.headers.get("content-type", ""),
            body_base64=base64.b64encode(body).decode("ascii"),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to fetch {req.url}: {exc}") from exc
    finally:
        await context.close()
