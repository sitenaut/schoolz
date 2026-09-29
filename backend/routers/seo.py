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

# Only pages with a real translation get a /es or /zh entry (and hreflang
# pairing) - listing an English page under /es would invite duplicate-content
# treatment. Mirror frontend/src/lib/i18n.ts:isTranslatedPath.
_TRANSLATED_STATIC = {"/", "/schools", "/directory", "/lunch", "/calendar"}
_TRANSLATED_PREFIX = "/schools/"
_ALT_LANGS = ("es", "zh")


def _lang_path(path: str, lang: str) -> str:
    return f"/{lang}" if path == "/" else f"/{lang}{path}"


def _entry(base_url: str, path: str) -> str:
    translated = path in _TRANSLATED_STATIC or path.startswith(_TRANSLATED_PREFIX)
    if not translated:
        return f"<url><loc>{escape(base_url + path)}</loc></url>"
    alts = {"en": path, **{lang: _lang_path(path, lang) for lang in _ALT_LANGS}}
    links = "".join(
        f'<xhtml:link rel="alternate" hreflang="{lang}" href="{escape(base_url + p)}"/>' for lang, p in alts.items()
    ) + f'<xhtml:link rel="alternate" hreflang="x-default" href="{escape(base_url + path)}"/>'
    return "".join(f"<url><loc>{escape(base_url + p)}</loc>{links}</url>" for p in alts.values())


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap(db: AsyncSession = Depends(get_db)) -> Response:
    base_url = os.getenv("PUBLIC_WEB_URL", "http://localhost:5173").rstrip("/")
    urls = list(_STATIC_PATHS)
    result = await db.execute(select(School.slug).order_by(School.name))
    urls += [f"/schools/{slug}" for slug in result.scalars().all() if slug]

    entries = "".join(_entry(base_url, path) for path in urls)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">'
        f"{entries}</urlset>"
    )
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
