import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


def normalize_name(value: str) -> str:
    return " ".join(value.strip().lower().split())


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "school"


_SCHOOL_NAME_SUFFIXES = [
    r"\s+International Middle School$",
    r"\s+Early Childhood Center$",
    r"\s+Elementary School$",
    r"\s+Middle School$",
    r"\s+High School$",
    r"\s+Elementary$",
]


def derive_school_short_name(full_name: str, district_name: str | None = None) -> str:
    """Best-effort default for School.short_name: strips the district name
    prefix and generic institution-type suffix, and a leading single-letter
    initial (e.g. "A. Russell Knight" -> "Russell Knight"). Not perfect for
    every real name (e.g. "Henry C. Beck Middle School" -> "Henry C. Beck",
    not "Beck") - short_name is meant to be manually corrected via
    PATCH /schools/{id} when the default doesn't match what a guardian
    actually wants to see, not treated as always-correct."""
    name = full_name.strip()
    if district_name and name.lower().startswith(district_name.strip().lower()):
        name = name[len(district_name.strip()):].strip()
    for pattern in _SCHOOL_NAME_SUFFIXES:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE)
    name = re.sub(r"^[A-Z]\.\s+", "", name)
    return name.strip() or full_name.strip()


def student_match_key(first_name: str, last_name: str, student_id: str) -> str:
    return f"{normalize_name(first_name)}|{normalize_name(last_name)}|{student_id.strip()}"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # Only set in local auth mode (bcrypt hash). Null for users provisioned via Supabase.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Set when this row was provisioned from a Supabase-authenticated login (prod).
    supabase_user_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Local auth mode only (prod's Supabase handles its own reset emails):
    # a one-shot token from POST /auth/forgot-password, cleared on use.
    password_reset_token: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class Student(Base):
    """Canonical record for a real child. Shared across every guardian who
    matches or is invited onto it - never owned by a single guardian.

    NOTE: no `user_id` column yet for the student's own login (that's a
    planned follow-up, not built in this pass - see CLAUDE.md).
    """

    __tablename__ = "students"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    student_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Cached display copy of the chosen School's name at add-time.
    # school_id (required at the API layer, chosen from a dropdown of
    # tracked schools - a child attends exactly one at a time) is the real
    # link; this column exists only so student listings don't need a join.
    school_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    school_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("schools.id", ondelete="SET NULL"), nullable=True)
    # normalize_name(first)|normalize_name(last)|student_id.strip() - how a
    # second guardian entering the same child gets auto-matched to this row
    # instead of creating a duplicate.
    match_key: Mapped[str] = mapped_column(String(400), unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class GuardianStudentLink(Base):
    """One guardian's own link to a student. Deleting this row only removes
    that guardian's access/view - it never touches the Student row or any
    other guardian's link to the same student."""

    __tablename__ = "guardian_student_links"
    __table_args__ = (UniqueConstraint("guardian_user_id", "student_id", name="uq_guardian_student"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    guardian_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    student_id: Mapped[str] = mapped_column(String(36), ForeignKey("students.id"), nullable=False)
    # "created" (first guardian to add this student), "auto_matched" (entered
    # the same name+student_id as an existing record), "invite_accepted"
    # (accepted another guardian's invite to this specific student).
    linked_via: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class GuardianInvite(Base):
    """A per-child invite: grants the accepting user a GuardianStudentLink
    to exactly one student, without them needing to know the student ID."""

    __tablename__ = "guardian_invites"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(String(36), ForeignKey("students.id"), nullable=False)
    inviter_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    invitee_email: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    # "pending" | "accepted" | "revoked"
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_by_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GmailToken(Base):
    """One connected Gmail account. A user may connect multiple accounts -
    PK is (user_id, google_email), not just user_id."""

    __tablename__ = "gmail_tokens"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), primary_key=True)
    google_email: Mapped[str] = mapped_column(String(255), primary_key=True)
    access_token: Mapped[str] = mapped_column(String, nullable=False)
    refresh_token: Mapped[str] = mapped_column(String, nullable=False)
    token_expiry: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class ScheduledJob(Base):
    """A recurring job definition. `kind` maps to a handler in
    scheduler/registry.py; `params` is handler-specific config.

    `owner_user_id` is nullable so a future system-wide job (no single
    owner) is representable, but every job created through the API today
    always has one - self-service, not admin-curated like billz."""

    __tablename__ = "scheduled_jobs"
    __table_args__ = (UniqueConstraint("owner_user_id", "kind", "name", name="uq_scheduled_job_owner_kind_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cron_expr: Mapped[str] = mapped_column(String(100), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York", nullable=False)
    params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "success" | "error" | "running" | "skipped"
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    # Stable, groupable reason for the last run's failure/warning - see
    # scheduler/errors.py. Null for a success (or a warning with no
    # parseable code, e.g. a bare "WARNING:" - see parse_warning()).
    last_error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A job that should fire exactly once, then turn itself off - added for
    # Smore newsletters whose URL is discarded and replaced with a brand
    # new one every issue (confirmed real for most schools, not just the
    # documented Cooper/Clara Barton exceptions - e.g. Beck already has two
    # separate tracked URLs). Re-scanning a dead URL forever on a cron is
    # pointless for those; the runner (`_finalize`) disables the job the
    # moment its first run finishes, regardless of outcome. Generic on
    # `ScheduledJob` rather than Smore-specific since any job kind could
    # plausibly want a single-shot run.
    run_once: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("scheduled_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "running" | "success" | "error" | "skipped"
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    # See scheduler/errors.py: classify_exception() for an error, parse_warning()
    # for a warning. error_stage is only set for a real error (fetch/parse/
    # extract/persist/unknown), null for a warning or success.
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    error_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    log_excerpt: Mapped[str | None] = mapped_column(String, nullable=True)
    # "cron" | "manual"
    triggered_by: Mapped[str] = mapped_column(String(20), default="cron", nullable=False)


class EmailScanner(Base):
    """One configured recurring Gmail search: filters + a `purpose` telling
    the processor registry how to handle each new matched message. Paired
    1:1 with a ScheduledJob (kind="email.scan", params={"scanner_id": id})."""

    __tablename__ = "email_scanners"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    google_email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # OR'd within each list, AND'd across lists; raw_query appended verbatim.
    from_contains: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    subject_contains: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    body_contains: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    raw_query: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lookback_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    # "school_email" for now - see services/email_processors/
    purpose: Mapped[str] = mapped_column(String(50), nullable=False)
    # Optional - set when a scanner is dedicated to one school's mail (the
    # normal case: a scanner named "X SMORE" filtering on that school's own
    # newsletter subject line). Lets the school_email processor deterministically
    # attribute any Smore link it finds to this school instead of leaving a
    # newly-discovered SmoreNewsletter unlinked and unscheduled every time.
    school_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("schools.id", ondelete="SET NULL"), nullable=True)
    scheduled_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class EmailScannerMatch(Base):
    """Idempotency/audit ledger: one row per Gmail message a scanner has
    ever seen, so re-runs never reprocess the same message twice."""

    __tablename__ = "email_scanner_matches"
    __table_args__ = (UniqueConstraint("scanner_id", "message_id", name="uq_email_scanner_matches_msg"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    scanner_id: Mapped[str] = mapped_column(String(36), ForeignKey("email_scanners.id", ondelete="CASCADE"), nullable=False)
    message_id: Mapped[str] = mapped_column(String(100), nullable=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sender: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    snippet: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # "pending" | "ok" | "skipped" | "error"
    processor_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    processor_error: Mapped[str | None] = mapped_column(String, nullable=True)
    artifact_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    artifact_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class SchoolEmailMessage(Base):
    """The `school_email` purpose's artifact: captured message content for
    review. Real structured extraction (this is an absence notice / this is
    a newsletter link, etc.) is a follow-up pass once there's real data."""

    __tablename__ = "school_email_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    scanner_id: Mapped[str] = mapped_column(String(36), ForeignKey("email_scanners.id", ondelete="CASCADE"), nullable=False)
    gmail_message_id: Mapped[str] = mapped_column(String(100), nullable=False)
    sender: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    body_text: Mapped[str | None] = mapped_column(String, nullable=True)
    # Smore (or similar hosted-newsletter) links found in the body, if any -
    # e.g. [{"url": "...", "fetched": false}]. Populated by the school_email
    # processor; a follow-up pass fetches+parses each into SmoreBlock rows.
    newsletter_links: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class District(Base):
    """A school district (e.g. Cherry Hill Public Schools). Some resources
    are published at the district level and apply to every school of a
    given type within it - lunch menus are the first confirmed case: one
    PDF per (district, school_type, month), not one per school. Modeling
    the district explicitly is what makes that lookup possible without the
    parent ever needing to know or care that it's shared."""

    __tablename__ = "districts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Page listing current breakfast/lunch menu PDFs by grade band - the
    # entry point for services/lunch_menu.py's discovery step.
    food_services_menu_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    scheduled_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True)
    # Direct .ics feed URLs for the district's own calendars - [{"name":
    # str, "url": str}, ...]. Confirmed real for Cherry Hill: a district can
    # publish more than one (its main events calendar - holidays, early
    # dismissals, in-service days, closures - plus e.g. a separate
    # elementary specials rotation calendar), and a Finalsite calendar
    # widget's visible "Subscribe" button only ever reveals its feed URL
    # via a clipboard write, never a plain link in the page (see
    # services/district_calendar.py for how these were actually found).
    ics_feeds: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    calendar_scan_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True)
    # Page listing interim/marking-period/report-card dates per school tier
    # (High/Middle/Grades K-5/Preschool) - parsed deterministically via real
    # HTML <table> elements, not an LLM pass (services/marking_period.py).
    marking_period_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    marking_period_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True)
    # District's own directory of preschool provider locations (mostly
    # private third-party sites, not chclc.org - see services/
    # preschool_locations.py) and its central preschool administration
    # staff page (services/preschool_team.py). Neither is a Finalsite site
    # in the school_info/staff_roster/documents sense, so these get their
    # own dedicated scans rather than reusing those.
    preschool_locations_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    preschool_locations_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True)
    preschool_team_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    preschool_team_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True)
    # Nav page linking the shared East/West high school day-rotation PDF
    # (services/hs_rotation.py) - one page covers both high schools.
    hs_rotation_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    hs_rotation_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True)
    # The district's transportation department page tree (services/
    # transportation.py) - office contact, late buses, delay policy,
    # bus stop changes, lost items. One page tree serves every school.
    transportation_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    transportation_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class School(Base):
    """A real school. Public/shared data (like Student), not owned by one
    user. Absence-reporting fields drive the adaptive "report absence"
    button in the UI - whichever method the school's own materials specify
    (confirmed schools vary: some want a phone call, some want email to
    named staff - see CLAUDE.md)."""

    __tablename__ = "schools"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # URL-friendly, unique, derived from short_name/name at creation
    # (slugify() + a numeric suffix on collision) - lets a school's page be
    # shared as /schools/bret-harte-elementary instead of a bare UUID.
    # routers/schools.py resolves a path param against id OR slug, so
    # existing links/API calls using the id keep working unchanged.
    slug: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    # Auto-derived at creation (derive_school_short_name), user-editable
    # thereafter. Exists because "school" alone is useless once a guardian
    # has kids at more than one school - the calendar/content scope badge
    # shows this instead, with the generic institution-type suffix
    # ("Elementary School" etc) and district name dropped since they're
    # redundant. The derivation can't perfectly guess every school's
    # preferred short form (e.g. "Henry C. Beck Middle School" -> "Beck"
    # needs a manual override), so this is a starting point, not gospel.
    short_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    district_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("districts.id", ondelete="SET NULL"), nullable=True)
    # "elementary" | "middle" | "high" | "alternative" | "other" | null
    # (unknown yet) - determines which district-level resources (like lunch
    # menus) apply to this school.
    school_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    main_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # "email" | "phone" | "portal" | "other" | null (not yet known)
    absence_method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    absence_emails: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    absence_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Only for absence_method="portal" - e.g. "Genesis". absence_portal_url
    # is resolved deterministically from a known-portal lookup table
    # (content_extractor.py), not trusted from the model directly, since a
    # newsletter naming a portal rarely also includes its actual login link.
    absence_portal_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    absence_portal_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Not populated for absence_method="portal" - a portal login flow's
    # click-by-click steps aren't worth surfacing once there's a direct link.
    absence_instructions: Mapped[str | None] = mapped_column(String, nullable=True)
    # Regular bell schedule as display strings ("8:45 AM"), plus the early
    # dismissal time - drive the "Open · 8:45–3:15" status pill on the Today
    # feed. Not scraped yet (varies per school site/handbook); admin-editable
    # via PATCH /schools/{id}.
    start_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    end_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    early_dismissal_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Start time on a delayed-opening day (both high schools: 9:30 AM, a
    # 2-hour delay; end time is unchanged).
    delayed_opening_time: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The full period-by-period table, for a live "what period is it right
    # now" view - the four day-level times above only cover start/end/
    # early-dismissal/delayed-opening as a whole, not each numbered
    # period's own start/end. Shape: {"regular": [...], "early_dismissal":
    # [...], "delayed_opening": [...]}, each a list of
    # {"name": "1"|"L1"|..., "start": "07:30", "end": "08:27"} in 24h
    # clock time (school-local, no date) - see services/bell_schedule.py.
    # Transcribed from each school's own published bell schedule PDF
    # (confirmed identical for East and West - see migration 0024), not
    # scraped; a school with no table on file here just has no current-
    # period feature, same as one with no start_time/end_time.
    bell_periods: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # External sports schedule (Cherry Hill's high schools publish game
    # schedules on ArbiterLive, keyed by an entityId - West 4058, East
    # 4057). A plain quick link; nothing is scraped from it. Labeled
    # "Sports & band" in the UI: the same ArbiterLive page carries the
    # marching band schedule too (confirmed by the user 2026-09-09).
    athletics_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # School's own logo/seal image, discovered from its homepage header
    # (services/school_info.py) - hotlinked from Finalsite's CDN like every
    # other asset URL in this app (lunch menu PDFs, documents), not
    # downloaded and re-hosted. Used in the school picker and the school
    # switcher chips in the top ribbon.
    logo_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # Auto-created (mirrors SmoreNewsletter/District) whenever website_url
    # is set - scans the school's own staff directory page.
    staff_roster_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True)
    # Auto-created alongside staff_roster_job_id - looks for the parent/
    # student handbook (and future document types) on the school's own site,
    # falling back to already-extracted Smore content when the site has no
    # standalone handbook page (confirmed real: several schools distribute
    # theirs only via a newsletter/Google Doc link, never on the site itself).
    documents_scan_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True)
    # Auto-created alongside the other website_url-triggered scans - fetches
    # address/main_phone from the school's own site footer.
    school_info_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True)
    # Base page URL (no ?mm=/&yy= query params - the job appends those
    # itself for whichever month(s) it's checking) for a per-school page
    # that lists monthly PDFs: a themed "special events" calendar, a lunch
    # menu, sometimes a newsletter. Only ever set by hand for a school
    # confirmed to actually publish this way (Chesterbrook Academy is the
    # first, confirmed 2026-09-12) - most schools have no such page at all.
    special_events_calendar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    special_events_scan_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class LunchMenu(Base):
    """A parsed menu, either district-wide (district_id+school_type set,
    school_id null - one PDF covers every school of that type, looked up
    by School.district_id+school_type so a parent never has to think about
    the fact that it's shared) or school-specific (school_id set, the
    others null - a single school's own newsletter-embedded menu, e.g. a
    private preschool with no district PDF pipeline at all). Mirrors
    SchoolContentItem's scope="district"/"school" split, just without a
    shared `scope` column since the two id columns already disambiguate.

    District-wide rows are keyed on source_pdf_url for dedup: districts
    publish a new PDF each month rather than editing one in place, so a
    changed URL means a new menu to parse, not an edit to the old one.
    School-specific rows reuse source_pdf_url for the source flyer's image
    URL instead, same dedup idea."""

    __tablename__ = "lunch_menus"
    __table_args__ = (
        UniqueConstraint("district_id", "school_type", "meal_type", "source_pdf_url", name="uq_lunch_menu_source"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    district_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("districts.id", ondelete="CASCADE"), nullable=True)
    school_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("schools.id", ondelete="CASCADE"), nullable=True)
    school_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # "breakfast" | "lunch"
    meal_type: Mapped[str] = mapped_column(String(20), nullable=False)
    period_label: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "September 2026"
    source_pdf_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    parsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class LunchMenuItem(Base):
    __tablename__ = "lunch_menu_items"
    __table_args__ = (UniqueConstraint("lunch_menu_id", "menu_date", name="uq_lunch_menu_item_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    lunch_menu_id: Mapped[str] = mapped_column(String(36), ForeignKey("lunch_menus.id", ondelete="CASCADE"), nullable=False, index=True)
    menu_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)


class StaffMember(Base):
    """One row per staff directory entry on a school's own Finalsite site
    (`/contact-us`, paginated via `?const_page=N`). `source_constituent_id`
    is Finalsite's own stable id for that person on that site
    (`data-constituent-id` in the HTML) - used for re-scan dedup instead of
    name matching, since names can have minor formatting differences across
    scans but the constituent id doesn't change.

    This is what lets a "person" mention parsed from a newsletter (see
    SchoolContentItem.staff_member_id) resolve to a real record instead of
    floating free text."""

    __tablename__ = "staff_members"
    __table_args__ = (UniqueConstraint("school_id", "source_constituent_id", name="uq_staff_member_school_constituent"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    school_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    source_constituent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Directory "Titles:" field. Genuinely absent for many real entries -
    # left null, not an empty string, when the source has no titles block.
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Deterministic keyword classification of `title` (services/staff_roles.py):
    # "principal" | "assistant_principal" | "nurse" | "counselor" | "secretary"
    # | "sacc" | "social_worker" | "psychologist" | null. Drives the
    # parent-facing "who to contact" grid; recomputed on every roster scan.
    role: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class SchoolContentItem(Base):
    """One piece of structured content extracted from a school's newsletter
    content (Smore blocks, eventually other sources). Deliberately one
    polymorphic table across all categories rather than N tables - the
    category list itself is expected to evolve as real newsletters get
    processed, and a shared shape keeps the calendar/summary/list queries
    simple (see backend/services/content_extractor.py for the extraction
    prompt and category definitions).

    Per explicit product decision: `policy_change` and `procedure` rows are
    only ever created when the source text itself flagged something as new
    or changed - baseline unchanging policy text is never extracted.

    Scoping (added for calendar filtering - a parent's calendar should show
    district-wide info + their own kids' schools, not every school in the
    system): `scope="school"` items belong to exactly one `School`
    (`school_id` set, `district_id` null). `scope="district"` items belong
    to a `District` instead (`district_id` set, `school_id` null) - these
    are things like holiday closures that every school in the district
    reports independently in their own newsletter; extraction dedupes them
    to one row per (district, category, date) rather than one per school."""

    __tablename__ = "school_content_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # "school" | "district" - exactly one of school_id/district_id is set,
    # matching this. Enforced in application code (services/content_extractor.py),
    # not a DB constraint.
    scope: Mapped[str] = mapped_column(String(10), default="school", nullable=False)
    school_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("schools.id", ondelete="CASCADE"), nullable=True, index=True)
    district_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("districts.id", ondelete="CASCADE"), nullable=True, index=True)
    newsletter_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("smore_newsletters.id", ondelete="SET NULL"), nullable=True)
    source_block_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("smore_blocks.id", ondelete="SET NULL"), nullable=True)
    # "newsletter" (default, from content_extractor.py) | "ics_feed" (from
    # services/district_calendar.py). external_uid is the iCal UID for
    # ics_feed rows - lets a re-scan update an existing row in place
    # instead of creating a duplicate, and also lets the ics scan claim an
    # already-newsletter-extracted row for the same district/category/date
    # (e.g. "Labor Day" reported independently by both a school's own
    # newsletter and the district calendar feed) rather than doubling it.
    source: Mapped[str] = mapped_column(String(20), default="newsletter", nullable=False)
    external_uid: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    # Restricts a scope="district" item to specific School.school_type
    # values (e.g. an elementary-only specials rotation calendar, or
    # marking-period/report-card dates that differ by grade tier) - null
    # means it applies district-wide regardless of school type, same as
    # before this column existed. Deliberately a filter on top of
    # scope="district" rather than creating one scope="school" row per
    # matching school - the data itself (e.g. 180 rotation-day entries) is
    # genuinely shared/identical across every school of that type, not
    # school-specific content that happens to repeat.
    applies_to_school_types: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # "event" | "deadline" | "initiative" | "reminder" | "policy_change" |
    # "procedure" | "program" | "busing" | "funding" | "volunteer" |
    # "org_club" | "merch_ad" | "pta" | "person" | "lunch_menu" |
    # "marking_period" (report card/interim/marking-period-end dates - not
    # a "deadline" a parent has to act on, so kept distinct: see
    # services/marking_period.py and the frontend's ItemTag "grading" badge)
    category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    # Used by "event"/"deadline"/"initiative" (a range: start+end both set).
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_all_day: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    link_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # "person" category only.
    person_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    person_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Resolved match against StaffMember (by normalized name, same school) -
    # ties a newsletter mention back to a real staff record. Nullable: the
    # mentioned person may not be in the roster (a parent, a vendor, etc)
    # or the roster may not have been scanned yet.
    staff_member_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("staff_members.id", ondelete="SET NULL"), nullable=True)
    # Verbatim-ish quote from the source, for provenance/spot-checking.
    source_excerpt: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    # Correction handling: block-level dedup is exact-text (a typo fix hashes
    # differently and would otherwise look like a brand-new item - e.g. two
    # near-duplicate calendar entries for one event with a corrected date).
    # Extraction is given the school's current items as context and can mark
    # a new item as superseding an old one (same event, corrected details)
    # instead of creating a confusing duplicate. Superseded items are kept
    # (not deleted) but excluded from default calendar/summary views.
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    superseded_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("school_content_items.id"), nullable=True)


class SmoreNewsletter(Base):
    """A hosted newsletter page (Smore, or similar) tracked for repeated
    scanning. Public/shared data (like Student), not owned by one user -
    `created_by_user_id` is just provenance. Reachable two ways: a guardian
    registers one directly (e.g. Bret Harte's weekly Smore URL) for its own
    recurring scan, or the `school_email` processor auto-creates one when it
    finds a newsletter link in a captured email (see school_email.py)."""

    __tablename__ = "smore_newsletters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    url: Mapped[str] = mapped_column(String(1000), unique=True, nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    school_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("schools.id", ondelete="SET NULL"), nullable=True)
    # For a newsletter that isn't any one school's - a district-wide
    # publication (confirmed real: Cherry Hill's own "CHPS Weekly", first
    # tracked 2026-09-11). Without this, content_extractor.py had nowhere
    # to attach a district-wide newsletter's items at all: scope="school"
    # items need a school_id and scope="district" items need a district_id
    # resolved from *a* school's own district_id - neither existed when
    # school_id was null, so every item silently became orphaned (created
    # with school_id=None, district_id=None, invisible everywhere).
    # Ordinarily exactly one of school_id/district_id is set, matching
    # SchoolContentItem's scope split - not enforced by a DB constraint.
    district_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("districts.id", ondelete="SET NULL"), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    scheduled_job_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Topical summary of the latest extraction pass - shown at the top of
    # the school page. Regenerated each time new blocks are extracted.
    latest_summary: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class SmoreBlock(Base):
    """One content block from a parsed newsletter page, keyed so re-scanning
    the same (still-live) URL only inserts genuinely new content - Smore
    pages get edited in place week to week, not replaced with a new URL.

    Image blocks carry no text on their own - `pending_vision_extraction`
    flags them for a follow-up Claude-vision pass (not run synchronously;
    needs ANTHROPIC_API_KEY, not yet configured for schoolz)."""

    __tablename__ = "smore_blocks"
    __table_args__ = (UniqueConstraint("newsletter_id", "content_hash", name="uq_smore_block_newsletter_hash"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    newsletter_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("smore_newsletters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # "text" | "image" | "link"
    block_type: Mapped[str] = mapped_column(String(20), nullable=False)
    text_content: Mapped[str | None] = mapped_column(String, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    link_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # sha256 of (block_type, text_content/image_url/link_url) - the dedup key.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pending_vision_extraction: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    vision_extracted_text: Mapped[str | None] = mapped_column(String, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class SchoolDocument(Base):
    """A discoverable reference document for a school - parent/student
    handbooks to start, extensible to other document types later. Shared/
    public like School itself.

    Discovery is heterogeneous (unlike LunchMenu's one reliable PDF-naming
    pattern): some schools link a handbook page directly from their own
    site nav, others only ever mention it inside a Smore newsletter (as a
    Google Doc link, confirmed real for one school) - `source` records
    which path found it. `academic_year` is parsed out of the title/link
    text when present (e.g. "2026-2027") specifically so a newer year can
    be preferred over a stale one - confirmed real case: one school's own
    site nav links a page still labeled "2023-2024" while its current
    newsletter links a "2026-2027" version instead."""

    __tablename__ = "school_documents"
    __table_args__ = (UniqueConstraint("school_id", "doc_type", "url", name="uq_school_document_url"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    school_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True)
    # "handbook" for now - extensible to other document types later.
    doc_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    # e.g. "2026-2027" - null when no year could be parsed out of the title/link text.
    academic_year: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # "website" | "newsletter"
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    # False once a newer-year document of the same doc_type is found for
    # this school - kept (not deleted) for history, excluded from default views.
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SaccProgram(Base):
    """School-Age Child Care (before/after-school care) info for one school
    - only exists for schools that actually host it. Confirmed real
    (Cherry Hill Public Schools): SACC is a single district-run program
    identical in hours/policy across every elementary school (K-5 only -
    Malberg, the district's Early Childhood Center, doesn't have it, and
    neither do any middle/high schools), but each school site has its own
    phone number, which is the number a parent actually needs when running
    late or checking on their kid - so this is modeled per-school even
    though most fields are the same district-wide text for every row.

    Deliberately NOT auto-scanned on a recurring job like SmoreNewsletter/
    LunchMenu - the source is one shared, slow-changing family handbook
    Google Doc plus a per-school phone directory page, not something that
    republishes on a predictable schedule the way a monthly newsletter
    does. Populated by a one-off admin script instead; re-run by hand if
    the handbook's hours/policy text changes."""

    __tablename__ = "sacc_programs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    school_id: Mapped[str] = mapped_column(String(36), ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, unique=True)
    am_hours: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pm_hours: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # This school's own SACC site phone - who to call to reach the site
    # directly (e.g. running late, day-of questions). Distinct from
    # absence_phone, which is the district SACC office's shared number.
    site_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    absence_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    absence_form_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    late_pickup_policy: Mapped[str | None] = mapped_column(String, nullable=True)
    pickup_change_procedure: Mapped[str | None] = mapped_column(String, nullable=True)
    closures_notes: Mapped[str | None] = mapped_column(String, nullable=True)
    handbook_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class DistrictTransportation(Base):
    """The district transportation department, one row per district -
    the bus answers a parent needs across every school (confirmed real
    for Cherry Hill: one central office at Malberg runs ~665 routes for
    all 19 schools, so none of this is per-school except which late-bus
    contractor serves a given middle/high school, resolved at read time
    from `late_bus_contractors` - see services/transportation.py).

    Kept fresh by `transportation.scan` on the normal 12h public-source
    cadence: the source pages are static policy/contact pages with no
    realtime delay feed (checked - the district's site has no alert
    module at all; delays go out as automated messages via Genesis),
    so there's nothing to gain from polling faster."""

    __tablename__ = "district_transportation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    district_id: Mapped[str] = mapped_column(String(36), ForeignKey("districts.id", ondelete="CASCADE"), nullable=False, unique=True)
    office_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    office_fax: Mapped[str | None] = mapped_column(String(50), nullable=True)
    office_hours: Mapped[str | None] = mapped_column(String(200), nullable=True)
    office_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # [{"name", "title", "email"}]
    contacts: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    delay_policy: Mapped[str | None] = mapped_column(String, nullable=True)
    late_bus_policy: Mapped[str | None] = mapped_column(String, nullable=True)
    # [{"name", "phone", "routes": {"BECK": ["BLR-1", ...], ...}}] - keyed
    # by the page's own all-caps school word, matched against School.name
    # / short_name at read time (late_bus_for_school).
    late_bus_contractors: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)
    bus_stop_change_procedure: Mapped[str | None] = mapped_column(String, nullable=True)
    bus_stop_change_deadline: Mapped[str | None] = mapped_column(String, nullable=True)
    bus_stop_change_form_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    lost_items_policy: Mapped[str | None] = mapped_column(String, nullable=True)
    main_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    late_bus_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    guidelines_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    lost_items_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    closing_info_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)


class CommunitySubmission(Base):
    """A flier/newsletter link submitted by anyone (no account needed) for
    an admin to review and, if it's real and useful, add to the tracked
    sources by hand via the existing /smore or school-documents flows.

    This is deliberately just an inbox, not automation - the whole point
    per the user's own framing is "so I can curate and validate the
    extractions" before anything from an anonymous submitter feeds the
    shared/public content pipeline. There's no asset-storage pattern
    elsewhere in this app (every other image/PDF is hotlinked from the
    source site's own CDN) - a submitted file has no such CDN, so its
    bytes are stored directly here (capped at 15MB in the router) rather
    than standing up a new object-storage integration for what should be
    low-volume community traffic.
    """

    __tablename__ = "community_submissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # "link" | "file"
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    submitter_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    submitter_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    school_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("schools.id", ondelete="SET NULL"), nullable=True)
    district_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("districts.id", ondelete="SET NULL"), nullable=True
    )
    # "pending" | "approved" | "rejected"
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    admin_notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class PageVisit(Base):
    """A daily tally of visits to a public page, broken down by where the
    visitor came from ("facebook", "direct", a referring host).

    Deliberately **aggregate only** - one counter row per (day, path,
    source), never a row per visitor. Nothing here can be traced back to a
    person, because nothing about a person is recorded: no id, no IP, no
    hash, no user agent, no session. That's a real constraint, not an
    oversight - /chcomms promises readers there's no ad tracking here, and
    a per-visitor analytics table would quietly make that untrue.

    It exists alongside Faro RUM because RUM is client-side JavaScript:
    ad blockers and privacy browsers drop a meaningful share of it, which
    is fine for spotting performance trends and useless for "how many
    people actually read the post" - the number that gets quoted to the
    district. This counter is same-origin and cheap, so it survives where
    RUM doesn't.
    """

    __tablename__ = "page_visits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # YYYY-MM-DD in the district's own timezone, not UTC - a 9pm visit is
    # "that evening" to a Cherry Hill parent, not the next morning.
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(100), nullable=False)
    # "facebook" | "direct" | "google" | a referring hostname | "other"
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)

    __table_args__ = (UniqueConstraint("day", "path", "source", name="uq_page_visits_day_path_source"),)


class SurveyResponse(Base):
    """One family's answers to the district-communication survey (/survey).

    Public and unauthenticated by design - the whole point is hearing from
    parents who have no reason to make an account here. That leaves no
    logged-in identity to lean on for "is this a real person", so each row
    also carries lightweight provenance: when it arrived, the browser's
    user agent, and a *salted hash* of the sender's IP - never the address
    itself, which would be personal data under GDPR for no added benefit.
    The hash is one-way but stable, so a pile of responses can be shown to
    the district as genuinely distinct submissions rather than one person
    clicking submit two hundred times. PrivacyPage.tsx discloses exactly
    this, in these words - keep the two in sync.

    `share_consent` is the respondent's own call about how their words may
    be used: "anonymous" (default) strips their name from anything shown
    to the district, "named" lets it be attached. Their email is never
    shared either way - it's only there so they can be followed up with.
    """

    __tablename__ = "survey_responses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # School ids the respondent's children attend - a list, since plenty of
    # families span two or three schools, which is itself the problem this
    # whole project exists for.
    school_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # 1 (very frustrated) - 5 (works well). Nullable: skipping it is a
    # legitimate answer and better than forcing a number nobody meant.
    satisfaction: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Stable keys from the frontend's canonical list (SurveyPage.tsx), e.g.
    # "absence" / "bell_schedule" / "pta" - kept as given rather than a
    # lookup table, since the list is presentational and versioning it in
    # the database would buy nothing here.
    pain_points: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    missing_info: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    comments: Mapped[str | None] = mapped_column(String(5000), nullable=True)
    submitter_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    submitter_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # "anonymous" | "named"
    share_consent: Mapped[str] = mapped_column(String(20), default="anonymous", nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(400), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True, nullable=False)
    # "guardian_matched" | "invite_accepted"
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    student_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("students.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
