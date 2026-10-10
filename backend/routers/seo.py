import os
from datetime import datetime
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import School, SchoolContentItem
import services.prerender as prerender

router = APIRouter(tags=["seo"])

# Static public routes worth listing - anything gated by RequireAuth/
# RequireAdmin (account, admin, jobs, gmail, children, login/register)
# isn't indexable content and is kept out of the sitemap and out of
# robots.txt (frontend/public/robots.txt).
_STATIC_PATHS = ["/", "/schools", "/directory", "/calendar", "/lunch", "/local", "/privacy", "/contact", "/upload", "/chcomms", "/survey"]

# Only pages with a real translation get a /<lang> entry (and hreflang
# pairing) - listing an English page under /es would invite duplicate-content
# treatment. Mirror frontend/src/lib/i18n.ts:isTranslatedPath.
_TRANSLATED_STATIC = {"/", "/schools", "/directory", "/lunch", "/calendar"}
_TRANSLATED_PREFIX = "/schools/"
_ALT_LANGS = ("es", "zh", "ko", "hi")


def _lang_path(path: str, lang: str) -> str:
    return f"/{lang}" if path == "/" else f"/{lang}{path}"


def _is_translated(path: str) -> bool:
    return path in _TRANSLATED_STATIC or path.startswith(_TRANSLATED_PREFIX)


def _variants(path: str) -> list[str]:
    """`path` plus its /<lang> versions, when it has real translations."""
    if not _is_translated(path):
        return [path]
    return [path] + [_lang_path(path, lang) for lang in _ALT_LANGS]


def _entry(base_url: str, path: str, lastmod: datetime | None) -> str:
    # lastmod is what tells Google which of ~900 URLs actually changed, so
    # its recrawls go there - it ignores the field on a site that stamps
    # every URL with today, so only pages with a real content date get one.
    mod = f"<lastmod>{lastmod.date().isoformat()}</lastmod>" if lastmod else ""
    if not _is_translated(path):
        return f"<url><loc>{escape(base_url + path)}</loc>{mod}</url>"
    alts = {"en": path, **{lang: _lang_path(path, lang) for lang in _ALT_LANGS}}
    links = "".join(
        f'<xhtml:link rel="alternate" hreflang="{lang}" href="{escape(base_url + p)}"/>' for lang, p in alts.items()
    ) + f'<xhtml:link rel="alternate" hreflang="x-default" href="{escape(base_url + path)}"/>'
    return "".join(f"<url><loc>{escape(base_url + p)}</loc>{mod}{links}</url>" for p in alts.values())


async def _school_lastmods(db: AsyncSession) -> dict[str, datetime]:
    """slug -> when that school's page last changed: the newest content item
    on it (its own, or its district's), or the school record itself."""
    by_school = dict((await db.execute(select(SchoolContentItem.school_id, func.max(SchoolContentItem.extracted_at)).where(SchoolContentItem.school_id.is_not(None)).group_by(SchoolContentItem.school_id))).all())
    by_district = dict((await db.execute(select(SchoolContentItem.district_id, func.max(SchoolContentItem.extracted_at)).where(SchoolContentItem.district_id.is_not(None)).group_by(SchoolContentItem.district_id))).all())
    rows = (await db.execute(select(School.id, School.slug, School.district_id, School.updated_at).where(School.slug.is_not(None)).order_by(School.name))).all()
    lastmods: dict[str, datetime] = {}
    for school_id, slug, district_id, updated_at in rows:
        if not slug:
            continue
        candidates = [d for d in (updated_at, by_school.get(school_id), by_district.get(district_id)) if d is not None]
        lastmods[slug] = max(candidates)
    return lastmods


async def sitemap_paths(db: AsyncSession) -> list[str]:
    """Every path the sitemap lists, language versions included - what the
    nightly prerender warm job renders."""
    slugs = [s for s in (await db.execute(select(School.slug).order_by(School.name))).scalars().all() if s]
    return [v for path in _STATIC_PATHS + [f"/schools/{slug}" for slug in slugs] for v in _variants(path)]


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap(db: AsyncSession = Depends(get_db)) -> Response:
    base_url = os.getenv("PUBLIC_WEB_URL", "http://localhost:5173").rstrip("/")
    lastmods = await _school_lastmods(db)
    entries = "".join(_entry(base_url, path, None) for path in _STATIC_PATHS)
    entries += "".join(_entry(base_url, f"/schools/{slug}", mod) for slug, mod in lastmods.items())
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
