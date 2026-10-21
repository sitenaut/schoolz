"""My family (frontend pages/FamilyPage.tsx): each of a guardian's children,
what schoolz can bring in for them, and how much of it has arrived.

Homework and grades exist only where the child's district has Google
Classroom or a Genesis that Backpack Capture can read (District.
uses_google_classroom / genesis_url), or where that data already arrived -
so the page never offers them for a school where they can't work. The counts
reuse the Kids view's own rules (routers/bucket3.py) rather than a second
copy of what "due" and "missing" mean.
"""

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models import (
    ChildCourseGrade,
    ChildScheduleBlock,
    District,
    GuardianStudentLink,
    School,
    Student,
    StudentAccountInvite,
    StudentSpecial,
    User,
)
from routers import bucket3
from routers.students import _student_out
from schemas import FamilyChildOut, FamilyTodayOut
from services import kids_view

router = APIRouter(tags=["family"])


def due_this_week(items: list[dict], today_iso: str) -> int:
    """Not-done work due from today through the next six days."""
    last = (date.fromisoformat(today_iso) + timedelta(days=6)).isoformat()
    return sum(1 for i in items if i["category"] == "due" and i["due_date"] and i["due_date"] <= last)


def today_line(now: dict) -> FamilyTodayOut | None:
    """kids_view.right_now's answer as one line, or None when no schedule for
    today was captured (a stale day is never shown as today)."""
    if now["stale"] or not now["blocks"]:
        return None
    if now["current"]:
        b = now["current"]
        return FamilyTodayOut(state="now", course_name=b["course_name"], room=b["room"], time_start=b["time_start"], time_end=b["time_end"])
    if now["school_day_over"]:
        return FamilyTodayOut(state="over")
    if now["next"]:
        b = now["next"]
        return FamilyTodayOut(state="next", course_name=b["course_name"], room=b["room"], time_start=b["time_start"], time_end=b["time_end"])
    return None


async def _child(db: AsyncSession, user: User, student: Student, link: GuardianStudentLink) -> FamilyChildOut:
    base = await _student_out(db, student, link)
    school = await db.get(School, student.school_id) if student.school_id else None
    district = await db.get(District, school.district_id) if school and school.district_id else None
    status = await bucket3.sync_status(db, user.id, student)

    due = missing = classes = None
    today = None
    if status.classroom_seen_at:
        items, _mp, today_iso = await bucket3._todo_items(db, student)
        due = due_this_week(items, today_iso)
        missing = sum(1 for i in items if i["category"] == "missing")
    if status.genesis_seen_at:
        classes = (
            await db.execute(
                select(func.count(func.distinct(tuple_(ChildCourseGrade.course_code, ChildCourseGrade.course_section)))).where(
                    ChildCourseGrade.student_id == student.id
                )
            )
        ).scalar_one()
        blocks = (
            (await db.execute(select(ChildScheduleBlock).where(ChildScheduleBlock.student_id == student.id, ChildScheduleBlock.source == "daily")))
            .scalars()
            .all()
        )
        today = today_line(kids_view.right_now(blocks, school.bell_periods if school else None, bucket3._local_now()))

    login_email = None
    if student.user_id:
        account = await db.get(User, student.user_id)
        login_email = account.email if account else None
    invite = (
        (
            await db.execute(
                select(StudentAccountInvite)
                .where(
                    StudentAccountInvite.student_id == student.id,
                    StudentAccountInvite.status == "pending",
                    StudentAccountInvite.expires_at > datetime.now(UTC),
                )
                .order_by(StudentAccountInvite.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    specials = (await db.execute(select(func.count()).select_from(StudentSpecial).where(StudentSpecial.student_id == student.id))).scalar_one()

    return FamilyChildOut(
        **base.model_dump(),
        district_name=district.name if district else None,
        has_classroom=bool(district and district.uses_google_classroom) or status.classroom_seen_at is not None,
        has_genesis=bool(district and district.genesis_url) or status.genesis_seen_at is not None,
        classroom_seen_at=status.classroom_seen_at,
        genesis_seen_at=status.genesis_seen_at,
        needs_login=status.needs_login,
        due_this_week=due,
        missing=missing,
        classes=classes,
        today=today,
        student_login_email=login_email,
        student_invite_email=invite.invitee_email if invite else None,
        specials_count=specials,
    )


@router.get("/family", response_model=list[FamilyChildOut])
async def my_family(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """The caller's own children (their GuardianStudentLinks), oldest link
    first like GET /students. A student's own login has none."""
    rows = await db.execute(
        select(Student, GuardianStudentLink)
        .join(GuardianStudentLink, GuardianStudentLink.student_id == Student.id)
        .where(GuardianStudentLink.guardian_user_id == user.id)
        .order_by(GuardianStudentLink.created_at)
    )
    return [await _child(db, user, student, link) for student, link in rows.all()]
