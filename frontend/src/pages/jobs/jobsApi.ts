import { apiFetch } from "../../api";
import type { JobKind, JobRun, ScheduledJob, TestFetchResult } from "../../types";

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

export async function listJobs(): Promise<ScheduledJob[]> {
  const res = await apiFetch("/scheduled-jobs");
  if (!res.ok) return fail(res, "Could not load jobs");
  return res.json();
}

export async function getJob(id: string): Promise<ScheduledJob> {
  const res = await apiFetch(`/scheduled-jobs/${id}`);
  if (!res.ok) return fail(res, "Could not load job");
  return res.json();
}

export async function listKinds(): Promise<JobKind[]> {
  const res = await apiFetch("/scheduled-jobs/kinds");
  if (!res.ok) return fail(res, "Could not load job kinds");
  return res.json();
}

export async function listRuns(id: string, limit = 50): Promise<JobRun[]> {
  const res = await apiFetch(`/scheduled-jobs/${id}/runs?limit=${limit}`);
  if (!res.ok) return fail(res, "Could not load runs");
  return res.json();
}

export type JobPayload = {
  kind: string;
  name: string;
  description: string | null;
  cron_expr: string;
  timezone: string;
  params: Record<string, unknown>;
  enabled: boolean;
};

export async function createJob(payload: JobPayload): Promise<ScheduledJob> {
  const res = await apiFetch("/scheduled-jobs", { method: "POST", body: JSON.stringify(payload) });
  if (!res.ok) return fail(res, "Could not create job");
  return res.json();
}

export async function updateJob(id: string, patch: Partial<JobPayload>): Promise<ScheduledJob> {
  const res = await apiFetch(`/scheduled-jobs/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
  if (!res.ok) return fail(res, "Could not update job");
  return res.json();
}

export async function deleteJob(id: string): Promise<void> {
  const res = await apiFetch(`/scheduled-jobs/${id}`, { method: "DELETE" });
  if (!res.ok) return fail(res, "Could not delete job");
}

export async function runJobNow(id: string): Promise<void> {
  const res = await apiFetch(`/scheduled-jobs/${id}/run-now`, { method: "POST" });
  if (!res.ok) return fail(res, "Could not start the job");
}

/** Every option list the create/edit form might need to pick a target,
 * keyed by the param name the job kind's schema asks for. */
export async function loadTargetOptions(): Promise<Record<string, { id: string; label: string }[]>> {
  const [schools, districts, newsletters, scanners] = await Promise.all([
    apiFetch("/schools").then((r) => (r.ok ? r.json() : [])),
    apiFetch("/districts").then((r) => (r.ok ? r.json() : [])),
    apiFetch("/smore-newsletters").then((r) => (r.ok ? r.json() : [])),
    apiFetch("/email-scanners").then((r) => (r.ok ? r.json() : [])),
  ]);
  const byName = (a: { label: string }, b: { label: string }) => a.label.localeCompare(b.label);
  return {
    school_id: schools.map((s: { id: string; name: string }) => ({ id: s.id, label: s.name })).sort(byName),
    district_id: districts.map((d: { id: string; name: string }) => ({ id: d.id, label: d.name })).sort(byName),
    newsletter_id: newsletters.map((n: { id: string; label: string | null; url: string }) => ({ id: n.id, label: n.label || n.url })).sort(byName),
    scanner_id: scanners.map((s: { id: string; name: string }) => ({ id: s.id, label: s.name })).sort(byName),
  };
}

export const TARGET_LABELS: Record<string, string> = {
  school_id: "School",
  district_id: "District",
  newsletter_id: "Newsletter",
  scanner_id: "Email scanner",
};

/** Dry-run a job's fetch step - nothing is saved. Local events only. */
export async function testFetchJob(kind: string, params: Record<string, unknown>, verbose = false): Promise<TestFetchResult> {
  const res = await apiFetch("/scheduled-jobs/test-fetch", { method: "POST", body: JSON.stringify({ kind, params, verbose }) });
  if (!res.ok) return fail(res, "Test fetch failed");
  return res.json();
}

export type BillzImportResult = { created: ScheduledJob[]; skipped: { name: string; reason: string }[] };

export async function importBillzJobs(text: string): Promise<BillzImportResult> {
  const res = await apiFetch("/scheduled-jobs/import-billz", { method: "POST", body: JSON.stringify({ text }) });
  if (!res.ok) return fail(res, "Import failed");
  return res.json();
}
