"""Read API for Localz's community resources. Public, no login: the whole
point is that someone can find a food pantry without an account.

Search is a POST on purpose: what a person types ("eviction", "domestic
violence shelter") goes in the body, never a URL, so it doesn't land in
access logs, RUM, browser history or a shared link (docs/LOCALZ_DESIGN.md,
"Search analytics"). Categories and counties are not sensitive and could be
GET params, but they share the one search call to keep the client simple.

"Closest first" is worked out on the visitor's device: the visitor's point
never comes here. The device asks /nearby for every match inside a box
around the radius the visitor chose, snapped outward to a GRID-degree grid
(so it says no more than "somewhere in here"), measures and sorts them,
fetches the ones it shows with /by-ids, and then pages /search with
`outside` for what has no place to measure (hotlines, statewide programs,
confidential shelters). "Statewide" skips all of this: plain /search.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import ResourceService
from resources import childcarenj, nj211, portal, search_terms
from resources.categories import CATEGORIES, categories_for_code
from resources.eligibility import criteria_for

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


# "Closest first" boxes snap to this grid (degrees), so a box says no more
# about where someone is than "somewhere in this ~30-mile square".
GRID = 0.5
# Big enough for the widest radius the device offers (50 miles).
MAX_LAT_SPAN, MAX_LON_SPAN = 2.0, 2.5


class Box(BaseModel):
    south: float = Field(ge=38.5, le=41.5)
    west: float = Field(ge=-76.0, le=-73.5)
    north: float = Field(ge=38.5, le=41.5)
    east: float = Field(ge=-76.0, le=-73.5)

    @model_validator(mode="after")
    def _coarse(self) -> Box:
        edges = (self.south, self.west, self.north, self.east)
        if any(abs(e / GRID - round(e / GRID)) > 1e-9 for e in edges):
            raise ValueError(f"box edges must be multiples of {GRID}")
        if not (0 < self.north - self.south <= MAX_LAT_SPAN and 0 < self.east - self.west <= MAX_LON_SPAN):
            raise ValueError("box is empty or too big")
        return self

    def contains(self):
        return and_(
            ResourceService.latitude.between(self.south, self.north),
            ResourceService.longitude.between(self.west, self.east),
        )


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
    # The rest of a "closest first" list: only what /nearby couldn't place
    # in this box (no location, or statewide and located elsewhere).
    outside: Box | None = None
    page: int = Field(default=1, ge=1, le=200)
    # Overrides `page` - the rest of a closest-first list starts mid-page.
    offset: int | None = Field(default=None, ge=0, le=10000)
    page_size: int = Field(default=20, ge=1, le=50)


class NearbyIn(BaseModel):
    category: str | None = Field(default=None, max_length=40)
    query: str | None = Field(default=None, max_length=100)
    type: str | None = Field(default=None, max_length=40)
    box: Box


class NearbyOut(BaseModel):
    # [id, lat, lon, statewide] per listing, compact: a box can hold thousands.
    points: list[tuple[str, float, float, bool]]


class ByIdsIn(BaseModel):
    ids: list[str] = Field(max_length=50)


class ClosureOut(BaseModel):
    starts_on: date
    ends_on: date
    note: str | None


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
    # Structured "who can come" (resources/eligibility.py), null until the
    # sentence has been read. The browser matches it against the visitor's
    # own answers, which never come here.
    eligibility: dict | None = None
    # A provider's "Closed today" / temporary closure, while it lasts.
    closure: ClosureOut | None = None
    # A confidential location (a shelter): no address, town or pin is ever
    # sent; the page says "Location shared after you call".
    location_confidential: bool = False


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
    # "This week only" hours a provider posted, for the current week.
    week_hours_text: str | None = None
    missing_core: list[str]
    source: str
    source_url: str | None
    updated_at: datetime


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _confidential(row: ResourceService) -> bool:
    return row.address_kind == "confidential"


def _closure(row: ResourceService) -> ClosureOut | None:
    if row.closure_starts_on and row.closure_ends_on and row.closure_ends_on >= portal.today():
        return ClosureOut(starts_on=row.closure_starts_on, ends_on=row.closure_ends_on, note=row.closure_note)
    return None


def _week_hours_text(row: ResourceService) -> str | None:
    week = row.week_hours or {}
    if week.get("week_of") == portal.week_of(portal.today()).isoformat():
        return week.get("text")
    return None


def _summary(row: ResourceService, eligibility: dict | None = None) -> dict:
    # A confidential row has no location columns in the first place
    # (resources/portal.py); this is the second lock on the same door.
    hidden = _confidential(row)
    return {
        "id": row.id,
        "name": row.name,
        "organization_name": row.organization_name,
        "location_name": row.location_name,
        "description": row.description,
        "phone": row.phone,
        "address": None if hidden else row.address,
        "city": None if hidden else row.city,
        "hours_text": row.hours_text,
        "closure": _closure(row),
        "location_confidential": hidden,
        "categories": list(row.categories or []),
        "complete": not row.missing_core,
        "statewide": _is_statewide(row),
        "last_assured_on": row.last_assured_on,
        "eligibility": eligibility,
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
    if body.outside:
        filters.append(or_(ResourceService.latitude.is_(None), and_(_statewide_sql(), ~body.outside.contains())))
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
                # Everyday words ("English classes") for what listings call ESL.
                *(ResourceService.categories.contains([c]) for c in search_terms.categories_meant(query)),
            )
        )
    return filters


def _source_url(row: ResourceService) -> str | None:
    # Attribution: every record links back to its source's own page (for
    # ChildCareNJ, the one with the provider's inspection reports).
    if row.source == nj211.SOURCE:
        return f"{nj211.BASE_URL}/search/{row.source_record_id}"
    if row.source == childcarenj.SOURCE:
        return childcarenj.provider_url(row.source_record_id, (row.raw or {}).get("LicenseNumber"))
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
                .offset(body.offset if body.offset is not None else (body.page - 1) * body.page_size)
                .limit(body.page_size)
            )
        )
        .scalars()
        .all()
    )
    criteria = await criteria_for(db, list(rows))
    return ResourceSearchOut(items=[ResourceSummaryOut(**_summary(r, criteria.get(r.id))) for r in rows], total=total)


@router.post("/nearby", response_model=NearbyOut)
async def nearby_resources(body: NearbyIn, db: AsyncSession = Depends(get_db)) -> NearbyOut:
    """Every match with a place inside the box, for the device to measure.
    No county filter: distance decides what's near, not a county line."""
    filters = _filters(ResourceSearchIn(category=body.category, query=body.query, type=body.type))
    rows = (
        await db.execute(
            select(ResourceService.id, ResourceService.latitude, ResourceService.longitude, _statewide_sql())
            .where(
                *filters,
                body.box.contains(),
                or_(ResourceService.address_kind.is_(None), ResourceService.address_kind != "confidential"),
            )
            .order_by(ResourceService.id)
        )
    ).all()
    return NearbyOut(points=[(r[0], round(r[1], 3), round(r[2], 3), bool(r[3])) for r in rows])


@router.post("/by-ids", response_model=list[ResourceSummaryOut])
async def resources_by_ids(body: ByIdsIn, db: AsyncSession = Depends(get_db)) -> list[ResourceSummaryOut]:
    """The listings the device chose to show, in its order."""
    if not body.ids:
        return []
    found = {
        r.id: r
        for r in (await db.execute(select(ResourceService).where(ResourceService.id.in_(body.ids), ResourceService.status == "active"))).scalars()
    }
    rows = [found[i] for i in dict.fromkeys(body.ids) if i in found]
    criteria = await criteria_for(db, rows)
    return [ResourceSummaryOut(**_summary(r, criteria.get(r.id))) for r in rows]


@router.get("/{resource_id}", response_model=ResourceDetailOut)
async def get_resource(resource_id: str, db: AsyncSession = Depends(get_db)) -> ResourceDetailOut:
    row = await db.get(ResourceService, resource_id)
    if row is None or row.status != "active":
        raise HTTPException(status_code=404, detail="Resource not found")
    criteria = await criteria_for(db, [row])
    return ResourceDetailOut(
        **_summary(row, criteria.get(row.id)),
        email=row.email,
        website=row.website,
        postal_code=None if _confidential(row) else row.postal_code,
        latitude=None if _confidential(row) else row.latitude,
        longitude=None if _confidential(row) else row.longitude,
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
        week_hours_text=_week_hours_text(row),
        missing_core=list(row.missing_core or []),
        source=row.source,
        source_url=_source_url(row),
        updated_at=row.updated_at,
    )
