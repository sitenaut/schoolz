import { AuthClient, type GoTrueClient } from "@supabase/auth-js";
import { IS_SUPABASE_AUTH, SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY } from "./authConfig";

// Same client as schoolz-web's src/supabase.ts, on purpose (see there for why
// it's auth-js alone and why these options): it reads the SAME localStorage
// key (`sb-<project ref>-auth-token`), so this app and the main one see one
// session without any hand-off. What this file exists to fix: the prototype
// used to read that key's raw JSON directly instead of going through the
// client, which meant it never refreshed an expired access token - only the
// main app's client did that, silently, whenever IT happened to load. Landing
// on /focus/ directly after the ~1hr access-token TTL elapsed read a stale
// token, the API 401'd, and the screen rendered as logged-out even though the
// session was fine. api.ts now calls getSession() through this client
// instead, which performs that same silent refresh here too.
function createAuthClient(url: string, key: string): GoTrueClient {
  return new AuthClient({
    url: new URL("auth/v1", url.endsWith("/") ? url : `${url}/`).href,
    headers: { Authorization: `Bearer ${key}`, apikey: key },
    storageKey: `sb-${new URL(url).hostname.split(".")[0]}-auth-token`,
  });
}

export const supabase: { auth: GoTrueClient } | null = IS_SUPABASE_AUTH
  ? { auth: createAuthClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY) }
  : null;
