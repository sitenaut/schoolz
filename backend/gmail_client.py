"""Shared Gmail API helpers used by both the OAuth router and the email
scanner service. All calls run in a worker thread via anyio.to_thread -
httplib2 (used internally by googleapiclient) is not safe to share across
threads/event-loop callbacks."""

import os
from datetime import timezone

import anyio
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy.ext.asyncio import AsyncSession

from models import GmailToken

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

TOKEN_URI = "https://oauth2.googleapis.com/token"


def _build_credentials(token: GmailToken) -> Credentials:
    return Credentials(
        token=token.access_token,
        refresh_token=token.refresh_token,
        token_uri=TOKEN_URI,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        scopes=GMAIL_SCOPES,
        expiry=token.token_expiry.replace(tzinfo=None) if token.token_expiry else None,
    )


async def get_gmail_service(db: AsyncSession, token: GmailToken):
    """Builds a Gmail API client for this token, refreshing it first if
    expired. Caller is responsible for `db.commit()` afterwards - this
    mutates `token`'s access_token/token_expiry in place when refreshed."""

    def _refresh_and_build():
        creds = _build_credentials(token)
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
            token.access_token = creds.token
            token.token_expiry = creds.expiry.replace(tzinfo=timezone.utc) if creds.expiry else None
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    return await anyio.to_thread.run_sync(_refresh_and_build)


def fetch_all_messages_sync(service, query: str, skip_ids: set[str], max_results: int = 500) -> list[dict]:
    """Lists + fetches full message payloads matching `query`, skipping any
    id already in `skip_ids`. Deliberately synchronous/single-threaded -
    listing and fetching must share the same httplib2 connection."""
    messages = []
    page_token = None
    while True:
        resp = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results, pageToken=page_token)
            .execute()
        )
        for item in resp.get("messages", []):
            if item["id"] in skip_ids:
                continue
            full = service.users().messages().get(userId="me", id=item["id"], format="full").execute()
            messages.append(full)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return messages


def extract_header(message: dict, name: str) -> str | None:
    headers = message.get("payload", {}).get("headers", [])
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value")
    return None


def extract_body_text(message: dict) -> str:
    """Best-effort plain-text body extraction, falling back to the snippet."""
    import base64

    def _walk(part: dict) -> str | None:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            data = part["body"]["data"]
            return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
        for sub in part.get("parts", []) or []:
            text = _walk(sub)
            if text:
                return text
        return None

    payload = message.get("payload", {})
    return _walk(payload) or message.get("snippet", "")
