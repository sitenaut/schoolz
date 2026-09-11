from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import JWT_ALGORITHM, JWT_SECRET, require_admin
from database import get_db
from gmail_client import GMAIL_SCOPES, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, TOKEN_URI
from models import GmailToken, User
from oauth_redirect import resolve_redirect_uri

router = APIRouter(prefix="/gmail", tags=["gmail"])

_STATE_EXPIRY_MINUTES = 10


@router.get("/auth-url")
async def auth_url(user: User = Depends(require_admin)):
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google OAuth is not configured")

    redirect_uri = resolve_redirect_uri("/gmail/callback")
    now = datetime.now(timezone.utc)
    state = jwt.encode(
        {"user_id": user.id, "redirect_uri": redirect_uri, "exp": now + timedelta(minutes=_STATE_EXPIRY_MINUTES)},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GMAIL_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return {"url": f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"}


def _popup_response(message: str) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html><body><script>
        window.opener && window.opener.postMessage('{message}', '*');
        window.close();
        </script></body></html>"""
    )


@router.get("/callback")
async def callback(code: str | None = None, state: str | None = None, db: AsyncSession = Depends(get_db)):
    if not code or not state:
        return _popup_response("gmail:error")
    try:
        payload = jwt.decode(state, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return _popup_response("gmail:error")

    user_id = payload["user_id"]
    redirect_uri = payload["redirect_uri"]
    # The state is only ever minted for an admin (auth_url above), but the
    # popup lands here unauthenticated - re-check rather than trust the
    # signed blob alone in case the user was demoted mid-flow.
    owner = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not owner or not owner.is_admin:
        return _popup_response("gmail:error")

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            TOKEN_URI,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            return _popup_response("gmail:error")
        tokens = token_resp.json()

        userinfo_resp = await client.get(
            "https://www.googleapis.com/oauth2/v1/userinfo",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        if userinfo_resp.status_code != 200:
            return _popup_response("gmail:error")
        google_email = userinfo_resp.json()["email"]

    expiry = datetime.now(timezone.utc) + timedelta(seconds=tokens.get("expires_in", 3600))

    result = await db.execute(
        select(GmailToken).where(GmailToken.user_id == user_id, GmailToken.google_email == google_email)
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.access_token = tokens["access_token"]
        if tokens.get("refresh_token"):
            existing.refresh_token = tokens["refresh_token"]
        existing.token_expiry = expiry
    else:
        if "refresh_token" not in tokens:
            # Shouldn't happen with access_type=offline+prompt=consent, but
            # without one we can never refresh later - bail rather than
            # silently store a token that will die in ~1 hour.
            return _popup_response("gmail:error")
        db.add(
            GmailToken(
                user_id=user_id,
                google_email=google_email,
                access_token=tokens["access_token"],
                refresh_token=tokens["refresh_token"],
                token_expiry=expiry,
            )
        )
    await db.commit()
    return _popup_response("gmail:connected")


@router.get("/connections")
async def list_connections(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GmailToken).where(GmailToken.user_id == user.id))
    return [
        {"google_email": t.google_email, "last_synced_at": t.last_synced_at, "created_at": t.created_at}
        for t in result.scalars().all()
    ]


@router.delete("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(google_email: str, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(GmailToken).where(GmailToken.user_id == user.id, GmailToken.google_email == google_email)
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not connected")
    await db.delete(token)
    await db.commit()
