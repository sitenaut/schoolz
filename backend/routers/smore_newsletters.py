from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_admin
from database import get_db
from models import ScheduledJob, SmoreBlock, SmoreNewsletter, User
from schemas import ScheduledJobOut, SmoreBlockOut, SmoreNewsletterCreate, SmoreNewsletterOut, SmoreNewsletterUpdate

router = APIRouter(prefix="/smore-newsletters", tags=["smore-newsletters"])


def _validate_cron(cron_expr: str) -> None:
    if not croniter.is_valid(cron_expr):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid cron expression: {cron_expr}")


async def _to_out(db: AsyncSession, newsletter: SmoreNewsletter) -> SmoreNewsletterOut:
    job = None
    if newsletter.scheduled_job_id:
        result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == newsletter.scheduled_job_id))
        job_row = result.scalar_one_or_none()
        if job_row:
            job = ScheduledJobOut.model_validate(job_row)
    return SmoreNewsletterOut(
        id=newsletter.id,
        url=newsletter.url,
        label=newsletter.label,
        school_id=newsletter.school_id,
        last_scanned_at=newsletter.last_scanned_at,
        latest_summary=newsletter.latest_summary,
        created_at=newsletter.created_at,
        scheduled_job=job,
    )


async def _require_manageable(db: AsyncSession, newsletter_id: str) -> SmoreNewsletter:
    """Centrally managed - any admin can manage any tracked newsletter,
    there's no per-guardian ownership concept for this data anymore."""
    result = await db.execute(select(SmoreNewsletter).where(SmoreNewsletter.id == newsletter_id))
    newsletter = result.scalar_one_or_none()
    if not newsletter:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Newsletter not found")
    return newsletter


@router.get("", response_model=list[SmoreNewsletterOut])
async def list_newsletters(db: AsyncSession = Depends(get_db)):
    # Shared/public data (like Student) - every guardian sees every tracked
    # newsletter, not just their own, since the content itself is public.
    result = await db.execute(select(SmoreNewsletter).order_by(SmoreNewsletter.created_at))
    return [await _to_out(db, n) for n in result.scalars().all()]


@router.post("", response_model=SmoreNewsletterOut, status_code=status.HTTP_201_CREATED)
async def create_newsletter(
    payload: SmoreNewsletterCreate, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    _validate_cron(payload.cron_expr)

    existing = await db.execute(select(SmoreNewsletter).where(SmoreNewsletter.url == payload.url))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "This newsletter URL is already tracked")

    newsletter = SmoreNewsletter(
        url=payload.url, label=payload.label, school_id=payload.school_id, created_by_user_id=user.id
    )
    db.add(newsletter)
    await db.flush()

    job = ScheduledJob(
        owner_user_id=user.id,
        kind="smore.scan",
        name=f"Smore scan: {payload.label or payload.url}",
        cron_expr=payload.cron_expr,
        timezone=payload.timezone,
        params={"newsletter_id": newsletter.id},
        enabled=payload.enabled,
    )
    db.add(job)
    await db.flush()
    newsletter.scheduled_job_id = job.id

    await db.commit()
    await db.refresh(newsletter)
    return await _to_out(db, newsletter)


@router.patch("/{newsletter_id}", response_model=SmoreNewsletterOut)
async def update_newsletter(
    newsletter_id: str,
    payload: SmoreNewsletterUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    newsletter = await _require_manageable(db, newsletter_id)
    if payload.school_id is not None:
        newsletter.school_id = payload.school_id
    if payload.label is not None:
        newsletter.label = payload.label

    if payload.enabled and not newsletter.scheduled_job_id:
        # This newsletter was auto-registered (e.g. the school_email
        # processor found a Smore link in an email) but never scheduled -
        # scanning stays opt-in until someone actually asks for it here.
        cron_expr = payload.cron_expr or "0 8 * * 1"
        timezone = payload.timezone or "America/New_York"
        _validate_cron(cron_expr)
        job = ScheduledJob(
            owner_user_id=user.id,
            kind="smore.scan",
            name=f"Smore scan: {newsletter.label or newsletter.url}",
            cron_expr=cron_expr,
            timezone=timezone,
            params={"newsletter_id": newsletter.id},
            enabled=True,
        )
        db.add(job)
        await db.flush()
        newsletter.scheduled_job_id = job.id
    elif payload.enabled is not None and newsletter.scheduled_job_id:
        job = (await db.execute(select(ScheduledJob).where(ScheduledJob.id == newsletter.scheduled_job_id))).scalar_one_or_none()
        if job:
            job.enabled = payload.enabled
            if payload.cron_expr:
                _validate_cron(payload.cron_expr)
                job.cron_expr = payload.cron_expr
            if payload.timezone:
                job.timezone = payload.timezone

    await db.commit()
    await db.refresh(newsletter)
    return await _to_out(db, newsletter)


@router.get("/{newsletter_id}/blocks", response_model=list[SmoreBlockOut])
async def list_blocks(newsletter_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SmoreNewsletter).where(SmoreNewsletter.id == newsletter_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Newsletter not found")
    blocks = await db.execute(
        select(SmoreBlock).where(SmoreBlock.newsletter_id == newsletter_id).order_by(SmoreBlock.first_seen_at.desc())
    )
    return blocks.scalars().all()


@router.post("/{newsletter_id}/run-now")
async def run_now(newsletter_id: str, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    newsletter = await _require_manageable(db, newsletter_id)
    if not newsletter.scheduled_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Newsletter has no linked scheduled job")

    from scheduler.runner import run_job_now

    run_job_now(newsletter.scheduled_job_id)
    return {"status": "started"}


@router.post("/{newsletter_id}/reextract-all")
async def reextract_all(newsletter_id: str, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """Re-runs extraction over every block this newsletter has ever
    fetched, not just newly-seen ones. `run-now`'s normal scan+extract path
    only ever passes *new* blocks to extraction - once a block is stored,
    a plain re-scan can't get its content re-extracted even if the
    extraction step itself failed or silently truncated last time (real
    case: a 37-block newsletter hit max_tokens and landed 0 items with a
    "success" status - re-scanning found no new blocks and did nothing).
    This is the deliberate escape hatch for exactly that: an admin-visible,
    on-demand full re-extraction, synchronous so a real result comes back
    immediately rather than needing to poll job_runs afterward.

    Caution: dedup is only at the block level (content_hash) - re-extracting
    a block that already produced an item creates a second, duplicate item,
    it doesn't update the first. Safe on a newsletter that currently has
    zero (or far fewer than expected) items; not a routine "refresh" button
    for one that's already fully extracted."""
    newsletter = await _require_manageable(db, newsletter_id)
    result = await db.execute(
        select(SmoreBlock).where(SmoreBlock.newsletter_id == newsletter.id).order_by(SmoreBlock.position)
    )
    blocks = result.scalars().all()
    if not blocks:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Newsletter has no fetched blocks yet - run a scan first")

    from services.content_extractor import extract_from_newsletter

    summary = await extract_from_newsletter(db, newsletter, list(blocks))
    await db.commit()
    return {"status": "done", "summary": summary}


@router.delete("/{newsletter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_newsletter(
    newsletter_id: str, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    newsletter = await _require_manageable(db, newsletter_id)
    if newsletter.scheduled_job_id:
        job_result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == newsletter.scheduled_job_id))
        job = job_result.scalar_one_or_none()
        if job:
            await db.delete(job)
    await db.delete(newsletter)
    await db.commit()
