"""Every route's gate, saved and enforced.

Almost everything in schoolz is public on purpose, which makes "public" the
easy thing to get by accident: a new router with no auth dependency at all
is public too. So every route's gate is worked out from its dependencies and
compared with tests/snapshots/route_gates.txt. A new route, or a changed
gate, fails here until the snapshot is regenerated on purpose:

    UPDATE_SNAPSHOTS=1 python -m pytest tests/test_route_gates.py

and the diff shows up in review. Gates are, strongest first:

    super_admin        require_super_admin (or a check built on it)
    perm:<key>         require_permission("<key>")
    login              get_current_user
    optional           get_optional_user - answers anonymous callers too
    public             no auth dependency

A route can still check more inside its handler (a guardian's own child);
this is the floor, not the whole story.

The other tests check the gates hold: anonymous callers get 401 from every
gated route, and a login with no role gets 403 from every admin route."""

import os
import re
import uuid
from pathlib import Path

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from httpx import ASGITransport, AsyncClient

import auth
import database
from main import app
from models import School
from permissions import PERMISSION_KEYS
from routers.admin_secret_requests import require_requester

SNAPSHOT = Path(__file__).resolve().parent / "snapshots" / "route_gates.txt"

_PERMISSION_DEPS = {auth.require_permission(key): f"perm:{key}" for key in PERMISSION_KEYS}
_RANK = {"public": 0, "optional": 1, "login": 2, "perm": 3, "super_admin": 4}


def _gate_of(call) -> str | None:
    if call is auth.require_super_admin or call is require_requester:
        return "super_admin"
    if call in _PERMISSION_DEPS:
        return _PERMISSION_DEPS[call]
    if call is auth.get_current_user:
        return "login"
    if call is auth.get_optional_user:
        return "optional"
    return None


def _gates(dependant) -> set[str]:
    found = set()
    for dep in dependant.dependencies:
        gate = _gate_of(dep.call)
        if gate:
            found.add(gate)
        found |= _gates(dep)
    return found


def _strongest(gates: set[str]) -> str:
    return max(gates, key=lambda g: _RANK[g.split(":")[0]], default="public")


def route_gates() -> list[tuple[str, str, str]]:
    # FastAPI >= 0.13x keeps included routers nested in app.routes;
    # iter_route_contexts is its public way to walk the effective routes
    # (path with prefixes, dependencies with the router's own).
    rows = []
    for context in iter_route_contexts(app.routes):
        if not isinstance(context.original_route, APIRoute):
            continue
        gate = _strongest(_gates(context.dependant))
        for method in sorted(context.methods - {"HEAD", "OPTIONS"}):
            rows.append((context.path, method, gate))
    return sorted(set(rows))


def render(rows: list[tuple[str, str, str]]) -> str:
    lines = ["# Generated. See tests/test_route_gates.py.", ""]
    lines += [f"{method:<6} {path}  {gate}" for path, method, gate in rows]
    return "\n".join(lines) + "\n"


def test_every_routes_gate_matches_the_snapshot():
    current = render(route_gates())
    if os.environ.get("UPDATE_SNAPSHOTS"):
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(current)
    assert SNAPSHOT.exists(), "No snapshot yet: run with UPDATE_SNAPSHOTS=1"
    saved = SNAPSHOT.read_text()
    if current != saved:
        import difflib

        diff = "\n".join(list(difflib.unified_diff(saved.splitlines(), current.splitlines(), "snapshot", "app", lineterm="", n=0))[:80])
        raise AssertionError(
            "A route was added, removed or changed gate. If that is intended, regenerate with "
            f"UPDATE_SNAPSHOTS=1 and commit tests/snapshots/route_gates.txt.\n{diff}"
        )


def _url(path: str, school: str) -> str:
    # School routes resolve {school_id} before the auth check (it's declared
    # first), so a made-up id would get 404 and never reach the gate. School
    # ids aren't secret - every school page is public - so that order is fine;
    # a real school lets the test see the gate itself.
    return re.sub(r"\{[^}]+\}", "1", path.replace("{school_id}", school))


async def _school() -> str:
    async with database.SessionLocal() as db:
        tag = uuid.uuid4().hex[:8]
        school = School(name=f"Gate Test {tag}", slug=f"gate-test-{tag}", school_type="high")
        db.add(school)
        await db.commit()
        return school.slug


def _body(method: str) -> dict | None:
    return {} if method in ("POST", "PUT", "PATCH") else None


@pytest.mark.anyio
async def test_anonymous_callers_are_refused_by_every_gated_route():
    reached = []
    school = await _school()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for path, method, gate in route_gates():
            if gate in ("public", "optional"):
                continue
            res = await client.request(method, _url(path, school), json=_body(method))
            if res.status_code != 401:
                reached.append(f"{method} {path} ({gate}) -> {res.status_code}")
    assert reached == [], "\n".join(reached)


@pytest.mark.anyio
async def test_a_login_with_no_role_is_refused_by_every_admin_route():
    reached = []
    school = await _school()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        run_id = uuid.uuid4().hex[:8]
        reg = await client.post(
            "/auth/register",
            json={"email": f"nobody_{run_id}@example.com", "username": f"nobody_{run_id}", "password": "password123"},
        )
        assert reg.status_code == 201, reg.text
        headers = {"authorization": f"Bearer {reg.json()['access_token']}"}
        for path, method, gate in route_gates():
            if not (gate == "super_admin" or gate.startswith("perm:")):
                continue
            res = await client.request(method, _url(path, school), headers=headers, json=_body(method))
            if res.status_code != 403:
                reached.append(f"{method} {path} ({gate}) -> {res.status_code}")
    assert reached == [], "\n".join(reached)
