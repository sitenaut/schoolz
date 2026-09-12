from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_admin
from database import get_db
from models import CommunitySubmission, District, School, User
from schemas import CommunitySubmissionOut, CommunitySubmissionUpdate

router = APIRouter(prefix="/submissions", tags=["community-submissions"])

# A submitted flier is a photo of a printed page or a phone-camera shot -
# generous enough for that, small enough that this table (bytes stored
# directly, no object storage) can't be turned into a free file host.
_MAX_FILE_BYTES = 15 * 1024 * 1024


async def _to_outs(db: AsyncSession, rows: list[CommunitySubmission]) -> list[CommunitySubmissionOut]:
    school_ids = [r.school_id for r in rows if r.school_id]
    schools_by_id: dict[str, str] = {}
    if school_ids:
        result = await db.execute(select(School.id, School.short_name, School.name).where(School.id.in_(school_ids)))
        schools_by_id = {sid: short_name or name for sid, short_name, name in result.all()}

    district_ids = [r.district_id for r in rows if r.district_id]
    districts_by_id: dict[str, str] = {}
    if district_ids:
        result = await db.execute(select(District.id, District.name).where(District.id.in_(district_ids)))
        districts_by_id = dict(result.all())

    return [
        CommunitySubmissionOut(
            id=r.id,
            kind=r.kind,
            url=r.url,
            file_name=r.file_name,
            file_content_type=r.file_content_type,
            file_size=r.file_size,
            description=r.description,
            submitter_name=r.submitter_name,
            submitter_email=r.submitter_email,
            school_id=r.school_id,
            district_id=r.district_id,
            school_name=schools_by_id.get(r.school_id) if r.school_id else None,
            district_name=districts_by_id.get(r.district_id) if r.district_id else None,
            status=r.status,
            admin_notes=r.admin_notes,
            reviewed_at=r.reviewed_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("", response_model=CommunitySubmissionOut, status_code=status.HTTP_201_CREATED)
async def create_submission(
    url: str | None = Form(default=None),
    description: str | None = Form(default=None),
    submitter_name: str | None = Form(default=None),
    submitter_email: str | None = Form(default=None),
    school_id: str | None = Form(default=None),
    district_id: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    db: AsyncSession = Depends(get_db),
):
    # No login required by design - the whole point is letting the
    # community contribute without becoming an admin. That means no
    # per-user ownership to lean on for trust, so everything lands as
    # "pending" for a human to look at before it touches anything public.
    url = url.strip() if url else None
    if not url and not file:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide either a link or a file")
    if url and file:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Provide either a link or a file, not both")

    if school_id:
        exists = (await db.execute(select(School.id).where(School.id == school_id))).scalar_one_or_none()
        if not exists:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown school_id")
    if district_id:
        exists = (await db.execute(select(District.id).where(District.id == district_id))).scalar_one_or_none()
        if not exists:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown district_id")

    submission = CommunitySubmission(
        kind="file" if file else "link",
        url=url,
        description=(description or "").strip()[:2000] or None,
        submitter_name=(submitter_name or "").strip()[:200] or None,
        submitter_email=(submitter_email or "").strip()[:255] or None,
        school_id=school_id or None,
        district_id=district_id or None,
    )

    if file:
        data = await file.read()
        if len(data) > _MAX_FILE_BYTES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is too large (15MB max)")
        if not data:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty")
        submission.file_data = data
        submission.file_name = (file.filename or "upload")[:255]
        submission.file_content_type = file.content_type or "application/octet-stream"
        submission.file_size = len(data)

    db.add(submission)
    await db.commit()
    await db.refresh(submission)
    return (await _to_outs(db, [submission]))[0]


@router.get("", response_model=list[CommunitySubmissionOut])
async def list_submissions(
    status_filter: str | None = None, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    query = select(CommunitySubmission).order_by(CommunitySubmission.created_at.desc())
    if status_filter:
        query = query.where(CommunitySubmission.status == status_filter)
    rows = (await db.execute(query)).scalars().all()
    return await _to_outs(db, list(rows))


@router.get("/{submission_id}/file")
async def download_file(
    submission_id: str, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    submission = (
        await db.execute(select(CommunitySubmission).where(CommunitySubmission.id == submission_id))
    ).scalar_one_or_none()
    if not submission or not submission.file_data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No file on this submission")
    return Response(
        content=submission.file_data,
        media_type=submission.file_content_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{submission.file_name or "upload"}"'},
    )


@router.patch("/{submission_id}", response_model=CommunitySubmissionOut)
async def update_submission(
    submission_id: str,
    payload: CommunitySubmissionUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    submission = (
        await db.execute(select(CommunitySubmission).where(CommunitySubmission.id == submission_id))
    ).scalar_one_or_none()
    if not submission:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")

    if payload.status is not None:
        submission.status = payload.status
        submission.reviewed_by_user_id = user.id
        submission.reviewed_at = datetime.now(timezone.utc)
    if payload.admin_notes is not None:
        submission.admin_notes = payload.admin_notes.strip()[:2000] or None

    await db.commit()
    await db.refresh(submission)
    return (await _to_outs(db, [submission]))[0]


@router.delete("/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_submission(submission_id: str, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    submission = (
        await db.execute(select(CommunitySubmission).where(CommunitySubmission.id == submission_id))
    ).scalar_one_or_none()
    if not submission:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    await db.delete(submission)
    await db.commit()
