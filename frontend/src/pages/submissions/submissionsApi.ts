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
  created_at: string;
};

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
  patch: { status?: string; admin_notes?: string }
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
