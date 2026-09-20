"""Bucket 3: import a family's own Backpack Capture export and expose the
extracted schedule, assignments, and grades for one Student - plus the Kids
view v2 dashboard on top of it (docs/KIDS_VIEW_V2_DESIGN.md).

Every student route is readable by that student's guardians *and* by the
student's own login (Student.user_id - see routers/student_accounts.py); both
see identical data. The only other route is the admin-only page-kind catalog,
which carries no student content. See CLAUDE.md's "Access model" and
models.py's Bucket3Capture docstring for why this is a deliberately different
access shape from the rest of the app.
"""
import hashlib
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, require_admin
from database import get_db
from models import (
    AssignmentSuggestion,
    Bucket3Capture,
    CapturePageKind,
    ChildCourseGrade,
    ChildDayCycle,
    ChildGradeEntry,
    ChildMarkingPeriod,
    ChildScheduleBlock,
    ChildWorkItem,
    ChildWorkItemProgress,
    CourseDisplayPreference,
    CourseLatePolicy,
    GuardianStudentLink,
    HelpRequest,
    Notification,
    WorkItemLateException,
    School,
    SchoolContentItem,
    StaffMember,
    Student,
    User,
)
from schemas import (
    AuditMatchedOut,
    Bucket3AuditOut,
    Bucket3GradesOut,
    Bucket3ImportRequest,
    Bucket3ImportResult,
    Bucket3StudentOut,
    CapturePageKindOut,
    ChildCourseGradeOut,
    ChildGradeEntryOut,
    ChildMarkingPeriodOut,
    ChildScheduleBlockOut,
    ChildScheduleOut,
    ChildWorkItemOut,
)
from services import bucket3_extract as ex
from services import help_requests as help_svc
from services import kids_suggestions, kids_view

logger = logging.getLogger(__name__)

router = APIRouter(tags=["bucket3"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _local_now() -> datetime:
    return datetime.now(kids_view.LOCAL_TZ)


def _local_today() -> str:
    return _local_now().date().isoformat()


# ---- Kids view v2 response shapes ------------------------------------------


class NowBlockOut(BaseModel):
    period: str
    period_number: str | None
    course_name: str
    teacher: str | None
    teacher_emails: list[str] = []
    room: str | None
    time_start: str | None
    time_end: str | None
    minutes_in: int | None
    minutes_left: int | None
    is_current: bool


class RightNowOut(BaseModel):
    schedule_date: str | None
    stale: bool
    cycle_label: str | None = None
    school_day_over: bool
    current: NowBlockOut | None
    next: NowBlockOut | None
    blocks: list[NowBlockOut]


class TodoGradeOut(BaseModel):
    score_earned: float | None
    score_possible: float | None
    percent: float | None
    status: str | None


class SuggestionOut(BaseModel):
    text: str | None
    declined: bool
    cached: bool = True


class LateCreditOut(BaseModel):
    """What this class's late policy says is still earnable. Null on the item
    when no policy is on file - "unknown" must stay distinct from "zero"."""

    accepted: bool
    credit_pct: int | None
    closes_on: str | None
    days_left: int | None
    is_late: bool
    extension_by_request: bool
    # True when a teacher's own exception produced this, not the class rule.
    by_exception: bool = False


class LateExceptionOut(BaseModel):
    accepted_until: str
    credit_pct: float | None
    granted_note: str | None


class LateExceptionIn(BaseModel):
    # "marking_period_end" or an ISO date - same vocabulary CourseLatePolicy
    # uses for accepted_until.
    accepted_until: str
    credit_pct: float | None = None
    granted_note: str | None = None


class TodoItemOut(BaseModel):
    id: str
    title: str
    item_type: str
    course_name: str | None
    # Same identity CourseProgressOut.course_key uses - lets the client key
    # a color (default or customized) by the class itself rather than by
    # display name, so Focus and Subjects can never disagree about which
    # color a class is.
    course_key: str
    due_raw: str | None
    due_date: str | None
    # "missing" | "due" | "done" | "no_due_date"
    category: str
    done: bool
    # "marked" (someone checked it in schoolz) | "classroom" | "genesis" | None
    done_source: str | None
    marked_by: str | None
    classroom_status: str | None
    grade: TodoGradeOut | None
    # From the assignment's own detail page, not the classwork/stream card
    # this row is otherwise built from - null means "not captured yet",
    # never "worth zero". See bucket3_extract.py:extract_classroom_detail_points.
    points_possible: float | None = None
    teacher_name: str | None
    teacher_emails: list[str]
    link: str | None
    suggestion: SuggestionOut | None
    late_credit: LateCreditOut | None = None
    late_exception: LateExceptionOut | None = None
    asked_kinds: list[str] = []


class ProgressOut(BaseModel):
    done: int
    missing: int
    due: int
    total: int
    percent: int | None


class TodoOut(BaseModel):
    current_marking_period: ChildMarkingPeriodOut | None
    progress: ProgressOut
    next_action: TodoItemOut | None
    missing: list[TodoItemOut]
    due: list[TodoItemOut]
    done: list[TodoItemOut]
    no_due_date: list[TodoItemOut]


class AnnouncementOut(BaseModel):
    id: str
    title: str
    course_name: str | None
    teacher_name: str | None
    teacher_emails: list[str]
    posted_raw: str | None
    posted_date: str | None
    body: str | None
    link: str | None


class LowGradeOut(BaseModel):
    title: str
    percent: float


class CourseProgressOut(BaseModel):
    course_key: str
    course_name: str
    grade_percent: float | None
    marking_period: str | None
    total: int
    done: int
    missing: int
    due_soon: int
    completion_pct: int | None
    low_grade_entries: list[LowGradeOut]
    teacher_name: str | None
    teacher_emails: list[str]


class CompleteRequest(BaseModel):
    done: bool


class CompleteOut(BaseModel):
    id: str
    done: bool
    marked_by: str | None


class PlanOut(BaseModel):
    text: str


class LatePolicyIn(BaseModel):
    course_key: str
    course_name: str | None = None
    shape: str
    penalty_pct: float | None = None
    penalty_per_day: float | None = None
    floor_pct: float | None = None
    window_days: int | None = None
    steps: list[dict] | None = None
    accepted_until: str | None = None
    applies_to_types: list[str] | None = None
    extension_by_request: bool = False
    source_text: str | None = None
    notes: str | None = None


class LatePolicyOut(BaseModel):
    course_key: str
    course_name: str | None
    shape: str
    penalty_pct: float | None
    penalty_per_day: float | None
    floor_pct: float | None
    window_days: int | None
    steps: list[dict] | None
    accepted_until: str | None
    applies_to_types: list[str] | None
    extension_by_request: bool
    source_text: str | None
    notes: str | None


class LatePolicyParseRequest(BaseModel):
    text: str


class LatePolicyParseOut(BaseModel):
    """A *proposal*, never a saved policy - the parent confirms it against
    their own handout before anything is written."""

    understood: bool
    summary: str | None = None
    source_sentence: str | None = None
    policy: dict | None = None


class HelpKindOut(BaseModel):
    kind: str
    label: str


class HelpDraftRequest(BaseModel):
    kind: str


class HelpDraftOut(BaseModel):
    kind: str
    label: str
    subject: str
    body: str
    teacher_email: str | None
    # The student sends it from their own mail app; schoolz never sends mail
    # on their behalf and never sees whether they did.
    logged: bool


class CoursePreferenceIn(BaseModel):
    custom_name: str | None = None
    custom_color: str | None = None


class CoursePreferenceOut(BaseModel):
    course_key: str
    custom_name: str | None
    custom_color: str | None


# ---- access -----------------------------------------------------------------


async def _viewer_role(db: AsyncSession, user_id: str, student: Student) -> str | None:
    """"student" when this user *is* the student (Student.user_id), "guardian"
    when they have a GuardianStudentLink, None otherwise. Both roles see the
    same data - that's the point of student accounts (see
    routers/student_accounts.py)."""
    if student.user_id == user_id:
        return "student"
    link = await db.execute(
        select(GuardianStudentLink.id).where(
            GuardianStudentLink.guardian_user_id == user_id, GuardianStudentLink.student_id == student.id
        )
    )
    return "guardian" if link.scalar_one_or_none() else None


async def _get_own_student(db: AsyncSession, user_id: str, student_id: str) -> Student:
    student = await db.get(Student, student_id)
    if not student or await _viewer_role(db, user_id, student) is None:
        # Same 404 for "doesn't exist" and "not yours" - never confirm a
        # student id exists to someone with no access to it.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found on your profile")
    return student


async def _get_own_work_item(db: AsyncSession, student: Student, work_item_id: str) -> ChildWorkItem:
    item = await db.get(ChildWorkItem, work_item_id)
    if not item or item.student_id != student.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    return item


# ---- import / extraction -----------------------------------------------------


async def _upsert_page_kind(db: AsyncSession, adapter: str, source_url: str) -> None:
    kind = ex.classify_page(adapter, source_url)
    existing = await db.get(CapturePageKind, kind.pattern)
    if existing:
        existing.count += 1
        existing.last_seen_at = _now()
    else:
        db.add(
            CapturePageKind(
                pattern=kind.pattern,
                adapter=adapter,
                description=kind.description,
                example_url=source_url,
                count=1,
            )
        )


def _parse_captured_at(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _course_map_for(db: AsyncSession, student: Student, batch: list[dict]) -> ex.CourseMap:
    """Course slug/code -> name, from this upload's Classroom captures AND
    every classroom capture already stored for this student. Schedule/grades
    and Classroom captures are commonly uploaded as separate exports
    (confirmed real: exactly how this feature was first tested) - a map built
    only from one request would leave every Genesis grade's course_name null
    whenever the resolving classroom page came in a different upload."""
    course_map = ex.CourseMap()
    texts = [c["reduced_text"] for c in batch if c.get("adapter") == "classroom" and c.get("reduced_text")]
    stored = await db.execute(
        select(Bucket3Capture.reduced_text).where(
            Bucket3Capture.student_id == student.id, Bucket3Capture.adapter == "classroom"
        )
    )
    texts.extend(text for (text,) in stored.all())
    for text in texts:
        cm = ex.extract_course_map(text)
        course_map.by_slug.update(cm.by_slug)
        course_map.by_numeric.update(cm.by_numeric)
        course_map.by_code.update(cm.by_code)
    return course_map


@dataclass
class _Counters:
    schedule: int = 0
    work_items: int = 0
    grades: int = 0
    mismatches: list[str] = field(default_factory=list)
    seen_work_uids: set[str] = field(default_factory=set)


_WORK_ITEM_KEEP_COLUMNS = (
    "course_name",
    "course_external_id",
    "due_raw",
    "due_date",
    "status",
    "link",
    "teacher_name",
    "posted_raw",
    "posted_date",
    "body",
)


async def _apply_capture(
    db: AsyncSession,
    student: Student,
    adapter: str,
    source_url: str,
    reduced_text: str,
    captured_at: datetime,
    course_map: ex.CourseMap,
    counters: _Counters,
) -> None:
    """Runs extraction for one stored-or-uploaded capture and upserts the
    results. Shared by import and reprocess so both always use the same,
    current parsing."""
    if adapter == "genesis":
        # Guard rail: never silently attach one child's captured data to a
        # different child's record. Checked two ways: the studentid URL param
        # (present on every Genesis page, including gradebook pages, which
        # don't carry the page-body identity block) and, when available, the
        # richer page-body identity.
        url_student_id = ex.genesis_student_id_from_url(source_url)
        if url_student_id and url_student_id != student.student_id:
            counters.mismatches.append(
                f"Capture of {source_url} is for student ID {url_student_id}, not {student.student_id} - skipped."
            )
            return
        identity = ex.extract_genesis_identity(reduced_text)
        if identity and identity.student_id != student.student_id:
            counters.mismatches.append(
                f"Capture of {source_url} is for student ID {identity.student_id}, not {student.student_id} - skipped."
            )
            return

        page_kind = ex.classify_page(adapter, source_url).pattern
        if page_kind == "genesis:gradebook-course":
            await _apply_course_grades(db, student, source_url, reduced_text, captured_at, course_map, counters)
            return
        if page_kind == "genesis:gradebook-weekly":
            for mp in ex.extract_genesis_marking_periods(reduced_text, captured_at):
                await db.execute(
                    pg_insert(ChildMarkingPeriod)
                    .values(student_id=student.id, label=mp.label, start_date=mp.start_date, end_date=mp.end_date)
                    .on_conflict_do_update(
                        index_elements=["student_id", "label"],
                        set_={"start_date": mp.start_date, "end_date": mp.end_date, "updated_at": _now()},
                    )
                )
            return
        await _apply_schedule(db, student, reduced_text, counters)
        return

    if adapter == "classroom":
        # Same guard-rail intent: a family with several kids can have more
        # than one child's Classroom account in one export. Only enforced
        # when the login email's local part is numeric (this district's
        # convention) - permissive otherwise, since a false block would be
        # worse than no check.
        classroom_student_id = ex.classroom_account_student_id(reduced_text)
        if classroom_student_id and classroom_student_id != student.student_id:
            counters.mismatches.append(
                f"Capture of {source_url} is for a Classroom account with student ID "
                f"{classroom_student_id}, not {student.student_id} - skipped."
            )
            return

        page_kind = ex.classify_page(adapter, source_url).pattern
        if page_kind in (
            "classroom:/u/N/c/:courseId/a/:id/details",
            "classroom:/u/N/c/:courseId/m/:id/details",
        ):
            # A details page never carries the title/due/status fields the
            # classwork-grid/stream shapes below extract - it's a wholly
            # different page for a wholly different purpose (updating the
            # one item this points value belongs to, not enumerating a
            # course's worth of items) - so it's handled on its own rather
            # than falling through into extract_classroom_work_items,
            # which would find nothing there anyway (confirmed real: no
            # "Assignment:"/"Material:" aria-label or classwork-button
            # shape appears anywhere on a details page).
            parsed = ex.extract_classroom_detail_points(reduced_text)
            if parsed and parsed[1] is not None:
                item_id, points_possible = parsed
                result = await db.execute(
                    update(ChildWorkItem)
                    .where(
                        ChildWorkItem.student_id == student.id,
                        ChildWorkItem.external_uid == f"si:{item_id}",
                    )
                    .values(points_possible=points_possible, last_seen_at=captured_at)
                )
                # A details page crawled before its own classwork/stream
                # capture has landed has nothing to attach to yet - the
                # UPDATE above simply matches zero rows. Self-heals the
                # next time either capture is reprocessed, so this is
                # silently accepted rather than logged as a mismatch.
                counters.work_items += result.rowcount or 0
            return

        items = ex.extract_classroom_work_items(source_url, reduced_text, course_map)
        items += ex.extract_classroom_announcements(source_url, reduced_text, course_map)
        for item in items:
            ins = pg_insert(ChildWorkItem).values(
                student_id=student.id,
                external_uid=item.external_uid,
                course_name=item.course_name,
                course_external_id=item.course_id,
                title=item.title,
                item_type=item.item_type,
                due_raw=item.due_raw,
                due_date=ex.resolve_due_date(item.due_raw, captured_at),
                status=item.status,
                link=item.link,
                teacher_name=item.teacher_name,
                posted_raw=item.posted_raw,
                posted_date=ex.resolve_posted_date(item.posted_raw, captured_at),
                body=item.body,
                first_seen_at=captured_at,
                last_seen_at=captured_at,
            )
            # A later capture that lacks a field (a classwork-grid row has no
            # teacher; a feed card has no due date) must not erase what an
            # earlier capture already found - only a non-null value replaces.
            set_ = {col: func.coalesce(getattr(ins.excluded, col), getattr(ChildWorkItem, col)) for col in _WORK_ITEM_KEEP_COLUMNS}
            set_["title"] = ins.excluded.title
            set_["item_type"] = ins.excluded.item_type
            set_["last_seen_at"] = func.greatest(ins.excluded.last_seen_at, ChildWorkItem.last_seen_at)
            await db.execute(ins.on_conflict_do_update(index_elements=["student_id", "external_uid"], set_=set_))
            counters.work_items += 1
            counters.seen_work_uids.add(item.external_uid)


async def _apply_course_grades(
    db: AsyncSession,
    student: Student,
    source_url: str,
    reduced_text: str,
    captured_at: datetime,
    course_map: ex.CourseMap,
    counters: _Counters,
) -> None:
    code = ex.genesis_course_code_from_url(source_url)
    sheet = ex.extract_genesis_course_grades(reduced_text)
    if not code or not sheet:
        return
    course_code, course_section = code
    course_name = course_map.by_code.get(code)
    if sheet.marking_period and sheet.marking_period_grade_pct is not None:
        await db.execute(
            pg_insert(ChildCourseGrade)
            .values(
                student_id=student.id,
                course_code=course_code,
                course_section=course_section,
                course_name=course_name,
                marking_period=sheet.marking_period,
                grade_percent=sheet.marking_period_grade_pct,
                last_grade_posted=sheet.last_grade_posted,
            )
            .on_conflict_do_update(
                index_elements=["student_id", "course_code", "course_section", "marking_period"],
                set_={
                    "course_name": course_name,
                    "grade_percent": sheet.marking_period_grade_pct,
                    "last_grade_posted": sheet.last_grade_posted,
                    "updated_at": _now(),
                },
            )
        )
    for entry in sheet.entries:
        uid_source = f"{course_code}-{course_section}:{ex.normalize_title(entry.title)}:{entry.weekday_date}"
        external_uid = hashlib.sha256(uid_source.encode("utf-8")).hexdigest()[:32]
        await db.execute(
            pg_insert(ChildGradeEntry)
            .values(
                student_id=student.id,
                external_uid=external_uid,
                course_code=course_code,
                course_section=course_section,
                course_name=course_name,
                marking_period=sheet.marking_period,
                weekday_date=entry.weekday_date,
                title=entry.title,
                description=entry.description,
                category=entry.category,
                score_earned=entry.score_earned,
                score_possible=entry.score_possible,
                percent=entry.percent,
                status=entry.status,
                is_updated=entry.updated,
                first_seen_at=captured_at,
                last_seen_at=captured_at,
            )
            .on_conflict_do_update(
                index_elements=["student_id", "external_uid"],
                set_={
                    "course_name": course_name,
                    "marking_period": sheet.marking_period,
                    "description": entry.description,
                    "category": entry.category,
                    "score_earned": entry.score_earned,
                    "score_possible": entry.score_possible,
                    "percent": entry.percent,
                    "status": entry.status,
                    "is_updated": entry.updated,
                    "last_seen_at": captured_at,
                },
            )
        )
        counters.grades += 1


async def _apply_schedule(db: AsyncSession, student: Student, reduced_text: str, counters: _Counters) -> None:
    cycle_label = ex.extract_genesis_cycle(reduced_text)
    daily = ex.extract_genesis_daily_blocks(reduced_text)
    if daily:
        schedule_date, blocks = daily
        if cycle_label:
            await db.execute(
                pg_insert(ChildDayCycle)
                .values(student_id=student.id, schedule_date=schedule_date, cycle_label=cycle_label)
                .on_conflict_do_update(
                    index_elements=["student_id", "schedule_date"],
                    set_={"cycle_label": cycle_label, "updated_at": _now()},
                )
            )
        for b in blocks:
            await db.execute(
                pg_insert(ChildScheduleBlock)
                .values(
                    student_id=student.id,
                    source="daily",
                    period=b.period,
                    schedule_date=schedule_date,
                    course_name=b.course,
                    teacher=b.teacher,
                    room=b.room,
                    term=b.term,
                    days=None,
                    time_start=b.time_start,
                    time_end=b.time_end,
                )
                .on_conflict_do_update(
                    index_elements=["student_id", "source", "period", "schedule_date", "term"],
                    set_={
                        "course_name": b.course,
                        "teacher": b.teacher,
                        "room": b.room,
                        "time_start": b.time_start,
                        "time_end": b.time_end,
                        "updated_at": _now(),
                    },
                )
            )
            counters.schedule += 1

    list_blocks = ex.extract_genesis_list_blocks(reduced_text) or []
    if list_blocks:
        # Every list row has schedule_date NULL, and Postgres treats NULLs as
        # distinct in a unique constraint, so the ON CONFLICT target below can
        # never match an existing list row - each re-import inserted a second
        # copy of the whole schedule (confirmed real: 12 rows -> 24 after one
        # reprocess). The list view is a complete-schedule snapshot, so the set
        # is replaced rather than upserted into. This also drops rows left by
        # an older parser, which is how the mis-zipped lunch row went away.
        await db.execute(
            delete(ChildScheduleBlock).where(
                ChildScheduleBlock.student_id == student.id, ChildScheduleBlock.source == "list"
            )
        )
    for b in list_blocks:
        await db.execute(
            pg_insert(ChildScheduleBlock)
            .values(
                student_id=student.id,
                source="list",
                period=b.period,
                schedule_date=None,
                course_name=b.course,
                teacher=b.teacher,
                room=b.room,
                term=b.term,
                days=b.days,
                time_start=None,
                time_end=None,
            )
            .on_conflict_do_update(
                index_elements=["student_id", "source", "period", "schedule_date", "term"],
                set_={
                    "course_name": b.course,
                    "teacher": b.teacher,
                    "room": b.room,
                    "days": b.days,
                    "updated_at": _now(),
                },
            )
        )
        counters.schedule += 1


@router.post("/students/{student_id}/bucket3/import", response_model=Bucket3ImportResult)
async def import_bucket3(
    student_id: str,
    payload: Bucket3ImportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    student = await _get_own_student(db, user.id, student_id)

    # Captures land newest-first in the extension's own export (its
    # background.js unshifts each new capture). Processing oldest-to-newest
    # is what makes "last write wins" upserts reflect the freshest page state
    # - confirmed real: an unsorted pass let a stale due date overwrite a
    # newer one.
    captures = sorted(payload.captures, key=lambda c: c.get("captured_at", ""))
    course_map = await _course_map_for(db, student, captures)

    counters = _Counters()
    skipped_duplicate = 0
    page_kinds_seen: set[str] = set()

    for envelope in captures:
        adapter = envelope.get("adapter")
        source_url = envelope.get("source_url", "")
        reduced_text = envelope.get("reduced_text", "")
        if not adapter or not source_url or envelope.get("status") == "login_wall":
            continue

        page_kinds_seen.add(ex.classify_page(adapter, source_url).pattern)
        await _upsert_page_kind(db, adapter, source_url)

        content_hash = hashlib.sha256(reduced_text.encode("utf-8")).hexdigest()
        existing_capture = await db.execute(
            select(Bucket3Capture.id).where(
                Bucket3Capture.student_id == student.id,
                Bucket3Capture.source_url == source_url,
                Bucket3Capture.content_hash == content_hash,
            )
        )
        if existing_capture.scalar_one_or_none():
            skipped_duplicate += 1
            continue

        captured_at = _parse_captured_at(envelope["captured_at"])
        db.add(
            Bucket3Capture(
                owner_user_id=user.id,
                student_id=student.id,
                adapter=adapter,
                source_url=source_url,
                captured_at=captured_at,
                status=envelope.get("status", "ok"),
                char_count=envelope.get("char_count", len(reduced_text)),
                content_hash=content_hash,
                reduced_text=reduced_text,
            )
        )
        await _apply_capture(db, student, adapter, source_url, reduced_text, captured_at, course_map, counters)

    await db.commit()

    return Bucket3ImportResult(
        captures_processed=len(captures) - skipped_duplicate,
        captures_skipped_duplicate=skipped_duplicate,
        schedule_blocks_upserted=counters.schedule,
        work_items_upserted=counters.work_items,
        grade_entries_upserted=counters.grades,
        page_kinds_seen=len(page_kinds_seen),
        identity_mismatches=counters.mismatches,
    )


@router.post("/students/{student_id}/bucket3/reprocess", response_model=Bucket3ImportResult)
async def reprocess_bucket3(
    student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Re-runs the current extraction over every capture already stored for
    this student. Import's content-hash dedup means an improved parser never
    touches pages imported before the improvement existed (confirmed real: a
    page imported before marking-period parsing existed stayed unparsed on
    re-upload). Work items are rebuilt: rows no capture produces any more are
    removed unless someone marked them done - which also clears the title-hash
    duplicates left behind once feed cards started resolving real ids."""
    student = await _get_own_student(db, user.id, student_id)
    stored = (
        await db.execute(
            select(Bucket3Capture).where(Bucket3Capture.student_id == student.id).order_by(Bucket3Capture.captured_at)
        )
    ).scalars().all()
    course_map = await _course_map_for(db, student, [])
    counters = _Counters()
    for capture in stored:
        await _apply_capture(
            db, student, capture.adapter, capture.source_url, capture.reduced_text, capture.captured_at, course_map, counters
        )

    if counters.seen_work_uids:
        marked = select(ChildWorkItemProgress.work_item_id).where(ChildWorkItemProgress.student_id == student.id)
        await db.execute(
            delete(ChildWorkItem).where(
                ChildWorkItem.student_id == student.id,
                ChildWorkItem.external_uid.not_in(counters.seen_work_uids),
                ChildWorkItem.id.not_in(marked),
            )
        )
    await db.commit()

    return Bucket3ImportResult(
        captures_processed=len(stored),
        captures_skipped_duplicate=0,
        schedule_blocks_upserted=counters.schedule,
        work_items_upserted=counters.work_items,
        grade_entries_upserted=counters.grades,
        page_kinds_seen=len({ex.classify_page(c.adapter, c.source_url).pattern for c in stored}),
        identity_mismatches=counters.mismatches,
    )


# ---- raw views ----------------------------------------------------------------


@router.get("/students/{student_id}/bucket3/schedule", response_model=ChildScheduleOut)
async def get_bucket3_schedule(
    student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    student = await _get_own_student(db, user.id, student_id)

    cycle_result = await db.execute(
        select(ChildDayCycle).where(ChildDayCycle.student_id == student.id).order_by(ChildDayCycle.schedule_date.desc())
    )
    latest_cycle = cycle_result.scalars().first()

    daily_result = await db.execute(
        select(ChildScheduleBlock)
        .where(ChildScheduleBlock.student_id == student.id, ChildScheduleBlock.source == "daily")
        .order_by(ChildScheduleBlock.schedule_date.desc())
    )
    daily_blocks = daily_result.scalars().all()
    latest_date = daily_blocks[0].schedule_date if daily_blocks else None
    daily_today = [b for b in daily_blocks if b.schedule_date == latest_date]

    list_result = await db.execute(
        select(ChildScheduleBlock)
        .where(ChildScheduleBlock.student_id == student.id, ChildScheduleBlock.source == "list")
        .order_by(ChildScheduleBlock.period)
    )
    list_blocks = list_result.scalars().all()

    return ChildScheduleOut(
        cycle_date=latest_cycle.schedule_date if latest_cycle else None,
        cycle_label=latest_cycle.cycle_label if latest_cycle else None,
        daily=[ChildScheduleBlockOut.model_validate(b) for b in daily_today],
        list_view=[ChildScheduleBlockOut.model_validate(b) for b in list_blocks],
    )


@router.get("/students/{student_id}/bucket3/workitems", response_model=list[ChildWorkItemOut])
async def get_bucket3_work_items(
    student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    student = await _get_own_student(db, user.id, student_id)
    result = await db.execute(
        select(ChildWorkItem)
        .where(ChildWorkItem.student_id == student.id)
        .order_by(ChildWorkItem.due_date.is_(None), ChildWorkItem.due_date, ChildWorkItem.last_seen_at.desc())
    )
    return [ChildWorkItemOut.model_validate(it) for it in result.scalars().all()]


async def _get_marking_periods(db: AsyncSession, student_id: str) -> list[ChildMarkingPeriod]:
    result = await db.execute(
        select(ChildMarkingPeriod).where(ChildMarkingPeriod.student_id == student_id).order_by(ChildMarkingPeriod.label)
    )
    return list(result.scalars().all())


def _current_marking_period(marking_periods: list[ChildMarkingPeriod], today: str) -> ChildMarkingPeriod | None:
    return next((mp for mp in marking_periods if mp.start_date <= today <= mp.end_date), None)


async def _marking_period_discrepancies(db: AsyncSession, student: Student, genesis_mps: list[ChildMarkingPeriod]) -> list[str]:
    """Best-effort cross-check against schoolz's own district-sourced
    marking-period scan (services/marking_period.py, SchoolContentItem
    category="marking_period") - confirms the Genesis-derived calendar
    agrees with the public district page, and flags it in plain language
    when it doesn't (could mean either source is stale)."""
    if not genesis_mps or not student.school_id:
        return []
    school = await db.get(School, student.school_id)
    if not school or not school.district_id or not school.school_type:
        return []

    result = await db.execute(
        select(SchoolContentItem).where(
            SchoolContentItem.district_id == school.district_id,
            SchoolContentItem.category == "marking_period",
            SchoolContentItem.title.like("%Marking Period Ends%"),
        )
    )
    district_end_dates = sorted(
        item.start_date.date().isoformat()
        for item in result.scalars().all()
        if not item.applies_to_school_types or school.school_type in item.applies_to_school_types
    )
    if not district_end_dates:
        return []

    discrepancies = []
    for mp, district_end in zip(genesis_mps, district_end_dates):
        if mp.end_date != district_end:
            discrepancies.append(
                f"{mp.label}: Genesis says it ends {mp.end_date}, but the district calendar says {district_end}."
            )
    return discrepancies


@router.get("/students/{student_id}/bucket3/grades", response_model=Bucket3GradesOut)
async def get_bucket3_grades(
    student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    student = await _get_own_student(db, user.id, student_id)
    course_grades = await db.execute(
        select(ChildCourseGrade)
        .where(ChildCourseGrade.student_id == student.id)
        .order_by(ChildCourseGrade.course_name, ChildCourseGrade.marking_period)
    )
    entries = await db.execute(
        select(ChildGradeEntry)
        .where(ChildGradeEntry.student_id == student.id)
        .order_by(ChildGradeEntry.last_seen_at.desc())
    )
    marking_periods = await _get_marking_periods(db, student.id)
    discrepancies = await _marking_period_discrepancies(db, student, marking_periods)
    return Bucket3GradesOut(
        course_grades=[ChildCourseGradeOut.model_validate(g) for g in course_grades.scalars().all()],
        entries=[ChildGradeEntryOut.model_validate(e) for e in entries.scalars().all()],
        marking_periods=[ChildMarkingPeriodOut.model_validate(mp) for mp in marking_periods],
        marking_period_discrepancies=discrepancies,
    )


@router.get("/students/{student_id}/bucket3/audit", response_model=Bucket3AuditOut)
async def get_bucket3_audit(
    student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """The "Venn diagram" between what Classroom and Genesis each report for
    this child, matched by normalized assignment title (see
    services/bucket3_extract.py:normalize_title for why an exact normalized
    match, not fuzzy matching, is the deliberate choice). This exists because
    teachers don't reliably keep both systems in sync - the point is surfacing
    that gap, not papering over it."""
    student = await _get_own_student(db, user.id, student_id)
    classroom_items = (
        await db.execute(
            select(ChildWorkItem).where(
                ChildWorkItem.student_id == student.id, ChildWorkItem.item_type != "announcement"
            )
        )
    ).scalars().all()
    genesis_entries = (
        await db.execute(select(ChildGradeEntry).where(ChildGradeEntry.student_id == student.id))
    ).scalars().all()

    classroom_by_key: dict[str, list[ChildWorkItem]] = {}
    for it in classroom_items:
        classroom_by_key.setdefault(ex.normalize_title(it.title), []).append(it)
    genesis_by_key: dict[str, list[ChildGradeEntry]] = {}
    for e in genesis_entries:
        genesis_by_key.setdefault(ex.normalize_title(e.title), []).append(e)

    matched: list[AuditMatchedOut] = []
    classroom_only: list[ChildWorkItem] = []
    genesis_only: list[ChildGradeEntry] = []

    for key, items in classroom_by_key.items():
        genesis_matches = genesis_by_key.get(key)
        if genesis_matches:
            for it in items:
                for e in genesis_matches:
                    matched.append(
                        AuditMatchedOut(
                            title=it.title,
                            classroom=ChildWorkItemOut.model_validate(it),
                            genesis=ChildGradeEntryOut.model_validate(e),
                        )
                    )
        else:
            classroom_only.extend(items)

    for key, entries in genesis_by_key.items():
        if key not in classroom_by_key:
            genesis_only.extend(entries)

    # A "missing" item from a marking period that already ended doesn't
    # matter any more (explicit product rule) - it clutters the list Classroom
    # itself never stops showing. No filtering when no MP contains today.
    current_mp = _current_marking_period(await _get_marking_periods(db, student.id), _local_today())
    classroom_only_current = (
        [it for it in classroom_only if not it.due_date or it.due_date >= current_mp.start_date]
        if current_mp
        else classroom_only
    )

    return Bucket3AuditOut(
        matched=matched,
        classroom_only=[ChildWorkItemOut.model_validate(it) for it in classroom_only_current],
        classroom_only_all_time=[ChildWorkItemOut.model_validate(it) for it in classroom_only],
        genesis_only=[ChildGradeEntryOut.model_validate(e) for e in genesis_only],
        current_marking_period=current_mp.label if current_mp else None,
        counts={
            "matched": len(matched),
            "classroom_only": len(classroom_only_current),
            "classroom_only_all_time": len(classroom_only),
            "genesis_only": len(genesis_only),
            "classroom_total": len(classroom_items),
            "genesis_total": len(genesis_entries),
        },
    )


@router.get("/students/{student_id}/bucket3/student", response_model=Bucket3StudentOut)
async def get_bucket3_student(
    student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """The header for the Kids detail view, readable by a guardian *or* the
    student themselves - GET /students is guardian-only (it's the "my
    children" list), so a student account needs this to see their own record
    at all."""
    student = await _get_own_student(db, user.id, student_id)
    return Bucket3StudentOut(
        id=student.id,
        first_name=student.first_name,
        last_name=student.last_name,
        student_id=student.student_id,
        school_name=student.school_name,
        viewer_role=await _viewer_role(db, user.id, student),
    )


# ---- Kids view v2 ----------------------------------------------------------------


async def _staff_directory(db: AsyncSession, student: Student) -> list[tuple[str, str | None]]:
    if not student.school_id:
        return []
    rows = await db.execute(
        select(StaffMember.full_name, StaffMember.email).where(StaffMember.school_id == student.school_id)
    )
    return [(name, email) for name, email in rows.all()]


def _marker_name(user_id: str | None, student: Student, usernames: dict[str, str]) -> str | None:
    if not user_id:
        return None
    if user_id == student.user_id:
        return student.first_name
    return usernames.get(user_id)


async def _todo_items(db: AsyncSession, student: Student) -> tuple[list[dict], ChildMarkingPeriod | None, str]:
    """Every current-marking-period to-do item for this student, with its
    Due/Missing/Done category resolved (services/kids_view.py holds the rules)
    and everything the dashboard shows next to it attached."""
    today = _local_today()
    current_mp = _current_marking_period(await _get_marking_periods(db, student.id), today)

    all_items = (
        await db.execute(select(ChildWorkItem).where(ChildWorkItem.student_id == student.id))
    ).scalars().all()
    work = [w for w in all_items if w.item_type not in kids_view.REFERENCE_TYPES]

    marks = {
        p.work_item_id: p
        for p in (
            await db.execute(select(ChildWorkItemProgress).where(ChildWorkItemProgress.student_id == student.id))
        ).scalars().all()
    }
    marker_ids = {p.marked_by_user_id for p in marks.values() if p.marked_by_user_id}
    usernames = (
        {u.id: u.username for u in (await db.execute(select(User).where(User.id.in_(marker_ids)))).scalars().all()}
        if marker_ids
        else {}
    )

    grades_by_title: dict[str, ChildGradeEntry] = {}
    for entry in (
        await db.execute(
            select(ChildGradeEntry)
            .where(ChildGradeEntry.student_id == student.id)
            .order_by(ChildGradeEntry.last_seen_at.desc())
        )
    ).scalars().all():
        grades_by_title.setdefault(ex.normalize_title(entry.title), entry)

    # A classwork-grid row never says who posted it; the course's feed cards
    # and announcements do. Fall back to whoever posts most in that course.
    poster_counts: dict[str, Counter] = {}
    for w in all_items:
        if w.teacher_name and w.course_external_id:
            poster_counts.setdefault(w.course_external_id, Counter())[w.teacher_name] += 1
    course_teacher = {course: counts.most_common(1)[0][0] for course, counts in poster_counts.items()}

    staff = await _staff_directory(db, student)

    policies = {
        (p.course_code, p.course_section): p
        for p in (
            await db.execute(select(CourseLatePolicy).where(CourseLatePolicy.student_id == student.id))
        ).scalars().all()
    }
    exceptions = {
        e.work_item_id: e
        for e in (
            await db.execute(select(WorkItemLateException).where(WorkItemLateException.student_id == student.id))
        ).scalars().all()
    }
    asked: dict[str, list[str]] = {}
    for h in (
        await db.execute(
            select(HelpRequest).where(HelpRequest.student_id == student.id).order_by(HelpRequest.created_at)
        )
    ).scalars().all():
        kinds = asked.setdefault(h.work_item_id, [])
        if h.kind not in kinds:
            kinds.append(h.kind)

    keyed = [(w, kids_view.course_key(w.course_name, w.course_external_id), ex.normalize_title(w.title)) for w in work]
    suggestion_keys = {(code, section, norm) for _, (code, section), norm in keyed}
    suggestions = {}
    if suggestion_keys:
        rows = await db.execute(
            select(AssignmentSuggestion).where(
                tuple_(
                    AssignmentSuggestion.course_code,
                    AssignmentSuggestion.course_section,
                    AssignmentSuggestion.normalized_title,
                ).in_(list(suggestion_keys))
            )
        )
        suggestions = {(s.course_code, s.course_section, s.normalized_title): s for s in rows.scalars().all()}

    items = []
    for w, key, norm in keyed:
        mark = marks.get(w.id)
        grade = grades_by_title.get(norm)
        has_real_grade = bool(grade and grade.percent is not None and grade.status not in ("Missing", "Exempt"))
        done, source = kids_view.resolve_done(mark.done if mark else None, w.status, has_real_grade)
        category = kids_view.todo_category(w.item_type, w.due_date, done, today)
        exception = exceptions.get(w.id)
        if not kids_view.in_current_marking_period(
            category,
            w.due_date,
            current_mp.start_date if current_mp else None,
            has_exception=exception is not None,
        ):
            continue
        teacher = w.teacher_name or course_teacher.get(w.course_external_id)
        cached = suggestions.get((key[0], key[1], norm))
        items.append(
            {
                "id": w.id,
                "title": w.title,
                "item_type": w.item_type,
                "course_name": w.course_name,
                "course_key": kids_view.course_key_str(key),
                "due_raw": w.due_raw,
                "due_date": w.due_date,
                "category": category,
                "done": done,
                "done_source": source,
                "marked_by": _marker_name(mark.marked_by_user_id, student, usernames) if mark and mark.done else None,
                "classroom_status": w.status,
                "grade": (
                    {
                        "score_earned": grade.score_earned,
                        "score_possible": grade.score_possible,
                        "percent": grade.percent,
                        "status": grade.status,
                    }
                    if grade
                    else None
                ),
                "points_possible": w.points_possible,
                "teacher_name": teacher,
                "teacher_emails": kids_view.match_teacher_emails(teacher, staff),
                "link": w.link,
                "suggestion": {"text": cached.suggestion_text, "declined": cached.declined} if cached else None,
                # The (code, section) tuple, for internal grouping only (course_progress,
                # policy/suggestion lookups) - "course_key" above is the joined string
                # TodoItemOut actually serializes; same dict literal can't hold both
                # under one name.
                "course_key_tuple": key,
                "late_credit": kids_view.late_credit(
                    policies.get(key),
                    w.due_date,
                    today,
                    mp_end=current_mp.end_date if current_mp else None,
                    item_type=w.item_type,
                    exception=exception,
                ),
                "late_exception": (
                    {
                        "accepted_until": exception.accepted_until,
                        "credit_pct": exception.credit_pct,
                        "granted_note": exception.granted_note,
                    }
                    if exception
                    else None
                ),
                "asked_kinds": asked.get(w.id, []),
            }
        )
    return items, current_mp, today


@router.get("/students/{student_id}/bucket3/right-now", response_model=RightNowOut)
async def get_right_now(student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    student = await _get_own_student(db, user.id, student_id)
    blocks = (
        await db.execute(
            select(ChildScheduleBlock).where(
                ChildScheduleBlock.student_id == student.id, ChildScheduleBlock.source == "daily"
            )
        )
    ).scalars().all()
    school = await db.get(School, student.school_id) if student.school_id else None
    result = kids_view.right_now(blocks, school.bell_periods if school else None, _local_now())

    staff = await _staff_directory(db, student)
    for block in result["blocks"]:  # current/next are the same dicts
        block["teacher_emails"] = kids_view.match_teacher_emails(block["teacher"], staff)

    if result["schedule_date"]:
        cycle = await db.execute(
            select(ChildDayCycle.cycle_label).where(
                ChildDayCycle.student_id == student.id, ChildDayCycle.schedule_date == result["schedule_date"]
            )
        )
        result["cycle_label"] = cycle.scalar_one_or_none()
    return result


@router.get("/students/{student_id}/bucket3/todo", response_model=TodoOut)
async def get_todo(student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    student = await _get_own_student(db, user.id, student_id)
    items, current_mp, _today = await _todo_items(db, student)
    buckets: dict[str, list[dict]] = {"missing": [], "due": [], "done": [], "no_due_date": []}
    for item in items:
        buckets[item["category"]].append(item)
    buckets["missing"].sort(key=lambda i: (i["due_date"] or "", i["title"]))
    buckets["due"].sort(key=lambda i: (i["due_date"] or "", i["title"]))
    buckets["done"].sort(key=lambda i: i["due_date"] or "", reverse=True)
    buckets["no_due_date"].sort(key=lambda i: i["title"])
    return TodoOut(
        current_marking_period=ChildMarkingPeriodOut.model_validate(current_mp) if current_mp else None,
        progress=kids_view.progress(items),
        next_action=kids_view.pick_next_action(items),
        **buckets,
    )


@router.get("/students/{student_id}/bucket3/progress", response_model=list[CourseProgressOut])
async def get_course_progress(
    student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    student = await _get_own_student(db, user.id, student_id)
    items, current_mp, today = await _todo_items(db, student)
    entry_query = select(ChildGradeEntry).where(ChildGradeEntry.student_id == student.id)
    grade_query = select(ChildCourseGrade).where(ChildCourseGrade.student_id == student.id)
    if current_mp:
        entry_query = entry_query.where(ChildGradeEntry.marking_period == current_mp.label)
        grade_query = grade_query.where(ChildCourseGrade.marking_period == current_mp.label)
    entries = (await db.execute(entry_query)).scalars().all()
    course_grades = (await db.execute(grade_query)).scalars().all()
    return kids_view.course_progress(items, entries, course_grades, today)


@router.get("/students/{student_id}/bucket3/announcements", response_model=list[AnnouncementOut])
async def get_announcements(
    student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    student = await _get_own_student(db, user.id, student_id)
    rows = (
        await db.execute(
            select(ChildWorkItem)
            .where(ChildWorkItem.student_id == student.id, ChildWorkItem.item_type == "announcement")
            .order_by(ChildWorkItem.posted_date.desc().nulls_last(), ChildWorkItem.last_seen_at.desc())
            .limit(100)
        )
    ).scalars().all()
    staff = await _staff_directory(db, student)
    return [
        AnnouncementOut(
            id=a.id,
            title=a.title,
            course_name=a.course_name,
            teacher_name=a.teacher_name,
            teacher_emails=kids_view.match_teacher_emails(a.teacher_name, staff),
            posted_raw=a.posted_raw,
            posted_date=a.posted_date,
            body=a.body,
            link=a.link,
        )
        for a in rows
    ]


@router.get("/students/{student_id}/bucket3/teacher-emails", response_model=dict[str, list[str]])
async def get_teacher_emails(
    student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Every teacher name seen for this student (Classroom posters, Genesis
    schedule teachers) resolved against the school's staff directory. An
    ambiguous or unknown name maps to an empty list - never a guessed email."""
    student = await _get_own_student(db, user.id, student_id)
    names = {
        n
        for (n,) in (
            await db.execute(
                select(ChildWorkItem.teacher_name).where(
                    ChildWorkItem.student_id == student.id, ChildWorkItem.teacher_name.is_not(None)
                )
            )
        ).all()
    }
    names |= {
        n
        for (n,) in (
            await db.execute(
                select(ChildScheduleBlock.teacher).where(
                    ChildScheduleBlock.student_id == student.id, ChildScheduleBlock.teacher.is_not(None)
                )
            )
        ).all()
    }
    staff = await _staff_directory(db, student)
    return {name: kids_view.match_teacher_emails(name, staff) for name in sorted(names)}


@router.post("/students/{student_id}/bucket3/workitems/{work_item_id}/complete", response_model=CompleteOut)
async def complete_work_item(
    student_id: str,
    work_item_id: str,
    payload: CompleteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an item done (or explicitly not done). One shared row per item:
    the student and every guardian change the same state, and who changed it
    is kept."""
    student = await _get_own_student(db, user.id, student_id)
    item = await _get_own_work_item(db, student, work_item_id)
    await db.execute(
        pg_insert(ChildWorkItemProgress)
        .values(student_id=student.id, work_item_id=item.id, done=payload.done, marked_by_user_id=user.id)
        .on_conflict_do_update(
            index_elements=["student_id", "work_item_id"],
            set_={"done": payload.done, "marked_by_user_id": user.id, "updated_at": _now()},
        )
    )
    await db.commit()
    return CompleteOut(
        id=item.id,
        done=payload.done,
        marked_by=_marker_name(user.id, student, {user.id: user.username}) if payload.done else None,
    )


@router.post("/students/{student_id}/bucket3/suggestions/assignment/{work_item_id}", response_model=SuggestionOut)
async def suggest_for_assignment(
    student_id: str, work_item_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Shared "how to approach this" note for one assignment in one class
    (docs/KIDS_VIEW_V2_DESIGN.md §7 tier A). Reused by every student in the
    same course section; only generated - from the title and course name
    alone - the first time anyone asks."""
    student = await _get_own_student(db, user.id, student_id)
    item = await _get_own_work_item(db, student, work_item_id)
    code, section = kids_view.course_key(item.course_name, item.course_external_id)
    norm = ex.normalize_title(item.title)

    existing = (
        await db.execute(
            select(AssignmentSuggestion).where(
                AssignmentSuggestion.course_code == code,
                AssignmentSuggestion.course_section == section,
                AssignmentSuggestion.normalized_title == norm,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return SuggestionOut(text=existing.suggestion_text, declined=existing.declined, cached=True)

    try:
        text, declined = await kids_suggestions.assignment_suggestion(item.title, item.course_name)
    except kids_suggestions.SuggestionsUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Suggestions aren't configured on this server")
    except Exception:
        logger.exception("assignment_suggestion_failed", extra={"work_item_id": item.id})
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Couldn't reach the suggestion service - try again in a bit")

    await db.execute(
        pg_insert(AssignmentSuggestion)
        .values(
            course_code=code,
            course_section=section,
            normalized_title=norm,
            suggestion_text=text,
            declined=declined,
            model=kids_suggestions.MODEL,
        )
        .on_conflict_do_nothing(index_elements=["course_code", "course_section", "normalized_title"])
    )
    await db.commit()
    return SuggestionOut(text=text, declined=declined, cached=False)


@router.post("/students/{student_id}/bucket3/suggestions/plan", response_model=PlanOut)
async def suggest_plan(student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """A short, personal "what order should I do this in" for the student's
    current Missing + Due list (tier B). Never cached or stored."""
    student = await _get_own_student(db, user.id, student_id)
    items, _current_mp, today = await _todo_items(db, student)
    open_items = sorted(
        (i for i in items if i["category"] in ("missing", "due")),
        key=lambda i: (i["category"] != "missing", i["due_date"] or ""),
    )
    if not open_items:
        return PlanOut(text="Nothing due or missing right now - nothing to plan.")
    try:
        text = await kids_suggestions.plan(open_items, today)
    except kids_suggestions.SuggestionsUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Suggestions aren't configured on this server")
    except Exception:
        logger.exception("plan_suggestion_failed", extra={"student_id": student.id})
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Couldn't reach the suggestion service - try again in a bit")
    return PlanOut(text=text)


def _policy_out(p: CourseLatePolicy) -> LatePolicyOut:
    return LatePolicyOut(
        course_key=f"{p.course_code}-{p.course_section}" if p.course_section else p.course_code,
        course_name=p.course_name,
        shape=p.shape,
        penalty_pct=p.penalty_pct,
        penalty_per_day=p.penalty_per_day,
        floor_pct=p.floor_pct,
        window_days=p.window_days,
        steps=p.steps,
        accepted_until=p.accepted_until,
        applies_to_types=p.applies_to_types,
        extension_by_request=p.extension_by_request,
        source_text=p.source_text,
        notes=p.notes,
    )


def _split_course_key(course_key: str) -> tuple[str, str]:
    """Reverse of the "code-section" join course_progress emits. A fallback
    key ("slug:..."/"name:...") has no section and must not be split on its
    own hyphens, so only the last segment of a real code pair is peeled off."""
    if course_key.startswith(("slug:", "name:")) or "-" not in course_key:
        return course_key, ""
    code, section = course_key.rsplit("-", 1)
    return code, section


@router.get("/students/{student_id}/bucket3/late-policies", response_model=list[LatePolicyOut])
async def list_late_policies(
    student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    student = await _get_own_student(db, user.id, student_id)
    rows = (
        await db.execute(
            select(CourseLatePolicy)
            .where(CourseLatePolicy.student_id == student.id)
            .order_by(CourseLatePolicy.course_name.nulls_last(), CourseLatePolicy.course_code)
        )
    ).scalars().all()
    return [_policy_out(p) for p in rows]


@router.put("/students/{student_id}/bucket3/late-policies", response_model=LatePolicyOut)
async def save_late_policy(
    student_id: str,
    payload: LatePolicyIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or replace one class's late-work policy. Per (student, course)
    on purpose - one family's transcription of their own handout, never
    shared with other families the way AssignmentSuggestion is."""
    student = await _get_own_student(db, user.id, student_id)
    if payload.shape not in kids_view.LATE_SHAPES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown late-policy shape '{payload.shape}'")
    code, section = _split_course_key(payload.course_key)
    values = {
        "student_id": student.id,
        "course_code": code,
        "course_section": section,
        "course_name": payload.course_name,
        "shape": payload.shape,
        "penalty_pct": payload.penalty_pct,
        "penalty_per_day": payload.penalty_per_day,
        "floor_pct": payload.floor_pct,
        "window_days": payload.window_days,
        "steps": payload.steps,
        "accepted_until": payload.accepted_until,
        "applies_to_types": payload.applies_to_types,
        "extension_by_request": payload.extension_by_request,
        "source_text": payload.source_text,
        "notes": payload.notes,
    }
    await db.execute(
        pg_insert(CourseLatePolicy)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["student_id", "course_code", "course_section"],
            set_={k: v for k, v in values.items() if k not in ("student_id", "course_code", "course_section")}
            | {"updated_at": _now()},
        )
    )
    await db.commit()
    saved = (
        await db.execute(
            select(CourseLatePolicy).where(
                CourseLatePolicy.student_id == student.id,
                CourseLatePolicy.course_code == code,
                CourseLatePolicy.course_section == section,
            )
        )
    ).scalar_one()
    return _policy_out(saved)


@router.delete("/students/{student_id}/bucket3/late-policies/{course_key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_late_policy(
    student_id: str, course_key: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    student = await _get_own_student(db, user.id, student_id)
    code, section = _split_course_key(course_key)
    await db.execute(
        delete(CourseLatePolicy).where(
            CourseLatePolicy.student_id == student.id,
            CourseLatePolicy.course_code == code,
            CourseLatePolicy.course_section == section,
        )
    )
    await db.commit()


@router.post("/students/{student_id}/bucket3/late-policies/parse", response_model=LatePolicyParseOut)
async def parse_late_policy(
    student_id: str,
    payload: LatePolicyParseRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Turn a pasted syllabus paragraph into a proposed policy. Deliberately
    does NOT save: a misread late policy quietly changes what the dashboard
    tells a kid to work on next, so a person confirms it against the handout
    first."""
    await _get_own_student(db, user.id, student_id)
    text = payload.text.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Paste the late-work paragraph first")
    try:
        parsed = await kids_suggestions.parse_late_policy(text)
    except kids_suggestions.SuggestionsUnavailable:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Suggestions aren't configured on this server")
    except Exception:
        logger.exception("late_policy_parse_failed", extra={"student_id": student_id})
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Couldn't reach the parser - try again in a bit")

    if not parsed.get("understood"):
        return LatePolicyParseOut(understood=False)
    policy = {
        k: parsed[k]
        for k in (
            "shape",
            "penalty_pct",
            "penalty_per_day",
            "floor_pct",
            "window_days",
            "steps",
            "accepted_until",
            "applies_to_types",
            "extension_by_request",
        )
        if k in parsed
    }
    return LatePolicyParseOut(
        understood=True,
        summary=parsed.get("summary"),
        source_sentence=parsed.get("source_sentence") or text,
        policy=policy,
    )


@router.put(
    "/students/{student_id}/bucket3/workitems/{work_item_id}/late-exception", response_model=LateExceptionOut
)
async def set_late_exception(
    student_id: str,
    work_item_id: str,
    payload: LateExceptionIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record that a teacher said yes to this one assignment.

    This overrides the class's late policy for this item and beats the
    marking-period filter, so work the app had written off comes back -
    which is the whole point. Confirmed real with more than one teacher:
    "turn it in before the marking period ends and I'll take it"."""
    student = await _get_own_student(db, user.id, student_id)
    item = await _get_own_work_item(db, student, work_item_id)
    until = payload.accepted_until.strip()
    if until != "marking_period_end":
        try:
            date.fromisoformat(until)
        except ValueError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "accepted_until must be an ISO date (YYYY-MM-DD) or 'marking_period_end'",
            )
    values = {
        "student_id": student.id,
        "work_item_id": item.id,
        "accepted_until": until,
        "credit_pct": payload.credit_pct,
        "granted_note": payload.granted_note,
        "recorded_by_user_id": user.id,
    }
    await db.execute(
        pg_insert(WorkItemLateException)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["student_id", "work_item_id"],
            set_={
                "accepted_until": until,
                "credit_pct": payload.credit_pct,
                "granted_note": payload.granted_note,
                "recorded_by_user_id": user.id,
                "updated_at": _now(),
            },
        )
    )
    await db.commit()
    return LateExceptionOut(
        accepted_until=until, credit_pct=payload.credit_pct, granted_note=payload.granted_note
    )


@router.delete(
    "/students/{student_id}/bucket3/workitems/{work_item_id}/late-exception",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_late_exception(
    student_id: str, work_item_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    student = await _get_own_student(db, user.id, student_id)
    item = await _get_own_work_item(db, student, work_item_id)
    await db.execute(
        delete(WorkItemLateException).where(
            WorkItemLateException.student_id == student.id, WorkItemLateException.work_item_id == item.id
        )
    )
    await db.commit()


@router.get("/students/{student_id}/bucket3/help-kinds", response_model=list[HelpKindOut])
async def list_help_kinds(
    student_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """The pick-a-kind menu for "I have no idea what this is about"."""
    await _get_own_student(db, user.id, student_id)
    return [HelpKindOut(**k) for k in help_svc.menu()]


@router.post("/students/{student_id}/bucket3/workitems/{work_item_id}/ask-teacher", response_model=HelpDraftOut)
async def draft_teacher_email(
    student_id: str,
    work_item_id: str,
    payload: HelpDraftRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Draft the email for one kind of stuck, and record that the ask
    happened.

    The draft is returned for a mailto: link - the student sends it from
    their own mail app, so schoolz never transmits mail on their behalf and
    never learns whether or what they sent. What's recorded is only that an
    ask of this kind happened, which is what makes a pattern ("can't tell
    what's being asked, every Geometry assignment") visible to a guardian."""
    student = await _get_own_student(db, user.id, student_id)
    item = await _get_own_work_item(db, student, work_item_id)
    if payload.kind not in help_svc.KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unknown help kind '{payload.kind}'")

    # Resolve the teacher exactly the way the dashboard did, not from
    # item.teacher_name alone: a classwork-grid row carries no teacher, and
    # _todo_items falls back to whoever posts most in that course. If the
    # modal said "Pat Jones", the email has to go to Pat Jones - reading the
    # raw column instead would silently address it to nobody.
    items, _mp, _today = await _todo_items(db, student)
    enriched = next((i for i in items if i["id"] == item.id), None)
    if enriched:
        teacher, emails = enriched["teacher_name"], enriched["teacher_emails"]
    else:
        # Filtered out of the dashboard (an older marking period, say) but
        # still a real item someone opened - resolve it directly.
        teacher = item.teacher_name
        emails = kids_view.match_teacher_emails(teacher, await _staff_directory(db, student))
    draft = help_svc.compose(payload.kind, item.title, item.course_name, teacher, student.first_name)

    db.add(
        HelpRequest(
            student_id=student.id,
            work_item_id=item.id,
            kind=payload.kind,
            teacher_email=emails[0] if emails else None,
            created_by_user_id=user.id,
        )
    )
    # Tell the guardians it happened - not what was written. A student
    # asking for help is the behaviour this whole flow is trying to make
    # easier; a parent who can see it happening can notice the pattern
    # without reading over anyone's shoulder.
    message = help_svc.notification_message(student.first_name, payload.kind, item.title, item.course_name)
    for link in (
        await db.execute(select(GuardianStudentLink).where(GuardianStudentLink.student_id == student.id))
    ).scalars().all():
        if link.guardian_user_id != user.id:
            db.add(
                Notification(
                    user_id=link.guardian_user_id, type="help_asked", message=message, student_id=student.id
                )
            )
    await db.commit()

    return HelpDraftOut(
        **draft, teacher_email=emails[0] if emails else None, logged=True
    )


# ---- per-account course display preferences ---------------------------------
#
# Deliberately NOT nested under /students/{student_id} the way everything
# else in this file is - a color/name pick is a fact about the ACCOUNT that
# made it, not about any one student. A Student row is shared across every
# linked guardian, so scoping this by student_id would leak one guardian's
# rename to every other guardian (and the kid) who can see the same
# student - explicit product requirement (2026-09-20) that this stay local
# to the account that picked it. Keying on the account rather than a device
# (the original localStorage-only version) is the whole point: it's what
# lets the pick follow that person across their own devices while staying
# invisible to everyone else.


@router.get("/course-preferences", response_model=list[CoursePreferenceOut])
async def list_course_preferences(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(CourseDisplayPreference).where(CourseDisplayPreference.user_id == user.id))
    ).scalars().all()
    return [
        CoursePreferenceOut(course_key=r.course_key, custom_name=r.custom_name, custom_color=r.custom_color)
        for r in rows
    ]


@router.put("/course-preferences/{course_key}", response_model=CoursePreferenceOut)
async def set_course_preference(
    course_key: str,
    payload: CoursePreferenceIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upsert, or delete once both fields go back to null - a row that
    carries no actual override is nothing to keep around."""
    if payload.custom_name is None and payload.custom_color is None:
        await db.execute(
            delete(CourseDisplayPreference).where(
                CourseDisplayPreference.user_id == user.id, CourseDisplayPreference.course_key == course_key
            )
        )
        await db.commit()
        return CoursePreferenceOut(course_key=course_key, custom_name=None, custom_color=None)

    values = {
        "user_id": user.id,
        "course_key": course_key,
        "custom_name": payload.custom_name,
        "custom_color": payload.custom_color,
    }
    await db.execute(
        pg_insert(CourseDisplayPreference)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["user_id", "course_key"],
            set_={"custom_name": payload.custom_name, "custom_color": payload.custom_color, "updated_at": _now()},
        )
    )
    await db.commit()
    return CoursePreferenceOut(course_key=course_key, custom_name=payload.custom_name, custom_color=payload.custom_color)


@router.get("/admin/capture-page-kinds", response_model=list[CapturePageKindOut])
async def list_capture_page_kinds(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(CapturePageKind).order_by(CapturePageKind.last_seen_at.desc()))
    return [CapturePageKindOut.model_validate(k) for k in result.scalars().all()]
