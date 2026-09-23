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
    # Set when this user is a student (Student.user_id points here) - the
    # frontend uses it to send a student straight to their own Kids view
    # instead of a guardian's list of children.
    student_profile_id: str | None = None

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
    school_type: str | None = None
    # High school only - see Student.grad_year in models.py. Drives which
    # class page (/schools/{slug}/class-of-{grad_year}) a guardian defaults
    # to. Editable by any linked guardian, same as the rest of this record.
    grad_year: int | None = None
    guardian_count: int
    linked_via: str
    matched_existing: bool = False

    model_config = {"from_attributes": True}


class StudentUpdate(BaseModel):
    grad_year: int | None = Field(default=None, ge=2000, le=2100)


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
    run_once: bool = False
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
    run_once: bool = False


class ScheduledJobUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    cron_expr: str | None = Field(default=None, min_length=1, max_length=100)
    timezone: str | None = None
    params: dict | None = None
    enabled: bool | None = None
    run_once: bool | None = None


class JobKindOut(BaseModel):
    kind: str
    default_name: str
    default_cron: str
    default_timezone: str
    description: str
    param_schema: dict | None = None
    default_params: dict = {}


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
    # A newsletter whose URL is replaced wholesale every issue (confirmed
    # common, not just the Cooper/Clara Barton exceptions) doesn't benefit
    # from a recurring cron - the URL is dead by the next fire. Checking
    # this scans the given URL exactly once and leaves the job disabled
    # afterward, rather than scheduling weekly re-checks of a stale link.
    run_once: bool = False


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
    run_once: bool | None = None


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
    # Short block labels for a high school ("1", "L1") and a middle
    # school's numbered periods ("1", "WIN") both fit comfortably; a
    # preschool's own daily routine tends to be a descriptive activity
    # name instead ("Outdoor Play", "Snack Time"), so this stays generous
    # rather than block-letter-sized.
    name: str = Field(min_length=1, max_length=40)
    start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")  # 24h "HH:MM", school-local, no date
    end: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


_BELL_PERIOD_VARIANTS = ("regular", "long_block", "delayed_opening", "early_dismissal")


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
    special_events_calendar_url: str | None = Field(default=None, max_length=500)
    # High-school class-pages sources - see School.activities_calendar_ics_url
    # etc in models.py. Opt-in like special_events_calendar_url; no admin
    # form exists for these either (set via PATCH, same as that field).
    activities_calendar_ics_url: str | None = Field(default=None, max_length=500)
    announcements_doc_url: str | None = Field(default=None, max_length=500)
    activities_site_url: str | None = Field(default=None, max_length=500)
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
    special_events_calendar_url: str | None
    activities_calendar_ics_url: str | None
    announcements_doc_url: str | None
    activities_site_url: str | None
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


class DirectorySchoolOut(BaseModel):
    id: str
    slug: str
    name: str
    short_name: str | None
    school_type: str | None


class DirectoryStaffOut(BaseModel):
    """One *person* in the district-wide directory, with every school they
    appear at. Deliberately not one row per staff_members row: the same
    human is stored once per school (see routers/directory.py), so a
    per-row result listed the district's preschool nurse ten times.
    `/schools/{id}/staff` is still per-school and unchanged."""

    id: str
    full_name: str
    title: str | None
    role: str | None
    department: str | None
    email: str | None
    phone: str | None
    category: str
    schools: list[DirectorySchoolOut]
    # Precomputed server-side so the rule lives in one testable place:
    # "District-wide · 10 preschools" when they cover a whole school type,
    # otherwise "Bret Harte" or "Bret Harte +2".
    affiliation: str
    is_district_wide: bool


class DirectoryFacetOut(BaseModel):
    key: str
    label: str
    count: int


class DirectoryPageOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[DirectoryStaffOut]
    categories: list[DirectoryFacetOut]


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
    # Grad years this item is scoped to (null = whole school) - see
    # SchoolContentItem.applies_to_grad_years in models.py.
    applies_to_grad_years: list[int] | None = None
    # Display label for a grad-year badge on a general calendar row
    # ("Class of 2027") - populated only by endpoints that span classes
    # (the general /calendar, a class page showing school-wide items too),
    # same idea as school_name above.
    class_label: str | None = None
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


class StaffMiniOut(BaseModel):
    """Just enough of a StaffMember to render "Dr. Kathy Lewis" on a class
    page - the full StaffMemberOut carries department/title/phone that a
    class page's advisor line doesn't need."""

    id: str
    full_name: str
    title: str | None
    email: str | None

    model_config = {"from_attributes": True}


class SchoolClassYearOut(BaseModel):
    id: str
    school_id: str
    grad_year: int
    label: str
    grade_level_principals: list[StaffMiniOut] = []
    advisors: list[StaffMiniOut] = []
    instagram_url: str | None
    source_page_url: str | None
    updated_at: datetime


class SchoolClassYearUpdate(BaseModel):
    """Manual correction of what services/hs_activities_site.py extracted -
    e.g. an ambiguous advisor-name match the auto-resolution deliberately
    left unset. Every field optional/patch-style, same convention as
    SchoolUpdate."""

    label: str | None = Field(default=None, max_length=50)
    instagram_url: str | None = Field(default=None, max_length=500)
    grade_level_principal_staff_ids: list[str] | None = None
    advisor_staff_ids: list[str] | None = None


class ClassPaymentOut(BaseModel):
    id: str
    school_class_year_id: str
    sequence: int
    kind: str
    label: str
    amount_cents: int | None
    window_opens_at: datetime | None
    window_closes_at: datetime | None
    methods: list[str] | None
    payschools_item_name: str | None
    refundable_until: datetime | None
    notes: str | None
    # Whether the CURRENT VIEWER has ticked this off (see ClassPaymentTick
    # in models.py) - null for an anonymous visitor, who has nothing to
    # tick. Per-account, not per-student: two guardians of the same kid
    # track their own payments independently.
    ticked: bool | None = None

    model_config = {"from_attributes": True}


class ClassPaymentCreate(BaseModel):
    sequence: int
    kind: str = Field(pattern="^(optional|official)$")
    label: str = Field(min_length=1, max_length=200)
    amount_cents: int | None = None
    window_opens_at: datetime | None = None
    window_closes_at: datetime | None = None
    methods: list[str] | None = None
    payschools_item_name: str | None = Field(default=None, max_length=200)
    refundable_until: datetime | None = None
    notes: str | None = Field(default=None, max_length=1000)


class ClassPaymentUpdate(BaseModel):
    sequence: int | None = None
    kind: str | None = Field(default=None, pattern="^(optional|official)$")
    label: str | None = Field(default=None, max_length=200)
    amount_cents: int | None = None
    window_opens_at: datetime | None = None
    window_closes_at: datetime | None = None
    methods: list[str] | None = None
    payschools_item_name: str | None = Field(default=None, max_length=200)
    refundable_until: datetime | None = None
    notes: str | None = Field(default=None, max_length=1000)
    # amount_cents/notes/etc above can't distinguish "leave unchanged" from
    # "clear it" for a nullable field via a plain PATCH body (both look
    # like the field being omitted vs. explicitly null - FastAPI/Pydantic
    # can tell those apart via `exclude_unset`, which the route uses).


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
    rotation_blocks: list[str] | None = None  # high school letters meeting that day, in clock order
    long_blocks: bool = False
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


class DayBlockOut(BaseModel):
    """One slot of today's lettered high-school timeline."""

    name: str  # "A".."H", or "L1"/"L2"
    start_label: str
    end_label: str


class NextRotationOut(BaseModel):
    label: str  # "Tomorrow" / "Mon"
    rotation_day: str
    blocks: list[str] | None
    long_blocks: bool


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
    rotation_blocks: list[str] | None = None
    long_blocks: bool = False
    day_blocks: list[DayBlockOut] | None = None
    next_rotation: NextRotationOut | None = None
    my_specials: list["TodayKidSpecialOut"] = []  # signed-in viewer's own kids at this school
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


class CommunitySubmissionOut(BaseModel):
    id: str
    kind: str
    url: str | None
    file_name: str | None
    file_content_type: str | None
    file_size: int | None
    description: str | None
    submitter_name: str | None
    submitter_email: str | None
    school_id: str | None
    district_id: str | None
    school_name: str | None = None
    district_name: str | None = None
    status: str
    admin_notes: str | None
    reviewed_at: datetime | None
    created_at: datetime


class CommunitySubmissionUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(pending|approved|rejected)$")
    admin_notes: str | None = None


class SurveyResponseCreate(BaseModel):
    """A public survey submission (/survey). Everything is optional
    individually - the router enforces that *something* substantive was
    actually answered, so an empty form can't be stored."""

    school_ids: list[str] = Field(default_factory=list, max_length=20)
    satisfaction: int | None = Field(default=None, ge=1, le=5)
    pain_points: list[str] = Field(default_factory=list, max_length=40)
    missing_info: str | None = Field(default=None, max_length=2000)
    comments: str | None = Field(default=None, max_length=5000)
    submitter_name: str | None = Field(default=None, max_length=200)
    submitter_email: str | None = Field(default=None, max_length=255)
    share_consent: str = Field(default="anonymous", pattern="^(anonymous|named)$")

    @field_validator("pain_points")
    @classmethod
    def _short_keys(cls, value: list[str]) -> list[str]:
        return [v.strip()[:80] for v in value if v and v.strip()]


class SurveyResponseOut(BaseModel):
    id: str
    school_ids: list[str]
    school_names: list[str] = []
    satisfaction: int | None
    pain_points: list[str]
    missing_info: str | None
    comments: str | None
    submitter_name: str | None
    submitter_email: str | None
    share_consent: str
    created_at: datetime


class SurveySummaryOut(BaseModel):
    """What the /survey page itself shows back ("N neighbors have answered")
    and what the admin view leads with. Deliberately carries no free text
    and no contact details - it's public."""

    total: int
    average_satisfaction: float | None
    top_pain_points: list[dict]


# ---- Bucket 3: Backpack Capture imports -----------------------------------


class Bucket3StudentOut(BaseModel):
    id: str
    first_name: str
    last_name: str
    student_id: str
    school_name: str | None
    # "guardian" | "student" - lets the UI hide guardian-only controls
    # (granting/revoking the student's own login) from the student.
    viewer_role: str


class Bucket3ImportRequest(BaseModel):
    """Mirrors the Backpack Capture extension's own export shape verbatim
    (see the sibling backpack-capture repo's background.js EXPORT_CAPTURES
    handler) so a guardian can upload the file exactly as downloaded, no
    reshaping needed."""

    exported_at: str | None = None
    captures: list[dict]


class Bucket3ImportResult(BaseModel):
    captures_processed: int
    captures_skipped_duplicate: int
    schedule_blocks_upserted: int
    work_items_upserted: int
    grade_entries_upserted: int = 0
    page_kinds_seen: int
    identity_mismatches: list[str] = []


class ChildScheduleBlockOut(BaseModel):
    source: str
    period: str
    schedule_date: str | None
    course_name: str
    teacher: str | None
    room: str | None
    term: str | None
    days: str | None
    time_start: str | None
    time_end: str | None

    model_config = {"from_attributes": True}


class ScheduleDayBlockOut(BaseModel):
    name: str  # block letter, or "L1"/"L2"
    start_label: str | None
    end_label: str | None
    course_name: str | None  # None = nothing on file for this block this term
    teacher: str | None
    room: str | None


class ScheduleDayOut(BaseModel):
    """One school day's classes, computed from the list view + rotation calendar."""

    date: str
    weekday: str
    status: str
    rotation_day: str | None
    long_blocks: bool
    timed: bool  # False when no bell table fits the day (block order only)
    blocks: list[ScheduleDayBlockOut]


class ChildScheduleOut(BaseModel):
    cycle_date: str | None
    cycle_label: str | None
    daily: list[ChildScheduleBlockOut]
    list_view: list[ChildScheduleBlockOut]
    days: list[ScheduleDayOut] = []


class ChildWorkItemOut(BaseModel):
    id: str
    external_uid: str
    course_name: str | None
    title: str
    item_type: str
    due_raw: str | None
    due_date: str | None
    status: str | None
    link: str | None
    teacher_name: str | None = None
    posted_raw: str | None = None
    posted_date: str | None = None
    first_seen_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True}


class ChildCourseGradeOut(BaseModel):
    course_code: str
    course_section: str
    course_name: str | None
    marking_period: str
    grade_percent: float | None
    last_grade_posted: str | None

    model_config = {"from_attributes": True}


class ChildGradeEntryOut(BaseModel):
    external_uid: str
    course_code: str
    course_section: str
    course_name: str | None
    marking_period: str | None
    weekday_date: str
    title: str
    description: str | None
    category: str | None
    score_earned: float | None
    score_possible: float | None
    percent: float | None
    status: str | None
    is_updated: bool

    model_config = {"from_attributes": True}


class ChildMarkingPeriodOut(BaseModel):
    label: str
    start_date: str
    end_date: str

    model_config = {"from_attributes": True}


class Bucket3GradesOut(BaseModel):
    course_grades: list[ChildCourseGradeOut]
    entries: list[ChildGradeEntryOut]
    marking_periods: list[ChildMarkingPeriodOut] = []
    # Best-effort comparison against schoolz's own district-sourced
    # marking-period scan (services/marking_period.py) - human-readable
    # strings, empty when no comparable district data exists yet or
    # everything matches.
    marking_period_discrepancies: list[str] = []


class AuditMatchedOut(BaseModel):
    """One assignment title-matched between Classroom and Genesis - the
    "in both" slice of the Venn diagram. Carries both sides' view so a
    guardian can see, e.g., Classroom says "due Tomorrow" while Genesis
    already has it graded."""

    title: str
    classroom: ChildWorkItemOut | None
    genesis: ChildGradeEntryOut | None


class Bucket3AuditOut(BaseModel):
    matched: list[AuditMatchedOut]
    # Filtered to the current marking period when one is known (a due date
    # from a marking period that already ended doesn't matter any more -
    # see ChildMarkingPeriod's docstring). classroom_only_all_time keeps
    # the unfiltered list so nothing is silently hidden if a guardian
    # wants to check something historical.
    classroom_only: list[ChildWorkItemOut]
    classroom_only_all_time: list[ChildWorkItemOut]
    genesis_only: list[ChildGradeEntryOut]
    current_marking_period: str | None = None
    counts: dict[str, int]


class CapturePageKindOut(BaseModel):
    pattern: str
    adapter: str
    description: str
    example_url: str
    count: int
    first_seen_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True}


class ContactMessageCreate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=255)
    message: str = Field(min_length=1, max_length=5000)
    # Honeypot: hidden from people by the form, filled in by form-spam bots.
    website: str | None = Field(default=None, max_length=500)


class ContactMessageOut(BaseModel):
    id: str
    name: str | None
    email: str | None
    message: str
    user_id: str | None
    read_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class StudentSpecialIn(BaseModel):
    rotation_day: int = Field(ge=1, le=12)
    subject: str = Field(min_length=1, max_length=100)
    teacher: str | None = Field(default=None, max_length=200)


class StudentSpecialOut(StudentSpecialIn):
    model_config = {"from_attributes": True}


class StudentSpecialsOut(BaseModel):
    rotation_days: list[int]  # the rotation days this child's school actually uses
    specials: list[StudentSpecialOut]


class TodayKidSpecialOut(BaseModel):
    student_id: str
    first_name: str
    today: str | None  # subject on today's rotation day, None when unknown or no school
    next_label: str | None  # "Tomorrow" / "Mon"
    next: str | None
    by_date: dict[str, str]  # YYYY-MM-DD -> subject, for the week strip


SchoolTodayOut.model_rebuild()
