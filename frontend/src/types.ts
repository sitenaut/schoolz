export type SchoolContentItem = {
  id: string;
  scope: "school" | "district";
  school_name: string | null;
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
  created_at: string;
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
  lunch: string | null;
  items: SchoolContentItem[];
};

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
  current_period: CurrentPeriod | null;
  transportation: TodayTransportation | null;
  lunch: { today: string | null; next_label: string | null; next: string | null; source_pdf_url: string | null };
  sacc: { am_hours: string | null; pm_hours: string | null; site_phone: string | null; absence_form_url: string | null; absence_phone: string | null } | null;
  contacts: TodayContact[];
  upcoming: SchoolContentItem[];
  alerts: SchoolContentItem[];
  week: TodayDay[];
};
