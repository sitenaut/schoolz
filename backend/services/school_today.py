"""Assembles one "Today" card for a school - the parent-facing home feed.

Everything here is derived from data the scans already produce; nothing
is fetched live. Day status comes from the district ICS feed items
(`SCHOOLS CLOSED - ...`, `EARLY DISMISSAL`, `DISTRICT CLOSED`) plus any
newsletter-extracted closure, the rotation label from the elementary
"Day N" feed, lunch from whichever LunchMenu applies, and contacts from
StaffMember.role (services/staff_roles.py).
"""

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import DistrictTransportation, LunchMenu, LunchMenuItem, SaccProgram, School, SchoolContentItem, StaffMember
from schemas import CurrentPeriodOut, SchoolContentItemOut, SchoolOut, SchoolTodayOut, TodayContactOut, TodayDayOut, TodayLunchOut, TodaySaccOut, TodayTransportationOut
from services.bell_schedule import current_period as _compute_current_period
from services.staff_roles import CONTACT_ROLES
from services.transportation import late_bus_for_school

LOCAL_TZ = ZoneInfo("America/New_York")

# Deliberately its own (narrower) patterns, not services/school_status.py's
# shared ones - that module's CLOSED_RE also matches bare "in-service"/
# "conference", which would wrongly outrank early_dismissal's precedence
# here on a real title like "EARLY DISMISSAL - Staff In-Service"
# (test_school_today.py:test_classify_day_precedence_and_labels pins this).
_CLOSED_RE = re.compile(r"\b(schools?|district)\s+closed\b|\bno school\b|\bclosed\b", re.I)
_EARLY_RE = re.compile(r"\bearly\s+dismissal\b|\bhalf[\s-]day\b", re.I)
_DELAY_RE = re.compile(r"\bdelayed\s+opening\b|\b\d\s*-?\s*hour\s+delay\b", re.I)
_ROTATION_RE = re.compile(r"^\s*Day\s+(\d)\s*$", re.I)
_UPCOMING_CATEGORIES = ("event", "deadline", "initiative", "reminder", "marking_period")
_UPCOMING_WINDOW_DAYS = 60
_ALERT_WINDOW_DAYS = 7

_WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def local_date(dt: datetime) -> date:
    if dt.tzinfo is None:
        return dt.date()
    return dt.astimezone(LOCAL_TZ).date()


def classify_day(titles: list[str]) -> tuple[str, str | None]:
    """Returns (status, label) from the titles of every item landing on a
    day. Closed beats early dismissal beats delay beats open. The label is
    the closure's own reason ("Labor Day") with the boilerplate prefix
    stripped, since the status already says "closed"."""
    for t in titles:
        if _CLOSED_RE.search(t):
            label = re.sub(r"^\s*(schools?|district)\s+closed\s*[-:–]?\s*", "", t, flags=re.I).strip() or None
            return "closed", label
    for t in titles:
        if _EARLY_RE.search(t):
            return "early_dismissal", "Early dismissal"
    for t in titles:
        if _DELAY_RE.search(t):
            return "delayed", t
    return "open", None


def _item_date_range(item: SchoolContentItem) -> list[date]:
    """Every calendar day an item covers, not just its start_date - a
    multi-day item (real case: "SCHOOLS CLOSED - NJEA Convention" spanning
    Nov 5-6) was otherwise only ever classified as closed on its first day,
    with the second day silently showing "Open" (both here and on the
    frontend calendar grid, which had the identical bug independently).
    All-day multi-day events store end_date as the ICS convention's
    exclusive day-after-the-last-day (confirmed real: Nov 5 start, Nov 7
    end, covering Nov 5-6) - a timed item's end_date, if it spans a later
    calendar day at all, is treated as inclusive of that day instead."""
    start_d = local_date(item.start_date)
    if not item.end_date:
        return [start_d]
    end_d = local_date(item.end_date)
    if item.is_all_day:
        end_d -= timedelta(days=1)
    if end_d <= start_d:
        return [start_d]
    return [start_d + timedelta(days=n) for n in range((end_d - start_d).days + 1)]


def _is_status_item(item: SchoolContentItem) -> bool:
    return bool(_CLOSED_RE.search(item.title) or _EARLY_RE.search(item.title) or _DELAY_RE.search(item.title))


def _is_rotation_item(item: SchoolContentItem) -> bool:
    return bool(_ROTATION_RE.match(item.title))


def _applies(item: SchoolContentItem, school: School) -> bool:
    return not item.applies_to_school_types or not school.school_type or school.school_type in item.applies_to_school_types


def week_window(today: date) -> list[date]:
    """Mon-Fri of the current week; on a weekend, the coming week."""
    monday = today - timedelta(days=today.weekday())
    if today.weekday() >= 5:
        monday += timedelta(days=7)
    return [monday + timedelta(days=i) for i in range(5)]


async def resolve_lunch_menu(db: AsyncSession, school: School, meal_type: str = "lunch") -> LunchMenu | None:
    """School's own newsletter-embedded menu first, then the shared
    district+school_type PDF menu (see routers/schools.py for why)."""
    menu = (
        await db.execute(
            select(LunchMenu).where(LunchMenu.school_id == school.id, LunchMenu.meal_type == meal_type).order_by(LunchMenu.parsed_at.desc())
        )
    ).scalars().first()
    if not menu and school.district_id and school.school_type:
        menu = (
            await db.execute(
                select(LunchMenu)
                .where(LunchMenu.district_id == school.district_id, LunchMenu.school_type == school.school_type, LunchMenu.meal_type == meal_type)
                .order_by(LunchMenu.parsed_at.desc())
            )
        ).scalars().first()
    return menu


def _hours(school: School, status: str) -> str | None:
    if status == "closed":
        return None
    if status == "delayed" and school.delayed_opening_time:
        return f"{school.delayed_opening_time}–{school.end_time}" if school.end_time else f"Opens {school.delayed_opening_time}"
    if status == "early_dismissal" and school.early_dismissal_time:
        return f"{school.start_time}–{school.early_dismissal_time}" if school.start_time else f"Out {school.early_dismissal_time}"
    if school.start_time and school.end_time:
        return f"{school.start_time}–{school.end_time}"
    return None


async def build_today(db: AsyncSession, school: School, today: date | None = None) -> SchoolTodayOut:
    today = today or datetime.now(LOCAL_TZ).date()
    week = week_window(today)
    range_start = min(today, week[0])
    range_end = today + timedelta(days=_UPCOMING_WINDOW_DAYS)

    scope_filter = SchoolContentItem.school_id == school.id
    if school.district_id:
        scope_filter = or_(scope_filter, SchoolContentItem.district_id == school.district_id)
    rows = (
        await db.execute(
            select(SchoolContentItem)
            .where(
                scope_filter,
                SchoolContentItem.is_current.is_(True),
                SchoolContentItem.start_date.is_not(None),
                SchoolContentItem.start_date >= datetime.combine(range_start, datetime.min.time(), LOCAL_TZ),
                SchoolContentItem.start_date <= datetime.combine(range_end, datetime.max.time(), LOCAL_TZ),
            )
            .order_by(SchoolContentItem.start_date)
        )
    ).scalars().all()
    items = [i for i in rows if _applies(i, school)]

    by_day: dict[date, list[SchoolContentItem]] = {}
    for i in items:
        for d in _item_date_range(i):
            by_day.setdefault(d, []).append(i)

    def day_status(d: date) -> tuple[str, str | None]:
        if d.weekday() >= 5:
            return "weekend", None
        return classify_day([i.title for i in by_day.get(d, [])])

    def rotation(d: date) -> str | None:
        for i in by_day.get(d, []):
            if _is_rotation_item(i):
                return i.title.strip()
        return None

    # Lunch: today's + the next school day's.
    menu = await resolve_lunch_menu(db, school)
    lunch_by_day: dict[date, str] = {}
    if menu:
        menu_items = (await db.execute(select(LunchMenuItem).where(LunchMenuItem.lunch_menu_id == menu.id))).scalars().all()
        lunch_by_day = {local_date(m.menu_date): m.description for m in menu_items}

    status, status_label = day_status(today)
    next_day = today + timedelta(days=1)
    while next_day.weekday() >= 5 or day_status(next_day)[0] == "closed":
        next_day += timedelta(days=1)
        if next_day > today + timedelta(days=14):
            break
    next_label = "Tomorrow" if next_day == today + timedelta(days=1) else _WEEKDAYS[next_day.weekday()]
    lunch = TodayLunchOut(
        today=lunch_by_day.get(today) if status != "closed" else None,
        next_label=next_label if lunch_by_day.get(next_day) else None,
        next=lunch_by_day.get(next_day),
        source_pdf_url=menu.source_pdf_url if menu and not menu.source_pdf_url.startswith("newsletter:") else None,
    )

    sacc_row = (await db.execute(select(SaccProgram).where(SaccProgram.school_id == school.id))).scalar_one_or_none()
    sacc = (
        TodaySaccOut(
            am_hours=sacc_row.am_hours,
            pm_hours=sacc_row.pm_hours,
            site_phone=sacc_row.site_phone,
            absence_form_url=sacc_row.absence_form_url,
            absence_phone=sacc_row.absence_phone,
        )
        if sacc_row
        else None
    )

    # One contact per role, in display order.
    staff = (
        await db.execute(select(StaffMember).where(StaffMember.school_id == school.id, StaffMember.role.is_not(None)).order_by(StaffMember.full_name))
    ).scalars().all()
    contacts: list[TodayContactOut] = []
    for role, label in CONTACT_ROLES:
        match = next((s for s in staff if s.role == role), None)
        if match:
            contacts.append(TodayContactOut(role=role, label=label, name=match.full_name, email=match.email, phone=match.phone))

    def out(i: SchoolContentItem) -> SchoolContentItemOut:
        return SchoolContentItemOut.model_validate(i, from_attributes=True)

    upcoming = [
        out(i)
        for i in items
        if local_date(i.start_date) >= today and i.category in _UPCOMING_CATEGORIES and not _is_rotation_item(i)
    ][:5]

    seen: set[tuple[date, str]] = set()
    alerts: list[SchoolContentItemOut] = []
    for i in items:
        if not _is_status_item(i):
            continue
        # Any day the item covers falling in the alert window is enough -
        # a multi-day closure that started before today but is still
        # ongoing (or one starting later in the window) should still surface.
        window_day = next(
            (d for d in _item_date_range(i) if today <= d <= today + timedelta(days=_ALERT_WINDOW_DAYS)), None
        )
        if window_day is not None:
            key = (window_day, classify_day([i.title])[0])
            if key not in seen:
                seen.add(key)
                alerts.append(out(i))

    week_out: list[TodayDayOut] = []
    for d in week:
        st, lbl = day_status(d)
        week_out.append(
            TodayDayOut(
                date=d.isoformat(),
                weekday=_WEEKDAYS[d.weekday()],
                status=st,
                status_label=lbl,
                rotation_day=rotation(d),
                lunch=lunch_by_day.get(d) if st != "closed" else None,
                items=[out(i) for i in by_day.get(d, []) if not _is_rotation_item(i) and not _is_status_item(i)][:3],
            )
        )

    transportation = None
    if school.district_id:
        t_row = (await db.execute(select(DistrictTransportation).where(DistrictTransportation.district_id == school.district_id))).scalar_one_or_none()
        if t_row:
            late = late_bus_for_school(t_row.late_bus_contractors, school.name, school.short_name)
            transportation = TodayTransportationOut(
                office_phone=t_row.office_phone,
                late_bus_phone=late["phone"] if late else None,
                late_bus_contractor=late["contractor"] if late else None,
            )

    # Only meaningful for the real, current moment - a caller (tests,
    # mainly) can pass a different `today` to inspect another date, and
    # "what period is it right now" would be nonsensical against that.
    period = None
    if today == datetime.now(LOCAL_TZ).date():
        raw = _compute_current_period(school.bell_periods, status, datetime.now(LOCAL_TZ))
        period = CurrentPeriodOut(**raw) if raw else None

    return SchoolTodayOut(
        school=SchoolOut.model_validate(school, from_attributes=True),
        date=today.isoformat(),
        is_school_day=status not in ("weekend", "closed"),
        status=status,
        status_label=status_label,
        hours=_hours(school, status),
        rotation_day=rotation(today),
        current_period=period,
        transportation=transportation,
        lunch=lunch,
        sacc=sacc,
        contacts=contacts,
        upcoming=upcoming,
        alerts=alerts,
        week=week_out,
    )
