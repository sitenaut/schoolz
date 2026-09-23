"""A student's class schedule for any school day, computed rather than captured.

Genesis's daily view only exists for the days someone happened to capture it.
Every other day can be derived from four things schoolz already has: the
student's block -> course list (Genesis list view), the district rotation
calendar (which letters meet on a date), the school's bell table (the clock
times for those letters), and the student's marking periods (which decide
whether an S1 or S2 course fills a block). See docs/HS_SCHEDULE_FINDINGS.md.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ChildMarkingPeriod, ChildScheduleBlock, School, SchoolContentItem, StudentSpecial
from services.bell_schedule import _parse_hm, is_long_block_day, lettered_day
from services.hs_rotation import blocks_from_description
from services.school_today import LOCAL_TZ, _WEEKDAYS, _applies, _is_rotation_item, _item_date_range, _ROTATION_RE, classify_day

_SEMESTER_MPS = {"S1": ("MP1", "MP2"), "S2": ("MP3", "MP4")}


def term_for(d: date, marking_periods: list) -> str | None:
    """"S1"/"S2" for a date, from the student's own MP ranges; None when unknown."""
    by_label = {mp.label: mp for mp in marking_periods}
    iso = d.isoformat()
    for term, (first, last) in _SEMESTER_MPS.items():
        if first in by_label and last in by_label and by_label[first].start_date <= iso <= by_label[last].end_date:
            return term
    return None


def _clock(hhmm: str) -> str:
    hour, minute = (int(x) for x in hhmm.split(":"))
    return f"{(hour - 1) % 12 + 1}:{minute:02d}"


def courses_for(letter: str, day_number: int | None, term: str | None, list_blocks: list) -> list:
    """The list-view rows that fill `letter` on this day. A row's term must
    be FY or match the day's semester (both candidates when the semester is
    unknown, so nothing is silently guessed). `days` only narrows the rows
    that split a block across rotation days (Homeroom 135 / 246) - for course
    blocks it's always "123456" and says nothing about the drop pattern."""
    out = []
    for b in list_blocks:
        if b.period != letter:
            continue
        if term and b.term in ("S1", "S2") and b.term != term:
            continue
        if day_number and b.days and str(day_number) not in b.days:
            continue
        out.append(b)
    return out


def special_day(d: date, status: str, rotation_day: str | None, specials: dict[int, StudentSpecial]) -> dict:
    """An elementary day: the one special that meets on this rotation day,
    or an empty day when the rotation (or the special for it) is unknown."""
    m = _ROTATION_RE.match(rotation_day or "")
    special = specials.get(int(m.group(1))) if m else None
    return {
        "date": d.isoformat(),
        "weekday": _WEEKDAYS[d.weekday()],
        "status": status,
        "rotation_day": rotation_day,
        "long_blocks": False,
        "timed": False,
        "blocks": [{"name": "Special", "start_label": None, "end_label": None, "course_name": special.subject, "teacher": special.teacher, "room": None}]
        if special
        else [],
    }


def build_day(d: date, status: str, rotation_day: str | None, letters: list[str] | None, bell_periods: dict | None, list_blocks: list, term: str | None) -> dict:
    m = _ROTATION_RE.match(rotation_day or "")
    day_number = int(m.group(1)) if m else None
    fit = lettered_day(bell_periods, status, letters)
    blocks = []
    if fit:
        for slot in fit[1]:
            rows = courses_for(slot["name"], day_number, term, list_blocks)
            blocks.append(
                {
                    "name": slot["name"],
                    "start_label": _clock(slot["start"]),
                    "end_label": _clock(slot["end"]),
                    "course_name": " / ".join(r.course_name for r in rows) or None,
                    "teacher": rows[0].teacher if len(rows) == 1 else None,
                    "room": rows[0].room if len(rows) == 1 else None,
                }
            )
    elif letters:
        # Known letters, no timetable that fits (a long-block early dismissal):
        # still say which classes meet, just without clock times.
        for letter in letters:
            rows = courses_for(letter, day_number, term, list_blocks)
            blocks.append({"name": letter, "start_label": None, "end_label": None, "course_name": " / ".join(r.course_name for r in rows) or None, "teacher": None, "room": None})
    return {
        "date": d.isoformat(),
        "weekday": _WEEKDAYS[d.weekday()],
        "status": status,
        "rotation_day": rotation_day,
        "long_blocks": is_long_block_day(bell_periods, letters),
        "timed": bool(fit),
        "blocks": blocks,
    }


async def current_class_for_student(db: AsyncSession, school: School, student_id: str, now: datetime | None = None) -> dict | None:
    """What class this student is in RIGHT NOW - the same block-letter ->
    course pipeline as upcoming_days(), resolved for one instant instead of
    a multi-day list. None covers every reason there's nothing to show: a
    weekend, a non-school day, no rotation letters found for today, no
    bell table entry `now` falls inside (before/after the day, a gap the
    table doesn't name), or no list-view course on file for that block.

    Deliberately its own small function rather than reusing build_day()'s
    output: build_day() formats clock times through bell_schedule's 12h
    `_clock()` helper, which drops AM/PM - fine for a display label next to
    a school day that's unambiguous in context, but wrong to compare
    against `now` (a 7:30 slot could be either AM or PM once formatted).
    This compares raw 24h "HH:MM" strings instead, the same way
    bell_schedule.current_period() does for the school-wide (non-student)
    version of this same question."""
    now = now or datetime.now(LOCAL_TZ)
    today = now.date()
    if today.weekday() >= 5:
        return None

    list_blocks = (
        await db.execute(select(ChildScheduleBlock).where(ChildScheduleBlock.student_id == student_id, ChildScheduleBlock.source == "list"))
    ).scalars().all()
    if not list_blocks:
        return None

    scope = SchoolContentItem.school_id == school.id
    if school.district_id:
        scope = or_(scope, SchoolContentItem.district_id == school.district_id)
    items = [
        i
        for i in (
            await db.execute(
                select(SchoolContentItem).where(
                    scope,
                    SchoolContentItem.is_current.is_(True),
                    SchoolContentItem.start_date.is_not(None),
                    SchoolContentItem.start_date >= datetime.combine(today, datetime.min.time(), LOCAL_TZ),
                    SchoolContentItem.start_date <= datetime.combine(today, datetime.max.time(), LOCAL_TZ),
                )
            )
        ).scalars()
        if _applies(i, school)
    ]
    status, _ = classify_day([i.title for i in items])
    if status not in ("open", "early_dismissal", "delayed"):
        return None
    rot = next((i for i in items if _is_rotation_item(i)), None)
    if not rot:
        return None
    letters = blocks_from_description(rot.description)
    fit = lettered_day(school.bell_periods, status, letters)
    if not fit:
        return None

    current_time = now.time()
    slot = next((s for s in fit[1] if _parse_hm(s["start"]) <= current_time < _parse_hm(s["end"])), None)
    if not slot:
        return None

    m = _ROTATION_RE.match(rot.title.strip())
    day_number = int(m.group(1)) if m else None
    mps = (await db.execute(select(ChildMarkingPeriod).where(ChildMarkingPeriod.student_id == student_id))).scalars().all()
    rows = courses_for(slot["name"], day_number, term_for(today, mps), list_blocks)
    if not rows:
        return None

    start, end = _parse_hm(slot["start"]), _parse_hm(slot["end"])
    end_dt = datetime.combine(today, end, LOCAL_TZ)
    return {
        "period_name": slot["name"],
        "course_name": " / ".join(r.course_name for r in rows),
        "teacher": rows[0].teacher if len(rows) == 1 else None,
        "room": rows[0].room if len(rows) == 1 else None,
        "start_label": start.strftime("%-I:%M %p"),
        "end_label": end.strftime("%-I:%M %p"),
        "minutes_left": int((end_dt - now).total_seconds() // 60),
    }


async def upcoming_days(db: AsyncSession, school: School, student_id: str, today: date | None = None, count: int = 5) -> list[dict]:
    """Today (if it's a school day) and the following school days, up to
    `count`, each with the student's own classes in clock order. Empty when
    the school has no rotation calendar or the student has no list view."""
    today = today or datetime.now(LOCAL_TZ).date()
    list_blocks = (
        await db.execute(select(ChildScheduleBlock).where(ChildScheduleBlock.student_id == student_id, ChildScheduleBlock.source == "list"))
    ).scalars().all()
    specials = {
        s.rotation_day: s for s in (await db.execute(select(StudentSpecial).where(StudentSpecial.student_id == student_id))).scalars().all()
    }
    if not list_blocks and not specials:
        return []
    mps = (await db.execute(select(ChildMarkingPeriod).where(ChildMarkingPeriod.student_id == student_id))).scalars().all()

    horizon = today + timedelta(days=21)
    scope = SchoolContentItem.school_id == school.id
    if school.district_id:
        scope = or_(scope, SchoolContentItem.district_id == school.district_id)
    items = [
        i
        for i in (
            await db.execute(
                select(SchoolContentItem).where(
                    scope,
                    SchoolContentItem.is_current.is_(True),
                    SchoolContentItem.start_date.is_not(None),
                    SchoolContentItem.start_date >= datetime.combine(today - timedelta(days=7), datetime.min.time(), LOCAL_TZ),
                    SchoolContentItem.start_date <= datetime.combine(horizon, datetime.max.time(), LOCAL_TZ),
                )
            )
        ).scalars()
        if _applies(i, school)
    ]
    by_day: dict[date, list[SchoolContentItem]] = {}
    for i in items:
        for d in _item_date_range(i):
            by_day.setdefault(d, []).append(i)
    if not any(_is_rotation_item(i) for i in items):
        return []

    days = []
    d = today
    while d <= horizon and len(days) < count:
        if d.weekday() < 5:
            status, _ = classify_day([i.title for i in by_day.get(d, [])])
            if status != "closed":
                rot = next((i for i in by_day.get(d, []) if _is_rotation_item(i)), None)
                rotation_day = rot.title.strip() if rot else None
                if list_blocks:
                    letters = blocks_from_description(rot.description) if rot else None
                    days.append(build_day(d, status, rotation_day, letters, school.bell_periods, list_blocks, term_for(d, mps)))
                else:
                    days.append(special_day(d, status, rotation_day, specials))
        d += timedelta(days=1)
    return days
