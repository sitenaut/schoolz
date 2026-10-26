import os
from datetime import datetime
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import database
import services.prerender as prerender
from database import get_db
from models import DistrictBudget, School, SchoolContentItem, StateDistrict
from services.response_cache import SingleFlightTTLCache

router = APIRouter(tags=["seo"])

# Every crawler fetch rebuilt it (1.1 MB of XML, two scans of the content
# table) - up to 2.8s on prod. lastmod is a date, so an hour-old copy says
# exactly the same thing. 0 disables it; the test suite does.
_SITEMAP = SingleFlightTTLCache(ttl_s=float(os.getenv("SITEMAP_CACHE_TTL_S", "3600")))

# Static public routes worth listing - anything gated by RequireAuth/
# RequireAdmin (account, admin, jobs, gmail, children, login/register)
# isn't indexable content and is kept out of the sitemap and out of
# robots.txt (frontend/public/robots.txt).
_STATIC_PATHS = ["/", "/schools", "/budgets", "/directory", "/calendar", "/lunch", "/local", "/privacy", "/contact", "/upload", "/chcomms", "/survey"]

# Only pages with a real translation get a /<lang> entry (and hreflang
# pairing) - listing an English page under /es would invite duplicate-content
# treatment. Mirror frontend/src/lib/i18n.ts:isTranslatedPath.
_TRANSLATED_STATIC = {"/", "/schools", "/budgets", "/directory", "/lunch", "/calendar"}
# A district's budget page is translated too, but listed in English only:
# ~585 pages times five languages would be most of the sitemap, and every
# one a render for the nightly warm job, for searches that come in English.
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


async def school_lastmods(db: AsyncSession) -> dict[str, datetime]:
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


async def budget_lastmods(db: AsyncSession) -> dict[str, datetime]:
    """slug -> when that district's budget page last changed: its newest import."""
    rows = (
        await db.execute(
            select(StateDistrict.slug, func.max(DistrictBudget.imported_at))
            .join(DistrictBudget, DistrictBudget.state_district_id == StateDistrict.id)
            .group_by(StateDistrict.slug)
            .order_by(StateDistrict.slug)
        )
    ).all()
    return dict(rows)


def _school_paths(slug: str) -> tuple[str, str]:
    """A school's page and its own calendar page (/calendar?school= used to be
    the only way in, and every one of those canonicalized to /calendar)."""
    return f"/schools/{slug}", f"/schools/{slug}/calendar"


async def sitemap_paths(db: AsyncSession) -> list[str]:
    """Every path the sitemap lists, language versions included - what the
    nightly prerender warm job renders, in this order (school pages before
    their calendars, so a run that stops at 6 AM has done the pages first)."""
    slugs = [s for s in (await db.execute(select(School.slug).order_by(School.name))).scalars().all() if s]
    pages = [f"/schools/{slug}" for slug in slugs]
    calendars = [_school_paths(slug)[1] for slug in slugs]
    budgets = [f"/budgets/{slug}" for slug in await budget_lastmods(db)]
    return [v for path in _STATIC_PATHS + pages + calendars for v in _variants(path)] + budgets


async def _sitemap_xml(db: AsyncSession) -> bytes:
    base_url = os.getenv("PUBLIC_WEB_URL", "http://localhost:5173").rstrip("/")
    lastmods = await school_lastmods(db)
    entries = "".join(_entry(base_url, path, None) for path in _STATIC_PATHS)
    entries += "".join(_entry(base_url, path, mod) for slug, mod in lastmods.items() for path in _school_paths(slug))
    entries += "".join(_entry(base_url, f"/budgets/{slug}", mod) for slug, mod in (await budget_lastmods(db)).items())
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">'
        f"{entries}</urlset>"
    )
    return xml.encode()


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap(db: AsyncSession = Depends(get_db)) -> Response:
    if not _SITEMAP.enabled:
        return Response(content=await _sitemap_xml(db), media_type="application/xml")

    async def compute() -> bytes:
        # Its own session: other crawlers wait on this same computation.
        async with database.SessionLocal() as own_db:
            return await _sitemap_xml(own_db)

    return Response(content=await _SITEMAP.get_or_compute("sitemap", compute), media_type="application/xml")


@router.get("/prerender", include_in_schema=False)
async def prerender_page(path: str) -> Response:
    """Called only by frontend/nginx.conf.template, for requests whose
    User-Agent matches a known crawler - see that file and
    services/prerender.py for why this exists."""
    try:
        html = await prerender.get_prerendered_html(path)
    except prerender.PathNotAllowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found") from None
    return Response(content=html, media_type="text/html")
