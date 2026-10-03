import functools
import hashlib
import os
import secrets
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

import observability
from database import SessionLocal, get_db
from models import ApiKey, RolePermission, User, UserRole
from permissions import PERMISSION_KEYS, expand

logger = logging.getLogger(__name__)

AUTH_MODE = os.getenv("AUTH_MODE", "local")  # "local" | "supabase"
JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRES_MINUTES = 60 * 24

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_JWT_AUDIENCE = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
BOOTSTRAP_ADMIN_EMAIL = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

# Admin-issued API keys (models.ApiKey). The prefix is what tells a key apart
# from a JWT before any verification runs.
API_KEY_PREFIX = "szk_"
_API_KEY_TOUCH_INTERVAL = timedelta(minutes=5)

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


def mask_email(email: str | None) -> str | None:
    """Mask email for an unauthenticated preview, revealing only the domain.

    This feeds invite previews that require no auth at all - anyone holding
    the token sees this, not just the invitee - so the local part is never
    partially revealed: a single leaked character would let someone who
    already has a guessed address confirm it's an exact match.

    Examples:
      'student@chclc.org' -> '*****@chclc.org'
      'a@school.edu' -> '*****@school.edu'
    """
    if not email or "@" not in email:
        return email
    _, _, domain = email.strip().lower().partition("@")
    return f"*****@{domain}"


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
            logger.info("supabase_identity_linked_existing_user", extra={"user_id": user.id})
            return user

    base_username = (email.split("@")[0] if email else supabase_user_id)[:56] or "user"
    candidate = base_username
    counter = 1
    while (await db.execute(select(User.id).where(User.username == candidate))).scalar_one_or_none():
        counter += 1
        candidate = f"{base_username}_{counter}"

    user = User(
        email=email or f"{supabase_user_id}@unknown.local",
        username=candidate,
        supabase_user_id=supabase_user_id,
        is_admin=bool(BOOTSTRAP_ADMIN_EMAIL and email == BOOTSTRAP_ADMIN_EMAIL),
    )
    db.add(user)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        candidate = f"{base_username[:50]}_{secrets.token_hex(4)}"
        user = User(
            email=email or f"{supabase_user_id}@unknown.local",
            username=candidate,
            supabase_user_id=supabase_user_id,
            is_admin=bool(BOOTSTRAP_ADMIN_EMAIL and email == BOOTSTRAP_ADMIN_EMAIL),
        )
        db.add(user)
        await db.commit()

    await db.refresh(user)
    logger.info("user_created", extra={"user_id": user.id, "source": "supabase_autoprovision"})
    observability.user_created_total.add(1, {"source": "supabase_autoprovision"})
    return user


def generate_api_key() -> tuple[str, str, str]:
    """(plaintext, display prefix, sha256 hex). 32 random bytes, so a plain
    hash is enough - there's nothing to brute-force the way a password has."""
    plaintext = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return plaintext, plaintext[:12], hash_api_key(plaintext)


def hash_api_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


async def _authenticate_api_key(request: Request, db: AsyncSession, token: str) -> User:
    key = (await db.execute(select(ApiKey).where(ApiKey.key_hash == hash_api_key(token)))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if key is None or (key.expires_at is not None and key.expires_at <= now):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired API key")
    user = (await db.execute(select(User).where(User.id == key.created_by_user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired API key")
    if key.last_used_at is None or now - key.last_used_at > _API_KEY_TOUCH_INTERVAL:
        key.last_used_at = now
        await db.commit()
    request.state.api_key_id = key.id
    request.state.api_key_scope = frozenset(key.permissions or ())
    return user


def is_api_key_request(request: Request) -> bool:
    return getattr(request.state, "api_key_scope", None) is not None


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    if token.startswith(API_KEY_PREFIX):
        user = await _authenticate_api_key(request, db, token)
    elif AUTH_MODE == "supabase":
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


async def require_super_admin(request: Request, user: User = Depends(get_current_user)) -> User:
    """Super admin = `User.is_admin`. Holds every permission and is the only
    tier that can manage users, roles and API keys. An API key never counts,
    even one a super admin created, so no key can mint admins or more keys."""
    if is_api_key_request(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "API keys can't manage users, roles or keys")
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Super admin access required")
    return user


async def get_user_permissions(db: AsyncSession, user: User) -> set[str]:
    if user.is_admin:
        return set(PERMISSION_KEYS)
    rows = await db.execute(
        select(RolePermission.permission)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user.id)
    )
    return expand(set(rows.scalars().all()))


async def get_effective_permissions(request: Request, db: AsyncSession, user: User) -> set[str]:
    """What this request may do: the user's permissions, narrowed to the API
    key's scope when it came in on a key. Intersected at request time, so
    demoting a key's creator shrinks the key with them."""
    perms = await get_user_permissions(db, user)
    scope = getattr(request.state, "api_key_scope", None)
    if scope is not None:
        perms &= expand(set(scope))
    return perms


@functools.cache
def require_permission(permission: str):
    """Dependency factory: the centrally-managed-data-sources gate. Creating
    or editing a District, School or newsletter, or triggering a scan, is an
    admin action - a super admin, or a user whose role grants `permission`.
    Cached so a test can override one gate by its identity."""
    if permission not in PERMISSION_KEYS:
        raise ValueError(f"Unknown permission {permission!r}")

    async def _dep(request: Request, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> User:
        if user.is_admin and not is_api_key_request(request):
            return user
        if permission not in await get_effective_permissions(request, db, user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
        return user

    return _dep
