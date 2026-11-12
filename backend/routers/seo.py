import os
import re
from datetime import datetime
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select, union
from sqlalchemy.ext.asyncio import AsyncSession

import database
import services.prerender as prerender
from database import get_db
from models import DistrictBudget, School, SchoolContentItem, SeasonalAttraction, SeasonalGuide, StateDistrict
from resources.categories import CATEGORIES
from routers.seasonal_guides import today_et
from services.class_years import CLASS_PAGE_SOURCES, current_grad_years
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
#
# Localz lists its home, provider and category pages, not yet each listing
# (/localz/r/<id>): every path here is a render for the nightly warm job, and
# there are thousands of listings. Crawlers find the ones a category page
# shows before "Show more". A registered family child care listing is
# someone's home, so its page tells crawlers not to index it
# (ResourceDetailOut.indexable).
#
# /calendar and /lunch aren't listed: with no schools picked (a crawler
# never has any) each is a one-line "Pick your kids' schools" prompt, and
# Search Console filed all five languages of both under "Crawled - currently
# not indexed". Each school's own page and calendar page carry that content.
_STATIC_PATHS = [
    "/", "/schools", "/budgets", "/directory", "/local", "/localz", "/localz/providers",
    *(f"/localz/{key}" for key in CATEGORIES),
    "/privacy", "/backpack-capture/privacy", "/contact", "/upload", "/chcomms", "/survey",
]

# Only pages with a real translation get a /<lang> entry (and hreflang
# pairing) - listing an English page under /es would invite duplicate-content
# treatment. Mirror frontend/src/lib/i18n.ts:isTranslatedPath.
_TRANSLATED_STATIC = {"/", "/schools", "/budgets", "/directory", "/lunch", "/calendar"}
# A district's budget page is translated too, but listed in English only:
# ~585 pages times five languages would be most of the sitemap, and every
# one a render for the nightly warm job, for searches that come in English.
# A class page (/schools/<slug>/class-of-2027) isn't translated.
_TRANSLATED_SCHOOL_PATH = re.compile(r"^/schools/[^/]+(?:/calendar)?$")
_ALT_LANGS = ("es", "zh", "ko", "hi")


def _lang_path(path: str, lang: str) -> str:
    return f"/{lang}" if path == "/" else f"/{lang}{path}"


def _is_translated(path: str) -> bool:
    return path in _TRANSLATED_STATIC or bool(_TRANSLATED_SCHOOL_PATH.match(path))


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


async def season_paths(db: AsyncSession) -> list[str]:
    """A page for each season with something on it today: an attraction not
    over yet or a guide in its window, as the season's own page reads them."""
    today = today_et()
    seasons = union(
        select(SeasonalAttraction.season).where(SeasonalAttraction.ends_on >= today),
        select(SeasonalGuide.season).where(SeasonalGuide.starts_on <= today, SeasonalGuide.ends_on >= today),
    )
    return [f"/seasonal/{season}" for season in sorted((await db.execute(seasons)).scalars().all())]


async def class_page_lastmods(db: AsyncSession) -> dict[str, datetime]:
    """path -> newest item on it, for each enrolled class's page with
    anything on it. Every high school has four, but most show nothing (no
    class-page source is read there), and an empty page is no search result.
    Same items as routers/class_years.py:list_class_year_content."""
    years = current_grad_years()
    rows = (
        await db.execute(
            select(School.slug, SchoolContentItem.applies_to_grad_years, SchoolContentItem.extracted_at)
            .join(School, School.id == SchoolContentItem.school_id)
            .where(
                School.school_type == "high",
                School.slug.is_not(None),
                SchoolContentItem.is_current.is_(True),
                SchoolContentItem.source.in_(CLASS_PAGE_SOURCES),
            )
        )
    ).all()
    lastmods: dict[str, datetime] = {}
    for slug, applies_to, extracted_at in rows:
        for year in years:
            if not applies_to or year in applies_to:
                path = f"/schools/{slug}/class-of-{year}"
                lastmods[path] = max(extracted_at, lastmods.get(path, extracted_at))
    return dict(sorted(lastmods.items()))


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
    classes = list(await class_page_lastmods(db))
    budgets = [f"/budgets/{slug}" for slug in await budget_lastmods(db)]
    undated = _STATIC_PATHS + await season_paths(db)
    return [v for path in undated + pages + calendars for v in _variants(path)] + classes + budgets


async def _sitemap_xml(db: AsyncSession) -> bytes:
    base_url = os.getenv("PUBLIC_WEB_URL", "http://localhost:5173").rstrip("/")
    lastmods = await school_lastmods(db)
    entries = "".join(_entry(base_url, path, None) for path in _STATIC_PATHS + await season_paths(db))
    entries += "".join(_entry(base_url, path, mod) for slug, mod in lastmods.items() for path in _school_paths(slug))
    entries += "".join(_entry(base_url, path, mod) for path, mod in (await class_page_lastmods(db)).items())
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
