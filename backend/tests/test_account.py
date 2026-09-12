import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


async def _register(client: AsyncClient) -> tuple[str, str, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    email, username = f"acct_{tag}@example.com", f"acct_{tag}"
    res = await client.post("/auth/register", json={"email": email, "username": username, "password": "password123"})
    assert res.status_code == 201, res.text
    return email, username, {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _login(client: AsyncClient, ident: str, password: str) -> int:
    return (await client.post("/auth/login", json={"username_or_email": ident, "password": password})).status_code


@pytest.mark.anyio
async def test_me_reports_sign_in_method_and_username_update():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, username, headers = await _register(client)
        me = await client.get("/auth/me", headers=headers)
        assert me.json()["sign_in_method"] == "password"
        assert me.json()["created_at"]

        new_name = f"{username}_renamed"
        res = await client.patch("/auth/me", json={"username": new_name}, headers=headers)
        assert res.status_code == 200 and res.json()["username"] == new_name

        _, other_name, other_headers = await _register(client)
        clash = await client.patch("/auth/me", json={"username": new_name}, headers=other_headers)
        assert clash.status_code == 409
        assert other_name  # unchanged account still fine


@pytest.mark.anyio
async def test_change_password_requires_current_and_takes_effect():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        email, _, headers = await _register(client)

        wrong = await client.post("/auth/change-password", json={"current_password": "nope", "new_password": "newpassword1"}, headers=headers)
        assert wrong.status_code == 400

        ok = await client.post("/auth/change-password", json={"current_password": "password123", "new_password": "newpassword1"}, headers=headers)
        assert ok.status_code == 204
        assert await _login(client, email, "password123") == 401
        assert await _login(client, email, "newpassword1") == 200


@pytest.mark.anyio
async def test_forgot_and_reset_password_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        email, _, _ = await _register(client)

        unknown = await client.post("/auth/forgot-password", json={"email": "nobody@example.com"})
        assert unknown.status_code == 200 and unknown.json()["reset_token"] is None

        res = await client.post("/auth/forgot-password", json={"email": email})
        token = res.json()["reset_token"]
        assert token

        bad = await client.post("/auth/reset-password", json={"token": "bogus", "new_password": "resetpass99"})
        assert bad.status_code == 400

        good = await client.post("/auth/reset-password", json={"token": token, "new_password": "resetpass99"})
        assert good.status_code == 200 and good.json()["access_token"]
        assert await _login(client, email, "resetpass99") == 200

        # One-shot: the same token can't be replayed.
        replay = await client.post("/auth/reset-password", json={"token": token, "new_password": "another999"})
        assert replay.status_code == 400


@pytest.mark.anyio
async def test_delete_account_requires_confirmation_and_password():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        email, _, headers = await _register(client)

        no_confirm = await client.request("DELETE", "/auth/me", json={"confirm": "delete", "password": "password123"}, headers=headers)
        assert no_confirm.status_code == 400

        wrong_pw = await client.request("DELETE", "/auth/me", json={"confirm": "DELETE", "password": "wrong"}, headers=headers)
        assert wrong_pw.status_code == 400

        gone = await client.request("DELETE", "/auth/me", json={"confirm": "DELETE", "password": "password123"}, headers=headers)
        assert gone.status_code == 204
        assert await _login(client, email, "password123") == 401
        assert (await client.get("/auth/me", headers=headers)).status_code == 401
