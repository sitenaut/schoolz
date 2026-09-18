"""Student accounts: a guardian invites their child to log in as themselves.

Accepting an invite sets Student.user_id - the student sees the same bucket3
data their guardians see (routers/bucket3.py's access check allows either).
Mirrors routers/invites.py's GuardianInvite flow on purpose (token, 7-day
expiry, minimal unauthenticated preview, accept-while-logged-in so it works
under both local and Supabase/Google auth), with two stricter rules because
this grants a child's identity rather than a shared view: the logged-in
email must match the invited email, and a student has at most one account.
"""
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models import GuardianStudentLink, Student, StudentAccountInvite, User

router = APIRouter(tags=["student_accounts"])

INVITE_EXPIRY_DAYS = 7


class StudentAccountInviteCreate(BaseModel):
    invitee_email: EmailStr


class StudentAccountInviteOut(BaseModel):
    id: str
    token: str
    accept_url: str
    invitee_email: str
    status: str
    expires_at: datetime


class StudentAccountInvitePreviewOut(BaseModel):
    student_first_name: str
    student_last_initial: str
    inviter_username: str
    status: str
    expires_at: datetime


class StudentAccountStatusOut(BaseModel):
    has_account: bool
    account_email: str | None
    pending_invite_email: str | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _require_guardian(db: AsyncSession, user: User, student_id: str) -> Student:
    result = await db.execute(
        select(Student)
        .join(GuardianStudentLink, GuardianStudentLink.student_id == Student.id)
        .where(Student.id == student_id, GuardianStudentLink.guardian_user_id == user.id)
    )
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found on your profile")
    return student


async def _get_live_invite(db: AsyncSession, token: str) -> StudentAccountInvite:
    invite = (
        await db.execute(select(StudentAccountInvite).where(StudentAccountInvite.token == token))
    ).scalar_one_or_none()
    if not invite:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invite not found")
    if invite.status == "pending" and invite.expires_at < _now():
        invite.status = "expired"
        await db.commit()
    return invite


@router.get("/students/{student_id}/student-account", response_model=StudentAccountStatusOut)
async def get_student_account_status(
    student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    student = await _require_guardian(db, user, student_id)
    account_email = None
    if student.user_id:
        account_user = await db.get(User, student.user_id)
        account_email = account_user.email if account_user else None
    pending = (
        await db.execute(
            select(StudentAccountInvite)
            .where(
                StudentAccountInvite.student_id == student.id,
                StudentAccountInvite.status == "pending",
                StudentAccountInvite.expires_at > _now(),
            )
            .order_by(StudentAccountInvite.created_at.desc())
        )
    ).scalars().first()
    return StudentAccountStatusOut(
        has_account=student.user_id is not None,
        account_email=account_email,
        pending_invite_email=pending.invitee_email if pending else None,
    )


@router.post(
    "/students/{student_id}/account-invites",
    response_model=StudentAccountInviteOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_student_account_invite(
    student_id: str,
    payload: StudentAccountInviteCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    student = await _require_guardian(db, user, student_id)
    if student.user_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "This student already has their own login")

    # One live invite at a time - re-inviting (e.g. a typo'd email) revokes
    # the previous one rather than leaving two claimable links around.
    previous = (
        await db.execute(
            select(StudentAccountInvite).where(
                StudentAccountInvite.student_id == student.id, StudentAccountInvite.status == "pending"
            )
        )
    ).scalars().all()
    for old in previous:
        old.status = "revoked"

    invite = StudentAccountInvite(
        student_id=student.id,
        invited_by_user_id=user.id,
        invitee_email=str(payload.invitee_email).lower(),
        token=secrets.token_urlsafe(32),
        status="pending",
        expires_at=_now() + timedelta(days=INVITE_EXPIRY_DAYS),
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)

    web_url = os.getenv("PUBLIC_WEB_URL", "http://localhost:5173")
    return StudentAccountInviteOut(
        id=invite.id,
        token=invite.token,
        accept_url=f"{web_url}/student-invites/{invite.token}",
        invitee_email=invite.invitee_email,
        status=invite.status,
        expires_at=invite.expires_at,
    )


@router.delete("/students/{student_id}/student-account", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_student_account(
    student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Unlinks the student's login from the student record (the User row
    itself stays - it's the child's own account) and revokes any pending
    invite. Any guardian of the student may do this."""
    student = await _require_guardian(db, user, student_id)
    student.user_id = None
    pending = (
        await db.execute(
            select(StudentAccountInvite).where(
                StudentAccountInvite.student_id == student.id, StudentAccountInvite.status == "pending"
            )
        )
    ).scalars().all()
    for invite in pending:
        invite.status = "revoked"
    await db.commit()


@router.get("/student-account-invites/{token}", response_model=StudentAccountInvitePreviewOut)
async def preview_student_account_invite(token: str, db: AsyncSession = Depends(get_db)):
    """Unauthenticated, deliberately minimal - same rule as GET /invites/{token}."""
    invite = await _get_live_invite(db, token)
    student = await db.get(Student, invite.student_id)
    inviter = await db.get(User, invite.invited_by_user_id)
    return StudentAccountInvitePreviewOut(
        student_first_name=student.first_name,
        student_last_initial=student.last_name[:1].upper(),
        inviter_username=inviter.username if inviter else "A guardian",
        status=invite.status,
        expires_at=invite.expires_at,
    )


@router.post("/student-account-invites/{token}/accept", response_model=StudentAccountStatusOut)
async def accept_student_account_invite(
    token: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    invite = await _get_live_invite(db, token)
    if invite.status != "pending":
        raise HTTPException(status.HTTP_410_GONE, f"This invite is {invite.status}")
    if user.email.lower() != invite.invitee_email.lower():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"This invite is for {invite.invitee_email} - sign in with that account to accept it",
        )

    student = await db.get(Student, invite.student_id)
    if student.user_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "This student already has their own login")

    guardian_of_this_student = (
        await db.execute(
            select(GuardianStudentLink.id).where(
                GuardianStudentLink.student_id == student.id, GuardianStudentLink.guardian_user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if guardian_of_this_student:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A guardian's account can't also be this student's own login"
        )

    already_a_student = (
        await db.execute(select(Student.id).where(Student.user_id == user.id))
    ).scalar_one_or_none()
    if already_a_student:
        raise HTTPException(status.HTTP_409_CONFLICT, "This account is already linked to a student")

    student.user_id = user.id
    invite.status = "accepted"
    invite.accepted_by_user_id = user.id
    invite.accepted_at = _now()
    await db.commit()

    return StudentAccountStatusOut(has_account=True, account_email=user.email, pending_invite_email=None)
