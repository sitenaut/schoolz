import os
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import School
import services.prerender as prerender

router = APIRouter(tags=["seo"])

# Static public routes worth listing - anything gated by RequireAuth/
# RequireAdmin (account, admin, jobs, gmail, children, login/register)
# isn't indexable content and is kept out of the sitemap and out of
# robots.txt (frontend/public/robots.txt).
_STATIC_PATHS = ["/", "/schools", "/directory", "/calendar", "/lunch", "/privacy", "/contact", "/contact/submit", "/chcomms", "/survey"]


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap(db: AsyncSession = Depends(get_db)) -> Response:
    base_url = os.getenv("PUBLIC_WEB_URL", "http://localhost:5173").rstrip("/")
    urls = list(_STATIC_PATHS)
    result = await db.execute(select(School.slug).order_by(School.name))
    urls += [f"/schools/{slug}" for slug in result.scalars().all() if slug]

    entries = "".join(f"<url><loc>{escape(base_url + path)}</loc></url>" for path in urls)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{entries}</urlset>'
    return Response(content=xml, media_type="application/xml")


@router.get("/prerender", include_in_schema=False)
async def prerender_page(path: str) -> Response:
    """Called only by frontend/nginx.conf.template, for requests whose
    User-Agent matches a known crawler - see that file and
    services/prerender.py for why this exists."""
    try:
        html = await prerender.get_prerendered_html(path)
    except prerender.PathNotAllowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return Response(content=html, media_type="text/html")
