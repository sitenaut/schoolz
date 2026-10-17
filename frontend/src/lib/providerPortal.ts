import { apiFetch } from "../api";

/** The Localz provider portal (backend/routers/provider_portal.py, design in
 * docs/LOCALZ_DESIGN.md "Provider portal"). A provider's form lives in the
 * request until a reviewer approves it - nothing here is public before then.
 *
 * A confidential address is sent once and never comes back, not even to the
 * person who typed it (`has_private_address` only says one is on file). */

export type HoursRange = { open: string; close: string };
export type DayKey = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
export type HoursMode = "weekly" | "24_7" | "appointment" | "call";
export type Hours = { mode: HoursMode | null; weekly: Partial<Record<DayKey, HoursRange[]>>; note?: string | null; seasonal?: string | null };
export type ServiceEntry = { type: string | null; name: string | null; description: string | null };
export type WhoCanCome = {
  open_to_anyone: boolean;
  counties: string[];
  age_min: number | null;
  age_max: number | null;
  families_with_children: boolean;
  low_income: boolean;
  seniors: boolean;
  note: string | null;
};
export type CostKind = "free" | "sliding" | "fee";
export type AddressKind = "public" | "confidential" | "service_area";

export type Submission = {
  organization_name: string | null;
  services: ServiceEntry[];
  address_kind: AddressKind | null;
  address: string | null;
  city: string | null;
  postal_code: string | null;
  service_area_counties: string[];
  hours: Hours;
  phone: string | null;
  who: WhoCanCome;
  cost: { kind: CostKind | null; amount: string | null };
  documents: string[];
  languages: string[];
  accessibility: string | null;
  website: string | null;
  email: string | null;
  access: "walk_in" | "appointment" | "both" | null;
  how_to_apply: string | null;
  public_contact_role: string | null;
  what_you_provide?: string | null;
  town?: string | null;
};

export type ListingBrief = {
  id: string;
  name: string;
  organization_name: string | null;
  city: string | null;
  address: string | null;
  phone: string | null;
  source: string;
  status: string;
  location_confidential: boolean;
};

export type Completeness = { missing_core: string[]; missing_optional: string[]; percent: number };

export type RequestStatus = "draft" | "submitted" | "in_review" | "approved" | "changes_requested" | "rejected" | "withdrawn";

export type OnboardingRequest = {
  id: string;
  status: RequestStatus;
  origin: string;
  submission: Submission;
  has_private_address: boolean;
  contact_name: string | null;
  contact_phone: string | null;
  claimed_service: ListingBrief | null;
  completeness: Completeness;
  decision_note: string | null;
  reject_reason: string | null;
  fields_to_fix: string[];
  service_ids: string[];
  submitted_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ProviderType = { key: string; label: string; category: string; normally_free: boolean; confidential_hint: boolean };

export type MyListing = {
  id: string;
  name: string;
  organization_name: string | null;
  status: string;
  role: string;
  verified: boolean;
  description: string | null;
  phone: string | null;
  website: string | null;
  email: string | null;
  address_kind: AddressKind | null;
  address: string | null;
  city: string | null;
  postal_code: string | null;
  service_areas: string[];
  hours: Hours | null;
  hours_text: string | null;
  week_hours: { week_of: string; hours: Hours; text: string | null } | null;
  closure: { starts_on: string; ends_on: string; note: string | null } | null;
  alert: string | null;
  languages: string[];
  required_documents: string[];
  eligibility_text: string | null;
  fees: string | null;
  cost_kind: CostKind | null;
  types: string[];
  pending_changes: { id: string; fields: string[]; created_at: string }[];
};

export const DAYS: { key: DayKey; label: string }[] = [
  { key: "mon", label: "Monday" },
  { key: "tue", label: "Tuesday" },
  { key: "wed", label: "Wednesday" },
  { key: "thu", label: "Thursday" },
  { key: "fri", label: "Friday" },
  { key: "sat", label: "Saturday" },
  { key: "sun", label: "Sunday" },
];

export const emptyHours = (): Hours => ({ mode: null, weekly: {}, note: null, seasonal: null });

export const emptySubmission = (): Submission => ({
  organization_name: "",
  services: [{ type: null, name: "", description: "" }],
  address_kind: null,
  address: "",
  city: "",
  postal_code: null,
  service_area_counties: [],
  hours: emptyHours(),
  phone: "",
  who: { open_to_anyone: false, counties: [], age_min: null, age_max: null, families_with_children: false, low_income: false, seniors: false, note: null },
  cost: { kind: null, amount: null },
  documents: [],
  languages: [],
  accessibility: null,
  website: null,
  email: null,
  access: null,
  how_to_apply: null,
  public_contact_role: null,
});

/** Merge a stored submission over the defaults, so an older or partial one
 * (an "Ask to be listed" inquiry) still fills every control. */
export function withDefaults(sub: Partial<Submission> | null | undefined): Submission {
  const base = emptySubmission();
  const s = { ...base, ...(sub ?? {}) } as Submission;
  s.hours = { ...base.hours, ...(sub?.hours ?? {}) };
  s.who = { ...base.who, ...(sub?.who ?? {}) };
  s.cost = { ...base.cost, ...(sub?.cost ?? {}) };
  if (!s.services?.length) s.services = base.services;
  return s;
}

export const phoneDigits = (p: string | null | undefined) => {
  const d = (p ?? "").replace(/\D/g, "");
  return d.length === 11 && d.startsWith("1") ? d.slice(1) : d;
};
export const validPhone = (p: string | null | undefined) => phoneDigits(p).length === 10;
const filled = (v: string | null | undefined) => !!(v ?? "").trim();

export const CORE_ITEMS = ["organization_name", "services", "address", "hours", "phone", "who", "cost"] as const;
export const OPTIONAL_ITEMS = ["documents", "languages", "accessibility", "website", "email", "access", "how_to_apply"] as const;

/** Mirrors backend resources/portal.py `completeness()` - keep them in step.
 * The server's answer is the one that counts on submit. */
export function completeness(s: Submission, hasPrivateAddress: boolean): Completeness {
  const h = s.hours;
  const hoursDone =
    h.mode === "weekly" ? DAYS.some((d) => (h.weekly[d.key] ?? []).length > 0) : h.mode === "call" ? validPhone(s.phone) : h.mode === "24_7" || h.mode === "appointment";
  const w = s.who;
  const whoDone = w.open_to_anyone || w.counties.length > 0 || w.age_min != null || w.age_max != null || w.families_with_children || w.low_income || w.seniors || filled(w.note);
  const addressDone =
    s.address_kind === "public" ? filled(s.address) && filled(s.city) : s.address_kind ? hasPrivateAddress && s.service_area_counties.length > 0 : false;
  const done: Record<string, boolean> = {
    organization_name: filled(s.organization_name),
    services: s.services.length > 0 && s.services.every((x) => !!x.type && filled(x.name) && filled(x.description)),
    address: addressDone,
    hours: hoursDone,
    phone: validPhone(s.phone),
    who: whoDone,
    cost: s.cost.kind != null && (s.cost.kind !== "fee" || filled(s.cost.amount)),
    documents: s.documents.length > 0,
    languages: s.languages.length > 0,
    accessibility: filled(s.accessibility),
    website: filled(s.website),
    email: filled(s.email),
    access: s.access != null,
    how_to_apply: filled(s.how_to_apply),
  };
  const core = CORE_ITEMS.filter((k) => done[k]).length;
  const opt = OPTIONAL_ITEMS.filter((k) => done[k]).length;
  return {
    missing_core: CORE_ITEMS.filter((k) => !done[k]),
    missing_optional: OPTIONAL_ITEMS.filter((k) => !done[k]),
    percent: Math.round((100 * (2 * core + opt)) / (2 * CORE_ITEMS.length + OPTIONAL_ITEMS.length)),
  };
}

/** What each completeness item is called on screen (passed through t()). */
export const ITEM_LABELS: Record<string, string> = {
  organization_name: "Organization name",
  services: "What you provide",
  address: "Address",
  hours: "Hours",
  phone: "Phone",
  who: "Who can come",
  cost: "Cost",
  documents: "What to bring",
  languages: "Languages spoken",
  accessibility: "Accessibility",
  website: "Website",
  email: "Email",
  access: "Walk-in or appointment",
  how_to_apply: "How to get help",
};

export const STATUS_LABELS: Record<RequestStatus, string> = {
  draft: "Draft",
  submitted: "Submitted",
  in_review: "In review",
  approved: "Approved",
  changes_requested: "Changes requested",
  rejected: "Not approved",
  withdrawn: "Withdrawn",
};

export class PortalError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await apiFetch(path, init);
  if (!res.ok) {
    let message = "Something went wrong - please try again.";
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* not JSON */
    }
    throw new PortalError(message, res.status);
  }
  return (await res.json()) as T;
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export const fetchProviderTypes = () => call<ProviderType[]>("/provider-portal/types");
export const sendInquiry = (body: Record<string, unknown>) => call<{ ok: boolean }>("/provider-portal/inquiries", json("POST", body));
export const matchListings = (name: string) => call<ListingBrief[]>("/provider-portal/match", json("POST", { name }));
export const fetchMyRequests = () => call<OnboardingRequest[]>("/provider-portal/requests");
export const fetchMyRequest = (id: string) => call<OnboardingRequest>(`/provider-portal/requests/${encodeURIComponent(id)}`);
export type RequestBody = {
  submission: Submission;
  private_address?: string | null;
  contact_name?: string | null;
  contact_phone?: string | null;
  claimed_service_id?: string | null;
  bot_token?: string | null;
};
export const startRequest = (body: RequestBody) => call<OnboardingRequest>("/provider-portal/requests", json("POST", body));
export const saveRequest = (id: string, body: RequestBody) => call<OnboardingRequest>(`/provider-portal/requests/${encodeURIComponent(id)}`, json("PUT", body));
export const submitRequest = (id: string) => call<OnboardingRequest>(`/provider-portal/requests/${encodeURIComponent(id)}/submit`, { method: "POST" });
export const withdrawRequest = (id: string) => call<OnboardingRequest>(`/provider-portal/requests/${encodeURIComponent(id)}/withdraw`, { method: "POST" });
export const fetchMyListings = () => call<MyListing[]>("/provider-portal/listings");
export const updateListing = (id: string, body: Record<string, unknown>) =>
  call<{ applied: string[]; held: string[]; change_request_id: string | null }>(`/provider-portal/listings/${encodeURIComponent(id)}`, json("PATCH", body));
