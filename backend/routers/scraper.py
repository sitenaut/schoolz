from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

import scraper_client
from auth import require_permission
from models import User

router = APIRouter(prefix="/scraper", tags=["scraper"])


class FetchHtmlRequest(BaseModel):
    url: str
    wait_for_selector: str | None = None
    block_assets: bool = False


@router.post("/fetch-html")
async def fetch_html(payload: FetchHtmlRequest, _: User = Depends(require_permission("scans.manage"))):
    """Proxies to the scraper service. Requires scans.manage permission -
    exists to verify the backend/scraper wiring end-to-end; site-specific
    extraction routes should call scraper_client.fetch_html() directly instead of this."""
    try:
        return await scraper_client.fetch_html(
            payload.url,
            wait_for_selector=payload.wait_for_selector,
            block_assets=payload.block_assets,
        )
    except scraper_client.ScraperNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


