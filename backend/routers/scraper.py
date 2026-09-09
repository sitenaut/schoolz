from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

import scraper_client
from auth import get_current_user
from models import User

router = APIRouter(prefix="/scraper", tags=["scraper"])


class FetchHtmlRequest(BaseModel):
    url: str
    wait_for_selector: str | None = None


@router.post("/fetch-html")
async def fetch_html(payload: FetchHtmlRequest, _: User = Depends(get_current_user)):
    """Proxies to the scraper service. Requires auth - exists to verify the
    backend/scraper wiring end-to-end; site-specific extraction routes
    should call scraper_client.fetch_html() directly instead of this."""
    try:
        return await scraper_client.fetch_html(payload.url, wait_for_selector=payload.wait_for_selector)
    except scraper_client.ScraperNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
