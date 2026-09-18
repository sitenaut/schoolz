import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import auth as auth_module
from auth import create_local_token, get_current_user, hash_password, verify_password
from database import get_db
from models import (
    EmailScanner,
    GmailToken,
    GuardianInvite,
    GuardianStudentLink,
    Notification,
    ScheduledJob,
    School,
    SchoolEmailMessage,
    SmoreNewsletter,
    Student,
    StudentAccountInvite,
    User,
)
from schemas import (
    ChangePasswordRequest,
    DeleteAccountRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserOut,
    UserUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_RESET_TOKEN_TTL = timedelta(hours=1)
_DELETE_CONFIRMATION = "DELETE"


def _user_out(user: User, student_profile_id: str | None = None) -> UserOut:
    # A Supabase user with no local password and a Google identity has
    # nothing to "change" password-wise - the settings page hides the form.
    method = "password"
    if auth_module.AUTH_MODE == "supabase" and not user.password_hash:
        method = "google"
    return UserOut(
        id=user.id,
        email=user.email,
        username=user.username,
        is_admin=user.is_admin,
        auth_mode=auth_module.AUTH_MODE,
        sign_in_method=method,
        created_at=user.created_at,
        student_profile_id=student_profile_id,
    )


async def _student_profile_id(db: AsyncSession, user: User) -> str | None:
    return (await db.execute(select(Student.id).where(Student.user_id == user.id))).scalar_one_or_none()


def _local_only() -> None:
    if auth_module.AUTH_MODE != "local":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    _local_only()

    existing = await db.execute(select(User).where(or_(User.email == payload.email, User.username == payload.username)))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "Email or username already registered")

    user = User(
        email=payload.email,
        username=payload.username,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return TokenResponse(access_token=create_local_token(user.id))


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    _local_only()

    result = await db.execute(
        select(User).where(or_(User.email == payload.username_or_email, User.username == payload.username_or_email))
    )
    user = result.scalar_one_or_none()
    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username/email or password")

    return TokenResponse(access_token=create_local_token(user.id))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return _user_out(user, await _student_profile_id(db, user))


@router.patch("/me", response_model=UserOut)
async def update_me(payload: UserUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if payload.username is not None and payload.username != user.username:
        taken = await db.execute(select(User.id).where(User.username == payload.username, User.id != user.id))
        if taken.scalar_one_or_none():
            raise HTTPException(status.HTTP_409_CONFLICT, "That username is already taken")
        user.username = payload.username
    await db.commit()
    await db.refresh(user)
    return _user_out(user, await _student_profile_id(db, user))


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(payload: ChangePasswordRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Local auth mode only. In prod (Supabase) the browser talks to
    Supabase Auth directly (`supabase.auth.updateUser`) - the backend never
    sees a Supabase password."""
    _local_only()
    if not user.password_hash or not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    user.password_reset_token = None
    user.password_reset_expires_at = None
    await db.commit()


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    """Local auth mode only (prod's Supabase sends its own reset email).

    Local mode is dev-only and has no mailer, so the one-shot token comes
    back in the response instead of an email - that's what makes the flow
    completable at all locally. Always 200 whether or not the email exists,
    so this can't be used to probe for registered addresses; the token is
    only present when there was a matching user."""
    _local_only()
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    token: str | None = None
    if user:
        token = secrets.token_urlsafe(32)
        user.password_reset_token = token
        user.password_reset_expires_at = datetime.now(timezone.utc) + _RESET_TOKEN_TTL
        await db.commit()
        logger.info("password_reset_token_issued", extra={"user_id": user.id})
    return {"status": "ok", "reset_token": token}


@router.post("/reset-password", response_model=TokenResponse)
async def reset_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    _local_only()
    result = await db.execute(select(User).where(User.password_reset_token == payload.token))
    user = result.scalar_one_or_none()
    if not user or not user.password_reset_expires_at or user.password_reset_expires_at < datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This reset link is invalid or has expired")
    user.password_hash = hash_password(payload.new_password)
    user.password_reset_token = None
    user.password_reset_expires_at = None
    await db.commit()
    return TokenResponse(access_token=create_local_token(user.id))


async def _delete_supabase_user(supabase_user_id: str) -> None:
    """Best-effort removal of the Supabase Auth identity so the email can't
    still sign in to a now-deleted account. Needs the service-role key;
    without it the local row is still deleted and the next Google/email
    login would just auto-provision a fresh, empty account (auth.py's
    _get_or_create_supabase_user) - not a security hole, just untidy."""
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not service_key or not auth_module.SUPABASE_URL:
        logger.warning("supabase_user_delete_skipped_no_service_key", extra={"supabase_user_id": supabase_user_id})
        return
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.delete(
            f"{auth_module.SUPABASE_URL}/auth/v1/admin/users/{supabase_user_id}",
            headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
        )
    if resp.status_code not in (200, 204, 404):
        logger.error("supabase_user_delete_failed", extra={"status": resp.status_code, "body": resp.text[:300]})


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(payload: DeleteAccountRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Deletes the account and everything only this user owns. Shared data
    (a Student row, a tracked newsletter, a school's scans) is never
    deleted - other guardians still see it; provenance columns are just
    nulled. See CLAUDE.md's guardian/student model for why."""
    if payload.confirm != _DELETE_CONFIRMATION:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f'Type {_DELETE_CONFIRMATION} to confirm')
    if auth_module.AUTH_MODE == "local" and user.password_hash:
        if not payload.password or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password is incorrect")

    uid = user.id

    # Personal layer: only this user's view of things.
    await db.execute(delete(Notification).where(Notification.user_id == uid))
    await db.execute(delete(GuardianStudentLink).where(GuardianStudentLink.guardian_user_id == uid))
    await db.execute(delete(GuardianInvite).where(GuardianInvite.inviter_user_id == uid))
    await db.execute(update(GuardianInvite).where(GuardianInvite.accepted_by_user_id == uid).values(accepted_by_user_id=None))
    # A student deleting their own login unlinks it from the Student row;
    # the student record and every guardian's access to it stay.
    await db.execute(update(Student).where(Student.user_id == uid).values(user_id=None))
    await db.execute(delete(StudentAccountInvite).where(StudentAccountInvite.invited_by_user_id == uid))
    await db.execute(
        update(StudentAccountInvite).where(StudentAccountInvite.accepted_by_user_id == uid).values(accepted_by_user_id=None)
    )

    # Gmail: the token, every scanner, and the scanners' own jobs/captures.
    scanners = (await db.execute(select(EmailScanner).where(EmailScanner.owner_user_id == uid))).scalars().all()
    scanner_job_ids = [s.scheduled_job_id for s in scanners if s.scheduled_job_id]
    await db.execute(delete(SchoolEmailMessage).where(SchoolEmailMessage.owner_user_id == uid))
    for scanner in scanners:
        await db.delete(scanner)
    if scanner_job_ids:
        await db.execute(delete(ScheduledJob).where(ScheduledJob.id.in_(scanner_job_ids)))
    await db.execute(delete(GmailToken).where(GmailToken.user_id == uid))

    # Centrally-managed data this user happened to create stays; only the
    # "who created it" pointer goes.
    await db.execute(update(ScheduledJob).where(ScheduledJob.owner_user_id == uid).values(owner_user_id=None))
    await db.execute(update(SmoreNewsletter).where(SmoreNewsletter.created_by_user_id == uid).values(created_by_user_id=None))
    await db.execute(update(School).where(School.created_by_user_id == uid).values(created_by_user_id=None))

    supabase_user_id = user.supabase_user_id
    await db.delete(user)
    await db.commit()
    logger.info("account_deleted", extra={"user_id": uid})

    if supabase_user_id:
        try:
            await _delete_supabase_user(supabase_user_id)
        except Exception:
            logger.exception("supabase_user_delete_errored", extra={"supabase_user_id": supabase_user_id})
