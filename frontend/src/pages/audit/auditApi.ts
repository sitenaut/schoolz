import { apiFetch } from "../../api";

export type AuditStatus = "current" | "stale" | "failing" | "not_collecting" | "not_applicable";
export type Audience = "internal" | "district";

export type Counts = Record<AuditStatus, number> & { applicable: number; pct: number | null };

export type CellSummary = { status: AuditStatus; tag: string };

/** One school x data point. The internal-only fields are absent (not just
 * empty) in a district-audience response - the server never sends them. */
export type CellDetail = CellSummary & {
  key: string;
  why: string;
  next: string;
  last_good: string | null;
  last_label: string;
  collected_by: string;
  runs: string;
  stale_after: string;
  internal_only: boolean;
  why_district?: string;
  next_district?: string;
  error_code?: string | null;
  job_ids?: string[];
  edit?: "school" | "district" | "newsletters" | "scans" | null;
  not_published?: boolean;
};

export type DataPointMeta = {
  key: string;
  label: string;
  group: string;
  order: number;
  applies: string;
  runs: string;
  stale_after: string;
  by_hand: boolean;
  collected_by: string;
  counts?: Counts;
};

export type AuditSchool<C extends CellSummary = CellSummary> = {
  id: string;
  slug: string;
  name: string;
  short_name: string;
  kind: string | null;
  kind_label: string;
  district_id: string | null;
  district_name: string | null;
  counts: Counts;
  cells: Record<string, C>;
};

export type AuditGrid<C extends CellSummary = CellSummary> = {
  generated_at: string;
  audience: Audience;
  data_points: DataPointMeta[];
  districts: { id: string; name: string }[];
  schools: AuditSchool<C>[];
  counts: Counts;
};

export type SchoolAudit = { generated_at: string; audience: Audience; data_points: DataPointMeta[]; school: AuditSchool<CellDetail> };
export type DataPointsAudit = { generated_at: string; audience: Audience; school_count: number; data_points: (DataPointMeta & { counts: Counts })[] };

async function fail(res: Response, fallback: string): Promise<never> {
  let msg = fallback;
  try {
    const body = await res.json();
    if (typeof body.detail === "string") msg = body.detail;
  } catch {
    /* non-JSON error body */
  }
  throw new Error(msg);
}

function qs(params: Record<string, string | boolean | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "" && v !== false) q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export async function getAudit<C extends CellSummary = CellSummary>(opts: { districtId?: string; audience?: Audience; detail?: boolean }): Promise<AuditGrid<C>> {
  const res = await apiFetch(`/admin/audit${qs({ district_id: opts.districtId, audience: opts.audience, detail: opts.detail })}`);
  if (!res.ok) return fail(res, "Could not load the audit");
  return res.json();
}

export async function listDistricts(): Promise<{ id: string; name: string }[]> {
  const res = await apiFetch("/districts");
  if (!res.ok) return fail(res, "Could not load districts");
  const rows: { id: string; name: string }[] = await res.json();
  return rows.map((d) => ({ id: d.id, name: d.name })).sort((a, b) => a.name.localeCompare(b.name));
}

export async function getSchoolAudit(schoolId: string, audience?: Audience): Promise<SchoolAudit> {
  const res = await apiFetch(`/admin/audit/schools/${encodeURIComponent(schoolId)}${qs({ audience })}`);
  if (!res.ok) return fail(res, "Could not load this school's audit");
  return res.json();
}

export async function getDataPoints(opts: { districtId?: string; audience?: Audience }): Promise<DataPointsAudit> {
  const res = await apiFetch(`/admin/audit/data-points${qs({ district_id: opts.districtId, audience: opts.audience })}`);
  if (!res.ok) return fail(res, "Could not load the data points");
  return res.json();
}

/** The CSV needs the auth header, so it's fetched and handed to the browser
 * as a blob rather than linked. */
export async function downloadCsv(opts: { districtId?: string; schoolId?: string; audience?: Audience; statuses?: AuditStatus[] }): Promise<void> {
  const res = await apiFetch(
    `/admin/audit/export.csv${qs({ district_id: opts.districtId, school_id: opts.schoolId, audience: opts.audience, statuses: opts.statuses?.join(",") })}`
  );
  if (!res.ok) return fail(res, "Could not download the CSV");
  const blob = await res.blob();
  const name = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? "data-audit.csv";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function runDataPoint(schoolId: string, key: string): Promise<{ started: { id: string; kind: string; name: string }[] }> {
  const res = await apiFetch(`/admin/audit/schools/${encodeURIComponent(schoolId)}/data-points/${key}/run`, { method: "POST" });
  if (!res.ok) return fail(res, "Could not start the scan");
  return res.json();
}

export async function runAllScans(schoolId: string): Promise<{ started: { id: string; kind: string; name: string }[] }> {
  const res = await apiFetch(`/admin/audit/schools/${encodeURIComponent(schoolId)}/run-all`, { method: "POST" });
  if (!res.ok) return fail(res, "Could not start the scans");
  return res.json();
}

export async function setNotPublished(schoolId: string, key: string, on: boolean, note?: string): Promise<void> {
  const path = `/admin/audit/schools/${encodeURIComponent(schoolId)}/data-points/${key}/not-published`;
  const res = on ? await apiFetch(path, { method: "PUT", body: JSON.stringify({ note: note || null }) }) : await apiFetch(path, { method: "DELETE" });
  if (!res.ok) return fail(res, "Could not save");
}
