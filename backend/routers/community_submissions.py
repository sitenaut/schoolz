from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from auth import require_permission
from database import get_db
from models import CommunitySubmission, CommunitySubmissionItem, District, School, SchoolContentItem, User
from schemas import (
    CommunitySubmissionOut,
    CommunitySubmissionUpdate,
    SubmissionItemIn,
    SubmissionItemOut,
    SubmissionPublishIn,
    SubmissionReviewOut,
)
from services import submission_review
from services.content_extractor import _DEFAULT_TZ, _parse_date

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
            extracted_at=r.extracted_at,
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
    status_filter: str | None = None, user: User = Depends(require_permission("submissions.view")), db: AsyncSession = Depends(get_db)
):
    # The bytes are up to 15MB a row and nothing in a listing needs them.
    query = (
        select(CommunitySubmission)
        .options(defer(CommunitySubmission.file_data))
        .order_by(CommunitySubmission.created_at.desc())
    )
    if status_filter:
        query = query.where(CommunitySubmission.status == status_filter)
    rows = (await db.execute(query)).scalars().all()
    return await _to_outs(db, list(rows))


@router.get("/{submission_id}/file")
async def download_file(
    submission_id: str, user: User = Depends(require_permission("submissions.view")), db: AsyncSession = Depends(get_db)
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
    user: User = Depends(require_permission("submissions.manage")),
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
    if payload.school_id is not None:
        school = (await db.execute(select(School).where(School.id == payload.school_id))).scalar_one_or_none()
        if not school:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown school_id")
        submission.school_id = school.id
        submission.district_id = school.district_id

    await db.commit()
    await db.refresh(submission)
    return (await _to_outs(db, [submission]))[0]


@router.delete("/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_submission(submission_id: str, user: User = Depends(require_permission("submissions.manage")), db: AsyncSession = Depends(get_db)):
    submission = (
        await db.execute(select(CommunitySubmission).where(CommunitySubmission.id == submission_id))
    ).scalar_one_or_none()
    if not submission:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    await db.delete(submission)
    await db.commit()


# --- Review: read the upload into draft items, correct them, publish --------
#
# Drafts live in community_submission_items and are never public. Publishing
# is the only step that writes a SchoolContentItem, and only for the drafts
# the reviewer named - so an anonymous upload still can't reach the calendar
# without a person choosing each item.


async def _load(db: AsyncSession, submission_id: str) -> CommunitySubmission:
    submission = (
        await db.execute(
            select(CommunitySubmission)
            .options(defer(CommunitySubmission.file_data))
            .where(CommunitySubmission.id == submission_id)
        )
    ).scalar_one_or_none()
    if not submission:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    return submission


async def _drafts(db: AsyncSession, submission_id: str) -> list[CommunitySubmissionItem]:
    result = await db.execute(
        select(CommunitySubmissionItem)
        .where(CommunitySubmissionItem.submission_id == submission_id)
        .order_by(CommunitySubmissionItem.position, CommunitySubmissionItem.created_at)
    )
    return list(result.scalars().all())


async def _draft(db: AsyncSession, submission_id: str, item_id: str) -> CommunitySubmissionItem:
    draft = (
        await db.execute(
            select(CommunitySubmissionItem).where(
                CommunitySubmissionItem.id == item_id, CommunitySubmissionItem.submission_id == submission_id
            )
        )
    ).scalar_one_or_none()
    if not draft:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    return draft


async def _existing_calendar(db: AsyncSession, submission: CommunitySubmission, drafts: list[CommunitySubmissionItem]) -> list:
    """The school's current calendar items around the drafts' dates, as
    (id, title, local day) - what `already_listed` is checked against."""
    days = [d for d in (submission_review.local_day(draft.start_local) for draft in drafts) if d]
    if not days or not submission.school_id:
        return []
    own = SchoolContentItem.school_id == submission.school_id
    if submission.district_id:
        own = or_(own, SchoolContentItem.district_id == submission.district_id)
    lo = datetime.combine(min(days), datetime.min.time(), tzinfo=_DEFAULT_TZ)
    hi = datetime.combine(max(days), datetime.min.time(), tzinfo=_DEFAULT_TZ) + timedelta(days=1)
    mine = {draft.content_item_id for draft in drafts if draft.content_item_id}
    result = await db.execute(
        select(SchoolContentItem.id, SchoolContentItem.title, SchoolContentItem.start_date).where(
            own,
            SchoolContentItem.is_current.is_(True),
            SchoolContentItem.start_date >= lo,
            SchoolContentItem.start_date < hi,
        )
    )
    return [
        (item_id, title, start.astimezone(_DEFAULT_TZ).date())
        for item_id, title, start in result.all()
        if item_id not in mine
    ]


async def _review(db: AsyncSession, submission: CommunitySubmission) -> SubmissionReviewOut:
    drafts = await _drafts(db, submission.id)
    existing = await _existing_calendar(db, submission, drafts)
    today = submission_review.today_local()
    return SubmissionReviewOut(
        submission=(await _to_outs(db, [submission]))[0],
        items=[
            SubmissionItemOut(
                id=d.id,
                origin=d.origin,
                title=d.title,
                description=d.description,
                category=d.category,
                scope=d.scope,
                start_local=d.start_local,
                end_local=d.end_local,
                stated_weekday=d.stated_weekday,
                tentative=d.tentative,
                source_excerpt=d.source_excerpt,
                replaces_item_id=d.replaces_item_id,
                content_item_id=d.content_item_id,
                flags=submission_review.item_flags(d, existing, today),
            )
            for d in drafts
        ],
        # Only once something dated has been read - before that every date
        # in the note would "match nothing".
        note_flags=submission_review.note_flags(submission.description, drafts) if any(d.start_local for d in drafts) else [],
        categories=submission_review.CATEGORIES,
    )


@router.get("/{submission_id}", response_model=SubmissionReviewOut)
async def get_submission(
    submission_id: str, user: User = Depends(require_permission("submissions.view")), db: AsyncSession = Depends(get_db)
):
    return await _review(db, await _load(db, submission_id))


@router.post("/{submission_id}/extract", response_model=SubmissionReviewOut)
async def extract_submission(
    submission_id: str, user: User = Depends(require_permission("submissions.manage")), db: AsyncSession = Depends(get_db)
):
    """Reads the uploaded file into draft items. Re-running replaces the
    drafts the reader made last time, but never one a person typed, and
    never one already published."""
    submission = await _load(db, submission_id)
    data = (
        await db.execute(select(CommunitySubmission.file_data).where(CommunitySubmission.id == submission_id))
    ).scalar_one_or_none()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "There's no uploaded file to read on this submission")

    school_name = None
    if submission.school_id:
        school_name = (await db.execute(select(School.name).where(School.id == submission.school_id))).scalar_one_or_none()
    try:
        items = await submission_review.read_upload(
            data,
            school_name=school_name,
            submitter_note=submission.description,
            today=submission_review.today_local(),
        )
    except submission_review.ReadError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    for draft in await _drafts(db, submission_id):
        if draft.origin == "model" and draft.content_item_id is None:
            await db.delete(draft)
    for position, item in enumerate(items):
        db.add(CommunitySubmissionItem(submission_id=submission_id, position=position, origin="model", **item))
    submission.extracted_at = datetime.now(timezone.utc)
    await db.commit()
    return await _review(db, submission)


def _apply(draft: CommunitySubmissionItem, payload: SubmissionItemIn) -> None:
    fields = payload.model_fields_set
    if "title" in fields and payload.title:
        draft.title = payload.title.strip()
    if "description" in fields:
        draft.description = (payload.description or "").strip() or None
    if "category" in fields and payload.category:
        if payload.category not in submission_review.CATEGORIES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown category")
        draft.category = payload.category
    if "scope" in fields and payload.scope:
        draft.scope = payload.scope
    for name in ("start_local", "end_local"):
        if name in fields:
            value = getattr(payload, name) or None
            if value and submission_review.clean_local(value) is None:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "That isn't a real date")
            if name == "start_local" and (value or "")[:10] != (draft.start_local or "")[:10]:
                # The printed weekday described the date the reader saw. Once
                # a person has moved the date, there's nothing left to compare.
                draft.stated_weekday = None
            setattr(draft, name, value)
    if "tentative" in fields and payload.tentative is not None:
        draft.tentative = payload.tentative
    if "replaces_item_id" in fields:
        draft.replaces_item_id = payload.replaces_item_id or None


def _published_title(draft: CommunitySubmissionItem) -> str:
    # There is no "tentative" field on a calendar item, and the title is the
    # one thing every surface (Today, calendar, chatbot) shows.
    if draft.tentative and "tentative" not in draft.title.lower():
        return f"{draft.title[:288]} (tentative)"
    return draft.title


def _write_item(item: SchoolContentItem, draft: CommunitySubmissionItem, school: School) -> None:
    start = _parse_date(draft.start_local, job_kind="submission.review")
    if start is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"“{draft.title}” has no date, so it can't be published")
    if draft.scope == "district" and not school.district_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{school.name} has no district to publish “{draft.title}” to")
    item.scope = draft.scope
    item.school_id = school.id if draft.scope == "school" else None
    item.district_id = school.district_id if draft.scope == "district" else None
    item.category = draft.category
    item.title = _published_title(draft)
    item.description = draft.description
    item.start_date = start
    item.end_date = _parse_date(draft.end_local, job_kind="submission.review")
    item.is_all_day = "T" not in draft.start_local
    item.source_excerpt = draft.source_excerpt


async def _submission_school(db: AsyncSession, submission: CommunitySubmission) -> School:
    school = None
    if submission.school_id:
        school = (await db.execute(select(School).where(School.id == submission.school_id))).scalar_one_or_none()
    if not school:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick the school this is about before publishing")
    return school


@router.post("/{submission_id}/items", response_model=SubmissionReviewOut, status_code=status.HTTP_201_CREATED)
async def add_item(
    submission_id: str,
    payload: SubmissionItemIn,
    user: User = Depends(require_permission("submissions.manage")),
    db: AsyncSession = Depends(get_db),
):
    submission = await _load(db, submission_id)
    if not payload.title or not payload.title.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An item needs a title")
    last = (
        await db.execute(
            select(func.max(CommunitySubmissionItem.position)).where(CommunitySubmissionItem.submission_id == submission_id)
        )
    ).scalar_one_or_none()
    draft = CommunitySubmissionItem(
        submission_id=submission_id, position=(last if last is not None else -1) + 1, origin="manual", title=payload.title.strip()
    )
    _apply(draft, payload)
    db.add(draft)
    await db.commit()
    return await _review(db, submission)


@router.patch("/{submission_id}/items/{item_id}", response_model=SubmissionReviewOut)
async def update_item(
    submission_id: str,
    item_id: str,
    payload: SubmissionItemIn,
    user: User = Depends(require_permission("submissions.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Editing a published draft edits the live calendar item with it - a
    correction made here shouldn't need a second trip somewhere else."""
    submission = await _load(db, submission_id)
    draft = await _draft(db, submission_id, item_id)
    _apply(draft, payload)
    if draft.content_item_id:
        item = (
            await db.execute(select(SchoolContentItem).where(SchoolContentItem.id == draft.content_item_id))
        ).scalar_one_or_none()
        if item:
            _write_item(item, draft, await _submission_school(db, submission))
    await db.commit()
    return await _review(db, submission)


@router.delete("/{submission_id}/items/{item_id}", response_model=SubmissionReviewOut)
async def delete_item(
    submission_id: str,
    item_id: str,
    user: User = Depends(require_permission("submissions.manage")),
    db: AsyncSession = Depends(get_db),
):
    submission = await _load(db, submission_id)
    draft = await _draft(db, submission_id, item_id)
    if draft.content_item_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unpublish this item before deleting it")
    await db.delete(draft)
    await db.commit()
    return await _review(db, submission)


@router.post("/{submission_id}/publish", response_model=SubmissionReviewOut)
async def publish_items(
    submission_id: str,
    payload: SubmissionPublishIn,
    user: User = Depends(require_permission("submissions.manage")),
    db: AsyncSession = Depends(get_db),
):
    submission = await _load(db, submission_id)
    school = await _submission_school(db, submission)
    wanted = set(payload.item_ids)
    drafts = [d for d in await _drafts(db, submission_id) if d.id in wanted and d.content_item_id is None]
    if not drafts:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to publish")

    for draft in drafts:
        item = SchoolContentItem(source="community", external_uid=f"submission:{draft.id}")
        _write_item(item, draft, school)
        db.add(item)
        await db.flush()
        if draft.replaces_item_id:
            old = (
                await db.execute(select(SchoolContentItem).where(SchoolContentItem.id == draft.replaces_item_id))
            ).scalar_one_or_none()
            if old:
                old.is_current = False
                old.superseded_by_id = item.id
        draft.content_item_id = item.id

    submission.status = "approved"
    submission.reviewed_by_user_id = user.id
    submission.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    return await _review(db, submission)


@router.post("/{submission_id}/items/{item_id}/unpublish", response_model=SubmissionReviewOut)
async def unpublish_item(
    submission_id: str,
    item_id: str,
    user: User = Depends(require_permission("submissions.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Takes one item back off the calendar and puts back whatever it
    replaced. The draft stays, so it can be fixed and published again."""
    submission = await _load(db, submission_id)
    draft = await _draft(db, submission_id, item_id)
    if not draft.content_item_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This item isn't published")
    replaced = (
        await db.execute(select(SchoolContentItem).where(SchoolContentItem.superseded_by_id == draft.content_item_id))
    ).scalars().all()
    for old in replaced:
        old.is_current = True
        old.superseded_by_id = None
    await db.flush()
    item = (
        await db.execute(select(SchoolContentItem).where(SchoolContentItem.id == draft.content_item_id))
    ).scalar_one_or_none()
    if item:
        await db.delete(item)
    draft.content_item_id = None

    remaining = [d for d in await _drafts(db, submission_id) if d.content_item_id and d.id != draft.id]
    if not remaining and submission.status == "approved":
        submission.status = "pending"
    await db.commit()
    return await _review(db, submission)
