"""Read API for Localz's community resources. Public, no login: the whole
point is that someone can find a food pantry without an account.

Search is a POST on purpose: what a person types ("eviction", "domestic
violence shelter") goes in the body, never a URL, so it doesn't land in
access logs, RUM, browser history or a shared link (docs/LOCALZ_DESIGN.md,
"Search analytics"). Categories and counties are not sensitive and could be
GET params, but they share the one search call to keep the client simple.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import ResourceService
from resources import nj211
from resources.categories import CATEGORIES, categories_for_code

router = APIRouter(prefix="/resources", tags=["resources"])

NJ_COUNTIES = (
    "Atlantic", "Bergen", "Burlington", "Camden", "Cape May", "Cumberland", "Essex", "Gloucester", "Hudson",
    "Hunterdon", "Mercer", "Middlesex", "Monmouth", "Morris", "Ocean", "Passaic", "Salem", "Somerset",
    "Sussex", "Union", "Warren",
)


# Listed by NJ 211 for at least this many counties' searches: statewide in
# practice, even before its detail page says so.
STATEWIDE_MIN_COUNTIES = 10
STATEWIDE_AREAS = ["NJ", "New Jersey", "Statewide"]


class CategoryOut(BaseModel):
    key: str
    label: str
    count: int


class ResourceSearchIn(BaseModel):
    category: str | None = Field(default=None, max_length=40)
    query: str | None = Field(default=None, max_length=100)
    county: str | None = Field(default=None, max_length=40)
    # A taxonomy code from POST /resources/types ("BD-1800.2000").
    type: str | None = Field(default=None, max_length=40)
    page: int = Field(default=1, ge=1, le=200)
    page_size: int = Field(default=20, ge=1, le=50)


class ResourceSummaryOut(BaseModel):
    id: str
    name: str
    organization_name: str | None
    location_name: str | None
    description: str | None
    phone: str | None
    address: str | None
    city: str | None
    hours_text: str | None
    categories: list[str]
    complete: bool
    statewide: bool
    last_assured_on: date | None


class ResourceTypeOut(BaseModel):
    code: str
    name: str
    count: int


class ResourceSearchOut(BaseModel):
    items: list[ResourceSummaryOut]
    total: int


class ResourceDetailOut(ResourceSummaryOut):
    email: str | None
    website: str | None
    postal_code: str | None
    latitude: float | None
    longitude: float | None
    eligibility_text: str | None
    application_process: str | None
    fees: str | None
    required_documents: list[str]
    languages: list[str]
    accessibility: str | None
    transportation: str | None
    service_areas: list[str]
    taxonomy_names: list[str]
    alert: str | None
    missing_core: list[str]
    source: str
    source_url: str | None
    updated_at: datetime


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _summary(row: ResourceService) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "organization_name": row.organization_name,
        "location_name": row.location_name,
        "description": row.description,
        "phone": row.phone,
        "address": row.address,
        "city": row.city,
        "hours_text": row.hours_text,
        "categories": list(row.categories or []),
        "complete": not row.missing_core,
        "statewide": _is_statewide(row),
        "last_assured_on": row.last_assured_on,
    }


def _is_statewide(row: ResourceService) -> bool:
    return bool(set(row.service_areas or []) & set(STATEWIDE_AREAS)) or len(row.listed_in_counties or []) >= STATEWIDE_MIN_COUNTIES


def _statewide_sql():
    return or_(
        ResourceService.service_areas.overlap(STATEWIDE_AREAS),
        func.cardinality(ResourceService.listed_in_counties) >= STATEWIDE_MIN_COUNTIES,
    )


def _county(name: str | None) -> str | None:
    if not name:
        return None
    county = next((c for c in NJ_COUNTIES if c.lower() == name.strip().lower()), None)
    if county is None:
        raise HTTPException(status_code=422, detail="Unknown county")
    return county


def _mentions(county: str):
    return func.array_to_string(ResourceService.service_areas, "|").ilike(f"%{county} County%")


def _filters(body: ResourceSearchIn, *, with_type: bool = True) -> list:
    filters = [ResourceService.status == "active"]
    if body.category:
        if body.category not in CATEGORIES:
            raise HTTPException(status_code=422, detail="Unknown category")
        filters.append(ResourceService.categories.contains([body.category]))
    county = _county(body.county)
    if county:
        # Serves the county if its own service area says so, if NJ 211
        # listed it for that county's search, or if it's statewide. A record
        # with neither on file yet is shown too: unknown is not "elsewhere".
        filters.append(
            or_(
                _mentions(county),
                ResourceService.listed_in_counties.contains([county]),
                _statewide_sql(),
                and_(
                    func.cardinality(ResourceService.service_areas) == 0,
                    func.cardinality(ResourceService.listed_in_counties) == 0,
                ),
            )
        )
    if with_type and body.type:
        filters.append(ResourceService.taxonomy_codes.contains([body.type]))
    query = (body.query or "").strip()
    if query:
        pattern = f"%{_escape_like(query)}%"
        filters.append(
            or_(
                ResourceService.name.ilike(pattern, escape="\\"),
                ResourceService.organization_name.ilike(pattern, escape="\\"),
                ResourceService.location_name.ilike(pattern, escape="\\"),
                ResourceService.description.ilike(pattern, escape="\\"),
                func.array_to_string(ResourceService.taxonomy_names, " ").ilike(pattern, escape="\\"),
            )
        )
    return filters


def _source_url(row: ResourceService) -> str | None:
    # Attribution: every NJ 211 record links back to NJ 211's own page.
    if row.source == nj211.SOURCE:
        return f"{nj211.BASE_URL}/search/{row.source_record_id}"
    return None


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(county: str | None = Query(default=None, max_length=40), db: AsyncSession = Depends(get_db)) -> list[CategoryOut]:
    """Listing counts per category, for one county when given (a county name
    isn't sensitive, so it can sit in the query string)."""
    category = func.unnest(ResourceService.categories).label("category")
    sub = select(category).where(*_filters(ResourceSearchIn(county=county))).subquery()
    counts = dict((await db.execute(select(sub.c.category, func.count()).group_by(sub.c.category))).all())
    return [CategoryOut(key=key, label=label, count=counts.get(key, 0)) for key, label in CATEGORIES.items()]


@router.post("/types", response_model=list[ResourceTypeOut])
async def list_types(body: ResourceSearchIn, db: AsyncSession = Depends(get_db)) -> list[ResourceTypeOut]:
    """The kinds of service ("Food Pantries", "Soup Kitchens") within a
    category, counted for the same county and text as the list - but not the
    chosen type, so picking one never zeroes out the others."""
    if not body.category:
        raise HTTPException(status_code=422, detail="Pick a category first")
    pairs = (
        select(
            func.unnest(ResourceService.taxonomy_codes).label("code"),
            func.unnest(ResourceService.taxonomy_names).label("name"),
        )
        .where(*_filters(body, with_type=False))
        .subquery()
    )
    rows = (await db.execute(select(pairs.c.code, pairs.c.name, func.count()).group_by(pairs.c.code, pairs.c.name))).all()
    # A pantry that also hands out hygiene kits carries both codes; only the
    # codes that belong to this category are types of it.
    types = [
        ResourceTypeOut(code=code, name=name, count=count)
        for code, name, count in rows
        if body.category in categories_for_code(code)
    ]
    return sorted(types, key=lambda t: (-t.count, t.name.lower()))


@router.post("/search", response_model=ResourceSearchOut)
async def search_resources(body: ResourceSearchIn, db: AsyncSession = Depends(get_db)) -> ResourceSearchOut:
    filters = _filters(body)
    county = _county(body.county)
    order = []
    if county:
        # Services that name the county first, then ones NJ 211 listed for
        # only a few counties, then statewide ones, then the unplaced.
        statewide = _statewide_sql()
        order.append(
            case(
                (and_(_mentions(county), ~statewide), 0),
                (and_(ResourceService.listed_in_counties.contains([county]), func.cardinality(ResourceService.listed_in_counties) <= 3, ~statewide), 1),
                (statewide, 2),
                else_=3,
            )
        )
    # Complete records next: an entry with no hours or phone is still worth
    # finding, but not before one that has them.
    order += [case((func.cardinality(ResourceService.missing_core) == 0, 0), else_=1), func.lower(ResourceService.name), ResourceService.id]
    total = (await db.execute(select(func.count()).select_from(ResourceService).where(*filters))).scalar_one()
    rows = (
        (
            await db.execute(
                select(ResourceService)
                .where(*filters)
                .order_by(*order)
                .offset((body.page - 1) * body.page_size)
                .limit(body.page_size)
            )
        )
        .scalars()
        .all()
    )
    return ResourceSearchOut(items=[ResourceSummaryOut(**_summary(r)) for r in rows], total=total)


@router.get("/{resource_id}", response_model=ResourceDetailOut)
async def get_resource(resource_id: str, db: AsyncSession = Depends(get_db)) -> ResourceDetailOut:
    row = await db.get(ResourceService, resource_id)
    if row is None or row.status != "active":
        raise HTTPException(status_code=404, detail="Resource not found")
    return ResourceDetailOut(
        **_summary(row),
        email=row.email,
        website=row.website,
        postal_code=row.postal_code,
        latitude=row.latitude,
        longitude=row.longitude,
        eligibility_text=row.eligibility_text,
        application_process=row.application_process,
        fees=row.fees,
        required_documents=list(row.required_documents or []),
        languages=list(row.languages or []),
        accessibility=row.accessibility,
        transportation=row.transportation,
        service_areas=list(row.service_areas or []),
        taxonomy_names=list(row.taxonomy_names or []),
        alert=row.alert,
        missing_core=list(row.missing_core or []),
        source=row.source,
        source_url=_source_url(row),
        updated_at=row.updated_at,
    )
