"""Backpack Capture's "Connect to schoolz": a computer's extension gets its
own key without anyone typing a password into it.

The extension starts a request and polls with a secret device code, and
opens schoolz's /connect page in a tab. Whoever is signed in there (by
Google, password or anything else - that's the point) checks the short code
matches the one the extension shows and presses Connect; the extension's
next poll collects a key minted for that person. The key reaches only
auth.CAPTURE_KEY_ROUTES, is listed under Account so it can be removed, and
the extension's own Sign out removes it.

Same shape as the admin API-key device flow (routers/admin_api_keys.py),
for guardians: nothing to pick, and approved by the person whose account it
is, not by a super admin.
"""
import json
import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import generate_capture_key, get_current_user, hash_api_key, require_permission
from database import get_db
from models import CaptureDevice, CaptureDeviceRequest, CaptureDiagnostic, User
from services import audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/capture-devices", tags=["capture-devices"])

REQUEST_TTL = timedelta(minutes=10)
# After Connect, time left for the extension to collect its key.
COLLECT_WINDOW = timedelta(minutes=5)
POLL_INTERVAL_S = 3
# Unauthenticated start endpoint: bounds how many open requests anyone can pile up.
MAX_PENDING_REQUESTS = 200
# No vowels (no accidental words) and no 0/O/1/I lookalikes.
_USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"
CONNECT_PATH = "/connect"


def _new_user_code() -> str:
    raw = "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def _normalize_user_code(code: str) -> str:
    raw = "".join(ch for ch in code.upper() if ch.isalnum())
    return f"{raw[:4]}-{raw[4:]}" if len(raw) == 8 else raw


class CaptureStartIn(BaseModel):
    client_name: str = Field(min_length=1, max_length=100)


class CaptureStartOut(BaseModel):
    device_code: str
    user_code: str
    # Path on the schoolz site the extension opens (it adds ?code=).
    connect_path: str
    expires_in: int
    interval: int


class CaptureTokenIn(BaseModel):
    device_code: str = Field(min_length=1, max_length=200)


class CaptureTokenOut(BaseModel):
    # pending | denied | expired | approved
    status: str
    key: str | None = None
    device_id: str | None = None
    email: str | None = None


class CaptureRequestOut(BaseModel):
    user_code: str
    client_name: str
    created_at: datetime
    expires_at: datetime
    # pending | approved | denied | issued | expired
    status: str


class CaptureDeviceOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None


@router.post("/start", response_model=CaptureStartOut)
async def start(payload: CaptureStartIn, db: AsyncSession = Depends(get_db)):
    now = datetime.now(UTC)
    await db.execute(delete(CaptureDeviceRequest).where(CaptureDeviceRequest.expires_at < now - timedelta(days=1)))
    open_count = (
        await db.execute(
            select(func.count())
            .select_from(CaptureDeviceRequest)
            .where(CaptureDeviceRequest.status == "pending", CaptureDeviceRequest.expires_at > now)
        )
    ).scalar_one()
    if open_count >= MAX_PENDING_REQUESTS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many open connect requests; try again in a few minutes")

    device_code = secrets.token_urlsafe(32)
    user_code = _new_user_code()
    while (await db.execute(select(CaptureDeviceRequest.id).where(CaptureDeviceRequest.user_code == user_code))).first():
        user_code = _new_user_code()
    db.add(
        CaptureDeviceRequest(
            user_code=user_code,
            device_code_hash=hash_api_key(device_code),
            client_name=payload.client_name.strip(),
            status="pending",
            created_at=now,
            expires_at=now + REQUEST_TTL,
        )
    )
    await db.commit()
    return CaptureStartOut(
        device_code=device_code,
        user_code=user_code,
        connect_path=CONNECT_PATH,
        expires_in=int(REQUEST_TTL.total_seconds()),
        interval=POLL_INTERVAL_S,
    )


@router.post("/token", response_model=CaptureTokenOut)
async def token(payload: CaptureTokenIn, request: Request, db: AsyncSession = Depends(get_db)):
    req = (
        await db.execute(
            select(CaptureDeviceRequest)
            .where(CaptureDeviceRequest.device_code_hash == hash_api_key(payload.device_code))
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    # Unknown, already collected and timed out all read "expired": the
    # extension's only move in each case is to start over.
    if req is None or req.status == "issued" or req.expires_at <= now:
        return CaptureTokenOut(status="expired")
    if req.status in ("pending", "denied"):
        return CaptureTokenOut(status=req.status)

    user = await db.get(User, req.approved_by_user_id)
    if user is None:
        return CaptureTokenOut(status="expired")
    plaintext, prefix, digest = generate_capture_key()
    device = CaptureDevice(user_id=user.id, name=req.client_name, key_prefix=prefix, key_hash=digest, created_at=now)
    db.add(device)
    await db.flush()
    req.status = "issued"
    req.capture_device_id = device.id
    await db.commit()
    audit.note(request, "capture_device.issued", capture_device_id=device.id, key_prefix=prefix, user_id=user.id)
    return CaptureTokenOut(status="approved", key=plaintext, device_id=device.id, email=user.email)


async def _get_request(db: AsyncSession, user_code: str) -> CaptureDeviceRequest:
    req = (
        await db.execute(
            select(CaptureDeviceRequest).where(CaptureDeviceRequest.user_code == _normalize_user_code(user_code))
        )
    ).scalar_one_or_none()
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No connect request with that code")
    return req


def _request_out(req: CaptureDeviceRequest) -> CaptureRequestOut:
    expired = req.status in ("pending", "approved") and req.expires_at <= datetime.now(UTC)
    return CaptureRequestOut(
        user_code=req.user_code,
        client_name=req.client_name,
        created_at=req.created_at,
        expires_at=req.expires_at,
        status="expired" if expired else req.status,
    )


async def _get_pending(db: AsyncSession, user_code: str) -> CaptureDeviceRequest:
    req = await _get_request(db, user_code)
    if req.status != "pending" or req.expires_at <= datetime.now(UTC):
        raise HTTPException(status.HTTP_410_GONE, "This connect request has expired or was already answered")
    return req


@router.get("/requests/{user_code}", response_model=CaptureRequestOut)
async def get_request(user_code: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return _request_out(await _get_request(db, user_code))


@router.post("/requests/{user_code}/approve", response_model=CaptureRequestOut)
async def approve(user_code: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    req = await _get_pending(db, user_code)
    req.status = "approved"
    req.approved_by_user_id = user.id
    req.expires_at = datetime.now(UTC) + COLLECT_WINDOW
    await db.commit()
    return _request_out(req)


@router.post("/requests/{user_code}/deny", response_model=CaptureRequestOut)
async def deny(user_code: str, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    req = await _get_pending(db, user_code)
    req.status = "denied"
    await db.commit()
    return _request_out(req)


@router.get("", response_model=list[CaptureDeviceOut])
async def list_devices(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(CaptureDevice).where(CaptureDevice.user_id == user.id).order_by(CaptureDevice.created_at.desc())
    )
    return [
        CaptureDeviceOut(id=d.id, name=d.name, key_prefix=d.key_prefix, created_at=d.created_at, last_used_at=d.last_used_at)
        for d in rows.scalars().all()
    ]


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_device(device_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    device = await db.get(CaptureDevice, device_id)
    if device is None or device.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such connected computer")
    await db.delete(device)
    await db.commit()


@router.post("/self/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_self(request: Request, _user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The extension's own Sign out: removes the key it was called with."""
    device_id = getattr(request.state, "capture_device_id", None)
    if device_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only a Backpack Capture key can remove itself")
    device = await db.get(CaptureDevice, device_id)
    if device is not None:
        await db.delete(device)
        await db.commit()


# ---- Send logs to schoolz --------------------------------------------------
#
# The extension keeps a step-by-step log of its last few updates on the
# device and shows it under the popup's result; "Send logs to schoolz" posts
# it here so a failed update can be worked out after the fact. It holds no
# page text and nothing about Google accounts that aren't the children's.
# Read back by admins with kids.view (GET /capture-devices/diagnostics).

DIAGNOSTICS_KEEP = timedelta(days=30)
DIAGNOSTICS_MAX_BYTES = 512_000
DIAGNOSTICS_MAX_ENTRIES = 2000


class CaptureDiagnosticsIn(BaseModel):
    extension_version: str = Field(min_length=1, max_length=20)
    platform: str | None = Field(default=None, max_length=40)
    log: list[dict] = Field(max_length=DIAGNOSTICS_MAX_ENTRIES)
    last_run: dict | None = None


class CaptureDiagnosticsSentOut(BaseModel):
    id: str
    # What the popup shows, and what the parent quotes when asking about it.
    reference: str


class CaptureDiagnosticSummaryOut(BaseModel):
    id: str
    reference: str
    created_at: datetime
    user_email: str | None
    device_name: str | None
    extension_version: str
    entries: int


class CaptureDiagnosticOut(CaptureDiagnosticSummaryOut):
    payload: dict


def _reference(diag_id: str) -> str:
    return diag_id[:8].upper()


@router.post("/diagnostics", response_model=CaptureDiagnosticsSentOut)
async def send_diagnostics(
    payload: CaptureDiagnosticsIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    body = {"platform": payload.platform, "log": payload.log, "last_run": payload.last_run}
    if len(json.dumps(body, default=str)) > DIAGNOSTICS_MAX_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "That log is too large to send")
    now = datetime.now(UTC)
    await db.execute(delete(CaptureDiagnostic).where(CaptureDiagnostic.created_at < now - DIAGNOSTICS_KEEP))
    diag = CaptureDiagnostic(
        user_id=user.id,
        capture_device_id=getattr(request.state, "capture_device_id", None),
        created_at=now,
        extension_version=payload.extension_version,
        payload=body,
    )
    db.add(diag)
    await db.commit()
    logger.info(
        "capture_diagnostics_received",
        extra={
            "diagnostic_id": diag.id,
            "user_id": user.id,
            "extension_version": payload.extension_version,
            "entries": len(payload.log),
        },
    )
    return CaptureDiagnosticsSentOut(id=diag.id, reference=_reference(diag.id))


def _diagnostic_summary(diag: CaptureDiagnostic, email: str | None, device: str | None) -> dict:
    return {
        "id": diag.id,
        "reference": _reference(diag.id),
        "created_at": diag.created_at,
        "user_email": email,
        "device_name": device,
        "extension_version": diag.extension_version,
        "entries": len((diag.payload or {}).get("log") or []),
    }


def _diagnostics_query():
    return (
        select(CaptureDiagnostic, User.email, CaptureDevice.name)
        .join(User, User.id == CaptureDiagnostic.user_id)
        .outerjoin(CaptureDevice, CaptureDevice.id == CaptureDiagnostic.capture_device_id)
    )


@router.get("/diagnostics", response_model=list[CaptureDiagnosticSummaryOut])
async def list_diagnostics(
    reference: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    _admin: User = Depends(require_permission("kids.view")),
    db: AsyncSession = Depends(get_db),
):
    """Newest first; `reference` is the code the popup showed the parent."""
    query = _diagnostics_query().order_by(CaptureDiagnostic.created_at.desc()).limit(limit)
    if reference:
        query = query.where(func.upper(func.substr(CaptureDiagnostic.id, 1, 8)) == reference.strip().upper())
    rows = (await db.execute(query)).all()
    return [CaptureDiagnosticSummaryOut(**_diagnostic_summary(d, email, device)) for d, email, device in rows]


@router.get("/diagnostics/{diagnostic_id}", response_model=CaptureDiagnosticOut)
async def get_diagnostic(
    diagnostic_id: str,
    _admin: User = Depends(require_permission("kids.view")),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(_diagnostics_query().where(CaptureDiagnostic.id == diagnostic_id))).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such log")
    diag, email, device = row
    return CaptureDiagnosticOut(**_diagnostic_summary(diag, email, device), payload=diag.payload)
