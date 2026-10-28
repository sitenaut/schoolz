"""Neighborz review (docs/NEIGHBORZ_DESIGN.md, "Review"): bills a check held,
payments a requester says never arrived, and givers whose holding is paused.

`bills.manage` shows bill images, which carry a name and address, so it is
browser-only: an API key is refused even when it holds the permission.
Every decision, unpause and image view is in the audit log (AUDITED).
"""
from __future__ import annotations

import base64
import json
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import is_api_key_request, require_permission
from bills import catalog, flow
from database import get_db
from models import BillGiver, BillHold, BillRequest, User
from request_context import CodedHTTPException

router = APIRouter(prefix="/admin/bills", tags=["admin-bills"])


async def reviewer(request: Request, user: User = Depends(require_permission("bills.manage"))) -> User:
    if is_api_key_request(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "API keys can't review bills")
    return user


class HeldOut(BaseModel):
    id: str
    flags: list[str]
    flag_text: list[str]
    # What was read off the bill, beside what the requester posted.
    read: dict
    account_number: str | None
    service_zip: str | None
    county: str | None
    amount_cents: int | None
    amount_due_cents: int | None
    due_date: date | None
    shutoff_notice: bool
    posted_at: datetime | None
    has_image: bool
    requester_disputes: int


class DisputeOut(BaseModel):
    bill_id: str
    hold_id: str
    amount_cents: int | None
    paid_cents: int | None
    paid_on: date | None
    confirmation_number: str | None
    reported_at: datetime | None
    disputed_at: datetime | None
    giver_strikes: int
    giver_reveals_90d: int
    requester_disputes: int


class PausedOut(BaseModel):
    # Not a name: the reviewer decides on the giver's history alone.
    giver_id: str
    strikes: int


class QueueOut(BaseModel):
    held: list[HeldOut]
    disputed: list[DisputeOut]
    paused: list[PausedOut]


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "relist", "close_paid"]
    reason: str | None = None


_READ_FIELDS = ("company", "account_number", "service_zip", "amount_due", "due_date", "statement_date", "shutoff_notice", "residential")


@router.get("", response_model=QueueOut)
async def review_queue(user: User = Depends(reviewer), db: AsyncSession = Depends(get_db)):
    at = flow.now()
    await flow.settle(db, at)
    held = (await db.execute(select(BillRequest).where(BillRequest.status == "held").order_by(BillRequest.posted_at))).scalars().all()
    held_out = []
    for r in held:
        try:
            read = json.loads(r.extraction) if r.extraction else {}
        except ValueError:
            read = {}
        held_out.append(HeldOut(
            id=r.id, flags=list(r.flags or []), flag_text=[catalog.FLAGS.get(f, f) for f in r.flags or []],
            read={k: read.get(k) for k in _READ_FIELDS}, account_number=r.account_number, service_zip=r.service_zip,
            county=r.county, amount_cents=r.amount_cents, amount_due_cents=r.amount_due_cents, due_date=r.due_date,
            shutoff_notice=r.shutoff_notice, posted_at=r.posted_at, has_image=r.image is not None,
            requester_disputes=await flow.recent_disputes(db, r.requester_id, at) if r.requester_id else 0,
        ))

    disputed = (
        await db.execute(
            select(BillHold, BillRequest).join(BillRequest, BillRequest.id == BillHold.request_id)
            .where(BillHold.status == "disputed").order_by(BillHold.disputed_at)
        )
    ).all()
    disputed_out = []
    for h, r in disputed:
        reveals = 0
        if h.giver_id:
            reveals = (
                await db.execute(
                    select(func.count()).select_from(BillHold).where(
                        BillHold.giver_id == h.giver_id, BillHold.revealed_at >= at - catalog.STRIKE_WINDOW
                    )
                )
            ).scalar_one()
        disputed_out.append(DisputeOut(
            bill_id=r.id, hold_id=h.id, amount_cents=r.amount_cents, paid_cents=h.paid_cents, paid_on=h.paid_on,
            confirmation_number=h.confirmation_number, reported_at=h.reported_at, disputed_at=h.disputed_at,
            giver_strikes=await flow.strikes(db, h.giver_id, at) if h.giver_id else 0, giver_reveals_90d=reveals,
            requester_disputes=await flow.recent_disputes(db, r.requester_id, at) if r.requester_id else 0,
        ))

    candidates = (
        await db.execute(
            select(BillHold.giver_id).where(
                BillHold.giver_id.is_not(None), BillHold.status.in_(flow.STRIKES), BillHold.settled_at >= at - catalog.STRIKE_WINDOW
            ).group_by(BillHold.giver_id).having(func.count() >= catalog.STRIKES_TO_PAUSE)
        )
    ).scalars().all()
    paused = []
    for giver_id in candidates:
        n = await flow.strikes(db, giver_id, at)
        if n >= catalog.STRIKES_TO_PAUSE:
            paused.append(PausedOut(giver_id=giver_id, strikes=n))
    return QueueOut(held=held_out, disputed=disputed_out, paused=paused)


@router.get("/{bill_id}/image")
async def bill_image(bill_id: str, user: User = Depends(reviewer), db: AsyncSession = Depends(get_db)):
    req = await db.get(BillRequest, bill_id)
    if req is None or req.status != "held" or not req.image or req.image_type not in ("application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return Response(
        content=base64.b64decode(req.image),
        media_type=req.image_type,
        headers={"Content-Disposition": "inline", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/{bill_id}/decision")
async def decide(bill_id: str, body: DecisionIn, user: User = Depends(reviewer), db: AsyncSession = Depends(get_db)):
    at = flow.now()
    await flow.settle(db, at)
    req = (await db.execute(select(BillRequest).where(BillRequest.id == bill_id).with_for_update())).scalar_one_or_none()
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if req.status == "held" and body.decision in ("approve", "reject"):
        if body.decision == "approve":
            req.status = "available"
            req.posted_at = at  # the 30-day listing clock starts when it's listed
        else:
            if body.reason not in catalog.REJECT_REASONS:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Pick a reason")
            req.status = "rejected"
            req.reject_reason = body.reason
            req.closed_at = at
            await flow.notify(db, req.requester_id, "bills.rejected", req.id)
        req.image = None
        req.image_type = None
    elif req.status == "disputed" and body.decision in ("relist", "close_paid"):
        hold = (await db.execute(select(BillHold).where(BillHold.request_id == req.id, BillHold.status == "disputed"))).scalar_one()
        hold.settled_at = at
        if body.decision == "relist":
            hold.status = "struck"
            req.status = "available"
            req.posted_at = at
        else:
            hold.status = "confirmed"
            req.status = "paid"
            req.closed_at = at
    else:
        raise CodedHTTPException(status.HTTP_409_CONFLICT, "That decision doesn't fit this bill now", "wrong_state")
    await db.commit()
    return {"status": req.status}


@router.post("/givers/{user_id}/unpause")
async def unpause_giver(user_id: str, user: User = Depends(reviewer), db: AsyncSession = Depends(get_db)):
    """Strikes so far stop counting; new ones count again."""
    if await db.get(User, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    row = await db.get(BillGiver, user_id)
    if row is None:
        db.add(BillGiver(user_id=user_id, strikes_cleared_at=flow.now()))
    else:
        row.strikes_cleared_at = flow.now()
    await db.commit()
    return {"strikes": 0}
