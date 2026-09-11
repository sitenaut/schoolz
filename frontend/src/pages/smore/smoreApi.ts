import { apiFetch } from "../../api";
import type { SmoreBlock, SmoreNewsletter } from "../../types";

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

export async function listNewsletters(): Promise<SmoreNewsletter[]> {
  const res = await apiFetch("/smore-newsletters");
  if (!res.ok) return fail(res, "Could not load newsletters");
  return res.json();
}

export async function listBlocks(id: string): Promise<SmoreBlock[]> {
  const res = await apiFetch(`/smore-newsletters/${id}/blocks`);
  if (!res.ok) return fail(res, "Could not load content");
  return res.json();
}

export type NewsletterPayload = {
  url: string;
  label: string | null;
  school_id: string | null;
  district_id: string | null;
  cron_expr: string;
  timezone: string;
  enabled: boolean;
};

export async function createNewsletter(payload: NewsletterPayload): Promise<SmoreNewsletter> {
  const res = await apiFetch("/smore-newsletters", { method: "POST", body: JSON.stringify(payload) });
  if (!res.ok) return fail(res, "Could not add newsletter");
  return res.json();
}

export async function updateNewsletter(id: string, patch: Partial<NewsletterPayload>): Promise<SmoreNewsletter> {
  const res = await apiFetch(`/smore-newsletters/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
  if (!res.ok) return fail(res, "Could not update newsletter");
  return res.json();
}

export async function deleteNewsletter(id: string): Promise<void> {
  const res = await apiFetch(`/smore-newsletters/${id}`, { method: "DELETE" });
  if (!res.ok) return fail(res, "Could not delete newsletter");
}

export async function runNewsletterNow(id: string): Promise<void> {
  const res = await apiFetch(`/smore-newsletters/${id}/run-now`, { method: "POST" });
  if (!res.ok) return fail(res, "Could not start the scan");
}

export async function reextractAll(id: string): Promise<{ summary: string }> {
  const res = await apiFetch(`/smore-newsletters/${id}/reextract-all`, { method: "POST" });
  if (!res.ok) return fail(res, "Could not re-extract this newsletter");
  return res.json();
}

export type TargetOption = { id: string; label: string };

export async function loadTargets(): Promise<{ schools: TargetOption[]; districts: TargetOption[] }> {
  const [schools, districts] = await Promise.all([
    apiFetch("/schools").then((r) => (r.ok ? r.json() : [])),
    apiFetch("/districts").then((r) => (r.ok ? r.json() : [])),
  ]);
  const byLabel = (a: TargetOption, b: TargetOption) => a.label.localeCompare(b.label);
  return {
    schools: schools.map((s: { id: string; name: string }) => ({ id: s.id, label: s.name })).sort(byLabel),
    districts: districts.map((d: { id: string; name: string }) => ({ id: d.id, label: d.name })).sort(byLabel),
  };
}
