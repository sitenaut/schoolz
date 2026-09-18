export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const AUTH_MODE = import.meta.env.VITE_AUTH_MODE ?? "local";

// The same key schoolz-web's src/api.ts writes. Sharing a session between
// the two front-ends depends entirely on this: localStorage is scoped to
// the ORIGIN, not the path, so serving this app from /focus/ on the same
// host means the token written by a login over in schoolz-web is already
// here, with nothing passed between them.
const LOCAL_TOKEN_KEY = "schoolz_token";

/** supabase-js persists its session under "sb-<project-ref>-auth-token".
 *
 * PROTOTYPE ONLY. Reading another library's storage key is exactly the
 * kind of coupling that breaks on a supabase-js upgrade. It's here so the
 * prototype works in prod's auth mode without pulling in supabase-js and
 * duplicating AuthContext's deadlock fix - the real version should import
 * a shared auth package instead (see the README next to this file). */
function supabaseTokenFromStorage(): string | null {
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (!key || !/^sb-.+-auth-token$/.test(key)) continue;
    try {
      const raw = localStorage.getItem(key);
      if (!raw) continue;
      const parsed = JSON.parse(raw);
      const token = parsed?.access_token ?? parsed?.currentSession?.access_token;
      if (typeof token === "string" && token) return token;
    } catch {
      /* not JSON, or not the shape we expect - keep looking */
    }
  }
  return null;
}

function authToken(): string | null {
  if (AUTH_MODE === "supabase") return supabaseTokenFromStorage();
  return localStorage.getItem(LOCAL_TOKEN_KEY);
}

export function hasSession(): boolean {
  return Boolean(authToken());
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = authToken();
  return fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  });
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
