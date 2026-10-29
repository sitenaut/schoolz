"""The rules a bill and a hold move by (docs/NEIGHBORZ_DESIGN.md, "States"
and "Limits"): timers, strikes, the per-account limits, the email nudges,
and what account deletion leaves behind.

`settle()` applies every timer. It runs at the top of each request that
acts on a bill and hourly from the bills.sweep job, so a hold past its 24
hours is released the moment anyone looks, and is made permanent within the
hour even if nobody does. Each step is an UPDATE ... RETURNING guarded by
the row's current status, so two settles at once never act on a row twice.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import crypto
from bills import catalog
from models import BillGiver, BillHold, BillRequest, User
from services import mailer
from services.app_help import SITE

OPEN = ("held", "available", "claimed", "reported", "disputed")
CLOSED = ("paid", "withdrawn", "rejected", "expired")
LIVE_HOLD = ("active", "reported", "disputed")
STRIKES = ("expired", "struck")

# Every Neighborz email says only this: a shared inbox or a lock screen
# learns nothing about bills, amounts, or who is helping whom.
SUBJECT = "An update on schoolz"
BODY = f"Something on your schoolz account needs a look. Sign in to see it:\n{SITE}/\n\n- schoolz"


def now() -> datetime:
    return datetime.now(UTC)


def fingerprint(utility: str, account_number: str) -> str | None:
    """A keyed HMAC of the account, so the limits can still match a bill
    after its account number is erased. None without an encryption key."""
    key = crypto.derived_key("bill_account_fingerprint")
    if key is None:
        return None
    return hmac.new(key, f"{utility}:{account_number}".encode(), hashlib.sha256).hexdigest()


async def notify(db: AsyncSession, user_id: str | None, kind: str, ref: str) -> None:
    if not user_id:
        return
    to = (await db.execute(select(User.email).where(User.id == user_id))).scalar_one_or_none()
    if to:
        mailer.queue(db, kind=kind, to=to, subject=SUBJECT, body=BODY, user_id=user_id, ref=ref)


def erase(req: BillRequest, at: datetime) -> None:
    """Drop what identifies the account; the fingerprint stays for the limits."""
    req.account_number = None
    req.service_zip = None
    req.extraction = None
    req.image = None
    req.image_type = None
    req.erased_at = at


async def settle(db: AsyncSession, at: datetime | None = None) -> dict:
    """Apply every timer that has run out. Commits."""
    at = at or now()
    done: dict[str, int] = {}

    # Holds past their 24 hours: a strike, and the bill goes back on the list.
    expired = (
        await db.execute(
            update(BillHold).where(BillHold.status == "active", BillHold.expires_at <= at)
            .values(status="expired", settled_at=at).returning(BillHold.request_id)
        )
    ).scalars().all()
    if expired:
        await db.execute(update(BillRequest).where(BillRequest.id.in_(expired), BillRequest.status == "claimed").values(status="available"))
    done["holds_expired"] = len(expired)

    # "I paid it" with no answer for 7 days: paid on the giver's word.
    unanswered = (
        await db.execute(
            update(BillHold).where(BillHold.status == "reported", BillHold.reported_at <= at - catalog.ANSWER_WAIT)
            .values(status="confirmed", settled_at=at).returning(BillHold.request_id)
        )
    ).scalars().all()
    if unanswered:
        await db.execute(
            update(BillRequest).where(BillRequest.id.in_(unanswered), BillRequest.status == "reported").values(status="paid", closed_at=at)
        )
    done["auto_confirmed"] = len(unanswered)

    # Drafts never posted: gone, image and all.
    drafts = await db.execute(delete(BillRequest).where(BillRequest.status == "draft", BillRequest.created_at <= at - catalog.DRAFT_LIFE))
    done["drafts_deleted"] = drafts.rowcount or 0

    # Held bills nobody reviewed in 7 days.
    stale_held = (
        await db.execute(
            update(BillRequest).where(BillRequest.status == "held", BillRequest.posted_at <= at - catalog.REVIEW_WAIT)
            .values(status="rejected", reject_reason="unreadable", closed_at=at, image=None, image_type=None)
            .returning(BillRequest.id, BillRequest.requester_id)
        )
    ).all()
    for req_id, requester_id in stale_held:
        await notify(db, requester_id, "bills.rejected", req_id)
    done["held_rejected"] = len(stale_held)

    # Listings nobody took in 30 days.
    old = (
        await db.execute(
            update(BillRequest).where(BillRequest.status == "available", BillRequest.posted_at <= at - catalog.LISTING_LIFE)
            .values(status="expired", closed_at=at).returning(BillRequest.id, BillRequest.requester_id)
        )
    ).all()
    for req_id, requester_id in old:
        await notify(db, requester_id, "bills.expired", req_id)
    done["listings_expired"] = len(old)

    # Closed for 30 days: erase the account number, ZIP, extraction, image
    # (an UPDATE, so nothing is decrypted to be thrown away).
    erased = await db.execute(
        update(BillRequest).where(
            BillRequest.status.in_(CLOSED), BillRequest.erased_at.is_(None), BillRequest.closed_at <= at - catalog.ERASE_AFTER
        ).values(account_number=None, service_zip=None, extraction=None, image=None, image_type=None, erased_at=at)
    )
    done["erased"] = erased.rowcount or 0

    await db.commit()
    return done


async def warn_ending_holds(db: AsyncSession, at: datetime | None = None) -> int:
    """One "your hold ends soon" email per hold. Commits."""
    at = at or now()
    rows = (
        await db.execute(
            update(BillHold).where(
                BillHold.status == "active", BillHold.warned_at.is_(None), BillHold.expires_at <= at + catalog.HOLD_WARNING,
                BillHold.expires_at > at,
            ).values(warned_at=at).returning(BillHold.id, BillHold.giver_id)
        )
    ).all()
    for hold_id, giver_id in rows:
        await notify(db, giver_id, "bills.hold_ending", hold_id)
    await db.commit()
    return len(rows)


async def strikes(db: AsyncSession, user_id: str, at: datetime | None = None) -> int:
    at = at or now()
    cleared = (await db.execute(select(BillGiver.strikes_cleared_at).where(BillGiver.user_id == user_id))).scalar_one_or_none()
    since = max(at - catalog.STRIKE_WINDOW, cleared) if cleared else at - catalog.STRIKE_WINDOW
    return (
        await db.execute(
            select(func.count()).select_from(BillHold).where(
                BillHold.giver_id == user_id, BillHold.status.in_(STRIKES), BillHold.settled_at >= since
            )
        )
    ).scalar_one()


async def hold_blocker(db: AsyncSession, user: User, at: datetime | None = None) -> str | None:
    """Why this person can't hold a bill right now, or None."""
    at = at or now()
    created = user.created_at if user.created_at.tzinfo else user.created_at.replace(tzinfo=UTC)
    if created > at - catalog.GIVER_MIN_AGE:
        return "account_too_new"
    if await strikes(db, user.id, at) >= catalog.STRIKES_TO_PAUSE:
        return "paused"
    holding = (
        await db.execute(select(BillHold.id).where(BillHold.giver_id == user.id, BillHold.status == "active").limit(1))
    ).scalar_one_or_none()
    if holding:
        return "holding_one"
    today = (
        await db.execute(
            select(func.count()).select_from(BillHold).where(BillHold.giver_id == user.id, BillHold.held_at > at - timedelta(hours=24))
        )
    ).scalar_one()
    if today >= catalog.HOLDS_PER_DAY:
        return "too_many_holds"
    return None


async def own_fingerprints(db: AsyncSession, user_id: str) -> set[str]:
    rows = (
        await db.execute(
            select(BillRequest.account_fingerprint).where(BillRequest.requester_id == user_id, BillRequest.account_fingerprint.is_not(None))
        )
    ).scalars().all()
    return set(rows)


async def account_blocker(db: AsyncSession, fp: str, exclude_id: str, at: datetime | None = None) -> str | None:
    """Per utility account, across every user: one open listing, and one
    paid listing per 60 days."""
    at = at or now()
    row = (
        await db.execute(
            select(BillRequest.status).where(
                BillRequest.account_fingerprint == fp,
                BillRequest.id != exclude_id,
                or_(
                    BillRequest.status.in_(OPEN),
                    and_(BillRequest.status == "paid", BillRequest.closed_at >= at - catalog.ACCOUNT_REPEAT),
                ),
            ).limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return "account_recently_paid" if row == "paid" else "account_listed"


async def recent_disputes(db: AsyncSession, requester_id: str, at: datetime | None = None) -> int:
    at = at or now()
    return (
        await db.execute(
            select(func.count()).select_from(BillHold).join(BillRequest, BillRequest.id == BillHold.request_id).where(
                BillRequest.requester_id == requester_id, BillHold.disputed_at >= at - catalog.STRIKE_WINDOW
            )
        )
    ).scalar_one()


async def notify_requester_reported(db: AsyncSession, req: BillRequest) -> None:
    await notify(db, req.requester_id, "bills.reported", req.id)


async def withdraw(db: AsyncSession, req: BillRequest, at: datetime | None = None) -> None:
    """Take a bill down. A giver holding it is told it isn't needed (no
    strike). No commit."""
    at = at or now()
    hold = (
        await db.execute(select(BillHold).where(BillHold.request_id == req.id, BillHold.status == "active"))
    ).scalar_one_or_none()
    if hold is not None:
        hold.status = "withdrawn"
        hold.settled_at = at
        await notify(db, hold.giver_id, "bills.withdrawn", hold.id)
    req.status = "withdrawn"
    req.closed_at = at
    req.image = None
    req.image_type = None


async def delete_user_data(db: AsyncSession, user_id: str) -> None:
    """Account deletion. A bill a giver has paid (or says they paid) stays,
    closed as paid, unlinked and erased, so the giver keeps the line in
    their own history; every other bill is deleted (a giver holding one is
    told it isn't needed). As a giver: an active hold is let go, and the
    rest lose the giver and the confirmation number. No commit."""
    at = now()
    mine = (await db.execute(select(BillRequest).where(BillRequest.requester_id == user_id))).scalars().all()
    for req in mine:
        if req.status in ("paid", "reported", "disputed"):
            if req.status != "paid":
                await db.execute(
                    update(BillHold).where(BillHold.request_id == req.id, BillHold.status.in_(("reported", "disputed")))
                    .values(status="confirmed", settled_at=at)
                )
                req.status = "paid"
                req.closed_at = at
            req.requester_id = None
            erase(req, at)
            continue
        if req.status == "claimed":
            await withdraw(db, req, at)
        await db.delete(req)

    held = (
        await db.execute(update(BillHold).where(BillHold.giver_id == user_id, BillHold.status == "active")
                         .values(status="released", settled_at=at).returning(BillHold.request_id))
    ).scalars().all()
    if held:
        await db.execute(update(BillRequest).where(BillRequest.id.in_(held), BillRequest.status == "claimed").values(status="available"))
    await db.execute(update(BillHold).where(BillHold.giver_id == user_id).values(giver_id=None, confirmation_number=None))
    await db.execute(delete(BillGiver).where(BillGiver.user_id == user_id))
