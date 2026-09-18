export const AUTH_MODE = (import.meta.env.VITE_AUTH_MODE ?? "local") as "local" | "supabase";
export const IS_SUPABASE_AUTH = AUTH_MODE === "supabase";

export const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL ?? "";
export const SUPABASE_PUBLISHABLE_KEY = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY ?? "";

export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
