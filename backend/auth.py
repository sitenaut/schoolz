import os
from datetime import datetime, timedelta, timezone

import logging

import bcrypt
import httpx
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt import PyJWKClient
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import SessionLocal, get_db
from models import User

logger = logging.getLogger(__name__)

AUTH_MODE = os.getenv("AUTH_MODE", "local")  # "local" | "supabase"
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRES_MINUTES = 60 * 24

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_JWT_AUDIENCE = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
BOOTSTRAP_ADMIN_EMAIL = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

_jwks_client: PyJWKClient | None = None


def prewarm_supabase_jwks() -> None:
    global _jwks_client
    if AUTH_MODE != "supabase" or not SUPABASE_URL:
        return
    _jwks_client = PyJWKClient(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json")
    try:
        _jwks_client.get_signing_keys()
    except Exception:
        pass  # best-effort warmup; verification will retry lazily per-request


async def seed_admin() -> None:
    """Create a default admin user from env vars if one doesn't exist yet.

    Only applies in local auth mode - in prod, admin status comes from
    BOOTSTRAP_ADMIN_EMAIL matching a Supabase-authenticated login instead.
    """
    if AUTH_MODE != "local":
        return

    admin_email = os.getenv("ADMIN_EMAIL")
    admin_username = os.getenv("ADMIN_USERNAME")
    admin_password = os.getenv("ADMIN_PASSWORD")
    if not (admin_email and admin_username and admin_password):
        return

    async with SessionLocal() as db:
        result = await db.execute(
            select(User).where(or_(User.email == admin_email, User.username == admin_username))
        )
        if result.scalar_one_or_none():
            return

        db.add(
            User(
                email=admin_email,
                username=admin_username,
                password_hash=hash_password(admin_password),
                is_admin=True,
            )
        )
        await db.commit()
        logger.info("seeded_default_admin_user", extra={"username": admin_username})


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_local_token(user_id: str) -> str:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET is not set")
    now = datetime.now(timezone.utc)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(minutes=JWT_EXPIRES_MINUTES)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_local_token(token: str) -> str:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return payload["sub"]


async def _verify_supabase_token(token: str) -> dict:
    global _jwks_client
    try:
        if _jwks_client is None:
            _jwks_client = PyJWKClient(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json")
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=SUPABASE_JWT_AUDIENCE,
        )
    except Exception:
        # Slow-path fallback: ask Supabase directly (covers key rotation races).
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code != 200:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
        body = resp.json()
        return {"sub": body["id"], "email": body.get("email")}


async def _get_or_create_supabase_user(db: AsyncSession, claims: dict) -> User:
    supabase_user_id = claims["sub"]
    email = claims.get("email", "")

    result = await db.execute(select(User).where(User.supabase_user_id == supabase_user_id))
    user = result.scalar_one_or_none()
    if user:
        return user

    if email:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user:
            user.supabase_user_id = supabase_user_id
            await db.commit()
            await db.refresh(user)
            return user

    user = User(
        email=email or f"{supabase_user_id}@unknown.local",
        username=(email.split("@")[0] if email else supabase_user_id)[:64],
        supabase_user_id=supabase_user_id,
        is_admin=bool(BOOTSTRAP_ADMIN_EMAIL and email == BOOTSTRAP_ADMIN_EMAIL),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    if AUTH_MODE == "supabase":
        claims = await _verify_supabase_token(token)
        user = await _get_or_create_supabase_user(db, claims)
    else:
        user_id = _decode_local_token(token)
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

    # Read back by the http_request log line (main.py). Without it there
    # was nothing in the logs distinguishing an authenticated request from
    # an anonymous one - the first thing worth knowing about a bug that
    # only reproduces while logged in.
    request.state.user_id = user.id
    return user


async def get_optional_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Like get_current_user, but returns None instead of raising - for
    public endpoints whose behavior only *changes* when someone happens to
    be logged in (e.g. GET /calendar defaulting to "my schools" for a
    logged-in guardian, vs. everything for an anonymous visitor), not
    endpoints that require a login at all."""
    if not token:
        return None
    try:
        return await get_current_user(request, token, db)
    except HTTPException:
        return None


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """The centrally-managed-data-sources gate: creating/editing a
    District, School, SmoreNewsletter, or triggering a scan is an admin
    action, not something any logged-in guardian can do - registering is
    only ever for the optional personal view (my kids, my calendar)."""
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user
