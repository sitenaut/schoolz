"""Reading the audit log (not the data audit at /admin/audit). Super admins
only; there is no way to change or remove an event (the table is
append-only, services/audit.py)."""
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_super_admin
from database import get_db
from models import AuditEvent, User

router = APIRouter(prefix="/admin/audit-log", tags=["admin-audit-log"], dependencies=[Depends(require_super_admin)])


class AuditEventOut(BaseModel):
    id: int
    ts: datetime
    action: str
    outcome: str
    status: int | None
    actor_user_id: str | None
    actor: str | None
    credential: str | None
    api_key_id: str | None
    method: str | None
    route: str | None
    target: dict[str, Any] | None
    request_id: str | None


class AuditPage(BaseModel):
    events: list[AuditEventOut]
    # Pass as `before_id` for the next (older) page; null when there is none.
    next_before_id: int | None


@router.get("", response_model=AuditPage)
async def list_audit_events(
    db: Annotated[AsyncSession, Depends(get_db)],
    action: Annotated[str | None, Query(max_length=64, description="Exact action, or a prefix ending in '.' (`api_key.`)")] = None,
    outcome: Annotated[str | None, Query(pattern="^(success|denied|failed)$")] = None,
    actor_user_id: Annotated[str | None, Query(max_length=36)] = None,
    before_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    query = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit + 1)
    if action:
        query = query.where(
            AuditEvent.action.startswith(action, autoescape=True) if action.endswith(".") else AuditEvent.action == action
        )
    if outcome:
        query = query.where(AuditEvent.outcome == outcome)
    if actor_user_id:
        query = query.where(AuditEvent.actor_user_id == actor_user_id)
    if before_id is not None:
        query = query.where(AuditEvent.id < before_id)
    rows = list((await db.execute(query)).scalars())
    more = len(rows) > limit
    rows = rows[:limit]

    ids = {r.actor_user_id for r in rows if r.actor_user_id}
    names = {u.id: u.email for u in (await db.execute(select(User).where(User.id.in_(ids)))).scalars()} if ids else {}
    return AuditPage(
        events=[
            AuditEventOut(
                **{c: getattr(r, c) for c in AuditEventOut.model_fields if c != "actor"},
                actor=names.get(r.actor_user_id) if r.actor_user_id else None,
            )
            for r in rows
        ],
        next_before_id=rows[-1].id if more and rows else None,
    )
