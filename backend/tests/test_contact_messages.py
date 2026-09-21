import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from tests.test_students import _make_admin, _register


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_contact_form_lands_in_the_shared_admin_inbox():
    run = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin1 = await _register(client, f"a1_{run}@example.com", f"a1_{run}")
        admin2 = await _register(client, f"a2_{run}@example.com", f"a2_{run}")
        guardian = await _register(client, f"g_{run}@example.com", f"g_{run}")
        await _make_admin(f"a1_{run}@example.com")
        await _make_admin(f"a2_{run}@example.com")

        base = (await client.get("/contact-messages/unread-count", headers=auth(admin1))).json()["count"]

        res = await client.post("/contact-messages", json={"name": "Pat", "email": "pat@example.com", "message": f"hello {run}"})
        assert res.status_code == 201
        # Honeypot: accepted with the same response, never stored.
        assert (await client.post("/contact-messages", json={"message": f"spam {run}", "website": "x"})).status_code == 201
        assert (await client.post("/contact-messages", json={"message": "   "})).status_code == 400

        # Shared: both admins see the same unread message.
        for token in (admin1, admin2):
            assert (await client.get("/contact-messages/unread-count", headers=auth(token))).json()["count"] == base + 1
        messages = (await client.get("/contact-messages", headers=auth(admin2))).json()
        assert any(m["message"] == f"hello {run}" for m in messages)
        assert not any(m["message"] == f"spam {run}" for m in messages)

        # Admin-only.
        assert (await client.get("/contact-messages", headers=auth(guardian))).status_code == 403
        assert (await client.get("/contact-messages/unread-count")).status_code == 401

        # One admin reading clears it for both.
        await client.post("/contact-messages/read-all", headers=auth(admin1))
        assert (await client.get("/contact-messages/unread-count", headers=auth(admin2))).json()["count"] == 0

        mine = next(m for m in messages if m["message"] == f"hello {run}")
        assert (await client.post(f"/contact-messages/{mine['id']}/unread", headers=auth(admin2))).json()["read_at"] is None
        assert (await client.delete(f"/contact-messages/{mine['id']}", headers=auth(admin1))).status_code == 204
