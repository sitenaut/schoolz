export const AUTH_MODE = (import.meta.env.VITE_AUTH_MODE ?? "local") as "local" | "supabase";
export const IS_SUPABASE_AUTH = AUTH_MODE === "supabase";

export const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL ?? "";
export const SUPABASE_PUBLISHABLE_KEY = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY ?? "";

export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
export const APP_VERSION = import.meta.env.VITE_APP_VERSION ?? "dev";
// Same-origin proxy path (frontend/nginx.conf) in prod, empty locally - RUM
// is off entirely when this isn't set (see src/lib/telemetry.ts).
export const FARO_URL = import.meta.env.VITE_FARO_URL ?? "";
