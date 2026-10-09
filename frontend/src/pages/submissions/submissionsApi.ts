import { API_URL } from "../../authConfig";
import { apiFetch, downloadFile } from "../../api";

export type CommunitySubmission = {
  id: string;
  kind: "link" | "file";
  url: string | null;
  file_name: string | null;
  file_content_type: string | null;
  file_size: number | null;
  description: string | null;
  submitter_name: string | null;
  submitter_email: string | null;
  school_id: string | null;
  district_id: string | null;
  school_name: string | null;
  district_name: string | null;
  status: "pending" | "approved" | "rejected";
  admin_notes: string | null;
  reviewed_at: string | null;
  extracted_at: string | null;
  created_at: string;
};

export type SubmissionFlag = { code: string; text: string; hold: boolean; item_id: string | null };

/** A draft item read off (or typed in beside) a submission. It is live
 * exactly while content_item_id (school calendar) or local_event_id (/local)
 * is set. */
export type SubmissionItem = {
  id: string;
  origin: "model" | "manual";
  title: string;
  description: string | null;
  category: string;
  scope: "school" | "district" | "local";
  // Local wall-clock, "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SS" - never a UTC instant.
  start_local: string | null;
  end_local: string | null;
  stated_weekday: string | null;
  tentative: boolean;
  source_excerpt: string | null;
  // Local scope only.
  venue_name: string | null;
  venue_address: string | null;
  local_categories: string[];
  replaces_item_id: string | null;
  content_item_id: string | null;
  local_event_id: string | null;
  flags: SubmissionFlag[];
};

export type SubmissionReview = {
  submission: CommunitySubmission;
  items: SubmissionItem[];
  note_flags: string[];
  categories: string[];
  // Tags a reviewer can add to a local event.
  local_categories: string[];
};

export type SubmissionItemInput = Partial<
  Pick<SubmissionItem, "title" | "category" | "scope" | "tentative"> & {
    description: string;
    venue_name: string;
    venue_address: string;
    local_categories: string[];
    start_local: string;
    end_local: string;
    replaces_item_id: string;
  }
>;

async function fail(res: Response, fallback: string): Promise<never> {
  let msg = fallback;
  try {
    const body = await res.json();
    if (typeof body.detail === "string") msg = body.detail;
    else if (Array.isArray(body.detail)) msg = body.detail.map((d: { msg: string }) => d.msg).join("; ");
  } catch {
    /* non-JSON error body */
  }
  throw new Error(msg);
}

export type SubmissionInput = {
  url?: string;
  file?: File;
  description?: string;
  submitter_name?: string;
  submitter_email?: string;
  school_id?: string;
  district_id?: string;
};

// No auth on this one by design - the whole point is letting anyone
// contribute without an account. apiFetch always forces a JSON
// Content-Type header, which breaks a multipart body (the browser needs
// to set its own boundary), so this calls fetch() directly.
export async function submitContent(input: SubmissionInput): Promise<CommunitySubmission> {
  const form = new FormData();
  if (input.url) form.set("url", input.url);
  if (input.file) form.set("file", input.file);
  if (input.description) form.set("description", input.description);
  if (input.submitter_name) form.set("submitter_name", input.submitter_name);
  if (input.submitter_email) form.set("submitter_email", input.submitter_email);
  if (input.school_id) form.set("school_id", input.school_id);
  if (input.district_id) form.set("district_id", input.district_id);

  const res = await fetch(`${API_URL}/submissions`, { method: "POST", body: form });
  if (!res.ok) return fail(res, "Could not submit this - please try again");
  return res.json();
}

export async function listSubmissions(statusFilter?: string): Promise<CommunitySubmission[]> {
  const qs = statusFilter ? `?status_filter=${encodeURIComponent(statusFilter)}` : "";
  const res = await apiFetch(`/submissions${qs}`);
  if (!res.ok) return fail(res, "Could not load submissions");
  return res.json();
}

export async function updateSubmission(
  id: string,
  patch: { status?: string; admin_notes?: string; school_id?: string }
): Promise<CommunitySubmission> {
  const res = await apiFetch(`/submissions/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
  if (!res.ok) return fail(res, "Could not update this submission");
  return res.json();
}

export async function deleteSubmission(id: string): Promise<void> {
  const res = await apiFetch(`/submissions/${id}`, { method: "DELETE" });
  if (!res.ok) return fail(res, "Could not delete this submission");
}

// GET /submissions/{id}/file is admin-only, so it can't be linked to
// directly - a raw navigation carries no Authorization header. Fetch it
// through apiFetch and hand the bytes to the browser instead.
export async function downloadSubmissionFile(id: string, fileName?: string | null): Promise<void> {
  await downloadFile(`/submissions/${id}/file`, fileName || "submission");
}

async function review(path: string, init: RequestInit | undefined, fallback: string): Promise<SubmissionReview> {
  const res = await apiFetch(path, init);
  if (!res.ok) return fail(res, fallback);
  return res.json();
}

export const getReview = (id: string) => review(`/submissions/${id}`, undefined, "Could not load this submission");

export const readUpload = (id: string) =>
  review(`/submissions/${id}/extract`, { method: "POST" }, "Could not read this upload");

export const addItem = (id: string, input: SubmissionItemInput) =>
  review(`/submissions/${id}/items`, { method: "POST", body: JSON.stringify(input) }, "Could not add this item");

export const updateItem = (id: string, itemId: string, input: SubmissionItemInput) =>
  review(`/submissions/${id}/items/${itemId}`, { method: "PATCH", body: JSON.stringify(input) }, "Could not save this item");

export const deleteItem = (id: string, itemId: string) =>
  review(`/submissions/${id}/items/${itemId}`, { method: "DELETE" }, "Could not remove this item");

export const publishItems = (id: string, itemIds: string[]) =>
  review(`/submissions/${id}/publish`, { method: "POST", body: JSON.stringify({ item_ids: itemIds }) }, "Could not publish");

export const unpublishItem = (id: string, itemId: string) =>
  review(`/submissions/${id}/items/${itemId}/unpublish`, { method: "POST" }, "Could not unpublish this item");

export type TargetOption = { id: string; label: string };

export async function loadTargets(): Promise<{ schools: TargetOption[]; districts: TargetOption[] }> {
  const [schools, districts] = await Promise.all([
    fetch(`${API_URL}/schools`).then((r) => (r.ok ? r.json() : [])),
    fetch(`${API_URL}/districts`).then((r) => (r.ok ? r.json() : [])),
  ]);
  const byLabel = (a: TargetOption, b: TargetOption) => a.label.localeCompare(b.label);
  return {
    schools: schools.map((s: { id: string; name: string }) => ({ id: s.id, label: s.name })).sort(byLabel),
    districts: districts.map((d: { id: string; name: string }) => ({ id: d.id, label: d.name })).sort(byLabel),
  };
}
