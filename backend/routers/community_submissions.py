import hashlib
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from auth import get_effective_permissions, get_optional_user, is_api_key_request, require_permission
from database import get_db
from local_events import normalizer as local_normalizer
from local_events.prune import COMMUNITY_SOURCE
from local_events.sources.base import RawEvent
from models import (
    CommunitySubmission,
    CommunitySubmissionItem,
    District,
    LocalEvent,
    School,
    SchoolContentItem,
    SubmissionAttempt,
    User,
)
from schemas import (
    CommunitySubmissionOut,
    CommunitySubmissionUpdate,
    SubmissionAttemptOut,
    SubmissionItemIn,
    SubmissionItemOut,
    SubmissionPublishIn,
    SubmissionReviewOut,
)
from services import submission_review, upload_guard
from services.content_extractor import _DEFAULT_TZ, _parse_date

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/submissions", tags=["community-submissions"])

# A submitted flier is a photo of a printed page or a phone-camera shot -
# generous enough for that, small enough that this table (bytes stored
# directly, no object storage) can't be turned into a free file host.
_MAX_FILE_BYTES = 15 * 1024 * 1024

# Per sender address, counted over every attempt (refused ones too) in
# submission_attempts - so it holds across machines and restarts, unlike an
# in-memory window. A parent sends one flyer, maybe a handful after a
# backpack clear-out; nobody sends ten an hour by hand.
_MAX_ATTEMPTS_PER_HOUR = 10
_MAX_ATTEMPTS_PER_DAY = 30


async def _attempt_outs(db: AsyncSession, attempts: list[SubmissionAttempt]) -> list[SubmissionAttemptOut]:
    user_ids = {a.user_id for a in attempts if a.user_id}
    emails: dict[str, str] = {}
    if user_ids:
        result = await db.execute(select(User.id, User.email).where(User.id.in_(user_ids)))
        emails = dict(result.all())
    outs = []
    for a in attempts:
        out = SubmissionAttemptOut.model_validate(a, from_attributes=True)
        out.user_email = emails.get(a.user_id) if a.user_id else None
        outs.append(out)
    return outs


async def _to_outs(
    db: AsyncSession, rows: list[CommunitySubmission], with_source: bool = False
) -> list[CommunitySubmissionOut]:
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

    sources: dict[str, SubmissionAttemptOut] = {}
    if with_source and rows:
        result = await db.execute(
            select(SubmissionAttempt).where(SubmissionAttempt.submission_id.in_([r.id for r in rows]))
        )
        for out in await _attempt_outs(db, list(result.scalars().all())):
            sources[out.submission_id] = out

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
            source=sources.get(r.id),
        )
        for r in rows
    ]


async def _refuse(db: AsyncSession, attempt: SubmissionAttempt, outcome: str, code: int, message: str, detail: str | None = None):
    """Record a refused attempt, then answer with the error. The row is the
    point: a refused upload is still someone trying."""
    attempt.outcome = outcome
    attempt.detail = (detail or message)[:300]
    db.add(attempt)
    await db.commit()
    logger.warning("submission refused: %s ip=%s detail=%s", outcome, attempt.ip, attempt.detail)
    raise HTTPException(code, message)


@router.post("", response_model=CommunitySubmissionOut, status_code=status.HTTP_201_CREATED)
async def create_submission(
    request: Request,
    url: str | None = Form(default=None),
    description: str | None = Form(default=None),
    submitter_name: str | None = Form(default=None),
    submitter_email: str | None = Form(default=None),
    school_id: str | None = Form(default=None),
    district_id: str | None = Form(default=None),
    # Honeypot: a field no person can see or reach.
    website: str | None = Form(default=None),
    bot_token: str | None = Form(default=None),
    file: UploadFile | None = File(default=None),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    # No login required by design - the whole point is letting the
    # community contribute without becoming an admin. That means no
    # per-user ownership to lean on for trust, so everything lands as
    # "pending" for a human to look at before it touches anything public,
    # and every attempt is recorded with where it came from.
    url = url.strip() if url else None
    name = (submitter_name or "").strip()[:200] or None
    email = (submitter_email or "").strip()[:255] or None

    attempt = SubmissionAttempt(
        outcome="accepted",
        user_id=user.id if user else None,
        submitter_name=name,
        submitter_email=email,
        kind="file" if file else "link" if url else None,
        url=url[:1000] if url else None,
        **upload_guard.request_source(request),
    )
    data: bytes | None = None
    if file:
        attempt.file_name = upload_guard.safe_file_name(file.filename)
        attempt.file_declared_type = (file.content_type or "")[:100] or None
        attempt.file_size = file.size
        # Hashed even when the attempt goes on to be refused, so a file that
        # keeps being tried is recognisable. Anything over the cap is never
        # read into memory at all.
        if file.size is None or file.size <= _MAX_FILE_BYTES:
            data = await file.read()
            attempt.file_size = len(data)
            attempt.file_sha256 = hashlib.sha256(data).hexdigest()
            attempt.file_detected_type = upload_guard.sniff_file_type(data)

    # Someone who may manage submissions adding one from the admin inbox is
    # already identified by their login, so the challenge and the rate limit
    # (which exist for strangers) don't apply. Still recorded, still sniffed.
    staff = bool(user) and (
        (user.is_admin and not is_api_key_request(request))
        or "submissions.manage" in await get_effective_permissions(request, db, user)
    )

    if website:
        await _refuse(db, attempt, "honeypot", status.HTTP_400_BAD_REQUEST, "Could not submit this - please try again")

    if attempt.ip and not staff:
        now = datetime.now(timezone.utc)
        recent = SubmissionAttempt.created_at > now - timedelta(days=1)
        result = await db.execute(
            select(
                func.count(),
                func.count().filter(SubmissionAttempt.created_at > now - timedelta(hours=1)),
            )
            .select_from(SubmissionAttempt)
            .where(SubmissionAttempt.ip == attempt.ip, recent)
        )
        in_day, in_hour = result.one()
        if in_hour >= _MAX_ATTEMPTS_PER_HOUR or in_day >= _MAX_ATTEMPTS_PER_DAY:
            await _refuse(
                db, attempt, "rate_limited", status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many uploads from this connection - please try again later.",
            )

    # Files only. A link puts nothing on this server, and the chatbot's
    # submit tool (mcp_server.py) posts links here in-process with no browser
    # to solve a challenge; links still get the rate limit and the record.
    if file and staff:
        attempt.bot_check = {"skipped": "staff"}
    elif file:
        try:
            passed, attempt.bot_check = await upload_guard.verify_bot_check(bot_token, attempt.ip)
        except upload_guard.BotCheckUnavailable as exc:
            await _refuse(
                db, attempt, "bot_check_unavailable", status.HTTP_503_SERVICE_UNAVAILABLE,
                "Uploads are unavailable right now - please try again in a few minutes.", str(exc),
            )
        if not passed:
            await _refuse(
                db, attempt, "bot_check_failed", status.HTTP_400_BAD_REQUEST,
                "We couldn't confirm you're a person - please reload the page and try again.",
            )

    if not url and not file:
        await _refuse(db, attempt, "invalid", status.HTTP_400_BAD_REQUEST, "Provide either a link or a file")
    if url and file:
        await _refuse(db, attempt, "invalid", status.HTTP_400_BAD_REQUEST, "Provide either a link or a file, not both")
    # The reviewer clicks this link, so nothing but a web address is kept.
    if url and not url.lower().startswith(("http://", "https://")):
        await _refuse(db, attempt, "invalid", status.HTTP_400_BAD_REQUEST, "The link must start with http:// or https://")
    if url and len(url) > 1000:
        await _refuse(db, attempt, "invalid", status.HTTP_400_BAD_REQUEST, "That link is too long")

    if school_id:
        exists = (await db.execute(select(School.id).where(School.id == school_id))).scalar_one_or_none()
        if not exists:
            await _refuse(db, attempt, "invalid", status.HTTP_400_BAD_REQUEST, "Unknown school_id")
    if district_id:
        exists = (await db.execute(select(District.id).where(District.id == district_id))).scalar_one_or_none()
        if not exists:
            await _refuse(db, attempt, "invalid", status.HTTP_400_BAD_REQUEST, "Unknown district_id")

    submission = CommunitySubmission(
        kind="file" if file else "link",
        url=url,
        description=(description or "").strip()[:2000] or None,
        submitter_name=name,
        submitter_email=email,
        school_id=school_id or None,
        district_id=district_id or None,
    )

    if file:
        if data is None:
            await _refuse(db, attempt, "too_large", status.HTTP_400_BAD_REQUEST, "File is too large (15MB max)")
        if not data:
            await _refuse(db, attempt, "invalid", status.HTTP_400_BAD_REQUEST, "Uploaded file is empty")
        if not attempt.file_detected_type:
            await _refuse(
                db, attempt, "bad_file_type", status.HTTP_400_BAD_REQUEST,
                "That file isn't a photo or PDF - please send a JPG, PNG or PDF.",
            )
        submission.file_data = data
        submission.file_name = attempt.file_name
        # What the bytes are, never what the sender called them.
        submission.file_content_type = attempt.file_detected_type
        submission.file_size = len(data)

    db.add(submission)
    await db.flush()
    attempt.submission_id = submission.id
    db.add(attempt)
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
    return await _to_outs(db, list(rows), with_source=True)


@router.get("/attempts", response_model=list[SubmissionAttemptOut])
async def list_attempts(
    limit: int = 200,
    user: User = Depends(require_permission("submissions.view")),
    db: AsyncSession = Depends(get_db),
):
    """Every recent attempt, newest first - including refused ones and ones
    whose submission has since been deleted."""
    result = await db.execute(
        select(SubmissionAttempt).order_by(SubmissionAttempt.created_at.desc()).limit(max(1, min(limit, 1000)))
    )
    return await _attempt_outs(db, list(result.scalars().all()))


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
        headers={
            # RFC 5987 form: a flyer named in Korean or Spanish can't go in a
            # plain quoted header value.
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(submission.file_name or 'upload')}",
            "X-Content-Type-Options": "nosniff",
        },
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
    return (await _to_outs(db, [submission], with_source=True))[0]


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


def _is_published(draft: CommunitySubmissionItem) -> bool:
    return bool(draft.content_item_id or draft.local_event_id)


async def _existing_local(db: AsyncSession, drafts: list[CommunitySubmissionItem]) -> list:
    """Local events on the days of the local-scope drafts, as (id, title,
    local day) - the same shape `_existing_calendar` gives, so a flyer for an
    event a feed already carries is flagged rather than listed twice."""
    local = [d for d in drafts if d.scope == "local"]
    days = [d for d in (submission_review.local_day(draft.start_local) for draft in local) if d]
    if not days:
        return []
    lo = datetime.combine(min(days), datetime.min.time(), tzinfo=_DEFAULT_TZ)
    hi = datetime.combine(max(days), datetime.min.time(), tzinfo=_DEFAULT_TZ) + timedelta(days=1)
    mine = {draft.local_event_id for draft in local if draft.local_event_id}
    result = await db.execute(
        select(LocalEvent.id, LocalEvent.title, LocalEvent.start_time).where(
            LocalEvent.start_time >= lo, LocalEvent.start_time < hi
        )
    )
    return [
        (event_id, title, start.astimezone(_DEFAULT_TZ).date())
        for event_id, title, start in result.all()
        if event_id not in mine
    ]


async def _review(db: AsyncSession, submission: CommunitySubmission) -> SubmissionReviewOut:
    drafts = await _drafts(db, submission.id)
    existing = await _existing_calendar(db, submission, drafts)
    existing_local = await _existing_local(db, drafts)
    today = submission_review.today_local()
    return SubmissionReviewOut(
        submission=(await _to_outs(db, [submission], with_source=True))[0],
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
                venue_name=d.venue_name,
                venue_address=d.venue_address,
                local_categories=d.local_categories or [],
                replaces_item_id=d.replaces_item_id,
                content_item_id=d.content_item_id,
                local_event_id=d.local_event_id,
                flags=submission_review.item_flags(d, existing_local if d.scope == "local" else existing, today),
            )
            for d in drafts
        ],
        # Only once something dated has been read - before that every date
        # in the note would "match nothing".
        note_flags=submission_review.note_flags(submission.description, drafts) if any(d.start_local for d in drafts) else [],
        categories=submission_review.CATEGORIES,
        local_categories=local_normalizer.PICKABLE_CATEGORIES,
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
        if draft.origin == "model" and not _is_published(draft):
            await db.delete(draft)
    # The sender said it's a town event and named no school: start the items
    # on /local. Only a default - the reviewer still decides each one.
    scope = "local" if not submission.school_id and (submission.description or "").startswith("[Local event]") else "school"
    for position, item in enumerate(items):
        db.add(CommunitySubmissionItem(submission_id=submission_id, position=position, origin="model", scope=scope, **item))
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
    if "scope" in fields and payload.scope and payload.scope != draft.scope:
        if _is_published(draft):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unpublish this item before changing where it goes")
        draft.scope = payload.scope
    if "local_categories" in fields and payload.local_categories is not None:
        unknown = set(payload.local_categories) - set(local_normalizer.PICKABLE_CATEGORIES)
        if unknown:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown category")
        draft.local_categories = list(dict.fromkeys(payload.local_categories))
    for name in ("venue_name", "venue_address"):
        if name in fields:
            setattr(draft, name, (getattr(payload, name) or "").strip() or None)
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


def _write_local_event(event: LocalEvent, draft: CommunitySubmissionItem) -> None:
    """Fills a LocalEvent from a draft, with the same normalisation (HTML
    strip, UTC storage, keyword categories) the feeds get."""
    start = _parse_date(draft.start_local, job_kind="submission.review")
    if start is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"“{draft.title}” has no date, so it can't be published")
    normalized = local_normalizer.normalize(
        RawEvent(
            source=COMMUNITY_SOURCE,
            source_event_id=f"submission:{draft.id}",
            title=_published_title(draft),
            description=draft.description,
            start_time=start,
            end_time=_parse_date(draft.end_local, job_kind="submission.review"),
            all_day="T" not in draft.start_local,
            venue_name=draft.venue_name,
            venue_address=draft.venue_address,
            default_categories=list(draft.local_categories or []),
            # A reviewer who ticks "free" knows it is; the keyword guess only runs without that.
            is_free=True if "free" in (draft.local_categories or []) else None,
        )
    )
    for name, value in normalized.items():
        setattr(event, name, value)


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
    if draft.local_event_id:
        event = (await db.execute(select(LocalEvent).where(LocalEvent.id == draft.local_event_id))).scalar_one_or_none()
        if event:
            _write_local_event(event, draft)
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
    if _is_published(draft):
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
    wanted = set(payload.item_ids)
    drafts = [d for d in await _drafts(db, submission_id) if d.id in wanted and not _is_published(d)]
    if not drafts:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to publish")
    # A school is only needed by the items that go on a school's calendar; a
    # local event stands on its own.
    school = await _submission_school(db, submission) if any(d.scope != "local" for d in drafts) else None

    for draft in drafts:
        if draft.scope == "local":
            event = LocalEvent(source=COMMUNITY_SOURCE, source_event_id=f"submission:{draft.id}")
            _write_local_event(event, draft)
            db.add(event)
            await db.flush()
            draft.local_event_id = event.id
            continue
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


async def _reopen_if_nothing_published(db: AsyncSession, submission: CommunitySubmission, taken_down: CommunitySubmissionItem) -> None:
    remaining = [d for d in await _drafts(db, submission.id) if _is_published(d) and d.id != taken_down.id]
    if not remaining and submission.status == "approved":
        submission.status = "pending"


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
    if not _is_published(draft):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This item isn't published")
    if draft.local_event_id:
        event = (await db.execute(select(LocalEvent).where(LocalEvent.id == draft.local_event_id))).scalar_one_or_none()
        if event:
            await db.delete(event)
        draft.local_event_id = None
        await _reopen_if_nothing_published(db, submission, draft)
        await db.commit()
        return await _review(db, submission)
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
    await _reopen_if_nothing_published(db, submission, draft)
    await db.commit()
    return await _review(db, submission)
