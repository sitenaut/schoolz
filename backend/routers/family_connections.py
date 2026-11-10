"""Connecting an app to one person's family: billz, the owner's household
app, reads that person's children, their schools, school days, schoolwork
and grades from GET /family/feed (routers/family_feed.py) with the key it
collects here.

Experimental, so only a super admin can approve a connection. The device
flow is `scripts/schoolz-api.sh login`'s (routers/admin_api_keys.py): the app
starts a request and polls with a secret device code; a super admin opens
the approval link (usually on a phone), checks the short code matches the
one the app shows, and approves. The key is minted when the app collects
it, so its plaintext never touches the database. Only a known app may
start a request, so the approval page never shows a name a stranger made up.

The key reaches only auth.FAMILY_KEY_ROUTES: read the feed and disconnect
itself. It is listed under Admin → Connected apps, where removing it cuts
the app off at once.
"""
import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import generate_family_key, get_current_user, hash_api_key, require_super_admin
from database import get_db
from models import FamilyConnection, FamilyConnectionRequest, User
from services import audit
from services.client_ip import client_ip

router = APIRouter(
    prefix="/admin/family-connections", tags=["family-connections"], dependencies=[Depends(require_super_admin)]
)
device_router = APIRouter(prefix="/family-connections", tags=["family-connections"])

REQUEST_TTL = timedelta(minutes=10)
# After approval, time left for the app to collect its key.
COLLECT_WINDOW = timedelta(minutes=5)
POLL_INTERVAL_S = 3
# Unauthenticated start endpoint: bounds how many open requests can pile up,
# per connection and in all.
MAX_PENDING_REQUESTS = 100
MAX_PENDING_REQUESTS_PER_IP = 3
# No vowels (no accidental words) and no 0/O/1/I lookalikes.
_USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"
# Path on the schoolz site the app sends the person to (it adds ?code=).
APPROVE_PATH = "/admin/connected-apps/approve"
# The apps that may connect, by the name each starts its request with.
KNOWN_APPS = frozenset({"billz"})


def requester_ip_hash(ip: str | None) -> str | None:
    """The connection a request came from, as the same reversible code the
    other rate limits keep (CLAUDE.md, "IP codes are reversible on purpose"),
    never the address. Gone with the request, a day after it expires."""
    if not ip:
        return None
    salt = os.getenv("JWT_SECRET", "schoolz-family-connect-salt")
    return hashlib.sha256(f"{salt}:family-connect:{ip}".encode()).hexdigest()


def _new_user_code() -> str:
    raw = "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def _normalize_user_code(code: str) -> str:
    raw = "".join(ch for ch in code.upper() if ch.isalnum())
    return f"{raw[:4]}-{raw[4:]}" if len(raw) == 8 else raw


class ConnectStartIn(BaseModel):
    client_name: str = Field(min_length=1, max_length=100)


class ConnectStartOut(BaseModel):
    device_code: str
    user_code: str
    # Path on the schoolz site to send the person to (add ?code=).
    approve_path: str
    expires_in: int
    interval: int


class ConnectTokenIn(BaseModel):
    device_code: str = Field(min_length=1, max_length=200)


class ConnectTokenOut(BaseModel):
    # pending | denied | expired | approved
    status: str
    key: str | None = None
    connection_id: str | None = None


class ConnectRequestOut(BaseModel):
    user_code: str
    client_name: str
    created_at: datetime
    expires_at: datetime
    # pending | approved | denied | issued | expired
    status: str


class FamilyConnectionOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None


@device_router.post("/start", response_model=ConnectStartOut)
async def start(payload: ConnectStartIn, request: Request, db: AsyncSession = Depends(get_db)):
    name = payload.client_name.strip()
    if name not in KNOWN_APPS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown app")
    now = datetime.now(UTC)
    ip_code = requester_ip_hash(client_ip(request))
    await db.execute(delete(FamilyConnectionRequest).where(FamilyConnectionRequest.expires_at < now - timedelta(days=1)))
    open_count, from_ip = (
        await db.execute(
            select(func.count(), func.count().filter(FamilyConnectionRequest.requester_ip_hash == ip_code))
            .select_from(FamilyConnectionRequest)
            .where(FamilyConnectionRequest.status == "pending", FamilyConnectionRequest.expires_at > now)
        )
    ).one()
    if open_count >= MAX_PENDING_REQUESTS or (ip_code and from_ip >= MAX_PENDING_REQUESTS_PER_IP):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many open connect requests; try again in a few minutes")

    device_code = secrets.token_urlsafe(32)
    user_code = _new_user_code()
    while (await db.execute(select(FamilyConnectionRequest.id).where(FamilyConnectionRequest.user_code == user_code))).first():
        user_code = _new_user_code()
    db.add(
        FamilyConnectionRequest(
            user_code=user_code,
            device_code_hash=hash_api_key(device_code),
            client_name=name,
            requester_ip_hash=ip_code,
            status="pending",
            created_at=now,
            expires_at=now + REQUEST_TTL,
        )
    )
    await db.commit()
    return ConnectStartOut(
        device_code=device_code,
        user_code=user_code,
        approve_path=APPROVE_PATH,
        expires_in=int(REQUEST_TTL.total_seconds()),
        interval=POLL_INTERVAL_S,
    )


@device_router.post("/token", response_model=ConnectTokenOut)
async def token(payload: ConnectTokenIn, request: Request, db: AsyncSession = Depends(get_db)):
    req = (
        await db.execute(
            select(FamilyConnectionRequest)
            .where(FamilyConnectionRequest.device_code_hash == hash_api_key(payload.device_code))
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    # Unknown, already collected and timed out all read "expired": the
    # app's only move in each case is to start over.
    if req is None or req.status == "issued" or req.expires_at <= now:
        return ConnectTokenOut(status="expired")
    if req.status in ("pending", "denied"):
        return ConnectTokenOut(status=req.status)

    user = await db.get(User, req.approved_by_user_id)
    if user is None:
        return ConnectTokenOut(status="expired")
    plaintext, prefix, digest = generate_family_key()
    connection = FamilyConnection(user_id=user.id, name=req.client_name, key_prefix=prefix, key_hash=digest, created_at=now)
    db.add(connection)
    await db.flush()
    req.status = "issued"
    req.family_connection_id = connection.id
    await db.commit()
    audit.note(request, "family_connection.issued", family_connection_id=connection.id, key_prefix=prefix, user_id=user.id)
    return ConnectTokenOut(status="approved", key=plaintext, connection_id=connection.id)


@device_router.post("/self/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_self(request: Request, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The app's own Disconnect: removes the key it was called with."""
    connection_id = getattr(request.state, "family_connection_id", None)
    if connection_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only a connected app's key can remove itself")
    connection = await db.get(FamilyConnection, connection_id)
    if connection is not None:
        await db.delete(connection)
        await db.commit()


@router.get("", response_model=list[FamilyConnectionOut])
async def list_connections(actor: User = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    """Apps connected to this person's own family."""
    rows = await db.execute(
        select(FamilyConnection).where(FamilyConnection.user_id == actor.id).order_by(FamilyConnection.created_at.desc())
    )
    return [
        FamilyConnectionOut(id=c.id, name=c.name, key_prefix=c.key_prefix, created_at=c.created_at, last_used_at=c.last_used_at)
        for c in rows.scalars().all()
    ]


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_connection(connection_id: str, actor: User = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    connection = await db.get(FamilyConnection, connection_id)
    if connection is None or connection.user_id != actor.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such connected app")
    await db.delete(connection)
    await db.commit()


async def _get_request(db: AsyncSession, user_code: str) -> FamilyConnectionRequest:
    req = (
        await db.execute(
            select(FamilyConnectionRequest).where(FamilyConnectionRequest.user_code == _normalize_user_code(user_code))
        )
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No connect request with that code")
    return req


def _request_out(req: FamilyConnectionRequest) -> ConnectRequestOut:
    expired = req.status in ("pending", "approved") and req.expires_at <= datetime.now(UTC)
    return ConnectRequestOut(
        user_code=req.user_code,
        client_name=req.client_name,
        created_at=req.created_at,
        expires_at=req.expires_at,
        status="expired" if expired else req.status,
    )


async def _get_pending(db: AsyncSession, user_code: str) -> FamilyConnectionRequest:
    req = await _get_request(db, user_code)
    if req.status != "pending" or req.expires_at <= datetime.now(UTC):
        raise HTTPException(status.HTTP_410_GONE, "This connect request has expired or was already answered")
    return req


@router.get("/requests/{user_code}", response_model=ConnectRequestOut)
async def get_request(user_code: str, db: AsyncSession = Depends(get_db)):
    return _request_out(await _get_request(db, user_code))


@router.post("/requests/{user_code}/approve", response_model=ConnectRequestOut)
async def approve(user_code: str, actor: User = Depends(require_super_admin), db: AsyncSession = Depends(get_db)):
    req = await _get_pending(db, user_code)
    req.status = "approved"
    req.approved_by_user_id = actor.id
    req.expires_at = datetime.now(UTC) + COLLECT_WINDOW
    await db.commit()
    return _request_out(req)


@router.post("/requests/{user_code}/deny", response_model=ConnectRequestOut)
async def deny(user_code: str, db: AsyncSession = Depends(get_db)):
    req = await _get_pending(db, user_code)
    req.status = "denied"
    await db.commit()
    return _request_out(req)
