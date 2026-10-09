"""The data audit: for every school x data point, is what we show current?

Statuses: current / stale / failing / not collecting / not applicable (the
last is left out of the compliance score). Everything is derived from what
already exists - the School/District rows, their scan jobs and run history,
and the content tables those scans fill. Nothing here writes, except the
"not published" marks, which live in `AuditNotPublished`.

Two audiences read the same cell. Internal wording names error codes, job
kinds and what we should do next; district wording says what the district
can provide, in plain language, and never carries a code, a job name or an
internal step. `render_cell` builds each audience's dict from scratch, so a
district response can't leak a field by forgetting to delete it.

Freshness = two missed scheduled runs plus a grace period, by the cadence of
the job's own cron (see `cadence_for_cron`). Hand-entered data has no
confirmation timestamp, so it counts as current while it's on file - except
before/after care, whose row carries `updated_at`, which must be from this
school year.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    AuditNotPublished,
    District,
    DistrictTransportation,
    JobRun,
    LunchMenu,
    LunchMenuItem,
    SaccProgram,
    ScheduledJob,
    School,
    SchoolDocument,
    SmoreBlock,
    SmoreNewsletter,
    StaffMember,
)

TZ = ZoneInfo("America/New_York")

CURRENT, STALE, FAILING, NONE, NA = "current", "stale", "failing", "not_collecting", "not_applicable"
STATUSES = (CURRENT, STALE, FAILING, NONE, NA)
STATUS_LABELS = {CURRENT: "Current", STALE: "Stale", FAILING: "Failing", NONE: "Not collecting", NA: "Not applicable"}
AUDIENCES = ("internal", "district")

# A newsletter whose newest content is older than this is stale even when
# its scan is fine - most schools publish each issue at a new URL.
NEWSLETTER_MAX_AGE = timedelta(days=21)

# School "kinds" the audit groups by. Preschools are school_type "other"
# (preschool_locations.scan creates them that way).
KIND_BY_TYPE = {"elementary": "elementary", "middle": "middle", "high": "high", "alternative": "alternative", "other": "preschool"}
KIND_LABELS = {"elementary": "Elementary", "middle": "Middle", "high": "High", "alternative": "Alternative", "preschool": "Preschool", None: "Type not set"}
_KIND_NOUN = {"elementary": "an elementary school", "middle": "a middle school", "high": "a high school", "alternative": "an alternative school", "preschool": "a preschool", None: "a school with no type set"}

ALL = None
NOT_PRESCHOOL = frozenset({"elementary", "middle", "high", "alternative"})
MIDDLE_HIGH = frozenset({"middle", "high", "alternative"})
HIGH = frozenset({"high"})


@dataclass(frozen=True)
class DataPoint:
    key: str
    label: str
    group: str
    applies: frozenset[str] | None  # None = every school, including one with no type
    applies_label: str
    source_internal: str  # job kind(s) / how it gets in
    source_district: str  # where it comes from, in plain words
    runs: str  # nominal cadence, Catalog wording
    stale_after: str
    by_hand: bool  # no scheduled scan behind it
    ask: str  # district wording: what the district can provide
    none_why: str  # internal: why nothing is collected
    none_why_district: str
    none_next: str  # internal next step when nothing is collected
    internal_gap: bool = False  # a gap only we can close (no parser) - reads neutrally for districts


DATA_POINTS: tuple[DataPoint, ...] = (
    DataPoint("info", "Address and phone", "Identity", ALL, "All schools", "school_info.scan", "The school website", "Monthly", "65 days", False,
              "The school's address and main phone number on its website.",
              "No website is set for this school, so school_info.scan has nothing to read.",
              "We don't have a website for this school to read its address and phone from.",
              "Set the school's website URL; the scan is created with it."),
    DataPoint("logo", "Logo", "Identity", ALL, "All schools", "school_info.scan", "The school website", "Monthly", "65 days", False,
              "The school's logo in its website header.",
              "No website is set for this school, so school_info.scan has nothing to read.",
              "We don't have a website for this school to read its logo from.",
              "Set the school's website URL; the scan is created with it."),
    DataPoint("geo", "Map location", "Identity", ALL, "All schools", "school_info.scan (geocoded from the address)", "Worked out from the school's address", "Monthly", "65 days", False,
              "The school's street address on its website.",
              "No website is set for this school, so there's no address to geocode.",
              "We don't have the school's address to place it on a map.",
              "Set the school's website URL; the scan is created with it."),
    DataPoint("staff", "Staff directory", "People", ALL, "All schools", "staff_roster.scan", "The staff directory on the school website", "Twice a month", "35 days", False,
              "A public staff directory page or document for the school.",
              "No website or staff directory URL is set, so staff_roster.scan has nothing to read.",
              "We don't have a staff directory for this school.",
              "Set the school's website or staff directory URL."),
    DataPoint("absence", "Absence method", "People", ALL, "All schools", "Newsletter extraction, or entered by hand", "School newsletters and announcements", "No scan", "Not confirmed this school year", True,
              "How a parent should report an absence: phone, email or portal.",
              "No tracked newsletter states how to report an absence, so the method was never extracted.",
              "Nothing we track states how a parent should report an absence.",
              "Enter it by hand on the school, or track a newsletter that states it."),
    DataPoint("pkteam", "Preschool team", "People", frozenset({"preschool"}), "Preschools", "preschool_team.scan", "The district preschool office page", "Weekly", "16 days", False,
              "The district preschool office's staff page.",
              "No preschool team URL is set on the district.",
              "We don't have the district's preschool office contacts.",
              "Set the district's preschool team URL."),
    DataPoint("hours", "School hours", "Schedule", ALL, "All schools", "Entered by hand", "The school's bell schedule", "No scan", "Not confirmed this school year", True,
              "The school's regular start and end times.",
              "No start and end times have been entered for this school.",
              "We don't have this school's regular start and end times.",
              "Enter the times from the school's bell schedule."),
    DataPoint("alt", "Early and delayed times", "Schedule", ALL, "All schools", "Entered by hand", "The school's bell schedule", "No scan", "Not confirmed this school year", True,
              "Early-dismissal and delayed-opening times for the school.",
              "Early-dismissal and delayed-opening times are not on file for this school.",
              "Early-dismissal and delayed-opening times are not published anywhere we found.",
              "Request them from the district, or mark as not published."),
    DataPoint("periods", "Period table", "Schedule", MIDDLE_HIGH, "Middle and high", "Entered by hand", "The school's bell schedule", "No scan", "Not confirmed this school year", True,
              "A period-by-period bell schedule for the school.",
              "No period-by-period table is on file for this school.",
              "No period-by-period table is published for this school.",
              "Request it from the school, or mark as not published."),
    DataPoint("cal", "District calendar", "Schedule", ALL, "All schools", "district_calendar.scan or district_calendar_pdf.scan", "The district calendar", "Every 12 hours", "36 hours", False,
              "A link to the district calendar feed or the school-year calendar PDF.",
              "The district has no calendar feed or calendar PDF page set.",
              "We don't have a link to the district calendar.",
              "Add the district's .ics feeds or its calendar PDF page."),
    DataPoint("mp", "Marking periods", "Schedule", NOT_PRESCHOOL, "All but preschools", "marking_period.scan", "The district marking-period page", "Weekly", "16 days", False,
              "The page listing marking-period and report-card dates.",
              "The district has no marking-period URL set.",
              "We don't have the district's marking-period and report-card dates.",
              "Set the district's marking-period URL."),
    DataPoint("rot", "Day rotation", "Schedule", HIGH, "High schools", "hs_rotation.scan", "The district day-rotation schedule", "Weekly", "16 days", False,
              "The high-school day-rotation schedule.",
              "The district has no day-rotation URL set.",
              "We don't have the high-school day-rotation schedule.",
              "Set the district's day-rotation URL."),
    DataPoint("news", "Newsletter", "News and events", ALL, "All schools", "smore.scan", "The school newsletter", "Weekly, on Monday", "16 days, or newest issue over 21 days old", False,
              "A link to the school's newsletter, or confirmation that there isn't one.",
              "No newsletter URL is tracked for this school.",
              "No newsletter link is known for this school.",
              "Add the school's Smore URL, or connect a Gmail scanner."),
    DataPoint("pta", "PTA page", "News and events", ALL, "All schools", "givebacks.scan or ptboard.scan", "The PTA website", "Daily or weekly", "3 days or 16 days", False,
              "A link to the PTA's website, or confirmation that there isn't one.",
              "No Givebacks shortname or PTBoard page is set for this school.",
              "We don't have a link to this school's PTA page.",
              "Find the PTA's Givebacks or PTBoard site and add it."),
    DataPoint("backpack", "District flyers", "News and events", ALL, "All schools", "virtual_backpack.scan", "The district flyer board", "Daily", "3 days", False,
              "A link to the district's flyer board (virtual backpack), or confirmation that there isn't one.",
              "No virtual backpack page is tracked for this school or its district.",
              "We don't have a link to a district flyer board.",
              "Add the district's virtual backpack page as a newsletter source."),
    DataPoint("events", "School events calendar", "News and events", ALL, "All schools", "special_events.scan or school_events_doc.scan", "The school's events calendar", "Weekly or every 12 hours", "16 days or 36 hours", False,
              "A link to the school's own events calendar, or confirmation that there isn't one.",
              "No special-events page or events doc is set for this school.",
              "We don't have a school-wide events calendar for this school.",
              "Set the school's special-events page or events doc URL, or mark as not published."),
    DataPoint("bulletin", "Student bulletin", "News and events", MIDDLE_HIGH, "Middle and high", "student_bulletin.scan", "The student bulletin", "Every 12 hours", "36 hours", False,
              "A link to the student bulletin, or confirmation that there isn't one.",
              "No student bulletin doc is set for this school.",
              "We don't have a link to a student bulletin.",
              "Set the school's bulletin doc URL, or mark as not published."),
    DataPoint("ann", "Morning announcements", "News and events", HIGH, "High schools", "hs_announcements.scan", "The morning announcements", "Every 2 hours on school days", "1 school day", False,
              "A link to the daily announcements, or confirmation that there isn't one.",
              "No announcements doc is set for this school.",
              "We don't have a link to the daily announcements.",
              "Set the school's announcements doc URL, or mark as not published."),
    DataPoint("actcal", "Activities calendar", "News and events", HIGH, "High schools", "hs_class_calendar.scan", "The activities calendar", "Every 12 hours", "36 hours", False,
              "A link to the activities calendar, or confirmation that there isn't one.",
              "No activities calendar feed is set for this school.",
              "We don't have a link to an activities calendar.",
              "Set the school's activities calendar .ics URL, or mark as not published."),
    DataPoint("actsite", "Class pages", "News and events", HIGH, "High schools", "hs_activities_site.scan", "The class and activities site", "Daily", "3 days", False,
              "A link to the class or activities site, or confirmation that there isn't one.",
              "No activities site is set for this school.",
              "We don't have a link to a class or activities site.",
              "Set the school's activities site URL, or mark as not published."),
    DataPoint("ath", "Athletics calendar", "News and events", MIDDLE_HIGH, "Middle and high", "athletics_calendar.scan", "The athletics schedule", "Every 12 hours", "36 hours", False,
              "A link to the athletics schedule, or confirmation that there isn't one.",
              "No ArbiterLive athletics URL is set for this school.",
              "We don't have a link to an athletics schedule.",
              "Set the school's ArbiterLive athletics URL, or mark as not published."),
    DataPoint("menu", "Meal menus", "Services and documents", ALL, "All schools", "lunch_menu.scan or a vendor menu scan", "The food-services menus", "Daily", "3 days, or no menu for the current week", False,
              "The current breakfast and lunch menus posted on the food-services page.",
              "No menu PDF page or menu vendor is set for this school or its district.",
              "We don't have a link to this school's meal menus.",
              "Set the district's food-services page, or the school's menu vendor location."),
    DataPoint("hand", "Handbook", "Services and documents", ALL, "All schools", "documents.scan", "The school website or newsletter", "Twice a month", "35 days, or dated an earlier school year", False,
              "The current handbook posted on the school site.",
              "No handbook was found on the school site or in a newsletter.",
              "No handbook was found on the school site or in a newsletter.",
              "Add the document link by hand, or mark as not published."),
    DataPoint("belldoc", "Bell schedule document", "Services and documents", ALL, "All schools", "documents.scan", "The school website", "Twice a month", "35 days, or dated an earlier school year", False,
              "This year's bell schedule posted on the school site.",
              "No bell schedule document was found on the school site.",
              "No bell schedule document was found on the school site.",
              "Find the bell schedule on the school site, or mark as not published."),
    DataPoint("bus", "Transportation", "Services and documents", NOT_PRESCHOOL, "All but preschools", "transportation.scan", "The district transportation pages", "Weekly", "16 days", False,
              "A link to the district's transportation department pages.",
              "The district has no transportation URL set.",
              "We don't have a link to the district's transportation pages.",
              "Set the district's transportation URL; if its pages aren't the supported layout, a parser is needed."),
    DataPoint("care", "Before and after care", "Services and documents", frozenset({"elementary"}), "Elementary", "One-off district import", "The district before- and after-care handbook", "No scan", "Not confirmed this school year", True,
              "Before- and after-care hours and the site phone number, or confirmation it isn't offered.",
              "No before and after care source has been imported for this school.",
              "We don't have before- and after-care details for this school.",
              "Run the one-off import for this district."),
)
POINTS_BY_KEY = {p.key: p for p in DATA_POINTS}
GROUPS = ("Identity", "People", "Schedule", "News and events", "Services and documents")


# --- cadence ---------------------------------------------------------------

@dataclass(frozen=True)
class Cadence:
    runs: str
    stale_after: str
    window: timedelta | None  # None = "one school day" (weekday counting)


_TIERS = (
    (timedelta(hours=3), Cadence("Every 2 hours on school days", "1 school day", None)),
    (timedelta(hours=13), Cadence("Every 12 hours", "36 hours", timedelta(hours=36))),
    (timedelta(hours=26), Cadence("Daily", "3 days", timedelta(days=3))),
    (timedelta(days=8), Cadence("Weekly", "16 days", timedelta(days=16))),
    (timedelta(days=17), Cadence("Twice a month", "35 days", timedelta(days=35))),
)
_MONTHLY = Cadence("Monthly", "65 days", timedelta(days=65))
_cadence_cache: dict[str, Cadence] = {}


def cadence_for_cron(cron_expr: str) -> Cadence:
    """Tier by the shortest gap between upcoming fires: an hourly-on-weekdays
    cron's longest gap is the weekend, but its rhythm is the short one. The
    window per tier is two missed runs plus a grace period (Catalog screen)."""
    if cron_expr in _cadence_cache:
        return _cadence_cache[cron_expr]
    try:
        it = croniter(cron_expr, datetime(2026, 1, 5, tzinfo=timezone.utc))
        fires = [it.get_next(datetime) for _ in range(8)]
        gap = min(b - a for a, b in zip(fires, fires[1:]))
    except (ValueError, KeyError):
        gap = timedelta(days=1)
    cadence = next((c for limit, c in _TIERS if gap <= limit), _MONTHLY)
    _cadence_cache[cron_expr] = cadence
    return cadence


def is_past_window(last_good: datetime, cadence: Cadence, now: datetime) -> bool:
    if cadence.window is not None:
        return now - last_good > cadence.window
    # One school day: stale once a whole weekday has gone by since the last
    # good run's day.
    day = last_good.astimezone(TZ).date() + timedelta(days=1)
    today = now.astimezone(TZ).date()
    while day < today:
        if day.weekday() < 5:
            return True
        day += timedelta(days=1)
    return False


def school_year_start(today: date) -> date:
    return date(today.year if today.month >= 7 else today.year - 1, 7, 1)


def academic_year_start(value: str | None) -> int | None:
    if not value:
        return None
    digits = "".join(ch if ch.isdigit() else " " for ch in value).split()
    years = [int(d) for d in digits if len(d) == 4]
    return years[0] if years else None


# --- findings --------------------------------------------------------------

@dataclass
class Finding:
    status: str
    why: str  # internal
    why_district: str
    next: str  # internal
    next_district: str
    tag: str = ""  # internal
    tag_district: str = ""
    last_good: datetime | None = None
    last_label: str = ""  # used when there's no timestamp ("Entered by hand")
    runs: str = ""
    stale_after: str = ""
    job_ids: list[str] = field(default_factory=list)
    error_code: str | None = None
    internal_only: bool = False  # nothing the district can do about it
    edit: str | None = None  # where the source is edited: "school" | "district" | "newsletters" | "scans"
    not_published: bool = False


@dataclass
class RunInfo:
    status: str  # success | warning | error
    error_code: str | None
    error_stage: str | None
    at: datetime


@dataclass
class AuditContext:
    now: datetime
    districts: dict[str, District]
    jobs: dict[str, ScheduledJob]
    last_run: dict[str, RunInfo]
    last_success: dict[str, datetime]
    last_fetch: dict[str, datetime]  # success or warning
    staff: dict[str, tuple[int, datetime | None]]
    preschool_team: dict[str, int]
    newsletters_by_school: dict[str, list[SmoreNewsletter]]
    backpacks_by_school: dict[str, list[SmoreNewsletter]]
    backpacks_by_district: dict[str, list[SmoreNewsletter]]
    ptboards_by_school: dict[str, list[SmoreNewsletter]]
    newest_block: dict[str, datetime]
    documents: dict[tuple[str, str], list[SchoolDocument]]
    sacc: dict[str, SaccProgram]
    transportation: set[str]
    menu_latest_school: dict[str, datetime]
    menu_latest_district: dict[tuple[str, str | None], datetime]
    not_published: dict[tuple[str, str], AuditNotPublished]


def _fmt_age(delta: timedelta) -> str:
    days = delta.days
    if days >= 2:
        return f"{days} days"
    hours = int(delta.total_seconds() // 3600)
    return f"{hours} hours" if hours != 1 else "1 hour"


_CODE_HINTS = {
    "site_did_not_load": "Re-run off-peak. If it keeps failing, check the site for a bot wall.",
    "scraper_timeout": "Re-run off-peak; the page took too long to render.",
    "scraper_unavailable": "The scraper was down or overloaded; re-run once it's healthy.",
    "smore_no_blocks": "The link has most likely expired. Replace the newsletter URL with a live issue.",
    "source_http_error": "The source returned an HTTP error. Check whether the URL has moved.",
    "llm_rate_limited": "Re-run later; extraction was rate limited.",
    "no_documents_found": "Check whether the school site has moved its documents page.",
    "no_staff_found": "Check whether the directory page has moved or changed layout.",
}


def _job_finding(point: DataPoint, ctx: AuditContext, job: ScheduledJob, *, has_data: bool | None, warning_ok: bool = False,
                 not_found_codes: frozenset[str] = frozenset(), missing_status: str = FAILING, edit: str = "school") -> Finding:
    """The common rule for a data point backed by one scheduled job.
    `has_data` None = we can't tell from the tables, trust the job."""
    cadence = cadence_for_cron(job.cron_expr)
    base = dict(runs=cadence.runs, stale_after=cadence.stale_after, job_ids=[job.id], edit=edit)
    run = ctx.last_run.get(job.id)
    good = ctx.last_fetch.get(job.id) if (warning_ok and has_data) else ctx.last_success.get(job.id)
    paused = "" if job.enabled else " The scan is switched off."
    last_internal = (f" Data from {_fmt_age(ctx.now - good)} ago is still showing." if good and has_data is not False else "")

    if run and run.status == "warning" and run.error_code in not_found_codes and not has_data:
        return Finding(NONE, point.none_why, point.none_why_district, point.none_next, point.ask,
                       tag="not found", tag_district="not found", last_good=good, error_code=run.error_code, **base)
    if run and (run.status == "error" or (run.status == "warning" and not (warning_ok and has_data))):
        code = run.error_code or ("unspecified" if run.status == "warning" else "unknown")
        kind = "warning" if run.status == "warning" else "error"
        stage = f", {run.error_stage}" if run.error_stage else ""
        never = "" if ctx.last_success.get(job.id) else " It has never scanned successfully."
        return Finding(
            FAILING,
            f"{code}: the last {job.kind} run ({run.at.astimezone(TZ):%-d %b}) ended in a {kind}.{never}{last_internal}{paused}",
            "We couldn't read this from the published source on our last check.",
            _CODE_HINTS.get(code, "Open the run for its error code, then re-run."),
            "Nothing needed yet; we're looking into it." if kind == "error" else point.ask,
            tag=f"{code} ({kind}{stage})", tag_district="couldn't read the source",
            last_good=good, error_code=code, internal_only=(kind == "error"), **base)
    if good is None:
        return Finding(STALE, f"{job.kind} is set up but has never completed successfully.{paused}",
                       "We haven't been able to collect this yet.", "Run the scan now and check its result.",
                       "Nothing needed yet; we're looking into it.", tag="never scanned", tag_district="not collected yet",
                       internal_only=True, **base)
    if is_past_window(good, cadence, ctx.now):
        return Finding(STALE, f"The last good {job.kind} run was {_fmt_age(ctx.now - good)} ago, past its {cadence.stale_after} window.{paused}",
                       "Our copy hasn't been refreshed recently.",
                       "Turn the scan back on, or run it now." if not job.enabled else "Check whether the source has moved or stopped updating, then re-run.",
                       "Nothing needed yet; we're looking into it.", tag="scan paused" if not job.enabled else "",
                       last_good=good, internal_only=True, **base)
    if has_data is False:
        if missing_status == NONE:
            return Finding(NONE, point.none_why, point.none_why_district, point.none_next, point.ask,
                           tag="not found", tag_district="not found", last_good=good, **base)
        return Finding(FAILING, f"The last {job.kind} run succeeded but nothing is on file.",
                       "The published source didn't contain this when we last checked.",
                       "Open the run's log to see what it read.", point.ask, tag="scan found nothing",
                       tag_district="not found in the source", last_good=good, **base)
    return Finding(CURRENT, "The last scan succeeded and the data on file is inside its freshness window.",
                   "On file and up to date.", "Nothing to do.", "Nothing needed.", last_good=good, **base)


_RANK = {CURRENT: 0, STALE: 1, FAILING: 2, NONE: 3}


def _best(findings: Iterable[Finding]) -> Finding | None:
    """"A or B" sources: any one working is enough."""
    found = list(findings)
    return min(found, key=lambda f: _RANK[f.status]) if found else None


def _no_source(point: DataPoint, edit: str) -> Finding:
    if point.internal_gap:
        return Finding(NONE, point.none_why, "We don't collect this yet.", point.none_next, "Nothing needed from the district.",
                       tag="no parser yet", internal_only=True, edit=edit, runs=point.runs, stale_after=point.stale_after)
    return Finding(NONE, point.none_why, point.none_why_district, point.none_next, point.ask, tag="no source set",
                   tag_district="", edit=edit, runs=point.runs, stale_after=point.stale_after)


def _by_hand(point: DataPoint, present: bool, edit: str = "school", extra: str = "") -> Finding:
    if present:
        return Finding(CURRENT, f"Entered by hand or extracted once; nothing re-checks it.{extra}", "On file.", "Nothing to do.",
                       "Nothing needed.", tag="entered by hand", last_label="Entered by hand, not re-checked",
                       edit=edit, runs=point.runs, stale_after=point.stale_after)
    return _no_source(point, edit)


def _jobs(ctx: AuditContext, *ids: str | None) -> list[ScheduledJob]:
    return [ctx.jobs[i] for i in ids if i and i in ctx.jobs]


def evaluate(point: DataPoint, school: School, ctx: AuditContext) -> Finding:
    kind = KIND_BY_TYPE.get(school.school_type or "")
    if point.applies is not None and kind not in point.applies:
        noun = _KIND_NOUN.get(kind, "this school")
        why = f"Applies to: {point.applies_label.lower()}. Left out of the score for {noun}."
        return Finding(NA, why, why, "Nothing to do.", "Nothing needed.", last_label="None expected",
                       runs=point.runs, stale_after=point.stale_after)
    finding = _evaluate_applicable(point, school, ctx)
    mark = ctx.not_published.get((school.id, point.key))
    if mark and finding.status == NONE:
        when = mark.created_at.astimezone(TZ)
        note = f" Note: {mark.note}" if mark.note else ""
        return Finding(NONE, f"Marked as not published on {when:%-d %b %Y}.{note}",
                       f"The school doesn't publish this (confirmed {when:%-d %B %Y}).",
                       "Nothing to do unless it starts being published.", "Nothing needed unless it starts being published.",
                       tag="not published", tag_district="not published", runs=finding.runs, stale_after=finding.stale_after,
                       job_ids=finding.job_ids, edit=finding.edit, not_published=True)
    return finding


def _evaluate_applicable(point: DataPoint, school: School, ctx: AuditContext) -> Finding:
    k = point.key
    district = ctx.districts.get(school.district_id or "")

    if k in ("info", "logo", "geo"):
        present = {"info": bool(school.address and school.main_phone), "logo": bool(school.logo_url),
                   "geo": school.latitude is not None and school.longitude is not None}[k]
        jobs = _jobs(ctx, school.school_info_job_id)
        if not jobs:
            return _by_hand(point, present)
        f = _job_finding(point, ctx, jobs[0], has_data=present, warning_ok=True)
        if k == "geo" and not present and not school.address:
            f.why = "No address is on file to geocode. " + f.why
        return f

    if k == "staff":
        jobs = _jobs(ctx, school.staff_roster_job_id)
        count, _synced = ctx.staff.get(school.id, (0, None))
        if not jobs:
            return _by_hand(point, count > 0, extra=" Staff rows exist without a roster scan.") if count else _no_source(point, "school")
        return _job_finding(point, ctx, jobs[0], has_data=count > 0, not_found_codes=frozenset({"no_staff_found"}))

    if k == "absence":
        return _by_hand(point, bool(school.absence_method))
    if k == "hours":
        return _by_hand(point, bool(school.start_time and school.end_time))
    if k == "alt":
        both = bool(school.early_dismissal_time and school.delayed_opening_time)
        either = bool(school.early_dismissal_time or school.delayed_opening_time)
        f = _by_hand(point, either)
        if either and not both:
            missing = "delayed-opening" if school.early_dismissal_time else "early-dismissal"
            f.why += f" Only one of the two is on file; the {missing} time is missing."
        return f
    if k == "periods":
        return _by_hand(point, bool(school.bell_periods))

    if k == "care":
        row = ctx.sacc.get(school.id)
        if not row:
            return _no_source(point, "scans")
        if row.updated_at and row.updated_at.astimezone(TZ).date() < school_year_start(ctx.now.astimezone(TZ).date()):
            return Finding(STALE, "Imported in an earlier school year and not re-imported since.",
                           "Our copy is from an earlier school year.", "Re-run the one-off import for this district.",
                           "This year's before- and after-care hours and site phone numbers.",
                           tag="entered last school year", tag_district="from an earlier school year",
                           last_good=row.updated_at, runs=point.runs, stale_after=point.stale_after, edit="scans")
        return Finding(CURRENT, "Imported by the one-off district import this school year.", "On file.", "Nothing to do.",
                       "Nothing needed.", last_good=row.updated_at, runs=point.runs, stale_after=point.stale_after, edit="scans")

    if district is None and k in ("pkteam", "cal", "mp", "rot", "bus"):
        f = _no_source(point, "school")
        f.why = "This school has no district set, so district-level sources can't reach it."
        f.next = "Set the school's district."
        return f

    if k == "pkteam":
        jobs = _jobs(ctx, district.preschool_team_job_id)
        if not jobs:
            return _no_source(point, "district")
        return _job_finding(point, ctx, jobs[0], has_data=ctx.preschool_team.get(school.id, 0) > 0, edit="district")

    if k == "cal":
        jobs = _jobs(ctx, district.calendar_scan_job_id, district.calendar_pdf_job_id)
        return _best(_job_finding(point, ctx, j, has_data=None, edit="district") for j in jobs) or _no_source(point, "district")
    if k == "mp":
        jobs = _jobs(ctx, district.marking_period_job_id)
        return _job_finding(point, ctx, jobs[0], has_data=None, edit="district") if jobs else _no_source(point, "district")
    if k == "rot":
        jobs = _jobs(ctx, district.hs_rotation_job_id)
        return _job_finding(point, ctx, jobs[0], has_data=None, edit="district") if jobs else _no_source(point, "district")
    if k == "bus":
        jobs = _jobs(ctx, district.transportation_job_id)
        if not jobs:
            return _no_source(point, "district")
        return _job_finding(point, ctx, jobs[0], has_data=district.id in ctx.transportation, edit="district")

    if k == "news":
        return _newsletter(point, school, ctx)

    if k == "pta":
        jobs = _jobs(ctx, school.givebacks_job_id, *(n.scheduled_job_id for n in ctx.ptboards_by_school.get(school.id, [])))
        return _best(_job_finding(point, ctx, j, has_data=None, edit="school") for j in jobs) or _no_source(point, "school")
    if k == "backpack":
        rows = ctx.backpacks_by_school.get(school.id, []) + ctx.backpacks_by_district.get(school.district_id or "", [])
        jobs = _jobs(ctx, *(n.scheduled_job_id for n in rows))
        return _best(_job_finding(point, ctx, j, has_data=None, edit="newsletters") for j in jobs) or _no_source(point, "newsletters")
    if k == "events":
        jobs = _jobs(ctx, school.special_events_scan_job_id, school.events_doc_job_id)
        return _best(_job_finding(point, ctx, j, has_data=None) for j in jobs) or _no_source(point, "school")

    single = {"bulletin": school.bulletin_doc_job_id, "ann": school.announcements_job_id, "actcal": school.activities_calendar_job_id,
              "actsite": school.activities_site_job_id, "ath": school.athletics_calendar_job_id}
    if k in single:
        jobs = _jobs(ctx, single[k])
        return _job_finding(point, ctx, jobs[0], has_data=None) if jobs else _no_source(point, "school")

    if k == "menu":
        return _menu(point, school, district, ctx)
    if k in ("hand", "belldoc"):
        return _document(point, school, ctx, "handbook" if k == "hand" else "bell_schedule")

    raise KeyError(k)


def _newsletter(point: DataPoint, school: School, ctx: AuditContext) -> Finding:
    rows = ctx.newsletters_by_school.get(school.id, [])
    if not rows:
        return _no_source(point, "newsletters")
    newest = max((ctx.newest_block[n.id] for n in rows if n.id in ctx.newest_block), default=None)
    jobs = _jobs(ctx, *(n.scheduled_job_id for n in rows))
    archive = any(n.source_type == "smore_archive" for n in rows)
    weekly = Cadence("Weekly, on Monday", "16 days, or newest issue over 21 days old", timedelta(days=16))
    base = dict(runs=weekly.runs, stale_after=weekly.stale_after, job_ids=[j.id for j in jobs], edit="newsletters", last_good=newest)

    # A broken link only matters when nothing fresh came in another way.
    if newest is None or ctx.now - newest > NEWSLETTER_MAX_AGE:
        for job in sorted(jobs, key=lambda j: ctx.last_run[j.id].at if j.id in ctx.last_run else ctx.now - timedelta(days=9999), reverse=True):
            run = ctx.last_run.get(job.id)
            if run and run.status in ("error", "warning"):
                f = _job_finding(point, ctx, job, has_data=newest is not None, edit="newsletters")
                if f.status == FAILING:
                    f.job_ids = base["job_ids"]
                    f.runs, f.stale_after, f.last_good = weekly.runs, weekly.stale_after, newest
                    if run.error_code == "smore_no_blocks":
                        f.why = ("smore_no_blocks: the page loads but has no newsletter blocks. The link has most likely expired, "
                                 "which looks the same as \"nothing new\" unless it is flagged." + ("" if newest else " It has never scanned successfully."))
                        f.why_district = "The newsletter link we have loads with no content and has most likely expired."
                        f.next_district, f.internal_only = "A link to a current issue.", False
                    return f
                break
    if newest is None:
        return Finding(STALE, "Newsletter sources are tracked but no issue content is on file yet.",
                       "We haven't collected an issue of this newsletter yet.", "Run the newsletter scan and check its result.",
                       "A link to a current issue.", tag="never scanned", tag_district="not collected yet", **base)
    age = ctx.now - newest
    if age > NEWSLETTER_MAX_AGE:
        per_issue = not archive
        return Finding(
            STALE,
            (f"The newest issue content on file is {_fmt_age(age)} old, past the 21-day window."
             + (" This school publishes each issue at a new URL; the tracked issue still scans cleanly." if per_issue else "")),
            f"The newest issue we have is {_fmt_age(age)} old." + (" Each issue is published at a new link." if per_issue else ""),
            "Add the current issue URL, or connect a Gmail scanner to catch new ones." if per_issue else "Check the archive page for newer issues.",
            "One stable link per school (an archive page), or the current issue's link." if per_issue else "A link to a current issue.",
            tag="new URL per issue" if per_issue else "", tag_district="out of date", **base)
    return Finding(CURRENT, "The newest issue is inside its 21-day window.", "On file and up to date.", "Nothing to do.", "Nothing needed.", **base)


def _menu(point: DataPoint, school: School, district: District | None, ctx: AuditContext) -> Finding:
    district_jobs = _jobs(ctx, district.scheduled_job_id, district.schoolcafe_job_id) if district else []
    school_jobs = _jobs(ctx, school.fdmealplanner_job_id, school.healthepro_job_id, school.myschoolplate_job_id,
                        school.nutrislice_job_id, school.presence_menu_job_id, school.special_events_scan_job_id)
    if not district_jobs and not school_jobs:
        latest = ctx.menu_latest_school.get(school.id)
        return _by_hand(point, latest is not None) if latest else _no_source(point, "school")

    findings = [_job_finding(point, ctx, j, has_data=None, edit="district") for j in district_jobs]
    findings += [_job_finding(point, ctx, j, has_data=None) for j in school_jobs]
    f = _best(findings)
    from_district = any(f is x for x in findings[: len(district_jobs)])
    if f.status != CURRENT:
        if from_district:
            f.tag = f.tag or "inherited from district"
        return f

    latest = max(filter(None, (ctx.menu_latest_school.get(school.id), ctx.menu_latest_district.get((school.district_id or "", school.school_type)),
                               ctx.menu_latest_district.get((school.district_id or "", None)))), default=None)
    today = ctx.now.astimezone(TZ).date()
    monday = today - timedelta(days=today.weekday())
    in_school_year = today.month not in (7, 8)
    if in_school_year and (latest is None or latest.astimezone(TZ).date() < monday):
        inherited = latest is None or bool(district_jobs) and school.id not in ctx.menu_latest_school
        on_file = f"The newest menu on file is for {latest.astimezone(TZ):%-d %B}." if latest else "No menu days are on file."
        return Finding(STALE, f"The scan succeeds, but there is no menu for the current week. {on_file}"
                              + (" Menus come from the district for every school of this type; fix once at district level." if inherited and district_jobs else ""),
                       f"We don't have a menu for the current week. {on_file}",
                       "Check the food-services page for the new month's menu." if district_jobs else "Check the vendor menu for the current week.",
                       point.ask, tag="inherited from district" if inherited and district_jobs else "no menu this week",
                       tag_district="out of date", last_good=latest, runs=f.runs, stale_after=point.stale_after,
                       job_ids=[j.id for j in district_jobs + school_jobs], edit=f.edit)
    f.last_good = latest or f.last_good
    if from_district:
        f.tag = "inherited from district"
    return f


def _document(point: DataPoint, school: School, ctx: AuditContext, doc_type: str) -> Finding:
    docs = [d for d in ctx.documents.get((school.id, doc_type), []) if d.is_current]
    jobs = _jobs(ctx, school.documents_scan_job_id)
    if not jobs:
        return _by_hand(point, bool(docs)) if docs else _no_source(point, "school")
    f = _job_finding(point, ctx, jobs[0], has_data=bool(docs), not_found_codes=frozenset({"no_documents_found"}), missing_status=NONE)
    if f.status != CURRENT:
        return f
    year = max((y for y in (academic_year_start(d.academic_year) for d in docs) if y), default=None)
    current_year = school_year_start(ctx.now.astimezone(TZ).date()).year
    if year is not None and year < current_year:
        label = f"{year}-{str(year + 1)[-2:]}"
        return Finding(STALE, f"The {point.label.lower()} on the school site is dated {label}. The scan reads it fine; the document itself is old.",
                       f"The {point.label.lower()} posted is dated {label}.", "Ask the school for this year's version.", point.ask,
                       tag="source is out of date", tag_district="out of date", last_label=f"{label} document",
                       last_good=f.last_good, runs=f.runs, stale_after=f.stale_after, job_ids=f.job_ids, edit="school")
    return f


# --- loading ---------------------------------------------------------------

async def load_context(db: AsyncSession, schools: list[School], now: datetime | None = None) -> AuditContext:
    now = now or datetime.now(timezone.utc)
    school_ids = [s.id for s in schools]
    district_ids = {s.district_id for s in schools if s.district_id}
    districts = {d.id: d for d in (await db.execute(select(District).where(District.id.in_(district_ids)))).scalars()} if district_ids else {}

    newsletters = list((await db.execute(select(SmoreNewsletter).where(
        (SmoreNewsletter.school_id.in_(school_ids)) | (SmoreNewsletter.district_id.in_(district_ids or {""}))))).scalars())
    by_school: dict[str, list[SmoreNewsletter]] = defaultdict(list)
    backpacks_school: dict[str, list[SmoreNewsletter]] = defaultdict(list)
    backpacks_district: dict[str, list[SmoreNewsletter]] = defaultdict(list)
    ptboards: dict[str, list[SmoreNewsletter]] = defaultdict(list)
    for n in newsletters:
        if n.source_type in ("smore", "smore_archive") and n.school_id:
            by_school[n.school_id].append(n)
        elif n.source_type == "virtual_backpack":
            (backpacks_school[n.school_id] if n.school_id else backpacks_district[n.district_id]).append(n)
        elif n.source_type == "ptboard" and n.school_id:
            ptboards[n.school_id].append(n)

    job_ids: set[str] = set()
    for s in schools:
        job_ids.update(filter(None, (getattr(s, c.key) for c in School.__table__.columns if c.key.endswith("_job_id"))))
    for d in districts.values():
        job_ids.update(filter(None, (getattr(d, c.key) for c in District.__table__.columns if c.key.endswith("_job_id"))))
    job_ids.update(n.scheduled_job_id for n in newsletters if n.scheduled_job_id)

    jobs = {j.id: j for j in (await db.execute(select(ScheduledJob).where(ScheduledJob.id.in_(job_ids)))).scalars()} if job_ids else {}
    last_run: dict[str, RunInfo] = {}
    last_success: dict[str, datetime] = {}
    last_fetch: dict[str, datetime] = {}
    if jobs:
        finished = func.coalesce(JobRun.finished_at, JobRun.started_at)
        rows = await db.execute(
            select(JobRun.job_id, JobRun.status, JobRun.error_code, JobRun.error_stage, finished)
            .where(JobRun.job_id.in_(jobs.keys()), JobRun.status.in_(("success", "warning", "error")))
            .order_by(JobRun.job_id, JobRun.started_at.desc())
            .distinct(JobRun.job_id)
        )
        for job_id, st, code, stage, at in rows.all():
            last_run[job_id] = RunInfo(st, code, stage, at)
        rows = await db.execute(
            select(JobRun.job_id, JobRun.status, func.max(finished))
            .where(JobRun.job_id.in_(jobs.keys()), JobRun.status.in_(("success", "warning")))
            .group_by(JobRun.job_id, JobRun.status)
        )
        for job_id, st, at in rows.all():
            if st == "success":
                last_success[job_id] = at
            last_fetch[job_id] = max(at, last_fetch.get(job_id, at))

    staff: dict[str, tuple[int, datetime | None]] = {}
    preschool_team: dict[str, int] = {}
    if school_ids:
        team = StaffMember.source_constituent_id.like("preschool-team:%")
        for sid, n, synced in (await db.execute(
            select(StaffMember.school_id, func.count(), func.max(StaffMember.last_synced_at))
            .where(StaffMember.school_id.in_(school_ids), ~team).group_by(StaffMember.school_id))).all():
            staff[sid] = (n, synced)
        for sid, n in (await db.execute(
            select(StaffMember.school_id, func.count()).where(StaffMember.school_id.in_(school_ids), team).group_by(StaffMember.school_id))).all():
            preschool_team[sid] = n

    newest_block: dict[str, datetime] = {}
    if newsletters:
        for nid, at in (await db.execute(select(SmoreBlock.newsletter_id, func.max(SmoreBlock.first_seen_at))
                                         .where(SmoreBlock.newsletter_id.in_([n.id for n in newsletters])).group_by(SmoreBlock.newsletter_id))).all():
            newest_block[nid] = at

    documents: dict[tuple[str, str], list[SchoolDocument]] = defaultdict(list)
    sacc: dict[str, SaccProgram] = {}
    menu_school: dict[str, datetime] = {}
    if school_ids:
        for d in (await db.execute(select(SchoolDocument).where(SchoolDocument.school_id.in_(school_ids),
                                                                SchoolDocument.doc_type.in_(("handbook", "bell_schedule"))))).scalars():
            documents[(d.school_id, d.doc_type)].append(d)
        sacc = {r.school_id: r for r in (await db.execute(select(SaccProgram).where(SaccProgram.school_id.in_(school_ids)))).scalars()}
        for sid, at in (await db.execute(select(LunchMenu.school_id, func.max(LunchMenuItem.menu_date))
                                         .join(LunchMenuItem, LunchMenuItem.lunch_menu_id == LunchMenu.id)
                                         .where(LunchMenu.school_id.in_(school_ids)).group_by(LunchMenu.school_id))).all():
            menu_school[sid] = at
    menu_district: dict[tuple[str, str | None], datetime] = {}
    transportation: set[str] = set()
    if district_ids:
        for did, stype, at in (await db.execute(select(LunchMenu.district_id, LunchMenu.school_type, func.max(LunchMenuItem.menu_date))
                                                .join(LunchMenuItem, LunchMenuItem.lunch_menu_id == LunchMenu.id)
                                                .where(LunchMenu.district_id.in_(district_ids)).group_by(LunchMenu.district_id, LunchMenu.school_type))).all():
            menu_district[(did, stype)] = at
        transportation = set((await db.execute(select(DistrictTransportation.district_id).where(DistrictTransportation.district_id.in_(district_ids)))).scalars())

    marks = {}
    if school_ids:
        marks = {(m.school_id, m.data_point): m for m in (await db.execute(select(AuditNotPublished).where(AuditNotPublished.school_id.in_(school_ids)))).scalars()}

    return AuditContext(now, districts, jobs, last_run, last_success, last_fetch, staff, preschool_team, by_school,
                        backpacks_school, backpacks_district, ptboards, newest_block, documents, sacc, transportation,
                        menu_school, menu_district, marks)


# --- rendering -------------------------------------------------------------

def _source_label(point: DataPoint, finding: Finding, ctx: AuditContext) -> str:
    kinds = sorted({ctx.jobs[j].kind for j in finding.job_ids if j in ctx.jobs})
    return " or ".join(kinds) if kinds else point.source_internal


def render_cell(point: DataPoint, finding: Finding, ctx: AuditContext, audience: str, *, full: bool = True) -> dict:
    """One school x data point for one audience. The district dict is built
    from district-only fields - never the internal dict with keys removed."""
    if not full:
        tag = finding.tag if audience == "internal" else finding.tag_district
        return {"status": finding.status, "tag": tag}
    last = finding.last_good.isoformat() if finding.last_good else None
    last_label = finding.last_label or (f"{finding.last_good.astimezone(TZ):%-d %B %Y}" if finding.last_good else
                                        ("None expected" if finding.status == NA else "None on file"))
    if audience == "district":
        return {
            "key": point.key, "status": finding.status, "tag": finding.tag_district,
            "why": finding.why_district, "next": finding.next_district,
            "last_good": last, "last_label": last_label,
            "collected_by": point.source_district, "runs": finding.runs or point.runs, "stale_after": finding.stale_after or point.stale_after,
            "internal_only": finding.internal_only,
        }
    return {
        "key": point.key, "status": finding.status, "tag": finding.tag,
        "why": finding.why, "next": finding.next,
        "why_district": finding.why_district, "next_district": finding.next_district,
        "last_good": last, "last_label": last_label,
        "collected_by": _source_label(point, finding, ctx), "runs": finding.runs or point.runs, "stale_after": finding.stale_after or point.stale_after,
        "internal_only": finding.internal_only,
        "error_code": finding.error_code, "job_ids": list(finding.job_ids), "edit": finding.edit,
        "not_published": finding.not_published,
    }


def counts_for(statuses: Iterable[str]) -> dict:
    n = {s: 0 for s in STATUSES}
    for s in statuses:
        n[s] += 1
    applicable = sum(n[s] for s in STATUSES if s != NA)
    n["applicable"] = applicable
    n["pct"] = round(100 * n[CURRENT] / applicable) if applicable else None
    return n


def school_summary(school: School, ctx: AuditContext) -> dict:
    district = ctx.districts.get(school.district_id or "")
    kind = KIND_BY_TYPE.get(school.school_type or "")
    return {
        "id": school.id, "slug": school.slug, "name": school.name, "short_name": school.short_name or school.name,
        "kind": kind, "kind_label": KIND_LABELS.get(kind, "Type not set"),
        "district_id": school.district_id, "district_name": district.name if district else None,
    }


def audit_school(school: School, ctx: AuditContext) -> dict[str, Finding]:
    return {p.key: evaluate(p, school, ctx) for p in DATA_POINTS}


def catalog(audience: str) -> list[dict]:
    out = []
    for i, p in enumerate(DATA_POINTS):
        row = {"key": p.key, "label": p.label, "group": p.group, "order": i, "applies": p.applies_label, "runs": p.runs,
               "stale_after": p.stale_after, "by_hand": p.by_hand,
               "collected_by": p.source_internal if audience == "internal" else p.source_district}
        out.append(row)
    return out


def jobs_to_run(findings: Iterable[Finding], ctx: AuditContext, registered: Callable[[str], bool]) -> list[ScheduledJob]:
    seen: dict[str, ScheduledJob] = {}
    for f in findings:
        for jid in f.job_ids:
            job = ctx.jobs.get(jid)
            if job and registered(job.kind):
                seen[jid] = job
    return list(seen.values())
