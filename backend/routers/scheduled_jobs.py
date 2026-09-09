from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_admin
from database import get_db
from models import JobRun, ScheduledJob
from schemas import JobRunOut, ScheduledJobOut

router = APIRouter(prefix="/scheduled-jobs", tags=["scheduled-jobs"])


@router.get("", response_model=list[ScheduledJobOut], dependencies=[Depends(require_admin)])
async def list_jobs(kind: str | None = None, db: AsyncSession = Depends(get_db)):
    """Admin-only - this is the visibility view for every centrally-managed
    scan (district feeds, staff rosters, documents, lunch menus, Smore,
    school info, email scanners)."""
    query = select(ScheduledJob)
    if kind:
        query = query.where(ScheduledJob.kind == kind)
    query = query.order_by(ScheduledJob.kind, ScheduledJob.name)
    result = await db.execute(query)
    return result.scalars().all()


async def _get_job_or_404(db: AsyncSession, job_id: str) -> ScheduledJob:
    result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


@router.get("/{job_id}/runs", response_model=list[JobRunOut], dependencies=[Depends(require_admin)])
async def list_runs(job_id: str, db: AsyncSession = Depends(get_db)):
    await _get_job_or_404(db, job_id)
    result = await db.execute(select(JobRun).where(JobRun.job_id == job_id).order_by(JobRun.started_at.desc()).limit(50))
    return result.scalars().all()


@router.get("/{job_id}", response_model=ScheduledJobOut, dependencies=[Depends(require_admin)])
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    return await _get_job_or_404(db, job_id)
