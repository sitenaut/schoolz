"""API keys for scripts and agents (models.ApiKey), managed beside users and
roles: super admin only, and a request made *with* a key can never reach
these endpoints (auth.require_super_admin), so keys can't mint more keys."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import generate_api_key, require_super_admin
from database import get_db
from models import ApiKey, User
from permissions import PERMISSION_KEYS

router = APIRouter(prefix="/admin/api-keys", tags=["admin-api-keys"], dependencies=[Depends(require_super_admin)])

MAX_EXPIRY_DAYS = 365


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
        unknown = sorted(set(v) - PERMISSION_KEYS)
        if unknown:
            raise ValueError(f"Unknown permission: {', '.join(unknown)}")
        return sorted(set(v))


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


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: str, db: AsyncSession = Depends(get_db)):
    key = (await db.execute(select(ApiKey).where(ApiKey.id == key_id))).scalar_one_or_none()
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    await db.delete(key)
    await db.commit()
