"""API keys for scripts and agents (models.ApiKey), managed beside users and
roles: super admin only, and a request made *with* a key can never reach
these endpoints (auth.require_super_admin), so keys can't mint more keys.

Device flow (`scripts/schoolz-api.sh login`), for when the person approving
is on a phone and can't paste a key into a file: the script starts a
request and polls with a secret device code; a super admin opens the
approval link, checks the short user code matches what the script printed,
and approves. The key is minted when the script collects it, so its
plaintext never touches the database or the chat.
"""
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import generate_api_key, hash_api_key, require_super_admin
from database import get_db
from models import ApiKey, ApiKeyRequest, User
from permissions import PERMISSION_KEYS

router = APIRouter(prefix="/admin/api-keys", tags=["admin-api-keys"], dependencies=[Depends(require_super_admin)])
device_router = APIRouter(prefix="/auth/device", tags=["auth-device"])

MAX_EXPIRY_DAYS = 365
DEVICE_REQUEST_TTL = timedelta(minutes=10)
# After approval, time left for the script to collect the key.
DEVICE_COLLECT_WINDOW = timedelta(minutes=5)
DEVICE_POLL_INTERVAL_S = 3
# Unauthenticated start endpoint: bounds how many open requests anyone can pile up.
MAX_PENDING_DEVICE_REQUESTS = 25
# No vowels (no accidental words) and no 0/O/1/I lookalikes.
_USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"


def _known_permissions(v: list[str]) -> list[str]:
    unknown = sorted(set(v) - PERMISSION_KEYS)
    if unknown:
        raise ValueError(f"Unknown permission: {', '.join(unknown)}")
    return sorted(set(v))


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    permissions: list[str] = Field(min_length=1)
    # None = never expires.
    expires_in_days: int | None = Field(default=90, ge=1, le=MAX_EXPIRY_DAYS)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v

    @field_validator("permissions")
    @classmethod
    def _known(cls, v: list[str]) -> list[str]:
        return _known_permissions(v)


class ApiKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    permissions: list[str]
    created_by_email: str | None
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    key: str  # plaintext, returned exactly once


def _out(key: ApiKey, email: str | None) -> ApiKeyOut:
    return ApiKeyOut(
        id=key.id,
        name=key.name,
        key_prefix=key.key_prefix,
        permissions=list(key.permissions or []),
        created_by_email=email,
        created_at=key.created_at,
        expires_at=key.expires_at,
        last_used_at=key.last_used_at,
    )


@router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(ApiKey, User.email).join(User, User.id == ApiKey.created_by_user_id).order_by(ApiKey.created_at.desc())
        )
    ).all()
    return [_out(key, email) for key, email in rows]


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(payload: ApiKeyIn, actor: User = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    plaintext, prefix, digest = generate_api_key()
    now = datetime.now(timezone.utc)
    key = ApiKey(
        name=payload.name,
        key_prefix=prefix,
        key_hash=digest,
        permissions=payload.permissions,
        created_by_user_id=actor.id,
        created_at=now,
        expires_at=now + timedelta(days=payload.expires_in_days) if payload.expires_in_days else None,
    )
    db.add(key)
    await db.commit()
    return ApiKeyCreated(**_out(key, actor.email).model_dump(), key=plaintext)


class ApiKeyPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    permissions: list[str] | None = Field(default=None, min_length=1)

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v

    @field_validator("permissions")
    @classmethod
    def _known(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _known_permissions(v)


@router.patch("/{key_id}", response_model=ApiKeyOut)
async def update_api_key(key_id: str, payload: ApiKeyPatch, db: AsyncSession = Depends(get_db)):
    """Rename a key or change what it may do, without minting a new secret.
    Super-admin only like every route here, so a key can never widen itself,
    and `_known_permissions` only accepts the grantable catalog, which never
    includes users/roles/keys."""
    row = (
        await db.execute(
            select(ApiKey, User.email).join(User, User.id == ApiKey.created_by_user_id).where(ApiKey.id == key_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    key, email = row
    if payload.name is not None:
        key.name = payload.name
    if payload.permissions is not None:
        key.permissions = payload.permissions
    await db.commit()
    return _out(key, email)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: str, db: AsyncSession = Depends(get_db)):
    key = (await db.execute(select(ApiKey).where(ApiKey.id == key_id))).scalar_one_or_none()
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    await db.delete(key)
    await db.commit()


# ---- Device flow ---------------------------------------------------------


def _new_user_code() -> str:
    raw = "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def _normalize_user_code(code: str) -> str:
    raw = "".join(ch for ch in code.upper() if ch.isalnum())
    return f"{raw[:4]}-{raw[4:]}" if len(raw) == 8 else raw


class DeviceStartIn(BaseModel):
    client_name: str = Field(min_length=1, max_length=100)


class DeviceStartOut(BaseModel):
    device_code: str
    user_code: str
    expires_in: int
    interval: int


class DeviceTokenIn(BaseModel):
    device_code: str = Field(min_length=1, max_length=200)


class DeviceTokenOut(BaseModel):
    # pending | denied | expired | approved
    status: str
    key: str | None = None
    key_prefix: str | None = None
    permissions: list[str] | None = None


@device_router.post("/start", response_model=DeviceStartOut)
async def device_start(payload: DeviceStartIn, request: Request, db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    await db.execute(delete(ApiKeyRequest).where(ApiKeyRequest.expires_at < now - timedelta(days=1)))
    open_count = (
        await db.execute(
            select(func.count()).select_from(ApiKeyRequest).where(ApiKeyRequest.status == "pending", ApiKeyRequest.expires_at > now)
        )
    ).scalar_one()
    if open_count >= MAX_PENDING_DEVICE_REQUESTS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many open login requests; try again in a few minutes")

    device_code = secrets.token_urlsafe(32)
    user_code = _new_user_code()
    while (await db.execute(select(ApiKeyRequest.id).where(ApiKeyRequest.user_code == user_code))).first():
        user_code = _new_user_code()
    db.add(
        ApiKeyRequest(
            user_code=user_code,
            device_code_hash=hash_api_key(device_code),
            client_name=payload.client_name.strip(),
            requested_ip=request.client.host if request.client else None,
            status="pending",
            created_at=now,
            expires_at=now + DEVICE_REQUEST_TTL,
        )
    )
    await db.commit()
    return DeviceStartOut(
        device_code=device_code,
        user_code=user_code,
        expires_in=int(DEVICE_REQUEST_TTL.total_seconds()),
        interval=DEVICE_POLL_INTERVAL_S,
    )


@device_router.post("/token", response_model=DeviceTokenOut)
async def device_token(payload: DeviceTokenIn, db: AsyncSession = Depends(get_db)):
    req = (
        await db.execute(
            select(ApiKeyRequest).where(ApiKeyRequest.device_code_hash == hash_api_key(payload.device_code)).with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    # An unknown code, an already-collected one and a timed-out one all read
    # "expired": the script's only move in each case is to start over.
    if req is None or req.status == "issued" or req.expires_at <= now:
        return DeviceTokenOut(status="expired")
    if req.status in ("pending", "denied"):
        return DeviceTokenOut(status=req.status)

    plaintext, prefix, digest = generate_api_key()
    key = ApiKey(
        name=req.key_name or req.client_name,
        key_prefix=prefix,
        key_hash=digest,
        permissions=list(req.permissions or []),
        created_by_user_id=req.approved_by_user_id,
        created_at=now,
        expires_at=now + timedelta(days=req.key_expires_in_days) if req.key_expires_in_days else None,
    )
    db.add(key)
    await db.flush()
    req.status = "issued"
    req.api_key_id = key.id
    await db.commit()
    return DeviceTokenOut(status="approved", key=plaintext, key_prefix=prefix, permissions=list(key.permissions))


class DeviceRequestOut(BaseModel):
    user_code: str
    client_name: str
    requested_ip: str | None
    created_at: datetime
    expires_at: datetime
    # pending | approved | denied | issued | expired
    status: str


class DeviceApproveIn(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    permissions: list[str] = Field(min_length=1)
    expires_in_days: int | None = Field(default=90, ge=1, le=MAX_EXPIRY_DAYS)

    @field_validator("permissions")
    @classmethod
    def _known(cls, v: list[str]) -> list[str]:
        return _known_permissions(v)


async def _get_request(db: AsyncSession, user_code: str) -> ApiKeyRequest:
    req = (
        await db.execute(select(ApiKeyRequest).where(ApiKeyRequest.user_code == _normalize_user_code(user_code)))
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No login request with that code")
    return req


def _request_out(req: ApiKeyRequest) -> DeviceRequestOut:
    expired = req.status in ("pending", "approved") and req.expires_at <= datetime.now(timezone.utc)
    return DeviceRequestOut(
        user_code=req.user_code,
        client_name=req.client_name,
        requested_ip=req.requested_ip,
        created_at=req.created_at,
        expires_at=req.expires_at,
        status="expired" if expired else req.status,
    )


async def _get_pending(db: AsyncSession, user_code: str) -> ApiKeyRequest:
    req = await _get_request(db, user_code)
    if req.status != "pending" or req.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status.HTTP_410_GONE, "This login request has expired or was already answered")
    return req


@router.get("/requests/{user_code}", response_model=DeviceRequestOut)
async def get_device_request(user_code: str, db: AsyncSession = Depends(get_db)):
    return _request_out(await _get_request(db, user_code))


@router.post("/requests/{user_code}/approve", response_model=DeviceRequestOut)
async def approve_device_request(
    user_code: str, payload: DeviceApproveIn, actor: User = Depends(require_super_admin), db: AsyncSession = Depends(get_db)
):
    req = await _get_pending(db, user_code)
    req.status = "approved"
    req.approved_by_user_id = actor.id
    req.key_name = (payload.name or "").strip() or req.client_name
    req.permissions = payload.permissions
    req.key_expires_in_days = payload.expires_in_days
    req.expires_at = datetime.now(timezone.utc) + DEVICE_COLLECT_WINDOW
    await db.commit()
    return _request_out(req)


@router.post("/requests/{user_code}/deny", response_model=DeviceRequestOut)
async def deny_device_request(user_code: str, db: AsyncSession = Depends(get_db)):
    req = await _get_pending(db, user_code)
    req.status = "denied"
    await db.commit()
    return _request_out(req)
