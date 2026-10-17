"""The Localz review queue: onboarding requests and held edits to live
listings. GETs need `resources.view`, every change `resources.manage` (the
"Localz reviewer" role holds both). Rules in `resources/portal.py`; design
in docs/LOCALZ_DESIGN.md, "Onboarding approval".

This is the only place a confidential address is ever read back, and only
to a reviewer who can act on it (`resources.manage`) in a signed-in browser
session: a view-only role or an API key sees only that one is on file.
"""
from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, get_effective_permissions, is_api_key_request, require_permission
from database import get_db
from models import (
    ProviderMembership,
    ResourceChangeLog,
    ResourceChangeRequest,
    ResourceOnboardingRequest,
    ResourcePrivateAddress,
    ResourceService,
    User,
)
from resources import portal, portal_mail
from resources.portal import Submission
from routers.provider_portal import ListingBriefOut, RequestOut, request_out
from services import mailer

_reveal_private: ContextVar[bool] = ContextVar("reveal_private_address", default=False)


async def _set_reveal(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> None:
    """Whether this request may see a confidential address (a shelter's
    location). Async, so the value is visible to the endpoint."""
    allowed = not is_api_key_request(request) and (
        user.is_admin or "resources.manage" in await get_effective_permissions(request, db, user)
    )
    _reveal_private.set(allowed)


def _private(value: str | None) -> str | None:
    return value if _reveal_private.get() else None


router = APIRouter(prefix="/admin/resources", tags=["admin-resources"], dependencies=[Depends(_set_reveal)])

_view = require_permission("resources.view")
_manage = require_permission("resources.manage")


class FlagOut(BaseModel):
    code: str
    level: str
    message: str


class DuplicateOut(ListingBriefOut):
    reasons: list[str]


class LogOut(BaseModel):
    id: str
    service_id: str | None
    request_id: str | None
    actor_email: str | None
    actor_kind: str
    action: str
    before: dict
    after: dict
    note: str | None
    reverted_at: datetime | None
    revertible: bool
    created_at: datetime


class QueueItemOut(BaseModel):
    id: str
    status: str
    origin: str
    organization_name: str | None
    town: str | None
    claim: bool
    percent: int
    missing_core: list[str]
    submitted_at: datetime | None
    created_at: datetime


class ReviewOut(RequestOut):
    contact_email: str | None
    account_email: str | None
    # Plain, for the reviewer verifying it. Never in any other response.
    private_address: str | None
    checklist: dict
    # The claimed listing's source-published email, masked: when set, the
    # phone call is optional (they can confirm with a code sent there).
    verify_by_email: str | None = None
    duplicates: list[DuplicateOut]
    flags: list[FlagOut]
    log: list[LogOut]
    reviewed_at: datetime | None


class CountOut(BaseModel):
    onboarding: int
    changes: int


class AssistedIn(BaseModel):
    submission: Submission = Field(default_factory=Submission)
    private_address: str | None = Field(default=None, max_length=300)
    contact_name: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, max_length=40)
    contact_email: str | None = Field(default=None, max_length=255)
    claimed_service_id: str | None = Field(default=None, max_length=36)


class EditIn(BaseModel):
    submission: Submission
    private_address: str | None = Field(default=None, max_length=300)


class ChecklistIn(BaseModel):
    checklist: dict[str, bool]


class ApproveIn(ChecklistIn):
    note: str | None = Field(default=None, max_length=2000)
    target_service_id: str | None = Field(default=None, max_length=36)


class MergeIn(ApproveIn):
    target_service_id: str = Field(max_length=36)


class ChangesIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)
    fields: list[str] = Field(default_factory=list, max_length=20)


class RejectIn(BaseModel):
    reason: str = Field(max_length=40)
    note: str | None = Field(default=None, max_length=2000)


class NoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class ChangeOut(BaseModel):
    id: str
    service: ListingBriefOut | None
    kind: str
    source: str | None
    changes: dict
    before: dict
    has_private_address: bool
    private_address: str | None
    requested_by: str | None
    status: str
    note: str | None
    created_at: datetime


class MemberIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: str = Field(default="editor", pattern=r"^(owner|editor)$")


class MemberOut(BaseModel):
    id: str
    email: str | None
    role: str
    verified_at: datetime | None
    created_at: datetime


# ---- helpers ------------------------------------------------------------------------


async def _emails(db: AsyncSession, ids: set[str | None]) -> dict[str, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict((await db.execute(select(User.id, User.email).where(User.id.in_(ids)))).all())


async def _log_outs(db: AsyncSession, entries: list[ResourceChangeLog]) -> list[LogOut]:
    emails = await _emails(db, {e.actor_user_id for e in entries})
    return [
        LogOut(
            id=e.id,
            service_id=e.service_id,
            request_id=e.request_id,
            actor_email=emails.get(e.actor_user_id or ""),
            actor_kind=e.actor_kind,
            action=e.action,
            before=e.before,
            after=e.after,
            note=e.note,
            reverted_at=e.reverted_at,
            revertible=e.action in portal.REVERTIBLE and e.reverted_at is None and e.service_id is not None,
            created_at=e.created_at,
        )
        for e in entries
    ]


async def _request(db: AsyncSession, request_id: str) -> ResourceOnboardingRequest:
    req = await db.get(ResourceOnboardingRequest, request_id)
    if req is None or req.status == "draft":
        # A draft is the provider's own until they send it.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return req


async def _review_out(db: AsyncSession, req: ResourceOnboardingRequest) -> ReviewOut:
    base = await request_out(db, req)
    sub = Submission.model_validate(req.submission)
    account_email = (await _emails(db, {req.user_id})).get(req.user_id or "")
    exclude = [x for x in [req.claimed_service_id, *(req.service_ids or [])] if x]
    entries = (
        await db.execute(
            select(ResourceChangeLog)
            .where(ResourceChangeLog.request_id == req.id)
            .order_by(ResourceChangeLog.created_at)
        )
    ).scalars().all()
    data = base.model_dump()
    # The reviewer sees the decision fields whatever the status.
    data |= {
        "decision_note": req.decision_note,
        "reject_reason": req.reject_reason,
        "fields_to_fix": list(req.fields_to_fix or []),
    }
    return ReviewOut(
        **data,
        contact_email=req.contact_email,
        account_email=account_email,
        private_address=_private(req.private_address),
        checklist=dict(req.checklist or {}),
        verify_by_email=_masked_source_email(
            await db.get(ResourceService, req.claimed_service_id) if req.claimed_service_id and req.status != "approved" else None
        ),
        duplicates=[DuplicateOut(**d) for d in await portal.duplicates(db, sub, exclude)],
        flags=[FlagOut(**f) for f in await portal.flags(db, req, sub, account_email)],
        log=await _log_outs(db, list(entries)),
        reviewed_at=req.reviewed_at,
    )


def _checklist(values: dict[str, bool]) -> dict[str, bool]:
    unknown = set(values) - set(portal.CHECKLIST_ITEMS)
    if unknown:
        raise HTTPException(422, f"Unknown checklist item: {', '.join(sorted(unknown))}")
    return {k: bool(values.get(k)) for k in portal.CHECKLIST_ITEMS}


def _open(req: ResourceOnboardingRequest) -> None:
    if req.status not in portal.OPEN_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, f"This request is {req.status.replace('_', ' ')}")


# ---- onboarding queue -------------------------------------------------------------------


@router.get("/onboarding", response_model=list[QueueItemOut])
async def queue(
    state: str = Query(default="open", max_length=20),
    _: User = Depends(_view),
    db: AsyncSession = Depends(get_db),
):
    """Oldest first: whoever has waited longest is next."""
    query = select(ResourceOnboardingRequest).where(ResourceOnboardingRequest.status != "draft")
    if state == "open":
        query = query.where(ResourceOnboardingRequest.status.in_(portal.OPEN_STATUSES))
    elif state != "all":
        query = query.where(ResourceOnboardingRequest.status == state)
    query = query.order_by(
        ResourceOnboardingRequest.submitted_at.asc().nulls_last(), ResourceOnboardingRequest.created_at.asc()
    ).limit(200)
    out = []
    for req in (await db.execute(query)).scalars().all():
        sub = Submission.model_validate(req.submission)
        done = portal.completeness(sub, bool(req.private_address))
        out.append(
            QueueItemOut(
                id=req.id,
                status=req.status,
                origin=req.origin,
                organization_name=sub.organization_name,
                town=sub.city or sub.town,
                claim=bool(req.claimed_service_id),
                percent=done["percent"],
                missing_core=done["missing_core"],
                submitted_at=req.submitted_at,
                created_at=req.created_at,
            )
        )
    return out


@router.get("/onboarding/count", response_model=CountOut)
async def pending_count(_: User = Depends(_view), db: AsyncSession = Depends(get_db)):
    onboarding = await db.scalar(
        select(func.count()).select_from(ResourceOnboardingRequest).where(ResourceOnboardingRequest.status.in_(portal.OPEN_STATUSES))
    )
    changes = await db.scalar(
        select(func.count()).select_from(ResourceChangeRequest).where(ResourceChangeRequest.status == "pending")
    )
    return CountOut(onboarding=onboarding or 0, changes=changes or 0)


@router.post("/onboarding", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
async def start_assisted(body: AssistedIn, admin: User = Depends(_manage), db: AsyncSession = Depends(get_db)):
    """A reviewer starts a request for a provider who called or emailed.
    It goes through the same approval - by someone else, where there's
    more than one reviewer."""
    try:
        portal.check_links(body.submission)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    req = ResourceOnboardingRequest(
        status="submitted",
        origin="admin_assisted",
        created_by_user_id=admin.id,
        claimed_service_id=body.claimed_service_id,
        submission=body.submission.model_dump(mode="json"),
        private_address=(body.private_address or "").strip() or None,
        contact_name=(body.contact_name or "").strip() or None,
        contact_phone=(body.contact_phone or "").strip() or None,
        contact_email=(body.contact_email or "").strip() or None,
        submitted_at=portal.now(),
    )
    db.add(req)
    await db.flush()
    portal.log(db, action="onboarding.assisted", actor=admin, actor_kind="reviewer", request_id=req.id)
    await db.commit()
    await db.refresh(req)
    return await _review_out(db, req)


@router.get("/onboarding/{request_id}", response_model=ReviewOut)
async def review(request_id: str, _: User = Depends(_view), db: AsyncSession = Depends(get_db)):
    return await _review_out(db, await _request(db, request_id))


@router.put("/onboarding/{request_id}", response_model=ReviewOut)
async def edit_before_approving(request_id: str, body: EditIn, admin: User = Depends(_manage), db: AsyncSession = Depends(get_db)):
    """Logged as the reviewer's change, before and after."""
    req = await _request(db, request_id)
    _open(req)
    try:
        portal.check_links(body.submission)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    before = dict(req.submission)
    req.submission = body.submission.model_dump(mode="json")
    after = dict(req.submission)
    if body.private_address is not None:
        req.private_address = body.private_address.strip() or None
        after["private_address"] = "changed"
    req.status = "in_review"
    portal.log(db, action="admin.edit", actor=admin, actor_kind="reviewer", request_id=req.id, before=before, after=after)
    await db.commit()
    await db.refresh(req)
    return await _review_out(db, req)


@router.put("/onboarding/{request_id}/checklist", response_model=ReviewOut)
async def save_checklist(request_id: str, body: ChecklistIn, admin: User = Depends(_manage), db: AsyncSession = Depends(get_db)):
    req = await _request(db, request_id)
    _open(req)
    req.checklist = _checklist(body.checklist)
    req.status = "in_review"
    await db.commit()
    await db.refresh(req)
    return await _review_out(db, req)


def _masked_source_email(target: ResourceService | None) -> str | None:
    email = portal.source_email(target)
    return portal_mail.mask(email) if email else None


async def _approve(db: AsyncSession, req: ResourceOnboardingRequest, admin: User, body: ApproveIn,
                   background: BackgroundTasks) -> ReviewOut:
    _open(req)
    checklist = _checklist(body.checklist)
    target_id = body.target_service_id or req.claimed_service_id
    target = await db.get(ResourceService, target_id) if target_id else None
    if target_id and target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That listing doesn't exist")
    # Claiming a listing whose source published an email: the call can be
    # skipped - they confirm with a code sent there instead, and until they
    # do, everything they change waits for review.
    optional = {"connected"} if portal.source_email(target) else set()
    if not all(v for k, v in checklist.items() if k not in optional):
        raise HTTPException(422, "Tick every checklist item before approving")
    sub = Submission.model_validate(req.submission)
    missing = portal.completeness(sub, bool(req.private_address))["missing_core"]
    if missing:
        raise HTTPException(422, f"The required core is incomplete: {', '.join(missing)}")
    try:
        portal.check_links(sub)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if req.origin == "admin_assisted" and req.created_by_user_id == admin.id and await portal.reviewer_count(db) > 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "A request you started is approved by another reviewer")
    req.checklist = checklist
    await portal.approve(db, req, admin, target, (body.note or "").strip() or None)
    await portal_mail.request_decided(db, req)
    await db.commit()
    background.add_task(mailer.send_pending_quietly)
    await db.refresh(req)
    return await _review_out(db, req)


@router.post("/onboarding/{request_id}/approve", response_model=ReviewOut)
async def approve(request_id: str, body: ApproveIn, background: BackgroundTasks, admin: User = Depends(_manage),
                  db: AsyncSession = Depends(get_db)):
    return await _approve(db, await _request(db, request_id), admin, body, background)


@router.post("/onboarding/{request_id}/merge", response_model=ReviewOut)
async def merge(request_id: str, body: MergeIn, background: BackgroundTasks, admin: User = Depends(_manage),
                db: AsyncSession = Depends(get_db)):
    """Approve into an existing listing instead of creating a second one."""
    return await _approve(db, await _request(db, request_id), admin, body, background)


@router.post("/onboarding/{request_id}/request-changes", response_model=ReviewOut)
async def request_changes(request_id: str, body: ChangesIn, background: BackgroundTasks, admin: User = Depends(_manage),
                          db: AsyncSession = Depends(get_db)):
    req = await _request(db, request_id)
    _open(req)
    note = body.note.strip()
    if not note:
        raise HTTPException(422, "Say what needs changing")
    req.status = "changes_requested"
    req.decision_note = note
    req.fields_to_fix = [f for f in body.fields if f in (*portal.CORE_ITEMS, *portal.OPTIONAL_ITEMS)]
    req.reviewed_by_user_id, req.reviewed_at = admin.id, portal.now()
    portal.log(db, action="onboarding.decision", actor=admin, actor_kind="reviewer", request_id=req.id,
               after={"status": "changes_requested", "fields": req.fields_to_fix, "checklist": req.checklist}, note=note)
    await portal_mail.request_decided(db, req)
    await db.commit()
    background.add_task(mailer.send_pending_quietly)
    await db.refresh(req)
    return await _review_out(db, req)


@router.post("/onboarding/{request_id}/reject", response_model=ReviewOut)
async def reject(request_id: str, body: RejectIn, background: BackgroundTasks, admin: User = Depends(_manage),
                 db: AsyncSession = Depends(get_db)):
    req = await _request(db, request_id)
    _open(req)
    if body.reason not in portal.REJECT_REASONS:
        raise HTTPException(422, "Pick a reason")
    req.status = "rejected"
    req.reject_reason = body.reason
    req.decision_note = (body.note or "").strip() or None
    req.reviewed_by_user_id, req.reviewed_at = admin.id, portal.now()
    portal.log(db, action="onboarding.decision", actor=admin, actor_kind="reviewer", request_id=req.id,
               after={"status": "rejected", "reason": body.reason, "checklist": req.checklist}, note=req.decision_note)
    await portal_mail.request_decided(db, req)
    await db.commit()
    background.add_task(mailer.send_pending_quietly)
    await db.refresh(req)
    return await _review_out(db, req)


# ---- held edits ------------------------------------------------------------------------


async def _change_outs(db: AsyncSession, rows: list[ResourceChangeRequest]) -> list[ChangeOut]:
    emails = await _emails(db, {r.user_id for r in rows})
    out = []
    for r in rows:
        service = await db.get(ResourceService, r.service_id)
        out.append(
            ChangeOut(
                id=r.id,
                service=ListingBriefOut(**portal.listing_brief(service)) if service else None,
                kind=r.kind,
                source=r.source,
                changes=r.changes,
                before=r.before,
                has_private_address=bool(r.private_address),
                private_address=_private(r.private_address),
                requested_by=emails.get(r.user_id or ""),
                status=r.status,
                note=r.note,
                created_at=r.created_at,
            )
        )
    return out


@router.get("/changes", response_model=list[ChangeOut])
async def held_changes(
    state: str = Query(default="pending", max_length=20), _: User = Depends(_view), db: AsyncSession = Depends(get_db)
):
    query = select(ResourceChangeRequest)
    if state != "all":
        query = query.where(ResourceChangeRequest.status == state)
    rows = (await db.execute(query.order_by(ResourceChangeRequest.created_at.asc()).limit(200))).scalars().all()
    return await _change_outs(db, list(rows))


async def _pending_change(db: AsyncSession, change_id: str) -> ResourceChangeRequest:
    change = await db.get(ResourceChangeRequest, change_id)
    if change is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change not found")
    if change.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"This change is already {change.status}")
    return change


@router.post("/changes/{change_id}/approve", response_model=ChangeOut)
async def approve_change(change_id: str, body: NoteIn, background: BackgroundTasks, admin: User = Depends(_manage),
                         db: AsyncSession = Depends(get_db)):
    change = await _pending_change(db, change_id)
    await portal.approve_change(db, change, admin, (body.note or "").strip() or None)
    await portal_mail.change_decided(db, change)
    await db.commit()
    background.add_task(mailer.send_pending_quietly)
    await db.refresh(change)
    return (await _change_outs(db, [change]))[0]


@router.post("/changes/{change_id}/reject", response_model=ChangeOut)
async def reject_change(change_id: str, body: NoteIn, background: BackgroundTasks, admin: User = Depends(_manage),
                        db: AsyncSession = Depends(get_db)):
    """The old value simply stays. A refused private address isn't kept."""
    change = await _pending_change(db, change_id)
    change.status, change.reviewed_by_user_id, change.reviewed_at = "rejected", admin.id, portal.now()
    change.note = (body.note or "").strip() or None
    change.private_address = None
    portal.log(db, action="change.reject", actor=admin, actor_kind="reviewer", service_id=change.service_id,
               change_request_id=change.id, after={"fields": sorted(change.changes)}, note=change.note)
    await portal_mail.change_decided(db, change)
    await db.commit()
    background.add_task(mailer.send_pending_quietly)
    await db.refresh(change)
    return (await _change_outs(db, [change]))[0]


# ---- a listing's history, revert, members ----------------------------------------------


@router.get("/services/{service_id}/log", response_model=list[LogOut])
async def service_log(service_id: str, _: User = Depends(_view), db: AsyncSession = Depends(get_db)):
    entries = (
        await db.execute(
            select(ResourceChangeLog).where(ResourceChangeLog.service_id == service_id).order_by(ResourceChangeLog.created_at.desc())
        )
    ).scalars().all()
    return await _log_outs(db, list(entries))


@router.post("/log/{log_id}/revert", response_model=LogOut)
async def revert(log_id: str, admin: User = Depends(_manage), db: AsyncSession = Depends(get_db)):
    entry = await db.get(ResourceChangeLog, log_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Change not found")
    if entry.action not in portal.REVERTIBLE or entry.reverted_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This change can't be reverted")
    try:
        new_entry = await portal.revert(db, entry, admin)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    await db.commit()
    await db.refresh(new_entry)
    return (await _log_outs(db, [new_entry]))[0]


@router.get("/services/{service_id}/members", response_model=list[MemberOut])
async def members(service_id: str, _: User = Depends(_view), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(ProviderMembership).where(ProviderMembership.service_id == service_id))).scalars().all()
    emails = await _emails(db, {m.user_id for m in rows})
    return [MemberOut(id=m.id, email=emails.get(m.user_id), role=m.role, verified_at=m.verified_at, created_at=m.created_at) for m in rows]


@router.post("/services/{service_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
async def add_member(service_id: str, body: MemberIn, admin: User = Depends(_manage), db: AsyncSession = Depends(get_db)):
    """Give an existing account access to a listing - unverified until a
    reviewer has called the listing's number."""
    if await db.get(ResourceService, service_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    user = (await db.execute(select(User).where(func.lower(User.email) == body.email.strip().lower()))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No account with that email - ask them to sign up first")
    existing = (
        await db.execute(select(ProviderMembership).where(ProviderMembership.user_id == user.id, ProviderMembership.service_id == service_id))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "They already manage this listing")
    row = await db.get(ResourceService, service_id)
    m = ProviderMembership(user_id=user.id, service_id=service_id, organization_id=row.organization_id, role=body.role)
    db.add(m)
    await db.flush()
    portal.log(db, action="member.add", actor=admin, actor_kind="reviewer", service_id=service_id, after={"role": body.role})
    await db.commit()
    await db.refresh(m)
    return MemberOut(id=m.id, email=user.email, role=m.role, verified_at=m.verified_at, created_at=m.created_at)


@router.post("/memberships/{membership_id}/verify", response_model=MemberOut)
async def verify_member(membership_id: str, admin: User = Depends(_manage), db: AsyncSession = Depends(get_db)):
    """v1 verification: the reviewer called the listing's own number and
    the person answering confirmed this account is theirs."""
    m = await db.get(ProviderMembership, membership_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Membership not found")
    m.verified_at, m.verified_by_user_id = portal.now(), admin.id
    portal.log(db, action="member.verify", actor=admin, actor_kind="reviewer", service_id=m.service_id, after={"verified": True})
    await db.commit()
    email = (await _emails(db, {m.user_id})).get(m.user_id)
    return MemberOut(id=m.id, email=email, role=m.role, verified_at=m.verified_at, created_at=m.created_at)


@router.get("/services/{service_id}/private-address")
async def private_address(service_id: str, _: User = Depends(_manage), db: AsyncSession = Depends(get_db)) -> dict:
    if not _reveal_private.get():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Confidential addresses are shown only in a reviewer's browser session")
    row = await db.get(ResourcePrivateAddress, service_id)
    return {"kind": row.kind if row else None, "address": row.address if row else None}
