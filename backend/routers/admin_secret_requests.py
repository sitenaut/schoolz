"""Approving use of the prod secrets vault (models.SecretAccessRequest).

The prod 1Password service-account token lives on the dev machine only in
encrypted form; the key that decrypts it is held here (`SECRETS_UNLOCK_KEY`, a
Fly secret) and handed over only for an approved request. So a session that
wants prod secrets (`scripts/prod-secrets.sh run`) asks first, saying why, what
it will run and which secrets it needs; a super admin reads that in the
browser, usually on a phone, and approves or denies. Neither side alone can
open the vault: the machine has the ciphertext, the server has the key.

Asking and collecting work with a super admin's API key. Reading the log and
deciding are super-admin sessions only (`require_super_admin` rejects keys), so
a session can't approve its own request. Each approval unlocks once and
expires; rows are kept as the audit log and never hold a secret value or the
unlock key.
"""
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, hash_api_key, require_super_admin
from database import get_db
from models import ApiKey, SecretAccessRequest, User
from routers.admin_api_keys import DEVICE_POLL_INTERVAL_S, _new_user_code, _normalize_user_code

router = APIRouter(prefix="/admin/secret-requests", tags=["admin-secret-requests"])

REQUEST_TTL = timedelta(minutes=10)
# After approval, time left for the requester to collect the unlock key.
COLLECT_WINDOW = timedelta(minutes=5)
# Bounds how many open requests one identity can pile up.
MAX_OPEN_PER_USER = 5
MAX_SECRETS = 40
LOG_LIMIT = 50
_SECRET_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _unlock_key() -> str | None:
    return os.environ.get("SECRETS_UNLOCK_KEY") or None


async def require_requester(user: User = Depends(get_current_user)) -> User:
    """Whoever asks must be a super admin or a key made by one. A key acts as
    its creator, so a demoted creator's key stops working here too."""
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Super admin access required")
    return user


class SecretRequestIn(BaseModel):
    client_name: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=300)
    command: str = Field(min_length=1, max_length=1000)
    secret_names: list[str] = Field(min_length=1, max_length=MAX_SECRETS)

    @field_validator("client_name", "reason", "command")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v

    @field_validator("secret_names")
    @classmethod
    def _names(cls, v: list[str]) -> list[str]:
        bad = sorted({n for n in v if not _SECRET_NAME.match(n)})
        if bad:
            raise ValueError(f"not secret names (UPPER_SNAKE_CASE): {', '.join(bad)[:200]}")
        return sorted(set(v))


class SecretRequestStarted(BaseModel):
    device_code: str
    user_code: str
    expires_in: int
    interval: int


class SecretPollIn(BaseModel):
    device_code: str = Field(min_length=1, max_length=200)


class SecretPollOut(BaseModel):
    # pending | denied | expired | approved
    status: str
    unlock_key: str | None = None
    # Echoed on approval so the requester can refuse to run anything else.
    command: str | None = None
    secret_names: list[str] | None = None


class SecretRequestOut(BaseModel):
    user_code: str
    client_name: str
    reason: str
    command: str
    secret_names: list[str]
    requested_ip: str | None
    api_key_name: str | None
    created_at: datetime
    expires_at: datetime
    # pending | approved | denied | collected | expired
    status: str
    decided_by: str | None
    decided_at: datetime | None
    collected_at: datetime | None


@router.post("", response_model=SecretRequestStarted, status_code=status.HTTP_201_CREATED)
async def start_secret_request(
    payload: SecretRequestIn, request: Request, requester: User = Depends(require_requester), db: AsyncSession = Depends(get_db)
):
    now = datetime.now(timezone.utc)
    open_count = (
        await db.execute(
            select(func.count())
            .select_from(SecretAccessRequest)
            .where(
                SecretAccessRequest.requested_by_user_id == requester.id,
                SecretAccessRequest.status == "pending",
                SecretAccessRequest.expires_at > now,
            )
        )
    ).scalar_one()
    if open_count >= MAX_OPEN_PER_USER:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many open requests; wait for them to expire or be answered")

    device_code = secrets.token_urlsafe(32)
    user_code = _new_user_code()
    while (await db.execute(select(SecretAccessRequest.id).where(SecretAccessRequest.user_code == user_code))).first():
        user_code = _new_user_code()
    db.add(
        SecretAccessRequest(
            user_code=user_code,
            device_code_hash=hash_api_key(device_code),
            client_name=payload.client_name,
            reason=payload.reason,
            command=payload.command,
            secret_names=payload.secret_names,
            requested_ip=request.client.host if request.client else None,
            requested_by_user_id=requester.id,
            api_key_id=getattr(request.state, "api_key_id", None),
            status="pending",
            created_at=now,
            expires_at=now + REQUEST_TTL,
        )
    )
    await db.commit()
    return SecretRequestStarted(
        device_code=device_code,
        user_code=user_code,
        expires_in=int(REQUEST_TTL.total_seconds()),
        interval=DEVICE_POLL_INTERVAL_S,
    )


@router.post("/poll", response_model=SecretPollOut)
async def poll_secret_request(
    payload: SecretPollIn, request: Request, requester: User = Depends(require_requester), db: AsyncSession = Depends(get_db)
):
    req = (
        await db.execute(
            select(SecretAccessRequest)
            .where(SecretAccessRequest.device_code_hash == hash_api_key(payload.device_code))
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    # Unknown, someone else's, already collected and timed out all read
    # "expired": the requester's only move in each case is to ask again.
    if (
        req is None
        or req.requested_by_user_id != requester.id
        or req.api_key_id != getattr(request.state, "api_key_id", None)
        or req.status == "collected"
    ):
        return SecretPollOut(status="expired")
    if req.status == "denied":
        return SecretPollOut(status="denied")
    if req.expires_at <= now:
        return SecretPollOut(status="expired")
    if req.status == "pending":
        return SecretPollOut(status="pending")

    key = _unlock_key()
    if key is None:
        # Checked before consuming the approval, so fixing the server config and
        # polling again still works inside the collect window.
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The secrets unlock key isn't configured on the server")
    req.status = "collected"
    req.collected_at = now
    await db.commit()
    return SecretPollOut(status="approved", unlock_key=key, command=req.command, secret_names=list(req.secret_names or []))


def _effective_status(req: SecretAccessRequest) -> str:
    if req.status in ("pending", "approved") and req.expires_at <= datetime.now(timezone.utc):
        return "expired"
    return req.status


async def _outs(db: AsyncSession, rows: list[SecretAccessRequest]) -> list[SecretRequestOut]:
    key_ids = {r.api_key_id for r in rows if r.api_key_id}
    user_ids = {r.decided_by_user_id for r in rows if r.decided_by_user_id}
    key_names = (
        {k.id: k.name for k in (await db.execute(select(ApiKey).where(ApiKey.id.in_(key_ids)))).scalars()} if key_ids else {}
    )
    emails = {u.id: u.email for u in (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars()} if user_ids else {}
    return [
        SecretRequestOut(
            user_code=r.user_code,
            client_name=r.client_name,
            reason=r.reason,
            command=r.command,
            secret_names=list(r.secret_names or []),
            requested_ip=r.requested_ip,
            api_key_name=key_names.get(r.api_key_id) if r.api_key_id else None,
            created_at=r.created_at,
            expires_at=r.expires_at,
            status=_effective_status(r),
            decided_by=emails.get(r.decided_by_user_id) if r.decided_by_user_id else None,
            decided_at=r.decided_at,
            collected_at=r.collected_at,
        )
        for r in rows
    ]


@router.get("", response_model=list[SecretRequestOut], dependencies=[Depends(require_super_admin)])
async def list_secret_requests(db: AsyncSession = Depends(get_db)):
    rows = (
        (await db.execute(select(SecretAccessRequest).order_by(SecretAccessRequest.created_at.desc()).limit(LOG_LIMIT)))
        .scalars()
        .all()
    )
    return await _outs(db, list(rows))


async def _get_request(db: AsyncSession, user_code: str) -> SecretAccessRequest:
    req = (
        await db.execute(select(SecretAccessRequest).where(SecretAccessRequest.user_code == _normalize_user_code(user_code)))
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No request with that code")
    return req


async def _get_pending(db: AsyncSession, user_code: str) -> SecretAccessRequest:
    req = await _get_request(db, user_code)
    if req.status != "pending" or req.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_410_GONE, "This request has expired or was already answered")
    return req


@router.get("/{user_code}", response_model=SecretRequestOut, dependencies=[Depends(require_super_admin)])
async def get_secret_request(user_code: str, db: AsyncSession = Depends(get_db)):
    return (await _outs(db, [await _get_request(db, user_code)]))[0]


@router.post("/{user_code}/approve", response_model=SecretRequestOut)
async def approve_secret_request(user_code: str, actor: User = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    req = await _get_pending(db, user_code)
    now = datetime.now(timezone.utc)
    req.status = "approved"
    req.decided_by_user_id = actor.id
    req.decided_at = now
    req.expires_at = now + COLLECT_WINDOW
    await db.commit()
    return (await _outs(db, [req]))[0]


@router.post("/{user_code}/deny", response_model=SecretRequestOut)
async def deny_secret_request(user_code: str, actor: User = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    req = await _get_pending(db, user_code)
    req.status = "denied"
    req.decided_by_user_id = actor.id
    req.decided_at = datetime.now(timezone.utc)
    await db.commit()
    return (await _outs(db, [req]))[0]
