import { API_URL } from "../authConfig";
import { apiFetch, authHeader } from "../api";
import { LOCALE } from "./i18n";

/** Neighborz (backend/routers/bills.py, docs/NEIGHBORZ_DESIGN.md): someone
 * posts a utility bill anonymously and a neighbor pays it straight to the
 * utility. We never touch money. The account number reaches only the one
 * giver holding the bill, and nothing typed crosses between the two. */

export type PublicBill = {
  id: string;
  utility: string;
  utility_name: string | null;
  amount_cents: number;
  due_date: string | null;
  shutoff_notice: boolean;
  county: string | null;
  avatar: string | null;
  state: "open" | "being_paid" | "paid";
};

export type BillsCatalog = {
  utilities: { key: string; name: string }[];
  avatars: string[];
  emojis: Record<string, string>;
  min_ask_cents: number;
  max_ask_cents: number;
  hold_hours: number;
};

export type Draft = {
  id: string;
  /** Set when this upload can't be posted. */
  refused: "not_a_bill" | "utility_not_supported" | null;
  utility: string | null;
  utility_name: string | null;
  account_number: string | null;
  service_zip: string | null;
  amount_due_cents: number | null;
  max_ask_cents: number;
  due_date: string | null;
  shutoff_notice: boolean;
  flags: string[];
};

export type PostedStatus = "held" | "available" | "claimed" | "reported" | "disputed" | "paid" | "withdrawn" | "rejected" | "expired";

export type Posted = {
  id: string;
  status: PostedStatus;
  utility_name: string | null;
  amount_cents: number | null;
  due_date: string | null;
  shutoff_notice: boolean;
  county: string | null;
  avatar: string | null;
  thanks: string | null;
  reject_reason: string | null;
  posted_at: string | null;
  closed_at: string | null;
  can_withdraw: boolean;
  can_answer: boolean;
  can_thank: boolean;
};

export type HoldStatus = "active" | "released" | "expired" | "withdrawn" | "reported" | "confirmed" | "disputed" | "struck";

export type Hold = {
  id: string;
  bill_id: string;
  status: HoldStatus;
  held_at: string;
  expires_at: string;
  utility_name: string | null;
  amount_cents: number | null;
  due_date: string | null;
  shutoff_notice: boolean;
  county: string | null;
  avatar: string | null;
  /** Only while the hold is active. */
  account_number: string | null;
  service_zip: string | null;
  pay_url: string | null;
  pay_phone: string | null;
  paid_cents: number | null;
  paid_on: string | null;
  confirmation_number: string | null;
  thanks: string | null;
};

export type Gift = {
  hold_id: string;
  status: HoldStatus;
  utility_name: string | null;
  amount_cents: number | null;
  paid_cents: number | null;
  paid_on: string | null;
  confirmation_number: string | null;
  avatar: string | null;
  county: string | null;
  thanks: string | null;
  held_at: string;
  expires_at: string;
};

export type Mine = {
  posted: Posted[];
  gifts: Gift[];
  /** Why this person can't hold a bill right now. */
  hold_blocker: "account_too_new" | "paused" | "holding_one" | "too_many_holds" | null;
};

export class BillsError extends Error {
  constructor(
    message: string,
    public code: string | null,
    public status: number,
  ) {
    super(message);
  }
}

async function failed(res: Response): Promise<BillsError> {
  try {
    const body = await res.json();
    return new BillsError(typeof body.detail === "string" ? body.detail : "Something went wrong", body.code ?? null, res.status);
  } catch {
    return new BillsError("Something went wrong", null, res.status);
  }
}

async function read<T>(res: Response): Promise<T> {
  if (!res.ok) throw await failed(res);
  return res.json() as Promise<T>;
}

const post = (path: string, body?: unknown) => apiFetch(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const fetchBills = (county?: string | null) =>
  apiFetch(`/bills${county ? `?county=${encodeURIComponent(county)}` : ""}`).then((r) => read<PublicBill[]>(r));
export const fetchBillsCatalog = () => apiFetch("/bills/catalog").then((r) => read<BillsCatalog>(r));
export const fetchMine = () => apiFetch("/bills/mine").then((r) => read<Mine>(r));

/** Raw fetch: apiFetch forces a JSON Content-Type, and multipart needs the
 * browser's own boundary. */
export async function uploadBill(file: File): Promise<Draft> {
  const form = new FormData();
  form.append("file", file);
  return read<Draft>(await fetch(`${API_URL}/bills/upload`, { method: "POST", body: form, headers: await authHeader() }));
}

export const postBill = (id: string, body: { account_number: string; service_zip: string; amount_cents: number; avatar: string; understood: boolean }) =>
  post(`/bills/${id}/post`, body).then((r) => read<Posted>(r));
export const withdrawBill = (id: string) => apiFetch(`/bills/${id}`, { method: "DELETE" }).then((r) => read<Posted>(r));
export const answerBill = (id: string, answer: "paid" | "not_yet") => post(`/bills/${id}/answer`, { answer }).then((r) => read<Posted>(r));
export const thankGiver = (id: string, emoji: string) => post(`/bills/${id}/thanks`, { emoji }).then((r) => read<Posted>(r));

export const holdBill = (id: string) => post(`/bills/${id}/hold`).then((r) => read<Hold>(r));
export const fetchHold = (id: string) => apiFetch(`/bills/holds/${id}`).then((r) => read<Hold>(r));
export const reportPaid = (id: string, body: { confirmation_number: string; paid_cents: number; paid_on: string }) =>
  post(`/bills/holds/${id}/paid`, body).then((r) => read<Hold>(r));
export const releaseHold = (id: string) => post(`/bills/holds/${id}/release`).then((r) => read<Hold>(r));

// Review (Admin -> Neighborz). English only, like the rest of the review side.

export type HeldBill = {
  id: string;
  flags: string[];
  flag_text: string[];
  read: Record<string, string | number | boolean | null>;
  account_number: string | null;
  service_zip: string | null;
  county: string | null;
  amount_cents: number | null;
  amount_due_cents: number | null;
  due_date: string | null;
  shutoff_notice: boolean;
  posted_at: string | null;
  has_image: boolean;
  requester_disputes: number;
};

export type DisputedBill = {
  bill_id: string;
  hold_id: string;
  amount_cents: number | null;
  paid_cents: number | null;
  paid_on: string | null;
  confirmation_number: string | null;
  reported_at: string | null;
  disputed_at: string | null;
  giver_strikes: number;
  giver_reveals_90d: number;
  requester_disputes: number;
};

export type ReviewQueue = { held: HeldBill[]; disputed: DisputedBill[]; paused: { giver_id: string; strikes: number }[] };

export const fetchReviewQueue = () => apiFetch("/admin/bills").then((r) => read<ReviewQueue>(r));
export const decideBill = (id: string, decision: "approve" | "reject" | "relist" | "close_paid", reason?: string) =>
  post(`/admin/bills/${id}/decision`, { decision, reason }).then((r) => read<{ status: string }>(r));
export const unpauseGiver = (userId: string) => post(`/admin/bills/givers/${userId}/unpause`).then((r) => read<{ strikes: number }>(r));

/** The held bill's image as an object URL (revoke it when done). Fetched
 * with the reviewer's token: a plain <img src> carries none. */
export async function billImageUrl(id: string): Promise<{ url: string; type: string }> {
  const res = await apiFetch(`/admin/bills/${id}/image`);
  if (!res.ok) throw await failed(res);
  const blob = await res.blob();
  return { url: URL.createObjectURL(blob), type: blob.type };
}

// Formatting

const money = new Intl.NumberFormat(LOCALE, { style: "currency", currency: "USD" });

export function dollars(cents: number | null | undefined): string {
  return cents == null ? "" : money.format(cents / 100);
}

/** "12.5" or "$12.50" typed by a person, in cents; null if it isn't money. */
export function parseDollars(text: string): number | null {
  const clean = text.replace(/[$,\s]/g, "");
  if (!/^\d+(\.\d{0,2})?$/.test(clean)) return null;
  return Math.round(parseFloat(clean) * 100);
}

/** A YYYY-MM-DD date as a short local date ("Nov 7"), no time-zone shift. */
export function shortDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(LOCALE, { month: "short", day: "numeric" });
}

/** Today in the visitor's own time zone, as YYYY-MM-DD. */
export function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}
