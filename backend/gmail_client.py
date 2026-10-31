"""Shared Gmail API helpers used by both the OAuth router and the email
scanner service. All calls run in a worker thread via anyio.to_thread -
httplib2 (used internally by googleapiclient) is not safe to share across
threads/event-loop callbacks."""

import os
from datetime import UTC

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
            token.token_expiry = creds.expiry.replace(tzinfo=UTC) if creds.expiry else None
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    return await anyio.to_thread.run_sync(_refresh_and_build)


def fetch_all_messages_sync(service, query: str, skip_ids: set[str], max_results: int = 500) -> tuple[int, list[dict]]:
    """(how many messages matched `query`, the full payloads of those not in
    `skip_ids`). Deliberately synchronous/single-threaded - listing and
    fetching must share the same httplib2 connection."""
    matched = 0
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
            matched += 1
            if item["id"] in skip_ids:
                continue
            full = service.users().messages().get(userId="me", id=item["id"], format="full").execute()
            messages.append(full)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return matched, messages
