import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


@pytest.mark.anyio
async def test_gmail_and_scanner_endpoints_are_admin_only():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        tag = uuid.uuid4().hex[:8]
        res = await client.post("/auth/register", json={"email": f"g_{tag}@example.com", "username": f"g_{tag}", "password": "password123"})
        headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
        for method, path in (
            ("get", "/email-scanners"),
            ("post", "/email-scanners"),
            ("get", "/gmail/auth-url"),
            ("get", "/gmail/connections"),
            ("get", "/school-emails"),
        ):
            r = await client.request(method, path, headers=headers)
            assert r.status_code == 403, f"{method} {path}: {r.status_code}"
        assert (await client.get("/email-scanners")).status_code == 401
