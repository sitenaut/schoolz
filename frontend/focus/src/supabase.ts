import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { IS_SUPABASE_AUTH, SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY } from "./authConfig";

// Same client shape as schoolz-web's src/supabase.ts, on purpose: it reads
// the SAME localStorage key (persistSession defaults to true, keyed by
// project ref), so this app and the main one see one session without any
// hand-off. What this file exists to fix: the prototype used to read that
// key's raw JSON directly instead of going through supabase-js, which meant
// it never refreshed an expired access token - only the main app's client
// did that, silently, whenever IT happened to load. Landing on /focus/
// directly after the ~1hr access-token TTL elapsed read a stale token, the
// API 401'd, and the screen rendered as logged-out even though the session
// was fine. api.ts now calls getSession() through this client instead,
// which performs that same silent refresh here too.
export const supabase: SupabaseClient | null = IS_SUPABASE_AUTH
  ? createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)
  : null;
