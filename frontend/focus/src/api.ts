import { API_URL, IS_SUPABASE_AUTH } from "./authConfig";
import { supabase } from "./supabase";

// The same key schoolz-web's src/api.ts writes and reads. Sharing a session
// between the two front-ends depends on this: localStorage is scoped to the
// ORIGIN, not the path, so serving this app from /focus/ on the same host
// means a login over in schoolz-web is already here, with nothing passed
// between them.
const LOCAL_TOKEN_KEY = "schoolz_token";

// Cached the same way schoolz-web's api.ts caches it, and for the same
// reason: asking supabase-js for the session on every request would be one
// more place serialising behind its internal auth lock. `undefined` means
// "haven't asked yet", `null` means "asked: no session".
let cachedAccessToken: string | null | undefined = undefined;

/** Reads the session through supabase-js rather than parsing its storage
 * key by hand (see supabase.ts for why that mattered). getSession() reads
 * localStorage itself and - this is the point - performs a network refresh
 * first if the stored access token is expired or close to it, using the
 * stored refresh token. That's the behaviour this app was missing: without
 * it, a token that went stale between visits stayed stale until some OTHER
 * page (schoolz-web) happened to refresh it first. */
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
  if (IS_SUPABASE_AUTH) {
    const token = cachedAccessToken === undefined ? await refreshCachedToken() : cachedAccessToken;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }
  const token = localStorage.getItem(LOCAL_TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Whether a session plausibly exists, for the "not signed in" screen. This
 * is deliberately not a freshness check - it just asks whether supabase-js
 * (or, in local mode, a plain login) has ever stored anything here. An
 * expired-but-refreshable token still counts as "has a session"; apiFetch is
 * what makes it usable. */
export function hasSession(): boolean {
  if (IS_SUPABASE_AUTH) {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key && /^sb-.+-auth-token$/.test(key)) return true;
    }
    return false;
  }
  return Boolean(localStorage.getItem(LOCAL_TOKEN_KEY));
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const auth = await authHeader();
  const headers = {
    "Content-Type": "application/json",
    ...auth,
    ...(init.headers ?? {}),
  };
  const url = `${API_URL}${path}`;
  const res = await fetch(url, { ...init, headers });

  // A cached token can go stale where getSession() itself wouldn't catch
  // it (a tab asleep past expiry, waking with a cache from before this
  // request started). A 401 says the request was rejected before being
  // processed, so re-reading the session and replaying once is safe
  // regardless of method - mirrors schoolz-web's api.ts retryOn401.
  if (res.status === 401 && IS_SUPABASE_AUTH) {
    const fresh = await refreshCachedToken();
    if (fresh && auth.Authorization !== `Bearer ${fresh}`) {
      return fetch(url, { ...init, headers: { ...headers, Authorization: `Bearer ${fresh}` } });
    }
  }
  return res;
}

export async function apiGet<T>(path: string): Promise<T | null> {
  try {
    const res = await apiFetch(path);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}
