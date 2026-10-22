import { AuthClient, type GoTrueClient } from "@supabase/auth-js";
import { IS_SUPABASE_AUTH, SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY } from "./authConfig";

// Only Supabase Auth, not supabase-js: nothing here uses its database,
// storage, realtime or functions clients, and they were ~120 KB of every
// visitor's first load. Built the way supabase-js 2.x's createClient builds
// its auth client (SupabaseClient._initSupabaseAuthClient), so sessions saved
// by the old client keep working:
// - storageKey `sb-<project ref>-auth-token` is supabase-js's default; auth-js
//   alone would use `supabase.auth.token` and sign every visitor out. Focus
//   (focus/src/supabase.ts) reads the same key, and lib/sessionRecovery.ts
//   finds it by that pattern.
// - auth-js replaces its default headers with these rather than merging, so
//   the API key goes in both, as supabase-js sends it.
// Everything else (persist, auto-refresh, session in URL, implicit flow) is
// auth-js's default and the same as supabase-js's.
export function createAuthClient(url: string, key: string): GoTrueClient {
  return new AuthClient({
    url: new URL("auth/v1", url.endsWith("/") ? url : `${url}/`).href,
    headers: { Authorization: `Bearer ${key}`, apikey: key },
    storageKey: `sb-${new URL(url).hostname.split(".")[0]}-auth-token`,
  });
}

export const supabase: { auth: GoTrueClient } | null = IS_SUPABASE_AUTH
  ? { auth: createAuthClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY) }
  : null;
