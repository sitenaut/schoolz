"""The signed-in person's own saved Localz answers ("My services profile").

Owner only, by construction: every query is keyed on the caller's own
`user.id`, nothing takes a user id from the request, and no permission key
reaches another person's profile (so no role, admin or API key can). API
keys are refused outright: a key is for scripts changing schoolz, and a
script has no business with someone's services profile.

The path is deliberately neutral ("saved answers"), since paths reach the
request log. Nothing here logs, and the request log line never carries a
body. Withdrawing consent or deleting the profile is a hard delete,
immediately. Design: docs/LOCALZ_DESIGN.md, "Saved profile".
"""
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import crypto
from auth import get_current_user, is_api_key_request
from database import get_db
from models import ConsentRecord, ServicesProfile, User
from request_context import CodedHTTPException
from resources import saved_profile as sp

router = APIRouter(prefix="/me/saved-answers", tags=["saved-answers"])


async def profile_owner(request: Request, user: User = Depends(get_current_user)) -> User:
    if is_api_key_request(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "API keys can't reach saved answers")
    return user


class ConsentOut(BaseModel):
    policy_version: int
    granted_at: datetime
    current: bool


class SavedAnswersOut(BaseModel):
    # False when the server has no encryption key: nothing can be saved.
    available: bool
    policy_version: int
    consent: ConsentOut | None
    # A profile exists, though its answers are withheld until consent is current.
    saved: bool
    answers: sp.SavedAnswers | None
    updated_at: datetime | None
    last_used_at: datetime | None


class ConsentIn(BaseModel):
    purpose: Literal["services_profile", "services_alerts", "services_alerts_named"]
    policy_version: int


def _now() -> datetime:
    return datetime.now(UTC)


async def _active_consent(db: AsyncSession, user_id: str) -> ConsentRecord | None:
    return (
        await db.execute(
            select(ConsentRecord)
            .where(
                ConsentRecord.user_id == user_id,
                ConsentRecord.purpose == sp.PURPOSE_PROFILE,
                ConsentRecord.withdrawn_at.is_(None),
            )
            .order_by(ConsentRecord.granted_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _consent_out(c: ConsentRecord | None) -> ConsentOut | None:
    if c is None:
        return None
    return ConsentOut(policy_version=c.policy_version, granted_at=c.granted_at, current=c.policy_version >= sp.POLICY_VERSION)


async def _forget(db: AsyncSession, user_id: str) -> None:
    """Hard-delete the profile and withdraw every services consent."""
    await db.execute(delete(ServicesProfile).where(ServicesProfile.user_id == user_id))
    await db.execute(
        update(ConsentRecord)
        .where(ConsentRecord.user_id == user_id, ConsentRecord.purpose.in_(sp.PURPOSES), ConsentRecord.withdrawn_at.is_(None))
        .values(withdrawn_at=_now())
    )
    await db.commit()


async def _state(db: AsyncSession, user_id: str, touch: bool) -> SavedAnswersOut:
    consent = await _active_consent(db, user_id)
    current = consent is not None and consent.policy_version >= sp.POLICY_VERSION
    row = await db.get(ServicesProfile, user_id)
    answers = None
    if row is not None and current:
        answers = sp.loads(row.profile)
        if touch:
            row.last_used_at = _now()
            await db.commit()
    return SavedAnswersOut(
        available=crypto.can_encrypt(),
        policy_version=sp.POLICY_VERSION,
        consent=_consent_out(consent),
        saved=row is not None,
        answers=answers,
        updated_at=row.updated_at if row else None,
        last_used_at=row.last_used_at if row else None,
    )


@router.get("", response_model=SavedAnswersOut)
async def get_saved_answers(user: User = Depends(profile_owner), db: AsyncSession = Depends(get_db)):
    """The caller's own profile. Reading it counts as using it
    (`last_used_at`, for the inactivity expiry)."""
    return await _state(db, user.id, touch=True)


@router.put("", response_model=SavedAnswersOut)
async def put_saved_answers(answers: sp.SavedAnswers, user: User = Depends(profile_owner), db: AsyncSession = Depends(get_db)):
    consent = await _active_consent(db, user.id)
    if consent is None or consent.policy_version < sp.POLICY_VERSION:
        raise CodedHTTPException(status.HTTP_409_CONFLICT, "Agree to the saved-answers terms first", "consent_required")
    if not crypto.can_encrypt():
        raise CodedHTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Saving answers isn't available here", "encryption_unavailable")
    if answers.is_empty():
        # Nothing to keep: saving nothing means forgetting.
        await db.execute(delete(ServicesProfile).where(ServicesProfile.user_id == user.id))
        await db.commit()
        return await _state(db, user.id, touch=False)
    try:
        blob = answers.dumps()
    except ValueError:
        raise HTTPException(413, "Too much to save") from None
    now = _now()
    row = await db.get(ServicesProfile, user.id)
    if row is None:
        db.add(ServicesProfile(user_id=user.id, profile=blob, updated_at=now, last_used_at=now))
    else:
        row.profile = blob
        row.updated_at = now
        row.last_used_at = now
    await db.commit()
    return await _state(db, user.id, touch=False)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_answers(user: User = Depends(profile_owner), db: AsyncSession = Depends(get_db)):
    """Delete the profile now (not a flag) and withdraw consent with it."""
    await _forget(db, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/consent", response_model=SavedAnswersOut)
async def grant_consent(body: ConsentIn, user: User = Depends(profile_owner), db: AsyncSession = Depends(get_db)):
    if body.purpose not in sp.GRANTABLE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not offered yet")
    if body.policy_version != sp.POLICY_VERSION:
        # They agreed to text that's no longer current; show them the new one.
        raise CodedHTTPException(status.HTTP_409_CONFLICT, "The terms have changed; read them again", "policy_changed")
    existing = await _active_consent(db, user.id)
    if existing is None or existing.policy_version < sp.POLICY_VERSION:
        now = _now()
        if existing is not None:
            existing.withdrawn_at = now  # superseded by this grant
        db.add(ConsentRecord(user_id=user.id, purpose=body.purpose, policy_version=body.policy_version, granted_at=now))
        await db.commit()
    return await _state(db, user.id, touch=False)


@router.delete("/consent", status_code=status.HTTP_204_NO_CONTENT)
async def withdraw_consent(user: User = Depends(profile_owner), db: AsyncSession = Depends(get_db)):
    """Withdrawing deletes the profile immediately."""
    await _forget(db, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
