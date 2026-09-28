import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

import database
from main import app
from models import User


async def _register(client: AsyncClient, prefix: str, *, super_admin: bool = False) -> tuple[dict, str]:
    run_id = uuid.uuid4().hex[:8]
    email = f"{prefix}_{run_id}@example.com"
    reg = await client.post("/auth/register", json={"email": email, "username": f"{prefix}_{run_id}", "password": "password123"})
    assert reg.status_code == 201, reg.text
    headers = {"authorization": f"Bearer {reg.json()['access_token']}"}
    me = (await client.get("/auth/me", headers=headers)).json()
    if super_admin:
        async with database.SessionLocal() as db:
            await db.execute(update(User).where(User.email == email).values(is_admin=True))
            await db.commit()
    return headers, me["id"]


@pytest.mark.anyio
async def test_role_scopes_which_admin_endpoints_a_user_can_reach():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        boss, _ = await _register(client, "boss", super_admin=True)
        helper, helper_id = await _register(client, "helper")

        assert (await client.get("/scheduled-jobs", headers=helper)).status_code == 403
        assert (await client.get("/auth/me", headers=helper)).json()["permissions"] == []

        role = await client.post(
            "/admin/roles", headers=boss, json={"name": f"Scans {uuid.uuid4().hex[:6]}", "permissions": ["scans.manage"]}
        )
        assert role.status_code == 201, role.text
        role_id = role.json()["id"]
        assigned = await client.put(f"/admin/users/{helper_id}/roles", headers=boss, json={"role_ids": [role_id]})
        assert assigned.status_code == 200 and assigned.json()["role_ids"] == [role_id]

        assert (await client.get("/scheduled-jobs", headers=helper)).status_code == 200
        assert (await client.get("/survey/responses", headers=helper)).status_code == 403
        me = (await client.get("/auth/me", headers=helper)).json()
        assert me["permissions"] == ["scans.manage", "scans.view"] and me["is_admin"] is False

        # Editing the role takes effect on the next request.
        upd = await client.put(f"/admin/roles/{role_id}", headers=boss, json={"name": role.json()["name"], "permissions": ["analytics.view"]})
        assert upd.status_code == 200
        assert (await client.get("/scheduled-jobs", headers=helper)).status_code == 403
        assert (await client.get("/survey/responses", headers=helper)).status_code == 200

        # Deleting the role revokes it.
        assert (await client.delete(f"/admin/roles/{role_id}", headers=boss)).status_code == 204
        assert (await client.get("/survey/responses", headers=helper)).status_code == 403


@pytest.mark.anyio
async def test_view_permission_reads_but_cannot_change():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        boss, _ = await _register(client, "boss", super_admin=True)
        helper, helper_id = await _register(client, "viewer")
        role = (await client.post("/admin/roles", headers=boss, json={"name": f"Viewer {uuid.uuid4().hex[:6]}", "permissions": ["scans.view", "inbox.view"]})).json()
        await client.put(f"/admin/users/{helper_id}/roles", headers=boss, json={"role_ids": [role["id"]]})

        assert (await client.get("/scheduled-jobs", headers=helper)).status_code == 200
        assert (await client.get("/contact-messages", headers=helper)).status_code == 200
        job = {"name": "x", "kind": "smore.scan", "cron_expr": "0 * * * *", "params": {}}
        assert (await client.post("/scheduled-jobs", headers=helper, json=job)).status_code == 403
        assert (await client.post("/contact-messages/read-all", headers=helper)).status_code == 403
        assert (await client.get("/admin/config/export", headers=helper)).status_code == 403

        # A write permission implies its read permission.
        await client.put(f"/admin/roles/{role['id']}", headers=boss, json={"name": role["name"], "permissions": ["config.manage"]})
        assert set((await client.get("/auth/me", headers=helper)).json()["permissions"]) == {"config.manage", "config.view"}
        assert (await client.get("/admin/config/export", headers=helper)).status_code == 200


@pytest.mark.anyio
async def test_scoped_admin_cannot_manage_users_or_roles():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        boss, _ = await _register(client, "boss", super_admin=True)
        helper, helper_id = await _register(client, "helper")
        role = (await client.post("/admin/roles", headers=boss, json={"name": f"All {uuid.uuid4().hex[:6]}", "permissions": sorted(
            p["key"] for p in (await client.get("/admin/permissions", headers=boss)).json())})).json()
        await client.put(f"/admin/users/{helper_id}/roles", headers=boss, json={"role_ids": [role["id"]]})

        for method, path, body in [
            ("get", "/admin/users", None),
            ("get", "/admin/roles", None),
            ("post", "/admin/roles", {"name": "x", "permissions": []}),
            ("put", f"/admin/users/{helper_id}/super-admin", {"is_admin": True}),
        ]:
            r = await client.request(method, path, headers=helper, json=body)
            assert r.status_code == 403, (path, r.status_code)


@pytest.mark.anyio
async def test_role_validation_and_duplicate_names():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        boss, _ = await _register(client, "boss", super_admin=True)
        bad = await client.post("/admin/roles", headers=boss, json={"name": "Bad", "permissions": ["nope.manage"]})
        assert bad.status_code == 422
        name = f"Dup {uuid.uuid4().hex[:6]}"
        assert (await client.post("/admin/roles", headers=boss, json={"name": name, "permissions": []})).status_code == 201
        assert (await client.post("/admin/roles", headers=boss, json={"name": name.upper(), "permissions": []})).status_code == 409


@pytest.mark.anyio
async def test_promote_and_demote_super_admin():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        boss, boss_id = await _register(client, "boss", super_admin=True)
        other, other_id = await _register(client, "other")

        assert (await client.get("/admin/users", headers=other)).status_code == 403
        promoted = await client.put(f"/admin/users/{other_id}/super-admin", headers=boss, json={"is_admin": True})
        assert promoted.status_code == 200 and promoted.json()["is_admin"] is True
        assert (await client.get("/admin/users", headers=other)).status_code == 200
        me = (await client.get("/auth/me", headers=other)).json()
        assert me["is_admin"] is True and "config.manage" in me["permissions"]

        # Nobody can strip their own super admin access.
        own = await client.put(f"/admin/users/{boss_id}/super-admin", headers=boss, json={"is_admin": False})
        assert own.status_code == 400

        # The new super admin can demote the original.
        demoted = await client.put(f"/admin/users/{boss_id}/super-admin", headers=other, json={"is_admin": False})
        assert demoted.status_code == 200 and demoted.json()["is_admin"] is False
        assert (await client.get("/admin/users", headers=boss)).status_code == 403


@pytest.mark.anyio
async def test_user_list_search_and_admins_only_filter():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        boss, boss_id = await _register(client, "boss", super_admin=True)
        helper, helper_id = await _register(client, "needle")
        found = (await client.get("/admin/users", headers=boss, params={"q": "needle"})).json()
        assert [u["id"] for u in found["items"]] == [helper_id]
        admins = (await client.get("/admin/users", headers=boss, params={"admins_only": True, "limit": 200})).json()
        ids = {u["id"] for u in admins["items"]}
        assert boss_id in ids and helper_id not in ids
