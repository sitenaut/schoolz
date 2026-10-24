"""Audit log: who did what to whom (ported from billz's SEC-17).

Two ways in, one writer:

- **Routes in `AUDITED`**: `AuditMiddleware` records every call to them,
  whatever the outcome, after the response is sent: the action, the caller
  (user, session or API key), the path parameters as the target, the status,
  a hashed address and the request id. No handler has to remember to log.
- **`note(request, ...)`** for what a route's status can't show: a key or
  secret released by a polling endpoint, a Gmail account connected by an
  OAuth callback that answers 200 either way. Written with the request.
- **`session_seen()`** for sign-ins: they happen in the browser against
  Supabase, so the first request a session makes here is the first schoolz
  hears of it (`auth.sign_in`, and `auth.mfa_passed` once it reaches aal2).

Rows go to `audit_events`, which a trigger keeps append-only. A failed write
is logged as `audit_write_failed` and never fails the request. Targets hold
ids and names only: never put a token, key or password in one.
"""
from __future__ import annotations

import hashlib
import logging
import os
from collections import OrderedDict
from typing import Any

from starlette.requests import Request

import database
from services.client_ip import client_ip

logger = logging.getLogger(__name__)

# (method, route template) -> action. tests/test_audit.py checks each one is
# a real route. Polling endpoints are left out on purpose (every poll would be
# a row); they note() the one poll that releases something.
AUDITED: dict[tuple[str, str], str] = {
    # Machine credentials and prod secrets
    ("POST", "/capture-devices/requests/{user_code}/approve"): "capture_device.approve",
    ("POST", "/capture-devices/requests/{user_code}/deny"): "capture_device.deny",
    ("DELETE", "/capture-devices/{device_id}"): "capture_device.revoke",
    ("POST", "/capture-devices/self/revoke"): "capture_device.revoke_self",
    ("POST", "/admin/api-keys"): "api_key.create",
    ("PATCH", "/admin/api-keys/{key_id}"): "api_key.update",
    ("DELETE", "/admin/api-keys/{key_id}"): "api_key.revoke",
    ("POST", "/admin/api-keys/requests/{user_code}/approve"): "api_key.device_approve",
    ("POST", "/admin/api-keys/requests/{user_code}/deny"): "api_key.device_deny",
    ("POST", "/admin/secret-requests"): "secret.request",
    ("POST", "/admin/secret-requests/{user_code}/approve"): "secret.approve",
    ("POST", "/admin/secret-requests/{user_code}/deny"): "secret.deny",
    # Roles and admins
    ("POST", "/admin/roles"): "role.create",
    ("PUT", "/admin/roles/{role_id}"): "role.update",
    ("DELETE", "/admin/roles/{role_id}"): "role.delete",
    ("PUT", "/admin/users/{user_id}/roles"): "user.set_roles",
    ("PUT", "/admin/users/{user_id}/super-admin"): "user.set_super_admin",
    # Accounts
    ("POST", "/auth/change-password"): "account.change_password",
    ("POST", "/auth/reset-password"): "account.reset_password",
    ("DELETE", "/auth/me"): "account.delete",
    # Access to a child's records
    ("POST", "/invites/{token}/accept"): "guardian.invite_accept",
    ("POST", "/student-account-invites/{token}/accept"): "student_account.invite_accept",
    ("DELETE", "/students/{student_id}/student-account"): "student_account.delete",
    # Inbox connections and scanners
    ("DELETE", "/gmail/disconnect"): "connection.disconnect",
    ("POST", "/email-scanners"): "email_scanner.create",
    ("PATCH", "/email-scanners/{scanner_id}"): "email_scanner.update",
    ("DELETE", "/email-scanners/{scanner_id}"): "email_scanner.delete",
    # Settings that change what the public sees or what it costs
    ("PUT", "/admin/chatbot"): "chatbot.settings",
    # Localz provider decisions
    ("POST", "/admin/resources/onboarding/{request_id}/approve"): "resources.onboarding_approve",
    ("POST", "/admin/resources/onboarding/{request_id}/reject"): "resources.onboarding_reject",
    ("POST", "/admin/resources/onboarding/{request_id}/merge"): "resources.onboarding_merge",
    ("POST", "/admin/resources/changes/{change_id}/approve"): "resources.change_approve",
    ("POST", "/admin/resources/changes/{change_id}/reject"): "resources.change_reject",
    ("POST", "/admin/resources/log/{log_id}/revert"): "resources.revert",
    ("POST", "/admin/resources/memberships/{membership_id}/verify"): "resources.membership_verify",
    ("POST", "/admin/resources/services/{service_id}/members"): "resources.member_add",
}

# Path parameters that are secrets in their own right: kept out of the target.
_SECRET_PARAMS = frozenset({"token"})
# Path parameters that are a credential: an invite token, a device-flow code.
SECRET_PATH_PARAMS = frozenset({"token", "user_code"})
_MAX_TARGET_VALUE = 200


def outcome_for(status: int | None) -> str:
    if status is None or status >= 500:
        return "failed"
    if status in (401, 403):
        return "denied"
    return "success" if status < 400 else "failed"


def note(request: Request, action: str, **target: Any) -> None:
    """Record `action` with this request (written after the response)."""
    request.state.audit_notes = [*getattr(request.state, "audit_notes", []), (action, _clean(target))]


# (action, session id) pairs this process has already settled, so a session
# costs one lookup per machine, not one per request.
_seen_sessions: OrderedDict[tuple[str, str], None] = OrderedDict()
_SEEN_MAX = 2000


async def session_seen(request: Request, session_id: str | None, aal: str | None) -> None:
    """Note `auth.sign_in` the first time a Supabase session is used, and
    `auth.mfa_passed` the first time it arrives at aal2. A session already
    recorded (by another machine, or before a restart) is skipped."""
    if not session_id:
        return
    actions = ["auth.sign_in"] + (["auth.mfa_passed"] if aal == "aal2" else [])
    for action in actions:
        key = (action, session_id)
        if key in _seen_sessions:
            continue
        _seen_sessions[key] = None
        while len(_seen_sessions) > _SEEN_MAX:
            _seen_sessions.popitem(last=False)
        if not await _session_recorded(action, session_id):
            note(request, action, session_id=session_id, aal=aal)


async def _session_recorded(action: str, session_id: str) -> bool:
    from sqlalchemy import select

    from models import AuditEvent

    try:
        async with database.SessionLocal() as session:
            found = await session.execute(
                select(AuditEvent.id)
                .where(AuditEvent.action == action, AuditEvent.target["session_id"].astext == session_id)
                .limit(1)
            )
            return found.scalar() is not None
    except Exception:
        logger.exception("audit_lookup_failed", extra={"action": action})
        return True  # better a missed entry than one per request


def _clean(target: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for key, value in target.items():
        if value is None or key in _SECRET_PARAMS:
            continue
        if not isinstance(value, (int, float, bool)):
            value = str(value)[:_MAX_TARGET_VALUE]
        out[str(key)[:64]] = value
    return out


def ip_hash(ip: str | None) -> str | None:
    if not ip:
        return None
    salt = os.getenv("JWT_SECRET", "schoolz-audit-salt")
    return hashlib.sha256(f"{salt}:audit:{ip}".encode()).hexdigest()


async def _write(rows: list[dict[str, Any]]) -> None:
    from models import AuditEvent

    try:
        # database.SessionLocal, not an imported name: tests swap it for their
        # rolled-back session, and rows here can never be removed.
        async with database.SessionLocal() as session:
            session.add_all(AuditEvent(**row) for row in rows)
            await session.commit()
    except Exception:
        logger.exception("audit_write_failed", extra={"actions": [r["action"] for r in rows]})


class AuditMiddleware:
    """Pure ASGI, inside the request-id middleware and outside routing: it
    reads the matched route and what auth put on request.state once the app
    has answered."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        status: list[int] = []

        async def capture(message):
            if message["type"] == "http.response.start":
                status.append(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            await self._after(scope, status[0] if status else None)

    async def _after(self, scope, status: int | None) -> None:
        state = scope.get("state") or {}
        notes = state.get("audit_notes") or []
        route = getattr(scope.get("route"), "path", None)
        action = AUDITED.get((scope["method"], route)) if route else None
        if action is None and not notes:
            return

        api_key_id = state.get("api_key_id")
        user_id = state.get("user_id")
        credential = "api_key" if api_key_id else "capture_key" if state.get("capture_device_id") else "session"
        base = {
            "status": status,
            "actor_user_id": user_id,
            "credential": credential if user_id else None,
            "api_key_id": api_key_id,
            "method": scope["method"],
            "route": route,
            "ip_hash": ip_hash(client_ip(Request(scope))),
            "request_id": state.get("request_id"),
        }
        rows = []
        if action is not None:
            target = _clean(dict(scope.get("path_params") or {}))
            rows.append({**base, "action": action, "outcome": outcome_for(status), "target": target or None})
        rows.extend({**base, "action": a, "outcome": "success", "target": t or None} for a, t in notes)
        await _write(rows)
