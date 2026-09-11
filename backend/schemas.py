from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    username_or_email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: str
    email: str
    username: str
    is_admin: bool
    auth_mode: str
    # "password" (local, or Supabase email+password) | "google" (Supabase
    # OAuth, no password to change) - the settings page uses this to decide
    # whether to show a change-password form at all.
    sign_in_method: str = "password"
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=64)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class DeleteAccountRequest(BaseModel):
    # Typed confirmation, always required - a destructive, irreversible
    # action shouldn't be one accidental click away.
    confirm: str
    # Local auth mode additionally re-verifies the password when the
    # account has one; Supabase-managed accounts can't be verified here.
    password: str | None = None


class StudentCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    student_id: str = Field(min_length=1, max_length=64)
    # A student attends exactly one school at a time - chosen from the
    # tracked schools list (GET /schools), not freely typed.
    school_id: str = Field(min_length=1)


class StudentOut(BaseModel):
    id: str
    first_name: str
    last_name: str
    student_id: str
    school_name: str | None
    school_id: str | None = None
    guardian_count: int
    linked_via: str
    matched_existing: bool = False

    model_config = {"from_attributes": True}


class InviteCreate(BaseModel):
    invitee_email: EmailStr


class InviteOut(BaseModel):
    id: str
    token: str
    accept_url: str
    invitee_email: str
    status: str
    expires_at: datetime


class InvitePreviewOut(BaseModel):
    student_first_name: str
    student_last_initial: str
    inviter_username: str
    status: str
    expires_at: datetime


class NotificationOut(BaseModel):
    id: str
    type: str
    message: str
    student_id: str | None
    created_at: datetime
    read_at: datetime | None

    model_config = {"from_attributes": True}


class GmailConnectionOut(BaseModel):
    google_email: str
    last_synced_at: datetime | None
    created_at: datetime


class EmailScannerCreate(BaseModel):
    google_email: str
    name: str = Field(min_length=1, max_length=200)
    from_contains: list[str] = Field(default_factory=list)
    subject_contains: list[str] = Field(default_factory=list)
    body_contains: list[str] = Field(default_factory=list)
    raw_query: str | None = None
    lookback_days: int = Field(default=30, ge=1, le=365)
    purpose: str = "school_email"
    # Dedicates this scanner to one school - lets any Smore link it finds be
    # deterministically attributed (and auto-scheduled) instead of landing
    # unlinked in the shared newsletter list.
    school_id: str | None = None
    cron_expr: str = "0 7 * * *"
    timezone: str = "America/New_York"
    enabled: bool = True


class EmailScannerUpdate(BaseModel):
    name: str | None = None
    from_contains: list[str] | None = None
    subject_contains: list[str] | None = None
    body_contains: list[str] | None = None
    raw_query: str | None = None
    lookback_days: int | None = Field(default=None, ge=1, le=365)
    school_id: str | None = None
    cron_expr: str | None = None
    timezone: str | None = None
    enabled: bool | None = None


class ScheduledJobOut(BaseModel):
    id: str
    kind: str
    name: str
    description: str | None = None
    cron_expr: str
    timezone: str
    params: dict = Field(default_factory=dict)
    enabled: bool
    last_run_at: datetime | None
    last_status: str | None
    last_error: str | None
    last_error_code: str | None
    last_duration_ms: int | None = None
    next_run_at: datetime | None
    created_at: datetime | None = None
    # What the job is *about*, resolved from its params so the jobs table
    # can say "Staff roster scan · Bret Harte" instead of showing a UUID -
    # only populated by the /scheduled-jobs list/detail endpoints.
    target_type: str | None = None
    target_label: str | None = None

    model_config = {"from_attributes": True}


class ScheduledJobCreate(BaseModel):
    kind: str
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    cron_expr: str = Field(min_length=1, max_length=100)
    timezone: str = "America/New_York"
    params: dict = Field(default_factory=dict)
    enabled: bool = True


class ScheduledJobUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    cron_expr: str | None = Field(default=None, min_length=1, max_length=100)
    timezone: str | None = None
    params: dict | None = None
    enabled: bool | None = None


class JobKindOut(BaseModel):
    kind: str
    default_name: str
    default_cron: str
    default_timezone: str
    description: str
    param_schema: dict | None = None


class JobRunSummaryOut(BaseModel):
    total: int
    by_status: dict[str, int]


class EmailScannerOut(BaseModel):
    id: str
    google_email: str
    name: str
    from_contains: list[str]
    subject_contains: list[str]
    body_contains: list[str]
    raw_query: str | None
    lookback_days: int
    purpose: str
    school_id: str | None
    enabled: bool
    created_at: datetime
    scheduled_job: ScheduledJobOut | None = None


class JobRunOut(BaseModel):
    id: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    error: str | None
    error_code: str | None
    error_stage: str | None
    log_excerpt: str | None
    triggered_by: str

    model_config = {"from_attributes": True}


class SmoreNewsletterCreate(BaseModel):
    url: str = Field(min_length=1, max_length=1000)
    label: str | None = Field(default=None, max_length=255)
    school_id: str | None = None
    # For a district-wide newsletter with no single school (e.g. "CHPS
    # Weekly") - ordinarily exactly one of school_id/district_id is set.
    district_id: str | None = None
    cron_expr: str = "0 8 * * 1"
    timezone: str = "America/New_York"
    enabled: bool = True


class SmoreNewsletterOut(BaseModel):
    id: str
    url: str
    label: str | None
    school_id: str | None
    district_id: str | None = None
    # Resolved display names - only populated by GET (list/create/update),
    # so the table can say "Bret Harte Elementary" without a client-side join.
    school_name: str | None = None
    district_name: str | None = None
    last_scanned_at: datetime | None
    latest_summary: str | None
    created_at: datetime
    scheduled_job: ScheduledJobOut | None = None


class SmoreNewsletterUpdate(BaseModel):
    school_id: str | None = None
    district_id: str | None = None
    label: str | None = None
    # Scanning is opt-in even for an auto-discovered newsletter (one the
    # school_email processor found a link to but never scheduled) - setting
    # this true creates the recurring smore.scan job if one doesn't exist yet.
    enabled: bool | None = None
    cron_expr: str | None = None
    timezone: str | None = None


_SCHOOL_TYPES = ("elementary", "middle", "high", "alternative", "other")


class IcsFeed(BaseModel):
    name: str
    url: str
    # e.g. ["elementary"] to restrict this feed's events to one or more
    # School.school_type values - omit/null for a district-wide feed.
    school_types: list[str] | None = None


class DistrictCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    website_url: str | None = None
    food_services_menu_url: str | None = None
    ics_feeds: list[IcsFeed] = Field(default_factory=list)
    marking_period_url: str | None = None
    preschool_locations_url: str | None = None
    preschool_team_url: str | None = None
    hs_rotation_url: str | None = None
    transportation_url: str | None = None


class DistrictUpdate(BaseModel):
    website_url: str | None = None
    food_services_menu_url: str | None = None
    ics_feeds: list[IcsFeed] | None = None
    marking_period_url: str | None = None
    preschool_locations_url: str | None = None
    preschool_team_url: str | None = None
    hs_rotation_url: str | None = None
    transportation_url: str | None = None


class DistrictOut(BaseModel):
    id: str
    name: str
    website_url: str | None
    food_services_menu_url: str | None
    ics_feeds: list[IcsFeed]
    marking_period_url: str | None
    preschool_locations_url: str | None
    preschool_team_url: str | None
    hs_rotation_url: str | None
    transportation_url: str | None
    created_at: datetime
    scheduled_job: ScheduledJobOut | None = None
    calendar_scan_job: ScheduledJobOut | None = None
    marking_period_job: ScheduledJobOut | None = None


class SchoolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    short_name: str | None = Field(default=None, max_length=100)
    district_id: str | None = None
    school_type: str | None = Field(default=None, pattern="|".join(_SCHOOL_TYPES))
    address: str | None = None
    main_phone: str | None = None
    website_url: str | None = None


class BellPeriodEntry(BaseModel):
    name: str = Field(min_length=1, max_length=10)  # "1", "L1", "6", ...
    start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")  # 24h "HH:MM", school-local, no date
    end: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


_BELL_PERIOD_VARIANTS = ("regular", "delayed_opening", "early_dismissal")


class SchoolUpdate(BaseModel):
    short_name: str | None = Field(default=None, max_length=100)
    district_id: str | None = None
    school_type: str | None = Field(default=None, pattern="|".join(_SCHOOL_TYPES))
    website_url: str | None = None
    start_time: str | None = Field(default=None, max_length=20)
    end_time: str | None = Field(default=None, max_length=20)
    early_dismissal_time: str | None = Field(default=None, max_length=20)
    delayed_opening_time: str | None = Field(default=None, max_length=20)
    athletics_url: str | None = Field(default=None, max_length=500)
    logo_url: str | None = Field(default=None, max_length=1000)
    # Lets an admin hand-enter or correct the per-period table behind the
    # "what period is it right now" chip (services/bell_schedule.py) - e.g.
    # a one-off half day or delayed start with different period times than
    # the school's usual early_dismissal/delayed_opening table. Keys are
    # restricted to the three variants classify_day() actually looks up;
    # an unknown key would just be silently ignored by current_period(),
    # which is worse than rejecting it outright here.
    bell_periods: dict[str, list[BellPeriodEntry]] | None = None

    @field_validator("bell_periods")
    @classmethod
    def _validate_bell_period_keys(cls, value: dict[str, list[BellPeriodEntry]] | None) -> dict[str, list[BellPeriodEntry]] | None:
        if value is None:
            return value
        unknown = set(value) - set(_BELL_PERIOD_VARIANTS)
        if unknown:
            raise ValueError(f"bell_periods keys must be one of {_BELL_PERIOD_VARIANTS}, got {sorted(unknown)}")
        return value


class SchoolOut(BaseModel):
    id: str
    slug: str
    name: str
    short_name: str | None
    district_id: str | None
    school_type: str | None
    address: str | None
    main_phone: str | None
    website_url: str | None
    absence_method: str | None
    absence_emails: list[str]
    absence_phone: str | None
    absence_portal_name: str | None
    absence_portal_url: str | None
    absence_instructions: str | None
    start_time: str | None
    end_time: str | None
    early_dismissal_time: str | None
    delayed_opening_time: str | None
    athletics_url: str | None
    logo_url: str | None
    bell_periods: dict[str, list[BellPeriodEntry]] | None
    created_at: datetime

    model_config = {"from_attributes": True}


class StaffMemberOut(BaseModel):
    id: str
    full_name: str
    title: str | None
    role: str | None
    department: str | None
    email: str | None
    phone: str | None
    last_synced_at: datetime

    model_config = {"from_attributes": True}


class SaccProgramOut(BaseModel):
    am_hours: str | None
    pm_hours: str | None
    site_phone: str | None
    absence_phone: str | None
    absence_form_url: str | None
    late_pickup_policy: str | None
    pickup_change_procedure: str | None
    closures_notes: str | None
    handbook_url: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class SchoolDocumentOut(BaseModel):
    id: str
    doc_type: str
    title: str
    url: str
    academic_year: str | None
    source: str
    discovered_at: datetime
    is_current: bool

    model_config = {"from_attributes": True}


class LunchMenuItemOut(BaseModel):
    id: str
    menu_date: datetime
    description: str
    notes: str | None

    model_config = {"from_attributes": True}


class LunchMenuOut(BaseModel):
    id: str
    school_type: str | None
    meal_type: str
    period_label: str
    source_pdf_url: str
    parsed_at: datetime
    items: list[LunchMenuItemOut]


class SchoolContentItemOut(BaseModel):
    id: str
    scope: str
    # Display label for the scope badge: the school's short_name (for
    # scope="school") - not populated by every endpoint (redundant on a
    # single school's own page, only set by /calendar which spans schools).
    school_name: str | None = None
    # Set only on scope="district" items that don't apply district-wide -
    # currently just the "Day N" rotation markers (elementary via the ICS
    # feed, high school via the rotation PDF, often both landing on the
    # same date with different values). Without this the calendar has no
    # way to say which one is which - "Day 2" and "Day 3" on the same day
    # read as a contradiction instead of two different school tiers.
    applies_to_school_types: list[str] | None = None
    category: str
    title: str
    description: str | None
    start_date: datetime | None
    end_date: datetime | None
    is_all_day: bool
    link_url: str | None
    person_name: str | None
    person_title: str | None
    staff_member_id: str | None
    source_excerpt: str | None
    extracted_at: datetime
    is_current: bool

    model_config = {"from_attributes": True}


class TodayContactOut(BaseModel):
    role: str
    label: str
    name: str
    email: str | None
    phone: str | None


class TodayDayOut(BaseModel):
    """One school day on the week strip."""

    date: str  # YYYY-MM-DD, school-local
    weekday: str  # "Mon"
    status: str  # "open" | "closed" | "early_dismissal" | "unknown"
    status_label: str | None  # e.g. "Labor Day", "Out 1:15"
    rotation_day: str | None  # "Day 3" for elementary
    lunch: str | None
    items: list[SchoolContentItemOut]


class TodayLunchOut(BaseModel):
    today: str | None
    next_label: str | None  # "Tomorrow" / "Mon"
    next: str | None
    source_pdf_url: str | None


class TodaySaccOut(BaseModel):
    am_hours: str | None
    pm_hours: str | None
    site_phone: str | None
    absence_form_url: str | None
    absence_phone: str | None


class TransportationContactOut(BaseModel):
    name: str
    title: str
    email: str | None


class LateBusContractorOut(BaseModel):
    name: str
    phone: str
    routes: dict[str, list[str]]


class DistrictTransportationOut(BaseModel):
    office_phone: str | None
    office_fax: str | None
    office_hours: str | None
    office_address: str | None
    contacts: list[TransportationContactOut]
    delay_policy: str | None
    late_bus_policy: str | None
    late_bus_contractors: list[LateBusContractorOut]
    bus_stop_change_procedure: str | None
    bus_stop_change_deadline: str | None
    bus_stop_change_form_url: str | None
    lost_items_policy: str | None
    main_url: str | None
    late_bus_url: str | None
    guidelines_url: str | None
    lost_items_url: str | None
    closing_info_url: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class SchoolLateBusOut(BaseModel):
    """This school's late-bus contractor, resolved from the district's
    list - null for a school with no late bus (every elementary school)."""

    contractor: str
    phone: str
    routes: list[str]


class SchoolTransportationOut(BaseModel):
    district: DistrictTransportationOut
    late_bus: SchoolLateBusOut | None


class TodayTransportationOut(BaseModel):
    """Just enough for the Today card's action row - the office line and
    this school's late-bus line, if it has one."""

    office_phone: str | None
    late_bus_phone: str | None
    late_bus_contractor: str | None


class CurrentPeriodOut(BaseModel):
    """Which numbered period is happening right now, computed live from
    the school's bell_periods table - not stored, recomputed on every
    request against the current clock time."""

    name: str
    start_label: str
    end_label: str
    minutes_in: int
    minutes_left: int
    next_name: str | None


class SchoolTodayOut(BaseModel):
    """Everything one Today-feed card needs, assembled server-side so the
    home page makes exactly one request per school."""

    school: SchoolOut
    date: str
    is_school_day: bool
    status: str
    status_label: str | None
    hours: str | None
    rotation_day: str | None
    current_period: CurrentPeriodOut | None
    transportation: TodayTransportationOut | None
    lunch: TodayLunchOut
    sacc: TodaySaccOut | None
    contacts: list[TodayContactOut]
    upcoming: list[SchoolContentItemOut]
    alerts: list[SchoolContentItemOut]
    week: list[TodayDayOut]


class SmoreBlockOut(BaseModel):
    id: str
    position: int
    block_type: str
    text_content: str | None
    image_url: str | None
    link_url: str | None
    pending_vision_extraction: bool
    vision_extracted_text: str | None
    first_seen_at: datetime

    model_config = {"from_attributes": True}


class SchoolEmailMessageOut(BaseModel):
    id: str
    scanner_id: str
    sender: str | None
    subject: str | None
    received_at: datetime | None
    body_text: str | None
    newsletter_links: list[dict]
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Admin config export/import - porting centrally-managed setup (districts,
# schools, Smore newsletters, SACC, and every recurring scan they imply)
# from one environment to another (typically local -> prod) without
# starting from scratch. Deliberately excludes anything personal (no
# users/students/guardian links/Gmail tokens) - only the shared, public,
# admin-owned configuration that GET /schools and GET /districts already
# expose to everyone. See backend/scripts/migrate_config.py.
# ---------------------------------------------------------------------------


class ExportSaccOut(BaseModel):
    am_hours: str | None
    pm_hours: str | None
    site_phone: str | None
    absence_phone: str | None
    absence_form_url: str | None
    late_pickup_policy: str | None
    pickup_change_procedure: str | None
    closures_notes: str | None
    handbook_url: str | None


class ExportSchoolOut(BaseModel):
    slug: str
    name: str
    short_name: str | None
    district_name: str | None  # relinked by name in the target environment, not by id
    school_type: str | None
    address: str | None
    main_phone: str | None
    website_url: str | None
    absence_method: str | None
    absence_emails: list[str]
    absence_phone: str | None
    absence_portal_name: str | None
    absence_portal_url: str | None
    absence_instructions: str | None
    start_time: str | None
    end_time: str | None
    early_dismissal_time: str | None
    delayed_opening_time: str | None
    athletics_url: str | None
    logo_url: str | None
    bell_periods: dict[str, list[BellPeriodEntry]] | None
    sacc: ExportSaccOut | None

    model_config = {"from_attributes": True}


class ExportDistrictOut(BaseModel):
    name: str
    website_url: str | None
    food_services_menu_url: str | None
    ics_feeds: list[IcsFeed]
    marking_period_url: str | None
    preschool_locations_url: str | None
    preschool_team_url: str | None
    hs_rotation_url: str | None
    transportation_url: str | None

    model_config = {"from_attributes": True}


class ExportSmoreOut(BaseModel):
    url: str
    label: str | None
    school_slug: str | None  # null for an unlinked/newly-discovered newsletter
    cron_expr: str
    timezone: str
    enabled: bool


class ConfigExport(BaseModel):
    exported_at: datetime
    source: str  # a human label for where this came from, e.g. "local" - informational only
    districts: list[ExportDistrictOut]
    schools: list[ExportSchoolOut]
    smore_newsletters: list[ExportSmoreOut]


class ConfigImportResult(BaseModel):
    districts_created: int
    districts_updated: int
    schools_created: int
    schools_updated: int
    smore_created: int
    smore_updated: int
    smore_skipped: list[str]  # urls that couldn't be linked to a school slug in this environment
    sacc_created: int
    sacc_updated: int
