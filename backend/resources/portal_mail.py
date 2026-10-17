"""The provider portal's emails: request decisions, held edits, sign-in-free
verification codes and the 90-day "Is this still right?" check. Every one
goes through services/mailer.py.

These go to providers about their own public listings, so they can name
the listing. Nothing here is ever about someone looking for help.
English for now, like the rest of the review side.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ProviderMembership, ResourceChangeRequest, ResourceOnboardingRequest, ResourceService, User
from services import mailer
from services.app_help import SITE

CODE_MINUTES = 15
CODE_ATTEMPTS = 5
CODES_PER_HOUR = 3

REJECT_TEXT = {
    "not_a_resource": "it isn't a service we list on Localz",
    "could_not_verify": "we couldn't confirm the details",
    "duplicate": "it's already listed",
    "outside_area": "it's outside the area Localz covers",
    "unsafe": "we can't list it",
    "other": "of the note below",
}

SIGN_OFF = "\n\n- Localz, from schoolz\nQuestions? Reply to this email or use " + f"{SITE}/contact"


async def _account_email(db: AsyncSession, user_id: str | None) -> str | None:
    if not user_id:
        return None
    user = await db.get(User, user_id)
    return user.email if user and user.email else None


async def _request_recipient(db: AsyncSession, req: ResourceOnboardingRequest) -> tuple[str | None, str | None]:
    email = await _account_email(db, req.user_id)
    return (email, req.user_id) if email else (req.contact_email, None)


def _name(req: ResourceOnboardingRequest) -> str:
    return ((req.submission or {}).get("organization_name") or "your listing").strip()


async def request_decided(db: AsyncSession, req: ResourceOnboardingRequest) -> None:
    """Approved, changes requested or not approved - whichever the request
    now is. Queued in the decision's own transaction."""
    to, user_id = await _request_recipient(db, req)
    if not to:
        return
    name = _name(req)
    note = f"\n\nFrom the reviewer: {req.decision_note}" if req.decision_note else ""
    portal = f"{SITE}/localz/providers/portal"
    if req.status == "approved":
        subject = f"{name} is on Localz"
        body = (
            f"Good news: {name} is now listed on Localz, where people in South Jersey look for help.{note}\n\n"
            f"Keep it right from your provider page - close for a day, post this week's hours, add a date:\n{portal}"
        )
    elif req.status == "changes_requested":
        subject = f"Localz: a few changes for {name}"
        body = f"Thanks for sending {name}. Before we can list it, a few things need changing.{note}\n\nOpen your request:\n{portal}"
    elif req.status == "rejected":
        why = REJECT_TEXT.get(req.reject_reason or "", "of the note below")
        subject = f"Localz: about {name}"
        body = f"Thanks for sending {name}. We can't list it, because {why}.{note}\n\nYour requests:\n{portal}"
    else:
        return
    mailer.queue(db, kind=f"portal.request_{req.status}", to=to, subject=subject, body=body + SIGN_OFF, user_id=user_id, ref=req.id)


async def change_decided(db: AsyncSession, change: ResourceChangeRequest) -> None:
    """A held edit was approved or not. Scraper conflicts have no person."""
    if change.kind != "provider_edit":
        return
    to = await _account_email(db, change.user_id)
    row = await db.get(ResourceService, change.service_id)
    if not to or row is None:
        return
    page = f"{SITE}/localz/providers/listings/{row.id}"
    note = f"\n\nFrom the reviewer: {change.note}" if change.note else ""
    if change.status == "approved":
        subject, body = f"Localz: your change to {row.name} is live", f"Your change to {row.name} is now on Localz.{note}"
    else:
        subject = f"Localz: your change to {row.name}"
        body = f"We didn't make your change to {row.name}; the listing stays as it was.{note}"
    mailer.queue(db, kind=f"portal.change_{change.status}", to=to, subject=subject, body=f"{body}\n\n{page}{SIGN_OFF}",
                 user_id=change.user_id, ref=change.id)


# ---- verify by email ------------------------------------------------------------------


def _code_hash(code: str) -> str:
    key = (os.getenv("JWT_SECRET") or "schoolz-localz").encode()
    return hmac.new(key, f"localz-verify:{code}".encode(), hashlib.sha256).hexdigest()


def mask(email: str) -> str:
    """"h***@maplepantry.org": enough to recognise, not enough to harvest."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


async def codes_sent_lately(db: AsyncSession, membership: ProviderMembership) -> int:
    from models import OutboundEmail

    since = mailer._now() - timedelta(hours=1)
    rows = await db.execute(
        select(OutboundEmail.id).where(OutboundEmail.kind == "portal.verify_code", OutboundEmail.ref == membership.id,
                                       OutboundEmail.created_at >= since)
    )
    return len(rows.all())


def send_code(db: AsyncSession, membership: ProviderMembership, row: ResourceService) -> None:
    """A 6-digit code to the address the source published for this listing.
    Only its hash is kept; it lasts 15 minutes and 5 tries."""
    code = f"{secrets.randbelow(10**6):06d}"
    membership.code_hash = _code_hash(code)
    membership.code_expires_at = mailer._now() + timedelta(minutes=CODE_MINUTES)
    membership.code_attempts = 0
    body = (
        f"Someone asked to manage the Localz listing \"{row.name}\" and gave this address as theirs.\n\n"
        f"Code: {code}\n\nIt works for {CODE_MINUTES} minutes. If that wasn't you or your organization, ignore this "
        "email - nothing changes."
    )
    mailer.queue(db, kind="portal.verify_code", to=membership.verify_email or "", subject=f"Your Localz code: {code}",
                 body=body + SIGN_OFF, user_id=membership.user_id, ref=membership.id,
                 expires_in=timedelta(minutes=CODE_MINUTES))


def check_code(membership: ProviderMembership, code: str) -> str | None:
    """None when it's right, else why not. Counts the try either way."""
    if not membership.code_hash or not membership.code_expires_at or membership.code_expires_at < mailer._now():
        return "That code has expired - ask for a new one."
    if membership.code_attempts >= CODE_ATTEMPTS:
        return "Too many tries - ask for a new code."
    membership.code_attempts += 1
    if not hmac.compare_digest(membership.code_hash, _code_hash(code.strip())):
        return "That code isn't right."
    membership.code_hash = membership.code_expires_at = None
    return None


# ---- "Is this still right?" ------------------------------------------------------------


def checkin(db: AsyncSession, to: str, user_id: str, listings: list[ResourceService]) -> None:
    """One email per person, every listing of theirs that's due."""
    def confirmed(r: ResourceService) -> str:
        return f"last confirmed {r.last_assured_on:%B %-d, %Y}" if r.last_assured_on else "not confirmed yet"

    lines = "\n".join(f"- {r.name} ({confirmed(r)}): {SITE}/localz/providers/listings/{r.id}" for r in listings)
    one = len(listings) == 1
    subject = f"Is {listings[0].name} still right on Localz?" if one else "Are your Localz listings still right?"
    body = (
        "People use Localz to decide whether to make the trip, so it matters that hours and details are current.\n\n"
        f"{lines}\n\n"
        "Open each one: if nothing has changed, tap \"Yes, it's all still right\". If something has, fix it there - "
        "it takes a minute."
    )
    mailer.queue(db, kind="portal.checkin", to=to, subject=subject, body=body + SIGN_OFF, user_id=user_id)
