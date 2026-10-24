"""Data audit (services/data_audit.py). The district wording is public
(`/audit`, no account needed); under `/admin/audit` the reads need
`audit.view` and anything that changes state needs `audit.manage`.

A view-only caller always gets the district audience: internal wording,
error codes, job names and ids are never computed into their response. A
manager gets the internal audience by default and can ask for
`audience=district` to preview what a district would see.

The district filter is a convenience, not a permission: the district
wording is public, so anyone may read every district."""
import csv
import io
import os
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import database
from auth import get_effective_permissions, require_permission
from database import get_db
from models import AuditNotPublished, District, School, User
from scheduler.registry import registry
from services import data_audit as audit
from services.response_cache import SingleFlightTTLCache

router = APIRouter(prefix="/admin/audit", tags=["admin-audit"])
public_router = APIRouter(prefix="/audit", tags=["audit"])

# The public grid, per (district, detail), and the catalog's per-point
# counts. Each request evaluated every school's data points on the API's one
# CPU (up to 3.5s on prod), and the answer only moves when a scan finishes;
# `generated_at` says how old it is. The admin views are never cached - an
# admin re-checks them after a run-now. 0 disables it; the test suite does.
_PUBLIC_GRID = SingleFlightTTLCache(ttl_s=float(os.getenv("AUDIT_CACHE_TTL_S", "600")), max_total_bytes=8 * 1024 * 1024)
# The public CSV (~1.7 MB for every school) evaluates the same, and is kept
# apart so a download never pushes the grid out.
_PUBLIC_CSV = SingleFlightTTLCache(ttl_s=_PUBLIC_GRID.ttl_s, max_total_bytes=4 * 1024 * 1024)


async def _audience(request: Request, db: AsyncSession, user: User, requested: str | None) -> str:
    can_manage = "audit.manage" in await get_effective_permissions(request, db, user)
    if not can_manage:
        return "district"
    return "district" if requested == "district" else "internal"


async def _schools(db: AsyncSession, district_id: str | None, school_id: str | None = None) -> list[School]:
    q = select(School).order_by(School.name)
    if district_id:
        q = q.where(School.district_id == district_id)
    if school_id:
        q = q.where(or_(School.id == school_id, School.slug == school_id))
    return list((await db.execute(q)).scalars())


async def _one_school(db: AsyncSession, school_id: str) -> School:
    schools = await _schools(db, None, school_id)
    if not schools:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")
    return schools[0]


def _school_row(school: School, ctx: audit.AuditContext, audience: str, full: bool) -> dict:
    findings = audit.audit_school(school, ctx)
    return {
        **audit.school_summary(school, ctx),
        "counts": audit.counts_for(f.status for f in findings.values()),
        "cells": {k: audit.render_cell(audit.POINTS_BY_KEY[k], f, ctx, audience, full=full) for k, f in findings.items()},
    }


async def _grid(db: AsyncSession, aud: str, district_id: str | None, detail: bool) -> dict:
    schools = await _schools(db, district_id)
    ctx = await audit.load_context(db, schools)
    rows = [_school_row(s, ctx, aud, detail) for s in schools]
    districts = (await db.execute(select(District.id, District.name).order_by(District.name))).all()
    return {
        "generated_at": ctx.now.isoformat(),
        "audience": aud,
        "data_points": audit.catalog(aud),
        "districts": [{"id": d.id, "name": d.name} for d in districts],
        "schools": rows,
        "counts": audit.counts_for(c["status"] for r in rows for c in r["cells"].values()),
    }


async def _data_points(db: AsyncSession, aud: str, district_id: str | None) -> dict:
    schools = await _schools(db, district_id)
    ctx = await audit.load_context(db, schools)
    per_school = [audit.audit_school(s, ctx) for s in schools]
    rows = []
    for row in audit.catalog(aud):
        row["counts"] = audit.counts_for(f[row["key"]].status for f in per_school)
        rows.append(row)
    return {"generated_at": ctx.now.isoformat(), "audience": aud, "school_count": len(schools), "data_points": rows}


async def _school_audit(db: AsyncSession, aud: str, school_id: str) -> dict:
    school = await _one_school(db, school_id)
    ctx = await audit.load_context(db, [school])
    return {"generated_at": ctx.now.isoformat(), "audience": aud, "data_points": audit.catalog(aud),
            "school": _school_row(school, ctx, aud, True)}


def _keep(statuses: str | None) -> frozenset[str] | None:
    return frozenset(statuses.split(",")) & frozenset(audit.STATUS_LABELS) if statuses else None


async def _csv_body(db: AsyncSession, aud: str, district_id: str | None, school_id: str | None, keep: frozenset[str] | None) -> bytes:
    schools = await _schools(db, district_id, school_id)
    ctx = await audit.load_context(db, schools)
    buf = io.StringIO()
    w = csv.writer(buf)
    header = ["District", "School", "School type", "Group", "Data point", "Status", "Reason", "Why", "Next step", "Last good data", "Collected by"]
    if aud == "internal":
        header += ["Error code", "District wording: why", "District wording: next step"]
    w.writerow(header)
    for s in schools:
        summary = audit.school_summary(s, ctx)
        for key, f in audit.audit_school(s, ctx).items():
            if keep is not None and f.status not in keep:
                continue
            p = audit.POINTS_BY_KEY[key]
            c = audit.render_cell(p, f, ctx, aud)
            row = [summary["district_name"] or "", s.name, summary["kind_label"], p.group, p.label, audit.STATUS_LABELS[f.status],
                   c["tag"], c["why"], c["next"], c["last_label"], c["collected_by"]]
            if aud == "internal":
                row += [c["error_code"] or "", c["why_district"], c["next_district"]]
            w.writerow(row)
    return buf.getvalue().encode()


def _csv_response(body: bytes) -> StreamingResponse:
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    return StreamingResponse(iter([body]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="data-audit-{stamp}.csv"'})


_AUDIENCE = Query(default=None, pattern="^(internal|district)$")
_STATUSES = Query(default=None, description="Comma-separated statuses to keep, e.g. failing,stale,not_collecting")


@router.get("")
async def get_audit(
    request: Request,
    district_id: str | None = None,
    audience: str | None = _AUDIENCE,
    detail: bool = False,
    user: User = Depends(require_permission("audit.view")),
    db: AsyncSession = Depends(get_db),
):
    """Every school x data point. Cells are just status + tag unless
    `detail=true` (the printable reports want the why/next for each)."""
    return await _grid(db, await _audience(request, db, user, audience), district_id, detail)


@router.get("/data-points")
async def get_data_points(
    request: Request,
    district_id: str | None = None,
    audience: str | None = _AUDIENCE,
    user: User = Depends(require_permission("audit.view")),
    db: AsyncSession = Depends(get_db),
):
    """One row per data point, tallied across the (filtered) schools."""
    return await _data_points(db, await _audience(request, db, user, audience), district_id)


@router.get("/schools/{school_id}")
async def get_school_audit(
    school_id: str,
    request: Request,
    audience: str | None = _AUDIENCE,
    user: User = Depends(require_permission("audit.view")),
    db: AsyncSession = Depends(get_db),
):
    return await _school_audit(db, await _audience(request, db, user, audience), school_id)


@router.get("/export.csv")
async def export_csv(
    request: Request,
    district_id: str | None = None,
    school_id: str | None = None,
    audience: str | None = _AUDIENCE,
    statuses: str | None = _STATUSES,
    user: User = Depends(require_permission("audit.view")),
    db: AsyncSession = Depends(get_db),
):
    return _csv_response(await _csv_body(db, await _audience(request, db, user, audience), district_id, school_id, _keep(statuses)))


# --- public: the district wording, no account needed -------------------------

@public_router.get("")
async def public_audit(district_id: str | None = None, detail: bool = False, db: AsyncSession = Depends(get_db)):
    if not _PUBLIC_GRID.enabled:
        return await _grid(db, "district", district_id, detail)

    async def compute() -> bytes:
        # Its own session: other visitors wait on this same computation.
        async with database.SessionLocal() as own_db:
            return JSONResponse(jsonable_encoder(await _grid(own_db, "district", district_id, detail))).body

    body = await _PUBLIC_GRID.get_or_compute(("grid", district_id, detail), compute)
    return Response(content=body, media_type="application/json")


@public_router.get("/data-points")
async def public_data_points(district_id: str | None = None, db: AsyncSession = Depends(get_db)):
    """The public catalog page asks for this on every visit."""
    if not _PUBLIC_GRID.enabled:
        return await _data_points(db, "district", district_id)

    async def compute() -> bytes:
        async with database.SessionLocal() as own_db:
            return JSONResponse(jsonable_encoder(await _data_points(own_db, "district", district_id))).body

    body = await _PUBLIC_GRID.get_or_compute(("data-points", district_id), compute)
    return Response(content=body, media_type="application/json")


@public_router.get("/schools/{school_id}")
async def public_school_audit(school_id: str, db: AsyncSession = Depends(get_db)):
    return await _school_audit(db, "district", school_id)


@public_router.get("/export.csv")
async def public_export_csv(district_id: str | None = None, school_id: str | None = None, statuses: str | None = _STATUSES,
                            db: AsyncSession = Depends(get_db)):
    keep = _keep(statuses)
    # One school's rows are cheap; caching them would only let made-up ids
    # fill the cache.
    if school_id or not _PUBLIC_CSV.enabled:
        return _csv_response(await _csv_body(db, "district", district_id, school_id, keep))

    async def compute() -> bytes:
        async with database.SessionLocal() as own_db:
            return await _csv_body(own_db, "district", district_id, None, keep)

    return _csv_response(await _PUBLIC_CSV.get_or_compute((district_id, keep), compute))


# --- mutations: audit.manage -----------------------------------------------

async def _start(jobs) -> dict:
    from scheduler.runner import run_job_now

    for job in jobs:
        await run_job_now(job.id)
    return {"started": [{"id": j.id, "kind": j.kind, "name": j.name} for j in jobs]}


@router.post("/schools/{school_id}/data-points/{key}/run", dependencies=[Depends(require_permission("audit.manage"))])
async def run_data_point(school_id: str, key: str, db: AsyncSession = Depends(get_db)):
    """Run now every scan behind one school's data point (a district-level
    scan, like marking periods, runs for the whole district)."""
    point = audit.POINTS_BY_KEY.get(key)
    if not point:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown data point")
    school = await _one_school(db, school_id)
    ctx = await audit.load_context(db, [school])
    jobs = audit.jobs_to_run([audit.evaluate(point, school, ctx)], ctx, lambda kind: kind in registry)
    if not jobs:
        raise HTTPException(status.HTTP_409_CONFLICT, "No scan collects this data point for this school")
    return await _start(jobs)


@router.post("/schools/{school_id}/run-all", dependencies=[Depends(require_permission("audit.manage"))])
async def run_all(school_id: str, db: AsyncSession = Depends(get_db)):
    school = await _one_school(db, school_id)
    ctx = await audit.load_context(db, [school])
    jobs = audit.jobs_to_run(audit.audit_school(school, ctx).values(), ctx, lambda kind: kind in registry)
    if not jobs:
        raise HTTPException(status.HTTP_409_CONFLICT, "No scans are set up for this school")
    return await _start(jobs)


class NotPublishedIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


@router.put("/schools/{school_id}/data-points/{key}/not-published")
async def mark_not_published(
    school_id: str,
    key: str,
    body: NotPublishedIn | None = None,
    user: User = Depends(require_permission("audit.manage")),
    db: AsyncSession = Depends(get_db),
):
    if key not in audit.POINTS_BY_KEY:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown data point")
    school = await _one_school(db, school_id)
    row = (await db.execute(select(AuditNotPublished).where(
        AuditNotPublished.school_id == school.id, AuditNotPublished.data_point == key))).scalar_one_or_none()
    if row is None:
        row = AuditNotPublished(school_id=school.id, data_point=key, created_by_user_id=user.id)
        db.add(row)
    row.note = (body.note or "").strip() or None if body else None
    await db.commit()
    return {"school_id": school.id, "data_point": key, "not_published": True}


@router.delete("/schools/{school_id}/data-points/{key}/not-published", dependencies=[Depends(require_permission("audit.manage"))])
async def unmark_not_published(school_id: str, key: str, db: AsyncSession = Depends(get_db)):
    school = await _one_school(db, school_id)
    row = (await db.execute(select(AuditNotPublished).where(
        AuditNotPublished.school_id == school.id, AuditNotPublished.data_point == key))).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()
    return {"school_id": school.id, "data_point": key, "not_published": False}
