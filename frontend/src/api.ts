import { API_URL, IS_SUPABASE_AUTH } from "./authConfig";
import { supabase } from "./supabase";

const LOCAL_TOKEN_KEY = "schoolz_token";

export function setLocalToken(token: string) {
  localStorage.setItem(LOCAL_TOKEN_KEY, token);
}

export function clearLocalToken() {
  localStorage.removeItem(LOCAL_TOKEN_KEY);
}

export function getLocalToken(): string | null {
  return localStorage.getItem(LOCAL_TOKEN_KEY);
}

// The Supabase access token, kept here so authHeader() doesn't have to ask
// supabase-js for it on every single request.
//
// `undefined` means "not known yet" (nothing has told us about a session),
// `null` means "known: no session". The difference matters - only the
// first case is worth a getSession() call.
//
// Why cache at all: supabase-js serialises auth operations behind one
// internal lock, so a getSession() per request makes every in-flight
// request queue behind whatever else is holding it. Confirmed in prod RUM
// (2026-09-15): batches of /schools/*/today fetches stalling 25-42s and
// unblocking on the same millisecond, while the backend served each in
// under a second. AuthContext keeps this fresh from onAuthStateChange,
// which fires on sign-in, sign-out and every token refresh.
let cachedAccessToken: string | null | undefined = undefined;

export function setCachedAccessToken(token: string | null): void {
  cachedAccessToken = token;
}

/** Re-reads the session from supabase-js and updates the cache. Safe to
 * call from ordinary code, but never from inside an onAuthStateChange
 * callback - see the comment on that subscription in AuthContext. */
async function refreshCachedToken(): Promise<string | null> {
  if (!supabase) return null;
  try {
    const { data } = await supabase.auth.getSession();
    cachedAccessToken = data.session?.access_token ?? null;
    return cachedAccessToken;
  } catch {
    return null;
  }
}

async function authHeader(): Promise<Record<string, string>> {
  if (IS_SUPABASE_AUTH && supabase) {
    const token = cachedAccessToken === undefined ? await refreshCachedToken() : cachedAccessToken;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }
  const token = localStorage.getItem(LOCAL_TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Observed live during a real deploy (2026-09-13): the backend is briefly
// unreachable for ~15-20s while Fly swaps machines - not an error
// response, a connection failure/timeout, since nothing is listening yet.
// A visitor mid-browse during that window got a broken page instead of a
// slower one. One retry after a short pause absorbs exactly that.
//
// Retried only for GET (the default method, and every read in this app):
// a network failure or a 502/503/504 gives no reliable signal about
// whether the request was actually processed, so retrying anything
// non-idempotent (a survey POST, a PATCH saving a school's hours) could
// silently double it. Reads have no such risk.
const RETRY_DELAY_MS = 2000;

function isRetryableStatus(status: number): boolean {
  return status === 502 || status === 503 || status === 504;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  // Kept separate from `headers` because init.headers widens the spread to
  // a HeadersInit union, which isn't indexable by name.
  const auth = await authHeader();
  const headers = {
    "Content-Type": "application/json",
    ...auth,
    ...(init.headers ?? {}),
  };
  const method = (init.method ?? "GET").toUpperCase();
  const url = `${API_URL}${path}`;

  // A cached token can go stale where a per-request getSession() couldn't
  // (a tab asleep past the token's expiry, waking before supabase-js has
  // refreshed it). A 401 says the request was rejected before it was
  // processed, so re-reading the session and replaying it once is safe for
  // any method - unlike the 502/network retry below, which is GET-only.
  const retryOn401 = async (res: Response): Promise<Response> => {
    if (res.status !== 401 || !IS_SUPABASE_AUTH || !supabase) return res;
    const fresh = await refreshCachedToken();
    if (!fresh || auth.Authorization === `Bearer ${fresh}`) return res;
    return fetch(url, { ...init, headers: { ...headers, Authorization: `Bearer ${fresh}` } });
  };

  if (method !== "GET") {
    return retryOn401(await fetch(url, { ...init, headers }));
  }

  try {
    const res = await retryOn401(await fetch(url, { ...init, headers }));
    if (isRetryableStatus(res.status)) {
      await sleep(RETRY_DELAY_MS);
      return fetch(url, { ...init, headers });
    }
    return res;
  } catch {
    // A thrown error (not an HTTP error response) means the connection
    // itself failed - exactly what a mid-deploy visitor sees. Retry once;
    // if it fails again, let the caller's existing error handling take over.
    await sleep(RETRY_DELAY_MS);
    return fetch(url, { ...init, headers });
  }
}

/** Download a file from an authenticated endpoint.
 *
 * A plain `<a href="${API_URL}/...">` is a raw browser navigation, so it
 * carries no Authorization header at all - anything behind require_admin
 * answers 401 and the browser just renders {"detail":"Not authenticated"}.
 * Passing the token in the query string instead would leak it into server
 * logs and browser history, so the file is fetched through apiFetch and
 * handed to the browser as a short-lived object URL instead. */
export async function downloadFile(path: string, fallbackName: string): Promise<void> {
  const res = await apiFetch(path);
  if (!res.ok) {
    let msg = `Download failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") msg = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(msg);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = filenameFromDisposition(res.headers.get("content-disposition")) || fallbackName;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    // Give the click a tick to start before the URL stops resolving.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null;
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
  return match ? decodeURIComponent(match[1]) : null;
}
