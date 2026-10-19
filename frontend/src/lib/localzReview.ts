import { apiFetch } from "../api";
import { PortalError, type ListingBrief, type ListingUpdateResult, type MyListing, type OnboardingRequest, type Submission } from "./providerPortal";

/** The Localz review queue (backend/routers/admin_resources.py). Admin UI,
 * English only like the rest of /admin. */

export type QueueItem = {
  id: string;
  status: string;
  origin: string;
  organization_name: string | null;
  town: string | null;
  claim: boolean;
  percent: number;
  missing_core: string[];
  submitted_at: string | null;
  created_at: string;
};

export type Flag = { code: string; level: "ok" | "info" | "warn"; message: string };

export type LogEntry = {
  id: string;
  service_id: string | null;
  request_id: string | null;
  actor_email: string | null;
  actor_kind: string;
  action: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  note: string | null;
  reverted_at: string | null;
  revertible: boolean;
  created_at: string;
};

export type Review = OnboardingRequest & {
  contact_email: string | null;
  account_email: string | null;
  private_address: string | null;
  checklist: Record<string, boolean>;
  /** The claimed listing's source-published email, masked: the call is optional, they can confirm with a code. */
  verify_by_email?: string | null;
  duplicates: (ListingBrief & { reasons: string[] })[];
  flags: Flag[];
  log: LogEntry[];
  reviewed_at: string | null;
};

export type HeldChange = {
  id: string;
  service: ListingBrief | null;
  kind: "provider_edit" | "source_conflict";
  source: string | null;
  changes: Record<string, unknown>;
  before: Record<string, unknown>;
  has_private_address: boolean;
  private_address: string | null;
  requested_by: string | null;
  status: string;
  note: string | null;
  created_at: string;
};

/** A live listing a provider looks after (GET /admin/resources/listings). */
export type LiveListing = {
  id: string;
  name: string;
  organization_name: string | null;
  city: string | null;
  source: string;
  status: "active" | "inactive" | "hidden";
  last_assured_on: string | null;
  members: number;
  verified_members: number;
  pending_changes: number;
  updated_at: string;
};

/** The portal's own listing shape, plus what only a reviewer sees. */
export type AdminListing = MyListing & {
  source: string;
  can_delete: boolean;
  hidden_note: string | null;
  hidden_at: string | null;
};

export type Member = { id: string; email: string | null; role: string; verified_at: string | null; created_at: string };

export const CHECKLIST: { key: string; label: string; hint: string }[] = [
  { key: "exists", label: "The organization exists", hint: "Website, NJ 211 listing, IRS nonprofit lookup, a church or municipal listing, or a call." },
  { key: "connected", label: "I called the listed number and the submitter is connected to it", hint: "This verifies their account: their quick updates will publish without review." },
  { key: "core_complete", label: "Required core is complete and plausible", hint: "Hours make sense, the address is the right place, the kinds of help fit the description." },
  { key: "not_duplicate", label: "Not a duplicate", hint: "If it is, merge into the existing listing instead of approving a new one." },
  { key: "confidential_ok", label: "Confidential address handled", hint: "A confidential location is marked confidential and the public view shows no location. Tick if it isn't one." },
];

export const REJECT_REASONS: { key: string; label: string }[] = [
  { key: "not_a_resource", label: "Not a community resource" },
  { key: "could_not_verify", label: "Couldn't verify it" },
  { key: "duplicate", label: "Duplicate" },
  { key: "outside_area", label: "Outside the area we cover" },
  { key: "unsafe", label: "Looks unsafe or a scam" },
  { key: "other", label: "Other" },
];

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await apiFetch(path, init);
  if (res.status === 204) return undefined as T;
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
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

const post = (body: unknown = {}): RequestInit => ({ method: "POST", body: JSON.stringify(body) });
const put = (body: unknown): RequestInit => ({ method: "PUT", body: JSON.stringify(body) });
const base = "/admin/resources";

export const fetchQueue = (state: string) => call<QueueItem[]>(`${base}/onboarding?state=${encodeURIComponent(state)}`);
export const fetchCounts = () => call<{ onboarding: number; changes: number }>(`${base}/onboarding/count`);
export const fetchReview = (id: string) => call<Review>(`${base}/onboarding/${encodeURIComponent(id)}`);
export const editRequest = (id: string, submission: Submission, private_address?: string) =>
  call<Review>(`${base}/onboarding/${encodeURIComponent(id)}`, put({ submission, private_address }));
export const saveChecklist = (id: string, checklist: Record<string, boolean>) =>
  call<Review>(`${base}/onboarding/${encodeURIComponent(id)}/checklist`, put({ checklist }));
export const approveRequest = (id: string, checklist: Record<string, boolean>, note: string) =>
  call<Review>(`${base}/onboarding/${encodeURIComponent(id)}/approve`, post({ checklist, note }));
export const mergeRequest = (id: string, checklist: Record<string, boolean>, target_service_id: string, note: string) =>
  call<Review>(`${base}/onboarding/${encodeURIComponent(id)}/merge`, post({ checklist, target_service_id, note }));
export const requestChanges = (id: string, note: string, fields: string[]) =>
  call<Review>(`${base}/onboarding/${encodeURIComponent(id)}/request-changes`, post({ note, fields }));
export const rejectRequest = (id: string, reason: string, note: string) =>
  call<Review>(`${base}/onboarding/${encodeURIComponent(id)}/reject`, post({ reason, note }));
export const fetchChanges = (state: string) => call<HeldChange[]>(`${base}/changes?state=${encodeURIComponent(state)}`);
export const approveChange = (id: string, note = "") => call<HeldChange>(`${base}/changes/${encodeURIComponent(id)}/approve`, post({ note }));
export const rejectChange = (id: string, note = "") => call<HeldChange>(`${base}/changes/${encodeURIComponent(id)}/reject`, post({ note }));
export const fetchServiceLog = (serviceId: string) => call<LogEntry[]>(`${base}/services/${encodeURIComponent(serviceId)}/log`);
export const revertLog = (logId: string) => call<LogEntry>(`${base}/log/${encodeURIComponent(logId)}/revert`, post());
export const fetchMembers = (serviceId: string) => call<Member[]>(`${base}/services/${encodeURIComponent(serviceId)}/members`);
export const addMember = (serviceId: string, email: string, role: string) =>
  call<Member>(`${base}/services/${encodeURIComponent(serviceId)}/members`, post({ email, role }));
export const verifyMember = (membershipId: string) => call<Member>(`${base}/memberships/${encodeURIComponent(membershipId)}/verify`, post());
export const fetchLiveListings = (state: string, q: string) =>
  call<LiveListing[]>(`${base}/listings?${new URLSearchParams({ state, ...(q.trim() ? { q: q.trim() } : {}) })}`);
export const fetchLiveListing = (id: string) => call<AdminListing>(`${base}/listings/${encodeURIComponent(id)}`);
export const editLiveListing = (id: string, body: Record<string, unknown>) =>
  call<ListingUpdateResult>(`${base}/listings/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) });
export const hideListing = (id: string, note: string) => call<AdminListing>(`${base}/listings/${encodeURIComponent(id)}/hide`, post({ note }));
export const unhideListing = (id: string) => call<AdminListing>(`${base}/listings/${encodeURIComponent(id)}/unhide`, post());
export const deleteListing = (id: string) => call<void>(`${base}/listings/${encodeURIComponent(id)}`, { method: "DELETE" });
