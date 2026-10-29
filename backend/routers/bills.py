"""Neighborz (docs/NEIGHBORZ_DESIGN.md): the public list of bills, posting a
bill, and holding and paying one.

We never touch money: a giver pays the utility on its own site and reports
the confirmation number here. Paths say `bills` and nothing about need, and
no request or log line carries an account number (they travel only in
bodies, which the request log never records). API keys are refused on every
route here by `get_current_user` (none has an admin gate).
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import crypto
from auth import get_current_user
from bills import catalog, flow, reader
from database import get_db
from models import BillHold, BillRequest, User
from request_context import CodedHTTPException
from resources.places import zip_county
from services import audit
from services.upload_guard import sniff_file_type

router = APIRouter(prefix="/bills", tags=["bills"])

_TZ = ZoneInfo("America/New_York")
_READABLE = {"application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp", "image/heic"}


def _today() -> date:
    return datetime.now(_TZ).date()


def _need_encryption() -> None:
    if not crypto.can_encrypt():
        raise CodedHTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Neighborz isn't available here", "encryption_unavailable")


def _utility_name(key: str | None) -> str | None:
    u = catalog.BY_KEY.get(key or "")
    return u.name if u else None


# ---------------------------------------------------------------- public


class UtilityOut(BaseModel):
    key: str
    name: str


class CatalogOut(BaseModel):
    utilities: list[UtilityOut]
    avatars: list[str]
    emojis: dict[str, str]
    min_ask_cents: int
    max_ask_cents: int
    hold_hours: int


class PublicBill(BaseModel):
    id: str
    utility: str
    utility_name: str | None
    amount_cents: int
    due_date: date | None
    shutoff_notice: bool
    county: str | None
    avatar: str | None
    state: Literal["open", "being_paid", "paid"]


@router.get("/catalog", response_model=CatalogOut)
async def get_catalog():
    return CatalogOut(
        utilities=[UtilityOut(key=u.key, name=u.name) for u in catalog.UTILITIES],
        avatars=list(catalog.AVATARS),
        emojis=catalog.EMOJIS,
        min_ask_cents=catalog.MIN_ASK_CENTS,
        max_ask_cents=catalog.MAX_ASK_CENTS,
        hold_hours=int(catalog.HOLD.total_seconds() // 3600),
    )


@router.get("", response_model=list[PublicBill])
async def list_bills(county: str | None = None, utility: str | None = None, db: AsyncSession = Depends(get_db)):
    """Public: what's waiting to be paid, then what's being paid, then what
    was paid in the last week. Nothing here says who."""
    at = flow.now()
    await flow.settle(db, at)
    state = case(
        (BillRequest.status == "available", 0),
        (BillRequest.status.in_(("claimed", "reported", "disputed")), 1),
        else_=2,
    )
    # Only the listing's own columns: a public request never decrypts anything.
    q = select(
        BillRequest.id, BillRequest.utility, BillRequest.status, BillRequest.amount_cents, BillRequest.due_date,
        BillRequest.shutoff_notice, BillRequest.county, BillRequest.avatar,
    ).where(
        or_(
            BillRequest.status.in_(("available", "claimed", "reported", "disputed")),
            and_(BillRequest.status == "paid", BillRequest.closed_at >= at - catalog.PAID_SHOWN),
        ),
        BillRequest.amount_cents.is_not(None),
    )
    if county:
        q = q.where(func.lower(BillRequest.county) == county.strip().lower()[:40])
    if utility:
        q = q.where(BillRequest.utility == utility[:20])
    q = q.order_by(state, BillRequest.shutoff_notice.desc(), BillRequest.due_date.asc().nulls_last(), BillRequest.posted_at.asc()).limit(300)
    rows = (await db.execute(q)).all()
    names = {"available": "open", "paid": "paid"}
    return [
        PublicBill(
            id=r.id, utility=r.utility, utility_name=_utility_name(r.utility), amount_cents=r.amount_cents, due_date=r.due_date,
            shutoff_notice=r.shutoff_notice, county=r.county, avatar=r.avatar, state=names.get(r.status, "being_paid"),
        )
        for r in rows
    ]


# ------------------------------------------------------------ requester


class DraftOut(BaseModel):
    id: str
    # Set when this upload can't be posted: not_a_bill | utility_not_supported.
    refused: str | None
    utility: str | None
    utility_name: str | None
    account_number: str | None
    service_zip: str | None
    amount_due_cents: int | None
    max_ask_cents: int
    due_date: date | None
    shutoff_notice: bool
    flags: list[str]


class PostIn(BaseModel):
    account_number: str = Field(max_length=40)
    service_zip: str = Field(max_length=10)
    amount_cents: int
    avatar: str = Field(max_length=30)
    # "The person who pays will see your account number and ZIP code."
    understood: bool


class PostedOut(BaseModel):
    id: str
    status: str
    utility_name: str | None
    amount_cents: int | None
    due_date: date | None
    shutoff_notice: bool
    county: str | None
    avatar: str | None
    thanks: str | None
    reject_reason: str | None
    posted_at: datetime | None
    closed_at: datetime | None
    can_withdraw: bool
    can_answer: bool
    can_thank: bool


class AnswerIn(BaseModel):
    answer: Literal["paid", "not_yet"]


class ThanksIn(BaseModel):
    emoji: str = Field(max_length=20)


def _max_ask(amount_due_cents: int | None) -> int:
    return min(amount_due_cents, catalog.MAX_ASK_CENTS) if amount_due_cents else catalog.MAX_ASK_CENTS


def _draft_out(req: BillRequest) -> DraftOut:
    return DraftOut(
        id=req.id, refused=req.refused, utility=None if req.refused else req.utility, utility_name=_utility_name(req.utility),
        account_number=req.account_number, service_zip=req.service_zip, amount_due_cents=req.amount_due_cents,
        max_ask_cents=_max_ask(req.amount_due_cents), due_date=req.due_date, shutoff_notice=req.shutoff_notice, flags=list(req.flags or []),
    )


def _posted_out(req: BillRequest) -> PostedOut:
    return PostedOut(
        id=req.id, status=req.status, utility_name=_utility_name(req.utility), amount_cents=req.amount_cents, due_date=req.due_date,
        shutoff_notice=req.shutoff_notice, county=req.county, avatar=req.avatar, thanks=req.thanks, reject_reason=req.reject_reason,
        posted_at=req.posted_at, closed_at=req.closed_at,
        can_withdraw=req.status in ("held", "available", "claimed"),
        can_answer=req.status == "reported",
        can_thank=req.status == "paid" and req.thanks is None,
    )


async def _open_listing(db: AsyncSession, user_id: str) -> bool:
    found = await db.execute(select(BillRequest.id).where(BillRequest.requester_id == user_id, BillRequest.status.in_(flow.OPEN)).limit(1))
    return found.scalar_one_or_none() is not None


async def _own_request(db: AsyncSession, user: User, bill_id: str, *, lock: bool = False) -> BillRequest:
    q = select(BillRequest).where(BillRequest.id == bill_id, BillRequest.requester_id == user.id)
    if lock:
        q = q.with_for_update()
    req = (await db.execute(q)).scalar_one_or_none()
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return req


@router.post("/upload", response_model=DraftOut)
async def upload_bill(file: UploadFile = File(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Read an uploaded bill into a draft the requester checks before
    posting. The same file uploaded again reuses the first read."""
    _need_encryption()
    data = await file.read(catalog.MAX_UPLOAD_BYTES + 1)
    if len(data) > catalog.MAX_UPLOAD_BYTES:
        raise CodedHTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "That file is too big", "file_too_big")
    if sniff_file_type(data) not in _READABLE:
        raise CodedHTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload a photo or a PDF of the bill", "unsupported_file")
    at = flow.now()
    await flow.settle(db, at)
    if await _open_listing(db, user.id):
        raise CodedHTTPException(status.HTTP_409_CONFLICT, "You already have a bill posted", "open_listing")

    sha = hashlib.sha256(data).hexdigest()
    again = (
        await db.execute(
            select(BillRequest).where(BillRequest.requester_id == user.id, BillRequest.status == "draft", BillRequest.image_sha256 == sha)
        )
    ).scalar_one_or_none()
    if again is not None:
        return _draft_out(again)

    uploads = (
        await db.execute(
            select(func.count()).select_from(BillRequest).where(BillRequest.requester_id == user.id, BillRequest.created_at >= at - catalog.DRAFT_LIFE)
        )
    ).scalar_one()
    if uploads >= catalog.UPLOADS_PER_DAY:
        raise CodedHTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "That's a lot of uploads today. Try again tomorrow", "too_many_uploads")

    try:
        raw = await reader.read_bill(data)
    except reader.ReadError as exc:
        raise CodedHTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc), "unreadable") from None
    cleaned = reader.clean(raw, _today())

    # A new upload replaces any earlier draft. Kept as withdrawn (image
    # gone) rather than deleted, so it still counts toward today's uploads.
    await db.execute(
        update(BillRequest).where(BillRequest.requester_id == user.id, BillRequest.status == "draft")
        .values(status="withdrawn", closed_at=at, image=None, image_type=None)
    )
    req = BillRequest(requester_id=user.id, status="draft", image_sha256=sha, created_at=at, flags=[])
    if cleaned["refused"]:
        req.utility = cleaned["utility"] or "other"
        req.refused = cleaned["refused"]
    else:
        stored = reader.stored_image(data)
        req.utility = cleaned["utility"]
        req.account_number = cleaned["account_number"]
        req.service_zip = cleaned["service_zip"]
        req.amount_due_cents = cleaned["amount_due_cents"]
        req.due_date = cleaned["due_date"]
        req.shutoff_notice = cleaned["shutoff_notice"]
        req.county = zip_county(cleaned["service_zip"])
        req.flags = cleaned["flags"]
        req.extraction = json.dumps(raw)
        if stored is not None:
            req.image = base64.b64encode(stored[0]).decode("ascii")
            req.image_type = stored[1]
    db.add(req)
    await db.commit()
    return _draft_out(req)


@router.post("/{bill_id}/post", response_model=PostedOut)
async def post_bill(bill_id: str, body: PostIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Post a checked draft: on the list now, or held for a reviewer when a
    check in code flags it."""
    _need_encryption()
    at = flow.now()
    await flow.settle(db, at)
    req = await _own_request(db, user, bill_id, lock=True)
    if req.status != "draft" or req.refused:
        raise CodedHTTPException(status.HTTP_409_CONFLICT, "This bill can't be posted", "not_a_draft")
    if not body.understood:
        raise CodedHTTPException(status.HTTP_400_BAD_REQUEST, "Tick the box to say you understand who sees what", "not_understood")
    if body.avatar not in catalog.AVATARS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Pick an avatar from the list")
    if not catalog.MIN_ASK_CENTS <= body.amount_cents <= _max_ask(req.amount_due_cents):
        raise CodedHTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "That amount isn't allowed", "amount_not_allowed")
    utility = catalog.BY_KEY[req.utility]
    account = reader.digits(body.account_number)
    zip_code = reader.digits(body.service_zip)
    if not reader.account_ok(utility, account):
        raise CodedHTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Check the account number", "account_number_invalid")
    if len(zip_code) != 5:
        raise CodedHTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Check the ZIP code", "zip_invalid")
    if await _open_listing(db, user.id):
        raise CodedHTTPException(status.HTTP_409_CONFLICT, "You already have a bill posted", "open_listing")

    fp = flow.fingerprint(req.utility, account)
    blocked = await flow.account_blocker(db, fp, req.id, at)
    if blocked:
        text = "This account already has a bill posted" if blocked == "account_listed" else "This account had a bill paid recently"
        raise CodedHTTPException(status.HTTP_409_CONFLICT, text, blocked)

    flags = [f for f in (req.flags or []) if f not in ("account_unreadable", "zip_not_nj", "edited_account", "repeat_disputes")]
    if account != (req.account_number or "") or zip_code != (req.service_zip or ""):
        # Models misread digits, so a correction is allowed - but a wrong
        # digit sends a stranger's money to the wrong account, so a person
        # checks it against the bill first.
        flags.append("edited_account")
    if zip_county(zip_code) is None:
        flags.append("zip_not_nj")
    if await flow.recent_disputes(db, user.id, at) >= catalog.DISPUTES_TO_HOLD:
        flags.append("repeat_disputes")

    req.account_number = account
    req.service_zip = zip_code
    req.county = zip_county(zip_code)
    req.account_fingerprint = fp
    req.amount_cents = body.amount_cents
    req.avatar = body.avatar
    req.flags = flags
    req.posted_at = at
    if flags:
        req.status = "held"
    else:
        req.status = "available"
        req.image = None
        req.image_type = None
    await db.commit()
    return _posted_out(req)


@router.delete("/{bill_id}", response_model=PostedOut)
async def withdraw_bill(bill_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await flow.settle(db)
    req = await _own_request(db, user, bill_id, lock=True)
    if req.status not in ("draft", "held", "available", "claimed"):
        raise CodedHTTPException(status.HTTP_409_CONFLICT, "This bill can't be taken down now", "cant_withdraw")
    await flow.withdraw(db, req)
    await db.commit()
    return _posted_out(req)


@router.post("/{bill_id}/answer", response_model=PostedOut)
async def answer_bill(bill_id: str, body: AnswerIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The requester checked their utility account: did the payment arrive?"""
    at = flow.now()
    await flow.settle(db, at)
    req = await _own_request(db, user, bill_id, lock=True)
    if req.status != "reported":
        raise CodedHTTPException(status.HTTP_409_CONFLICT, "There's nothing to answer on this bill", "nothing_to_answer")
    hold = (await db.execute(select(BillHold).where(BillHold.request_id == req.id, BillHold.status == "reported"))).scalar_one()
    req.answered_at = at
    if body.answer == "paid":
        req.status = "paid"
        req.closed_at = at
        hold.status = "confirmed"
        hold.settled_at = at
    else:
        req.status = "disputed"
        hold.status = "disputed"
        hold.disputed_at = at
    await db.commit()
    return _posted_out(req)


@router.post("/{bill_id}/thanks", response_model=PostedOut)
async def thank_giver(bill_id: str, body: ThanksIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """One emoji from the fixed set, once. The only thing that reaches the giver."""
    if body.emoji not in catalog.EMOJIS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Pick one of the emojis")
    req = await _own_request(db, user, bill_id, lock=True)
    if req.status != "paid" or req.thanks is not None:
        raise CodedHTTPException(status.HTTP_409_CONFLICT, "You can't send a thank-you on this bill", "cant_thank")
    req.thanks = body.emoji
    await db.commit()
    return _posted_out(req)


# ----------------------------------------------------------------- giver


class HoldOut(BaseModel):
    id: str
    bill_id: str
    status: str
    held_at: datetime
    expires_at: datetime
    utility_name: str | None
    amount_cents: int | None
    due_date: date | None
    shutoff_notice: bool
    county: str | None
    avatar: str | None
    # Only while the hold is active, and only to its giver.
    account_number: str | None
    service_zip: str | None
    pay_url: str | None
    pay_phone: str | None
    paid_cents: int | None
    paid_on: date | None
    confirmation_number: str | None
    thanks: str | None


class PaidIn(BaseModel):
    confirmation_number: str = Field(pattern=r"^[A-Za-z0-9-]{4,30}$")
    paid_cents: int
    paid_on: date


def _hold_out(hold: BillHold, req: BillRequest) -> HoldOut:
    active = hold.status == "active"
    utility = catalog.BY_KEY.get(req.utility)
    return HoldOut(
        id=hold.id, bill_id=req.id, status=hold.status, held_at=hold.held_at, expires_at=hold.expires_at,
        utility_name=utility.name if utility else None, amount_cents=req.amount_cents, due_date=req.due_date,
        shutoff_notice=req.shutoff_notice, county=req.county, avatar=req.avatar,
        account_number=req.account_number if active else None, service_zip=req.service_zip if active else None,
        pay_url=utility.pay_url if utility else None, pay_phone=utility.pay_phone if utility else None,
        paid_cents=hold.paid_cents, paid_on=hold.paid_on, confirmation_number=hold.confirmation_number,
        thanks=req.thanks if req.status == "paid" else None,
    )


def _revealed(request: Request, hold: BillHold, at: datetime) -> None:
    if hold.revealed_at is None:
        hold.revealed_at = at
    audit.note(request, "bills.account_revealed", hold_id=hold.id, bill_id=hold.request_id)


async def _own_hold(db: AsyncSession, user: User, hold_id: str, *, lock: bool = False) -> tuple[BillHold, BillRequest]:
    q = select(BillHold, BillRequest).join(BillRequest, BillRequest.id == BillHold.request_id).where(
        BillHold.id == hold_id, BillHold.giver_id == user.id
    )
    if lock:
        q = q.with_for_update()
    row = (await db.execute(q)).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return row[0], row[1]


@router.post("/{bill_id}/hold", response_model=HoldOut)
async def hold_bill(bill_id: str, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """"I'll pay this": the bill is this giver's for 24 hours, and they see
    what the utility's guest payment needs."""
    _need_encryption()
    at = flow.now()
    await flow.settle(db, at)
    blocker = await flow.hold_blocker(db, user, at)
    if blocker:
        texts = {
            "account_too_new": "New accounts can hold a bill after a day",
            "paused": "Holding bills is paused on your account",
            "holding_one": "Finish or let go of the bill you're holding first",
            "too_many_holds": "You've held a few bills today. Try again tomorrow",
        }
        raise CodedHTTPException(status.HTTP_409_CONFLICT, texts[blocker], blocker)
    req = (await db.execute(select(BillRequest).where(BillRequest.id == bill_id).with_for_update())).scalar_one_or_none()
    if req is None or req.status not in ("available", "claimed", "reported", "disputed", "paid"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if req.requester_id == user.id or (req.account_fingerprint and req.account_fingerprint in await flow.own_fingerprints(db, user.id)):
        raise CodedHTTPException(status.HTTP_409_CONFLICT, "This is your own bill", "own_bill")
    if req.status != "available":
        raise CodedHTTPException(status.HTTP_409_CONFLICT, "Someone else is already paying this one", "not_available")
    hold = BillHold(request_id=req.id, giver_id=user.id, status="active", held_at=at, expires_at=at + catalog.HOLD, revealed_at=at)
    db.add(hold)
    req.status = "claimed"
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise CodedHTTPException(status.HTTP_409_CONFLICT, "Someone else is already paying this one", "not_available") from None
    _revealed(request, hold, at)
    return _hold_out(hold, req)


@router.get("/holds/{hold_id}", response_model=HoldOut)
async def get_hold(hold_id: str, request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    at = flow.now()
    await flow.settle(db, at)
    hold, req = await _own_hold(db, user, hold_id)
    if hold.status == "active":
        _revealed(request, hold, at)
        await db.commit()
    return _hold_out(hold, req)


@router.post("/holds/{hold_id}/paid", response_model=HoldOut)
async def report_paid(hold_id: str, body: PaidIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """"I paid it": the giver's confirmation number, kept for their own
    record and never shown to the requester."""
    at = flow.now()
    await flow.settle(db, at)
    hold, req = await _own_hold(db, user, hold_id, lock=True)
    if hold.status != "active":
        raise CodedHTTPException(status.HTTP_409_CONFLICT, "This hold has ended", "hold_ended")
    if body.paid_cents != req.amount_cents:
        raise CodedHTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter the amount the bill asked for", "amount_mismatch")
    # The date is the giver's own, whose day may start before or after New
    # Jersey's: a day of slack either way.
    held_on = hold.held_at.astimezone(_TZ).date()
    if not held_on - timedelta(days=1) <= body.paid_on <= _today() + timedelta(days=1):
        raise CodedHTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Check the date you paid", "paid_on_invalid")
    hold.status = "reported"
    hold.reported_at = at
    hold.paid_cents = body.paid_cents
    hold.paid_on = body.paid_on
    hold.confirmation_number = body.confirmation_number
    req.status = "reported"
    await flow.notify_requester_reported(db, req)
    await db.commit()
    return _hold_out(hold, req)


@router.post("/holds/{hold_id}/release", response_model=HoldOut)
async def release_hold(hold_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """"I can't pay this after all": back on the list, no strike."""
    at = flow.now()
    await flow.settle(db, at)
    hold, req = await _own_hold(db, user, hold_id, lock=True)
    if hold.status != "active":
        raise CodedHTTPException(status.HTTP_409_CONFLICT, "This hold has ended", "hold_ended")
    hold.status = "released"
    hold.settled_at = at
    if req.status == "claimed":
        req.status = "available"
    await db.commit()
    return _hold_out(hold, req)


# ------------------------------------------------------------------ both


class GiftOut(BaseModel):
    hold_id: str
    status: str
    utility_name: str | None
    amount_cents: int | None
    paid_cents: int | None
    paid_on: date | None
    confirmation_number: str | None
    avatar: str | None
    county: str | None
    thanks: str | None
    held_at: datetime
    expires_at: datetime


class MineOut(BaseModel):
    posted: list[PostedOut]
    gifts: list[GiftOut]
    # Why this person can't hold a bill right now, or None.
    hold_blocker: str | None


@router.get("/mine", response_model=MineOut)
async def mine(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Both sides on one page: bills I posted, and bills I've held or paid."""
    at = flow.now()
    await flow.settle(db, at)
    posted = (
        await db.execute(
            select(BillRequest).where(
                BillRequest.requester_id == user.id, BillRequest.status != "draft", BillRequest.posted_at.is_not(None)
            ).order_by(BillRequest.posted_at.desc()).limit(50)
        )
    ).scalars().all()
    gifts = (
        await db.execute(
            select(BillHold, BillRequest).join(BillRequest, BillRequest.id == BillHold.request_id).where(
                BillHold.giver_id == user.id, BillHold.status.in_(("active", "reported", "confirmed", "disputed", "struck"))
            ).order_by(BillHold.held_at.desc()).limit(200)
        )
    ).all()
    return MineOut(
        posted=[_posted_out(r) for r in posted],
        gifts=[
            GiftOut(
                hold_id=h.id, status=h.status, utility_name=_utility_name(r.utility), amount_cents=r.amount_cents,
                paid_cents=h.paid_cents, paid_on=h.paid_on, confirmation_number=h.confirmation_number, avatar=r.avatar,
                county=r.county, thanks=r.thanks if r.status == "paid" else None, held_at=h.held_at, expires_at=h.expires_at,
            )
            for h, r in gifts
        ],
        hold_blocker=await flow.hold_blocker(db, user, at),
    )
