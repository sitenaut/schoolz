import { apiFetch } from "../api";
import { IS_SUPABASE_AUTH } from "../authConfig";
import { supabase } from "../supabase";

/** Account self-service. Every function is mode-aware: in prod the
 * password lives in Supabase Auth (the backend never sees it), locally
 * it's a bcrypt hash the backend owns - the same UI calls the right one. */

async function detail(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    return body.detail ?? fallback;
  } catch {
    return fallback;
  }
}

export async function updateProfile(username: string): Promise<void> {
  const res = await apiFetch("/auth/me", { method: "PATCH", body: JSON.stringify({ username }) });
  if (!res.ok) throw new Error(await detail(res, "Could not update profile"));
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  if (IS_SUPABASE_AUTH) {
    if (!supabase) throw new Error("Auth is not configured");
    const { error } = await supabase.auth.updateUser({ password: newPassword });
    if (error) throw new Error(error.message);
    return;
  }
  const res = await apiFetch("/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  if (!res.ok) throw new Error(await detail(res, "Could not change password"));
}

/** Returns a dev-only reset token in local auth mode (no mailer there);
 * in prod Supabase emails the link and this resolves to null. */
export async function sendPasswordReset(email: string): Promise<string | null> {
  if (IS_SUPABASE_AUTH) {
    if (!supabase) throw new Error("Auth is not configured");
    const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: `${window.location.origin}/reset-password` });
    if (error) throw new Error(error.message);
    return null;
  }
  const res = await apiFetch("/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) });
  if (!res.ok) throw new Error(await detail(res, "Could not start a password reset"));
  const body = await res.json();
  return body.reset_token ?? null;
}

/** Local: token from the reset link. Supabase: the recovery session the SDK
 * established from the emailed link is what authorizes updateUser. */
export async function completePasswordReset(token: string | null, newPassword: string): Promise<string | null> {
  if (IS_SUPABASE_AUTH) {
    if (!supabase) throw new Error("Auth is not configured");
    const { error } = await supabase.auth.updateUser({ password: newPassword });
    if (error) throw new Error(error.message);
    return null;
  }
  const res = await apiFetch("/auth/reset-password", { method: "POST", body: JSON.stringify({ token, new_password: newPassword }) });
  if (!res.ok) throw new Error(await detail(res, "This reset link is invalid or has expired"));
  return (await res.json()).access_token as string;
}

export async function deleteAccount(password: string | null): Promise<void> {
  const res = await apiFetch("/auth/me", { method: "DELETE", body: JSON.stringify({ confirm: "DELETE", password }) });
  if (!res.ok) throw new Error(await detail(res, "Could not delete account"));
}
