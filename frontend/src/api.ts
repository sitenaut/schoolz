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

async function authHeader(): Promise<Record<string, string>> {
  if (IS_SUPABASE_AUTH && supabase) {
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    return token ? { Authorization: `Bearer ${token}` } : {};
  }
  const token = localStorage.getItem(LOCAL_TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = {
    "Content-Type": "application/json",
    ...(await authHeader()),
    ...(init.headers ?? {}),
  };
  return fetch(`${API_URL}${path}`, { ...init, headers });
}
