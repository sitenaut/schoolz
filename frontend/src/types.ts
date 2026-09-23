export type SchoolContentItem = {
  id: string;
  scope: "school" | "district";
  school_name: string | null;
  applies_to_school_types: string[] | null;
  // Grad years this item is scoped to (null = whole school) - see
  // docs/HS_CLASS_PAGES_DESIGN.md. class_label is a display badge
  // ("Class of 2027"), populated only by endpoints that span classes
  // (the general calendar), same idea as school_name.
  applies_to_grad_years: number[] | null;
  class_label: string | null;
  category: string;
  title: string;
  description: string | null;
  start_date: string | null;
  end_date: string | null;
  is_all_day: boolean;
  link_url: string | null;
  person_name: string | null;
  person_title: string | null;
  staff_member_id: string | null;
  source_excerpt: string | null;
  extracted_at: string;
  is_current: boolean;
};

export type School = {
  id: string;
  slug: string;
  name: string;
  short_name: string | null;
  district_id: string | null;
  school_type: string | null;
  address: string | null;
  main_phone: string | null;
  website_url: string | null;
  absence_method: string | null;
  absence_emails: string[];
  absence_phone: string | null;
  absence_portal_name: string | null;
  absence_portal_url: string | null;
  absence_instructions: string | null;
  start_time: string | null;
  end_time: string | null;
  early_dismissal_time: string | null;
  delayed_opening_time: string | null;
  athletics_url: string | null;
  logo_url: string | null;
  bell_periods: Partial<Record<"regular" | "delayed_opening" | "early_dismissal", BellPeriod[]>> | null;
  created_at: string;
};

export type BellPeriod = { name: string; start: string; end: string };

export type StaffMini = { id: string; full_name: string; title: string | null; email: string | null };

export type SchoolClassYear = {
  id: string;
  school_id: string;
  grad_year: number;
  label: string;
  grade_level_principals: StaffMini[];
  advisors: StaffMini[];
  instagram_url: string | null;
  source_page_url: string | null;
  updated_at: string;
};

export type ClassPayment = {
  id: string;
  school_class_year_id: string;
  sequence: number;
  kind: "optional" | "official";
  label: string;
  amount_cents: number | null;
  window_opens_at: string | null;
  window_closes_at: string | null;
  methods: string[] | null;
  payschools_item_name: string | null;
  refundable_until: string | null;
  notes: string | null;
  // null for an anonymous visitor (nothing to tick); a bool for anyone
  // signed in - see ClassPaymentTick in the backend.
  ticked: boolean | null;
};

export type StaffMember = {
  id: string;
  full_name: string;
  title: string | null;
  role: string | null;
  department: string | null;
  email: string | null;
  phone: string | null;
};

export type DirectorySchool = {
  id: string;
  slug: string;
  name: string;
  short_name: string | null;
  school_type: string | null;
};

/** One *person* from the district-wide directory (GET /directory/staff).
 * The backend collapses the per-school staff rows by email, so this is a
 * human with every school they appear at - not one row per school. */
export type DirectoryStaff = StaffMember & {
  category: string;
  schools: DirectorySchool[];
  /** "District-wide · 10 preschools", "Bret Harte", "Bret Harte +2". */
  affiliation: string;
  is_district_wide: boolean;
};

export type DirectoryFacet = { key: string; label: string; count: number };

export type DirectoryPage = {
  total: number;
  limit: number;
  offset: number;
  items: DirectoryStaff[];
  categories: DirectoryFacet[];
};

export type SchoolDocument = {
  id: string;
  doc_type: string;
  title: string;
  url: string;
  academic_year: string | null;
  source: string;
  is_current: boolean;
};

export type SaccProgram = {
  am_hours: string | null;
  pm_hours: string | null;
  site_phone: string | null;
  absence_phone: string | null;
  absence_form_url: string | null;
  late_pickup_policy: string | null;
  pickup_change_procedure: string | null;
  closures_notes: string | null;
  handbook_url: string | null;
};

export type LunchMenuItem = { id: string; menu_date: string; description: string; notes: string | null };
export type LunchMenu = { id: string; period_label: string; source_pdf_url: string; items: LunchMenuItem[] };

export type TodayContact = { role: string; label: string; name: string; email: string | null; phone: string | null };

export type TodayDay = {
  date: string;
  weekday: string;
  status: "open" | "closed" | "early_dismissal" | "delayed" | "weekend" | "unknown";
  status_label: string | null;
  rotation_day: string | null;
  rotation_blocks?: string[] | null;
  long_blocks?: boolean;
  lunch: string | null;
  items: SchoolContentItem[];
};

export type KidSpecials = {
  student_id: string;
  first_name: string;
  today: string | null;
  next_label: string | null;
  next: string | null;
  by_date: Record<string, string>;
};

export type CurrentClass = {
  student_id: string;
  first_name: string;
  status: "in_class" | "passing_period";
  period_name: string | null;
  course_name: string | null;
  teacher: string | null;
  room: string | null;
  start_label: string | null;
  end_label: string | null;
  minutes_left: number | null;
  next_course_name: string | null;
  next_start_label: string | null;
  minutes_until_next: number | null;
};

export type DayBlock = { name: string; start_label: string; end_label: string };
export type NextRotation = { label: string; rotation_day: string; blocks: string[] | null; long_blocks: boolean };

export type TodayTransportation = { office_phone: string | null; late_bus_phone: string | null; late_bus_contractor: string | null };

export type TransportationContact = { name: string; title: string; email: string | null };
export type LateBusContractor = { name: string; phone: string; routes: Record<string, string[]> };
export type DistrictTransportation = {
  office_phone: string | null;
  office_fax: string | null;
  office_hours: string | null;
  office_address: string | null;
  contacts: TransportationContact[];
  delay_policy: string | null;
  late_bus_policy: string | null;
  late_bus_contractors: LateBusContractor[];
  bus_stop_change_procedure: string | null;
  bus_stop_change_deadline: string | null;
  bus_stop_change_form_url: string | null;
  lost_items_policy: string | null;
  main_url: string | null;
  late_bus_url: string | null;
  guidelines_url: string | null;
  lost_items_url: string | null;
  closing_info_url: string | null;
};
export type SchoolTransportation = {
  district: DistrictTransportation;
  late_bus: { contractor: string; phone: string; routes: string[] } | null;
};

export type CurrentPeriod = {
  name: string;
  start_label: string;
  end_label: string;
  minutes_in: number;
  minutes_left: number;
  next_name: string | null;
};

export type SchoolToday = {
  school: School;
  date: string;
  is_school_day: boolean;
  status: TodayDay["status"];
  status_label: string | null;
  hours: string | null;
  rotation_day: string | null;
  rotation_blocks?: string[] | null;
  long_blocks?: boolean;
  day_blocks?: DayBlock[] | null;
  next_rotation?: NextRotation | null;
  my_specials?: KidSpecials[];
  my_current_classes?: CurrentClass[];
  current_period: CurrentPeriod | null;
  transportation: TodayTransportation | null;
  lunch: { today: string | null; next_label: string | null; next: string | null; source_pdf_url: string | null };
  sacc: { am_hours: string | null; pm_hours: string | null; site_phone: string | null; absence_form_url: string | null; absence_phone: string | null } | null;
  contacts: TodayContact[];
  upcoming: SchoolContentItem[];
  alerts: SchoolContentItem[];
  week: TodayDay[];
};

export type ScheduledJob = {
  id: string;
  kind: string;
  name: string;
  description: string | null;
  cron_expr: string;
  timezone: string;
  params: Record<string, unknown>;
  enabled: boolean;
  run_once: boolean;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
  last_error_code: string | null;
  last_duration_ms: number | null;
  next_run_at: string | null;
  created_at: string | null;
  target_type: string | null;
  target_label: string | null;
};

export type JobRun = {
  id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  error: string | null;
  error_code: string | null;
  error_stage: string | null;
  log_excerpt: string | null;
  triggered_by: string;
  machine_id: string | null;
  trace_id: string | null;
  last_progress_at: string | null;
};

export type JobKind = {
  kind: string;
  default_name: string;
  default_cron: string;
  default_timezone: string;
  description: string;
  param_schema: JobParamSchema | null;
  default_params?: Record<string, unknown>;
};

export type JobParamSchema = {
  type?: string;
  description?: string;
  properties?: Record<string, JobParamSchema>;
  items?: JobParamSchema;
  required?: string[];
  default?: unknown;
  enum?: unknown[];
};

export type TestFetchSourceResult = {
  name: string;
  url: string | null;
  status: "ok" | "http_error" | "parse_error" | "misconfigured";
  event_count: number;
  sample_titles: string[];
  error: string | null;
  first_entry_fields: Record<string, string> | null;
  source_type: string | null;
};

export type TestFetchResult = { kind: string; sources: TestFetchSourceResult[] };

export type LocalEvent = {
  id: string;
  source: string;
  title: string;
  description: string | null;
  start_time: string;
  end_time: string | null;
  all_day: boolean;
  venue_name: string | null;
  venue_address: string | null;
  url: string | null;
  image_url: string | null;
  price_min: number | null;
  price_max: number | null;
  is_free: boolean | null;
  categories: string[];
};

export type LocalEventFacets = { categories: { value: string; count: number }[]; sources: { value: string; count: number }[] };

export type SmoreNewsletter = {
  id: string;
  url: string;
  label: string | null;
  school_id: string | null;
  district_id: string | null;
  school_name: string | null;
  district_name: string | null;
  last_scanned_at: string | null;
  latest_summary: string | null;
  created_at: string;
  scheduled_job: ScheduledJob | null;
};

export type SmoreBlock = {
  id: string;
  position: number;
  block_type: string;
  text_content: string | null;
  image_url: string | null;
  link_url: string | null;
  pending_vision_extraction: boolean;
  vision_extracted_text: string | null;
  first_seen_at: string;
};
