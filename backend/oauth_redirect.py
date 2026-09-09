import os

from fastapi import HTTPException, status


def resolve_redirect_uri(path: str) -> str:
    """Absolute redirect URI for an OAuth callback, rooted at this backend's
    own public URL (NOT the frontend's - unlike billz, schoolz's frontend
    and backend are separate origins/apps with no shared reverse proxy, so
    there's no safe way to derive this from a request Origin header)."""
    base = os.getenv("PUBLIC_API_URL")
    if not base:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "PUBLIC_API_URL is not configured - required to build the OAuth redirect URI",
        )
    return f"{base.rstrip('/')}{path}"
