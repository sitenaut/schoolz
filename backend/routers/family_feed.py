"""GET /family/feed: one person's family, for an app they connected
(routers/family_connections.py) - billz, the owner's household app.

One read returns a snapshot of a date window: the person's children, their
schools, and every item in the window, each under a stable `uid`. The app
keeps items by uid and drops one that a newer snapshot no longer has while
the window still covers it. That is the whole sync: most of what feeds this
has no updated_at (a newsletter correction is a new row, a revised district
PDF replaces every row), so there is no "changed since" to ask for; each
item's `hash` says whether it changed. docs/FAMILY_FEED.md has the contract.

Built with the site's own rules: day status and rotation days as on Today
(services/school_today.py), each child's classes or specials as on their
schedule (services/kids_schedule.py), schoolwork as on Gradez
(routers/bucket3._todo_items). English only; nothing here calls a model,
the scraper or the weather.

What never leaves: a child's last name and district student ID (with the
first name, the auto-match key that would let the holder link their own
account to the child), the child's login and invite emails, who marked work
done, help requests, teacher emails and captured pages.

Experimental: super admins only, by session or by a connected app's key.
"""
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models import (
    ChildCourseGrade,
    ChildGradeEntry,
    District,
    GuardianStudentLink,
    School,
    SchoolContentItem,
    SmoreNewsletter,
    Student,
    StudentSpecial,
    User,
)
from routers import bucket3
from routers.calendar import _applies_to_grad_years
from schemas import Bucket3SyncStatusOut
from services import i18n_strings, kids_schedule, rotation_day
from services.arbiter import ATHLETICS_SOURCES
from services.class_years import CLASS_PAGE_SOURCES
from services.hs_rotation import blocks_from_description
from services.school_today import (
    LOCAL_TZ,
    _applies,
    _hours,
    _is_rotation_item,
    _is_status_item,
    _item_date_range,
    classify_day,
    local_date,
    other_grades_only,
    starts_or_runs_from,
)

router = APIRouter(tags=["family"])

FEED_VERSION = 1
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_AHEAD_DAYS = 60
MAX_SPAN_DAYS = 120
# How many school days of each child's own schedule, from today.
SCHEDULE_DAYS = 15
# Not news for a family: staff introductions, lunch menus, merchandise ads.
_LEFT_OUT_CATEGORIES = ("person", "lunch_menu", "merch_ad")
_DAY_TITLES = {"open": "School day", "closed": "No school", "early_dismissal": "Early dismissal", "delayed": "Delayed opening"}
_KIND_ORDER = {"day": 0, "schedule": 1, "event": 2, "news": 3, "assignment": 4, "course_grade": 5, "grade": 6}


class FeedSpecialOut(BaseModel):
    rotation_day: int
    subject: str
    teacher: str | None


class FeedChildOut(BaseModel):
    id: str
    first_name: str
    school_id: str | None
    grad_year: int | None
    specials: list[FeedSpecialOut]
    # When Backpack Capture last brought Classroom / Genesis data, and whether
    # a child's Google sign-in ran out (Gradez's header).
    classroom_seen_at: datetime | None
    genesis_seen_at: datetime | None
    needs_login: bool


class FeedSchoolOut(BaseModel):
    id: str
    slug: str
    name: str
    short_name: str | None
    school_type: str | None
    district_name: str | None
    start_time: str | None
    end_time: str | None
    early_dismissal_time: str | None
    delayed_opening_time: str | None


class FeedItemOut(BaseModel):
    uid: str
    kind: Literal["day", "schedule", "event", "news", "assignment", "course_grade", "grade"]
    school_id: str | None = None
    child_id: str | None = None
    # The local day it's on or due (YYYY-MM-DD), and its last day when it runs longer.
    date: str | None = None
    end_date: str | None = None
    # A timed event's start and end; all-day items have neither.
    start_at: datetime | None = None
    end_at: datetime | None = None
    all_day: bool = True
    title: str
    detail: str | None = None
    status: str | None = None
    category: str | None = None
    source: str | None = None
    link_url: str | None = None
    # The fields only this kind has (docs/FAMILY_FEED.md).
    data: dict = Field(default_factory=dict)
    # Changes whenever anything above does.
    hash: str = ""


class FamilyFeedOut(BaseModel):
    version: int
    generated_at: datetime
    start: str
    end: str
    children: list[FeedChildOut]
    schools: list[FeedSchoolOut]
    items: list[FeedItemOut]


def _item(**fields) -> FeedItemOut:
    item = FeedItemOut(**fields)
    body = json.dumps(item.model_dump(mode="json", exclude={"hash"}), sort_keys=True)
    item.hash = hashlib.sha256(body.encode()).hexdigest()[:16]
    return item


def _content_item(item: SchoolContentItem, kind: str, school_ids: list[str], newsletter_urls: dict[str, str]) -> FeedItemOut:
    days = _item_date_range(item) if item.start_date else []
    return _item(
        uid=f"item:{item.id}",
        kind=kind,
        # A district item reaches every child's school in the district once.
        school_id=school_ids[0] if len(school_ids) == 1 else None,
        date=days[0].isoformat() if days else None,
        end_date=days[-1].isoformat() if len(days) > 1 else None,
        start_at=item.start_date if item.start_date and not item.is_all_day else None,
        end_at=item.end_date if item.start_date and not item.is_all_day else None,
        all_day=item.is_all_day,
        title=item.title,
        detail=item.description,
        category=item.category,
        source=item.source,
        link_url=item.link_url,
        data={
            "school_ids": school_ids,
            "scope": item.scope,
            "applies_to_grad_years": item.applies_to_grad_years,
            "newsletter_url": newsletter_urls.get(item.newsletter_id) if item.newsletter_id else None,
            "extracted_at": item.extracted_at.isoformat(),
        },
    )


async def _school_days_and_items(
    db: AsyncSession, school: School, start: date, end: date, grad_years: set[int]
) -> tuple[list[FeedItemOut], list[tuple[str, SchoolContentItem]]]:
    """The school's day for every weekday in the window, plus the content
    items (kind, row) that apply to this family there."""
    start_at = datetime.combine(start, datetime.min.time(), LOCAL_TZ)
    end_at = datetime.combine(end, datetime.max.time(), LOCAL_TZ)
    scope = SchoolContentItem.school_id == school.id
    if school.district_id:
        scope = or_(scope, SchoolContentItem.district_id == school.district_id)
    rows = (
        await db.execute(
            select(SchoolContentItem)
            .where(
                scope,
                SchoolContentItem.is_current.is_(True),
                SchoolContentItem.source.not_in(ATHLETICS_SOURCES),
                SchoolContentItem.start_date.is_not(None),
                starts_or_runs_from(start_at),
                SchoolContentItem.start_date <= end_at,
            )
            .order_by(SchoolContentItem.start_date)
        )
    ).scalars().all()
    # Of the items that began before the window, only closures and the like,
    # which still decide the days they run into (as on Today).
    dated = [i for i in rows if _applies(i, school) and (local_date(i.start_date) >= start or _is_status_item(i))]
    by_day: dict[date, list[SchoolContentItem]] = {}
    for i in dated:
        for d in _item_date_range(i):
            by_day.setdefault(d, []).append(i)

    days = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            on_day = by_day.get(d, [])
            day_status, label = classify_day([i.title for i in on_day if not other_grades_only(i.title, school.school_type)])
            rot = next((i for i in on_day if _is_rotation_item(i)), None)
            title = f"No school: {label}" if day_status == "closed" and label else _DAY_TITLES[day_status]
            days.append(
                _item(
                    uid=f"day:{school.id}:{d.isoformat()}",
                    kind="day",
                    school_id=school.id,
                    date=d.isoformat(),
                    title=title,
                    detail=_hours(school, day_status),
                    status=day_status,
                    data={
                        "label": label,
                        "rotation_day": i18n_strings.rotation_label(rotation_day.parse(rot.title).key, "en") if rot else None,
                        "blocks": blocks_from_description(rot.description) if rot else None,
                    },
                )
            )
        d += timedelta(days=1)

    def wanted(i: SchoolContentItem) -> bool:
        return (
            i.category not in _LEFT_OUT_CATEGORIES
            and i.source not in CLASS_PAGE_SOURCES
            and _applies(i, school)
            and _applies_to_grad_years(i, grad_years)
        )

    content = [("event", i) for i in dated if local_date(i.start_date) >= start and not _is_rotation_item(i) and wanted(i)]
    # Undated newsletter items (reminders, programs, volunteer asks) count from
    # when they were read: the window's start, a week back by default.
    news = (
        await db.execute(
            select(SchoolContentItem)
            .where(
                scope,
                SchoolContentItem.is_current.is_(True),
                SchoolContentItem.start_date.is_(None),
                SchoolContentItem.source == "newsletter",
                SchoolContentItem.extracted_at >= start_at,
            )
            .order_by(SchoolContentItem.extracted_at)
        )
    ).scalars().all()
    content += [("news", i) for i in news if wanted(i)]
    return days, content


async def _child_items(
    db: AsyncSession, student: Student, school: School | None, start: date, end: date, today: date, sync: Bucket3SyncStatusOut
) -> list[FeedItemOut]:
    """The child's own schedule from today, their Gradez to-do, and their
    grades: this marking period's per class, and graded work first seen in
    the window."""
    items = []
    if school and end >= today:
        for day in await kids_schedule.upcoming_days(db, school, student.id, today=max(today, start), count=SCHEDULE_DAYS):
            if day["date"] > end.isoformat():
                break
            courses = [b["course_name"] for b in day["blocks"] if b.get("course_name")]
            items.append(
                _item(
                    uid=f"schedule:{student.id}:{day['date']}",
                    kind="schedule",
                    school_id=school.id,
                    child_id=student.id,
                    date=day["date"],
                    title=day["rotation_day"] or "School day",
                    detail=", ".join(courses) or None,
                    status=day["status"],
                    data={k: day[k] for k in ("rotation_day", "timed", "long_blocks", "blocks")},
                )
            )

    if sync.classroom_seen_at:
        todo, _mp, _today = await bucket3._todo_items(db, student)
        for t in todo:
            items.append(
                _item(
                    uid=f"assignment:{t['id']}",
                    kind="assignment",
                    school_id=student.school_id,
                    child_id=student.id,
                    date=t["due_date"],
                    title=t["title"],
                    status=t["category"],
                    category=t["item_type"],
                    source="classroom",
                    link_url=t["link"],
                    data={
                        "course_name": t["course_name"],
                        "due_raw": t["due_raw"],
                        "done": t["done"],
                        "done_source": t["done_source"],
                        "classroom_status": t["classroom_status"],
                        "points_possible": t["points_possible"],
                        "grade": t["grade"],
                        "teacher_name": t["teacher_name"],
                    },
                )
            )

    if sync.genesis_seen_at:
        current = bucket3._current_marking_period(await bucket3._get_marking_periods(db, student.id), today.isoformat())
        grades = select(ChildCourseGrade).where(ChildCourseGrade.student_id == student.id)
        if current:
            grades = grades.where(ChildCourseGrade.marking_period == current.label)
        for g in (await db.execute(grades.order_by(ChildCourseGrade.course_name))).scalars():
            items.append(
                _item(
                    uid=f"course_grade:{student.id}:{g.course_code}-{g.course_section}:{g.marking_period}",
                    kind="course_grade",
                    school_id=student.school_id,
                    child_id=student.id,
                    title=g.course_name or f"{g.course_code}-{g.course_section}",
                    source="genesis",
                    data={
                        "course_code": g.course_code,
                        "course_section": g.course_section,
                        "marking_period": g.marking_period,
                        "grade_percent": g.grade_percent,
                        "last_grade_posted": g.last_grade_posted,
                    },
                )
            )
        # Grades schoolz first saw inside the window: the ones that are news.
        # List Assignments shows work before it's graded; that's news once a
        # score or a mark (Missing, Exempt) is on it.
        entries = select(ChildGradeEntry).where(
            ChildGradeEntry.student_id == student.id,
            ChildGradeEntry.graded_at >= datetime.combine(start, datetime.min.time(), LOCAL_TZ),
        )
        for e in (await db.execute(entries.order_by(ChildGradeEntry.graded_at))).scalars():
            items.append(
                _item(
                    uid=f"grade:{student.id}:{e.external_uid}",
                    kind="grade",
                    school_id=student.school_id,
                    child_id=student.id,
                    title=e.title,
                    status=e.status,
                    category=e.category,
                    source="genesis",
                    data={
                        "course_name": e.course_name,
                        "course_code": e.course_code,
                        "course_section": e.course_section,
                        "marking_period": e.marking_period,
                        "weekday_date": e.weekday_date,
                        "score_earned": e.score_earned,
                        "score_possible": e.score_possible,
                        "percent": e.percent,
                        "first_seen_at": e.first_seen_at.isoformat(),
                        "graded_at": e.graded_at.isoformat(),
                    },
                )
            )
    return items


@router.get("/family/feed", response_model=FamilyFeedOut)
async def family_feed(
    start: date | None = None,
    end: date | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The caller's own children and everything about them from `start` to
    `end` (local dates, inclusive; a week back to 60 days ahead by default)."""
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "The family feed is experimental: super admins only for now")
    today = datetime.now(LOCAL_TZ).date()
    start = start or today - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    end = end or today + timedelta(days=DEFAULT_AHEAD_DAYS)
    if end < start or (end - start).days > MAX_SPAN_DAYS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"end must be on or after start, and at most {MAX_SPAN_DAYS} days later")

    kids = (
        await db.execute(
            select(Student)
            .join(GuardianStudentLink, GuardianStudentLink.student_id == Student.id)
            .where(GuardianStudentLink.guardian_user_id == user.id)
            .order_by(GuardianStudentLink.created_at)
        )
    ).scalars().all()
    school_ids = list(dict.fromkeys(k.school_id for k in kids if k.school_id))
    schools = {s.id: s for s in (await db.execute(select(School).where(School.id.in_(school_ids)))).scalars()} if school_ids else {}
    district_ids = {s.district_id for s in schools.values() if s.district_id}
    districts = {d.id: d.name for d in (await db.execute(select(District).where(District.id.in_(district_ids)))).scalars()} if district_ids else {}

    children, items = [], []
    for kid in kids:
        sync = await bucket3.sync_status(db, user.id, kid)
        specials = (
            await db.execute(select(StudentSpecial).where(StudentSpecial.student_id == kid.id).order_by(StudentSpecial.rotation_day))
        ).scalars().all()
        children.append(
            FeedChildOut(
                id=kid.id,
                first_name=kid.first_name,
                school_id=kid.school_id,
                grad_year=kid.grad_year,
                specials=[FeedSpecialOut(rotation_day=s.rotation_day, subject=s.subject, teacher=s.teacher) for s in specials],
                classroom_seen_at=sync.classroom_seen_at,
                genesis_seen_at=sync.genesis_seen_at,
                needs_login=sync.needs_login,
            )
        )
        items += await _child_items(db, kid, schools.get(kid.school_id), start, end, today, sync)

    content: dict[str, tuple[str, SchoolContentItem, list[str]]] = {}
    for school in schools.values():
        grad_years = {k.grad_year for k in kids if k.school_id == school.id and k.grad_year}
        days, found = await _school_days_and_items(db, school, start, end, grad_years)
        items += days
        for kind, row in found:
            content.setdefault(row.id, (kind, row, []))[2].append(school.id)
    newsletter_ids = {row.newsletter_id for _, row, _ in content.values() if row.newsletter_id}
    newsletter_urls = (
        dict((await db.execute(select(SmoreNewsletter.id, SmoreNewsletter.url).where(SmoreNewsletter.id.in_(newsletter_ids)))).all())
        if newsletter_ids
        else {}
    )
    items += [_content_item(row, kind, ids, newsletter_urls) for kind, row, ids in content.values()]
    items.sort(key=lambda i: (_KIND_ORDER[i.kind], i.date or "", i.uid))

    return FamilyFeedOut(
        version=FEED_VERSION,
        generated_at=datetime.now(UTC),
        start=start.isoformat(),
        end=end.isoformat(),
        children=children,
        schools=[
            FeedSchoolOut(
                id=s.id,
                slug=s.slug,
                name=s.name,
                short_name=s.short_name,
                school_type=s.school_type,
                district_name=districts.get(s.district_id),
                start_time=s.start_time,
                end_time=s.end_time,
                early_dismissal_time=s.early_dismissal_time,
                delayed_opening_time=s.delayed_opening_time,
            )
            for s in schools.values()
        ],
        items=items,
    )
