import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { IS_SUPABASE_AUTH, SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY } from "./authConfig";

export const supabase: SupabaseClient | null = IS_SUPABASE_AUTH
  ? createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)
  : null;
