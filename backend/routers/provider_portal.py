"""The Localz provider portal, provider side: "Ask to be listed" (public, no
account) and, signed in, the listing form, its status, and quick updates to
an approved listing. Review is `routers/admin_resources.py`; the rules live
in `resources/portal.py`; design in docs/LOCALZ_DESIGN.md, "Provider portal".

Nothing a provider sends is public until a reviewer approves it, and v1 has
no outbound email or SMS: verification is a reviewer calling the listed
number, and decisions show here rather than in an email.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models import ProviderMembership, ResourceChangeRequest, ResourceOnboardingRequest, ResourceService, User
from resources import portal
from resources.portal import Cost, Hours, Submission
from resources.provider_types import BY_CODE, PROVIDER_TYPES
from services import upload_guard
from services.client_ip import client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/provider-portal", tags=["provider-portal"])


# ---- shapes ---------------------------------------------------------------------


class ProviderTypeOut(BaseModel):
    key: str
    label: str
    category: str
    normally_free: bool
    confidential_hint: bool


class InquiryIn(BaseModel):
    organization_name: str = Field(min_length=1, max_length=200)
    contact_name: str = Field(min_length=1, max_length=200)
    phone: str = Field(min_length=1, max_length=40)
    email: str | None = Field(default=None, max_length=255)
    what_you_provide: str = Field(min_length=1, max_length=1000)
    town: str = Field(min_length=1, max_length=100)
    # Honeypot: a field no person can see or reach.
    website: str | None = None
    bot_token: str | None = Field(default=None, max_length=2048)


class MatchIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)


class ListingBriefOut(BaseModel):
    id: str
    name: str
    organization_name: str | None
    city: str | None
    address: str | None
    phone: str | None
    source: str
    status: str
    location_confidential: bool


class CompletenessOut(BaseModel):
    missing_core: list[str]
    missing_optional: list[str]
    percent: int


class RequestIn(BaseModel):
    submission: Submission = Field(default_factory=Submission)
    # Confidential location, or a service-area program's mailing address.
    # Stored encrypted; never sent back, not even to the person who typed it.
    private_address: str | None = Field(default=None, max_length=300)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=40)
    claimed_service_id: str | None = Field(default=None, max_length=36)
    bot_token: str | None = Field(default=None, max_length=2048)


class RequestOut(BaseModel):
    id: str
    status: str
    origin: str
    submission: dict
    has_private_address: bool
    contact_name: str | None
    contact_phone: str | None
    claimed_service: ListingBriefOut | None
    completeness: CompletenessOut
    decision_note: str | None
    reject_reason: str | None
    fields_to_fix: list[str]
    service_ids: list[str]
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ClosureIn(BaseModel):
    starts_on: date
    ends_on: date
    note: str | None = Field(default=None, max_length=300)


class AddressIn(BaseModel):
    kind: str = Field(pattern=r"^(public|confidential|service_area)$")
    address: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, pattern=r"^\d{5}$")
    counties: list[str] = Field(default_factory=list, max_length=21)
    private_address: str | None = Field(default=None, max_length=300)

    @field_validator("counties")
    @classmethod
    def _counties(cls, values: list[str]) -> list[str]:
        return portal._county_list(values)


class ListingUpdateIn(BaseModel):
    """Every field optional; only the ones sent are changed (send null to
    clear a closure, an alert or this week's hours)."""

    closed_today: bool | None = None
    closure: ClosureIn | None = None
    week_hours: Hours | None = None
    hours: Hours | None = None
    alert: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=500)
    languages: list[str] | None = Field(default=None, max_length=20)
    documents: list[str] | None = Field(default=None, max_length=20)
    eligibility_note: str | None = Field(default=None, max_length=500)
    cost: Cost | None = None
    name: str | None = Field(default=None, max_length=200)
    organization_name: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    website: str | None = Field(default=None, max_length=300)
    email: str | None = Field(default=None, max_length=255)
    address: AddressIn | None = None
    types: list[str] | None = Field(default=None, max_length=5)


class ListingUpdateOut(BaseModel):
    applied: list[str]
    held: list[str]
    change_request_id: str | None


class PendingChangeOut(BaseModel):
    id: str
    fields: list[str]
    created_at: datetime


class ClosureOut(BaseModel):
    starts_on: date
    ends_on: date
    note: str | None


class MyListingOut(BaseModel):
    id: str
    name: str
    organization_name: str | None
    status: str
    role: str
    verified: bool
    description: str | None
    phone: str | None
    website: str | None
    email: str | None
    address_kind: str | None
    address: str | None
    city: str | None
    postal_code: str | None
    service_areas: list[str]
    hours: dict | None
    hours_text: str | None
    week_hours: dict | None
    closure: ClosureOut | None
    alert: str | None
    languages: list[str]
    required_documents: list[str]
    eligibility_text: str | None
    fees: str | None
    cost_kind: str | None
    types: list[str]
    pending_changes: list[PendingChangeOut]


# ---- helpers ----------------------------------------------------------------------


async def _brief(db: AsyncSession, service_id: str | None) -> ListingBriefOut | None:
    if not service_id:
        return None
    row = await db.get(ResourceService, service_id)
    return ListingBriefOut(**portal.listing_brief(row)) if row else None


async def request_out(db: AsyncSession, req: ResourceOnboardingRequest) -> RequestOut:
    sub = Submission.model_validate(req.submission)
    show_decision = req.status in ("changes_requested", "rejected", "approved")
    return RequestOut(
        id=req.id,
        status=req.status,
        origin=req.origin,
        submission=sub.model_dump(mode="json"),
        has_private_address=bool(req.private_address),
        contact_name=req.contact_name,
        contact_phone=req.contact_phone,
        claimed_service=await _brief(db, req.claimed_service_id),
        completeness=CompletenessOut(**portal.completeness(sub, bool(req.private_address))),
        decision_note=req.decision_note if show_decision else None,
        reject_reason=req.reject_reason if req.status == "rejected" else None,
        fields_to_fix=list(req.fields_to_fix or []) if req.status == "changes_requested" else [],
        service_ids=list(req.service_ids or []),
        submitted_at=req.submitted_at,
        created_at=req.created_at,
        updated_at=req.updated_at,
    )


async def _own_request(db: AsyncSession, request_id: str, user: User) -> ResourceOnboardingRequest:
    req = await db.get(ResourceOnboardingRequest, request_id)
    # Someone else's request is "not found", not "forbidden": no probing ids.
    if req is None or req.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return req


def _check_links(sub: Submission) -> None:
    try:
        portal.check_links(sub)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


def _clean(text: str | None) -> str | None:
    return (text or "").strip() or None


# ---- public ---------------------------------------------------------------------


@router.get("/types", response_model=list[ProviderTypeOut])
async def list_types() -> list[ProviderTypeOut]:
    """The kinds of service the form offers, each tied to a Localz category."""
    return [
        ProviderTypeOut(key=t.key, label=t.label, category=t.category, normally_free=t.normally_free, confidential_hint=t.confidential_hint)
        for t in PROVIDER_TYPES
    ]


@router.post("/inquiries", status_code=status.HTTP_201_CREATED)
async def ask_to_be_listed(body: InquiryIn, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """"Ask to be listed": no account. Lands in the review queue as a
    `submitted` request with origin "inquiry"; a reviewer calls back."""
    # A filled honeypot gets the same answer a person would.
    if body.website:
        return {"ok": True}
    ip = client_ip(request)
    hashed = portal.ip_hash(ip)
    if hashed:
        stamp = portal.now()
        in_day, in_hour = (
            await db.execute(
                select(
                    func.count(),
                    func.count().filter(ResourceOnboardingRequest.created_at > stamp - timedelta(hours=1)),
                ).where(
                    ResourceOnboardingRequest.ip_hash == hashed,
                    ResourceOnboardingRequest.created_at > stamp - timedelta(days=1),
                )
            )
        ).one()
        if in_hour >= portal.INQUIRIES_PER_HOUR or in_day >= portal.INQUIRIES_PER_DAY:
            logger.warning("provider_inquiry_rate_limited")
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests from this connection - please try again later.")
    try:
        passed, _ = await upload_guard.verify_bot_check(body.bot_token, ip)
    except upload_guard.BotCheckUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "This form is unavailable right now - please try again in a few minutes.") from None
    if not passed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "We couldn't confirm you're a person - please reload the page and try again.")
    if not portal.valid_phone(body.phone):
        raise HTTPException(422, "Please give a 10-digit phone number.")
    sub = Submission(
        organization_name=body.organization_name.strip(),
        phone=body.phone.strip(),
        what_you_provide=body.what_you_provide.strip(),
        town=body.town.strip(),
        email=_clean(body.email),
    )
    db.add(
        ResourceOnboardingRequest(
            status="submitted",
            origin="inquiry",
            submission=sub.model_dump(mode="json"),
            contact_name=body.contact_name.strip(),
            contact_phone=body.phone.strip(),
            contact_email=_clean(body.email),
            ip_hash=hashed,
            submitted_at=portal.now(),
        )
    )
    await db.commit()
    return {"ok": True}


# ---- signed in: requests ------------------------------------------------------------


@router.post("/match", response_model=list[ListingBriefOut])
async def is_this_you(body: MatchIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """"Is this you?" - existing listings with a similar name, so a provider
    claims their record instead of making a second one."""
    name = body.name.strip()
    key = portal.name_key(name)
    pattern = f"%{name[:80].replace('%', '').replace('_', ' ')}%"
    rows = (
        await db.execute(
            select(ResourceService)
            .where(
                ResourceService.status == "active",
                or_(
                    ResourceService.organization_name.ilike(pattern),
                    ResourceService.name.ilike(pattern),
                    func.regexp_replace(func.lower(ResourceService.organization_name), "[^a-z0-9]+", " ", "g") == key,
                ),
            )
            .order_by(ResourceService.organization_name, ResourceService.name)
            .limit(8)
        )
    ).scalars().all()
    return [ListingBriefOut(**portal.listing_brief(r)) for r in rows]


@router.get("/requests", response_model=list[RequestOut])
async def my_requests(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(ResourceOnboardingRequest)
            .where(ResourceOnboardingRequest.user_id == user.id)
            .order_by(ResourceOnboardingRequest.created_at.desc())
        )
    ).scalars().all()
    return [await request_out(db, r) for r in rows]


@router.post("/requests", response_model=RequestOut, status_code=status.HTTP_201_CREATED)
async def start_request(body: RequestIn, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stamp = portal.now()
    created_today, still_open = (
        await db.execute(
            select(
                func.count().filter(ResourceOnboardingRequest.created_at > stamp - timedelta(days=1)),
                func.count().filter(ResourceOnboardingRequest.status.in_(("draft", "submitted", "in_review", "changes_requested"))),
            ).where(ResourceOnboardingRequest.user_id == user.id)
        )
    ).one()
    if created_today >= portal.REQUESTS_PER_DAY or still_open >= portal.OPEN_REQUESTS_MAX:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "You have several listings in progress already - finish or withdraw one first.")
    try:
        passed, _ = await upload_guard.verify_bot_check(body.bot_token, client_ip(request))
    except upload_guard.BotCheckUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "This form is unavailable right now - please try again in a few minutes.") from None
    if not passed:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "We couldn't confirm you're a person - please reload the page and try again.")
    if body.claimed_service_id:
        claimed = await db.get(ResourceService, body.claimed_service_id)
        if claimed is None or claimed.status != "active":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "That listing isn't available")
    _check_links(body.submission)
    req = ResourceOnboardingRequest(
        status="draft",
        origin="self_serve",
        user_id=user.id,
        created_by_user_id=user.id,
        claimed_service_id=body.claimed_service_id,
        submission=body.submission.model_dump(mode="json"),
        private_address=_clean(body.private_address),
        contact_name=_clean(body.contact_name),
        contact_phone=_clean(body.contact_phone),
        contact_email=user.email,
    )
    db.add(req)
    await db.commit()
    await db.refresh(req)
    return await request_out(db, req)


@router.get("/requests/{request_id}", response_model=RequestOut)
async def get_request(request_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await request_out(db, await _own_request(db, request_id, user))


@router.put("/requests/{request_id}", response_model=RequestOut)
async def save_request(request_id: str, body: RequestIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Save the form. Only while it's a draft or changes were asked for:
    once submitted it's the reviewer's to read until they decide."""
    req = await _own_request(db, request_id, user)
    if req.status not in portal.EDITABLE_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "This request can't be edited right now")
    _check_links(body.submission)
    req.submission = body.submission.model_dump(mode="json")
    if body.private_address is not None:
        req.private_address = _clean(body.private_address)
    req.contact_name = _clean(body.contact_name)
    req.contact_phone = _clean(body.contact_phone)
    await db.commit()
    await db.refresh(req)
    return await request_out(db, req)


@router.post("/requests/{request_id}/submit", response_model=RequestOut)
async def submit_request(request_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    req = await _own_request(db, request_id, user)
    if req.status not in portal.EDITABLE_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "This request has already been sent")
    sub = Submission.model_validate(req.submission)
    missing = portal.completeness(sub, bool(req.private_address))["missing_core"]
    if missing:
        raise HTTPException(422, f"Still needed: {', '.join(missing)}")
    req.status = "submitted"
    req.submitted_at = portal.now()
    req.fields_to_fix = []
    portal.log(db, action="onboarding.submit", actor=user, actor_kind="provider", request_id=req.id)
    await db.commit()
    await db.refresh(req)
    return await request_out(db, req)


@router.post("/requests/{request_id}/withdraw", response_model=RequestOut)
async def withdraw_request(request_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    req = await _own_request(db, request_id, user)
    if req.status not in portal.WITHDRAWABLE_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "This request can't be withdrawn")
    req.status = "withdrawn"
    portal.log(db, action="onboarding.withdraw", actor=user, actor_kind="provider", request_id=req.id)
    await db.commit()
    await db.refresh(req)
    return await request_out(db, req)


# ---- signed in: approved listings --------------------------------------------------


def _closure(row: ResourceService) -> ClosureOut | None:
    if row.closure_ends_on and row.closure_starts_on and row.closure_ends_on >= portal.today():
        return ClosureOut(starts_on=row.closure_starts_on, ends_on=row.closure_ends_on, note=row.closure_note)
    return None


async def _listing_out(db: AsyncSession, row: ResourceService, membership: ProviderMembership) -> MyListingOut:
    pending = (
        await db.execute(
            select(ResourceChangeRequest)
            .where(
                ResourceChangeRequest.service_id == row.id,
                ResourceChangeRequest.status == "pending",
                ResourceChangeRequest.kind == "provider_edit",
            )
            .order_by(ResourceChangeRequest.created_at)
        )
    ).scalars().all()
    return MyListingOut(
        id=row.id,
        name=row.name,
        organization_name=row.organization_name,
        status=row.status,
        role=membership.role,
        verified=membership.verified_at is not None,
        description=row.description,
        phone=row.phone,
        website=row.website,
        email=row.email,
        address_kind=row.address_kind,
        address=row.address,
        city=row.city,
        postal_code=row.postal_code,
        service_areas=list(row.service_areas or []),
        hours=row.hours,
        hours_text=row.hours_text,
        week_hours=row.week_hours,
        closure=_closure(row),
        alert=row.alert,
        languages=list(row.languages or []),
        required_documents=list(row.required_documents or []),
        eligibility_text=row.eligibility_text,
        fees=row.fees,
        cost_kind=row.cost_kind,
        types=[BY_CODE[c].key for c in (row.taxonomy_codes or []) if c in BY_CODE],
        pending_changes=[PendingChangeOut(id=p.id, fields=sorted(p.changes), created_at=p.created_at) for p in pending],
    )


async def _membership(db: AsyncSession, user: User, service_id: str) -> tuple[ResourceService, ProviderMembership]:
    membership = (
        await db.execute(
            select(ProviderMembership).where(ProviderMembership.user_id == user.id, ProviderMembership.service_id == service_id)
        )
    ).scalar_one_or_none()
    row = await db.get(ResourceService, service_id) if membership else None
    if membership is None or row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    return row, membership


@router.get("/listings", response_model=list[MyListingOut])
async def my_listings(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    memberships = (
        await db.execute(select(ProviderMembership).where(ProviderMembership.user_id == user.id).order_by(ProviderMembership.created_at))
    ).scalars().all()
    out = []
    for m in memberships:
        row = await db.get(ResourceService, m.service_id)
        if row is not None:
            out.append(await _listing_out(db, row, m))
    return out


def _update_columns(body: ListingUpdateIn, row: ResourceService) -> tuple[dict, str | None]:
    """The listing columns a quick update sets, and a private address."""
    sent = body.model_fields_set
    cols: dict = {}
    private_address = None
    day = portal.today()
    if "closed_today" in sent:
        if body.closed_today:
            cols |= {"closure_starts_on": day.isoformat(), "closure_ends_on": day.isoformat(), "closure_note": None}
        else:
            cols |= {"closure_starts_on": None, "closure_ends_on": None, "closure_note": None}
    if "closure" in sent:
        if body.closure is None:
            cols |= {"closure_starts_on": None, "closure_ends_on": None, "closure_note": None}
        else:
            c = body.closure
            if c.ends_on < c.starts_on or c.ends_on < day or c.ends_on > day + timedelta(days=366):
                raise HTTPException(422, "Pick an end date on or after the start, within a year")
            cols |= {"closure_starts_on": c.starts_on.isoformat(), "closure_ends_on": c.ends_on.isoformat(), "closure_note": _clean(c.note)}
    if "week_hours" in sent:
        if body.week_hours is None:
            cols["week_hours"] = None
        else:
            cols["week_hours"] = {
                "week_of": portal.week_of(day).isoformat(),
                "hours": body.week_hours.model_dump(mode="json"),
                "text": portal.hours_text(body.week_hours),
            }
    if "hours" in sent and body.hours is not None:
        if body.hours.mode == "call" and not portal.valid_phone(row.phone):
            raise HTTPException(422, "\"Call for hours\" needs a phone number on the listing")
        cols |= {"hours": body.hours.model_dump(mode="json"), "hours_text": portal.hours_text(body.hours)}
    if "alert" in sent:
        cols["alert"] = _clean(body.alert)
    if "description" in sent:
        cols["description"] = _clean(body.description)
    if "languages" in sent:
        cols["languages"] = [x.strip()[:100] for x in body.languages or [] if x.strip()]
    if "documents" in sent:
        cols["required_documents"] = [x.strip()[:200] for x in body.documents or [] if x.strip()]
    if "eligibility_note" in sent:
        cols["eligibility_text"] = _clean(body.eligibility_note)
    if "cost" in sent and body.cost is not None:
        if body.cost.kind is None or (body.cost.kind == "fee" and not _clean(body.cost.amount)):
            raise HTTPException(422, "Say what it costs")
        cols |= {"cost_kind": body.cost.kind, "fees": portal.fees_text(body.cost)}
    for field in ("name", "organization_name", "email"):
        if field in sent:
            value = _clean(getattr(body, field))
            if field == "name" and not value:
                raise HTTPException(422, "A listing needs a name")
            cols[field] = value
    if "phone" in sent:
        if not portal.valid_phone(body.phone):
            raise HTTPException(422, "Please give a 10-digit phone number.")
        cols["phone"] = body.phone.strip()
    if "website" in sent:
        website = _clean(body.website)
        reason = portal.bad_link_reason(website)
        if reason:
            raise HTTPException(422, reason)
        if website and not website.lower().startswith(("http://", "https://")):
            website = "https://" + website
        cols["website"] = website
    if "address" in sent and body.address is not None:
        a = body.address
        if a.kind == "public" and not (_clean(a.address) and _clean(a.city)):
            raise HTTPException(422, "A public address needs a street and town")
        if a.kind != "public" and not a.counties:
            raise HTTPException(422, "Pick the counties you serve")
        cols |= portal.address_columns(a.kind, a.address, a.city, a.postal_code, a.counties)
        private_address = _clean(a.private_address)
    if "types" in sent and body.types is not None:
        if not body.types:
            raise HTTPException(422, "Pick at least one kind of service")
        unknown = [t for t in body.types if t not in portal.BY_KEY]
        if unknown:
            raise HTTPException(422, "Unknown kind of service")
        cols |= portal.type_columns(body.types)
    return cols, private_address


@router.patch("/listings/{service_id}", response_model=ListingUpdateOut)
async def update_listing(
    service_id: str, body: ListingUpdateIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Quick updates. For a verified member, hours, closures, alerts,
    description, languages, documents and the eligibility note publish
    now; name, address, phone, website, email, free -> fee and new
    categories wait for a reviewer while the old value stays live. An
    unverified member's every change waits."""
    row, membership = await _membership(db, user, service_id)
    cols, private_address = _update_columns(body, row)
    cols = portal.has_changes(row, cols)
    now_cols, held = portal.split_changes(row, cols, membership.verified_at is not None)
    if private_address:
        # A private address never publishes, so it's always the reviewer's call.
        held.setdefault("address_kind", cols.get("address_kind", row.address_kind))
    if now_cols:
        before = portal.snapshot(row, now_cols)
        portal.apply_columns(row, now_cols)
        portal.log(db, action="provider.update", actor=user, actor_kind="provider", service_id=row.id, before=before, after=now_cols)
    change_id = None
    if held:
        change = ResourceChangeRequest(
            service_id=row.id,
            kind="provider_edit",
            user_id=user.id,
            changes=held,
            before=portal.snapshot(row, held),
            private_address=private_address,
        )
        db.add(change)
        await db.flush()
        change_id = change.id
    await db.commit()
    return ListingUpdateOut(applied=sorted(now_cols), held=sorted(held) + (["private_address"] if private_address else []), change_request_id=change_id)
