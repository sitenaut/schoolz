from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_admin
from database import get_db
from models import EmailScanner, GmailToken, ScheduledJob, User
from schemas import EmailScannerCreate, EmailScannerOut, EmailScannerUpdate, ScheduledJobOut
from scheduler.registry import registry as job_registry

# Admin-only for now (2026-09-11): connecting a Gmail account and scanning it
# is a data-source management task, not part of the guardian personal layer.
# Rows stay owner-scoped so two admins never see each other's inbox captures.
router = APIRouter(prefix="/email-scanners", tags=["email-scanners"])


def _validate_cron(cron_expr: str) -> None:
    if not croniter.is_valid(cron_expr):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid cron expression: {cron_expr}")


async def _require_own_scanner(db: AsyncSession, user: User, scanner_id: str) -> EmailScanner:
    result = await db.execute(select(EmailScanner).where(EmailScanner.id == scanner_id))
    scanner = result.scalar_one_or_none()
    if not scanner or (scanner.owner_user_id != user.id and not user.is_admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scanner not found")
    return scanner


async def _to_out(db: AsyncSession, scanner: EmailScanner) -> EmailScannerOut:
    job = None
    if scanner.scheduled_job_id:
        result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == scanner.scheduled_job_id))
        job_row = result.scalar_one_or_none()
        if job_row:
            job = ScheduledJobOut.model_validate(job_row)
    return EmailScannerOut(
        id=scanner.id,
        google_email=scanner.google_email,
        name=scanner.name,
        from_contains=scanner.from_contains,
        subject_contains=scanner.subject_contains,
        body_contains=scanner.body_contains,
        raw_query=scanner.raw_query,
        lookback_days=scanner.lookback_days,
        purpose=scanner.purpose,
        school_id=scanner.school_id,
        enabled=scanner.enabled,
        created_at=scanner.created_at,
        scheduled_job=job,
    )


@router.get("", response_model=list[EmailScannerOut])
async def list_scanners(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(EmailScanner).where(EmailScanner.owner_user_id == user.id))
    return [await _to_out(db, s) for s in result.scalars().all()]


@router.post("", response_model=EmailScannerOut, status_code=status.HTTP_201_CREATED)
async def create_scanner(
    payload: EmailScannerCreate, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    if payload.purpose not in ("school_email",):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown purpose: {payload.purpose}")
    _validate_cron(payload.cron_expr)

    token_result = await db.execute(
        select(GmailToken).where(GmailToken.user_id == user.id, GmailToken.google_email == payload.google_email)
    )
    if not token_result.scalar_one_or_none():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "That Gmail account isn't connected to your profile")

    scanner = EmailScanner(
        owner_user_id=user.id,
        google_email=payload.google_email,
        name=payload.name,
        from_contains=payload.from_contains,
        subject_contains=payload.subject_contains,
        body_contains=payload.body_contains,
        raw_query=payload.raw_query,
        lookback_days=payload.lookback_days,
        purpose=payload.purpose,
        school_id=payload.school_id,
    )
    db.add(scanner)
    await db.flush()

    job = ScheduledJob(
        owner_user_id=user.id,
        kind="email.scan",
        name=f"Email scan: {payload.name}",
        description=f"Runs the '{payload.name}' email scanner",
        cron_expr=payload.cron_expr,
        timezone=payload.timezone,
        params={"scanner_id": scanner.id},
        enabled=payload.enabled,
    )
    db.add(job)
    await db.flush()
    scanner.scheduled_job_id = job.id

    await db.commit()
    await db.refresh(scanner)
    return await _to_out(db, scanner)


@router.patch("/{scanner_id}", response_model=EmailScannerOut)
async def update_scanner(
    scanner_id: str,
    payload: EmailScannerUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    scanner = await _require_own_scanner(db, user, scanner_id)

    for field in ("name", "from_contains", "subject_contains", "body_contains", "raw_query", "lookback_days", "school_id"):
        value = getattr(payload, field)
        if value is not None:
            setattr(scanner, field, value)

    job = None
    if scanner.scheduled_job_id:
        result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == scanner.scheduled_job_id))
        job = result.scalar_one_or_none()

    if job:
        if payload.cron_expr is not None:
            _validate_cron(payload.cron_expr)
            job.cron_expr = payload.cron_expr
        if payload.timezone is not None:
            job.timezone = payload.timezone
        if payload.enabled is not None:
            job.enabled = payload.enabled

    await db.commit()
    await db.refresh(scanner)
    return await _to_out(db, scanner)


@router.delete("/{scanner_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scanner(scanner_id: str, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    scanner = await _require_own_scanner(db, user, scanner_id)
    if scanner.scheduled_job_id:
        result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == scanner.scheduled_job_id))
        job = result.scalar_one_or_none()
        if job:
            await db.delete(job)
    await db.delete(scanner)
    await db.commit()


@router.post("/{scanner_id}/run-now")
async def run_scanner_now(scanner_id: str, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    scanner = await _require_own_scanner(db, user, scanner_id)
    if not scanner.scheduled_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Scanner has no linked scheduled job")
    if "email.scan" not in job_registry:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "email.scan job kind not registered")

    from scheduler.runner import run_job_now

    run_job_now(scanner.scheduled_job_id)
    return {"status": "started"}
